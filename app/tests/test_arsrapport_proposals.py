#!/usr/bin/env python3
"""
Tests for sales that become proposals in the yearly report (step 4a, Task 2): Skicka, Ändra and Dra tillbaka by a
caretaker or through the link, and the owner's direct sale beside them. Synthetic herds, rabbits and buyers only.

isort:skip_file
"""

import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.inbox as inbox
import utils.report_code as report_code
import utils.sale_proposal as sp
import utils.settings as settings
from herdbook import APP
from utils.arsrapport import ArsrapportError
from utils.report_code import CodeActor

from tests.arsrapport_fixtures import ArsrapportTest
from tests.database_test import _USE_POSTGRES

DAY0 = date(2026, 1, 10)
LAST = date(2025, 12, 31)
BUYER = {"name": "Zelda Uniquebuyer", "town": "Visby"}
OTHER_BUYER = {"name": "Ylva Otherbuyer", "town": "Slite"}
NOW = datetime(2026, 1, 12, 11, 0, tzinfo=timezone.utc)


def rows(rabbit, kind, active=True):
    query = db.HerdTracking.select().where(db.HerdTracking.individual == rabbit.id, db.HerdTracking.kind == kind)
    return list((query.where(db.ht_not_voided()) if active else query).order_by(db.HerdTracking.id))


def proposals(rabbit):
    query = db.SaleProposal.select().where(db.SaleProposal.individual == rabbit.id)
    return list(query.order_by(db.SaleProposal.id))


