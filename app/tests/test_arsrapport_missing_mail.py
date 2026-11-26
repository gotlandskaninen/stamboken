#!/usr/bin/env python3
"""
Tests for Å22, the question about the rabbits a paper form left out (step 6, Task 3): once per report, the rabbits
still unstated when it is sent, the current main member and link, and the two phases without a lock cycle.
Synthetic herds, rabbits and addresses only.

isort:skip_file
"""

import json
import re
import threading
from datetime import datetime, timedelta
from unittest import mock

import utils.arsrapport as arsrapport
import utils.arsrapport_invite as invite
import utils.arsrapport_remind as remind
import utils.database as db
import utils.mail as mail
import utils.report_code as report_code
import utils.settings as settings
from utils.arsrapport import STOCKHOLM

from tests.test_arsrapport_remind import ReminderTest
from tests.test_purchase_notice import in_thread, lock_waiter, until

ENTERED = datetime(2026, 1, 12, 10, 0, tzinfo=STOCKHOLM)


class MissingTest(ReminderTest):
    def setUp(self):
        super().setUp()
        self.now = ENTERED
        self.case, self.left = self.ej_angiven_case(self.h)
        self.report = self.paper(self.h, self.case, self.left)

    def paper(self, herd, rabbits, left, **fields):
        """A report from paper that leaves `left` unstated, as Skicka from "från blankett" stores it."""
        entries = [self.ej_angiven(r) if r in left else self.kvar(r, vikt=2.8) for r in rabbits]
        return self.reported(herd, *entries, source="paper", **fields)

    def ask(self, when=None):
        self.now = when or self.now
        return remind.send_missing_questions(self.now)

    def questions(self):
        query = db.MailMessage.select().where(db.MailMessage.kind == remind.MISSING)
        return list(query.order_by(db.MailMessage.id))

    def answer(self, *entries):
        """The latest submission with `entries` in place of their rabbits' entries, as a completion stores it."""
        report = arsrapport.current_report(self.h, self.round_)
        data = json.loads(report.data)
        answered = {int(key) for key, _ in entries}
        data["not_stated"] = [i for i in data["not_stated"] if i not in answered]
        db.YearlyHerdReport.update(data=json.dumps(data)).where(db.YearlyHerdReport.id == report.id).execute()


