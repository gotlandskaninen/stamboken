"""Regression tests for sales without a försäljningsbevis through reports, the inbox and the nightly purge."""

from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import utils.database as db
from utils import buyer_contact, buyer_mail, herd_tracking, inbox, mail, settings
from utils.herd_tracking import BEVIS_NOT_YET, BUYER_REMOVED, NOT_RECORDED, HerdTrackingInvalid, record_herd_tracking

from tests.arsrapport_fixtures import ArsrapportTest
from tests.inbox_fixtures import QUALITY
from tests.test_arsrapport_proposal_api import rows
from tests.test_buyer_contact import BUYER
from tests.test_buyer_notice_only import DAY, NOTICE, REAL_BEVIS_FROM, NoticeOnlyTest
from tests.test_inbox_grant import GrantTest


class TestReportReview(ArsrapportTest):
    report_path = "/besattning/G9001/2025"

    def setUp(self):
        super().setUp()
        self.at(date(2026, 1, 10))
        self.round(2025)
        self.herd = db.Herd.create(genebank=self.gotland, herd="G9001", is_active=True)
        self.gx1 = db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.main_member(self.herd)
        self.owner.add_role("owner", self.herd.id)
        (self.rabbit,) = self.rabbits(self.herd, 1)

    def sale_body(self, buyer, **fields):
        return self.body(self.sald(self.rabbit, "utanfor", 2025, 10, 3, kopare=buyer), **fields)

    def ok(self, response):
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def submit(self, body):
        return self.api("POST", f"{self.report_path}/skicka", **body)

    def withdraw(self):
        return self.ok(self.api("POST", f"{self.report_path}/dra-tillbaka", revision=1))

    def assert_buyer_refusal(self, response, message):
        self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
        self.assertEqual(
            response.get_json()["refusals"], [{"individual_id": self.rabbit.id, "code": "kopare", "message": message}]
        )

    def propose(self, buyer):
        caretaker = self.user("skotare")
        member = db.Member.create(
            first_name="Test", last_name="Skötare", membership=self.herd.membership, role="skotare", user=caretaker
        )
        db.HerdAccessGrant.create(member=member, herd=self.herd, granted_by=self.admin)
        self.login("skotare")
        self.ok(self.submit(self.sale_body(buyer)))
        self.login("man")
        (listed,) = self.ok(self.api("GET", f"{self.report_path}/forslag"))["forslag"]
        return db.SaleProposal.get_by_id(listed["id"])

    def approve_without_buyer(self, proposal):
        result = self.ok(self.api("POST", f"/forslag/{proposal.id}/godkann"))
        self.assertEqual(result["state"], "godkand")
        (sale,) = rows(self.rabbit, "TRANSFER")
        self.assertEqual((sale.herd_id, sale.holder_contact_id, sale.buyer_removed), (self.gx1.id, None, False))

    def test_resubmitting_as_not_recorded_leaves_the_kept_buyer_off_the_sale(self):
        self.login("owner")
        self.ok(self.submit(self.sale_body(NOTICE)))
        (old,) = rows(self.rabbit, "TRANSFER")
        draft = self.withdraw()["draft"]["data"]
        key = str(self.rabbit.id)
        kept_id = draft["rabbits"][key]["sald"]["kopare_id"]
        self.assertEqual(db.BuyerContact.get_by_id(kept_id).id, old.holder_contact_id)

        body = self.sale_body(NOT_RECORDED)
        body["rabbits"][key]["sald"]["kopare_id"] = kept_id
        self.ok(self.submit(body))
        (new,) = rows(self.rabbit, "TRANSFER")
        self.assertNotEqual(new.id, old.id)
        self.assertEqual((new.herd_id, new.holder_contact_id, new.buyer_removed), (self.gx1.id, None, False))

    @mock.patch.object(settings.mail, "link_secret", "synthetic-review-test")
    def test_erase_link_before_purge_keeps_the_other_sale_and_matching_proposal(self):
        proposal = self.propose(NOTICE)
        first, second = self.rabbits(self.herd, 2)
        linked, other = [
            record_herd_tracking(rabbit, self.gx1, DAY, "TRANSFER", self.manager, buyer=NOTICE)
            for rabbit in (first, second)
        ]
        self.assertEqual(linked.holder_contact.email, NOTICE["email"])
        self.assertEqual(proposal.buyer["email"], NOTICE["email"])
        token = mail.link_token(buyer_mail.ERASE_PURPOSE, linked.holder_contact_id)
        self.assertEqual(buyer_mail.erase_by_link(token), "removed")

        self.assertIsNone(db.BuyerContact.get_or_none(db.BuyerContact.id == linked.holder_contact_id))
        erased = db.HerdTracking.get_by_id(linked.id)
        self.assertEqual((erased.holder_contact_id, erased.buyer_removed), (None, True))
        kept = db.HerdTracking.get_by_id(other.id)
        self.assertEqual(
            (kept.holder_contact_id, kept.holder_contact.email), (other.holder_contact_id, NOTICE["email"])
        )
        pending = db.SaleProposal.get_by_id(proposal.id)
        self.assertEqual((pending.state, pending.buyer), ("foreslagen", proposal.buyer))

    def test_a_new_paper_sale_in_2025_refuses_the_old_buyer_format(self):
        item, (page,) = inbox.create_upload(
            self.owner, self.herd, None, [("inkorg/original/rapport.jpg", "0" * 64, QUALITY)]
        )
        page.doc_type = "arsblankett"
        page.save()
        inbox.take(item, self.manager, over=False)
        self.login("man")
        body = self.sale_body(BUYER, inbox_item_id=item.id, received_on="2026-01-10", health=None)
        with mock.patch.object(herd_tracking, "BEVIS_FROM", REAL_BEVIS_FROM):
            response = self.api("POST", f"{self.report_path}/skicka?post={item.id}", **body)
        self.assert_buyer_refusal(response, BEVIS_NOT_YET)
        self.assertEqual(rows(self.rabbit, "TRANSFER"), [])

    def test_resubmitting_a_bounced_buyer_refuses_to_register_them_again(self):
        self.login("owner")
        self.ok(self.submit(self.sale_body(NOTICE)))
        (sale,) = rows(self.rabbit, "TRANSFER")
        (notice,) = db.MailMessage.select().where(db.MailMessage.kind == "kopare.information")
        notice.status = "bounced"
        notice.save()
        self.assertEqual(buyer_contact.purge_undelivered_notice(notice.created_at), 1)
        self.assertTrue(db.HerdTracking.get_by_id(sale.id).buyer_removed)
        self.withdraw()

        self.assert_buyer_refusal(self.submit(self.sale_body(NOTICE)), BUYER_REMOVED)
        self.assertFalse(db.BuyerContact.select().exists())
        self.assertEqual(rows(self.rabbit, "TRANSFER"), [])

    def test_a_not_recorded_proposal_can_be_approved_after_thirteen_months(self):
        proposal = self.propose(NOT_RECORDED)
        now = proposal.created_at + timedelta(days=400)
        self.at(now)
        self.assertEqual(buyer_contact.purge_proposal_buyers(now), 0)
        pending = db.SaleProposal.get_by_id(proposal.id)
        self.assertEqual((pending.state, pending.buyer), ("foreslagen", NOT_RECORDED))
        self.approve_without_buyer(pending)

    def test_after_thirty_days_an_uninformed_proposal_and_an_unchecked_address_lose_the_buyer(self):
        proposal = self.propose(NOTICE)
        self.assertTrue(proposal.buyer["notice_only"])
        buyer_contact.run(proposal.created_at + timedelta(days=29))
        self.assertEqual(db.SaleProposal.get_by_id(proposal.id).buyer, proposal.buyer)
        now = proposal.created_at + timedelta(days=31)
        self.at(now)
        known, older, newer = self.rabbits(self.herd, 3)
        day = proposal.sale_date
        record_herd_tracking(
            known, self.gx1, day, "TRANSFER", self.manager, buyer={**NOTICE, "name": "Annan Testköpare"}
        )
        old, recent = [
            record_herd_tracking(rabbit, self.gx1, day, "TRANSFER", self.manager, buyer=NOTICE)
            for rabbit in (older, newer)
        ]
        for sale, age in ((old, 31), (recent, 29)):
            contact = sale.holder_contact
            self.assertTrue(contact.email_review_pending)
            contact.created_at = now - timedelta(days=age)
            contact.save(only=[db.BuyerContact.created_at])

        buyer_contact.run(now)

        pending = db.SaleProposal.get_by_id(proposal.id)
        self.assertEqual((pending.state, pending.buyer), ("foreslagen", NOT_RECORDED))
        self.approve_without_buyer(pending)
        self.assertIsNone(db.BuyerContact.get_or_none(db.BuyerContact.id == old.holder_contact_id))
        erased = db.HerdTracking.get_by_id(old.id)
        self.assertEqual((erased.holder_contact_id, erased.buyer_removed), (None, True))
        kept = db.HerdTracking.get_by_id(recent.id).holder_contact
        self.assertTrue(kept.email_review_pending)
        self.assertEqual(kept.email, NOTICE["email"])


