#!/usr/bin/env python3
"""
Tests for the report's sale dialog registering the sale at once (Jonas 2026-11-26): POST …/forsaljning writes one
rabbit's sale as Sälj does, under the rules Skicka checks. Synthetic herds, rabbits and buyers only.

isort:skip_file
"""

import json
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import utils.arsrapport as arsrapport
import utils.buyer_contact as buyer_contact
import utils.database as db
import utils.herd_tracking as herd_tracking
import utils.inbox as inbox
import utils.settings as settings
from herdbook import APP
from utils.herd_tracking import BUYER_REMOVED, CONTACT_OR_MEMBERSHIP_NEEDED, REPORT_BEVIS_NOT_YET
from utils.individual_commands import record_sale

from tests.arsrapport_fixtures import ArsrapportTest
from tests.inbox_fixtures import QUALITY
from tests.test_buyer_notice_only import REAL_REPORT_BEVIS_FROM

DAY0 = date(2026, 1, 10)
SOLD_ON = date(2025, 10, 10)
BUYER = {
    "name": "Zelda Direktköpare",
    "town": "Klintehamn",
    "postal_address": "Testgatan 1",
    "contact_consent": True,
    "email": "zelda@example.invalid",
}
OTHER = {"name": "Ylva Annankopare", "town": "Slite", "postal_address": "Testgatan 2"}


def sales(rabbit, active=True):
    query = db.HerdTracking.select().where(db.HerdTracking.individual == rabbit.id, db.HerdTracking.kind == "TRANSFER")
    return list(query.where(db.HerdTracking.voided_at.is_null(active)).order_by(db.HerdTracking.id))


class SellNowTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        context = APP.app_context()  # the mail templates read the app
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

    def sell(self, rabbit=None, till="utanfor", ar=2025, manad=10, dag=10, kopare=None, post=None, **sald):
        rabbit = rabbit or self.a
        body = {"till": till, "ar": ar, "manad": manad, "dag": dag, "kopare": kopare, **sald}
        path = "/besattning/G9001/2025/forsaljning" + (f"?post={post}" if post else "")
        return self.api("POST", path, individual_id=rabbit.id, sald=body)

    def sold(self, **kwargs):
        response = self.sell(**kwargs)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def refusals(self, **kwargs):
        response = self.sell(**kwargs)
        self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
        return [(r["code"], r["message"]) for r in response.get_json()["refusals"]]

    def page(self):
        return self.api("GET", "/besattning/G9001/2025").get_json()

    def skicka(self, *entries, **fields):
        return self.api("POST", "/besattning/G9001/2025/skicka", **self.body(*entries, **fields))

    def buyer_mails(self):
        rows = db.MailMessage.select().where(db.MailMessage.recipient_kind == "buyer_contact")
        return [m.kind for m in rows.order_by(db.MailMessage.id)]

    def test_a_sale_outside_is_registered_at_once_and_the_buyer_told(self):
        answer = self.sold(kopare=BUYER)
        (sale,) = sales(self.a)
        self.assertEqual(
            (sale.herd.herd, sale.herd_tracking_date, str(sale.operation_id)), ("GX1", SOLD_ON, answer["operation_id"])
        )
        contact = sale.holder_contact
        self.assertEqual((contact.name, contact.purge_at), (BUYER["name"], db.BuyerContact.purge_at_for(SOLD_ON)))
        self.assertEqual(self.buyer_mails(), ["kopare.information"])
        page = self.page()
        self.assertNotIn(self.a.id, [row["id"] for row in page["rabbits"]])  # sold in the year: off the list
        (listed,) = page["sales"]
        self.assertEqual((listed["individual_id"], listed["undo"]), (self.a.id, sale.id))
        self.assertNotIn("Zelda", json.dumps(page))

    def test_a_sale_in_the_genebank_or_without_a_buyer(self):
        self.sold(till="G9002")
        self.assertEqual([(s.herd.herd, s.holder_contact_id) for s in sales(self.a)], [("G9002", None)])
        self.sold(rabbit=self.b, kopare={"not_recorded": True})
        self.assertEqual([(s.herd.herd, s.holder_contact_id) for s in sales(self.b)], [("GX1", None)])
        self.assertFalse(db.BuyerContact.select().exists())

    def test_the_reports_rules_refuse_it_and_nothing_is_written(self):
        email_only = {**OTHER, "email": "xena@example.invalid"}
        no_address = {k: v for k, v in OTHER.items() if k != "postal_address"}
        self.assertEqual([c for c, _ in self.refusals()], ["kopare_saknas"])
        self.assertEqual(self.refusals(kopare=email_only), [("kopare", CONTACT_OR_MEMBERSHIP_NEEDED)])
        self.assertEqual(self.refusals(kopare=no_address), [("kopare", "Ange köparens postadress.")])
        self.assertEqual([c for c, _ in self.refusals(ar=2026, manad=3, kopare=BUYER)], ["forsaljning"])  # future
        with mock.patch.object(herd_tracking, "REPORT_BEVIS_FROM", REAL_REPORT_BEVIS_FROM):
            self.assertEqual(self.refusals(kopare=BUYER), [("kopare", REPORT_BEVIS_NOT_YET)])
        self.assertEqual(sales(self.a), [])
        self.assertFalse(db.BuyerContact.select().exists())
        self.login("man")  # a manager's sale needs no address (old papers)
        self.sold(kopare=no_address)

    def test_an_erased_buyer_is_not_registered_again(self):
        self.assertEqual(
            self.skicka(
                self.sald(self.a, "utanfor", 2025, 10, 10, kopare=BUYER), self.kvar(self.b, vikt=2.8)
            ).status_code,
            200,
        )
        buyer_contact.erase_buyer_contact(sales(self.a)[0].holder_contact_id, self.admin)
        self.assertEqual(self.api("POST", "/besattning/G9001/2025/dra-tillbaka", revision=1).status_code, 200)
        self.assertEqual(self.refusals(kopare=OTHER), [("kopare", BUYER_REMOVED)])

    def test_only_while_the_round_is_open_and_before_the_first_skicka(self):
        self.at(date(2026, 3, 31))  # after end_date the owner's round is closed
        self.assertEqual([c for c, _ in self.refusals(kopare=BUYER)], ["rundan_stangd"])
        self.at(DAY0)
        self.assertEqual(self.skicka(self.kvar(self.a, vikt=2.8), self.kvar(self.b, vikt=2.8)).status_code, 200)
        response = self.sell(kopare=BUYER)
        self.assertEqual((response.status_code, response.get_json()["detail"]), (409, arsrapport.SOLD_WITH_SKICKA))
        self.assertEqual(sales(self.a), [])

    def test_skicka_does_not_register_it_again(self):
        self.sold(kopare=BUYER)
        refused = self.skicka(self.sald(self.a, "utanfor", 2025, 10, 10, kopare=BUYER), self.kvar(self.b, vikt=2.8))
        self.assertEqual(refused.status_code, 422)  # a stale entry for it: the rabbit is not the report's any more
        self.assertEqual(self.skicka(self.kvar(self.b, vikt=2.8)).status_code, 200)
        self.assertEqual(len(sales(self.a)), 1)

    def test_a_sale_the_report_wrote_has_no_angra_here(self):  # REPORT_ROW: Ändra changes it
        sent = self.skicka(self.sald(self.a, "utanfor", 2025, 10, 10, kopare=BUYER), self.kvar(self.b, vikt=2.8))
        self.assertEqual(sent.status_code, 200)
        self.assertIsNone(self.page()["sales"][0]["undo"])

    def test_the_drafts_entry_goes_with_the_sale(self):  # a reload before the form's next save finds no entry
        sald = {"till": "utanfor", "ar": 2026, "manad": 1, "dag": 5}
        entries = {str(self.a.id): {"val": "sald", "sald": sald}, str(self.b.id): {"val": "kvar", "vikt": 2.8}}
        data = {**arsrapport.stored_body(self.body()), "rabbits": entries, "form": {"rabbits": entries}}
        saved = self.api(
            "PUT", "/besattning/G9001/2025/utkast", data=data, updated_at=None, submission_key=None, revision=None
        )
        self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
        self.sold(ar=2026, manad=1, dag=5, kopare=BUYER)
        draft = db.YearlyReportDraft.get()
        self.assertEqual(set(draft.data["rabbits"]), {str(self.b.id)})
        self.assertEqual(set(draft.data["form"]["rabbits"]), {str(self.b.id)})
        self.assertEqual(draft.updated_at.isoformat(), saved.get_json()["updated_at"])

    def test_a_sale_after_new_year_keeps_the_row_counted_by_its_move(self):
        self.sold(ar=2026, manad=1, dag=5, kopare=BUYER)
        row = next(row for row in self.page()["rabbits"] if row["id"] == self.a.id)
        self.assertEqual((row["state"], row["undo"], row["undo_to"]), ("via_flytt", sales(self.a)[0].id, "GX1"))
        self.assertEqual(self.skicka(self.kvar(self.b, vikt=2.8)).status_code, 200)
        self.assertEqual(len(sales(self.a)), 1)

    def test_the_seller_undoes_it_within_seven_days(self):
        self.sold(kopare=BUYER)
        (sale,) = sales(self.a)
        self.login("man")  # a manager's wider right stays on the rabbit page
        self.assertIsNone(self.page()["sales"][0]["undo"])
        self.login("owner")
        later = datetime.now(timezone.utc) + herd_tracking.SALE_UNDO_WINDOW + timedelta(minutes=1)
        with mock.patch.object(herd_tracking, "_now_utc", return_value=later):
            self.assertIsNone(self.page()["sales"][0]["undo"])
        response = self.client.post(
            f"/api/v2/herd-tracking/{sale.id}/void", json={"reason": "Ångrad av den som registrerade den"}
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(sales(self.a), [])
        self.assertFalse(db.BuyerContact.select().exists())
        self.assertIn(self.a.id, [row["id"] for row in self.page()["rabbits"]])  # back on the list

    def undo(self, sale):
        return self.client.post(
            f"/api/v2/herd-tracking/{sale.id}/void", json={"reason": "Ångrad av den som registrerade den"}
        )

    def test_angra_on_the_row_is_for_the_move_it_shows(self):  # review r1: a buyback and a resale after it
        self.sold(ar=2026, manad=1, dag=5, till="G9002")
        record_sale(db.User.get_by_id(self.admin.id), self.a.id, "G9001", "2026-01-07")  # bought back
        record_sale(db.User.get_by_id(self.owner.id), self.a.id, "GX1", "2026-01-08", buyer=OTHER)  # sold again
        row = next(row for row in self.page()["rabbits"] if row["id"] == self.a.id)
        self.assertEqual((row["later"]["date"], row["undo"], row["undo_to"]), ("2026-01-05", None, "G9002"))

    def test_an_erasure_outlives_angra(self):  # review r1: the voided direct sale keeps blocking that buyer
        self.sold(kopare=BUYER)
        (sale,) = sales(self.a)
        buyer_contact.erase_buyer_contact(sale.holder_contact_id, self.admin)
        self.assertEqual(self.undo(sale).status_code, 200)
        self.assertEqual(self.refusals(kopare=BUYER), [("kopare", BUYER_REMOVED)])
        self.assertEqual(self.refusals(kopare=OTHER), [("kopare", BUYER_REMOVED)])
        self.sold(manad=11, kopare=OTHER)  # another sale, another day

    def test_an_erasure_takes_the_paper_form_behind_a_direct_sale(self):  # review r1: every page of it
        stored = [(f"inkorg/original/{n}.jpg", f"{n}".rjust(64, "0"), QUALITY) for n in range(2)]
        item, _ = inbox.create_upload(self.owner, self.h, None, stored)
        db.InboxDocument.update(doc_type="arsblankett").where(db.InboxDocument.item == item.id).execute()
        inbox.take(db.InboxItem.get_by_id(item.id), db.User.get_by_id(self.helper.id), over=False)
        self.login("hjalp")
        self.sold(post=item.id, kopare=BUYER)
        (sale,) = sales(self.a)
        buyer_contact.erase_buyer_contact(sale.holder_contact_id, self.admin)
        pages = db.InboxDocument.select().where(db.InboxDocument.item == item.id)
        self.assertEqual([page.original_path for page in pages], [None, None])

    def test_a_rabbit_sold_in_the_year_keeps_its_defect(self):  # review r1 (Opus 1): it left the list
        self.sold(kopare=BUYER)
        defects = [{"individual_id": self.a.id, "beskrivning": "Skev tand"}]
        sent = self.skicka(self.kvar(self.b, vikt=2.8), health="ja", defects=defects)
        self.assertEqual(sent.status_code, 200, sent.get_data(as_text=True))
        self.assertEqual(json.loads(db.YearlyHerdReport.get().data)["defects"], [{**defects[0], "foto": None}])

    def test_paper_rechecks_the_item_under_the_locks(self):
        item, _ = inbox.create_upload(self.owner, self.h, None, [("inkorg/original/x.jpg", "0" * 64, QUALITY)])
        db.InboxDocument.update(doc_type="arsblankett").where(db.InboxDocument.item == item.id).execute()
        helper = db.User.get_by_id(self.helper.id)
        inbox.take(db.InboxItem.get_by_id(item.id), helper, over=False)
        self.login("hjalp")
        self.sold(post=item.id, kopare={k: v for k, v in OTHER.items() if k != "postal_address"})  # as written
        access = arsrapport.report_access(helper, self.h, item.id)
        inbox.take(db.InboxItem.get_by_id(item.id), db.User.get_by_id(self.manager.id), over=True)  # meanwhile
        with self.assertRaises(Exception) as caught:
            arsrapport.sell_now(
                self.h, self.round_, access, helper, self.b.id, {"till": "G9002", "ar": 2025, "manad": 9, "dag": None}
            )
        self.assertEqual(getattr(caught.exception, "status", None), 409)
        self.assertEqual(sales(self.b), [])

    def test_a_buyer_kept_across_dra_tillbaka_is_linked(self):  # K1, and the draft's next save spares it
        ok = self.skicka(self.sald(self.a, "utanfor", 2025, 10, 10, kopare=BUYER), self.kvar(self.b, vikt=2.8))
        self.assertEqual(ok.status_code, 200)
        (old,) = sales(self.a)
        view = self.api("POST", "/besattning/G9001/2025/dra-tillbaka", revision=1).get_json()
        self.sold(kopare_id=old.holder_contact_id)
        (new,) = sales(self.a)
        self.assertEqual(new.holder_contact_id, old.holder_contact_id)
        kvar = {"val": "kvar", "vikt": 2.8}
        data = {
            **arsrapport.stored_body(self.body()),
            "rabbits": {str(self.b.id): kvar},
            "form": {"rabbits": {str(self.b.id): kvar}},
        }
        response = self.api(
            "PUT",
            "/besattning/G9001/2025/utkast",
            data=data,
            updated_at=view["draft"]["updated_at"],
            submission_key=None,
            revision=None,
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual([c.id for c in db.BuyerContact.select()], [old.holder_contact_id])
