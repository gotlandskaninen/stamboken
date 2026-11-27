#!/usr/bin/env python3
"""
Tests for the report's sale dialog registering the sale at once (Jonas 2026-11-26): POST …/forsaljning writes one
rabbit's sale as Sälj does, under the rules Skicka checks. Synthetic herds, rabbits and buyers only.

isort:skip_file
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from unittest import mock
from uuid import uuid4

import utils.arsrapport as arsrapport
import utils.arsrapport_pdf as arsrapport_pdf
import utils.buyer_contact as buyer_contact
import utils.database as db
import utils.herd_tracking as herd_tracking
import utils.inbox as inbox
import utils.settings as settings
from herdbook import APP
from peewee import OperationalError
from utils.herd_tracking import BUYER_REMOVED, CONTACT_OR_MEMBERSHIP_NEEDED, REPORT_BEVIS_NOT_YET
from utils.individual_commands import record_sale

from tests.arsrapport_fixtures import ArsrapportTest
from tests.inbox_fixtures import QUALITY
from tests.test_arsrapport_pdf import text_of
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

    def undo(self, sale, op="00000000-0000-4000-8000-000000000001"):
        """The report's Ångra: its own route, which checks the seller's rule again now."""
        return self.api("POST", f"/besattning/G9001/2025/forsaljning/{sale.id}/angra", operation_id=op)

    def test_the_seller_undoes_it_within_seven_days(self):
        self.sold(kopare=BUYER)
        (sale,) = sales(self.a)
        self.login("man")  # a manager's wider right stays on the rabbit page, also through this route
        self.assertIsNone(self.page()["sales"][0]["undo"])
        self.assertEqual(self.undo(sale).status_code, 403)
        self.login("owner")
        later = datetime.now(timezone.utc) + herd_tracking.SALE_UNDO_WINDOW + timedelta(minutes=1)
        with mock.patch.object(herd_tracking, "_now_utc", return_value=later):
            self.assertIsNone(self.page()["sales"][0]["undo"])
            self.assertEqual(self.undo(sale).status_code, 403)  # checked at undo time, not only when shown
        response = self.undo(sale)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(self.undo(sale).status_code, 200)  # the same Ångra again: nothing more happens
        self.assertEqual(sales(self.a), [])
        self.assertFalse(db.BuyerContact.select().exists())
        self.assertIn(self.a.id, [row["id"] for row in self.page()["rabbits"]])  # back on the list

    def test_angra_here_never_undoes_a_sale_the_report_wrote(self):  # REPORT_ROW: Ändra changes it
        sent = self.skicka(self.sald(self.a, "utanfor", 2025, 10, 10, kopare=BUYER), self.kvar(self.b, vikt=2.8))
        self.assertEqual(sent.status_code, 200)
        self.assertEqual(self.undo(sales(self.a)[0]).status_code, 403)
        self.assertEqual(len(sales(self.a)), 1)

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

    def test_rabbit_page_sale_respects_erasure_after_angra(self):
        self.sold(kopare=BUYER)
        (sale,) = sales(self.a)
        buyer_contact.erase_buyer_contact(sale.holder_contact_id, self.admin)
        self.assertEqual(self.undo(sale).status_code, 200)
        mails = self.buyer_mails()
        path = f"/api/individual/{self.a.number}"
        body = {"herd": "GX1", "selling_date": SOLD_ON.isoformat(), "buyer": BUYER}
        refused = self.client.patch(path, json=body)
        self.assertEqual((refused.status_code, refused.get_json()["detail"]), (409, BUYER_REMOVED))
        self.assertFalse(sales(self.a))
        self.assertFalse(db.BuyerContact.select().exists())
        self.assertEqual(self.buyer_mails(), mails)

        unnamed = self.client.patch(path, json={**body, "buyer": {"not_recorded": True}})
        self.assertEqual(unnamed.status_code, 200, unnamed.get_data(as_text=True))
        (unnamed_sale,) = sales(self.a)
        self.assertTrue(unnamed_sale.buyer_removed)
        self.assertEqual(self.undo(unnamed_sale, str(uuid4())).status_code, 200)
        later = self.client.patch(path, json={**body, "selling_date": "2025-10-11", "buyer": OTHER})
        self.assertEqual(later.status_code, 200, later.get_data(as_text=True))
        self.assertEqual(sales(self.a)[0].holder_contact.name, OTHER["name"])

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

    def test_sold_rabbit_defect_survives_withdrawal_and_resubmission(self):
        self.sold(till="G9002")
        defects = [{"individual_id": self.a.id, "beskrivning": "Skev tand"}]
        body = self.body(self.kvar(self.b, vikt=2.8), health="ja", defects=defects)
        path = "/besattning/G9001/2025"
        self.assertEqual(self.api("POST", f"{path}/skicka", **body).status_code, 200)
        data = arsrapport.stored_body(body)
        saved = self.api(
            "PUT", f"{path}/utkast", data={**data, "form": data}, updated_at=None, submission_key=None, revision=1
        )
        self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
        withdrawn = self.api("POST", f"{path}/dra-tillbaka", revision=1)
        self.assertEqual(withdrawn.status_code, 200, withdrawn.get_data(as_text=True))
        draft = withdrawn.get_json()["draft"]["data"]
        self.assertEqual(draft.pop("form")["defects"], defects)
        self.assertEqual(draft["defects"], defects)

        resent = self.skicka(**draft)
        self.assertEqual(resent.status_code, 200, resent.get_data(as_text=True))
        report = db.YearlyHerdReport.get_by_id(resent.get_json()["report_id"])
        self.assertEqual(json.loads(report.data)["defects"], [{**defects[0], "foto": None}])

    def test_a_month_only_sale_stays_month_only(self):  # review r1: in the view and the register extract
        self.sold(dag=None, kopare=BUYER)
        self.sold(rabbit=self.b, ar=2026, manad=1, dag=None, till="G9002")
        page = self.page()
        self.assertEqual([(s["date"], s["day_known"]) for s in page["sales"]], [("2025-10-31", False)])
        row = next(row for row in page["rabbits"] if row["id"] == self.b.id)
        self.assertEqual((row["later"]["date"], row["later"]["day_known"]), ("2026-01-10", False))
        sold, _ = arsrapport_pdf._sold_and_dead(self.h, self.round_)  # pylint: disable=protected-access
        self.assertEqual([entry["date"] for entry in sold], ["2025-10"])

    def test_after_the_last_day_the_sale_needs_the_reason_skicka_asks(self):  # review r1: it goes with Skicka
        self.at(date(2026, 3, 31))
        self.login("man")
        self.assertEqual([c for c, _ in self.refusals(kopare=BUYER)], ["orsak_kravs"])
        self.assertEqual(sales(self.a), [])

    def test_an_old_tabs_autosave_does_not_bring_the_sale_back(self):  # review r1: Skicka would refuse it
        sald = {"till": "utanfor", "ar": 2026, "manad": 1, "dag": None}
        entries = {str(self.a.id): {"val": "sald", "sald": sald}, str(self.b.id): {"val": "kvar", "vikt": 2.8}}
        data = {**arsrapport.stored_body(self.body()), "rabbits": entries, "form": {"rabbits": entries}}
        put = {"submission_key": None, "revision": None}
        saved = self.api("PUT", "/besattning/G9001/2025/utkast", data=data, updated_at=None, **put).get_json()
        self.sold(ar=2026, manad=1, dag=None, kopare=BUYER)
        self.at(DAY0 + timedelta(days=1))  # the made-up day of a month-only sale moves with the clock
        old_tab = {**data, "message": "Från en annan flik"}
        response = self.api("PUT", "/besattning/G9001/2025/utkast", data=old_tab, updated_at=saved["updated_at"], **put)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        draft = db.YearlyReportDraft.get()
        self.assertEqual((set(draft.data["rabbits"]), draft.data["message"]), ({str(self.b.id)}, "Från en annan flik"))
        self.assertEqual(set(draft.data["form"]["rabbits"]), {str(self.b.id)})

    def test_january_sale_drops_stale_kvar_and_keeps_other_edits(self):
        path = "/besattning/G9001/2025/utkast"
        data = arsrapport.stored_body(self.body(self.kvar(self.a, vikt=2.8), self.kvar(self.b, vikt=2.8)))
        put = {"submission_key": None, "revision": None}
        first = self.api("PUT", path, data={**data, "form": data}, updated_at=None, **put)
        self.assertEqual(first.status_code, 200)
        self.sold(ar=2026, manad=1, dag=5, till="G9002")
        data["message"] = "Från en annan flik"
        second = self.api("PUT", path, data={**data, "form": data}, updated_at=first.json["updated_at"], **put)
        self.assertEqual(second.status_code, 200, second.get_data(as_text=True))
        draft = self.page()["draft"]["data"]
        for copy in (draft.pop("form"), draft):
            self.assertEqual(copy["rabbits"], {str(self.b.id): data["rabbits"][str(self.b.id)]})
            self.assertEqual(copy["message"], data["message"])
        sent = self.skicka(**draft)
        self.assertEqual(sent.status_code, 200, sent.get_data(as_text=True))

    def test_the_receipt_counts_the_years_sales_besides_the_report(self):  # review r1: not "0 sålda"
        self.sold(dag=None, kopare=BUYER)
        sent = self.skicka(self.kvar(self.b, vikt=2.8))
        self.assertEqual(sent.status_code, 200, sent.get_data(as_text=True))
        self.assertEqual(sent.get_json()["summary"]["salda"], 1)
        submission = db.YearlyReportSubmission.get()
        self.assertEqual(
            submission.data["salda_direkt"],
            [{"individual_id": self.a.id, "till": "utanfor", "ar": 2025, "manad": 10, "dag": None}],
        )
        text = text_of(arsrapport_pdf.receipt_pdf(db.YearlyHerdReport.get(), submission))
        self.assertIn("Såld utanför genbanken", text)
        self.assertIn("2025-10", text)

    def test_angra_waits_until_skicka_has_recorded_the_sale(self):
        self.sold(till="G9002")
        (sale,) = sales(self.a)
        owner = db.User.get_by_id(self.owner.id)
        access = arsrapport.report_access(owner, self.h)
        sold_besides = arsrapport._sold_besides  # pylint: disable=protected-access

        def try_undo():
            with APP.app_context(), db.DB_PROXY.connection_context():
                try:
                    with db.DB_PROXY.atomic():
                        db.DB_PROXY.execute_sql("SET LOCAL lock_timeout = '250ms'")
                        arsrapport.undo_sale(self.h, access, owner, sale.id, uuid4())
                except OperationalError as exc:
                    self.assertEqual(exc.__context__.pgcode, "55P03")  # lock_not_available

        def before_receipt(*args):
            with ThreadPoolExecutor(max_workers=1) as worker:
                worker.submit(try_undo).result(timeout=10)
            return sold_besides(*args)

        with mock.patch.object(arsrapport, "_sold_besides", side_effect=before_receipt) as snapshot:
            sent = self.skicka(self.kvar(self.b, vikt=2.8))
        snapshot.assert_called_once()
        self.assertEqual(sent.status_code, 200, sent.get_data(as_text=True))
        self.assertEqual(sent.get_json()["summary"]["salda"], 1)
        self.assertEqual(self.undo(sale).status_code, 200)
        self.assertEqual(db.YearlyReportSubmission.get().data["salda_direkt"][0]["individual_id"], self.a.id)

    def test_paper_rechecks_the_item_under_the_locks(self):
        item, _ = inbox.create_upload(self.owner, self.h, None, [("inkorg/original/x.jpg", "0" * 64, QUALITY)])
        db.InboxDocument.update(doc_type="arsblankett").where(db.InboxDocument.item == item.id).execute()
        helper = db.User.get_by_id(self.helper.id)
        inbox.take(db.InboxItem.get_by_id(item.id), helper, over=False)
        self.login("hjalp")
        self.sold(post=item.id, kopare={k: v for k, v in OTHER.items() if k != "postal_address"})  # as written
        access = arsrapport.report_access(helper, self.h, item.id)
        inbox.take(db.InboxItem.get_by_id(item.id), db.User.get_by_id(self.manager.id), over=True)  # meanwhile
        with self.assertRaises(inbox.InboxError) as caught:  # _lock_form: the item is the manager's now
            arsrapport.sell_now(
                self.h, self.round_, access, helper, self.b.id, {"till": "G9002", "ar": 2025, "manad": 9, "dag": None}
            )
        self.assertEqual(caught.exception.status, 409)
        self.assertRegex(str(caught.exception.detail), r"har posten\. Ta över den")
        self.assertEqual(sales(self.b), [])

    def test_dra_tillbaka_leaves_a_direct_sale(self):  # review r1: the register's, not the report's
        self.sold(kopare=BUYER)
        (sale,) = sales(self.a)
        self.assertEqual(self.skicka(self.kvar(self.b, vikt=2.8)).status_code, 200)
        withdrawn = self.api("POST", "/besattning/G9001/2025/dra-tillbaka", revision=1)
        self.assertEqual(withdrawn.status_code, 200, withdrawn.get_data(as_text=True))
        self.assertEqual([(s.id, s.holder_contact_id) for s in sales(self.a)], [(sale.id, sale.holder_contact_id)])
        self.assertNotIn(self.a.id, [row["id"] for row in withdrawn.get_json()["rabbits"]])

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
