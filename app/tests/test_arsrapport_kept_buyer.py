#!/usr/bin/env python3
"""
Tests for the buyer outside the genebank kept across Dra tillbaka (step 4a, Task 4: K1, K2, FB6), and for the
buyer's consent fields through the report. Synthetic herds, rabbits and buyers only.

isort:skip_file
"""

import json
from datetime import date, datetime, timedelta
from unittest import mock

import utils.arsrapport as arsrapport
import utils.buyer_contact as buyer_contact
import utils.database as db
import utils.mail as mail
import utils.report_code as report_code
import utils.settings as settings
from herdbook import APP
from utils.arsrapport_pdf import receipt_pdf
from utils.herd_tracking import CONTACT_OR_MEMBERSHIP_NEEDED, undo_herd_tracking_operation, void_herd_tracking
from utils.individual_commands import record_sale
from utils.report_code import CodeActor

from tests.arsrapport_fixtures import ArsrapportTest
from tests.test_arsrapport_pdf import text_of

DAY0 = date(2026, 1, 10)
STOCKHOLM = arsrapport.STOCKHOLM
BUYER = {"name": "Zelda Keptbuyer", "town": "Klintehamn", "contact_consent": True, "email": "zelda@example.invalid"}
BUYER_TEXTS = ("Zelda", "Keptbuyer", "Klintehamn", "zelda@example")
OTHER = {"name": "Ylva Newbuyer", "town": "Slite"}
KEPT_UNTIL = datetime(2026, 4, 1, tzinfo=STOCKHOLM)  # end_date 30 March, plus the night after it and a day
SOLD_ON = date(2025, 10, 10)


def sales(rabbit, active=None):
    query = db.HerdTracking.select().where(db.HerdTracking.individual == rabbit.id, db.HerdTracking.kind == "TRANSFER")
    if active is not None:
        query = query.where(db.HerdTracking.voided_at.is_null(active))
    return list(query.order_by(db.HerdTracking.id))


def contacts():
    return {c.id: c.purge_at for c in db.BuyerContact.select()}


class KeptBuyerTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        context = APP.app_context()  # request_hash and the mail templates read the app
        context.push()
        self.addCleanup(context.pop)
        patcher = mock.patch.multiple(settings.mail, link_secret="test-link-secret", link_hosts=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.at(DAY0)
        self.round_ = self.round(2025)
        self.h = db.Herd.create(genebank=self.gotland, herd="G9001", herd_name="Testbesättning", is_active=True)
        self.g9002 = db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.owner.add_role("owner", self.h.id)
        self.member = self.main_member(self.h, "g9001@example.invalid")
        self.a, self.b = self.rabbits(self.h, 2)
        self.login("owner")

    def skicka(self, body):
        return self.api("POST", "/besattning/G9001/2025/skicka", **body)

    def ok(self, body):
        response = self.skicka(body)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def refused(self, body):
        response = self.skicka(body)
        self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
        return [(r["individual_id"], r["code"]) for r in response.get_json()["refusals"]]

    def withdrawn(self, revision, reason=None):
        response = self.api("POST", "/besattning/G9001/2025/dra-tillbaka", revision=revision, reason=reason)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def put(self, data, updated_at):
        response = self.api(
            "PUT", "/besattning/G9001/2025/utkast", data=data, updated_at=updated_at, submission_key=None, revision=None
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()["updated_at"]

    def sold_and_withdrawn(self, *more):
        """a sold outside the genebank with BUYER, b Finns kvar, and Dra tillbaka: (the kept buyer, the report id)."""
        rid = self.ok(
            self.body(self.sald(self.a, "utanfor", 2025, 10, 10, kopare=BUYER), self.kvar(self.b, vikt=2.8), *more)
        )["report_id"]
        (sale,) = sales(self.a)
        self.view = self.withdrawn(1)
        return db.BuyerContact.get_by_id(sale.holder_contact_id), rid

    def draft(self):
        return db.YearlyReportDraft.get().data

    def resent(self, **sald):
        """The withdrawn draft sent as the client sends it (lib.ts): a's kopare_id carried, fran_rapport not."""
        data, key = self.draft(), str(self.a.id)
        kept = {k: v for k, v in data["rabbits"][key]["sald"].items() if k != "fran_rapport"}
        rabbits = {**data["rabbits"], key: {**data["rabbits"][key], "sald": {**kept, **sald}}}
        return self.body(**{**{k: v for k, v in data.items() if k != "form"}, "rabbits": rabbits})

    def test_withdraw_keeps_outside_buyer_unlinked_until_end_date(self):
        contact, rid = self.sold_and_withdrawn()
        (sale,) = sales(self.a)
        self.assertIsNotNone(sale.voided_at)
        self.assertEqual(sale.holder_contact_id, contact.id)  # the voided sale is where it came from (K1)
        self.assertEqual(sales(self.a, active=True), [])  # no active row holds it
        self.assertEqual((contact.name, contact.email), (BUYER["name"], BUYER["email"]))
        self.assertEqual(contact.purge_at, KEPT_UNTIL)
        self.assertEqual(contact.purge_at, arsrapport.kept_until(self.round_))
        self.assertEqual(
            self.draft()["rabbits"][str(self.a.id)]["sald"],
            {"till": "utanfor", "ar": 2025, "manad": 10, "dag": 10, "kopare_id": contact.id, "fran_rapport": rid},
        )
        self.assertEqual(self.view["draft"]["data"], self.draft())  # the seller gets the id, never the buyer
        (row,) = db.MailMessage.select().where(db.MailMessage.kind == "arsrapport.angrad")
        _, mailed = mail.render("arsrapport.angrad", arsrapport._angrad(row.params))  # pylint: disable=protected-access
        for text in (json.dumps(self.view), mailed):
            self.assertFalse([value for value in BUYER_TEXTS if value in text])

    def test_first_draft_save_takes_no_kopare_id(self):  # K1: only the server writes one
        self.ok(self.body(self.sald(self.a, "utanfor", 2025, 10, 10, kopare=BUYER), self.kvar(self.b, vikt=2.8)))
        forged = {"val": "sald", "sald": {"till": "utanfor", "ar": 2025, "manad": 10, "dag": 10, "kopare_id": 1}}
        data = arsrapport.stored_body(self.body(self.kvar(self.b, vikt=2.8)))
        data["rabbits"][str(self.a.id)] = {**forged, "sald": {**forged["sald"], "fran_rapport": 1}}
        data["form"] = {"rabbits": {str(self.a.id): forged}}
        response = self.api(
            "PUT", "/besattning/G9001/2025/utkast", data=data, updated_at=None, submission_key=None, revision=1
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertNotIn("kopare_id", json.dumps(self.draft()))
        self.assertNotIn("fran_rapport", json.dumps(self.draft()))

    def test_resubmit_reattaches_kept_buyer(self):
        contact, _ = self.sold_and_withdrawn()
        receipt = self.ok(self.resent())
        old, new = sales(self.a)
        self.assertIsNotNone(old.voided_at)
        self.assertEqual((new.holder_contact_id, new.voided_at, new.herd.herd), (contact.id, None, "GX1"))
        self.assertEqual(db.BuyerContact.get_by_id(contact.id).purge_at, db.BuyerContact.purge_at_for(SOLD_ON))
        self.assertEqual(list(contacts()), [contact.id])
        self.assertFalse(db.YearlyReportDraft.select().exists())
        # The seller never reads the buyer back: the view, the receipt, its PDF and its mail.
        report = db.YearlyHerdReport.get_by_id(receipt["report_id"])
        submission = db.YearlyReportSubmission.get_by_id(receipt["submission_id"])
        self.assertNotIn("kopare_id", json.dumps(submission.data))
        row = db.MailMessage.select().where(db.MailMessage.kind == "arsrapport.kvitto").order_by(db.MailMessage.id)
        _, mailed = mail.render("arsrapport.kvitto", arsrapport._kvitto(row[-1].params))  # pylint: disable=protected-access
        view = self.api("GET", "/besattning/G9001/2025").get_json()
        self.assertIn("Såld", text_of(receipt_pdf(report, submission)))
        for text in (json.dumps(view), json.dumps(receipt), text_of(receipt_pdf(report, submission)), mailed):
            self.assertFalse([value for value in BUYER_TEXTS if value in text], text[:200])

    def test_skicka_withdraw_skicka_keeps_same_contact_id(self):  # K1: the whole cycle, twice
        contact, _ = self.sold_and_withdrawn()
        self.ok(self.resent())
        self.withdrawn(2)
        (kept,) = db.BuyerContact.select()
        self.assertEqual((kept.id, kept.purge_at), (contact.id, KEPT_UNTIL))
        self.assertEqual(self.draft()["rabbits"][str(self.a.id)]["sald"]["kopare_id"], contact.id)
        self.ok(self.resent())
        self.assertEqual([sale.holder_contact_id for sale in sales(self.a, active=True)], [contact.id])
        self.assertEqual(list(contacts()), [contact.id])

    def test_foreign_kopare_id_refused(self):  # Review Focus 2: refused, and nothing is attached
        contact, rid = self.sold_and_withdrawn(self.sald(self.c_rabbit(), "utanfor", 2025, 10, 11, kopare=OTHER))
        sibling = sales(self.c)[0].holder_contact_id  # kept from the same report, for another rabbit
        x, y = self.rabbits(self.g9002, 2)
        admin = db.User.get_by_id(self.admin.id)
        record_sale(admin, y.id, "GX1", "2025-09-02", buyer=OTHER)
        (live,) = sales(y)
        foreign, foreign_rid = self.kept_elsewhere(x)
        record_sale(admin, self.a.id, "GX1", "2025-11-01", buyer=OTHER)  # a rabbit-page sale of a, voided
        (page_sale,) = sales(self.a, active=True)
        void_herd_tracking(page_sale.id, admin, "Test", keep_buyer_until=KEPT_UNTIL)
        cases = {
            "another herd's kept buyer": (foreign, foreign_rid),
            "a live sale's buyer": (live.holder_contact_id, rid),
            "a voided sale outside the report": (page_sale.holder_contact_id, rid),
            "another rabbit's kept buyer": (sibling, rid),
            "an id the draft does not name": (foreign, None),
        }
        server = self.draft()
        for case, (kopare_id, fran_rapport) in cases.items():
            forged = json.loads(json.dumps(server))
            if fran_rapport is not None:  # a forged claim in the server's draft, past save_draft
                forged["rabbits"][str(self.a.id)]["sald"] |= {"kopare_id": kopare_id, "fran_rapport": fran_rapport}
            db.YearlyReportDraft.update(data=forged).execute()
            with self.subTest(case):
                before, rows = contacts(), db.HerdTracking.select().count()
                self.assertEqual(self.refused(self.resent(kopare_id=kopare_id)), [(self.a.id, "kopare_saknas")])
                self.assertEqual((contacts(), db.HerdTracking.select().count()), (before, rows))
        db.YearlyReportDraft.update(data=server).execute()
        self.ok(self.resent())  # the true claim still goes through
        self.assertEqual([sale.holder_contact_id for sale in sales(self.a, active=True)], [contact.id])

    def c_rabbit(self):
        (self.c,) = self.rabbits(self.h, 1)
        return self.c

    def kept_elsewhere(self, rabbit):
        """A buyer kept by G9002's own voided report for `rabbit`: (its id, the report id)."""
        report = self.reported(self.g9002, self.sald(rabbit, "utanfor", 2025, 9, 1, kopare=OTHER))
        (sale,) = sales(rabbit)
        void_herd_tracking(sale.id, db.User.get_by_id(self.admin.id), "Test", keep_buyer_until=KEPT_UNTIL)
        voided = {"status": "voided", "voided_at": arsrapport.now(), "voided_by_user": self.admin.id}
        db.YearlyHerdReport.update(voided).where(db.YearlyHerdReport.id == report.id).execute()
        return sale.holder_contact_id, report.id

    def test_kept_buyer_survives_end_date_night(self):  # K2: the purge runs at 03:50
        contact, _ = self.sold_and_withdrawn()
        buyer_contact.run(datetime(2026, 3, 31, 3, 50, tzinfo=STOCKHOLM))  # the night after end_date
        self.assertEqual(list(contacts()), [contact.id])

    def test_kept_buyer_purged_after_end_date(self):
        contact, _ = self.sold_and_withdrawn()
        buyer_contact.run(datetime(2026, 4, 1, 3, 50, tzinfo=STOCKHOLM))
        self.assertEqual(contacts(), {})
        self.assertIsNone(sales(self.a)[0].holder_contact_id)
        self.assertTrue(db.AuditLog.select().where(db.AuditLog.record_id == str(contact.id)).exists())

    def test_extended_round_moves_kept_buyer(self):  # K2, with step 3's R10 hook
        contact, _ = self.sold_and_withdrawn()
        arsrapport.save_round(2025, self.admin, end_date=date(2026, 4, 30))
        self.assertEqual(contacts(), {contact.id: datetime(2026, 5, 2, tzinfo=STOCKHOLM)})
        self.ok(self.resent())  # linked again: a later change of the round leaves it at five years
        arsrapport.save_round(2025, self.admin, end_date=date(2026, 5, 15))
        self.assertEqual(contacts(), {contact.id: db.BuyerContact.purge_at_for(SOLD_ON)})

    def test_undoing_the_withdraws_void_gives_the_buyer_five_years_again(self):
        contact, _ = self.sold_and_withdrawn()
        (sale,) = sales(self.a)
        undo_herd_tracking_operation(
            sale.voided_operation_id, db.User.get_by_id(self.manager.id), "Fel tillbakadragning"
        )
        self.assertEqual([row.id for row in sales(self.a, active=True)], [sale.id])
        self.assertEqual(contacts(), {contact.id: db.BuyerContact.purge_at_for(SOLD_ON)})

    def test_contact_fields_need_tick(self):  # through the report: BuyerFields' rule on the server
        email_only = {"name": "Xena Tickbuyer", "town": "Visby", "email": "xena@example.invalid"}
        body = self.body(self.sald(self.a, "utanfor", 2025, 10, 10, kopare=email_only), self.kvar(self.b, vikt=2.8))
        response = self.skicka(body)
        self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
        self.assertEqual(
            response.get_json()["refusals"],
            [{"individual_id": self.a.id, "code": "kopare", "message": CONTACT_OR_MEMBERSHIP_NEEDED}],
        )
        self.assertEqual(contacts(), {})
        ticked = {**email_only, "membership_optin": True}
        self.ok(self.body(self.sald(self.a, "utanfor", 2025, 10, 10, kopare=ticked), self.kvar(self.b, vikt=2.8)))
        contact = db.BuyerContact.get()
        self.assertEqual(
            (contact.name, contact.email, contact.contact_consent_at), (email_only["name"], email_only["email"], None)
        )
        self.assertIsNotNone(contact.membership_optin_at)

    def test_client_cannot_set_kopare_id_and_a_cleared_sale_deletes_it(self):  # K1, FB6 in save_draft
        contact, rid = self.sold_and_withdrawn()
        key, server = str(self.a.id), self.draft()
        sale = server["rabbits"][key]["sald"]
        forged = {**server, "rabbits": {**server["rabbits"], key: {"val": "sald", "sald": {**sale, "kopare_id": 1}}}}
        stamp = self.put(forged, self.view["draft"]["updated_at"])
        self.assertEqual(self.draft()["rabbits"][key]["sald"]["kopare_id"], contact.id)  # the server's stays
        # A row still being filled in: the body leaves it out, the form copy decides.
        form = {"rabbits": {key: {"val": "sald", "sald": {"till": "utanfor", "ar": 2025, "manad": None, "dag": None}}}}
        half = {**server, "rabbits": {k: v for k, v in server["rabbits"].items() if k != key}, "form": form}
        stamp = self.put(half, stamp)
        self.assertEqual(self.draft()["form"]["rabbits"][key]["sald"]["kopare_id"], contact.id)
        self.assertEqual(self.draft()["form"]["rabbits"][key]["sald"]["fran_rapport"], rid)
        self.assertEqual(list(contacts()), [contact.id])
        # The sale cleared: the buyer goes at once, not at end_date.
        kvar = {"val": "kvar", "vikt": 2.8}
        self.put({**server, "rabbits": {**server["rabbits"], key: kvar}, "form": {"rabbits": {key: kvar}}}, stamp)
        self.assertEqual(contacts(), {})
        self.assertNotIn("kopare_id", json.dumps(self.draft()))
        self.assertIsNone(sales(self.a)[0].holder_contact_id)

    def test_withdraw_with_an_open_draft_without_the_sale_deletes_it(self):  # FB6, the branch with a draft
        self.ok(self.body(self.sald(self.a, "utanfor", 2025, 10, 10, kopare=BUYER), self.kvar(self.b, vikt=2.8)))
        kvar = {"val": "kvar", "vikt": 2.8}
        data = {**arsrapport.stored_body(self.body(self.kvar(self.b, vikt=2.8))), "form": {"rabbits": {}}}
        data["rabbits"][str(self.a.id)] = kvar
        data["form"]["rabbits"] = {str(self.a.id): kvar}
        response = self.api(
            "PUT", "/besattning/G9001/2025/utkast", data=data, updated_at=None, submission_key=None, revision=1
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.withdrawn(1)
        self.assertEqual(contacts(), {})
        self.assertNotIn("kopare_id", json.dumps(self.draft()))

    def test_new_buyer_at_skicka_deletes_the_kept_one(self):  # "eller skriv en ny köpare"
        contact, _ = self.sold_and_withdrawn()
        self.ok(self.resent(kopare=OTHER))
        (new,) = sales(self.a, active=True)
        self.assertNotEqual(new.holder_contact_id, contact.id)
        self.assertEqual([(c.name, c.town) for c in db.BuyerContact.select()], [(OTHER["name"], OTHER["town"])])

    def test_kept_buyer_not_taken_by_a_proposal(self):  # F1: a link's sale is a proposal, whose buyer is typed
        contact, _ = self.sold_and_withdrawn()
        code = report_code.issue_code(self.h, self.round_, self.member, now=arsrapport.now())
        access, actor = arsrapport.code_access(self.h, self.round_, [code.id]), CodeActor(code)

        def send(body):
            return arsrapport.submit(self.h, self.round_, access, actor, arsrapport.parse_submission(body, paper=False))

        with self.assertRaises(arsrapport.ArsrapportError) as caught:
            send(self.resent())
        refusals = [(r["individual_id"], r["code"]) for r in caught.exception.extra["refusals"]]
        self.assertEqual(refusals, [(self.a.id, "kopare_saknas")])
        send(self.resent(kopare=OTHER))
        (proposal,) = db.SaleProposal.select()
        self.assertEqual((proposal.state, proposal.buyer["name"]), ("foreslagen", OTHER["name"]))
        self.assertEqual(contacts(), {})  # the kept buyer went with the draft

    def caretaker(self):
        """An account with a herd-access grant to G9001 through the membership: the caretaker (skötare)."""
        user = self.user("skotare")
        person = db.Member.create(
            first_name="Test", last_name="Skötare", membership=self.h.membership, role="skotare", user=user
        )
        db.HerdAccessGrant.create(member=person, herd=self.h, granted_by=self.admin)
        return user

    def test_a_seller_cannot_probe_the_kept_buyer_through_the_reason(self):  # Codex P1: the system reason
        self.sold_and_withdrawn()
        self.caretaker()

        def answers(path):
            sent = [{**self.resent(), "reason": reason} for reason in ("Zelda hämtar den i mars", "Ingen hämtar den")]
            return [(r.status_code, r.get_json()) for r in (self.api("POST", path, **body) for body in sent)]

        for who in ("skotare", "owner"):
            self.login(who)
            with self.subTest(who):
                named, other = answers("/besattning/G9001/2025/torrkorning")
                self.assertEqual(named, other)
        self.login("skotare")  # a proposal takes no kept buyer: refused alike, whatever the reason says
        named, other = answers("/besattning/G9001/2025/skicka")
        self.assertEqual((named[0], named), (422, other))
        self.login("owner")
        self.ok({**self.resent(), "reason": "Zelda hämtar den i mars"})
        self.login("skotare")
        self.withdrawn(2, reason="Zelda ångrade sig")
        stored = [row.voided_reason for row in db.HerdTracking.select()]
        stored += [row.void_reason for row in db.YearlyHerdReport.select()]
        stored += [json.dumps(row.data) for row in db.YearlyReportSubmission.select()]
        self.assertFalse([text for text in stored if text and "Zelda" in text])

    def test_late_withdraw_keeps_nothing(self):  # after kept_until only an editor withdraws, and nothing is kept
        self.ok(self.body(self.sald(self.a, "utanfor", 2025, 10, 10, kopare=BUYER), self.kvar(self.b, vikt=2.8)))
        self.at(KEPT_UNTIL + timedelta(hours=12))
        self.login("man")
        self.withdrawn(1, reason="Fel i rapporten")
        self.assertEqual(contacts(), {})
        self.assertNotIn("kopare_id", json.dumps(self.draft()))
