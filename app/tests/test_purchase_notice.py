#!/usr/bin/env python3
"""
Tests for "Köpt i år" and "Anmäl köpet" (step 4a, Task 5): the bought mark on the report's list, the purchase notice
and its kontroll item, matching a seller's sale proposal, and the notice closing once the transfer is registered.
Synthetic herds and rabbits only.

isort:skip_file
"""

from datetime import date
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.mail as mail
import utils.purchase_notice as purchase_notice
import utils.report_code as report_code
import utils.settings as settings
from herdbook import APP
from utils.report_code import CodeActor

from tests.arsrapport_fixtures import ArsrapportTest
from tests.ht_helpers import ht_row

DAY0 = date(2026, 1, 10)


def notices():
    return list(db.InboxItem.select().where(db.InboxItem.ref_type == "kopanmalan").order_by(db.InboxItem.id))


class PurchaseNoticeTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        context = APP.app_context()  # request_hash reads the app's secret key
        context.push()
        self.addCleanup(context.pop)
        patcher = mock.patch.multiple(settings.mail, link_secret="test-link-secret", link_hosts=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.at(DAY0)
        self.round_ = self.round(2025)
        self.h = db.Herd.create(genebank=self.gotland, herd="G9001", herd_name="Köparen", is_active=True)
        self.seller = db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.owner.add_role("owner", self.h.id)
        now = arsrapport.now()
        self.code = report_code.issue_code(self.h, self.round_, self.main_member(self.h, "g1@example.invalid"), now=now)
        member = self.main_member(self.seller, "g2@example.invalid")
        self.seller_code = report_code.issue_code(self.seller, self.round_, member, now=now)
        self.own = self.rabbits(self.h, 1)[0]
        self.a, self.b = self.rabbits(self.seller, 2)

    def notify(self, number=None, from_herd="G9002", when="2025-05-14", herd="G9001", year=2025):
        number = self.a.number if number is None else number
        return self.api("POST", f"/besattning/{herd}/{year}/kop", number=number, from_herd=from_herd, date=when)

    def open_link(self, code):
        response = self.client.post("/api/v2/rapport/oppna", json={"token": mail.link_token("rapport", code.id)})
        self.assertEqual(response.status_code, 200)

    def view(self):
        response = self.api("GET", "/besattning/G9001/2025")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def seller_proposes(self, month=5, day=10):
        """G9002's link reports a sold to G9001: a sale proposal (5.9)."""
        access = arsrapport.code_access(self.seller, self.round_, [self.seller_code.id])
        body = self.body(self.sald(self.a, "G9001", 2025, month, day), self.kvar(self.b, vikt=2.8))
        arsrapport.submit(
            self.seller,
            self.round_,
            access,
            CodeActor(self.seller_code),
            arsrapport.parse_submission(body, paper=False),
        )
        return db.SaleProposal.get(db.SaleProposal.individual == self.a.id)

    def kop_anmalt(self):
        self.login("man")
        response = self.client.get(f"/api/v2/arsrapport/2025/status?genebank_id={self.gotland.id}")
        return {row["herd"]: row["flags"]["kop_anmalt"] for row in response.get_json()["rows"]}["G9001"]

    def test_report_list_marks_bought_this_year(self):
        old, new, back = self.rabbits(self.seller, 3)
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=old, herd_tracking_date=date(2024, 6, 1))
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=new, herd_tracking_date=date(2025, 5, 14))
        # bought, sold back and bought again in the year: the latest purchase is the mark
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=back, herd_tracking_date=date(2025, 3, 1))
        ht_row("TRANSFER", from_herd=self.h, herd=self.seller, individual=back, herd_tracking_date=date(2025, 4, 1))
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=back, herd_tracking_date=date(2025, 9, 2))
        rows = {row["number"]: row["kopt"] for row in arsrapport.report_list(self.h, 2025)}
        self.assertEqual(
            rows,
            {
                self.own.number: None,
                old.number: None,
                new.number: {"datum": "2025-05-14", "fran": "G9002"},
                back.number: {"datum": "2025-09-02", "fran": "G9002"},
            },
        )

    def test_purchase_notice_creates_kontroll_item(self):
        self.login("owner")
        response = self.notify()
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        (item,) = notices()
        fields = {"number": self.a.number, "from_herd": "G9002", "date": "2025-05-14"}
        self.assertEqual(response.get_json(), {"id": item.id, **fields, "state": "ny"})
        self.assertEqual(
            (item.kind, item.state, item.herd_id, item.genebank_id, item.sender_user_id, item.ref_id),
            ("kontroll", "ny", self.h.id, self.gotland.id, None, None),
        )
        self.assertEqual(item.ref_data, {**fields, "individual_id": self.a.id})  # no personal data
        (event,) = item.events
        self.assertEqual((event.kind, event.user_id, event.detail), ("inkommen", self.owner.id, None))
        self.assertEqual(self.view()["kopanmalningar"], [{"id": item.id, **fields, "state": "ny"}])
        # the same rabbit again is the open notice, not a second one
        self.assertEqual(self.notify(when="2025-05-20").get_json()["id"], item.id)
        self.assertEqual(len(notices()), 1)
        # "utanfor" is the genebank's GX1, and the typed number is stored as Stamboken has it
        self.assertEqual(self.notify(number=f" {self.b.number} ", from_herd="utanfor").get_json()["from_herd"], "GX1")
        self.assertEqual(notices()[1].ref_data["number"], self.b.number)
        self.assertEqual(self.kop_anmalt(), 2)
        self.login("man")
        detail = self.client.get(f"/api/v2/inkorg/{item.id}").get_json()
        self.assertEqual(
            (detail["ref_type"], detail["ref_data"], detail["report_year"]), ("kopanmalan", item.ref_data, None)
        )

    def test_notice_refuses_a_bad_seller_or_date_and_a_rabbit_in_the_herd(self):
        self.login("owner")
        for body, field in (
            ({"from_herd": "G9001"}, "from_herd"),  # the buyer itself
            ({"from_herd": "G0000"}, "from_herd"),
            ({"from_herd": None}, "from_herd"),
            ({"when": "2024-12-31"}, "date"),
            ({"when": "2026-01-02"}, "date"),
            ({"when": None}, "date"),
        ):
            response = self.notify(**body)
            self.assertEqual((response.status_code, response.get_json()["field"]), (400, field), body)
        response = self.notify(number=self.own.number)
        self.assertEqual((response.status_code, response.get_json()["field"]), (409, "number"))
        self.assertEqual(notices(), [])

    def test_number_not_in_stamboken_points_to_certificate_form(self):
        self.login("owner")
        response = self.notify(number="G9001-99999")
        self.assertEqual(response.status_code, 422)
        body = response.get_json()
        self.assertEqual((body["code"], body["field"]), ("inte_i_stamboken", "number"))
        self.assertEqual(body["detail"], "Finns kaninen inte i Stamboken? Lägg till den från intyget.")
        db.Individual.update(voided=True).where(db.Individual.id == self.b.id).execute()  # an unpromoted slot
        self.assertEqual(self.notify(number=self.b.number).status_code, 422)
        self.assertEqual(notices(), [])

    def test_manager_closes_a_notice_by_hand_in_the_queue(self):
        """A notice whose purchase never comes (a typo, a rejected sale) is taken and closed as any item."""
        self.login("owner")
        item_id = self.notify().get_json()["id"]
        self.login("man")
        self.assertEqual(self.client.post(f"/api/v2/inkorg/{item_id}/ta", json={}).status_code, 200)
        response = self.client.post(f"/api/v2/inkorg/{item_id}/lage", json={"state": "klar"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(notices()[0].state, "klar")
        self.assertEqual(self.kop_anmalt(), 0)

    def test_code_session_may_report_purchase_only_for_its_herd(self):
        self.open_link(self.code)
        response = self.notify()
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        (item,) = notices()
        (event,) = item.events
        self.assertEqual((item.herd_id, event.user_id, event.detail), (self.h.id, None, {"via": "länk G9001/2025"}))
        # another herd, or another year, is not the link's: nothing is written
        self.assertEqual(self.notify(herd="G9002", number=self.own.number, from_herd="G9001").status_code, 404)
        self.assertEqual(self.notify(year=2024).status_code, 404)
        self.assertEqual(len(notices()), 1)
        # a revoked link writes nothing either (E4)
        db.ReportAccessCode.update(revoked_at=arsrapport.now()).where(db.ReportAccessCode.id == self.code.id).execute()
        self.assertEqual(self.notify(number=self.b.number).status_code, 403)
        self.assertEqual(len(notices()), 1)

    def test_notice_matches_seller_proposal_and_one_approval_settles_both(self):
        proposal = self.seller_proposes(5, 10)
        self.open_link(self.code)
        far = self.notify(number=self.b.number, when="2025-01-02").get_json()  # no proposal: the queue's item
        item = notices()[0]
        self.assertEqual(self.notify(when="2025-05-24").status_code, 200)  # 14 days after the sale
        notice = notices()[1]
        self.assertEqual(self.kop_anmalt(), 1)  # the matched one is shown with the sale instead
        self.login("man")
        (row,) = self.client.get("/api/v2/arsrapport/besattning/G9002/2025/forslag").get_json()["forslag"]
        self.assertEqual(row["kopanmalan"], purchase_notice.notice_json(notice))
        self.assertEqual(self.client.get(f"/api/v2/inkorg/{notice.id}").get_json()["report_year"], 2025)
        self.assertIsNone(self.client.get(f"/api/v2/inkorg/{item.id}").get_json()["report_year"])
        self.assertEqual(far["id"], item.id)

        passes, original = [], arsrapport._lock_items

        def spy(*args, **kwargs):  # the notice's item is locked in the one ascending pass, before the rabbit (K4)
            passes.append(original(*args, **kwargs))
            return passes[-1]

        with mock.patch.object(arsrapport, "_lock_items", side_effect=spy):
            response = self.client.post(f"/api/v2/arsrapport/forslag/{proposal.id}/godkann", json={})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(passes, [{proposal.inbox_item_id, notice.id}])
        notice = db.InboxItem.get_by_id(notice.id)
        self.assertEqual(notice.state, "klar")
        closing = notice.events.where(db.InboxEvent.kind == "lage").get()
        self.assertEqual((closing.user_id, closing.detail["note"]), (self.manager.id, "Köpet är registrerat"))
        self.assertEqual(db.InboxItem.get_by_id(item.id).state, "ny")

    def test_notice_fifteen_days_from_the_sale_is_not_matched(self):
        proposal = self.seller_proposes(5, 10)
        self.login("owner")
        self.notify(when="2025-05-25")
        self.login("man")
        (row,) = self.client.get("/api/v2/arsrapport/besattning/G9002/2025/forslag").get_json()["forslag"]
        self.assertIsNone(row["kopanmalan"])
        self.client.post(f"/api/v2/arsrapport/forslag/{proposal.id}/godkann", json={})
        # the transfer is registered after the notice all the same: the next look at the notice closes it
        self.assertEqual(notices()[0].state, "ny")
        self.assertEqual(self.client.get(f"/api/v2/inkorg/{notices()[0].id}").get_json()["state"], "klar")

    def test_notice_closes_when_transfer_registered(self):
        self.login("owner")
        self.notify()
        self.notify(number=self.b.number)
        first, second = notices()
        # registered by another path, the rabbit's own sale dialog
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=self.a, herd_tracking_date=date(2025, 5, 14))
        self.assertEqual(db.InboxItem.get_by_id(first.id).state, "ny")  # no trigger
        shown = {row["id"]: row["state"] for row in self.view()["kopanmalningar"]}
        self.assertEqual(shown, {first.id: "klar", second.id: "ny"})
        self.view()  # idempotent: one closing event
        events = list(db.InboxItem.get_by_id(first.id).events.where(db.InboxEvent.kind == "lage"))
        self.assertEqual(
            [(e.user_id, e.detail) for e in events],
            [(None, {"from": "ny", "to": "klar", "note": "Köpet är registrerat"})],
        )
        # the queue's item view closes too
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=self.b, herd_tracking_date=date(2025, 6, 1))
        self.login("man")
        self.assertEqual(self.client.get(f"/api/v2/inkorg/{second.id}").get_json()["state"], "klar")
        self.assertEqual(self.kop_anmalt(), 0)

    def test_an_earlier_stay_in_the_herd_does_not_close_the_notice(self):
        """The bought-back case: an old TRANSFER into the buyer herd is not this purchase."""
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=self.a, herd_tracking_date=date(2023, 3, 1))
        ht_row("TRANSFER", from_herd=self.h, herd=self.seller, individual=self.a, herd_tracking_date=date(2024, 3, 1))
        self.login("owner")
        self.assertEqual(self.notify().status_code, 200)
        self.assertEqual([row["state"] for row in self.view()["kopanmalningar"]], ["ny"])
        self.assertEqual(self.kop_anmalt(), 1)
        self.assertEqual(purchase_notice.registered(notices()), set())
        # this purchase, registered after the notice with another date
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=self.a, herd_tracking_date=date(2025, 4, 1))
        self.assertEqual(purchase_notice.registered(notices()), {notices()[0].id})