class TestSaleReview(NoticeOnlyTest):
    def test_before_2027_only_a_replacement_outside_sale_accepts_the_old_format(self):
        event = {"kind": "TRANSFER", "date": DAY, "herd": "GX1", "buyer": BUYER}
        with mock.patch.object(herd_tracking, "BEVIS_FROM", REAL_BEVIS_FROM):
            with self.assertRaisesRegex(HerdTrackingInvalid, BEVIS_NOT_YET):
                herd_tracking.correct_herd_tracking(self.rabbit, self.manager, None, [], [event])

            sale = record_herd_tracking(self.rabbit, self.gx1, DAY, "TRANSFER", self.manager)
            (replacement,) = herd_tracking.correct_herd_tracking(
                self.rabbit, self.manager, None, [sale.id], [event], reason="Rättelse av försäljning"
            )
        self.assertIsNotNone(db.HerdTracking.get_by_id(sale.id).voided_at)
        self.assertEqual(replacement.holder_contact.name, BUYER["name"])

    def test_cancelled_notice_removes_the_buyer_only_when_the_sale_was_not_withdrawn(self):
        withdrawn = self.sale()
        stopped = record_herd_tracking(self.individuals[1], self.gx1, DAY, "TRANSFER", self.manager, buyer=NOTICE)
        self.notice_status("cancelled")
        for sale, reason in ((withdrawn, mail.SALE_WITHDRAWN), (stopped, "stoppat i statusvyn")):
            changed = (
                db.MailMessage.update(last_error=reason)
                .where(
                    db.MailMessage.kind == "kopare.information", db.MailMessage.recipient_id == sale.holder_contact_id
                )
                .execute()
            )
            self.assertEqual(changed, 1)

        self.purge()

        self.assertEqual(self.contact(withdrawn).email, NOTICE["email"])
        self.assertFalse(db.HerdTracking.get_by_id(withdrawn.id).buyer_removed)
        self.assertIsNone(self.contact(stopped))
        erased = db.HerdTracking.get_by_id(stopped.id)
        self.assertEqual((erased.holder_contact_id, erased.buyer_removed), (None, True))