class ProposalsTest(ArsrapportTest):
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
        self.owner.add_role("owner", self.h.id)
        self.member = self.main_member(self.h, "g9001@example.invalid")
        self.code = report_code.issue_code(self.h, self.round_, self.member, now=arsrapport.now())
        self.a, self.b, self.c = self.rabbits(self.h, 3)
        self.decider = db.User.get_by_id(self.manager.id)

    def day(self, n):
        self.at(DAY0 + timedelta(days=n))

    def actor(self, who):
        """(access, actor) of the link, the caretaker (an account with a herd-access grant) or the owner."""
        if who == "code":
            return arsrapport.code_access(self.h, self.round_, [self.code.id]), CodeActor(self.code)
        if who == "caretaker" and not hasattr(self, "caretaker"):
            self.caretaker = self.user("skotare")
            person = db.Member.create(
                first_name="Test",
                last_name="Skötare",
                membership=self.h.membership,
                role="skotare",
                user=self.caretaker,
            )
            db.HerdAccessGrant.create(member=person, herd=self.h, granted_by=self.admin)
        user = db.User.get_by_id(self.caretaker.id if who == "caretaker" else self.owner.id)
        access = arsrapport.report_access(user, self.h)
        self.assertEqual(access.role, who)
        return access, user

    def send(self, *entries, who="code", revision=None, body=None):
        access, actor = self.actor(who)
        sub = arsrapport.parse_submission(body or self.body(*entries, revision=revision), paper=False)
        return arsrapport.submit(self.h, self.round_, access, actor, sub)

    def withdraw(self, revision, who="code"):
        access, actor = self.actor(who)
        return arsrapport.withdraw(self.h, self.round_, access, actor, revision=revision)

    def report(self):
        return db.YearlyHerdReport.get(db.YearlyHerdReport.herd == self.h.id, db.YearlyHerdReport.status == "submitted")

    def refused(self, call):
        with self.assertRaises(ArsrapportError) as caught:
            call()
        self.assertEqual(caught.exception.status, 422)
        return [(r["individual_id"], r["code"]) for r in caught.exception.extra["refusals"]]

    def test_caretaker_sale_becomes_proposal(self):
        receipt = self.send(
            self.sald(self.a, "G9002", 2025, 10, 3),
            self.kvar(self.b, vikt=2.8),
            self.kvar(self.c, vikt=2.8),
            who="caretaker",
        )
        self.assertEqual((rows(self.a, "TRANSFER"), rows(self.a, "ATTESTATION")), ([], []))  # F2, fråga 28
        self.assertEqual(len(rows(self.b, "ATTESTATION")), 1)
        (proposal,) = proposals(self.a)
        self.assertEqual(
            (proposal.state, proposal.to_herd_id, proposal.sale_date, proposal.buyer),
            ("foreslagen", self.g9002.id, date(2025, 10, 3), None),
        )
        item = db.InboxItem.get_by_id(proposal.inbox_item_id)
        self.assertEqual(
            (item.kind, item.ref_type, item.ref_id, item.state), ("kontroll", "sale_proposal", proposal.id, "ny")
        )
        submission = db.YearlyReportSubmission.get()
        self.assertEqual(proposal.submission_id, submission.id)
        self.assertEqual(submission.data["rabbits"][str(self.a.id)]["sald"]["forslag"], proposal.id)
        self.assertEqual(receipt["summary"]["salda"], 1)
        access, user = self.actor("caretaker")
        view = arsrapport.report_view(self.h, self.round_, access, user)
        self.assertEqual(
            view["forslag"],
            [{"individual_id": self.a.id, "to_herd": "G9002", "sale_date": "2025-10-03", "state": "foreslagen"}],
        )

    def test_sale_after_new_year_is_kvar_plus_proposal(self):
        self.send(
            self.sald(self.a, "utanfor", 2026, 1, 5, kopare=BUYER),
            self.kvar(self.b, vikt=2.8),
            self.kvar(self.c, vikt=2.8),
        )
        (attest,) = rows(self.a, "ATTESTATION")
        self.assertEqual((attest.herd_tracking_date, attest.herd_id), (LAST, self.h.id))
        self.assertEqual(rows(self.a, "TRANSFER"), [])
        (proposal,) = proposals(self.a)
        self.assertEqual(
            (proposal.state, proposal.to_herd_id, proposal.sale_date, proposal.buyer["name"]),
            ("foreslagen", None, date(2026, 1, 5), BUYER["name"]),
        )
        self.assertEqual(db.BuyerContact.select().count(), 0)  # the buyer waits in the proposal

    def first(self):
        """The link's first report: a sold in October to G9002, b and c kvar."""
        self.send(self.sald(self.a, "G9002", 2025, 10, 3), self.kvar(self.b, vikt=2.8), self.kvar(self.c, vikt=2.8))
        return proposals(self.a)[0]

    def test_change_removing_sale_retracts_proposal(self):
        first = self.first()
        self.day(1)
        self.send(self.kvar(self.a, vikt=2.8), self.kvar(self.b, vikt=2.8), self.kvar(self.c, vikt=2.8), revision=1)
        first = db.SaleProposal.get_by_id(first.id)
        self.assertEqual((first.state, db.InboxItem.get_by_id(first.inbox_item_id).state), ("atertagen", "skrap"))
        self.assertEqual(len(rows(self.a, "ATTESTATION")), 1)
        self.assertEqual(db.SaleProposal.select().count(), 1)

    def test_change_moving_sale_date_replaces_proposal(self):  # Review Focus 3
        first = self.first()
        self.day(1)
        self.send(
            self.sald(self.a, "G9002", 2025, 11, 5),
            self.kvar(self.b, vikt=2.8),
            self.kvar(self.c, vikt=2.8),
            revision=1,
        )
        old, new = proposals(self.a)
        self.assertEqual(
            (old.id, old.state, new.state, new.sale_date), (first.id, "atertagen", "foreslagen", date(2025, 11, 5))
        )
        self.assertEqual(db.InboxItem.get_by_id(old.inbox_item_id).state, "skrap")
        self.assertEqual(db.InboxItem.get_by_id(new.inbox_item_id).state, "ny")
        latest = db.YearlyReportSubmission.select().order_by(db.YearlyReportSubmission.id.desc()).first()
        self.assertEqual(
            (new.submission_id, latest.data["rabbits"][str(self.a.id)]["sald"]["forslag"]), (latest.id, new.id)
        )
        self.day(2)  # Ändra of another rabbit leaves the proposal as it is, and the data still names it
        self.send(
            self.sald(self.a, "G9002", 2025, 11, 5),
            self.kvar(self.b, vikt=3.0),
            self.kvar(self.c, vikt=2.8),
            revision=2,
        )
        self.assertEqual([p.state for p in proposals(self.a)], ["atertagen", "foreslagen"])
        latest = db.YearlyReportSubmission.select().order_by(db.YearlyReportSubmission.id.desc()).first()
        self.assertEqual(latest.data["rabbits"][str(self.a.id)]["sald"]["forslag"], new.id)

    def test_change_buyer_only_replaces_proposal(self):  # K5
        self.send(
            self.sald(self.a, "utanfor", 2025, 10, 3, kopare=BUYER),
            self.kvar(self.b, vikt=2.8),
            self.kvar(self.c, vikt=2.8),
        )
        self.day(1)  # the same sale without a buyer typed keeps the proposal
        self.send(
            self.sald(self.a, "utanfor", 2025, 10, 3),
            self.kvar(self.b, vikt=3.0),
            self.kvar(self.c, vikt=2.8),
            revision=1,
        )
        self.assertEqual([p.state for p in proposals(self.a)], ["foreslagen"])
        self.send(
            self.sald(self.a, "utanfor", 2025, 10, 3, kopare=OTHER_BUYER),
            self.kvar(self.b, vikt=3.0),
            self.kvar(self.c, vikt=2.8),
            revision=2,
        )
        old, new = proposals(self.a)
        self.assertEqual((old.state, old.buyer), ("atertagen", None))
        self.assertEqual(
            (new.state, new.buyer["name"], new.sale_date), ("foreslagen", OTHER_BUYER["name"], date(2025, 10, 3))
        )

    def test_kvar_then_sale_before_new_year_removes_attestation(self):  # K5
        self.send(self.kvar(self.a, vikt=2.8), self.kvar(self.b, vikt=2.8), self.kvar(self.c, vikt=2.8))
        (attest,) = rows(self.a, "ATTESTATION")
        self.day(1)
        self.send(
            self.sald(self.a, "G9002", 2025, 12, 10),
            self.kvar(self.b, vikt=2.8),
            self.kvar(self.c, vikt=2.8),
            revision=1,
        )
        self.assertIsNotNone(db.HerdTracking.get_by_id(attest.id).voided_at)
        self.assertEqual((rows(self.a, "ATTESTATION"), rows(self.a, "TRANSFER")), ([], []))
        self.assertEqual([(p.state, p.sale_date) for p in proposals(self.a)], [("foreslagen", date(2025, 12, 10))])

    def test_withdraw_retracts_pending_keeps_approved(self):
        self.send(
            self.sald(self.a, "G9002", 2025, 10, 3),
            self.sald(self.b, "utanfor", 2025, 11, 20, kopare=BUYER),
            self.kvar(self.c, vikt=2.8),
        )
        (approved,), (pending,) = proposals(self.a), proposals(self.b)
        sale = sp.approve(approved, self.decider, now=NOW)
        self.day(1)
        self.withdraw(1)
        approved, pending = db.SaleProposal.get_by_id(approved.id), db.SaleProposal.get_by_id(pending.id)
        self.assertEqual((approved.state, pending.state, pending.buyer), ("godkand", "atertagen", None))
        self.assertIsNone(db.HerdTracking.get_by_id(sale.id).voided_at)
        self.assertEqual(rows(self.c, "ATTESTATION"), [])
        self.assertEqual(db.YearlyHerdReport.get(db.YearlyHerdReport.herd == self.h.id).status, "voided")

    def test_owner_still_sells_directly(self):
        self.send(
            self.sald(self.a, "G9002", 2025, 10, 3),
            self.kvar(self.b, vikt=2.8),
            self.kvar(self.c, vikt=2.8),
            who="owner",
        )
        (sale,) = rows(self.a, "TRANSFER")
        self.assertEqual((sale.herd_id, sale.herd_tracking_date), (self.g9002.id, date(2025, 10, 3)))
        self.assertEqual(db.SaleProposal.select().count(), 0)
        self.assertNotIn("forslag", db.YearlyReportSubmission.get().data["rabbits"][str(self.a.id)]["sald"])

    def test_withdraw_after_approved_january_sale(self):  # K3, fråga 15 b, acceptance case 6
        self.send(self.sald(self.a, "G9002", 2026, 1, 10), self.kvar(self.b, vikt=2.8), self.kvar(self.c, vikt=2.8))
        (attest,) = rows(self.a, "ATTESTATION")
        sale = sp.approve(proposals(self.a)[0], self.decider, now=NOW)
        self.assertEqual(sale.herd_tracking_date, date(2026, 1, 10))
        self.day(1)
        self.withdraw(1)
        self.assertIsNotNone(db.HerdTracking.get_by_id(attest.id).voided_at)
        self.assertIsNone(db.HerdTracking.get_by_id(sale.id).voided_at)
        self.assertEqual(db.SaleProposal.get_by_id(proposals(self.a)[0].id).state, "godkand")

    def test_skicka_approve_withdraw_skicka(self):  # FB1
        sale = sp.approve(self.first(), self.decider, now=NOW)
        self.day(1)
        self.withdraw(1)
        draft = db.YearlyReportDraft.get()
        self.assertEqual(sorted(draft.data["rabbits"]), sorted([str(self.b.id), str(self.c.id)]))
        self.day(2)  # the second Skicka is the restored draft as it is
        self.send(body={**draft.data, "submission_key": str(uuid.uuid4()), "revision": None})
        self.assertEqual(self.report().status, "submitted")
        self.assertIsNone(db.HerdTracking.get_by_id(sale.id).voided_at)

    def test_resend_after_rejection_is_a_new_proposal(self):  # FB3, the Task 2 part
        first = self.first()
        sp.reject(first, self.decider, reason="Fel köpare", then="valj_igen", now=NOW)
        self.day(1)
        self.send(
            self.sald(self.a, "G9002", 2025, 10, 3),
            self.kvar(self.b, vikt=2.8),
            self.kvar(self.c, vikt=2.8),
            revision=1,
        )
        self.assertEqual([p.state for p in proposals(self.a)], ["avvisad", "foreslagen"])

    def test_change_after_rejection_kvar_leaves_the_rabbit(self):  # FB3's rule stops at an attested rabbit
        first = self.first()
        sp.reject(first, self.decider, reason="Fel datum", then="kvar", now=NOW)
        self.day(1)
        self.send(
            self.sald(self.a, "G9002", 2025, 10, 3),
            self.kvar(self.b, vikt=3.0),
            self.kvar(self.c, vikt=2.8),
            revision=1,
        )
        self.assertEqual([p.state for p in proposals(self.a)], ["avvisad"])
        self.assertEqual(len(rows(self.a, "ATTESTATION")), 1)

    def test_owner_sale_survives_link_change_and_withdraw(self):  # FB5, acceptance case 1 with a sale
        entries = (self.kvar(self.a, vikt=2.8), self.sald(self.b, "G9002", 2025, 10, 3))
        self.send(*entries, self.sald(self.c, "utanfor", 2025, 11, 20, kopare=BUYER), who="owner")
        stored = (*entries, self.sald(self.c, "utanfor", 2025, 11, 20))  # as submitted: no buyer
        sales = rows(self.b, "TRANSFER") + rows(self.c, "TRANSFER")
        self.day(5)
        self.send(self.dod(self.a, 2025, 11, 20), *stored[1:], revision=1)
        self.assertEqual(db.Individual.get_by_id(self.a.id).death_date, date(2025, 11, 20))
        undo = (self.dod(self.a, 2025, 11, 20), self.kvar(self.b, vikt=2.8), stored[2])
        self.assertEqual(self.refused(lambda: self.send(*undo, revision=2)), [(self.b.id, "salj_via_lank")])
        self.day(6)
        self.withdraw(2)
        self.assertIsNone(db.Individual.get_by_id(self.a.id).death_date)
        self.assertEqual(rows(self.a, "ATTESTATION"), [])
        self.assertEqual([db.HerdTracking.get_by_id(row.id).voided_at for row in sales], [None, None])
        self.assertEqual([(c.name, c.town) for c in db.BuyerContact.select()], [(BUYER["name"], BUYER["town"])])
        self.assertEqual(db.SaleProposal.select().count(), 0)

    def test_link_withdraw_keeps_owners_january_sale(self):  # FB5 with K3's rule: the attestation goes from behind it
        self.send(
            self.sald(self.a, "G9002", 2026, 1, 5),
            self.kvar(self.b, vikt=2.8),
            self.kvar(self.c, vikt=2.8),
            who="owner",
        )
        (attest,), (sale,) = rows(self.a, "ATTESTATION"), rows(self.a, "TRANSFER")
        self.day(1)
        self.withdraw(1)
        self.assertIsNotNone(db.HerdTracking.get_by_id(attest.id).voided_at)
        self.assertIsNone(db.HerdTracking.get_by_id(sale.id).voided_at)

    def test_lock_order_against_queue_bulk_assign(self):  # K4
        if not _USE_POSTGRES:
            self.skipTest("row locks need PostgreSQL")
        # The owner sells c outside the genebank, so c's documents are buyer items; the link then sells a, which
        # makes the proposal's item P, and a photo of c arrives after it: item X, so X > P in id but is a buyer item.
        self.send(
            self.kvar(self.a, vikt=2.8),
            self.kvar(self.b, vikt=2.8),
            self.sald(self.c, "utanfor", 2025, 11, 20, kopare=BUYER),
            who="owner",
        )
        self.day(1)
        self.send(
            self.sald(self.a, "utanfor", 2025, 10, 3, kopare=OTHER_BUYER),
            self.kvar(self.b, vikt=2.8),
            self.sald(self.c, "utanfor", 2025, 11, 20),
            revision=1,
        )
        proposed = db.InboxItem.get_by_id(proposals(self.a)[0].inbox_item_id)
        photo = self.item_of(self.c)
        self.assertLess(proposed.id, photo.id)
        barrier, results = threading.Barrier(2, timeout=10), {}
        original = arsrapport._lock_rabbits

        def held_items_then_rabbits(ids, items):
            # the report path holds its items; the queue now takes what it can before the report goes on
            barrier.wait()
            time.sleep(0.5)
            return original(ids, items)

        def report_path():
            try:
                with APP.app_context():
                    self.withdraw(2)
                results["report"] = "ok"
            except Exception as exc:  # noqa: BLE001  # the test reports any failure, a deadlock included
                results["report"] = repr(exc)
            finally:
                db.DB_PROXY.close()

        def bulk_assign():
            client = APP.test_client(use_cookies=True)
            client.post("/api/login", json={"username": "man", "password": "pass"})
            try:
                barrier.wait()
                response = client.post("/api/v2/inkorg/tilldela", json={"herd": "G9001", "user_id": self.helper.id})
                results["queue"] = response.status_code
            finally:
                db.DB_PROXY.close()

        with mock.patch.object(arsrapport, "_lock_rabbits", side_effect=held_items_then_rabbits):
            threads = [threading.Thread(target=report_path), threading.Thread(target=bulk_assign)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
        self.assertFalse(any(thread.is_alive() for thread in threads), "hung threads")
        self.assertEqual(results, {"report": "ok", "queue": 200})
        self.assertEqual(db.InboxItem.get_by_id(proposed.id).state, "skrap")
        self.assertEqual(db.InboxItem.get_by_id(photo.id).assigned_to_id, self.helper.id)

    def item_of(self, rabbit):
        """An uploaded photo of `rabbit` in the herd's queue."""
        stored = [("inkorg/original/c.jpg", "c".rjust(64, "0"), None)]
        item, _ = inbox.create_upload(db.User.get_by_id(self.owner.id), self.h, None, stored)
        db.InboxDocument.update(individual=rabbit.id).where(db.InboxDocument.item == item.id).execute()
        return db.InboxItem.get_by_id(item.id)
