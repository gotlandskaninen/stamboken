"""The incomplete item's mails: inlasning.ofullstandig when it is marked, inlasning.paminnelse after 11 months.

isort:skip_file
"""

from datetime import datetime, timedelta, timezone
from unittest import mock

import utils.database as db  # noqa: E402
import utils.inbox as inbox  # noqa: E402
import utils.inbox_purge as purge  # noqa: E402
import utils.mail as mail  # noqa: E402
import utils.settings as settings  # noqa: E402

from tests.test_inbox_mail import InboxMailTest  # noqa: E402

NOW = datetime(2027, 11, 14, 3, 45, tzinfo=timezone.utc)
MINUTE = timedelta(minutes=1)
NOTE = "Överlåtelsebeviset till G9001-2512 saknas."  # synthetic


class ReminderTest(InboxMailTest):
    def incomplete(self, received_at=None, **fields):
        """The owner's upload, marked incomplete by the helper with NOTE; returns the item and the marking event."""
        item = self.item(0)
        if fields:
            db.InboxItem.update(**fields).where(db.InboxItem.id == item.id).execute()
            item = self.reload(item)
        inbox.take(item, self.helper, over=False)
        inbox.change_state(item, self.helper, "ofullstandig", note=NOTE)
        if received_at:
            db.InboxItem.update(received_at=received_at).where(db.InboxItem.id == item.id).execute()
        return self.reload(item), item.events.where(db.InboxEvent.kind == "lage").get()

    def sent(self):
        """Sends what is queued: [(subject, recipients, body)]."""
        relay = self.relay()
        mail.send_pending()
        return [(msg["Subject"], to, msg.get_content()) for msg, _, to in relay.sent]


class TestIncompleteMail(ReminderTest):
    def test_queued_with_ids_only_and_the_note_read_when_it_goes(self):
        item, event = self.incomplete()
        (row,) = self.mails("inlasning.ofullstandig")
        self.assertEqual(
            (row.recipient_kind, row.recipient_id, row.params),
            ("user", self.owner.id, {"item_id": item.id, "event_id": event.id}),
        )
        self.assertEqual((row.ref_type, row.ref_id, row.created_by_id), ("inbox_item", item.id, self.helper.id))
        self.assertNotIn("saknas", str(db.MailMessage.select().where(db.MailMessage.id == row.id).tuples().get()))

        changed = {**event.detail, "note": "Pappersintyget saknas."}  # the note as it stands when the mail goes
        db.InboxEvent.update(detail=changed).where(db.InboxEvent.id == event.id).execute()
        ((subject, to, body),) = self.sent()
        self.assertEqual(subject, f"Något saknas i ditt inskick (ärende {item.id})")
        self.assertEqual(to, [self.owner.email])
        self.assertIn("Pappersintyget saknas.", body)
        self.assertNotIn(NOTE, body)
        self.assertIn(f"{item.received_at + inbox.months(12):%Y-%m-%d}", body)
        self.assertIn("/stamboken/inskick", body)

    def test_a_mailed_item_mails_the_address_it_came_from(self):
        item, _ = self.incomplete(kind="mail", sender_user=None, sender_address="avsandare@example.org")
        (row,) = self.mails("inlasning.ofullstandig")
        self.assertEqual((row.recipient_kind, row.recipient_id), ("inbox_sender", item.id))
        ((_, to, body),) = self.sent()
        self.assertEqual(to, ["avsandare@example.org"])
        self.assertNotIn("/stamboken/inskick", body)

    def test_stopped_when_the_item_moved_on(self):
        moved_on, _ = self.incomplete()
        inbox.change_state(moved_on, self.helper, "tagen")
        self.assertEqual(self.sent(), [])
        self.assertEqual([row.status for row in self.mails("inlasning.ofullstandig")], ["cancelled"])

    def test_an_erased_note_leaves_the_mail_without_it(self):
        erased, _ = self.incomplete()
        with db.DB_PROXY.atomic():
            purge.erase_document(inbox.lock_item(erased.id), erased.documents.get(), self.manager)
        ((subject, _, body),) = self.sent()
        self.assertEqual(subject, f"Något saknas i ditt inskick (ärende {erased.id})")
        self.assertNotIn(NOTE, body)
        self.assertIn("något saknas innan vi kan lägga in det.\n\nSvara", body)

    def test_a_rolled_back_marking_queues_nothing(self):
        item = self.item(0)
        inbox.take(item, self.helper, over=False)
        with self.assertRaises(RuntimeError), db.DB_PROXY.atomic():
            inbox.change_state(inbox.lock_item(item.id), self.helper, "ofullstandig", note=NOTE)
            raise RuntimeError("the write failed")
        self.assertEqual(self.mails("inlasning.ofullstandig"), [])


class TestReminder(ReminderTest):
    def test_once_11_months_after_the_item_came_in(self):
        limit = NOW - inbox.months(11)
        early, _ = self.incomplete(limit + MINUTE)
        due, event = self.incomplete(limit - MINUTE)
        self.sent()  # the mails from the marking

        self.assertEqual(purge.remind_incomplete(NOW), 1)
        self.assertEqual(purge.remind_incomplete(NOW), 0)  # once

        (row,) = self.mails("inlasning.paminnelse")
        self.assertEqual((row.recipient_kind, row.recipient_id), ("user", self.owner.id))
        self.assertEqual((row.params, row.ref_id), ({"item_id": due.id, "event_id": event.id}, due.id))
        ((subject, _, body),) = self.sent()
        self.assertEqual(subject, f"Påminnelse: något saknas i ditt inskick (ärende {due.id})")
        self.assertIn(NOTE, body)
        self.assertIn(f"{due.received_at + inbox.months(12):%Y-%m-%d}", body)
        self.assertNotIn(f"ärende {early.id}", subject)

    def test_the_nightly_job_reminds(self):
        item, _ = self.incomplete(NOW - inbox.months(11) - MINUTE)
        purge.run(NOW)
        self.assertEqual([row.params["item_id"] for row in self.mails("inlasning.paminnelse")], [item.id])

    def test_the_reminder_goes_also_when_the_originals_and_the_note_went_earlier(self):
        item, _ = self.incomplete(NOW - inbox.months(11) - MINUTE)
        self.sent()  # the mail from the marking
        with mock.patch.object(settings.inbox, "original_months", 6):
            purge.purge_originals(NOW - inbox.months(4))  # a night five months earlier
            self.assertNotIn(NOTE, str([e.detail for e in self.reload(item).events]))
            purge.run(NOW)
        ((subject, _, body),) = self.sent()
        self.assertEqual(subject, f"Påminnelse: något saknas i ditt inskick (ärende {item.id})")
        self.assertNotIn(NOTE, body)
        self.assertIn(f"{item.received_at + inbox.months(12):%Y-%m-%d}", body)
