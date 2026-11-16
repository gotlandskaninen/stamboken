#!/usr/bin/env python3
"""
Tests for the sale proposal service (step 4a, Task 1). Synthetic herds, rabbits and buyers only. The proposer is
the submission's user here; a link code is the other actor the submission can hold (step 3).

isort:skip_file
"""

from datetime import date, datetime, timezone
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.sale_proposal as sp
from utils.herd_tracking import HerdTrackingInvalid

from tests.arsrapport_fixtures import ArsrapportTest
from tests.ht_helpers import ht_row

SALE = date(2025, 10, 3)
LAST = date(2025, 12, 31)
BUYER = {"name": "Zelda Uniquebuyer", "town": "Visby"}
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
        stored = self.propose(self.other, buyer=BUYER)  # name and town alone are stored
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

    def test_approve_to_herd_in_genebank(self):
        proposal = self.propose(to_herd=self.g9002, buyer=None)
        row = sp.approve(proposal, self.manager, now=NOW)
        self.assertEqual((row.herd.herd, row.holder_contact), ("G9002", None))
        self.assertEqual(db.BuyerContact.select().count(), 0)

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
