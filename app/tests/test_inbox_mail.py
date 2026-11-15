"""The queue's mails: inlasning.klar to the uploader and the daily notis.sammandrag, through the mail queue.

isort:skip_file
"""

import os
import tempfile
from unittest import mock

import herdbook  # noqa: E402
import utils.cache_invalidation as ci  # noqa: E402
import utils.database as db  # noqa: E402
import utils.inbox as inbox  # noqa: E402
import utils.mail as mail  # noqa: E402

from tests.inbox_fixtures import InboxTest  # noqa: E402
from tests.test_mail_queue import MailTest  # noqa: E402


class InboxMailTest(InboxTest, MailTest):
    def setUp(self):
        super().setUp()
        for user in (self.owner, self.manager, self.helper, self.mellerud_helper):  # synthetic addresses
            db.User.update(email=f"konto{user.id}@example.org").where(db.User.id == user.id).execute()
            user.email = f"konto{user.id}@example.org"

    def mails(self, kind):
        return list(db.MailMessage.select().where(db.MailMessage.kind == kind).order_by(db.MailMessage.id))

    def done_but_last(self):
        """An item of the owner's with one document left, held by the helper."""
        item = self.item(0)
        inbox.take(item, self.helper, over=False)
        document = item.documents.get()
        document.individual = db.Individual.get(db.Individual.number == "G1-2112")
        document.save()
        return item, document


class TestItemDoneMail(InboxMailTest):
    def test_queued_with_the_last_document_and_sent_to_the_uploader(self):
        item, document = self.done_but_last()
        inbox.update_document(item, document, self.helper, {"dismissed": True})
        (row,) = self.mails("inlasning.klar")
        self.assertEqual(
            (row.recipient_kind, row.recipient_id, row.params), ("user", self.owner.id, {"item_id": item.id})
        )
        self.assertEqual(
            (row.ref_type, row.ref_id, row.herd_id, row.category), ("inbox_item", item.id, self.herds[0].id, "T")
        )
        relay = self.relay()
        mail.send_pending()
        ((msg, _, to),) = relay.sent
        self.assertEqual(to, [self.owner.email])
        self.assertEqual(msg["Subject"], f"G1-2112 är inlagd i Stamboken (ärende {item.id})")
        self.assertIn("G1-2112", msg.get_content())
        self.assertIn("/stamboken/inskick", msg.get_content())

    def test_a_rolled_back_write_queues_nothing(self):
        item, document = self.done_but_last()
        with self.assertRaises(RuntimeError), db.DB_PROXY.atomic():
            inbox.update_document(inbox.lock_item(item.id), document, self.helper, {"dismissed": True})
            self.assertEqual(len(self.mails("inlasning.klar")), 1)  # queued in the write's transaction
            raise RuntimeError("the write failed")
        self.assertEqual(self.mails("inlasning.klar"), [])
        self.assertEqual(self.reload(item).state, "tagen")

    def test_a_reopened_item_stops_its_mail(self):
        item, document = self.done_but_last()
        inbox.update_document(item, document, self.helper, {"dismissed": True})
        inbox.change_state(self.reload(item), self.manager, "tagen")
        self.relay()
        mail.send_pending()
        self.assertEqual(self.mails("inlasning.klar")[0].status, "cancelled")


class TestDigest(InboxMailTest):
    def test_one_mail_per_user_with_new_unread_notices(self):
        first, second = self.item(0), self.item(2)  # Gotland: manager and helper; Mellerud: its helper
        inbox.set_mail_enabled(self.mellerud_helper, False)
        self.assertEqual(inbox.queue_digests(), 2)
        rows = self.mails("notis.sammandrag")
        self.assertEqual(sorted(r.recipient_id for r in rows), sorted([self.manager.id, self.helper.id]))
        self.assertEqual({r.category for r in rows}, {"N"})
        mailed = db.Notice.select().where(db.Notice.mailed_at.is_null(False))
        self.assertEqual(sorted(n.user_id for n in mailed), sorted([self.manager.id, self.helper.id]))

        self.assertEqual(inbox.queue_digests(), 0)  # nothing new since
        self.item(1)
        self.assertEqual(inbox.queue_digests(), 0)  # the same day: one digest a day

        relay = self.relay()
        mail.send_pending()
        bodies = {to[0]: msg for msg, _, to in relay.sent}
        body = bodies[self.helper.email].get_content()
        self.assertEqual(bodies[self.helper.email]["Subject"], "Olästa notiser i Stamboken")
        self.assertIn(f"Ny post i inläsningskön (ärende {first.id})", body)
        self.assertNotIn(f"ärende {second.id}", body)

    def test_read_notices_and_klar_notices_are_left_out(self):
        item = self.item(0)
        inbox.mark_read(self.manager)
        inbox.notify(self.helper, "klar", item, mailed=True)
        inbox.mark_read(self.helper)
        self.assertEqual(inbox.queue_digests(), 0)

    def test_notices_read_before_the_mail_goes_stop_it(self):
        self.item(0)
        inbox.queue_digests()
        inbox.mark_read(self.helper)
        self.relay()
        mail.send_pending()
        status = {r.recipient_id: r.status for r in self.mails("notis.sammandrag")}
        self.assertEqual(status, {self.helper.id: "cancelled", self.manager.id: "sent"})

    def test_a_rolled_back_digest_queues_nothing(self):
        self.item(0)
        with mock.patch.object(inbox, "enqueue_mail", side_effect=[1, RuntimeError("database gone")]):
            with self.assertRaises(RuntimeError):
                inbox.queue_digests()
        self.assertEqual(self.mails("notis.sammandrag"), [])
        self.assertFalse(db.Notice.select().where(db.Notice.mailed_at.is_null(False)).exists())

    def test_the_leader_queues_the_digest_at_seven(self):
        lock = os.path.join(tempfile.mkdtemp(), "scheduler.lock")
        with (
            mock.patch.object(herdbook, "SCHEDULER_LOCK_PATH", lock),
            mock.patch.object(ci, "init_redis"),
            mock.patch.object(ci, "start_pubsub_listener"),
            mock.patch.object(ci, "set_cache_and_functions"),
            mock.patch.object(herdbook, "_warm_genetics_in_background"),
            mock.patch.object(herdbook.gblogging, "create_genebank_logs"),
            mock.patch.object(herdbook.apscheduler.schedulers.background, "BackgroundScheduler") as scheduler_cls,
        ):
            herdbook.initialize_app()
        (job,) = [
            c for c in scheduler_cls.return_value.add_job.call_args_list if herdbook._queue_notice_digests in c.args
        ]
        self.assertEqual(job.args[1], "cron")
        self.assertEqual(
            {k: job.kwargs[k] for k in ("hour", "id", "max_instances")},
            {"hour": 7, "id": "notice_digest", "max_instances": 1},
        )

        self.item(0)
        with mock.patch.object(herdbook.genetics.ps, "_close_db_connection") as close:
            herdbook._queue_notice_digests()
        self.assertEqual(len(self.mails("notis.sammandrag")), 2)
        close.assert_called_once()
        with (
            mock.patch.object(herdbook, "queue_digests", side_effect=RuntimeError("database gone")),
            mock.patch.object(herdbook.genetics.ps, "_close_db_connection") as close,
            self.assertLogs(herdbook.APP.logger, "ERROR"),
        ):
            herdbook._queue_notice_digests()  # logged, never raised into the scheduler
        close.assert_called_once()
