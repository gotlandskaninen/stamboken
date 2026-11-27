#!/usr/bin/env python3
"""
Tests for the yearly report's invitation, a new link and the test mail (step 3, Task 8).
Synthetic herds, rabbits and addresses only.

isort:skip_file
"""

import os
import re
import threading
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import utils.arsrapport as arsrapport
import utils.arsrapport_invite as invite
import utils.data_access as da
import utils.database as db
import utils.mail as mail
import utils.matrikel as matrikel
import utils.report_code as report_code
import utils.settings as settings
from herdbook import APP

from tests.arsrapport_fixtures import ArsrapportTest
from tests.database_test import _USE_POSTGRES
from tests.ht_helpers import count_queries
from tests.test_mail_queue import FakeRelay, _refused
from tests.test_purchase_notice import in_thread, lock_waiter, run_all, until

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

    def test_demo_skips_invitations(self):
        with mock.patch.object(settings.service, "demo_instance", True), self.assertLogs(invite.logger, "INFO") as log:
            self.assertEqual(self.run_job(), 0)
        self.assertEqual([r.levelname for r in log.records], ["INFO"])
        self.assertFalse(db.ReportAccessCode.select().exists())
        self.assertFalse(db.MailMessage.select().exists())
        self.assertIsNone(db.YearlyReportRoundGenebank.get().sent_at)

    def test_revoked_codes_without_mail_still_count_as_invited(self):
        self.assertEqual(self.run_job(), 2)
        db.ReportAccessCode.update(revoked_at=NOW).execute()
        db.MailMessage.delete().execute()
        self.assertIsNotNone(db.YearlyReportRoundGenebank.get().sent_at)
        self.assertEqual(self.run_job(), 0)
        self.assertEqual(db.ReportAccessCode.select().count(), 2)
        self.assertEqual(self.mails(), [])

    def test_new_link_counts_as_invited(self):
        link = invite.new_link(self.h, self.round_, self.manager, now=NOW)
        self.assertEqual(self.run_job(), 1)
        self.assertEqual([m.herd_id for m in self.mails()], [self.h2.id])
        self.assertEqual([c.id for c in self.codes(self.h)], [link.id])

    def test_new_main_member_is_invited_once(self):
        self.assertEqual(self.run_job(), 2)
        member = self.main_member(self.h, "ny@example.invalid")
        self.assertEqual(self.run_job(), 1)
        self.assertEqual(self.run_job(), 0)
        self.assertEqual([m.recipient_id for m in self.mails() if m.herd_id == self.h.id], [self.member.id, member.id])
        self.assertEqual([c.member_id for c in self.codes(self.h) if c.revoked_at is None], [member.id])

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
        self.assertIn("Kaninerna som står registrerade på din besättning är redan ifyllda. Välj för varje kanin", body)
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

    def test_invitation_recommends_code_login_only_when_it_is_on(self):
        self.run_job()
        row = self.mails()[0]
        for flag, tip in (("true", True), ("false", False)):
            with mock.patch.dict(os.environ, KODINLOGGNING=flag):
                variables = {k: v for k, v in self.build(row).items() if k != "attachments"}
                _, body = mail.render(row.kind, variables)
            self.assertEqual("Logga gärna in i Stamboken först" in body, tip)
            self.assertEqual("/auth/sign-in" in body, tip)
            self.assertEqual("Du behöver inte logga in" in body, not tip)
            self.assertEqual("Vill du inte logga in går det bra att använda länken ovan." in body, tip)

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

    def test_recipients_follow_invitation_recipient(self):
        pending = self.herd_with_member("G9004")
        db.Membership.update(membership_status="pending").where(db.Membership.id == pending.membership_id).execute()
        blank = self.herd_with_member("G9005", email="x@example.invalid")
        db.Member.update(email="  ").where(db.Member.membership == blank.membership_id).execute()
        ended = self.herd_with_member("G9006")
        db.Member.update(end_date=date(2025, 1, 1)).where(db.Member.membership == ended.membership_id).execute()
        expected = [report_code.invitation_recipient(h) is not None for h in invite._herds(self.gotland.id)]
        self.assertEqual(
            invite.recipients(self.round_, self.gotland.id),
            {"med_epost": sum(expected), "utan_epost": len(expected) - sum(expected)},
        )
        self.assertEqual(invite.recipients(self.round_, self.gotland.id), {"med_epost": 2, "utan_epost": 4})

    def test_recipients_queries_do_not_grow_with_herds(self):
        def queries():
            with count_queries() as counter:
                invite.recipients(self.round_, self.gotland.id)
            return counter["n"]

        few = queries()
        for n in range(30):
            self.herd_with_member(f"G92{n:02d}")
        self.assertEqual(queries(), few)

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

    def test_the_activation_is_locked_for_update(self):
        # A non-concurrent test cannot show the wait itself, so check that the statement asks for the row lock.
        stale = db.YearlyReportRoundGenebank.get(db.YearlyReportRoundGenebank.genebank == self.gotland.id)
        seen = []
        real = db.DB_PROXY.obj.execute_sql

        def spy(sql, *args, **kwargs):
            seen.append(sql)
            return real(sql, *args, **kwargs)

        with mock.patch.object(db.DB_PROXY.obj, "execute_sql", spy):
            invite._invite_genebank(stale, NOW)
        self.assertTrue([q for q in seen if "yearly_report_round_genebank" in q and "FOR UPDATE" in q])

    def test_a_stale_recipient_never_replaces_the_current_members_link(self):
        # A was the main member when the job chose; B is now, and has an active code.
        current = report_code.invitation_recipient(self.h)
        rival = self.other_member_code(self.h)  # a code for someone who is not the herd's main member any more
        db.ReportAccessCode.update(revoked_at=NOW).where(db.ReportAccessCode.id == rival.id).execute()
        mine = report_code.issue_code(self.h, self.round_, current, now=NOW)
        stale_member = db.Member.get_by_id(rival.member_id)
        with self.assertRaises(report_code.StaleRecipient):
            report_code.issue_code(self.h, self.round_, stale_member, now=NOW)
        self.assertIsNone(db.ReportAccessCode.get_by_id(mine.id).revoked_at)
        self.assertEqual(db.ReportAccessCode.select().where(db.ReportAccessCode.revoked_at.is_null()).count(), 1)
        with self.assertRaises(arsrapport.ArsrapportError):  # new_link says so too, and revokes nothing
            with mock.patch.object(report_code, "invitation_recipient", return_value=stale_member):
                invite.new_link(self.h, self.round_, self.owner, now=NOW)
        self.assertIsNone(db.ReportAccessCode.get_by_id(mine.id).revoked_at)

    def test_priorities_follow_the_mail_queue_spec(self):
        self.run_job()
        invite.new_link(self.h, self.round_, self.owner, now=NOW)
        invite.test_mail(self.round_, self.gotland.id, self.owner)
        self.assertEqual({m.priority for m in self.mails()}, {2, 0})
        self.assertEqual(sorted(m.priority for m in self.mails() if m.params.get("prov")), [0])
        self.assertEqual([m.priority for m in self.mails("arsrapport.ny_lank")], [1])

    def send_all(self, relay):
        with (
            mock.patch.multiple(settings.mail, mode="live", allowlist=[]),
            mock.patch.object(mail.smtplib, "SMTP", relay),
        ):
            mail.send_pending()

    def set_email(self, member, address, by="other"):
        with mock.patch.object(matrikel, "datetime", wraps=datetime) as clock:
            clock.now.return_value = NOW
            return matrikel.set_member_email(member, address, self.manager, by=by)

    def delivered_to(self, row):
        relay = FakeRelay()
        self.send_all(relay)
        return [address for msg, _, (address,) in relay.sent if msg["Message-ID"] == mail.message_id(row.id)]

    def test_new_link_uses_previous_address_until_paper_change_wait_ends(self):
        new = self.set_email(self.member, "ny@example.invalid")
        self.login("man")
        for when, address in (
            (new.email_login_from - timedelta(seconds=1), self.member.email),
            (new.email_login_from, new.email),
        ):
            with self.subTest(when=when.isoformat()):  # xdist serialises subTest params
                self.at(when)
                response = self.api("POST", "/besattning/G9001/2025/ny-lank")
                self.assertEqual(response.status_code, 200, response.data)
                row = self.mails("arsrapport.ny_lank")[-1]
                self.assertEqual((row.recipient_kind, row.recipient_id), ("member", self.member.id))
                self.assertEqual(self.delivered_to(row), [address])

    def test_already_queued_invitation_uses_login_address_at_delivery(self):
        self.run_job()
        row = self.mails()[0]
        self.set_email(self.member, "ny@example.invalid")
        self.assertEqual(self.delivered_to(row), [self.member.email])

    def test_link_hash_only_for_current_address(self):
        new = self.set_email(self.member, "ny@example.invalid")
        self.send_all(FakeRelay())  # deliver the address change notice first
        for when, expected in ((NOW, None), (new.email_login_from, mail.address_hash(new.email))):
            self.at(when)
            for status, reply in (("sent", None), ("failed", _refused(550, "5.1.1 unknown mailbox"))):
                with self.subTest(when=when.isoformat(), status=status):
                    invite.new_link(self.h, self.round_, self.manager, now=when)
                    self.send_all(FakeRelay(replies=[reply]))
                    row = self.mails("arsrapport.ny_lank")[-1]
                    self.assertEqual((row.status, row.address_hash), (status, expected))

    def test_queued_new_link_follows_a_further_verified_address_change(self):
        self.set_email(self.member, "ny@example.invalid")
        invite.new_link(self.h, self.round_, self.manager, now=NOW)
        (row,) = self.mails("arsrapport.ny_lank")
        self.assertEqual((row.recipient_kind, row.recipient_id), ("member", self.member.id))
        verified = self.set_email(self.member, "bekraftad@example.invalid", by="matrikel")
        self.assertEqual(self.delivered_to(row), [verified.email])

    def test_invitation_uses_new_address_if_wait_ends_while_rendering_pdf(self):
        new = self.set_email(self.member, "ny@example.invalid")
        self.run_job()
        row = self.mails()[0]
        self.assertEqual((row.recipient_kind, row.recipient_id), ("member", self.member.id))

        def render_pdf(_context):
            self.at(new.email_login_from)
            return b"%PDF"

        with mock.patch.object(invite, "render_pdf", side_effect=render_pdf):
            self.assertEqual(self.delivered_to(row), [new.email])

    def test_previous_address_purge_preserves_queued_links(self):
        second = db.Member.get(db.Member.membership == self.h2.membership_id)
        new = self.set_email(self.member, "ny@example.invalid")
        other = self.set_email(second, "annan@example.invalid")
        self.run_job()
        old_invite = self.mails()[0]
        invite.new_link(self.h2, self.round_, self.manager, now=NOW)
        (link,) = self.mails("arsrapport.ny_lank")

        later = db.MemberPreviousAddress.get(db.MemberPreviousAddress.member == self.member.id).purge_at + timedelta(
            days=1
        )
        self.at(later)
        self.assertEqual(matrikel.purge_previous_addresses(later), 2)
        relay = FakeRelay()
        self.send_all(relay)
        delivered = {msg["Message-ID"]: address for msg, _, (address,) in relay.sent}
        self.assertEqual(delivered.get(mail.message_id(old_invite.id)), new.email)
        self.assertEqual(delivered.get(mail.message_id(link.id)), other.email)

    def test_member_erasure_cancels_queued_links(self):
        self.set_email(self.member, "ny@example.invalid")
        self.run_job()
        invitation = self.mails()[0]
        invite.new_link(self.h, self.round_, self.manager, now=NOW)
        (link,) = self.mails("arsrapport.ny_lank")
        matrikel.anonymize_person(self.member, self.manager)
        for row in (invitation, link):
            self.assertEqual(db.MailMessage.get_by_id(row.id).status, "cancelled")
            self.assertEqual((row.recipient_kind, row.recipient_id), ("member", self.member.id))

    def test_new_link_while_building_invitation_only_delivers_new_code(self):
        db.Herd.update(is_active=False).where(db.Herd.id == self.h2.id).execute()
        self.assertEqual(self.run_job(), 1)
        (invitation,) = self.mails()

        def render_pdf(herd, round_):
            invite.new_link(herd, round_, self.manager, now=NOW)

        relay = FakeRelay()
        real = invite.extract_context
        with mock.patch.object(invite, "extract_context", side_effect=lambda h, r: (render_pdf(h, r), real(h, r))[1]):
            self.send_all(relay)
        ((msg, _, (address,)),) = relay.sent
        (link,) = self.mails("arsrapport.ny_lank")
        (token,) = re.findall(r"/rapport#(\S+)", msg.get_body().get_content())
        self.assertEqual((msg["Message-ID"], address), (mail.message_id(link.id), self.member.email))
        self.assertEqual(report_code.resolve(token).id, link.params["code_id"])
        self.assertEqual(db.MailMessage.get_by_id(invitation.id).status, "cancelled")

    def test_main_member_replaced_while_building_invitation_cancels_mail(self):
        self.run_job()
        row = self.mails()[0]

        def render_pdf(herd, _round):
            if herd.id == self.h.id:
                db.Herd.update(membership=self.h2.membership_id).where(db.Herd.id == herd.id).execute()

        real = invite.extract_context
        with mock.patch.object(invite, "extract_context", side_effect=lambda h, r: (render_pdf(h, r), real(h, r))[1]):
            self.assertEqual(self.delivered_to(row), [])
        self.assertEqual(db.MailMessage.get_by_id(row.id).status, "cancelled")

    def test_first_address_during_paper_change_wait_skips_invitation_and_refuses_new_link(self):
        member = db.Member.get(db.Member.membership == self.h3.membership_id)
        self.set_email(member, "forsta@example.invalid")
        self.login("man")
        response = self.api("POST", "/besattning/G9003/2025/ny-lank")
        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("logga in", response.get_json()["detail"])
        self.assertEqual(invite.recipients(self.round_, self.gotland.id), {"med_epost": 2, "utan_epost": 1})
        with self.assertLogs(invite.logger, level="WARNING") as log:
            self.assertEqual(self.run_job(), 2)
        self.assertTrue(any(f"besättning {self.h3.id} saknar" in line for line in log.output))
        self.assertEqual(self.codes(self.h3), [])

    def test_skipped_herd_is_invited_once_when_its_first_address_counts(self):
        member = db.Member.get(db.Member.membership == self.h3.membership_id)
        ready = self.set_email(member, "forsta@example.invalid").email_login_from
        for when, expected in ((NOW, 2), (ready - timedelta(seconds=1), 0)):
            with self.assertLogs(invite.logger, level="WARNING") as log:
                self.assertEqual(invite.send_due_invitations(when), expected)
            self.assertTrue(any(f"besättning {self.h3.id} saknar" in line for line in log.output))
        self.assertEqual(invite.send_due_invitations(ready), 1)
        self.assertEqual(invite.send_due_invitations(ready), 0)
        self.assertEqual([row.herd_id for row in self.mails()], [self.h.id, self.h2.id, self.h3.id])
        self.assertEqual([len(self.codes(h)) for h in (self.h, self.h2, self.h3)], [1, 1, 1])

    def test_skipped_herd_gets_no_invitation_after_end_date(self):
        member = db.Member.get(db.Member.membership == self.h3.membership_id)
        ready = self.set_email(member, "forsta@example.invalid").email_login_from
        end = ready.date() - timedelta(days=1)
        db.YearlyReportRound.update(deadline=end, end_date=end).where(
            db.YearlyReportRound.id == self.round_.id
        ).execute()
        self.assertEqual(self.run_job(), 2)
        self.assertEqual(invite.send_due_invitations(ready), 0)
        self.assertEqual(self.codes(self.h3), [])

    def test_queued_invitation_cancelled_when_previous_address_has_expired(self):
        self.run_job()
        row = self.mails()[0]
        self.set_email(self.member, "ny@example.invalid")
        db.MemberPreviousAddress.update(login_until=arsrapport.now()).where(
            db.MemberPreviousAddress.member == self.member.id
        ).execute()
        self.assertEqual(self.delivered_to(row), [])
        self.assertEqual(db.MailMessage.get_by_id(row.id).status, "cancelled")

    def test_no_token_in_rows_after_sending_failing_and_bouncing(self):  # R5
        self.run_job()
        macs = [report_code.code_url(c).split("#")[1].split(".")[1] for h in (self.h, self.h2) for c in self.codes(h)]
        urls = [report_code.code_url(c) for h in (self.h, self.h2) for c in self.codes(h)]
        # the first mail is refused with a text quoting its link, the second goes through and then bounces
        relay = FakeRelay(replies=[_refused(550, f"5.7.1 rejected, body had {urls[0]}", "g9001@example.invalid"), None])
        self.send_all(relay)
        first, second = self.mails()
        self.assertEqual((first.status, second.status), ("failed", "sent"))
        self.assertTrue(mail.record_bounce(mail.message_id(second.id), f"550 5.1.1 returned: {urls[1]}"))
        for table in (db.MailMessage, db.MailAttempt):
            for row in table.select().dicts():
                for mac in macs:
                    self.assertNotIn(mac, repr(row))

    def test_new_link_mail_goes_through_the_queue_after_submission(self):
        self.run_job()
        (rabbit, _) = list(db.Individual.select().where(db.Individual.origin_herd == self.h.id))
        self.reported(self.h, self.kvar(rabbit, vikt=2.8))
        new = invite.new_link(self.h, self.round_, self.owner, now=NOW)
        relay = FakeRelay()
        self.send_all(relay)
        (row,) = self.mails("arsrapport.ny_lank")
        self.assertEqual(db.MailMessage.get_by_id(row.id).status, "sent")
        sent = [m for m, _, _ in relay.sent if "Ny länk" in m["Subject"]]
        self.assertEqual(len(sent), 1)
        (token,) = re.findall(r"/rapport#(\S+)", sent[0].get_body().get_content())
        self.assertEqual(report_code.resolve(token).id, new.id)

    def spy_sql(self):
        seen = []
        real = db.DB_PROXY.obj.execute_sql

        def spy(sql, params=None, *args, **kwargs):
            seen.append(sql)
            return real(sql, params, *args, **kwargs)

        patcher = mock.patch.object(db.DB_PROXY.obj, "execute_sql", spy)
        patcher.start()
        self.addCleanup(patcher.stop)
        return seen

    def assert_lock_comes_first(self, seen):
        locks = [i for i, q in enumerate(seen) if "pg_advisory_xact_lock" in q]
        touched = [i for i, q in enumerate(seen) if "report_access_code" in q or 'FROM "member"' in q]
        self.assertTrue(locks and touched and locks[0] < touched[0], seen)

    def test_issuing_and_replacing_a_link_take_the_herd_lock_first(self):
        # Not a concurrency test: it shows the per-herd lock is taken before any code or recipient statement.
        # Lock order: this lock, then code rows. It is never taken under lock_report, and nothing here takes
        # lock_report, so a submission (lock_report, then FOR SHARE on its code row) cannot form a cycle with it.
        seen = self.spy_sql()
        report_code.issue_code(self.h, self.round_, self.member, now=NOW)
        self.assert_lock_comes_first(seen)
        seen.clear()
        invite.new_link(self.h, self.round_, self.owner, now=NOW)
        self.assert_lock_comes_first(seen)

    def test_new_link_answers_409_when_issue_code_finds_the_member_stale(self):
        self.run_job()
        old = self.codes(self.h)[0]
        with mock.patch.object(report_code, "issue_code", side_effect=report_code.StaleRecipient("changed")):
            with self.assertRaises(arsrapport.ArsrapportError) as caught:
                invite.new_link(self.h, self.round_, self.owner, now=NOW)
        self.assertEqual(caught.exception.status, 409)
        self.assertIsNone(db.ReportAccessCode.get_by_id(old.id).revoked_at)
        self.assertEqual(self.mails("arsrapport.ny_lank"), [])

    def test_new_link_and_a_legacy_year_change_take_the_round_row_first(self):  # Codex: no deadlock
        """
        The legacy PATCH holds the round row FOR UPDATE (report_year is a unique key) and then updates the codes;
        the replacement code's insert takes the round row's key-share lock. new_link takes the round row first.
        """
        if not _USE_POSTGRES:
            self.skipTest("row locks need PostgreSQL")
        self.run_job()
        revoked, original, results = threading.Event(), report_code.revoke, {}

        def revoke_then_wait(code, *, now):
            original(code, now=now)  # the old code's row is held from here
            revoked.set()
            until(lock_waiter)  # the year change waits for a lock before the replacement goes in

        def link():
            return invite.new_link(self.h, self.round_, self.owner, now=NOW).id

        def year():
            revoked.wait(10)
            return da.update_yearly_report_round(self.round_.id, {"report_year": 2024}, self.admin.uuid)["status"]

        with mock.patch.object(report_code, "revoke", side_effect=revoke_then_wait):
            done = run_all(in_thread(results, "link", link), in_thread(results, "year", year))
        self.assertTrue(done, "hung threads")
        self.assertEqual(results["year"], "success", results)
        new = db.ReportAccessCode.get_by_id(results["link"])
        self.assertIsNone(new.revoked_at)
        self.assertEqual((new.round.report_year, new.expires_at), (2024, self.round_.end_date))
