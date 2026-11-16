#!/usr/bin/env python3
"""
Tests for the yearly report's access codes (step 3, Task 1): issue, revoke, token, validity and the code as actor.
Synthetic herds and addresses only.

isort:skip_file
"""

import threading
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.mail as mail
import utils.report_code as report_code
import utils.settings as settings
from utils.report_code import CodeActor, actor_key

from tests.arsrapport_fixtures import ArsrapportTest

NOW = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
TODAY = date(2026, 1, 15)


class ReportCodeTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.multiple(settings.mail, link_secret="test-link-secret", link_hosts=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.round_ = self.round(2025)
        self.herd = db.Herd.create(genebank=self.gotland, herd="G9001", herd_name="Testbesättning", is_active=True)
        self.member = self.main_member(self.herd, "g9001@example.invalid")

    def issue(self, herd=None, member=None):
        return report_code.issue_code(herd or self.herd, self.round_, member or self.member, now=NOW)

    def test_issue_is_idempotent_per_herd_and_round(self):
        self.assertEqual(self.issue().id, self.issue().id)
        self.assertEqual(db.ReportAccessCode.select().count(), 1)
        self.assertEqual(self.issue().expires_at, self.round_.end_date)

    def test_revoke_then_issue_gives_a_new_code(self):
        first = self.issue()
        report_code.revoke(first, now=NOW)
        self.assertIsNotNone(db.ReportAccessCode.get_by_id(first.id).revoked_at)
        self.assertNotEqual(self.issue().id, first.id)

    def test_resolve_rejects_forged_and_foreign_purpose(self):
        code = self.issue()
        self.assertEqual(report_code.resolve(report_code.code_url(code).rsplit("#", 1)[1]).id, code.id)
        self.assertIsNone(report_code.resolve(mail.link_token("andringar", code.id)))
        good = mail.link_token("rapport", code.id)
        self.assertIsNone(report_code.resolve(good[:-1] + ("A" if good[-1] != "A" else "B")))
        self.assertIsNone(report_code.resolve(f"{code.id + 99}.{good.split('.')[1]}"))
        self.assertIsNone(report_code.resolve("not a token"))
        # L8: a valid mac for an id with no row, which is the path a forged id never takes
        self.assertIsNone(report_code.resolve(mail.link_token("rapport", code.id + 999)))

    def test_link_from_old_host_still_verifies(self):
        code = self.issue()
        with mock.patch.object(mail, "_hostname", return_value="gammal.example.invalid"):
            old = mail.link_token("rapport", code.id)
        self.assertIsNone(report_code.resolve(old))
        with mock.patch.object(settings.mail, "link_hosts", ["gammal.example.invalid"]):
            self.assertEqual(report_code.resolve(old).id, code.id)
            self.assertIn(mail.link_token("rapport", code.id), report_code.code_url(code))  # built with the new host

    def test_refusal_reasons(self):
        code = self.issue()
        self.assertIsNone(report_code.refusal(code, self.herd, today=TODAY))
        end = self.round_.end_date
        self.assertEqual(report_code.refusal(code, self.herd, today=end + timedelta(days=1)), "utgangen")
        self.assertIsNone(report_code.refusal(code, self.herd, today=end))
        inactive = db.Herd.get_by_id(self.herd.id)
        inactive.is_active = False
        self.assertEqual(report_code.refusal(code, inactive, today=TODAY), "inaktiv")
        db.Member.update(end_date=date(2026, 1, 1)).where(db.Member.id == self.member.id).execute()
        db.Member.create(
            first_name="Ny",
            last_name="Medlem",
            email="ny@example.invalid",
            membership=self.herd.membership,
            role="huvudmedlem",
        )
        self.assertEqual(report_code.refusal(code, self.herd, today=TODAY), "ny_huvudmedlem")
        report_code.revoke(code, now=NOW)
        self.assertEqual(report_code.refusal(code, self.herd, today=TODAY), "aterkallad")

    def test_ended_membership_invalidates_code(self):
        code = self.issue()
        for status in ("inactive", "pending", "friexemplar"):
            db.Membership.update(membership_status=status).where(db.Membership.id == self.herd.membership_id).execute()
            self.assertEqual(report_code.refusal(code, self.herd, today=TODAY), "ingen_mottagare", status)
        db.Membership.update(membership_status="active").where(db.Membership.id == self.herd.membership_id).execute()
        self.assertIsNone(report_code.refusal(code, self.herd, today=TODAY))
        db.Member.update(email=None).where(db.Member.id == self.member.id).execute()
        self.assertEqual(report_code.refusal(code, self.herd, today=TODAY), "ingen_mottagare")

    def test_code_url_has_no_herd_or_name(self):
        url = report_code.code_url(self.issue())
        self.assertRegex(url, r"^https?://[^/]+/rapport#\d+\.[A-Za-z0-9_-]{22}$")
        self.assertNotIn("G9001", url)

    def test_extended_round_extends_codes(self):
        code = self.issue()
        old_end = self.round_.end_date
        self.at(date(2026, 1, 15))
        revoked = report_code.issue_code(
            db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True), self.round_, self.member, now=NOW
        )
        report_code.revoke(revoked, now=NOW)
        arsrapport.save_round(2025, self.admin, end_date=old_end + timedelta(days=14))
        self.assertEqual(db.ReportAccessCode.get_by_id(code.id).expires_at, old_end + timedelta(days=14))
        self.assertEqual(db.ReportAccessCode.get_by_id(revoked.id).expires_at, old_end)
        later = db.ReportAccessCode.get_by_id(code.id)
        self.assertIsNone(report_code.refusal(later, self.herd, today=old_end + timedelta(days=10)))

    def test_actor_shape_for_roles_for(self):
        actor = CodeActor(self.issue())
        self.assertIsNone(actor.id)
        self.assertEqual(actor.access_code_id, actor.code.id)
        self.assertEqual(actor.username, "länk G9001/2025")
        for value in (actor.is_manager, actor.is_helper, actor.transfer_herd_ids(), actor.effective_herd_ids()):
            self.assertEqual(value, frozenset())
            self.assertEqual(value - frozenset({1}), frozenset())
        self.assertFalse(actor.can_edit(1))

    def test_actor_key_separates_users_and_codes(self):
        code = self.issue()
        self.assertEqual(actor_key(CodeActor(code)), ("code", code.id))
        self.assertEqual(actor_key(self.owner), ("user", self.owner.id))
        self.assertNotEqual(actor_key(CodeActor(code)), actor_key(self.owner))

    def test_issue_survives_a_lost_race(self):
        """L5: the loser of two concurrent issues re-reads and returns the winner's code."""
        winner = self.issue()
        real = report_code._active  # pylint: disable=protected-access
        calls = []

        def stale(herd, round_):  # the first read saw no code, as a transaction that started before the winner's
            calls.append(1)
            return None if len(calls) == 1 else real(herd, round_)

        with mock.patch.object(report_code, "_active", stale):
            self.assertEqual(self.issue().id, winner.id)
        self.assertEqual(db.ReportAccessCode.select().count(), 1)

    def test_issue_from_two_connections_gives_one_code(self):
        results, barrier = [], threading.Barrier(2)

        def run():
            try:
                barrier.wait(timeout=10)
                results.append(report_code.issue_code(self.herd, self.round_, self.member, now=NOW).id)
            finally:
                db.DB_PROXY.close()

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(len(results), 2, "a thread raised")
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(db.ReportAccessCode.select().count(), 1)

    def test_a_code_for_an_earlier_main_member_is_replaced(self):
        old = self.issue()
        db.Member.update(end_date=date(2026, 1, 1)).where(db.Member.id == self.member.id).execute()
        new_member = db.Member.create(
            first_name="Ny",
            last_name="Huvud",
            email="ny@example.invalid",
            membership=self.herd.membership,
            role="huvudmedlem",
        )
        fresh = self.issue(member=new_member)
        self.assertNotEqual(fresh.id, old.id)
        self.assertIsNotNone(db.ReportAccessCode.get_by_id(old.id).revoked_at)
        self.assertEqual(fresh.member_id, new_member.id)
        self.assertEqual(self.issue(member=new_member).id, fresh.id)
