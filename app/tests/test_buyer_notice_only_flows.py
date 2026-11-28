"""Sales without a försäljningsbevis through address review, yearly reports, proposals and erasure (#273)."""

import re
from datetime import date, datetime, timezone
from unittest import mock

import utils.database as db
from utils import buyer_contact, buyer_mail, herd_tracking
from utils.herd_tracking import NOT_RECORDED, REPORT_BEVIS_NOT_YET, record_herd_tracking

from tests.arsrapport_fixtures import ArsrapportTest
from tests.test_arsrapport_proposal_api import rows
from tests.test_buyer_contact import BUYER
from tests.test_buyer_notice_only import DAY, NOTICE, REAL_REPORT_BEVIS_FROM, NoticeOnlyTest


class TestNoticeOnlyMailFlows(NoticeOnlyTest):
    def sell_other_rabbit(self, buyer):
        return record_herd_tracking(self.individuals[1], self.gx1, DAY, "TRANSFER", self.manager, buyer=buyer)

    def test_address_review_keeps_notice_only_and_queues_the_notice(self):
        self.sell_other_rabbit({**NOTICE, "name": "Annan testköpare"})
        sale = self.sale()
        contact = self.contact(sale)
        self.assertTrue(contact.email_review_pending)

        def buyer_mails():
            return [
                (m.kind, m.status)
                for m in self.mails()
                if m.recipient_kind == "buyer_contact" and m.recipient_id == sale.holder_contact_id
            ]

        self.assertEqual(buyer_mails(), [])
        self._login("man")
        corrected = "rattad@example.org"
        response = self.client.post(
            f"/api/v2/buyer-contacts/{contact.id}/review-email", json={"name": NOTICE["name"], "email": corrected}
        )
        self.assertEqual(response.status_code, 204, response.get_data(as_text=True))
        contact = self.contact(sale)
        self.assertFalse(contact.email_review_pending)
        self.assertTrue(contact.email_notice_only)
        self.assertEqual((contact.email, contact.postal_address), (corrected, NOTICE["postal_address"]))
        self.assertEqual(buyer_mails(), [("kopare.information", "queued")])

    def test_erase_link_after_email_purge_only_removes_its_own_buyer(self):
        sale = self.sale()
        (notice,) = self.send()
        body = notice.get_body(("plain",)).get_content()
        (token,) = re.findall(r"/kopare/ta-bort#(\S+)", body)
        other = self.sell_other_rabbit(NOTICE)  # same buyer and e-mail, this notice still waits
        buyer_contact.purge_notice_email(datetime.now(timezone.utc))
        self.assertIsNone(self.contact(sale).email)
        self.assertEqual(self.contact(other).email, NOTICE["email"])

        self.assertEqual(buyer_mail.erase_by_link(token), "removed")
        self.assertIsNone(self.contact(sale))
        self.assertEqual(buyer_mail.erase_by_link(token), "already_removed")
        self.assertEqual(self.contact(other).email, NOTICE["email"])


class TestNoticeOnlyReportFlows(ArsrapportTest):
    report_path = "/besattning/G9001/2025"

    def setUp(self):
        super().setUp()
        self.at(date(2026, 1, 10))
        self.round(2025)
        self.herd = db.Herd.create(genebank=self.gotland, herd="G9001", is_active=True)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.main_member(self.herd)
        self.first, self.second = self.rabbits(self.herd, 2)

    def submit_sales(self, first_buyer, second_buyer):
        body = self.body(
            self.sald(self.first, "utanfor", 2025, 10, 3, kopare=first_buyer),
            self.sald(self.second, "utanfor", 2025, 10, 3, kopare=second_buyer),
        )
        return self.api("POST", f"{self.report_path}/skicka", **body)

    def test_report_accepts_both_modes_and_refuses_a_2025_sale_in_the_old_format(self):
        self.owner.add_role("owner", self.herd.id)
        self.login("owner")
        with mock.patch.object(herd_tracking, "REPORT_BEVIS_FROM", REAL_REPORT_BEVIS_FROM):
            refused = self.submit_sales(BUYER, NOT_RECORDED)
            self.assertEqual(refused.status_code, 422, refused.get_data(as_text=True))
            self.assertEqual(
                refused.get_json()["refusals"],
                [{"individual_id": self.first.id, "code": "kopare", "message": REPORT_BEVIS_NOT_YET}],
            )
            sent = self.submit_sales(NOTICE, NOT_RECORDED)
            self.assertEqual(sent.status_code, 200, sent.get_data(as_text=True))

        (with_buyer,) = rows(self.first, "TRANSFER")
        (without_buyer,) = rows(self.second, "TRANSFER")
        self.assertEqual((with_buyer.herd.herd, without_buyer.herd.herd), ("GX1", "GX1"))
        self.assertTrue(with_buyer.holder_contact.email_notice_only)
        self.assertEqual(with_buyer.holder_contact.email, NOTICE["email"])
        self.assertIsNone(without_buyer.holder_contact_id)
        self.assertFalse(without_buyer.buyer_removed)
        self.assertEqual(db.BuyerContact.select().count(), 1)

    def test_not_recorded_proposals_can_be_listed_approved_and_rejected(self):
        self.link_submit(
            self.herd,
            self.body(
                self.sald(self.first, "utanfor", 2025, 10, 3, kopare=NOT_RECORDED),
                self.sald(self.second, "utanfor", 2025, 10, 3, kopare=NOT_RECORDED),
            ),
        )

        self.login("man")
        listed = self.api("GET", f"{self.report_path}/forslag")
        self.assertEqual(listed.status_code, 200, listed.get_data(as_text=True))
        proposals = {p["individual_id"]: p for p in listed.get_json()["forslag"]}
        self.assertEqual(set(proposals), {self.first.id, self.second.id})
        for proposal in proposals.values():
            self.assertIsNone(proposal["buyer"])
            self.assertIs(proposal["buyer_not_recorded"], True)

        self.assertEqual(rows(self.first, "TRANSFER"), [])
        approved_id = proposals[self.first.id]["id"]
        approved = self.api("POST", f"/forslag/{approved_id}/godkann")
        self.assertEqual(approved.status_code, 200, approved.get_data(as_text=True))
        (sale,) = rows(self.first, "TRANSFER")
        self.assertEqual((sale.herd.herd, sale.holder_contact_id), ("GX1", None))
        rejected_id = proposals[self.second.id]["id"]
        rejected = self.api("POST", f"/forslag/{rejected_id}/avvisa", reason="Fel datum", then="valj_igen")
        self.assertEqual(rejected.status_code, 200, rejected.get_data(as_text=True))
        self.assertEqual(db.SaleProposal.get_by_id(rejected_id).state, "avvisad")
        self.assertEqual(rows(self.second, "TRANSFER"), [])
        self.assertFalse(db.BuyerContact.select().exists())