class TestInboxReview(GrantTest):
    def test_a_proof_claiming_no_buyer_conflicts_with_the_registered_buyer_and_keeps_its_original(self):
        gx1 = db.Herd.create(genebank=self.genebanks[0], herd="GX1", is_active=True)
        rabbit = self.rabbit("G1-2111")
        sale = record_herd_tracking(rabbit, gx1, DAY, "TRANSFER", self.manager, buyer=NOTICE)
        item, proof = self.taken(self.helper)
        original = Path(self.stored(proof))
        original.parent.mkdir(parents=True)
        original.write_bytes(b"synthetic proof")
        self.login("hjalp")
        response = self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{proof.id}", json={"doc_type": "bevis"})
        self.assertEqual(response.status_code, 200, response.get_json())

        response = self.transfer(item, proof, individual=rabbit.number, herd="GX1", date=DAY, buyer=NOT_RECORDED)

        self.assertEqual(response.status_code, 409, response.get_json())
        self.assertIn("har redan en köpare", response.get_json()["detail"])
        kept = db.HerdTracking.get_by_id(sale.id)
        self.assertEqual((kept.holder_contact_id, kept.holder_contact.email), (sale.holder_contact_id, NOTICE["email"]))
        document = db.InboxDocument.get_by_id(proof.id)
        self.assertEqual((document.original_path, document.herd_tracking_id), (proof.original_path, None))
        self.assertEqual(original.read_bytes(), b"synthetic proof")
