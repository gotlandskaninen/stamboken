#!/usr/bin/env python3
"""
Tests for the buyer outside the genebank kept across Dra tillbaka (step 4a, Task 4: K1, K2, FB6), and for the
buyer's consent fields through the report. Synthetic herds, rabbits and buyers only.

isort:skip_file
"""

import json
import threading
import time
from datetime import date, datetime, timedelta
from unittest import mock

import utils.arsrapport as arsrapport
import utils.arsrapport_invite as arsrapport_invite
import utils.buyer_contact as buyer_contact
import utils.database as db
import utils.herd_tracking as herd_tracking
import utils.individual_commands as individual_commands
import utils.mail as mail
import utils.report_code as report_code
import utils.settings as settings
from herdbook import APP
from utils.arsrapport_pdf import receipt_pdf
from utils.herd_tracking import CONTACT_OR_MEMBERSHIP_NEEDED, undo_herd_tracking_operation, void_herd_tracking
from utils.individual_commands import record_sale
from utils.report_code import CodeActor

from tests.arsrapport_fixtures import ArsrapportTest
from tests.database_test import _USE_POSTGRES
from tests.test_arsrapport_pdf import text_of

DAY0 = date(2026, 1, 10)
STOCKHOLM = arsrapport.STOCKHOLM
BUYER = {
    "name": "Zelda Keptbuyer",
    "town": "Klintehamn",
    "postal_address": "Testgatan 1",
    "contact_consent": True,
    "email": "zelda@example.invalid",
}
BUYER_TEXTS = ("Zelda", "Keptbuyer", "Klintehamn", "zelda@example")
OTHER = {"name": "Ylva Newbuyer", "town": "Slite", "postal_address": "Testgatan 1"}
KEPT_UNTIL = datetime(2026, 4, 1, tzinfo=STOCKHOLM)  # end_date 30 March, plus the night after it and a day
SOLD_ON = date(2025, 10, 10)
PURGE_NIGHT = datetime(2026, 4, 1, 3, 50, tzinfo=STOCKHOLM)  # the first night the kept buyer is due
EXTENDED = date(2026, 4, 30)  # the round's end_date moved a month on
EXTENDED_UNTIL = datetime(2026, 5, 2, tzinfo=STOCKHOLM)


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

    def assert_erased_buyer_stays_removed(self, typed, blank, day, original=SOLD_ON):
        response = self.skicka(typed)
        self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
        self.assertEqual([r["message"] for r in response.json["refusals"]], [herd_tracking.BUYER_REMOVED])
        view = self.api("GET", "/besattning/G9001/2025").json
        row = next(row for row in view["rabbits"] if row["id"] == self.a.id)
        self.assertIn(original.isoformat(), row["removed_buyer_dates"])
        self.ok(blank)
        (sale,) = sales(self.a, active=True)
        self.assertEqual((sale.herd_tracking_date, sale.holder_contact_id, sale.buyer_removed), (day, None, True))
        self.assertEqual(contacts(), {})

    def test_erased_buyer_stays_removed_after_withdrawal(self):
        self.ok(self.body(self.sald(self.a, "utanfor", 2025, 10, 10, kopare=BUYER), self.kvar(self.b, vikt=2.8)))
        buyer_contact.erase_buyer_contact(sales(self.a)[0].holder_contact_id, self.admin)
        self.withdrawn(1)
        self.assert_erased_buyer_stays_removed(self.resent(kopare=OTHER), self.resent(), SOLD_ON)

    def test_erased_month_only_sale_resubmitted_next_day(self):
        self.ok(self.body(self.sald(self.a, "utanfor", 2026, 1, kopare=BUYER), self.kvar(self.b, vikt=2.8)))
        (sale,) = sales(self.a)
        self.assertEqual(sale.herd_tracking_date, DAY0)
        buyer_contact.erase_buyer_contact(sale.holder_contact_id, self.admin)
        self.withdrawn(1)
        tomorrow = DAY0 + timedelta(days=1)
        self.at(tomorrow)
        self.assert_erased_buyer_stays_removed(self.resent(kopare=OTHER), self.resent(), tomorrow, original=DAY0)
        self.withdrawn(2)
        self.assertEqual(self.refused(self.resent(dag=tomorrow.day, kopare=OTHER)), [(self.a.id, "kopare")])

    def test_expired_kept_buyer_allows_new_buyer_on_same_sale(self):
        kept, _ = self.sold_and_withdrawn()
        self.at(PURGE_NIGHT)
        self.assertEqual(buyer_contact.purge_expired(arsrapport.now()), 1)
        deleted = db.AuditLog.get(
            db.AuditLog.table_name == "buyer_contact",
            db.AuditLog.operation == "DELETE",
            db.AuditLog.record_id == str(kept.id),
        )
        self.assertEqual(deleted.new_data, {"action": "gallring_kvar"})
        arsrapport.save_round(2025, self.admin, end_date=EXTENDED)
        self.ok(self.resent(kopare=OTHER))
        (sale,) = sales(self.a, active=True)
        self.assertEqual((sale.herd_tracking_date, sale.holder_contact.name), (SOLD_ON, OTHER["name"]))

    def test_buyer_erased_while_kept_stays_removed(self):
        kept, _ = self.sold_and_withdrawn()
        buyer_contact.erase_buyer_contact(kept.id, self.admin)
        self.assert_erased_buyer_stays_removed(self.resent(kopare=OTHER), self.resent(), SOLD_ON)

    def test_date_change_preserves_buyer_removed(self):
        def body(day, buyer=None, revision=None):
            return self.body(
                self.sald(self.a, "utanfor", 2025, 10, day, kopare=buyer),
                self.kvar(self.b, vikt=2.8),
                revision=revision,
            )

        self.ok(body(10, BUYER))
        buyer_contact.erase_buyer_contact(sales(self.a)[0].holder_contact_id, self.admin)
        self.assert_erased_buyer_stays_removed(body(11, OTHER, 1), body(11, revision=1), date(2025, 10, 11))
        self.withdrawn(2)
        self.assertEqual(self.refused(self.resent(kopare=OTHER)), [(self.a.id, "kopare")])

    def test_kept_buyer_without_address_only_covers_original_sale_date(self):
        kept, _ = self.sold_and_withdrawn()
        row = next(row for row in self.view["rabbits"] if row["id"] == self.a.id)
        self.assertEqual(row["kept_buyer_date"], SOLD_ON.isoformat())
        db.BuyerContact.update(postal_address=None).where(db.BuyerContact.id == kept.id).execute()
        self.assertEqual(self.refused(self.resent(dag=11)), [(self.a.id, "kopare_saknas")])
        self.assertEqual(
            self.refused(self.resent(dag=11, kopare={**OTHER, "postal_address": ""})), [(self.a.id, "kopare")]
        )
        self.ok(self.resent())
        self.assertEqual(sales(self.a, active=True)[0].holder_contact_id, kept.id)
        self.withdrawn(2)
        self.ok(self.resent(dag=11, kopare=OTHER))
        (sale,) = sales(self.a, active=True)
        self.assertEqual(
            (sale.herd_tracking_date, sale.holder_contact.postal_address), (date(2025, 10, 11), OTHER["postal_address"])
        )

    def test_voided_sale_outside_the_report_does_not_block_a_new_buyer(self):
        record_sale(self.admin, self.a.id, "GX1", "2025-08-01", buyer=BUYER)
        (old,) = sales(self.a)
        buyer_contact.erase_buyer_contact(old.holder_contact_id, self.admin)
        void_herd_tracking(old.id, self.admin, "Fel försäljning")
        self.ok(self.body(self.sald(self.a, "utanfor", 2025, 10, 10, kopare=OTHER), self.kvar(self.b, vikt=2.8)))
        (new,) = sales(self.a, active=True)
        self.assertEqual(new.holder_contact.name, OTHER["name"])

    def test_three_sale_revisions_then_withdraw_and_resubmit_keep_latest_buyer(self):
        latest = {**OTHER, "name": "Tredje Köparen"}
        for revision, buyer in ((None, BUYER), (1, OTHER), (2, latest)):
            body = self.body(
                self.sald(self.a, "utanfor", 2025, 10, 10, kopare=buyer),
                self.kvar(self.b, vikt=2.8),
                revision=revision,
            )
            self.ok(body)
            (sale,) = sales(self.a, active=True)
            self.assertFalse(sale.buyer_removed)
            self.assertEqual(sale.holder_contact.name, buyer["name"])

        contact_id = sale.holder_contact_id
        blank = self.body(self.sald(self.a, "utanfor", 2025, 10, 11), self.kvar(self.b, vikt=2.8), revision=3)
        self.assertEqual(self.refused(blank), [(self.a.id, "kopare_saknas")])
        self.withdrawn(3)
        self.assertEqual(self.draft()["rabbits"][str(self.a.id)]["sald"]["kopare_id"], contact_id)
        self.ok(self.resent())
        (sale,) = sales(self.a, active=True)
        self.assertEqual((sale.holder_contact_id, sale.holder_contact.name), (contact_id, latest["name"]))

    def test_sale_after_buyback_can_have_new_buyer_after_purge(self):
        (rabbit,) = self.rabbits(self.h, 1, born=date(2018, 1, 1))
        with mock.patch.object(herd_tracking, "_now_utc", return_value=datetime(2019, 1, 1, tzinfo=STOCKHOLM)):
            record_sale(self.admin, rabbit.id, "GX1", "2019-01-01", buyer=BUYER)
        self.assertEqual(buyer_contact.purge_expired(arsrapport.now()), 1)
        record_sale(self.admin, rabbit.id, self.h.herd, "2025-02-01")

        row = next(r for r in self.api("GET", "/besattning/G9001/2025").json["rabbits"] if r["id"] == rabbit.id)
        self.assertFalse(row.get("buyer_removed"))
        self.ok(
            self.body(
                self.kvar(self.a, vikt=2.8),
                self.kvar(self.b, vikt=2.8),
                self.sald(rabbit, "utanfor", 2025, 10, 10, kopare=OTHER),
            )
        )
        old, _, latest = sales(rabbit)
        self.assertTrue(old.buyer_removed)
        self.assertEqual((latest.holder_contact.name, latest.buyer_removed), (OTHER["name"], False))

    def test_withdrawn_erasure_only_blocks_that_sale_date(self):
        kept, _ = self.sold_and_withdrawn()
        buyer_contact.erase_buyer_contact(kept.id, self.admin)
        self.assertEqual(self.refused(self.resent(kopare=OTHER)), [(self.a.id, "kopare")])
        self.ok(self.resent(dag=11, kopare=OTHER))
        (sale,) = sales(self.a, active=True)
        self.assertEqual((sale.herd_tracking_date, sale.holder_contact.name), (date(2025, 10, 11), OTHER["name"]))

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

    def test_legacy_round_patch_moves_kept_buyer_and_codes(self):  # Codex P1: the legacy endpoint is live
        contact, _ = self.sold_and_withdrawn()
        code = report_code.issue_code(self.h, self.round_, self.member, now=arsrapport.now())
        self.login("admin")

        def patched(end_date):
            response = self.client.patch(f"/api/manage/yearly_report_round/{self.round_.id}", json=end_date)
            self.assertEqual(response.get_json(), {"status": "success", "round": self.round_.id})  # legacy's contract
            return contacts(), db.ReportAccessCode.get_by_id(code.id).expires_at

        self.assertEqual(patched({"end_date": "2026-04-30"}), ({contact.id: EXTENDED_UNTIL}, EXTENDED))
        shortened = datetime(2026, 3, 17, tzinfo=STOCKHOLM)
        self.assertEqual(patched({"end_date": "2026-03-15"}), ({contact.id: shortened}, date(2026, 3, 15)))
        self.assertEqual(patched({"is_active": True}), ({contact.id: shortened}, date(2026, 3, 15)))
        buyer_contact.run(datetime(2026, 3, 17, 3, 50, tzinfo=STOCKHOLM))  # gone on 17 March, not on 1 April
        self.assertEqual(contacts(), {})

    def test_undoing_the_withdraws_void_gives_the_buyer_five_years_again(self):
        contact, _ = self.sold_and_withdrawn()
        (sale,) = sales(self.a)
        undo_herd_tracking_operation(
            sale.voided_operation_id, db.User.get_by_id(self.manager.id), "Fel tillbakadragning"
        )
        self.assertEqual([row.id for row in sales(self.a, active=True)], [sale.id])
        self.assertEqual(contacts(), {contact.id: db.BuyerContact.purge_at_for(SOLD_ON)})

    def test_contact_fields_need_tick(self):  # through the report: BuyerFields' rule on the server
        email_only = {**OTHER, "email": "xena@example.invalid"}
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
        self.ok(self.body(self.sald(self.a, "utanfor", 2025, 10, 10, kopare=OTHER), self.kvar(self.b, vikt=2.8)))
        (new,) = sales(self.a, active=True)
        self.assertEqual(new.holder_contact.name, OTHER["name"])

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

    def test_a_seller_cannot_probe_the_kept_buyer_through_a_void(self):  # Codex P1: the shared void's system reason
        self.sold_and_withdrawn()
        self.caretaker()
        owner = db.User.get_by_id(self.owner.id)

        def attested():  # an ordinary attestation through the rabbit page's PATCH
            response = self.client.patch(
                f"/api/individual/{self.a.number}", json={"herd": "G9001", "yearly_report_date": "2026-01-10"}
            )
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            (row,) = db.HerdTracking.select().where(
                db.HerdTracking.individual == self.a.id,
                db.HerdTracking.kind == "ATTESTATION",
                db.HerdTracking.voided_at.is_null(),
            )
            return row.id

        def sold():  # the owner's own sale outside the genebank, on the rabbit page
            record_sale(owner, self.a.id, "GX1", "2026-01-10", buyer=OTHER)
            (row,) = sales(self.a, active=True)
            return row.id

        voided = []
        for who, row in (("skotare", attested), ("owner", sold)):
            self.login(who)
            with self.subTest(who):
                answers = []
                for reason in ("Zelda hämtar den", "Ingen hämtar den"):
                    voided.append(row())
                    response = self.client.post(f"/api/v2/herd-tracking/{voided[-1]}/void", json={"reason": reason})
                    answers.append(response.status_code)
                self.assertEqual(answers, [200, 200])
        reasons = [db.HerdTracking.get_by_id(row_id).voided_reason for row_id in voided]
        self.assertEqual(reasons, [herd_tracking.UNDO_REASON] * 4)  # the typed text is never stored

    def test_late_withdraw_keeps_nothing(self):  # after kept_until only an editor withdraws, and nothing is kept
        self.ok(self.body(self.sald(self.a, "utanfor", 2025, 10, 10, kopare=BUYER), self.kvar(self.b, vikt=2.8)))
        self.at(KEPT_UNTIL + timedelta(hours=12))
        self.login("man")
        self.withdrawn(1, reason="Fel i rapporten")
        self.assertEqual(contacts(), {})
        self.assertNotIn("kopare_id", json.dumps(self.draft()))

    # Codex review of 8b19610: the nightly purge and a moved end_date against the writers, in two transactions

    def race(self, target, name, first, second):
        """
        Two real transactions: `first` runs until `target.name` has first returned inside it and holds its locks there
        while `second` starts, then goes on and commits. Returns each one's result, or the repr of what it raised.
        """
        if not _USE_POSTGRES:
            self.skipTest("row locks need PostgreSQL")
        barrier, results, original, paused = threading.Barrier(2, timeout=10), {}, getattr(target, name), []

        def held(*args, **kwargs):
            value = original(*args, **kwargs)
            if threading.current_thread().name == "first" and not paused:
                paused.append(True)
                barrier.wait()
                time.sleep(0.5)  # `second` meets the locks `first` holds
            return value

        def run(key, call):
            try:
                with APP.app_context():
                    if key == "second":
                        barrier.wait()
                    results[key] = call()
            except Exception as exc:  # noqa: BLE001  # the test reports any failure, a deadlock included
                results[key] = repr(exc)
            finally:
                db.DB_PROXY.close()

        with mock.patch.object(target, name, side_effect=held):
            threads = [
                threading.Thread(target=run, args=pair, name=pair[0]) for pair in (("first", first), ("second", second))
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
        self.assertFalse(any(thread.is_alive() for thread in threads), "hung threads")
        return results

    def resubmit(self):
        """Skicka of the withdrawn draft as the owner, which links the kept buyer again: a call for race."""
        sub = arsrapport.parse_submission(self.resent(), paper=False)
        access, user = arsrapport.Access("owner"), db.User.get_by_id(self.owner.id)
        return lambda: bool(arsrapport.submit(self.h, self.round_, access, user, sub))

    def withdraw(self, round_):
        access, user = arsrapport.Access("owner"), db.User.get_by_id(self.owner.id)
        return lambda: bool(arsrapport.withdraw(self.h, round_, access, user, revision=1))

    def extend(self):
        admin = db.User.get_by_id(self.admin.id)
        return lambda: arsrapport.save_round(2025, admin, end_date=EXTENDED).end_date

    def purge(self):
        return lambda: buyer_contact.purge_expired(PURGE_NIGHT)

    def sent(self):
        self.ok(self.body(self.sald(self.a, "utanfor", 2025, 10, 10, kopare=BUYER), self.kvar(self.b, vikt=2.8)))

    # Finding 2: the purge locks as the writers do, and reads purge_at again under the locks

    def test_purge_spares_a_kept_buyer_linked_again_meanwhile(self):
        contact, _ = self.sold_and_withdrawn()
        results = self.race(arsrapport, "drop_kept_buyers", self.resubmit(), self.purge())
        self.assertEqual(results, {"first": True, "second": 0})
        self.assertEqual([sale.holder_contact_id for sale in sales(self.a, active=True)], [contact.id])
        self.assertEqual(contacts(), {contact.id: db.BuyerContact.purge_at_for(SOLD_ON)})

    def test_purge_waits_for_an_undo_of_the_withdraws_void(self):  # no deadlock through ON DELETE SET NULL
        contact, _ = self.sold_and_withdrawn()
        (sale,) = sales(self.a)
        manager = db.User.get_by_id(self.manager.id)

        def undo():
            return undo_herd_tracking_operation(sale.voided_operation_id, manager, "Fel tillbakadragning")[
                "individual_ids"
            ]

        results = self.race(herd_tracking, "_unvoid_rows", undo, self.purge())
        self.assertEqual(results, {"first": [self.a.id], "second": 0})
        self.assertEqual([row.id for row in sales(self.a, active=True)], [sale.id])
        self.assertEqual(contacts(), {contact.id: db.BuyerContact.purge_at_for(SOLD_ON)})

    def test_purge_spares_a_kept_buyer_of_a_round_extended_meanwhile(self):
        contact, _ = self.sold_and_withdrawn()
        results = self.race(arsrapport, "_move_kept_buyers", self.extend(), self.purge())
        self.assertEqual(results, {"first": EXTENDED, "second": 0})
        self.assertEqual(contacts(), {contact.id: EXTENDED_UNTIL})

    # Finding 3: a moved end_date and Dra tillbaka take the round row's lock

    def test_withdraw_reads_an_end_date_moved_meanwhile(self):  # the change first; withdraw holds a stale round
        self.sent()
        results = self.race(arsrapport, "_move_kept_buyers", self.extend(), self.withdraw(self.round_))
        self.assertEqual(results, {"first": EXTENDED, "second": True})
        (sale,) = sales(self.a)
        self.assertEqual(contacts(), {sale.holder_contact_id: EXTENDED_UNTIL})

    def test_end_date_moved_after_a_withdraw_moves_its_buyer(self):  # withdraw first
        self.sent()
        results = self.race(arsrapport, "_mail", self.withdraw(self.round_), self.extend())
        self.assertEqual(results, {"first": True, "second": EXTENDED})
        (sale,) = sales(self.a)
        self.assertEqual(contacts(), {sale.holder_contact_id: EXTENDED_UNTIL})

    def test_end_date_moved_during_a_resubmission_leaves_the_linked_buyer(self):  # five years, not the round's end
        contact, _ = self.sold_and_withdrawn()
        results = self.race(arsrapport, "drop_kept_buyers", self.resubmit(), self.extend())
        self.assertEqual(results, {"first": True, "second": EXTENDED})
        self.assertEqual(contacts(), {contact.id: db.BuyerContact.purge_at_for(SOLD_ON)})

    def test_end_date_moved_during_a_resubmission_that_links_buyers_against_id_order(self):  # Codex P2, finding 3
        # b's buyer first and a's on Ändra: Skicka links a's (the higher id) before b's, against the buyers' id order
        self.ok(self.body(self.kvar(self.a, vikt=2.8), self.sald(self.b, "utanfor", 2025, 10, 10, kopare=BUYER)))
        both = (self.sald(self.a, "utanfor", 2025, 10, 10, kopare=OTHER), self.sald(self.b, "utanfor", 2025, 10, 10))
        self.ok({**self.body(*both), "revision": 1})
        self.withdrawn(2)
        kept = [sales(rabbit)[-1].holder_contact_id for rabbit in (self.a, self.b)]
        self.assertGreater(kept[0], kept[1])
        rabbits = {
            key: {**entry, "sald": {k: v for k, v in entry["sald"].items() if k != "fran_rapport"}}
            for key, entry in self.draft()["rabbits"].items()
        }
        data = {k: v for k, v in self.draft().items() if k != "form"}
        sub = arsrapport.parse_submission(self.body(**{**data, "rabbits": rabbits}), paper=False)
        owner = db.User.get_by_id(self.owner.id)

        def resubmit():
            return bool(arsrapport.submit(self.h, self.round_, arsrapport.Access("owner"), owner, sub))

        results = self.race(individual_commands, "record_herd_tracking", resubmit, self.extend())
        self.assertEqual(results, {"first": True, "second": EXTENDED})
        self.assertEqual(contacts(), dict.fromkeys(kept, db.BuyerContact.purge_at_for(SOLD_ON)))

    def test_end_date_moved_during_the_invitations(self):  # Codex P2, finding 6: the job takes the round row first
        # G9000 is newer than G9001 but first in the job's herd order, and G9001's code is the older: the job revokes
        # G9000's and then G9001's, against the order of the herds' ids and of the codes' rows alike
        g9000 = db.Herd.create(genebank=self.gotland, herd="G9000", is_active=True)
        self.main_member(g9000, "g9000@example.invalid")
        for herd in (self.h, g9000):
            member = report_code.invitation_recipient(herd)
            report_code.issue_code(herd, self.round_, member, now=arsrapport.now())
            db.Member.update(end_date=DAY0).where(db.Member.id == member.id).execute()  # a new main member since
            new = {"first_name": "Ny", "last_name": "Ny", "email": f"ny.{herd.herd}@example.invalid"}
            db.Member.create(**new, membership=herd.membership, role="huvudmedlem")

        def job():
            return arsrapport_invite.send_due_invitations(arsrapport.now())

        results = self.race(report_code, "revoke", job, self.extend())
        self.assertEqual(results, {"first": 2, "second": EXTENDED})  # the job's failure would be 0, logged
        active = db.ReportAccessCode.select().where(db.ReportAccessCode.revoked_at.is_null())
        self.assertEqual([(code.member.first_name, code.expires_at) for code in active], [("Ny", EXTENDED)] * 2)
