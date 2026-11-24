#!/usr/bin/env python3
"""
Tests for the sale proposal service (step 4a, Task 1). Synthetic herds, rabbits and buyers only. The proposer is
the submission's user here; a link code is the other actor the submission can hold (step 3).

isort:skip_file
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import utils.arsrapport as arsrapport
import utils.buyer_contact as buyer_contact
import utils.buyer_mail as buyer_mail
import utils.database as db
import utils.mail as mail
import utils.report_code as report_code
import utils.sale_proposal as sp
import utils.settings as settings
from utils.herd_tracking import HerdTrackingConflict, HerdTrackingInvalid, record_herd_tracking

from tests.arsrapport_fixtures import ArsrapportTest
from tests.ht_helpers import ht_row
from tests.test_purchase_notice import until

SALE = date(2025, 10, 3)
LAST = date(2025, 12, 31)
BUYER = {"name": "Zelda Uniquebuyer", "town": "Visby", "postal_address": "Testgatan 1"}
NOW = datetime(2026, 1, 5, 11, 0, tzinfo=timezone.utc)


def rows(rabbit, kind):
    query = db.HerdTracking.select().where(
        db.HerdTracking.individual == rabbit, db.HerdTracking.kind == kind, db.ht_not_voided()
    )
    return list(query)


class ProposalTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        self.at(date(2026, 1, 5))
        self.round(2025)
        self.h = db.Herd.create(genebank=self.gotland, herd="G9001", herd_name="Testbesättning", is_active=True)
        self.g9002 = db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.rabbit, self.other = self.rabbits(self.h, 2)
        self.report = self.reported(self.h, self.ej_angiven(self.rabbit), self.ej_angiven(self.other))
        self.submission = arsrapport._submissions(self.report)[-1]
        self.manager = self.user("mgr", ("manager", self.gotland.id))

    def propose(self, rabbit=None, **fields):
        fields = {"to_herd": None, "buyer": BUYER, "sale_date": SALE} | fields
        return sp.propose(self.report, self.submission, rabbit or self.rabbit, **fields)

    def test_propose_creates_row_and_kontroll_item(self):
        proposal = self.propose()
        self.assertEqual(
            (proposal.state, proposal.sale_date, proposal.buyer["name"]), ("foreslagen", SALE, BUYER["name"])
        )
        item = db.InboxItem.get_by_id(proposal.inbox_item_id)
        self.assertEqual(
            (item.kind, item.state, item.ref_type, item.ref_id), ("kontroll", "ny", "sale_proposal", proposal.id)
        )
        self.assertEqual((item.herd_id, item.genebank_id), (self.h.id, self.gotland.id))
        self.assertEqual([p.id for p in sp.pending(self.report)], [proposal.id])
        with self.assertRaises(arsrapport.ArsrapportError) as ctx:  # one open proposal per rabbit and report
            self.propose()
        self.assertEqual(ctx.exception.status, 409)

    def test_buyer_contact_needs_tick(self):
        with self.assertRaises(HerdTrackingInvalid):
            self.propose(buyer={**BUYER, "email": "k@example.invalid"})
        self.assertEqual(db.SaleProposal.select().count(), 0)
        proposal = self.propose(buyer={**BUYER, "email": "k@example.invalid", "contact_consent": True})
        self.assertEqual(proposal.buyer["email"], "k@example.invalid")
        with self.assertRaisesRegex(HerdTrackingInvalid, "postadress"):
            self.propose(self.other, buyer={**BUYER, "postal_address": ""})
        stored = self.propose(self.other, buyer=BUYER)
        self.assertEqual(stored.buyer["postal_address"], BUYER["postal_address"])
        self.assertEqual((stored.buyer["name"], stored.buyer["email"]), (BUYER["name"], None))

    def test_approve_writes_transfer_and_buyer_contact(self):
        proposal = self.propose()
        row = sp.approve(proposal, self.manager, now=NOW)
        self.assertEqual((row.kind, row.herd_tracking_date, row.herd.herd), ("TRANSFER", SALE, "GX1"))
        contact = row.holder_contact
        self.assertEqual((contact.name, contact.town), (BUYER["name"], BUYER["town"]))
        self.assertEqual(contact.purge_at, db.BuyerContact.purge_at_for(SALE.isoformat()))
        proposal = db.SaleProposal.get_by_id(proposal.id)
        self.assertEqual(
            (proposal.state, proposal.decided_by_id, proposal.herd_tracking_id), ("godkand", self.manager.id, row.id)
        )
        self.assertIsNone(proposal.buyer)
        self.assertEqual(db.InboxItem.get_by_id(proposal.inbox_item_id).state, "klar")

    def test_approval_dates_contact_consent_from_submission_and_membership_from_sale(self):  # L2
        buyer = {**BUYER, "email": "k@example.invalid", "contact_consent": True, "membership_optin": True}
        proposal = self.propose(buyer=buyer)
        self.assertEqual(proposal.created_at, self.submission.created_at)
        row = sp.approve(proposal, self.manager, now=NOW + timedelta(days=3))
        contact = db.BuyerContact.get_by_id(row.holder_contact_id)
        sale_midnight = datetime.combine(SALE, datetime.min.time(), arsrapport.STOCKHOLM)
        self.assertEqual(contact.contact_consent_at, proposal.created_at)
        self.assertEqual(contact.membership_optin_at, sale_midnight)
        only_optin = self.propose(self.other, buyer={**BUYER, "phone": "070-1234567", "membership_optin": True})
        contact = sp.approve(only_optin, self.manager, now=NOW).holder_contact
        self.assertEqual((contact.contact_consent_at, contact.membership_optin_at), (None, sale_midnight))

    def test_approval_saves_the_sale_but_holds_mail_for_a_shared_address(self):
        buyer = {**BUYER, "email": "kopare@example.org", "contact_consent": True}
        sp.approve(self.propose(buyer=buyer), self.manager, now=NOW)
        proposal = self.propose(self.other, buyer={**buyer, "name": "Testköpare två"})
        sale = sp.approve(proposal, self.manager, now=NOW)
        self.assertTrue(sale.holder_contact.email_review_pending)
        self.assertFalse(
            db.MailMessage.select()
            .where(
                db.MailMessage.recipient_kind == "buyer_contact", db.MailMessage.recipient_id == sale.holder_contact_id
            )
            .exists()
        )
        self.assertEqual(db.Notice.get(db.Notice.kind == "kopare_adresskontroll").individual_id, self.other.id)

    def test_approve_to_herd_in_genebank(self):
        proposal = self.propose(to_herd=self.g9002, buyer=None)
        row = sp.approve(proposal, self.manager, now=NOW)
        self.assertEqual((row.herd.herd, row.holder_contact), ("G9002", None))
        self.assertEqual(db.BuyerContact.select().count(), 0)

    def test_erase_link_clears_the_same_buyer_on_a_pending_proposal(self):
        buyer = {**BUYER, "email": "kopare@example.org", "contact_consent": True}
        sale = sp.approve(self.propose(buyer=buyer), self.manager, now=NOW)
        pending = self.propose(self.other, buyer={**buyer, "email": buyer["email"].upper()})
        with mock.patch.object(settings.mail, "link_secret", "test-link-secret"):
            token = mail.link_token(buyer_mail.ERASE_PURPOSE, sale.holder_contact_id)
            self.assertEqual(buyer_mail.erase_by_link(token), "removed")
        with self.assertRaises(arsrapport.ArsrapportError) as refused:
            sp.approve(pending, self.manager, now=NOW)
        self.assertEqual((refused.exception.status, refused.exception.detail), (409, sp.BUYER_GONE))
        self.assertFalse(db.BuyerContact.select().exists())
        self.assertEqual(rows(self.other, "TRANSFER"), [])
        self.assertFalse(
            db.MailMessage.select()
            .where(db.MailMessage.recipient_kind == "buyer_contact", db.MailMessage.status == "queued")
            .exists()
        )

    def purged_contact_and_link(self, buyer):
        sale = sp.approve(self.propose(buyer=buyer), self.manager, now=NOW)
        db.BuyerContact.update(email=None, erased_email_hash=mail.address_hash(buyer["email"])).where(
            db.BuyerContact.id == sale.holder_contact_id
        ).execute()
        return mail.link_token(buyer_mail.ERASE_PURPOSE, sale.holder_contact_id)

    def test_older_link_clears_proposals_under_both_confirmed_names(self):
        first = {**BUYER, "name": "Testköpare A", "email": "delad@example.org", "contact_consent": True}
        second = {**first, "name": "Testköpare B"}
        with mock.patch.object(settings.mail, "link_secret", "test-link-secret"):
            token = self.purged_contact_and_link(first)
            sale = sp.approve(self.propose(self.other, buyer=second), self.manager, now=NOW)
            self.assertTrue(sale.holder_contact.email_review_pending)
            buyer_contact.review_buyer_email(sale.holder_contact_id, {"confirm": True}, self.manager)
            rabbits = self.rabbits(self.h, 3)
            proposals = [
                self.propose(rabbit, buyer=buyer)
                for rabbit, buyer in zip(rabbits, [first, second, {**first, "name": "Annan testköpare"}], strict=True)
            ]
            self.assertEqual(buyer_mail.erase_by_link(token), "removed")
        self.assertFalse(db.BuyerContact.select().exists())
        self.assertEqual([db.SaleProposal.get_by_id(p.id).buyer for p in proposals], [None, None, proposals[2].buyer])

    def report_form(self, buyer):
        (rabbit,) = self.rabbits(self.g9002, 1)
        member = self.main_member(self.g9002, "saljare@example.org")
        code = report_code.issue_code(self.g9002, self.report.round, member, now=arsrapport.now())
        opened = self.client.post("/api/v2/rapport/oppna", json={"token": mail.link_token("rapport", code.id)})
        self.assertEqual(opened.status_code, 200)
        body = self.body(self.sald(rabbit, "utanfor", 2025, 10, 3, kopare=buyer))
        return lambda: self.api("POST", "/besattning/G9002/2025/skicka", **body)

    def assert_address_waiter(self):
        waiting = """SELECT 1 FROM pg_locks WHERE NOT granted AND classid = %s
                     AND pg_backend_pid() = ANY(pg_blocking_pids(pid))"""
        self.assertTrue(until(lambda: db.DB_PROXY.execute_sql(waiting, (buyer_mail.BUYER_ADDRESS_LOCK,)).fetchone()))

    def assert_proposal_receipt(self, response):
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        receipt = response.get_json()
        self.assertEqual(receipt["summary"], {"salda": 1, "vantar": 1, "kvar": 0, "doda": 0, "ej_angivna": 0})
        return db.SaleProposal.get(db.SaleProposal.submission == receipt["submission_id"])

    def test_erasure_waits_for_an_uncommitted_report_and_rechecks(self):
        buyer = {**BUYER, "email": "test@example.org", "contact_consent": True}
        with mock.patch.object(settings.mail, "link_secret", "test-link-secret"), ThreadPoolExecutor(1) as worker:
            token = self.purged_contact_and_link(buyer)
            submit = self.report_form(buyer)

            def erase():
                with db.DB_PROXY.connection_context():
                    return buyer_mail.erase_by_link(token)

            erasure = None
            propose = arsrapport._propose

            def erase_before_commit(*args):
                nonlocal erasure
                propose(*args)
                erasure = worker.submit(erase)
                self.assert_address_waiter()

            with mock.patch.object(arsrapport, "_propose", erase_before_commit):
                pending = self.assert_proposal_receipt(submit())
            with self.assertRaises(HerdTrackingConflict):
                erasure.result(timeout=10)
            self.assertIsNotNone(pending.buyer)
            self.assertEqual(erase(), "removed")
            self.assertIsNone(db.SaleProposal.get_by_id(pending.id).buyer)

    def test_report_waits_for_an_erasure_and_returns_the_usual_receipt(self):
        buyer = {**BUYER, "email": "test@example.org", "contact_consent": True}
        with mock.patch.object(settings.mail, "link_secret", "test-link-secret"), ThreadPoolExecutor(1) as worker:
            token = self.purged_contact_and_link(buyer)
            submit = self.report_form(buyer)
            with db.DB_PROXY.atomic():
                self.assertEqual(buyer_mail.erase_by_link(token), "removed")
                response = worker.submit(submit)
                self.assert_address_waiter()
            self.assertIsNone(self.assert_proposal_receipt(response.result(timeout=10)).buyer)

    def test_report_waits_for_a_direct_sale_and_keeps_the_proposed_buyer(self):
        buyer = {**BUYER, "email": "test@example.org", "contact_consent": True}
        with mock.patch.object(settings.mail, "link_secret", "test-link-secret"), ThreadPoolExecutor(1) as worker:
            submit = self.report_form(buyer)
            with db.DB_PROXY.atomic():
                record_herd_tracking(self.rabbit, "GX1", SALE, "TRANSFER", self.manager, buyer=buyer)
                response = worker.submit(submit)
                self.assert_address_waiter()
            self.assertEqual(self.assert_proposal_receipt(response.result(timeout=10)).buyer["email"], buyer["email"])

    def test_report_lock_timeout_is_generic_and_the_same_submission_can_be_retried(self):
        buyer = {**BUYER, "email": "test@example.org", "contact_consent": True}
        with mock.patch.object(settings.mail, "link_secret", "test-link-secret"), ThreadPoolExecutor(1) as worker:
            submit = self.report_form(buyer)
            with db.DB_PROXY.atomic(), mock.patch.object(arsrapport, "SALE_LOCK_TIMEOUT", "200ms"):
                buyer_mail.lock_buyer_addresses([buyer["email"]])
                response = worker.submit(submit).result(timeout=10)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json()["detail"], "Rapporten kunde inte sparas just nu. Försök igen.")
            self.assertFalse(db.SaleProposal.select().exists())
            self.assertEqual(self.assert_proposal_receipt(submit()).buyer["email"], buyer["email"])

    def test_retract_is_idempotent_and_clears_buyer(self):
        proposal = self.propose()
        sp.retract(proposal, now=NOW)
        sp.retract(proposal, now=NOW)
        proposal = db.SaleProposal.get_by_id(proposal.id)
        self.assertEqual((proposal.state, proposal.buyer), ("atertagen", None))
        self.assertEqual(db.InboxItem.get_by_id(proposal.inbox_item_id).state, "skrap")
        self.assertEqual(sp.pending(self.report), [])
        decided = self.propose(self.other)
        sp.approve(decided, self.manager, now=NOW)
        sp.retract(decided, now=NOW)  # a decided proposal stays
        self.assertEqual(db.SaleProposal.get_by_id(decided.id).state, "godkand")

    def test_reject_kvar_attests_31_december(self):
        proposal = self.propose()
        sp.reject(proposal, self.manager, reason="Datumet stämmer inte", then="kvar", now=NOW)
        proposal = db.SaleProposal.get_by_id(proposal.id)
        self.assertEqual((proposal.state, proposal.reason, proposal.buyer), ("avvisad", "Datumet stämmer inte", None))
        (attest,) = rows(self.rabbit, "ATTESTATION")
        self.assertEqual((attest.herd_tracking_date, attest.herd_id), (LAST, self.h.id))
        self.assertEqual(rows(self.rabbit, "TRANSFER"), [])
        self.assertEqual(db.InboxItem.get_by_id(proposal.inbox_item_id).state, "klar")

    def test_reject_valj_igen_leaves_rabbit_unchosen(self):
        proposal = self.propose()
        sp.reject(proposal, self.manager, reason="Fel köpare", then="valj_igen", now=NOW)
        self.assertEqual(db.SaleProposal.get_by_id(proposal.id).state, "avvisad")
        self.assertEqual(rows(self.rabbit, "ATTESTATION"), [])
        self.assertEqual(rows(self.rabbit, "TRANSFER"), [])

    def test_reject_kvar_refused_leaves_proposal_open(self):
        proposal = self.propose()
        ht_row(  # the rabbit moved meanwhile: the register refuses the attestation
            kind="TRANSFER",
            individual=self.rabbit,
            herd=self.g9002,
            from_herd=self.h,
            herd_tracking_date=date(2025, 11, 1),
        )
        with self.assertRaises(arsrapport.ArsrapportError) as ctx:
            sp.reject(proposal, self.manager, reason="Fel datum", then="kvar", now=NOW)
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(db.SaleProposal.get_by_id(proposal.id).state, "foreslagen")

    def test_second_decision_gets_409(self):
        proposal = self.propose()
        sp.approve(proposal, self.manager, now=NOW)
        for decide in (
            lambda: sp.approve(proposal, self.manager, now=NOW),
            lambda: sp.reject(proposal, self.manager, reason="För sent", then="kvar", now=NOW),
        ):
            with self.assertRaises(arsrapport.ArsrapportError) as ctx:
                decide()
            self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(len(rows(self.rabbit, "TRANSFER")), 1)

    def test_reason_with_buyer_name_refused(self):
        proposal = self.propose()
        with self.assertRaises(arsrapport.ArsrapportError) as ctx:
            sp.reject(proposal, self.manager, reason="Zelda köpte den inte", then="kvar", now=NOW)
        self.assertEqual((ctx.exception.status, ctx.exception.detail), (400, sp.NAMED))
        self.assertEqual(db.SaleProposal.get_by_id(proposal.id).state, "foreslagen")

    def test_approve_refused_when_rabbit_moved_before_sale_date(self):
        proposal = self.propose()
        ht_row(
            "TRANSFER", individual=self.rabbit, herd=self.g9002, from_herd=self.h, herd_tracking_date=date(2025, 10, 1)
        )
        with self.assertRaises(arsrapport.ArsrapportError) as ctx:
            sp.approve(proposal, self.manager, now=NOW)
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(db.SaleProposal.get_by_id(proposal.id).state, "foreslagen")
        self.assertEqual(len(rows(self.rabbit, "TRANSFER")), 1)

    def test_reject_kvar_locks_the_rabbit_when_already_attested(self):
        proposal = self.propose()
        ht_row("ATTESTATION", individual=self.rabbit, herd=self.h, herd_tracking_date=LAST)
        with mock.patch.object(sp, "lock_individual_for_edit") as lock:
            sp.reject(proposal, self.manager, reason="Fel datum", then="kvar", now=NOW)
        lock.assert_called_with(self.rabbit.id)

    def test_decisions_work_when_the_item_is_gone(self):
        gone, other = self.propose(), self.propose(self.other)
        db.InboxItem.delete().execute()
        sp.retract(gone, now=NOW)
        retracted = db.SaleProposal.get_by_id(gone.id)
        self.assertEqual((retracted.state, retracted.buyer), ("atertagen", None))
        sp.approve(other, self.manager, now=NOW)
        self.assertEqual(db.SaleProposal.get_by_id(other.id).state, "godkand")

    # M2: a pending proposal's buyer goes after 13 months, 30 days after a recorded death, or on request

    def logged(self):
        rows = db.AuditLog.select().where(db.AuditLog.table_name == "sale_proposal").order_by(db.AuditLog.id)
        return [(row.record_id, row.operation, row.new_data, row.changed_fields, row.changed_by) for row in rows]

    def test_a_pending_buyer_goes_thirteen_months_after_the_proposal(self):
        old, recent = self.propose(), self.propose(self.other)
        db.SaleProposal.update(created_at=NOW).execute()
        night = NOW + timedelta(days=396)
        self.assertEqual(buyer_contact.purge_proposal_buyers(night), 0)  # 13 months to the hour: not yet
        db.SaleProposal.update(created_at=NOW - timedelta(hours=1)).where(db.SaleProposal.id == old.id).execute()
        self.assertEqual(buyer_contact.purge_proposal_buyers(night), 1)
        self.assertEqual([db.SaleProposal.get_by_id(p.id).buyer for p in (old, recent)], [None, recent.buyer])
        self.assertEqual(self.logged(), [(str(old.id), "UPDATE", {"action": "gallring_forslag"}, ["buyer"], None)])
        self.assertEqual(db.SaleProposal.get_by_id(old.id).state, "foreslagen")
        with self.assertRaises(arsrapport.ArsrapportError) as ctx:  # a sale outside the genebank needs its buyer
            sp.approve(old, self.manager, now=NOW)
        self.assertEqual((ctx.exception.status, ctx.exception.detail), (409, sp.BUYER_GONE))
        self.assertEqual(rows(self.rabbit, "TRANSFER"), [])
        sp.reject(old, self.manager, reason="Köparen är gallrad", then="valj_igen", now=NOW)  # the way out
        self.assertEqual(db.SaleProposal.get_by_id(old.id).state, "avvisad")

    def test_a_pending_buyer_goes_30_days_after_the_death_is_recorded(self):
        dead, alive = self.propose(), self.propose(self.other)
        db.Individual.update(death_date=date(2025, 11, 1)).where(db.Individual.id == self.rabbit.id).execute()
        recorded = db.AuditLog.get(
            db.AuditLog.table_name == "individual",
            db.AuditLog.record_id == str(self.rabbit.id),
            db.AuditLog.operation == "UPDATE",
            db.AuditLog.changed_fields.contains("death_date"),
        ).changed_at
        db.SaleProposal.update(created_at=recorded).execute()  # neither proposal expires during the grace period
        self.assertEqual(buyer_contact.purge_proposal_buyers(recorded), 0)
        self.assertEqual(db.SaleProposal.get_by_id(dead.id).buyer, dead.buyer)
        settled = recorded + timedelta(days=30)
        self.assertEqual(buyer_contact.purge_proposal_buyers(settled - timedelta(seconds=1)), 0)
        with mock.patch.object(sp, "_locked", wraps=sp._locked) as locked:  # pylint: disable=protected-access
            self.assertEqual(buyer_contact.purge_proposal_buyers(settled), 1)
        locked.assert_called_once()  # under the decision's locks
        self.assertEqual([db.SaleProposal.get_by_id(p.id).buyer for p in (dead, alive)], [None, alive.buyer])
        self.assertEqual(buyer_contact.purge_proposal_buyers(settled), 0)
