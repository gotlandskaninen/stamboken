#!/usr/bin/env python3
"""
Tests for the yearly report's reminders (step 6, Task 1): the occasions on deadline−11 and deadline−2 at 07:00 in
Stockholm, the manager's button, the checks before queueing and when sent, and the queue's states (P2–P5).
Synthetic herds, rabbits and addresses only.

isort:skip_file
"""

import re
import threading
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

import utils.arsrapport as arsrapport
import utils.arsrapport_invite as invite
import utils.arsrapport_remind as remind
import utils.database as db
import utils.login_code as login_code
import utils.mail as mail
import utils.report_code as report_code
import utils.settings as settings
from herdbook import APP
from utils.arsrapport import STOCKHOLM, ArsrapportError

from tests.arsrapport_fixtures import ArsrapportTest
from tests.test_mail_queue import FakeRelay, _refused
from tests.test_purchase_notice import in_thread, run_all

INVITED = datetime(2025, 12, 31, 8, 0, tzinfo=STOCKHOLM)
SLOT1 = datetime(2026, 1, 20, 7, 0, tzinfo=STOCKHOLM)  # deadline 2026-01-31 − 11 days
SLOT2 = datetime(2026, 1, 29, 7, 0, tzinfo=STOCKHOLM)  # − 2 days


class ReminderTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        context = APP.app_context()
        context.push()
        self.addCleanup(context.pop)
        patcher = mock.patch.multiple(settings.mail, link_secret="test-link-secret", link_hosts=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.now = INVITED
        for target in (arsrapport, mail):  # the report's clock and the queue's stand still together
            patcher = mock.patch.object(
                target, "now" if target is arsrapport else "_utcnow", side_effect=lambda: self.now
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        self.round_ = self.round(2025)
        self.h = self.herd_with_member("G9001")
        self.h2 = self.herd_with_member("G9002")
        self.h3 = self.herd_with_member("G9003", email=None)
        self.m1 = self.herd_with_member("M9001", genebank=self.mellerud)
        self.assertEqual(invite.send_due_invitations(INVITED), 2)  # G9001 and G9002 have their links
        self.send()  # and the invitations went on 31 December

    def herd_with_member(self, code, email="x", genebank=None):
        herd = db.Herd.create(genebank=genebank or self.gotland, herd=code, herd_name=f"Namn {code}", is_active=True)
        self.main_member(herd, email and f"{code.lower()}@example.invalid")
        self.rabbits(herd, 2)
        return herd

    def job(self, when=None):
        self.now = when or self.now
        return remind.send_due_reminders(self.now)

    def button(self, herd, when=None):
        self.now = when or self.now
        return remind.send_reminder(herd, self.round_, self.manager, now=self.now)

    def rows(self, herd=None):
        query = db.MailMessage.select().where(db.MailMessage.kind == remind.REMINDER)
        if herd is not None:
            query = query.where(db.MailMessage.herd == herd.id)
        return list(query.order_by(db.MailMessage.id))

    def build(self, row):
        return mail.MAIL_KINDS[row.kind].build(row.params)

    def send(self, relay=None):
        relay = relay or FakeRelay()
        with (
            mock.patch.multiple(settings.mail, mode="live", allowlist=[]),
            mock.patch.object(mail.smtplib, "SMTP", relay),
        ):
            mail.send_pending()
        return relay

    def state(self):
        """(herd, slot, status) of every reminder, oldest first."""
        return [(row.herd.herd, row.params["slot"], db.MailMessage.get_by_id(row.id).status) for row in self.rows()]

    def code(self, herd):
        return db.ReportAccessCode.get(db.ReportAccessCode.herd == herd.id, db.ReportAccessCode.revoked_at.is_null())


class TestCalendar(ReminderTest):
    def test_reminder_calendar_follows_the_deadline_in_stockholm(self):
        round_ = SimpleNamespace(deadline=date(2026, 12, 26))  # the round open now: 15 and 24 December
        utc = timezone.utc
        cases = [
            (datetime(2026, 12, 15, 6, 59, tzinfo=STOCKHOLM), None),
            (datetime(2026, 12, 15, 5, 59, tzinfo=utc), None),  # 06:59 in Stockholm (CET)
            (datetime(2026, 12, 15, 6, 0, tzinfo=utc), 1),
            (datetime(2026, 12, 24, 6, 59, tzinfo=STOCKHOLM), 1),
            (datetime(2026, 12, 24, 7, 0, tzinfo=STOCKHOLM), 2),
            (datetime(2026, 12, 26, 23, 59, tzinfo=STOCKHOLM), 2),
            (datetime(2026, 12, 26, 23, 30, tzinfo=utc), None),  # 00:30 on 27 December in Stockholm
        ]
        for when, slot in cases:
            self.assertEqual(remind.reminder_slot(round_, when), slot, when)
        self.assertIsNone(remind.reminder_slot(SimpleNamespace(deadline=None), SLOT1))

    def test_reminder_calendar_and_catch_up(self):
        self.assertEqual(self.job(SLOT1 - timedelta(minutes=1)), 0)
        self.assertEqual(self.job(SLOT1), 2)  # not G9003 (no address) and not M9001 (genebank not activated)
        self.assertEqual(self.job(SLOT1 + timedelta(hours=1)), 0)
        self.send()
        self.assertEqual(self.job(SLOT1 + timedelta(days=1, hours=3)), 0)  # the occasion had its reminder
        self.assertEqual(self.job(SLOT2), 2)
        self.send()
        self.assertEqual(self.job(datetime(2026, 2, 1, 9, 0, tzinfo=STOCKHOLM)), 0)  # none after the deadline
        self.assertEqual(
            self.state(), [("G9001", 1, "sent"), ("G9002", 1, "sent"), ("G9001", 2, "sent"), ("G9002", 2, "sent")]
        )

    def test_a_long_outage_sends_only_the_latest_and_nothing_before_seven(self):
        self.assertEqual(self.job(datetime(2026, 1, 31, 6, 30, tzinfo=STOCKHOLM)), 0)  # a startup before 07:00
        self.assertEqual(self.job(datetime(2026, 1, 31, 7, 5, tzinfo=STOCKHOLM)), 2)
        self.assertEqual({row.params["slot"] for row in self.rows()}, {2})

    def test_a_moved_deadline_never_repeats_a_delivered_occasion(self):
        self.job(SLOT1)
        self.send()
        db.YearlyReportRound.update(deadline=date(2026, 2, 5)).execute()  # slot 1 now from 25 January
        self.assertEqual(self.job(SLOT1 + timedelta(days=1)), 0)
        self.assertEqual(self.job(datetime(2026, 1, 25, 7, 0, tzinfo=STOCKHOLM)), 0)
        self.assertEqual(self.job(datetime(2026, 2, 3, 7, 0, tzinfo=STOCKHOLM)), 2)

    def test_a_queued_reminder_is_judged_again_when_the_deadline_moves(self):
        self.job(SLOT1)
        db.YearlyReportRound.update(deadline=date(2026, 2, 5)).execute()
        self.send()  # still 20 January: slot 1 has not begun under the new deadline
        self.assertEqual([status for *_, status in self.state()], ["cancelled", "cancelled"])
        self.assertEqual(self.job(datetime(2026, 1, 25, 7, 0, tzinfo=STOCKHOLM)), 2)  # owed again, and queued

    def test_a_shortened_round_cancels_the_queued_reminder(self):
        self.job(SLOT2)
        db.YearlyReportRound.update(deadline=date(2026, 1, 28)).execute()
        self.send()
        self.assertEqual([status for *_, status in self.state()], ["cancelled", "cancelled"])

    def test_no_reminder_before_the_invitations_or_in_a_closed_round(self):
        db.YearlyReportRoundGenebank.update(sent_at=None).execute()
        self.assertEqual(self.job(SLOT1), 0)
        db.YearlyReportRoundGenebank.update(sent_at=INVITED).execute()
        db.YearlyReportRound.update(end_date=date(2026, 1, 19)).execute()  # closed before 20 January
        self.assertEqual(self.job(SLOT1), 0)
        self.assertEqual(self.rows(), [])


class TestEligibility(ReminderTest):
    def test_reminder_eligibility_and_draft_copy(self):
        (rabbit, _) = list(db.Individual.select().where(db.Individual.origin_herd == self.h2.id))
        self.reported(self.h2, self.kvar(rabbit, vikt=2.8))
        self.now = SLOT1
        with self.assertRaises(ArsrapportError) as refused:
            self.button(self.h2)
        self.assertEqual(
            (refused.exception.status, refused.exception.detail), (409, "Årsrapporten är redan inskickad.")
        )
        with self.assertRaises(ArsrapportError):
            self.button(self.h3)  # no address: no code, no mail
        self.assertFalse(db.ReportAccessCode.select().where(db.ReportAccessCode.herd == self.h3.id).exists())
        db.YearlyReportDraft.create(herd=self.h, round=self.round_, data={}, updated_at=self.now)
        self.assertEqual(self.job(), 1)
        (row,) = self.rows()
        subject, body = mail.render(row.kind, self.build(row))
        self.assertEqual(subject, "Påminnelse om årsrapporten 2025 för G9001")
        self.assertIn("Din årsrapport är påbörjad men inte inskickad.", body)
        self.assertNotIn("Vi saknar", body)
        self.assertIn("Sista dag för stödet är 2026-01-31. Länken gäller till och med 2026-03-30.", body)
        self.assertIn("Har du redan skickat en blankett behöver du inte skicka den igen.", body)
        (token,) = re.findall(r"/rapport#(\S+)", body)
        self.assertEqual(report_code.resolve(token).id, self.code(self.h).id)
        db.YearlyReportDraft.delete().execute()  # the wording follows the state when the mail goes
        self.assertIn("Vi saknar årsrapporten för G9001.", mail.render(row.kind, self.build(row))[1])

    def test_the_reminder_recommends_code_login_only_when_it_is_on(self):  # Jonas 2026-11-27
        self.job(SLOT1)
        row = self.rows(self.h)[0]
        tip = (
            "Logga gärna in i Stamboken först, med din e-postadress hos föreningen. Vi mejlar en kod, du behöver "
            "inget lösenord. Inloggad kan du sälja kaniner direkt, ändra dina uppgifter i rapporten och ångra en "
            f"försäljning. Logga in på {settings.service.host.rstrip('/')}/auth/sign-in.\n\n"
            "Vill du inte logga in går det bra att använda länken ovan.\n\nSista dag för stödet är"
        )
        with mock.patch.object(login_code, "enabled", return_value=True):
            on = mail.render(row.kind, self.build(row))[1]
        self.assertIn(tip, on)
        (link,) = re.findall(r"/rapport#\S+", on)
        self.assertLess(on.index(link), on.index("Logga gärna in"))
        with mock.patch.object(login_code, "enabled", return_value=False):
            off = mail.render(row.kind, self.build(row))[1]
        self.assertNotIn("Logga", off)
        self.assertIn(f"{link}\n\nSista dag för stödet är", off)  # as before

    def test_an_ending_report_counts_and_a_withdrawn_one_does_not(self):
        ending = self.reported(self.h, ending_genbank=True)
        self.assertEqual(self.job(SLOT1), 1)  # G9002 only
        self.assertEqual([row.herd_id for row in self.rows()], [self.h2.id])
        db.YearlyHerdReport.update(status="voided", voided_at=SLOT1, voided_by_user=self.owner.id).where(
            db.YearlyHerdReport.id == ending.id
        ).execute()
        self.assertEqual(self.job(SLOT1 + timedelta(hours=1)), 1)

    def test_a_button_reminder_after_the_deadline_says_so(self):
        self.assertIsNotNone(self.button(self.h, datetime(2026, 2, 2, 10, 0, tzinfo=STOCKHOLM)))
        (row,) = self.rows()
        self.assertEqual((row.params["slot"], row.params["scheduled"]), (None, False))
        body = mail.render(row.kind, self.build(row))[1]
        self.assertIn("Sista dag för stödet var 2026-01-31. Rapportera ändå, så räknas dina kaniner.", body)
        self.assertNotIn("Sista dag för stödet är", body)

    def test_demo_followups_create_no_codes_or_mail(self):
        codes = list(db.ReportAccessCode.select().dicts())
        mails = db.MailMessage.select().count()
        with mock.patch.object(settings.service, "demo_instance", True):
            self.assertEqual(self.job(SLOT1), 0)
            self.assertEqual(remind.send_due_unanswered(datetime(2026, 2, 1, 8, 0, tzinfo=STOCKHOLM)), 0)
            with self.assertRaises(ArsrapportError) as refused:
                self.button(self.h)  # an invited herd with an address: the demo alone refuses it
        self.assertEqual(refused.exception.detail, "Påminnelser skickas inte från demon.")
        self.assertEqual(list(db.ReportAccessCode.select().dicts()), codes)
        self.assertEqual(db.MailMessage.select().count(), mails)


class TestQueue(ReminderTest):
    def test_reminder_rechecked_and_deduplicated(self):
        self.assertIsNotNone(self.button(self.h, SLOT1 - timedelta(hours=1)))  # before slot 1: an occasion of none
        self.assertIsNone(self.button(self.h))  # one waits in the queue
        self.assertEqual(self.job(SLOT1), 1)  # G9002; G9001's waits
        self.send()
        self.assertIsNone(self.button(self.h, SLOT1 + timedelta(hours=2)))  # it went today
        self.assertIsNotNone(self.button(self.h, SLOT1 + timedelta(days=1)))  # the button: once a day
        self.assertEqual(self.job(), 0)  # stamped slot 1: the occasion is covered
        self.assertEqual(len(self.rows(self.h)), 2)

    def test_the_builder_cancels_after_submission_revocation_or_a_new_main_member(self):
        self.job(SLOT1)
        row, row2 = self.rows()
        (rabbit, _) = list(db.Individual.select().where(db.Individual.origin_herd == self.h.id))
        self.reported(self.h, self.kvar(rabbit, vikt=2.8))
        self.assertIsNone(self.build(row))
        self.assertIsNotNone(self.build(row2))
        self.main_member(self.h2, "ny@example.invalid")
        self.assertIsNone(self.build(row2))

    def test_concurrent_button_and_job_queue_one(self):
        barrier = threading.Barrier(2)
        self.now = SLOT1

        def work(fn):
            def run():
                barrier.wait(timeout=10)
                return fn()

            return run

        results = {}
        threads = [
            in_thread(
                results, "button", work(lambda: remind.send_reminder(self.h, self.round_, self.manager, now=SLOT1))
            ),
            in_thread(results, "job", work(lambda: remind.send_due_reminders(SLOT1))),
        ]
        self.assertTrue(run_all(*threads))
        self.assertFalse(any(isinstance(value, str) for value in results.values()), results)
        self.assertEqual(len(self.rows(self.h)), 1)

    def test_cancelled_followup_does_not_consume_delivery(self):
        self.job(SLOT1)
        old = self.code(self.h)
        invite.new_link(self.h, self.round_, self.manager, now=self.now)  # the queued reminder's link is revoked
        self.send()
        first = self.rows(self.h)[0]
        self.assertEqual(db.MailMessage.get_by_id(first.id).status, "cancelled")
        for _ in range(5):  # the new link's mail reminded the member: no second mail in the occasion
            self.job(SLOT1 + timedelta(hours=1))
        self.assertEqual(len(self.rows(self.h)), 1)
        self.assertEqual(self.job(SLOT2), 2)  # the next occasion goes, with the new link
        again = self.rows(self.h)[-1]
        self.assertEqual(again.params["code_id"], self.code(self.h).id)
        self.assertNotEqual(again.params["code_id"], old.id)
        self.assertNotEqual(again.dedupe_key, first.dedupe_key)

    def test_a_late_invitation_is_not_followed_by_a_reminder(self):
        late = self.herd_with_member("G9005")
        self.now = SLOT1 + timedelta(minutes=5)
        self.assertEqual(invite.send_due_invitations(self.now), 1)  # its first usable address came today
        self.send()
        self.assertEqual(self.job(SLOT1 + timedelta(hours=1)), 2)  # G9001 and G9002, not G9005
        self.assertEqual(self.rows(late), [])
        self.assertEqual(self.job(SLOT2), 3)

    def test_follow_ups_never_make_the_link_the_invitation_needs(self):  # review 1: the invitation is not suppressed
        herd = self.herd_with_member("G9005")
        self.now = SLOT1 - timedelta(days=1)
        with self.assertRaises(ArsrapportError) as refused:
            self.button(herd)
        self.assertEqual(refused.exception.detail, remind.NO_LINK)
        self.assertEqual(self.job(SLOT1), 2)
        self.assertFalse(db.ReportAccessCode.select().where(db.ReportAccessCode.herd == herd.id).exists())
        self.assertEqual(invite.send_due_invitations(SLOT1), 1)  # the invitation still goes, with its extract
        (invitation,) = [m for m in db.MailMessage.select() if m.kind == "arsrapport.inbjudan" and m.herd_id == herd.id]
        self.assertIsNotNone(self.build(invitation))

    def test_an_address_the_queue_cannot_send_to_is_never_queued(self):  # review 1: no new cancelled row every hour
        herd = self.herd_with_member("G9005")
        db.Member.update(email="o'neil@example.invalid").where(db.Member.membership == herd.membership).execute()
        self.assertEqual(invite.send_due_invitations(self.now), 1)  # the invitation job makes a link all the same
        for hour in range(3):
            self.job(SLOT1 + timedelta(hours=hour))
        self.assertEqual(self.rows(herd), [])
        with self.assertRaises(ArsrapportError):
            self.button(herd)

    def test_a_button_reminder_sent_in_the_next_occasion_covers_it(self):  # review 1: delivered slot
        self.button(self.h, datetime(2026, 1, 29, 6, 58, tzinfo=STOCKHOLM))  # queued in occasion 1
        self.now = datetime(2026, 1, 29, 7, 3, tzinfo=STOCKHOLM)  # sent in occasion 2
        self.send()
        (row,) = self.rows(self.h)
        self.assertEqual((row.params["slot"], db.MailMessage.get_by_id(row.id).last_error), (1, "tillfälle 2"))
        self.assertEqual(self.job(datetime(2026, 1, 30, 9, 0, tzinfo=STOCKHOLM)), 1)  # G9002 only
        self.assertEqual(len(self.rows(self.h)), 1)

    def test_a_reminder_the_queue_reaches_at_night_waits_for_morning(self):  # review 2: rechecked when sent
        self.job(SLOT1)
        row = self.rows(self.h)[0]
        self.now = datetime(2026, 1, 20, 23, 30, tzinfo=STOCKHOLM)  # the relay was down all day
        with self.assertRaises(mail.Later) as later:
            self.build(row)
        self.assertEqual(later.exception.until, datetime(2026, 1, 21, 7, 0, tzinfo=STOCKHOLM))
        self.now = datetime(2026, 1, 21, 6, 0, tzinfo=STOCKHOLM)
        with self.assertRaises(mail.Later) as later:
            self.build(row)
        self.assertEqual(later.exception.until, datetime(2026, 1, 21, 7, 0, tzinfo=STOCKHOLM))
        self.now = datetime(2026, 1, 21, 7, 0, tzinfo=STOCKHOLM)
        self.assertIsNotNone(self.build(row))

    def test_no_member_mail_at_night(self):
        self.assertEqual(self.job(datetime(2026, 1, 20, 21, 0, tzinfo=STOCKHOLM)), 0)
        self.assertEqual(self.job(datetime(2026, 1, 21, 6, 59, tzinfo=STOCKHOLM)), 0)
        self.assertEqual(self.job(datetime(2026, 1, 21, 7, 0, tzinfo=STOCKHOLM)), 2)

    def test_a_stopped_or_failed_reminder_is_not_replaced(self):
        self.job(SLOT1)
        stopped, failed = self.rows()
        db.MailMessage.update(status="cancelled", last_error=mail.STOPPED).where(
            db.MailMessage.id == stopped.id
        ).execute()
        db.MailMessage.update(status="failed").where(db.MailMessage.id == failed.id).execute()
        self.assertEqual(self.job(SLOT1 + timedelta(hours=1)), 0)
        self.assertEqual(self.job(SLOT1 + timedelta(days=1)), 0)
        self.assertIsNotNone(self.button(self.h2))  # the button is not stopped by a failure

    def test_a_slot_one_backlog_does_not_block_slot_two(self):
        self.job(SLOT1)
        db.MailMessage.update(next_attempt_at=SLOT2 + timedelta(hours=6)).execute()  # on the retry ladder
        self.assertEqual(self.job(SLOT2), 2)
        self.now = SLOT2 + timedelta(hours=7)  # 14:00, by day
        self.send()
        self.assertEqual(
            sorted(self.state()),
            [("G9001", 1, "cancelled"), ("G9001", 2, "sent"), ("G9002", 1, "cancelled"), ("G9002", 2, "sent")],
        )

    def test_reminder_queue_contract(self):
        self.job(SLOT1)
        self.send()
        self.button(self.h, SLOT1 + timedelta(days=1))
        scheduled, _, button = self.rows()
        self.assertEqual((scheduled.priority, button.priority), (2, 1))
        self.assertEqual({row.category for row in self.rows()}, {"T"})
        self.assertEqual(set(scheduled.params), {"round_id", "code_id", "slot", "scheduled"})
        self.assertTrue(all(value is None or isinstance(value, int) for value in scheduled.params.values()))
        self.assertEqual((scheduled.ref_type, scheduled.ref_id), ("access_code", self.code(self.h).id))
        self.assertEqual(button.created_by_id, self.manager.id)
        self.assertNotIn("attachments", self.build(scheduled))
        mac = report_code.code_url(self.code(self.h)).split("#")[1].split(".")[1]
        for row in db.MailMessage.select().dicts():
            self.assertNotIn(mac, repr(row))
        self.send(FakeRelay(replies=[_refused(451, "4.2.0 try later")]))  # temporary: the queue's own retry ladder
        button = db.MailMessage.get_by_id(button.id)
        self.assertEqual((button.status, button.attempts), ("queued", 1))
        self.assertEqual(self.job(SLOT1 + timedelta(days=1, hours=1)), 0)
        self.assertIsNone(self.button(self.h))