class TestMissingQuestion(MissingTest):
    def test_missing_question_once_for_paper_report(self):
        self.assertEqual(self.ask(), 1)
        self.assertEqual(self.ask(ENTERED + timedelta(hours=1)), 0)
        (row,) = self.questions()
        self.assertEqual(
            (row.ref_type, row.ref_id, row.priority, row.category), ("yearlyherdreport", self.report.id, 1, "T")
        )
        self.assertEqual(row.params, {"report_id": self.report.id, "code_id": self.code(self.h).id})
        self.send()
        self.answer(self.ej_angiven(self.left[0]))  # a later change to the report
        self.assertEqual(self.ask(ENTERED + timedelta(days=1)), 0)
        self.assertEqual(len(self.questions()), 1)

    def test_missing_question_reads_current_missing_rabbits(self):
        self.ask()
        (row,) = self.questions()
        subject, body = mail.render(row.kind, self.build(row))
        self.assertEqual(subject, "Kaniner saknas på årsblanketten för G9001")
        listed = sorted(r.number for r in self.left)
        self.assertIn("De här kaninerna saknas på blanketten:\n\n" + "\n".join(listed) + "\n", body)
        self.assertIn("De är markerade som ej rapporterade tills du har svarat.", body)
        self.assertIn("Datumet då årsrapporten kom in ändras inte.", body)
        self.assertIn("Du kan också svara på det här mejlet.", body)
        (token,) = re.findall(r"/rapport#(\S+)", body)
        self.assertEqual(report_code.resolve(token).id, self.code(self.h).id)
        for private in ("@", "Huvudmedlem", "konto", "Namn G9001"):
            self.assertNotIn(private, body)
        self.answer(self.kvar(self.left[0], vikt=2.8))
        body = mail.render(row.kind, self.build(row))[1]
        self.assertNotIn(self.left[0].number, body)
        self.answer(self.kvar(self.left[1], vikt=2.8), self.kvar(self.left[2], vikt=2.8))
        self.assertIsNone(self.build(row))  # none left

    def test_withdrawal_ending_or_a_digital_report_asks_nothing(self):
        self.ask()
        (row,) = self.questions()
        db.YearlyHerdReport.update(status="voided", voided_at=ENTERED, voided_by_user=self.owner.id).execute()
        self.assertIsNone(self.build(row))
        ending = self.paper(self.h2, self.rabbits(self.h2, 2), [], ending_genbank=True)
        data = json.loads(ending.data) | {"not_stated": [1]}
        db.YearlyHerdReport.update(data=json.dumps(data)).where(db.YearlyHerdReport.id == ending.id).execute()
        herd = self.herd_with_member("G9004")
        rabbits = self.rabbits(herd, 3)
        self.reported(herd, self.kvar(rabbits[0], vikt=2.8), self.ej_angiven(rabbits[1]))  # by link: never Å22
        self.assertEqual(self.ask(ENTERED + timedelta(hours=1)), 0)

    def test_missing_question_uses_current_main_member(self):
        herd = self.herd_with_member("G9004", email=None)
        rabbits = self.rabbits(herd, 3)
        self.paper(herd, rabbits, rabbits[:1])
        self.assertEqual(self.ask(), 1)  # G9001 only: G9004 has no address and gets no code
        self.assertFalse(db.ReportAccessCode.select().where(db.ReportAccessCode.herd == herd.id).exists())
        (row,) = self.questions()
        member = self.main_member(self.h, "ny@example.invalid")  # a new main member before it goes
        self.assertIsNone(self.build(row))
        self.send()
        self.assertEqual(db.MailMessage.get_by_id(row.id).status, "cancelled")
        self.assertEqual(self.ask(ENTERED + timedelta(hours=1)), 1)  # P4: still owed, to the new member's link
        (_, again) = self.questions()
        self.assertEqual(again.recipient_id, member.id)
        self.assertEqual(again.params["code_id"], self.code(self.h).id)
        self.assertNotEqual(again.dedupe_key, row.dedupe_key)
        self.send()
        self.assertEqual(db.MailMessage.get_by_id(again.id).status, "sent")
        self.assertEqual(self.ask(ENTERED + timedelta(hours=2)), 0)
        self.assertEqual(len(self.questions()), 2)

    def test_a_stopped_question_stays_stopped(self):
        self.ask()
        db.MailMessage.update(status="cancelled", last_error=mail.STOPPED).execute()
        self.assertEqual(self.ask(ENTERED + timedelta(hours=1)), 0)

    def test_closed_or_inactive_rounds_and_the_demo_ask_nothing(self):
        with mock.patch.object(settings.service, "demo_instance", True):
            self.assertEqual(self.ask(), 0)
        db.YearlyReportRoundGenebank.delete().execute()  # the genebank's activation is gone
        self.assertEqual(self.ask(), 0)
        self.assertEqual(self.ask(datetime(2026, 3, 31, 9, 0, tzinfo=STOCKHOLM)), 0)  # after end_date
        self.assertEqual(self.questions(), [])

    def test_missing_question_code_and_report_locks_do_not_overlap(self):
        """A new link (the herd's code lock, then the code row) against Å22's recheck under the report's lock."""
        self.ask()
        db.MailMessage.delete().execute()
        entered, release = threading.Event(), threading.Event()
        real = report_code.revoke

        def slow_revoke(code, *, now):
            real(code, now=now)
            entered.set()
            release.wait(timeout=10)

        results = {}
        with mock.patch.object(report_code, "revoke", slow_revoke):
            link = in_thread(
                results, "link", lambda: invite.new_link(self.h, self.round_, self.manager, now=self.now).id
            )
            link.start()
            self.assertTrue(entered.wait(timeout=10))
            ask = in_thread(results, "ask", lambda: remind.send_missing_questions(self.now))
            ask.start()
            self.assertTrue(until(lock_waiter))  # Å22's first phase waits for the herd's code lock
            release.set()
            link.join(timeout=30)
            ask.join(timeout=30)
        self.assertFalse(link.is_alive() or ask.is_alive())
        self.assertIsInstance(results["link"], int, results)
        self.assertIsInstance(results["ask"], int, results)
        (row,) = self.questions()
        self.assertEqual(row.params["code_id"], results["link"])
