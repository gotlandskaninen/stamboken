#!/usr/bin/env python3
"""
Tests for the yearly report's invitation, a new link and the test mail (step 3, Task 8).
Synthetic herds, rabbits and addresses only.

isort:skip_file
"""

import re
from datetime import date, datetime, timezone
from unittest import mock

import utils.arsrapport as arsrapport
import utils.arsrapport_invite as invite
import utils.database as db
import utils.mail as mail
import utils.report_code as report_code
import utils.settings as settings
from herdbook import APP

from tests.arsrapport_fixtures import ArsrapportTest

NOW = datetime(2026, 1, 5, 7, 0, tzinfo=timezone.utc)


class InviteTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        context = APP.app_context()
        context.push()
        self.addCleanup(context.pop)
        patcher = mock.patch.multiple(settings.mail, link_secret="test-link-secret", link_hosts=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.at(date(2026, 1, 5))
        self.round_ = self.round(2025)
        self.h = self.herd_with_member("G9001")
        self.h2 = self.herd_with_member("G9002")
        self.h3 = self.herd_with_member("G9003", email=None)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.m1 = self.herd_with_member("M9001", genebank=self.mellerud)
        self.member = db.Member.get(db.Member.membership == self.h.membership)

    def herd_with_member(self, code, email="x@example.invalid", genebank=None):
        herd = db.Herd.create(genebank=genebank or self.gotland, herd=code, herd_name=f"Namn {code}", is_active=True)
        self.main_member(herd, email and f"{code.lower()}@example.invalid")
        self.rabbits(herd, 2)
        return herd

    def run_job(self):
        return invite.send_due_invitations(NOW)

    def mails(self, kind="arsrapport.inbjudan"):
        return list(db.MailMessage.select().where(db.MailMessage.kind == kind).order_by(db.MailMessage.id))

    def codes(self, herd):
        return list(db.ReportAccessCode.select().where(db.ReportAccessCode.herd == herd.id))

    def build(self, row):
        return mail.MAIL_KINDS[row.kind].build(row.params)

    def test_invites_each_active_herd_once(self):
        self.assertEqual(self.run_job(), 2)
        self.assertEqual(self.run_job(), 0)
        self.assertEqual(sorted(m.herd.herd for m in self.mails()), ["G9001", "G9002"])
        self.assertEqual([len(self.codes(h)) for h in (self.h, self.h2)], [1, 1])
        activation = db.YearlyReportRoundGenebank.get(db.YearlyReportRoundGenebank.genebank == self.gotland.id)
        self.assertIsNotNone(activation.sent_at)

    def test_no_email_no_code(self):
        self.run_job()
        self.assertEqual(self.codes(self.h3), [])
        self.assertNotIn("G9003", [m.herd.herd for m in self.mails()])

    def test_sent_at_only_after_whole_genebank(self):
        real, calls = report_code.issue_code, []

        def failing(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("boom")
            return real(*args, **kwargs)

        with mock.patch.object(report_code, "issue_code", failing):
            self.assertEqual(self.run_job(), 0)
        activation = db.YearlyReportRoundGenebank.get(db.YearlyReportRoundGenebank.genebank == self.gotland.id)
        self.assertIsNone(activation.sent_at)
        self.assertEqual(self.mails(), [])
        self.assertEqual(self.run_job(), 2)
        self.assertEqual(len(self.mails()), 2)
        self.assertEqual([len(self.codes(h)) for h in (self.h, self.h2)], [1, 1])

    def test_other_genebank_untouched(self):
        self.run_job()
        self.assertEqual(self.codes(self.m1), [])
        self.assertNotIn("M9001", [m.herd.herd for m in self.mails()])

    def test_not_before_send_at_or_without_open_round(self):
        db.YearlyReportRoundGenebank.update(send_at=date(2026, 1, 6)).execute()
        self.assertEqual(self.run_job(), 0)
        db.YearlyReportRoundGenebank.update(send_at=date(2026, 1, 5)).execute()
        db.YearlyReportRound.update(end_date=date(2026, 1, 4)).execute()
        self.assertEqual(self.run_job(), 0)

    def test_builder_cancels_when_revoked_or_submitted(self):
        self.run_job()
        row = self.mails()[0]
        self.assertIsNotNone(self.build(row))
        report_code.revoke(self.codes(self.h)[0], now=NOW)
        self.assertIsNone(self.build(row))
        row2 = self.mails()[1]
        (rabbit, _) = list(db.Individual.select().where(db.Individual.origin_herd == self.h2.id))
        self.reported(self.h2, self.kvar(rabbit, vikt=2.8))
        self.assertIsNone(self.build(row2))

    def test_mail_row_holds_no_token(self):
        self.run_job()
        code = self.codes(self.h)[0]
        mac = report_code.code_url(code).split("#")[1].split(".")[1]
        for row in db.MailMessage.select().dicts():
            self.assertNotIn(mac, repr(row))

    def test_link_in_body_resolves_to_the_code(self):
        self.run_job()
        row = self.mails()[0]
        variables = self.build(row)
        subject, body = mail.render(row.kind, {k: v for k, v in variables.items() if k != "attachments"})
        (token,) = re.findall(r"/rapport#(\S+)", body)
        self.assertEqual(report_code.resolve(token).id, self.codes(row.herd)[0].id)
        self.assertEqual(subject, f"Årsrapporten 2025 för {row.herd.herd}: rapportera senast 2026-01-31")
        self.assertIn("Dina kaniner är redan ifyllda. Välj för varje kanin", body)
        ((name, mime, data),) = variables["attachments"]
        self.assertEqual((mime, data[:4]), ("application/pdf", b"%PDF"))

    def test_new_link_revokes_old(self):
        self.run_job()
        old = self.codes(self.h)[0]
        new = invite.new_link(self.h, self.round_, self.owner, now=NOW)
        self.assertNotEqual(new.id, old.id)
        self.assertIsNotNone(db.ReportAccessCode.get_by_id(old.id).revoked_at)
        self.assertIsNone(new.revoked_at)
        (row,) = self.mails("arsrapport.ny_lank")
        self.assertEqual((row.dedupe_key, row.created_by_id), (f"arsrapport.ny_lank:{new.id}", self.owner.id))
        _, body = mail.render(row.kind, self.build(row))
        (token,) = re.findall(r"/rapport#(\S+)", body)
        self.assertEqual(report_code.resolve(token).id, new.id)
        self.assertIsNone(self.build(self.mails()[0]))  # the invitation's code is revoked now

    def test_new_link_takes_no_report_lock(self):
        self.run_job()
        with mock.patch.object(arsrapport, "lock_report", side_effect=AssertionError("locked")):
            invite.new_link(self.h, self.round_, self.owner, now=NOW)

    def test_new_link_mail_sent_after_submission(self):
        self.run_job()
        (rabbit, _) = list(db.Individual.select().where(db.Individual.origin_herd == self.h.id))
        self.reported(self.h, self.kvar(rabbit, vikt=2.8))
        invite.new_link(self.h, self.round_, self.owner, now=NOW)
        (row,) = self.mails("arsrapport.ny_lank")
        self.assertIsNotNone(self.build(row))

    def test_new_link_without_email_refused(self):
        with self.assertRaises(arsrapport.ArsrapportError):
            invite.new_link(self.h3, self.round_, self.owner, now=NOW)

    def test_test_mail_goes_to_the_user_without_code(self):
        invite.test_mail(self.round_, self.gotland.id, self.owner)
        (row,) = self.mails()
        self.assertEqual((row.recipient_kind, row.recipient_id, row.herd.herd), ("user", self.owner.id, "G9001"))
        self.assertEqual(db.ReportAccessCode.select().count(), 0)
        subject, body = mail.render(row.kind, {k: v for k, v in self.build(row).items() if k != "attachments"})
        self.assertTrue(subject.startswith("[Provmejl] "))
        self.assertIn("/rapport#prov", body)
        self.assertIn("(Det här är en provlänk.", body)
        self.assertEqual(db.ReportAccessCode.select().count(), 0)

    def test_recipients_counts(self):
        self.assertEqual(invite.recipients(self.round_, self.gotland.id), {"med_epost": 2, "utan_epost": 1})

    def test_endpoints_need_the_genebank_manager(self):
        self.login("man")
        path = "/rundor/2025/genbanker"
        gb = self.gotland.id
        self.assertEqual(self.api("GET", f"{path}/{gb}/mottagare").get_json(), {"med_epost": 2, "utan_epost": 1})
        self.assertEqual(self.api("POST", f"{path}/{gb}/provmejl").status_code, 200)
        self.assertEqual(self.api("POST", "/besattning/G9001/2025/ny-lank").status_code, 200)
        self.assertEqual(self.api("POST", "/besattning/M9001/2025/ny-lank").status_code, 403)
        self.assertEqual(self.api("POST", f"{path}/{self.mellerud.id}/provmejl").status_code, 403)

    def other_member_code(self, herd):
        """A code another main member of the herd got, as when a new_link wins the unique index race."""
        other = db.Member.create(
            first_name="Ny",
            last_name="Huvudmedlem",
            email="ny@example.invalid",
            role="huvudmedlem",
            membership=db.Membership.create(),
        )
        return db.ReportAccessCode.create(
            herd=herd.id, round=self.round_.id, member=other.id, expires_at=self.round_.end_date, created_at=NOW
        )

    def test_invitation_goes_to_the_returned_codes_member(self):
        rival = self.other_member_code(self.h)
        real = report_code.issue_code
        with mock.patch.object(
            report_code, "issue_code", lambda herd, *a, **k: rival if herd.id == self.h.id else real(herd, *a, **k)
        ):
            self.assertEqual(self.run_job(), 1)
        self.assertEqual([m.herd.herd for m in self.mails()], ["G9002"])

    def test_new_link_refuses_a_code_for_another_member(self):
        rival = self.other_member_code(self.h)
        with mock.patch.object(report_code, "issue_code", return_value=rival):
            with self.assertRaises(arsrapport.ArsrapportError):
                invite.new_link(self.h, self.round_, self.owner, now=NOW)
        self.assertEqual(self.mails("arsrapport.ny_lank"), [])

    def test_a_stale_activation_issues_nothing(self):
        stale = db.YearlyReportRoundGenebank.get(db.YearlyReportRoundGenebank.genebank == self.gotland.id)
        self.run_job()
        with mock.patch.object(report_code, "issue_code", side_effect=AssertionError("issued")):
            self.assertEqual(invite._invite_genebank(stale, NOW), 0)
