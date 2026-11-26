#!/usr/bin/env python3
"""
Tests for the manager's "Skicka påminnelse", the status view's reminder and "Ej svarat", and Å5, the list of herds
without a report after the deadline (step 6, Task 2). Synthetic herds, rabbits and addresses only.

isort:skip_file
"""

from datetime import date, datetime, timedelta

import utils.arsrapport_remind as remind
import utils.database as db
import utils.mail as mail
from utils.arsrapport import STOCKHOLM

from tests.ht_helpers import count_queries
from tests.test_arsrapport_remind import SLOT1, ReminderTest

DUE = datetime(2026, 2, 1, 7, 0, tzinfo=STOCKHOLM)  # deadline 2026-01-31 + 1 day


class TestButton(ReminderTest):
    def setUp(self):
        super().setUp()
        self.now = SLOT1
        self.treasurer = self.user("kassor")
        self.treasurer.add_role("matrikel_admin", None)
        self.owner.add_role("owner", self.h.id)

    def press(self, herd="G9001"):
        return self.client.post(f"/api/v2/arsrapport/besattning/{herd}/2025/paminnelse", json={})

    def test_manual_reminder_requires_manager_of_herd(self):
        before = (db.ReportAccessCode.select().count(), db.MailMessage.select().count())
        self.assertEqual(self.press().status_code, 401)  # no login, and a link session is no login either
        for username in ("hjalp", "mhjalp", "owner", "kassor"):
            self.login(username)
            self.assertEqual(self.press().status_code, 403, username)
        self.login("man")
        self.assertEqual(self.press("M9001").status_code, 403)  # Mellerud: not the manager's genebank
        self.assertEqual((db.ReportAccessCode.select().count(), db.MailMessage.select().count()), before)
        response = self.press()
        self.assertEqual((response.status_code, response.get_json()), (200, {"queued": True}))
        self.assertEqual(self.press().get_json(), {"queued": False})
        self.login("admin")
        self.assertEqual(self.press("G9002").get_json(), {"queued": True})
        self.assertEqual(self.press("G9003").status_code, 409)  # no address
        self.assertEqual(self.press("G9999").status_code, 404)

    def test_reminder_status_is_batched_and_private(self):
        self.job()
        self.send()
        self.button(self.h2, SLOT1 + timedelta(days=1))
        self.login("man")
        view = self.client.get(f"/api/v2/arsrapport/2025/status?genebank_id={self.gotland.id}").get_json()
        rows = {row["herd"]: row for row in view["rows"]}
        self.assertEqual(rows["G9001"]["last_reminder"]["status"], "sent")
        self.assertIsNotNone(rows["G9001"]["last_reminder"]["sent_at"])
        self.assertEqual(
            (rows["G9002"]["last_reminder"]["status"], rows["G9002"]["last_reminder"]["sent_at"]), ("queued", None)
        )
        self.assertIsNone(rows["G9003"]["last_reminder"])
        self.assertEqual(set(rows["G9001"]["last_reminder"]), {"queued_at", "sent_at", "status"})
        db.MailMessage.update(status="failed").where(
            db.MailMessage.herd == self.h2.id, db.MailMessage.status == "queued"
        ).execute()
        view = self.client.get(f"/api/v2/arsrapport/2025/status?genebank_id={self.gotland.id}").get_json()
        self.assertEqual(
            {row["herd"]: (row["last_reminder"] or {}).get("status") for row in view["rows"]}["G9002"], "failed"
        )

        def queries():
            with count_queries() as counter:
                self.client.get(f"/api/v2/arsrapport/2025/status?genebank_id={self.gotland.id}")
            return counter["n"]

        few = queries()
        for n in range(10):
            herd = self.herd_with_member(f"G91{n:02d}")
            self.button(herd)
        self.assertEqual(queries(), few)


