#!/usr/bin/env python3
"""
Tests for approving and rejecting sale proposals from the status view (step 4a, Task 3): the endpoints and who may
call them, the rejection's submission (S1, FB2, FB3), its mail, the status flags and the buyer's notice (FB4).
Synthetic herds, rabbits and buyers only.

isort:skip_file
"""

import json
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.mail as mail
import utils.report_code as report_code
import utils.sale_proposal as sp
import utils.settings as settings
from herdbook import APP
from utils.arsrapport import ArsrapportError
from utils.report_code import CodeActor

from tests.arsrapport_fixtures import ArsrapportTest
from tests.ht_helpers import ht_row

DAY0 = date(2026, 1, 10)
LAST = date(2025, 12, 31)
BUYER = {"name": "Zelda Uniquebuyer", "town": "Visby"}
KEPT = arsrapport.REJECTED_KVAR  # S6: the Ej vägd reason a kvar rejection writes


def rows(rabbit, kind):
    query = db.HerdTracking.select().where(
        db.HerdTracking.individual == rabbit.id, db.HerdTracking.kind == kind, db.ht_not_voided()
    )
    return list(query.order_by(db.HerdTracking.id))


def proposals(rabbit):
    return list(db.SaleProposal.select().where(db.SaleProposal.individual == rabbit.id).order_by(db.SaleProposal.id))


def mails(kind):
    return list(db.MailMessage.select().where(db.MailMessage.kind == kind))


