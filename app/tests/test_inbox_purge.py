"""The intake queue's retention (utils/inbox_purge.py): each rule at its limit, the files with the rows, run twice.

Synthetic data only: the "photos" are a few bytes, the phone number is made up.

isort:skip_file
"""

import os
import shutil
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import herdbook  # noqa: E402
import utils.cache_invalidation as ci  # noqa: E402
import utils.database as db  # noqa: E402
import utils.inbox as inbox  # noqa: E402
import utils.inbox_purge as purge  # noqa: E402
import utils.mail as mail  # noqa: E402
import utils.settings as settings  # noqa: E402

from tests.ht_helpers import ht_row  # noqa: E402
from tests.inbox_fixtures import QUALITY, InboxTest  # noqa: E402

NOW = datetime(2027, 11, 14, 3, 45, tzinfo=timezone.utc)
MINUTE = timedelta(minutes=1)
PHONE = "0700-12 34 56"  # made up


class PurgeTest(InboxTest):
    def write(self, relative):
        path = os.path.join(self.folder, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as out:
            out.write(b"synthetic jpeg")
        return relative

    def exists(self, relative):
        return os.path.exists(os.path.join(self.folder, relative))

    def make(self, received_at=NOW, *, state="ny", closed_at=None, kind="upload", documents=1, doc_type="intyg"):
        """An item with a message holding PHONE, a question about it, and `documents` originals on disk."""
        stored = [(self.write(f"inkorg/original/{uuid.uuid4().hex}.jpg"), "0" * 64, QUALITY) for _ in range(documents)]
        item, _ = inbox.create_upload(self.owner, self.herds[0], f"Ring mig på {PHONE}", stored)
        inbox.log_event(item, self.manager, "fraga", text=f"Står det {PHONE}?")
        db.InboxItem.update(received_at=received_at, state=state, closed_at=closed_at, kind=kind).where(
            db.InboxItem.id == item.id
        ).execute()
        db.InboxDocument.update(doc_type=doc_type).where(db.InboxDocument.item == item.id).execute()
        return self.reload(item)

    def document(self, item):
        return db.InboxDocument.get(db.InboxDocument.item == item.id)

    def with_copy(self, item, number="G1-2112"):
        """The document saved as `number`'s paper certificate, with its masked copy on disk."""
        document = self.document(item)
        db.InboxDocument.update(
            public_path=self.write(f"inkorg/kopia/{document.id}.jpg"),
            individual=db.Individual.get(db.Individual.number == number),
            mask_rects=[],
            done_at=NOW,
        ).where(db.InboxDocument.id == document.id).execute()
        return db.InboxDocument.get_by_id(document.id)

    def text(self, item):
        """Everything the item says in words: its message and its events' details."""
        item = self.reload(item)
        return " ".join([item.message or ""] + [str(e.detail) for e in item.events])

    def snapshot(self):
        tables = (
            db.InboxItem,
            db.InboxDocument,
            db.InboxEvent,
            db.InboxOperation,
            db.Notice,
            db.GmailProcessed,
            db.MailMessage,
        )
        rows = [list(model.select().order_by(model._meta.primary_key).tuples()) for model in tables]
        files = sorted(os.path.join(root, name) for root, _, names in os.walk(self.folder) for name in names)
        return rows, files

    def assertIdempotent(self, rule):  # pylint: disable=invalid-name
        before = self.snapshot()
        rule(NOW)
        self.assertEqual(self.snapshot(), before)


class TestOriginals(PurgeTest):
    limit = NOW - inbox.months(12)

    def test_the_original_goes_after_the_months_with_the_text_and_the_copy_stays(self):
        kept, gone = self.make(self.limit + MINUTE), self.make(self.limit - MINUTE)
        kept_document, gone_document = self.with_copy(kept), self.with_copy(gone, "G1-2111")
        events = [(e.kind, e.user_id, e.at) for e in self.reload(gone).events.order_by(db.InboxEvent.id)]

        purge.purge_originals(NOW)

        self.assertEqual(self.document(kept).original_path, kept_document.original_path)
        self.assertTrue(self.exists(kept_document.original_path))
        self.assertIn(PHONE, self.text(kept))
        document = self.document(gone)
        self.assertIsNone(document.original_path)
        self.assertFalse(self.exists(gone_document.original_path))
        self.assertEqual(document.public_path, gone_document.public_path)
        self.assertTrue(self.exists(gone_document.public_path))  # the copy on the rabbit stays
        self.assertNotIn(PHONE, self.text(gone))
        self.assertIsNone(self.reload(gone).message)
        self.assertEqual(
            [(e.kind, e.user_id, e.at) for e in self.reload(gone).events.order_by(db.InboxEvent.id)], events
        )
        self.assertIdempotent(purge.purge_originals)

    def test_the_setting_gives_the_months(self):
        item = self.make(NOW - inbox.months(6) - MINUTE)
        purge.purge_originals(NOW)
        self.assertIsNotNone(self.document(item).original_path)
        with mock.patch.object(settings.inbox, "original_months", 6):
            purge.purge_originals(NOW)
        self.assertIsNone(self.document(item).original_path)

    def test_only_certificates_and_proofs_lose_their_original(self):
        for doc_type, goes in (("intyg", True), ("bevis", True), ("annat", False), ("arsblankett", False)):
            with self.subTest(doc_type):
                item = self.make(self.limit - MINUTE, doc_type=doc_type)
                path = self.document(item).original_path
                purge.purge_originals(NOW)
                self.assertEqual(self.document(item).original_path is None, goes)
                self.assertEqual(self.exists(path), not goes)
                self.assertNotIn(PHONE, self.text(item))  # the text goes with the item's year all the same

    def test_an_item_without_documents_keeps_its_text(self):
        item = self.make(self.limit - MINUTE, kind="meddelande", documents=0)
        purge.purge_originals(NOW)
        self.assertIn(PHONE, self.text(item))  # a message's text follows the message's own rule

    def test_waiting_for_the_reading_stops_with_the_original(self):
        item = self.make(self.limit - MINUTE)
        db.InboxDocument.update(interpretation_status="vantar").execute()
        purge.purge_originals(NOW)
        self.assertEqual(self.document(item).interpretation_status, "av")

    def test_the_queue_and_the_images_after_the_purge(self):
        item = self.make(self.limit - MINUTE, state="tagen")
        db.InboxItem.update(assigned_to=self.manager).execute()
        document = self.with_copy(item)
        purge.purge_originals(NOW)
        self.login("man")

        resp = self.client.get(f"/api/v2/inkorg/{item.id}")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        (shown,) = resp.get_json()["documents"]
        self.assertEqual((shown["has_original"], shown["has_copy"]), (False, True))
        self.assertIsNone(resp.get_json()["message"])
        self.assertNotIn(PHONE, resp.get_data(as_text=True))

        resp = self.client.get(f"/api/v2/inkorg/{item.id}/dokument/{document.id}/original")
        self.assertEqual((resp.status_code, resp.content_type), (404, "application/problem+json"))
        self.assertEqual(resp.get_json()["detail"], "Originalet är raderat.")
        self.assertFalse(self.reload(item).events.where(db.InboxEvent.kind == "original_visat").exists())

        resp = self.client.get("/api/v2/individual/G1-2112/paper-certificate")
        self.assertEqual((resp.status_code, resp.content_type), (200, "image/jpeg"))

        resp = self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{document.id}", json={"rotation": 90})
        self.assertEqual(resp.status_code, 409, resp.get_json())
        self.assertTrue(self.exists(document.public_path))


class TestSoldProofs(PurgeTest):
    def test_the_proofs_original_goes_when_the_rabbit_is_sold_on_and_not_before(self):
        rabbit = db.Individual.get(db.Individual.number == "G1-2111")
        g1, g2 = self.herds[0], self.herds[1]
        sale = ht_row("TRANSFER", herd=g2, from_herd=g1, individual=rabbit, herd_tracking_date=date(2027, 3, 1))
        item = self.make(NOW - timedelta(days=30), doc_type="bevis")
        db.InboxDocument.update(herd_tracking_id=sale.id, individual=rabbit, done_at=NOW).execute()
        path = self.document(item).original_path
        # None of these sells it on: before the sale, not a sale, undone.
        ht_row("TRANSFER", herd=g1, from_herd=g2, individual=rabbit, herd_tracking_date=date(2027, 2, 1))
        ht_row("ATTESTATION", herd=g2, from_herd=g2, individual=rabbit, herd_tracking_date=date(2027, 4, 1))
        undone = {"voided_at": NOW, "voided_by_user": self.manager, "voided_operation_id": uuid.uuid4()}
        ht_row(
            "TRANSFER",
            herd=g1,
            from_herd=g2,
            individual=rabbit,
            herd_tracking_date=date(2027, 5, 1),
            voided_reason="fel",
            **undone,
        )

        purge.purge_sold_proofs(NOW)
        self.assertEqual(self.document(item).original_path, path)
        self.assertTrue(self.exists(path))

        ht_row("TRANSFER", herd=g1, from_herd=g2, individual=rabbit, herd_tracking_date=date(2027, 6, 1))
        purge.purge_sold_proofs(NOW)
        self.assertIsNone(self.document(item).original_path)
        self.assertFalse(self.exists(path))
        self.assertEqual(self.document(item).herd_tracking_id, sale.id)
        self.assertIsNone(db.HerdTracking.get_by_id(sale.id).voided_at)  # the sale's row stays
        self.assertIn(PHONE, self.text(item))  # the item's text waits for the item's year
        self.assertIdempotent(purge.purge_sold_proofs)


class TestDeletedItems(PurgeTest):
    def queued_mail(self, item):
        """A mail to the item's sender, sent once, so the queue holds a trace of the address."""
        row_id = mail.enqueue_mail("inlasning.klar", "inbox_sender", item.id, {"item_id": item.id})
        db.MailMessage.update(address_hash="ab" * 32).where(db.MailMessage.id == row_id).execute()
        return row_id

    def assertDeleted(self, item, paths):  # pylint: disable=invalid-name
        self.assertIsNone(db.InboxItem.get_or_none(db.InboxItem.id == item.id))
        self.assertFalse(db.InboxEvent.select().where(db.InboxEvent.item == item.id).exists())
        self.assertFalse(any(self.exists(path) for path in paths))

    def test_junk_goes_30_days_after_it_closed_and_the_trace_stays(self):
        limit = NOW - timedelta(days=30)
        kept = self.make(state="skrap", closed_at=limit + MINUTE)
        gone = self.make(state="skrap", closed_at=limit - MINUTE)
        paths = [self.document(gone).original_path]
        trace = db.InboxOperation.create(operation_id=uuid.uuid4(), user=self.helper, document=self.document(gone))
        row_id = self.queued_mail(gone)

        self.assertEqual(purge.purge_junk(NOW), 1)

        self.assertDeleted(gone, paths)
        self.assertTrue(self.exists(self.document(kept).original_path))
        trace = db.InboxOperation.get_by_id(trace.id)  # "inlagd från foto av" outlives its item
        self.assertEqual((trace.document_id, trace.user_id), (None, self.helper.id))
        self.assertIsNone(db.MailMessage.get_by_id(row_id).address_hash)
        self.assertIdempotent(purge.purge_junk)

    def test_an_incomplete_item_goes_a_year_after_it_came_in(self):
        limit = NOW - inbox.months(12)
        kept = self.make(limit + MINUTE, state="ofullstandig")
        gone = self.make(limit - MINUTE, state="ofullstandig")
        paths = [self.document(gone).original_path]
        row_id = self.queued_mail(gone)

        self.assertEqual(purge.purge_incomplete(NOW), 1)

        self.assertDeleted(gone, paths)
        self.assertTrue(self.exists(self.document(kept).original_path))
        self.assertIsNone(db.MailMessage.get_by_id(row_id).address_hash)
        self.assertIdempotent(purge.purge_incomplete)

    def test_a_closed_message_goes_13_months_after_it_closed(self):
        limit = NOW - inbox.months(13)
        kept = self.make(state="klar", closed_at=limit + MINUTE, kind="meddelande", documents=0)
        gone = self.make(state="klar", closed_at=limit - MINUTE, kind="meddelande", documents=0)
        open_one = self.make(limit - MINUTE, state="tagen", kind="meddelande", documents=0)
        with_document = self.make(state="klar", closed_at=limit - MINUTE, kind="meddelande")
        attachments_skipped = self.make(state="klar", closed_at=limit - MINUTE, kind="mail", documents=0)

        self.assertEqual(purge.purge_messages(NOW), 1)

        self.assertDeleted(gone, [])
        for item in (kept, open_one, with_document, attachments_skipped):
            self.assertIsNotNone(db.InboxItem.get_or_none(db.InboxItem.id == item.id))
        self.assertIdempotent(purge.purge_messages)

    def test_an_item_that_put_something_on_a_rabbit_is_never_deleted(self):
        old = NOW - inbox.months(24)
        junk = self.make(state="skrap", closed_at=old)
        incomplete = self.make(old, state="ofullstandig")
        copy = self.with_copy(junk)
        db.InboxDocument.update(individual=db.Individual.get(db.Individual.number == "G1-2111")).where(
            db.InboxDocument.item == incomplete.id
        ).execute()
        purge.purge_junk(NOW)
        purge.purge_incomplete(NOW)
        for item in (junk, incomplete):
            self.assertIsNotNone(db.InboxItem.get_or_none(db.InboxItem.id == item.id))
        self.assertTrue(self.exists(copy.public_path))

    def test_the_copy_on_the_rabbit_survives_every_rule(self):
        old = NOW - inbox.months(36)
        copies = []
        for state in ("klar", "skrap", "ofullstandig", "tagen", "dubblett"):
            item = self.make(old, state=state, closed_at=old if state in inbox.CLOSED_STATES else None)
            copies.append(self.with_copy(item))
        db.InboxItem.update(state_changed_at=old).execute()

        purge.run(NOW)

        for copy in copies:
            self.assertEqual(db.InboxDocument.get_by_id(copy.id).public_path, copy.public_path)
            self.assertTrue(self.exists(copy.public_path))
            self.assertIsNone(db.InboxDocument.get_by_id(copy.id).original_path)  # the original did go


class TestLogs(PurgeTest):
    def test_who_opened_an_item_is_forgotten_after_13_months(self):
        limit = NOW - inbox.months(13)
        item = self.make()
        kept = db.InboxEvent.create(item=item, user=self.manager, kind="oppnad", at=limit + MINUTE)
        gone = db.InboxEvent.create(item=item, user=self.manager, kind="oppnad", at=limit - MINUTE)
        other = db.InboxEvent.create(item=item, user=self.manager, kind="tagen", at=limit - MINUTE)
        self.assertEqual(purge.purge_opened(NOW), 1)
        self.assertEqual(
            {e.id for e in db.InboxEvent.select().where(db.InboxEvent.id.in_([kept.id, gone.id, other.id]))},
            {kept.id, other.id},
        )
        self.assertIdempotent(purge.purge_opened)

    def test_the_gmail_readers_rows_go_after_60_days(self):
        limit = NOW - timedelta(days=60)
        db.GmailProcessed.create(gmail_message_id="kept", kind="ignored", at=limit + MINUTE)
        db.GmailProcessed.create(gmail_message_id="gone", kind="item", item=self.make(), at=limit - MINUTE)
        self.assertEqual(purge.purge_gmail_processed(NOW), 1)
        self.assertEqual([r.gmail_message_id for r in db.GmailProcessed.select()], ["kept"])
        self.assertIdempotent(purge.purge_gmail_processed)


class TestSenderAddress(PurgeTest):
    def test_the_nightly_job_drops_a_closed_items_address_also_with_the_gmail_job_off(self):
        limit = NOW - timedelta(days=30)
        kept = self.make(state="klar", closed_at=limit + MINUTE, kind="mail")
        gone = self.make(state="klar", closed_at=limit - MINUTE, kind="mail")
        rows = {}
        for item in (kept, gone):
            db.InboxItem.update(sender_address="avsandare@example.org").where(db.InboxItem.id == item.id).execute()
            rows[item.id] = mail.enqueue_mail("inlasning.klar", "inbox_sender", item.id, {"item_id": item.id})
            db.MailMessage.update(address_hash="cd" * 32).where(db.MailMessage.id == rows[item.id]).execute()
        self.assertEqual(settings.gmail.mode, "off")

        purge.run(NOW)

        self.assertEqual(self.reload(kept).sender_address, "avsandare@example.org")  # its mail is on its way
        self.assertIsNone(self.reload(gone).sender_address)
        self.assertIsNone(db.MailMessage.get_by_id(rows[gone.id]).address_hash)
        self.assertIsNotNone(db.MailMessage.get_by_id(rows[kept.id]).address_hash)


class TestSafety(PurgeTest):
    def test_a_path_outside_the_originals_folder_is_never_removed(self):
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        victim = os.path.join(outside, "keep.jpg")
        with open(victim, "wb") as out:
            out.write(b"not the queue's")
        named = [
            victim,
            os.path.relpath(victim, self.folder),
            "inkorg/original/../../../" + os.path.relpath(victim, os.path.dirname(self.folder)),
            self.write("inkorg/kopia/elsewhere.jpg"),
        ]
        items = [self.make(NOW - inbox.months(13)) for _ in named]
        for item, path in zip(items, named, strict=True):
            db.InboxDocument.update(original_path=path).where(db.InboxDocument.item == item.id).execute()

        with self.assertLogs(purge.logger, "WARNING") as logs:
            purge.purge_originals(NOW)

        self.assertTrue(os.path.exists(victim))
        self.assertTrue(self.exists("inkorg/kopia/elsewhere.jpg"))
        self.assertEqual(
            logs.output, ["WARNING:herdbook.inbox_purge:Kept 4 inbox files named outside the originals folder"]
        )


class TestJob(PurgeTest):
    def test_the_leader_runs_the_purge_at_night(self):
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
        (job,) = [c for c in scheduler_cls.return_value.add_job.call_args_list if herdbook._purge_inbox in c.args]
        self.assertEqual(job.args[1], "cron")
        self.assertEqual(
            {k: job.kwargs[k] for k in ("hour", "minute", "id", "max_instances")},
            {"hour": 3, "minute": 45, "id": "inbox_purge", "max_instances": 1},
        )

        gone = self.make(state="skrap", closed_at=datetime.now(timezone.utc) - timedelta(days=31))  # the job's clock
        with mock.patch.object(herdbook.genetics.ps, "_close_db_connection") as close:
            herdbook._purge_inbox()
        self.assertIsNone(db.InboxItem.get_or_none(db.InboxItem.id == gone.id))
        close.assert_called_once()

    def test_a_failing_rule_skips_none_of_the_others(self):
        gone = self.make(state="skrap", closed_at=NOW - timedelta(days=31))

        def broken(now):
            raise RuntimeError("database gone")

        with (
            mock.patch.object(purge, "RULES", (broken, purge.purge_junk)),
            self.assertLogs(purge.logger, "ERROR"),
        ):
            purge.run(NOW)
        self.assertIsNone(db.InboxItem.get_or_none(db.InboxItem.id == gone.id))