class TestUnanswered(ReminderTest):
    def setUp(self):
        super().setUp()
        (rabbit, _) = list(db.Individual.select().where(db.Individual.origin_herd == self.h2.id))
        self.now = SLOT1
        self.reported(self.h2, self.kvar(rabbit, vikt=2.8))
        self.h4 = self.herd_with_member("G9004")
        self.reported(self.h4, ending_genbank=True)
        self.h5 = self.herd_with_member("G9005")  # a paper form waiting in the queue
        item = self.item()
        db.InboxItem.update(herd=self.h5.id).where(db.InboxItem.id == item.id).execute()
        db.InboxDocument.update(doc_type="arsblankett").where(db.InboxDocument.item == item.id).execute()
        self.old = db.Herd.create(genebank=self.gotland, herd="G9006", is_active=False)

    def lists(self):
        return list(db.MailMessage.select().where(db.MailMessage.kind == remind.UNANSWERED).order_by(db.MailMessage.id))

    def test_unanswered_list_rechecks_scope_and_includes_no_email(self):
        self.assertEqual(remind.send_due_unanswered(DUE), 1)  # one manager of Gotland; no admin, no helper
        (row,) = self.lists()
        self.assertEqual(
            (row.recipient_kind, row.recipient_id, row.priority, row.category), ("user", self.manager.id, 1, "T")
        )
        self.assertEqual(
            row.params, {"round_id": self.round_.id, "genebank_id": self.gotland.id, "user_id": self.manager.id}
        )
        subject, body = mail.render(row.kind, self.build(row))
        self.assertEqual(subject, "Årsrapporter 2025 som saknas för gotland")
        self.assertIn("Blanketten har kommit men är inte inmatad:\nG9005, blankett inkommen\n", body)
        self.assertIn("Inget inskick:\nG9001, ej rapporterad\nG9003, ingen e-post\n", body)
        for absent in ("G9002", "G9004", "G9006", "M9001", "Namn ", "@"):
            self.assertNotIn(absent, body)
        self.assertIn(f"/stamboken/arsrapport/status/2025?genebank_id={self.gotland.id}&filter=ej_svarat", body)
        self.login("man")  # P12: the filter is the same herds
        view = self.client.get(f"/api/v2/arsrapport/2025/status?genebank_id={self.gotland.id}").get_json()
        self.assertEqual(sorted(r["herd"] for r in view["rows"] if r["needs_report"]), ["G9001", "G9003", "G9005"])
        self.manager.remove_role("manager", self.gotland.id)
        self.assertIsNone(self.build(row))

    def test_unanswered_list_is_once_and_current(self):
        self.assertEqual(remind.send_due_unanswered(DUE - timedelta(minutes=1)), 0)
        db.YearlyReportRound.update(end_date=date(2026, 1, 31)).execute()  # closed since: Å5 still goes
        self.assertEqual(remind.send_due_unanswered(DUE + timedelta(hours=3)), 1)
        self.assertEqual(remind.send_due_unanswered(DUE + timedelta(days=1)), 0)
        (row,) = self.lists()
        for herd in (self.h, self.h3, self.h5):  # every herd reports late, before the list goes
            self.reported(herd, ending_genbank=True)
        self.assertIsNone(self.build(row))
        self.assertEqual(remind.send_due_unanswered(DUE + timedelta(days=remind.UNANSWERED_DAYS)), 0)

    def test_no_list_when_everyone_has_answered_or_long_after(self):
        for herd in (self.h, self.h3, self.h5):
            self.reported(herd, ending_genbank=True)
        self.assertEqual(remind.send_due_unanswered(DUE), 0)
        db.YearlyHerdReport.update(status="voided", voided_at=DUE, voided_by_user=self.owner.id).where(
            db.YearlyHerdReport.herd == self.h.id
        ).execute()
        self.assertEqual(remind.send_due_unanswered(DUE + timedelta(days=remind.UNANSWERED_DAYS)), 0)
        self.assertEqual(remind.send_due_unanswered(DUE + timedelta(days=1)), 1)