class ProposalApiTest(ArsrapportTest):
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
        self.member = self.main_member(self.h, "g9001@example.invalid")
        self.buyer_member = self.main_member(self.g9002, "g9002@example.invalid")
        self.code = report_code.issue_code(self.h, self.round_, self.member, now=arsrapport.now())
        self.a, self.b, self.c = self.rabbits(self.h, 3)  # female, male, female

    def day(self, n):
        self.at(DAY0 + timedelta(days=n))

    def latest(self, herd=None):
        """The rabbits of the latest submission of `herd`'s report, as the page reloads them."""
        report = arsrapport.current_report(herd or self.h, self.round_)
        return arsrapport._submissions(report)[-1].data["rabbits"]  # pylint: disable=protected-access

    def send(self, *entries, revision=None, herd=None, code=None):
        """The link's Skicka, for G9001 or for `herd` with its `code`."""
        herd, code = herd or self.h, code or self.code
        access = arsrapport.code_access(herd, self.round_, [code.id])
        body = self.body(*entries, revision=revision)
        return arsrapport.submit(
            herd, self.round_, access, CodeActor(code), arsrapport.parse_submission(body, paper=False)
        )

    def withdraw(self, revision):
        access = arsrapport.code_access(self.h, self.round_, [self.code.id])
        return arsrapport.withdraw(self.h, self.round_, access, CodeActor(self.code), revision=revision)

    def first(self, *sold):
        """The link's first report: a sold in October to G9002 (or `sold`), the others kvar."""
        sold = sold or (self.sald(self.a, "G9002", 2025, 10, 3),)
        ids = {int(key) for key, _ in sold}
        kept = [self.kvar(r, vikt=2.8) for r in (self.a, self.b, self.c) if r.id not in ids]
        self.send(*sold, *kept)
        return proposals(self.a)[0] if self.a.id in ids else None

    def report(self):
        return db.YearlyHerdReport.get(db.YearlyHerdReport.herd == self.h.id, db.YearlyHerdReport.status == "submitted")

    def decide(self, proposal, action, who="man", **body):
        self.login(who)
        return self.client.post(f"/api/v2/arsrapport/forslag/{proposal.id}/{action}", json=body)

    def flags(self, herd="G9001"):
        self.login("man")
        response = self.client.get(f"/api/v2/arsrapport/2025/status?genebank_id={self.gotland.id}")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return {row["herd"]: row for row in response.get_json()["rows"]}[herd]["flags"]

    def test_only_manager_of_genebank_or_admin_decides(self):
        proposal = self.first()
        self.user("mman", ("manager", self.mellerud.id))
        for who in ("hjalp", "owner", "mman"):
            self.assertEqual(self.decide(proposal, "godkann", who).status_code, 403, who)
            response = self.decide(proposal, "avvisa", who, reason="Fel datum", then="kvar")
            self.assertEqual(response.status_code, 403, who)
            self.assertEqual(self.client.get("/api/v2/arsrapport/besattning/G9001/2025/forslag").status_code, 403)
        self.assertEqual(db.SaleProposal.get_by_id(proposal.id).state, "foreslagen")
        self.assertEqual(self.decide(proposal, "godkann", "admin").get_json(), {"id": proposal.id, "state": "godkand"})
        (sale,) = rows(self.a, "TRANSFER")
        self.assertEqual((sale.herd_id, sale.herd_tracking_date), (self.g9002.id, date(2025, 10, 3)))
        self.assertEqual(self.decide(proposal, "avvisa", "man", reason="Fel", then="kvar").status_code, 409)

    def test_dialog_lists_pending_with_buyer_name_and_town(self):  # K7
        buyer = {**BUYER, "email": "k@example.invalid", "contact_consent": True}
        proposal = self.first(self.sald(self.a, "utanfor", 2025, 10, 3, kopare=buyer))
        db.SaleProposal.update(buyer_notified_at=datetime(2026, 1, 11, tzinfo=timezone.utc)).execute()
        self.login("man")
        (row,) = self.client.get("/api/v2/arsrapport/besattning/G9001/2025/forslag").get_json()["forslag"]
        self.assertEqual(
            row,
            {
                "id": proposal.id,
                "individual_id": self.a.id,
                "number": self.a.number,
                "name": None,
                "to_herd": None,
                "buyer": BUYER,
                "sale_date": "2025-10-03",
                "buyer_notified_at": "2026-01-11T00:00:00+00:00",
            },
        )

    def test_approve_after_withdraw_gets_409(self):  # Review Focus 1
        proposal = self.first()
        self.day(1)
        self.withdraw(1)
        self.assertEqual(self.decide(proposal, "godkann").status_code, 409)
        self.assertEqual(rows(self.a, "TRANSFER"), [])
        self.assertEqual(db.SaleProposal.get_by_id(proposal.id).state, "atertagen")

    def test_withdraw_after_approve_keeps_sale(self):  # Review Focus 1
        proposal = self.first()
        self.assertEqual(self.decide(proposal, "godkann").status_code, 200)
        (sale,) = rows(self.a, "TRANSFER")
        self.day(1)
        self.withdraw(1)
        self.assertIsNone(db.HerdTracking.get_by_id(sale.id).voided_at)
        self.assertEqual(rows(self.b, "ATTESTATION"), [])
        self.assertEqual(db.SaleProposal.get_by_id(proposal.id).state, "godkand")

    def test_approve_after_end_date_allowed(self):  # Review Focus 4
        proposal = self.first()
        self.at(self.round_.end_date + timedelta(days=20))
        self.assertEqual(self.decide(proposal, "godkann").status_code, 200)
        self.assertEqual(len(rows(self.a, "TRANSFER")), 1)

    def test_reject_kvar_when_rabbit_moved_is_refused_and_stays_open(self):  # Review Focus 5
        proposal = self.first()
        g9003 = db.Herd.create(genebank=self.gotland, herd="G9003", is_active=True)
        ht_row("TRANSFER", individual=self.a, herd=g9003, from_herd=self.h, herd_tracking_date=date(2025, 11, 1))
        response = self.decide(proposal, "avvisa", reason="Fel datum", then="kvar")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["detail"], arsrapport.REFUSALS["inte_innehavare"])
        self.assertEqual(db.SaleProposal.get_by_id(proposal.id).state, "foreslagen")
        self.assertEqual((rows(self.a, "ATTESTATION"), self.report().revision), ([], 1))
        self.assertEqual(mails("arsrapport.forsaljning_avvisad"), [])

    def test_reason_with_buyer_name_refused(self):  # K6
        proposal = self.first(self.sald(self.a, "utanfor", 2025, 10, 3, kopare=BUYER))
        for body, detail in (
            ({"reason": "Zelda köpte den inte", "then": "kvar"}, sp.NAMED),
            ({"reason": "  ", "then": "kvar"}, "Skriv varför försäljningen inte godkänns."),
            ({"reason": "Fel datum", "then": "kanske"}, None),
        ):
            response = self.decide(proposal, "avvisa", **body)
            self.assertEqual(response.status_code, 400, body)
            if detail:
                self.assertEqual(response.get_json()["detail"], detail)
        self.assertEqual(db.SaleProposal.get_by_id(proposal.id).state, "foreslagen")
        self.assertEqual(mails("arsrapport.forsaljning_avvisad"), [])

    def test_rejection_mail_enqueued_with_reason(self):
        proposal = self.first()
        response = self.decide(proposal, "avvisa", reason="Datumet stämmer inte", then="valj_igen")
        self.assertEqual(response.get_json(), {"id": proposal.id, "state": "avvisad"})
        (row,) = mails("arsrapport.forsaljning_avvisad")
        self.assertEqual(
            (row.recipient_kind, row.recipient_id, row.params, row.ref_type, row.ref_id, row.priority),
            ("member", self.member.id, {"proposal_id": proposal.id, "kvar": 0}, "sale_proposal", proposal.id, 1),
        )
        subject, text = mail.render(row.kind, mail.MAIL_KINDS[row.kind].build(row.params))
        self.assertEqual(subject, f"Försäljningen av {self.a.number} är inte godkänd")
        self.assertIn(f"försäljningen av {self.a.number} i årsrapporten för G9001.", text)
        self.assertIn("Orsak: Datumet stämmer inte", text)
        self.assertIn("Öppna årsrapporten och välj igen för kaninen.", text)
        self.assertNotIn("None", text)
        self.day(1)  # the member chooses again and sells b; that one is rejected as kvar
        self.send(
            self.kvar(self.a, vikt=2.8),
            self.sald(self.b, "G9002", 2025, 11, 5),
            self.kvar(self.c, vikt=2.8),
            revision=2,
        )
        (other,) = proposals(self.b)
        self.assertEqual(self.decide(other, "avvisa", reason="Fel köpare", then="kvar").status_code, 200)
        row = mails("arsrapport.forsaljning_avvisad")[-1]
        _, text = mail.render(row.kind, mail.MAIL_KINDS[row.kind].build(row.params))
        self.assertIn("Kaninen räknas som kvar i din besättning den 31 december 2025.", text)

    def test_status_flag_counts_pending(self):
        self.first(self.sald(self.a, "G9002", 2025, 10, 3), self.sald(self.b, "utanfor", 2025, 11, 5, kopare=BUYER))
        self.assertEqual(self.flags()["forsaljning_vantar"], 2)
        self.assertEqual(self.decide(proposals(self.a)[0], "godkann").status_code, 200)
        self.assertEqual(self.flags()["forsaljning_vantar"], 1)
        self.assertEqual(self.flags("G9002")["forsaljning_vantar"], 0)

    def test_withdraw_after_reject_kvar(self):  # FB2
        proposal = self.first()
        self.assertEqual(self.decide(proposal, "avvisa", reason="Fel datum", then="kvar").status_code, 200)
        (attest,) = rows(self.a, "ATTESTATION")
        self.assertIn(str(attest.operation_id), arsrapport.report_ops(self.report()))
        latest = arsrapport._submissions(self.report())[-1]  # pylint: disable=protected-access
        self.assertEqual((latest.user_id, latest.data["rabbits"][str(self.a.id)]["val"]), (self.manager.id, "kvar"))
        self.day(1)
        self.withdraw(2)
        self.assertIsNotNone(db.HerdTracking.get_by_id(attest.id).voided_at)
        self.assertEqual(db.YearlyHerdReport.get(db.YearlyHerdReport.herd == self.h.id).status, "voided")

    def test_reject_valj_igen_shows_and_counts(self):  # FB3
        db.Breeding.create(
            breeding_herd_id=self.h, breed_date=date(2025, 4, 1), birth_date=date(2025, 5, 2), litter_size=3
        )
        self.first(self.sald(self.b, "G9002", 2025, 10, 3))  # b is the only male
        flags = self.flags()
        self.assertEqual((flags["forsaljning_vantar"], flags["forsaljning_avvisad"]), (1, 0))
        response = self.decide(proposals(self.b)[0], "avvisa", reason="Fel köpare", then="valj_igen")
        self.assertEqual(response.status_code, 200)
        self.assertEqual((rows(self.b, "ATTESTATION"), rows(self.b, "TRANSFER")), ([], []))
        flags = self.flags()
        self.assertEqual(
            (flags["forsaljning_vantar"], flags["forsaljning_avvisad"], flags["forsaljning_avvisad_paverkar"]),
            (0, 1, True),
        )
        # the member has to choose again: left out, b is not klar
        access = arsrapport.code_access(self.h, self.round_, [self.code.id])
        body = self.body(self.kvar(self.a, vikt=2.8), self.kvar(self.c, vikt=2.8), revision=2)
        refusals, _ = arsrapport.check(
            self.h, self.round_, access, self.report(), arsrapport.parse_submission(body, paper=False), on=DAY0
        )
        self.assertEqual([(r.individual_id, r.code) for r in refusals], [(self.b.id, "inte_klar")])
        self.day(1)  # the same choice again is a new proposal
        self.send(
            self.kvar(self.a, vikt=2.8),
            self.sald(self.b, "G9002", 2025, 10, 3),
            self.kvar(self.c, vikt=2.8),
            revision=2,
        )
        self.assertEqual([p.state for p in proposals(self.b)], ["avvisad", "foreslagen"])
        flags = self.flags()
        self.assertEqual((flags["forsaljning_vantar"], flags["forsaljning_avvisad"]), (1, 0))

    def test_january_rejected_kvar_then_change_makes_no_proposal(self):  # S1
        proposal = self.first(self.sald(self.a, "G9002", 2026, 1, 5))
        (attest,) = rows(self.a, "ATTESTATION")
        self.assertEqual(self.decide(proposal, "avvisa", reason="Fel datum", then="kvar").status_code, 200)
        self.assertEqual([r.id for r in rows(self.a, "ATTESTATION")], [attest.id])  # nothing new to write
        self.assertEqual(arsrapport._submissions(self.report())[-1].operation_ids, [])  # pylint: disable=protected-access
        self.day(1)  # an unrelated Ändra from the reloaded page
        self.send(self.kvar(self.a, ej_vagd=KEPT), self.kvar(self.b, vikt=3.0), self.kvar(self.c, vikt=2.8), revision=2)
        self.assertEqual([p.state for p in proposals(self.a)], ["avvisad"])
        self.assertEqual([r.id for r in rows(self.a, "ATTESTATION")], [attest.id])

    def test_page_opened_before_rejection_gets_409(self):  # S1, the draft too
        proposal = self.first()
        access, actor = arsrapport.code_access(self.h, self.round_, [self.code.id]), CodeActor(self.code)
        sold = {"val": "sald", "sald": {"till": "G9002", "ar": 2025, "manad": 10, "dag": 3}}
        data = {"rabbits": {str(self.a.id): sold}, "form": {"rabbits": {str(self.a.id): sold}}}
        draft = arsrapport.save_draft(self.h, self.round_, access, actor, data, None, None, 1)
        self.assertEqual(self.decide(proposal, "avvisa", reason="Fel köpare", then="valj_igen").status_code, 200)
        self.assertEqual(db.YearlyReportDraft.get().data["form"]["rabbits"], {})
        with self.assertRaises(ArsrapportError) as caught:  # the old tab's autosave gets the draft as it is now
            arsrapport.save_draft(self.h, self.round_, access, actor, data, draft.updated_at, None, 1)
        self.assertEqual((caught.exception.status, caught.exception.extra["draft"]["data"]["rabbits"]), (409, {}))
        with self.assertRaises(ArsrapportError) as caught:  # and its Skicka the existing 409
            self.send(
                self.sald(self.a, "G9002", 2025, 10, 3),
                self.kvar(self.b, vikt=2.8),
                self.kvar(self.c, vikt=2.8),
                revision=1,
            )
        self.assertEqual((caught.exception.status, caught.exception.detail), (409, "Rapporten har ändrats."))
        self.assertEqual([p.state for p in proposals(self.a)], ["avvisad"])

    def test_approved_sale_flags_buyer_report(self):  # FB4
        self.owner.add_role("owner", self.g9002.id)
        self.reported(self.g9002)  # the buyer's report came in on day 0
        proposal = self.first()
        self.day(1)
        self.assertEqual(self.decide(proposal, "godkann").status_code, 200)
        self.assertEqual(self.flags("G9002")["kopt_efter_inskick"], 1)
        (row,) = mails("arsrapport.kop_godkant")
        self.assertEqual(
            (row.recipient_kind, row.recipient_id, row.herd_id), ("member", self.buyer_member.id, self.g9002.id)
        )
        subject, text = mail.render(row.kind, mail.MAIL_KINDS[row.kind].build(row.params))
        self.assertEqual(subject, f"{self.a.number} är registrerad i din besättning")
        self.assertIn(
            f"{self.a.number} är registrerad i din besättning från 2025-10-03. Ändra din årsrapport och välj Finns kvar"
            " för kaninen, så räknas den den 31 december.",
            text,
        )
        self.day(2)  # the buyer changes the report: a is on its list now, and the flag goes
        buyer = db.User.get_by_id(self.owner.id)
        body = self.body(self.kvar(self.a, vikt=2.8), revision=1)
        access = arsrapport.report_access(buyer, self.g9002)
        arsrapport.submit(self.g9002, self.round_, access, buyer, arsrapport.parse_submission(body, paper=False))
        self.assertEqual(self.flags("G9002")["kopt_efter_inskick"], 0)
        self.assertEqual(rows(self.a, "ATTESTATION")[0].herd_id, self.g9002.id)

    # Codex review of 9e55e5b..f638e7a, and S6

    def test_reject_kvar_leaves_a_klar_row(self):  # S6
        proposal = self.first()
        self.assertEqual(self.decide(proposal, "avvisa", reason="Fel datum", then="kvar").status_code, 200)
        stored = self.latest()[str(self.a.id)]
        self.assertEqual((stored["val"], stored["vikt"], stored["ej_vagd"]), ("kvar", None, KEPT))
        self.assertEqual(json.loads(self.report().data)["not_weighed"], {str(self.a.id): KEPT})
        self.day(1)  # the reloaded page sends a as it is: nothing to refuse, nothing new written
        (attest,) = rows(self.a, "ATTESTATION")
        self.send(self.kvar(self.a, ej_vagd=KEPT), self.kvar(self.b, vikt=3.0), self.kvar(self.c, vikt=2.8), revision=2)
        weighed = db.Weight.select().where(db.Weight.individual == self.a.id)
        self.assertEqual(([r.id for r in rows(self.a, "ATTESTATION")], weighed.count()), ([attest.id], 0))
        self.assertEqual([p.state for p in proposals(self.a)], ["avvisad"])
        self.day(2)  # the member may still weigh it
        self.send(self.kvar(self.a, vikt=2.9), self.kvar(self.b, vikt=3.0), self.kvar(self.c, vikt=2.8), revision=3)
        self.assertEqual([round(w.weight, 2) for w in weighed], [2.9])

    def test_rejections_locked_in_another_order_than_started(self):  # P1
        self.first(self.sald(self.a, "G9002", 2025, 10, 3), self.sald(self.b, "G9002", 2025, 11, 5))
        (first,), (second,) = proposals(self.a), proposals(self.b)
        started = datetime(2026, 1, 10, 11, 0, tzinfo=timezone.utc)
        # a's rejection started first but took the report's lock second: it writes after b's, with an older clock
        manager = db.User.get_by_id(self.manager.id)
        sp.reject(second, manager, reason="Fel köpare", then="valj_igen", now=started + timedelta(seconds=1))
        sp.reject(first, manager, reason="Fel datum", then="kvar", now=started)
        latest = self.latest()
        self.assertEqual((latest[str(self.a.id)]["val"], latest[str(self.b.id)]["val"]), ("kvar", None))
        self.assertEqual(self.report().revision, 3)
        self.assertEqual(self.flags()["forsaljning_avvisad"], 1)
