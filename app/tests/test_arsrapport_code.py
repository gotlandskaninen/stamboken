#!/usr/bin/env python3
"""
Tests for the yearly report through the personal link (step 3, Task 4): the report service with a CodeActor, as
the step-2 owner tests have it with an account. Synthetic herds, rabbits and addresses only.

isort:skip_file
"""

from datetime import date, timedelta
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.report_code as report_code
import utils.settings as settings
from herdbook import APP
from utils.arsrapport import ArsrapportError
from utils.report_code import CodeActor

from tests.arsrapport_fixtures import ArsrapportTest

DAY0 = date(2026, 1, 10)
WRITTEN = (
    db.HerdTracking,
    db.IndividualCommand,
    db.Weight,
    db.YearlyHerdReport,
    db.YearlyReportSubmission,
    db.YearlyReportDraft,
    db.MailMessage,
)


class CodeReportTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        context = APP.app_context()  # request_hash reads the app's secret key
        context.push()
        self.addCleanup(context.pop)
        patcher = mock.patch.multiple(settings.mail, link_secret="test-link-secret", link_hosts=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.day(0)
        self.round_ = self.round(2025)
        self.h = db.Herd.create(genebank=self.gotland, herd="G9001", herd_name="Testbesättning", is_active=True)
        self.g9002 = db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.owner.add_role("owner", self.h.id)
        self.member = self.main_member(self.h, "g9001@example.invalid")
        self.code = report_code.issue_code(self.h, self.round_, self.member, now=arsrapport.now())
        self.rabbits_ = self.rabbits(self.h, 4)
        self.entries = [self.kvar(rabbit, vikt=2.8) for rabbit in self.rabbits_]

    def day(self, n):
        self.at(DAY0 + timedelta(days=n))

    def access(self, code=None):
        return arsrapport.code_access(self.h, self.round_, [(code or self.code).id])

    def send(self, body, code=None, access=None):
        code = code or self.code
        sub = arsrapport.parse_submission(body, paper=False)
        return arsrapport.submit(self.h, self.round_, access or self.access(code), CodeActor(code), sub)

    def withdraw(self, revision, code=None):
        code = code or self.code
        return arsrapport.withdraw(self.h, self.round_, self.access(code), CodeActor(code), revision=revision)

    def counts(self):
        return [model.select().count() for model in WRITTEN]

    def report(self):
        return db.YearlyHerdReport.get(db.YearlyHerdReport.herd == self.h.id)

    def refused(self, call, status, code=None):
        with self.assertRaises(ArsrapportError) as caught:
            call()
        self.assertEqual(caught.exception.status, status)
        if code is not None:
            self.assertEqual(caught.exception.extra.get("code"), code)
        return caught.exception

    def test_code_access_is_the_sessions_valid_code_for_the_herd(self):
        access = self.access()
        self.assertEqual((access.role, access.source, access.can_sell, access.editor), ("code", "link", False, False))
        self.assertEqual(access.code.id, self.code.id)
        other = report_code.issue_code(
            self.g9002, self.round_, self.main_member(self.g9002, "g9002@example.invalid"), now=arsrapport.now()
        )
        self.assertIsNone(arsrapport.code_access(self.h, self.round_, [other.id]))
        self.assertIsNone(arsrapport.code_access(self.h, self.round_, []))
        report_code.revoke(self.code, now=arsrapport.now())
        self.refused(lambda: self.access(), 403, "lank_ogiltig")

    def test_code_submit_change_withdraw(self):
        receipt = self.send(self.body(*self.entries))
        report = self.report()
        self.assertEqual((report.source, report.generated_by_id, report.access_code_id), ("link", None, self.code.id))
        submission = db.YearlyReportSubmission.get()
        self.assertEqual(
            (submission.source, submission.user_id, submission.access_code_id), ("link", None, self.code.id)
        )
        row = db.HerdTracking.get(
            db.HerdTracking.individual == self.rabbits_[0].id, db.HerdTracking.kind == "ATTESTATION"
        )
        self.assertEqual((row.signature_id, row.access_code_id), (None, self.code.id))
        mail = db.MailMessage.get()
        self.assertEqual(
            (mail.kind, mail.recipient_id, mail.created_by_id), ("arsrapport.kvitto", self.member.id, None)
        )
        self.assertEqual(receipt["report_id"], report.id)

        self.day(5)  # Ändra: one rabbit turns out dead, the others are as before
        dead = self.rabbits_[0]
        self.send(self.body(self.dod(dead, 2025, 11, 20), *self.entries[1:], revision=1))
        self.assertEqual(db.Individual.get_by_id(dead.id).death_date, date(2025, 11, 20))
        voided = db.HerdTracking.get_by_id(row.id)
        self.assertEqual((voided.voided_by_user_id, voided.voided_by_access_code_id), (None, self.code.id))
        self.assertEqual(self.report().revision, 2)
        self.assertEqual(db.YearlyReportSubmission.select().count(), 2)
        self.assertEqual(
            db.YearlyReportSubmission.select().where(db.YearlyReportSubmission.user.is_null(False)).count(), 0
        )
        self.assertEqual(
            [m.kind for m in db.MailMessage.select().order_by(db.MailMessage.id)],
            ["arsrapport.kvitto", "arsrapport.andrad"],
        )

        self.day(6)
        view = self.withdraw(2)
        report = self.report_by_status("voided")
        self.assertEqual((report.voided_by_user_id, report.voided_by_access_code_id), (None, self.code.id))
        self.assertIsNone(view["report"])
        draft = db.YearlyReportDraft.get()
        self.assertEqual((draft.updated_by_user_id, draft.updated_by_access_code_id), (None, self.code.id))
        self.assertIsNone(db.Individual.get_by_id(dead.id).death_date)
        self.assertFalse(
            db.HerdTracking.select()
            .where(
                db.HerdTracking.individual == self.rabbits_[1].id,
                db.ht_not_voided(),
                db.HerdTracking.kind == "ATTESTATION",
            )
            .exists()
        )
        self.assertEqual(
            db.MailMessage.select().where(db.MailMessage.kind == "arsrapport.angrad").get().created_by_id, None
        )

    def report_by_status(self, status):
        return db.YearlyHerdReport.get(db.YearlyHerdReport.herd == self.h.id, db.YearlyHerdReport.status == status)

    def test_code_withdraw_window_is_seven_days(self):
        self.send(self.body(*self.entries))
        self.day(8)
        before = self.counts()
        exc = self.refused(lambda: self.withdraw(1), 403)
        self.assertEqual(exc.detail, arsrapport.WITHDRAW_LATE)
        self.assertEqual(self.counts(), before)

    def test_code_sale_refused(self):
        entries = [self.sald(self.rabbits_[0], "G9002", 2025, 12, 20), *self.entries[1:]]
        message = "Försäljningen registrerar du hos genbanksansvarig. Ring eller mejla."
        refusals, _ = arsrapport.check(
            self.h,
            self.round_,
            self.access(),
            None,
            arsrapport.parse_submission(self.body(*entries), paper=False),
            on=arsrapport.today(),
        )
        self.assertEqual([(r.code, r.message) for r in refusals], [("salj_via_lank", message)])
        before = self.counts()
        exc = self.refused(lambda: self.send(self.body(*entries)), 422)
        self.assertEqual([r["code"] for r in exc.extra["refusals"]], ["salj_via_lank"])
        self.assertEqual(self.counts(), before)

    def test_code_checked_again_under_lock(self):
        access = self.access()  # the dry run's view, before the manager revokes the code
        report_code.revoke(self.code, now=arsrapport.now())
        before = self.counts()
        self.refused(lambda: self.send(self.body(*self.entries), access=access), 403, "lank_ogiltig")
        self.assertEqual(self.counts(), before)

    def test_withdraw_checked_again_under_lock(self):
        self.send(self.body(*self.entries))
        access = self.access()
        report_code.revoke(self.code, now=arsrapport.now())
        before = self.counts()
        self.refused(
            lambda: arsrapport.withdraw(self.h, self.round_, access, CodeActor(self.code), revision=1),
            403,
            "lank_ogiltig",
        )
        self.assertEqual(self.counts(), before)

    def test_draft_checked_again_under_lock(self):
        access = self.access()
        report_code.revoke(self.code, now=arsrapport.now())
        self.refused(
            lambda: arsrapport.save_draft(
                self.h, self.round_, access, CodeActor(self.code), self.body(*self.entries), None, None, None
            ),
            403,
            "lank_ogiltig",
        )
        self.assertFalse(db.YearlyReportDraft.select().exists())

    def test_new_main_member_invalidates_code(self):
        access = self.access()
        db.Member.update(end_date=date(2026, 1, 1)).where(db.Member.id == self.member.id).execute()
        db.Member.create(
            first_name="Ny",
            last_name="Huvudmedlem",
            email="ny@example.invalid",
            membership=self.h.membership,
            role="huvudmedlem",
        )
        before = self.counts()
        self.refused(lambda: self.send(self.body(*self.entries), access=access), 403, "lank_ogiltig")
        self.assertEqual(self.counts(), before)

    def test_draft_by_code_and_own_flag(self):
        actor = CodeActor(self.code)
        draft = arsrapport.save_draft(
            self.h, self.round_, self.access(), actor, self.body(*self.entries), None, None, None
        )
        self.assertEqual((draft.updated_by_user_id, draft.updated_by_access_code_id), (None, self.code.id))
        self.assertTrue(arsrapport.draft_json(draft, actor)["own"])
        self.assertFalse(arsrapport.draft_json(draft, self.owner)["own"])
        self.assertFalse(arsrapport.draft_json(draft, CodeActor(self.other_code()))["own"])
        draft.updated_by_user, draft.updated_by_access_code = (
            self.owner.id,
            None,
        )  # a user's draft, and a code's id equal to the user's
        self.assertFalse(arsrapport.draft_json(draft, actor)["own"])

    def other_code(self):
        report_code.revoke(self.code, now=arsrapport.now())
        return report_code.issue_code(self.h, self.round_, self.member, now=arsrapport.now())

    def test_retry_found_only_for_same_actor(self):
        body = self.body(*self.entries)
        first = self.send(body)
        sub = arsrapport.parse_submission(body, paper=False)
        digest = arsrapport.request_hash(sub)
        same = arsrapport.find_submission(sub.key, self.h, self.round_, CodeActor(self.code), digest)
        self.assertEqual(arsrapport.receipt(same)["report_id"], first["report_id"])
        for stranger in (CodeActor(self.other_code()), self.owner):
            with self.subTest(stranger=type(stranger).__name__):
                self.refused(
                    lambda stranger=stranger: arsrapport.find_submission(
                        sub.key, self.h, self.round_, stranger, digest
                    ),
                    409,
                )
        same_id = mock.Mock(id=self.code.id, spec=["id"])  # a user whose id equals the code's
        self.refused(lambda: arsrapport.find_submission(sub.key, self.h, self.round_, same_id, digest), 409)

    def test_account_submission_is_not_found_by_a_code(self):
        body = self.body(*self.entries)
        sub = arsrapport.parse_submission(body, paper=False)
        arsrapport.submit(self.h, self.round_, arsrapport.Access("owner"), self.owner, sub)
        self.refused(
            lambda: arsrapport.find_submission(
                sub.key, self.h, self.round_, CodeActor(self.code), arsrapport.request_hash(sub)
            ),
            409,
        )

    def test_code_change_of_an_account_report(self):
        """A report an owner sent can be changed through the link, which then writes as the code."""
        arsrapport.submit(
            self.h,
            self.round_,
            arsrapport.Access("owner"),
            self.owner,
            arsrapport.parse_submission(self.body(*self.entries), paper=False),
        )
        self.day(2)
        self.send(self.body(self.dod(self.rabbits_[0], 2025, 11, 20), *self.entries[1:], revision=1))
        report = self.report()
        self.assertEqual(
            (report.source, report.generated_by_id, report.access_code_id), ("link", self.owner.id, self.code.id)
        )
        row = db.HerdTracking.get(
            db.HerdTracking.individual == self.rabbits_[0].id, db.HerdTracking.kind == "ATTESTATION"
        )
        self.assertEqual((row.voided_by_user_id, row.voided_by_access_code_id), (None, self.code.id))
