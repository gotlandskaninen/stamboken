#!/usr/bin/env python3
"""
Tests for the report endpoints with a code session (step 3, Task 5): which actor a request runs as, and what a
link can and cannot reach. Synthetic herds, rabbits and addresses only.

isort:skip_file
"""

from datetime import date, timedelta
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.mail as mail
import utils.report_code as report_code
import utils.settings as settings

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


class CodeApiTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.multiple(settings.mail, link_secret="test-link-secret", link_hosts=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.at(DAY0)
        self.round_ = self.round(2025)
        self.h = db.Herd.create(genebank=self.gotland, herd="G9001", herd_name="Testbesättning", is_active=True)
        self.h2 = db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.owner.add_role("owner", self.h.id)
        self.member = self.main_member(self.h, "g9001@example.invalid")
        self.member2 = self.main_member(self.h2, "g9002@example.invalid")
        self.code = report_code.issue_code(self.h, self.round_, self.member, now=arsrapport.now())
        self.code2 = report_code.issue_code(self.h2, self.round_, self.member2, now=arsrapport.now())
        self.rabbits_ = self.rabbits(self.h, 3)
        self.rabbits2 = self.rabbits(self.h2, 3)

    def open_link(self, code=None, client=None):
        code = code or self.code
        response = (client or self.client).get(f"/api/v2/rapport/oppna/{mail.link_token('rapport', code.id)}")
        self.assertEqual(response.status_code, 303)

    def body_for(self, rabbits, **fields):
        return self.body(*[self.kvar(rabbit, vikt=2.8) for rabbit in rabbits], **fields)

    def skicka(self, herd, rabbits, **fields):
        return self.api("POST", f"/besattning/{herd}/2025/skicka", **self.body_for(rabbits, **fields))

    def counts(self):
        return [model.select().count() for model in WRITTEN]

    def test_code_session_reads_and_writes_its_herd(self):
        self.open_link()
        view = self.api("GET", "/besattning/G9001/2025")
        self.assertEqual(view.status_code, 200, view.get_data(as_text=True))
        data = view.get_json()
        self.assertEqual((data["access"], data["source"], data["can_sell"]), ("code", "link", False))
        self.assertEqual(len(data["rabbits"]), 3)
        draft = self.api("PUT", "/besattning/G9001/2025/utkast", data=self.body_for(self.rabbits_), revision=None)
        self.assertEqual(draft.status_code, 200, draft.get_data(as_text=True))
        self.assertEqual(db.YearlyReportDraft.get().updated_by_access_code_id, self.code.id)
        dry = self.api("POST", "/besattning/G9001/2025/torrkorning", **self.body_for(self.rabbits_))
        self.assertEqual((dry.status_code, dry.get_json()["ok"]), (200, True), dry.get_data(as_text=True))
        sent = self.skicka("G9001", self.rabbits_)
        self.assertEqual(sent.status_code, 200, sent.get_data(as_text=True))
        report = db.YearlyHerdReport.get()
        self.assertEqual((report.source, report.access_code_id), ("link", self.code.id))
        self.assertEqual(self.api("GET", "/besattning/G9001/2025").get_json()["report"]["status"], "submitted")
        out = self.api("POST", "/besattning/G9001/2025/dra-tillbaka", revision=report.revision, reason=None)
        self.assertEqual(out.status_code, 200, out.get_data(as_text=True))
        self.assertEqual(db.YearlyHerdReport.get_by_id(report.id).voided_by_access_code_id, self.code.id)

    def test_retry_gets_its_receipt_only_while_the_code_is_valid(self):
        """Codex 5: E4 holds for a receipt too; a revoked link answers lank_ogiltig, not the receipt and not 409."""
        self.open_link()
        body = self.body_for(self.rabbits_)
        first = self.api("POST", "/besattning/G9001/2025/skicka", **body)
        self.assertEqual(first.status_code, 200)
        again = self.api("POST", "/besattning/G9001/2025/skicka", **body)
        self.assertEqual((again.status_code, again.get_json()), (200, first.get_json()))
        report_code.revoke(self.code, now=arsrapport.now())
        gone = self.api("POST", "/besattning/G9001/2025/skicka", **body)
        self.assertEqual((gone.status_code, gone.get_json()["code"]), (403, "lank_ogiltig"))

    def test_retry_after_login_gets_the_links_receipt(self):
        """Opus L6: the response was lost, the member logged in, and the same request comes again."""
        self.open_link()
        body = self.body_for(self.rabbits_)
        first = self.api("POST", "/besattning/G9001/2025/skicka", **body)
        self.assertEqual(first.status_code, 200)
        self.login("owner")
        self.open_link()  # the member opens the link again after logging in
        again = self.api("POST", "/besattning/G9001/2025/skicka", **body)
        self.assertEqual((again.status_code, again.get_json()), (200, first.get_json()))

    def test_retry_after_a_reissue_is_refused_not_409(self):
        self.open_link()
        body = self.body_for(self.rabbits_)
        self.assertEqual(self.api("POST", "/besattning/G9001/2025/skicka", **body).status_code, 200)
        report_code.revoke(self.code, now=arsrapport.now())
        new = report_code.issue_code(self.h, self.round_, self.member, now=arsrapport.now())
        self.open_link(new)  # the session holds the old, revoked code and the new one
        again = self.api("POST", "/besattning/G9001/2025/skicka", **body)
        self.assertEqual((again.status_code, again.get_json()["code"]), (403, "lank_ogiltig"))

    def test_code_session_cannot_reach_another_herd(self):
        self.open_link()
        before = self.counts()
        for method, suffix in (("GET", ""), ("PUT", "/utkast"), ("POST", "/torrkorning"), ("POST", "/dra-tillbaka")):
            response = self.api(method, f"/besattning/G9002/2025{suffix}", revision=None, data={})
            self.assertEqual(response.status_code, 404, (method, suffix))
        self.assertEqual(self.skicka("G9002", self.rabbits2).status_code, 404)
        self.assertEqual(self.counts(), before)

    def test_two_codes_write_only_their_own_herd(self):
        self.open_link()
        self.open_link(self.code2)
        wrong = self.skicka("G9001", self.rabbits2)  # the other herd's rabbits, with the right code
        self.assertEqual(wrong.status_code, 422)
        self.assertEqual(db.YearlyHerdReport.select().count(), 0)
        for herd, rabbits, code in (("G9002", self.rabbits2, self.code2), ("G9001", self.rabbits_, self.code)):
            self.assertEqual(self.skicka(herd, rabbits).status_code, 200)
            report = db.YearlyHerdReport.get(db.YearlyHerdReport.herd == db.Herd.get(db.Herd.herd == herd).id)
            self.assertEqual((report.source, report.access_code_id), ("link", code.id))

    def test_logged_in_user_with_own_herd_uses_account(self):
        self.login("owner")
        self.open_link()
        view = self.api("GET", "/besattning/G9001/2025").get_json()
        self.assertEqual((view["access"], view["source"]), ("owner", "login"))
        self.assertEqual(self.skicka("G9001", self.rabbits_).status_code, 200)
        report = db.YearlyHerdReport.get()
        self.assertEqual((report.source, report.generated_by_id, report.access_code_id), ("login", self.owner.id, None))

    def test_forwarded_link_in_a_members_browser_reaches_only_its_herd(self):
        """Review Focus 1: the member's own herd still uses the account, the forwarded link's herd the link."""
        self.login("owner")
        self.open_link(self.code2)
        own = self.api("GET", "/besattning/G9001/2025").get_json()
        forwarded = self.api("GET", "/besattning/G9002/2025").get_json()
        self.assertEqual((own["access"], own["source"]), ("owner", "login"))
        self.assertEqual((forwarded["access"], forwarded["source"]), ("code", "link"))
        self.assertEqual(self.skicka("G9002", self.rabbits2).status_code, 200)
        self.assertEqual(db.YearlyHerdReport.get().access_code_id, self.code2.id)

    def test_logged_in_user_without_right_uses_code(self):
        self.user("annan")
        self.login("annan")
        self.assertEqual(self.api("GET", "/besattning/G9001/2025").status_code, 403)
        self.open_link()
        self.assertEqual(self.api("GET", "/besattning/G9001/2025").get_json()["source"], "link")
        self.assertEqual(self.skicka("G9001", self.rabbits_).status_code, 200)
        self.assertEqual(db.YearlyHerdReport.get().source, "link")

    def test_no_session_is_401_and_an_idle_one_session_ute(self):
        self.assertEqual(self.api("GET", "/besattning/G9001/2025").status_code, 401)
        self.open_link()
        with self.client.session_transaction() as session:
            session["rapport_seen"] = (arsrapport.now() - timedelta(minutes=121)).isoformat()
        response = self.api("GET", "/besattning/G9001/2025")
        self.assertEqual((response.status_code, response.get_json()["code"]), (401, "session_ute"))
        self.assertEqual(self.api("GET", "/besattning/G9001/2025").status_code, 401)

    def test_a_request_refreshes_the_two_hours(self):
        self.open_link()
        with self.client.session_transaction() as session:
            session["rapport_seen"] = (arsrapport.now() - timedelta(minutes=119)).isoformat()
        self.assertEqual(self.api("GET", "/besattning/G9001/2025").status_code, 200)
        with self.client.session_transaction() as session:
            self.assertIn("rapport_seen", session)
            self.assertLess(
                arsrapport.now() - arsrapport.datetime.fromisoformat(session["rapport_seen"]), timedelta(minutes=1)
            )

    def test_revoked_code_is_403_lank_ogiltig(self):
        self.open_link()
        report_code.revoke(self.code, now=arsrapport.now())
        before = self.counts()
        for call in (
            lambda: self.api("GET", "/besattning/G9001/2025"),
            lambda: self.skicka("G9001", self.rabbits_),
        ):
            response = call()
            self.assertEqual((response.status_code, response.get_json()["code"]), (403, "lank_ogiltig"))
        self.assertEqual(self.counts(), before)

    def test_round_and_status_routes_still_need_login(self):
        self.open_link()
        calls = (
            ("GET", "/api/v2/arsrapport/rundor", None),
            ("PUT", "/api/v2/arsrapport/rundor/2025", {}),
            ("POST", f"/api/v2/arsrapport/rundor/2025/genbanker/{self.gotland.id}/aktivera", {}),
            ("GET", f"/api/v2/arsrapport/2025/status?genebank_id={self.gotland.id}", None),
            ("POST", "/api/v2/arsrapport/besattning/G9001/2025/i-tid", {"on_time": True}),
            ("GET", "/api/v2/arsrapport/blankett.pdf", None),
            ("GET", "/api/v2/arsrapport/mina", None),
        )
        for method, path, body in calls:
            with self.subTest(path=path):
                self.assertEqual(self.client.open(path, method=method, json=body).status_code, 401)
