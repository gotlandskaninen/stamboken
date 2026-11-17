"""Void, undoing a sale, and no buyer identity in free text."""

import threading
import unittest
import uuid
from datetime import date, timedelta

import utils.data_access as da
import utils.database as db
from utils.herd_tracking import (
    OWN_ROWS_ONLY,
    HerdTrackingConflict,
    HerdTrackingError,
    HerdTrackingForbidden,
    HerdTrackingInvalid,
    _active_rows,
    _assert_no_new_violations,
    herd_tracking_history,
    record_herd_tracking,
    reject_contact_details,
    void_herd_tracking,
)

from tests.database_test import _USE_POSTGRES, DatabaseTest
from tests.ht_helpers import age_row, ht_row, make_individual


class VoidBase(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.g1, self.g2 = self.herds[0], self.herds[1]
        self.g3 = db.Herd.create(genebank=self.genebanks[0], herd="G3", herd_name="Tre", is_active=True)
        self.gx1 = db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför", is_active=True)
        self.buyer = da.register_user("buyer", "pass")
        self.buyer.add_role("owner", self.g2.id)
        self.other_owner = da.register_user("other", "pass")
        self.other_owner.add_role("owner", self.g3.id)
        self.today = date.today()
        self.sale_day = self.today - timedelta(days=2)
        self.rabbit = make_individual(self.g1, "G1-2401", date(2024, 1, 1))
        ht_row("BIRTH", individual=self.rabbit, herd=self.g1, herd_tracking_date=date(2024, 1, 1))
        self.sale = record_herd_tracking(self.rabbit, self.g2, self.sale_day, "TRANSFER", self.owner)

    def _holder(self):
        return db.Individual.get_by_id(self.rabbit.id).current_herd.herd


class TestUndoSale(VoidBase):
    def test_seller_undoes_within_the_window(self):
        before = db.Individual.get_by_id(self.rabbit.id)
        row = void_herd_tracking(self.sale.id, self.owner, "Fel besättning vald")
        self.assertIsNotNone(row.voided_at)
        self.assertEqual(self._holder(), "G1")
        after = db.Individual.get_by_id(self.rabbit.id)
        self.assertEqual((after.number, after.origin_herd_id), (before.number, before.origin_herd_id))

    def test_outside_the_window_needs_a_manager(self):
        age_row(self.sale, 8)
        with self.assertRaises(HerdTrackingForbidden) as ctx:
            void_herd_tracking(self.sale.id, self.owner, "För sent")
        self.assertTrue(ctx.exception.detail.endswith("Kontakta genbanksansvarig."))
        void_herd_tracking(self.sale.id, self.manager, "Korrigering")
        self.assertEqual(self._holder(), "G1")

    def test_a_later_row_blocks_the_seller(self):
        record_herd_tracking(self.rabbit, self.g2, self.today, "ATTESTATION", self.buyer)
        with self.assertRaises(HerdTrackingForbidden):
            void_herd_tracking(self.sale.id, self.owner, "Ångrar")

    def test_doe_bought_pregnant_blocks_the_seller(self):
        """Breeding in the buyer's herd dated BEFORE the sale (mother_belongs_to_herd case)."""
        db.Breeding.create(mother=self.rabbit, breeding_herd_id=self.g2, breed_date=self.sale_day - timedelta(days=10))
        with self.assertRaises(HerdTrackingForbidden):
            void_herd_tracking(self.sale.id, self.owner, "Ångrar")

    def test_breeding_after_the_sale_in_any_herd_blocks_the_seller(self):
        db.Breeding.create(mother=self.rabbit, breeding_herd_id=self.g3, breed_date=self.today)
        with self.assertRaises(HerdTrackingForbidden):
            void_herd_tracking(self.sale.id, self.owner, "Ångrar")

    def test_permission_follows_the_from_herd(self):
        for user in (self.buyer, self.other_owner):
            with self.assertRaises(HerdTrackingForbidden):
                void_herd_tracking(self.sale.id, user, "Ångrar")
        void_herd_tracking(self.sale.id, self.owner, "Ångrar")

    def test_a_non_seller_is_told_who_may_undo_before_the_window(self):
        age_row(self.sale, 8)
        with self.assertRaises(HerdTrackingForbidden) as ctx:
            void_herd_tracking(self.sale.id, self.other_owner, "Ångrar")
        self.assertTrue(ctx.exception.detail.startswith("Bara säljaren kan ångra försäljningen."))

    def test_manager_rights_follow_the_rows_genebank(self):
        age_row(self.sale, 8)
        foreign = da.register_user("man2", "pass")
        foreign.add_role("manager", self.genebanks[1].id)
        with self.assertRaises(HerdTrackingForbidden):
            void_herd_tracking(self.sale.id, db.User.get_by_id(foreign.id), "Korrigering")
        void_herd_tracking(self.sale.id, self.admin, "Korrigering")
        self.assertEqual(self._holder(), "G1")

    def test_sell_undo_sell_again_on_the_same_date(self):
        void_herd_tracking(self.sale.id, self.owner, "Fel köpare")
        again = record_herd_tracking(self.rabbit, self.g3, self.sale_day, "TRANSFER", self.owner)
        self.assertEqual(again.from_herd_id, self.g1.id)
        v1 = db.Individual.get_by_id(self.rabbit.id).as_dict()["herd_tracking"]
        self.assertEqual([t["herd"] for t in v1], ["G3", "G1"])

    def test_already_voided_is_a_no_op(self):
        first = void_herd_tracking(self.sale.id, self.owner, "Fel köpare")
        second = void_herd_tracking(self.sale.id, self.manager, "Igen")
        self.assertEqual(second.voided_operation_id, first.voided_operation_id)
        self.assertEqual(second.voided_reason, "Fel köpare")

    def test_replayed_operation_id_never_voids_a_second_row(self):
        """Ruling I4: idempotency per (individual, operation_id), checked before the row's own voided state."""
        op = uuid.uuid4()
        void_herd_tracking(self.sale.id, self.owner, "Fel köpare", operation_id=op)
        report = record_herd_tracking(self.rabbit, self.g1, self.today, "ATTESTATION", self.owner)
        replay = void_herd_tracking(report.id, self.owner, "Fel köpare", operation_id=op)
        self.assertEqual(replay.id, self.sale.id)
        self.assertIsNone(db.HerdTracking.get_by_id(report.id).voided_at)


class TestOwnRowsOnly(VoidBase):
    """ADR-0017: others than managers void only the rows they recorded, as the last rule, so earlier ones keep
    their messages."""

    def setUp(self):
        super().setUp()
        self.co_owner = da.register_user("co", "pass")
        self.co_owner.add_role("owner", self.g1.id)
        self.report_rabbit = make_individual(self.g1, "G1-2402", date(2024, 1, 1))
        ht_row("BIRTH", individual=self.report_rabbit, herd=self.g1, herd_tracking_date=date(2024, 1, 1))

    def _refused(self, row, user):
        with self.assertRaises(HerdTrackingForbidden) as ctx:
            void_herd_tracking(row.id, user, "Fel kanin")
        return ctx.exception.detail

    def _caretaker(self):
        """A grant holder on G1, as in test_individual_sell_v2.py::TestTransferPermissionsV2."""
        membership = db.Membership.create(member_number=6, membership_status="active")
        self.g1.membership = membership
        self.g1.save()
        user = da.register_user("sune@example.com", "pass", username="sune")
        member = db.Member.create(
            membership=membership, first_name="Sune", last_name="S", email="sune@example.com", role="skotare", user=user
        )
        db.HerdAccessGrant.create(member=member, herd=self.g1, granted_by=self.admin)
        return user

    def test_co_owner_cannot_void_others_report(self):
        report = record_herd_tracking(self.report_rabbit, self.g1, self.today, "ATTESTATION", self.owner)
        self.assertEqual(self._refused(report, self.co_owner), OWN_ROWS_ONLY)
        void_herd_tracking(report.id, self.owner, "Fel kanin")

    def test_co_owner_cannot_undo_others_sale(self):
        self.assertEqual(self._refused(self.sale, self.co_owner), OWN_ROWS_ONLY)
        self.assertEqual(self._holder(), "G2")

    def test_caretaker_voids_own_report(self):
        caretaker = self._caretaker()
        report = record_herd_tracking(self.report_rabbit, self.g1, self.today, "ATTESTATION", caretaker)
        self.assertIsNotNone(void_herd_tracking(report.id, caretaker, "Fel kanin").voided_at)

    def test_unsigned_row_needs_manager(self):
        report = ht_row("ATTESTATION", individual=self.report_rabbit, herd=self.g1, herd_tracking_date=self.today)
        self.assertEqual(self._refused(report, self.owner), OWN_ROWS_ONLY)
        self.assertIsNotNone(void_herd_tracking(report.id, self.manager, "Fel kanin").voided_at)

    def test_history_can_void_follows_signature(self):
        report = record_herd_tracking(self.report_rabbit, self.g1, self.today, "ATTESTATION", self.owner)
        individual = db.Individual.get_by_id(self.report_rabbit.id)
        flags = {}
        for name, user in (("owner", self.owner), ("co", self.co_owner), ("manager", self.manager)):
            rows = herd_tracking_history(individual, user)["rows"]
            flags[name] = next(r["can_void"] for r in rows if r["id"] == report.id)
        self.assertEqual(flags, {"owner": True, "co": False, "manager": True})


class TestVoidMatrix(VoidBase):
    def _report(self, rabbit, herd, user, day=None):
        return record_herd_tracking(rabbit, herd, day or self.today, "ATTESTATION", user)

    def _own_rabbit(self, number):
        rabbit = make_individual(self.g1, number, date(2024, 1, 1))
        ht_row("BIRTH", individual=rabbit, herd=self.g1, herd_tracking_date=date(2024, 1, 1))
        return rabbit

    def test_owner_voids_own_fresh_latest_report(self):
        rabbit = self._own_rabbit("G1-2402")
        report = self._report(rabbit, self.g1, self.owner)
        self.assertIsNotNone(void_herd_tracking(report.id, self.owner, "Fel kanin").voided_at)

    def test_owner_cannot_void_an_old_report(self):
        rabbit = self._own_rabbit("G1-2403")
        report = self._report(rabbit, self.g1, self.owner)
        age_row(report, 8)
        with self.assertRaises(HerdTrackingForbidden):
            void_herd_tracking(report.id, self.owner, "Fel kanin")

    def test_owner_cannot_void_a_report_that_is_not_latest(self):
        rabbit = self._own_rabbit("G1-2404")
        report = self._report(rabbit, self.g1, self.owner, self.today - timedelta(days=1))
        record_herd_tracking(rabbit, self.g2, self.today, "TRANSFER", self.owner)
        with self.assertRaises(HerdTrackingForbidden):
            void_herd_tracking(report.id, self.owner, "Fel kanin")

    def test_owner_of_another_herd_cannot_void_a_report(self):
        rabbit = self._own_rabbit("G1-2405")
        report = self._report(rabbit, self.g1, self.owner)
        with self.assertRaises(HerdTrackingForbidden):
            void_herd_tracking(report.id, self.other_owner, "Fel kanin")

    def test_correction_rows_are_manager_only(self):
        rabbit = self._own_rabbit("G1-2406")
        fix = ht_row("CORRECTION", individual=rabbit, herd=self.g2, from_herd=self.g1, herd_tracking_date=self.today)
        with self.assertRaises(HerdTrackingForbidden):
            void_herd_tracking(fix.id, self.owner, "Nej")
        void_herd_tracking(fix.id, self.manager, "Felaktig korrigering")

    def test_birth_cannot_be_voided_even_by_a_manager(self):
        birth = db.HerdTracking.get((db.HerdTracking.individual == self.rabbit) & (db.HerdTracking.kind == "BIRTH"))
        with self.assertRaises(HerdTrackingForbidden):
            void_herd_tracking(birth.id, self.manager, "Nej")

    def test_losing_the_birth_is_an_i5_conflict(self):
        """void_denial refuses BIRTH first; the invariant check is the second line of defence (I5)."""
        before = _active_rows(self.rabbit.id)
        with self.assertRaises(HerdTrackingConflict) as ctx:
            _assert_no_new_violations(self.rabbit, before, [r for r in before if r.kind != "BIRTH"])
        self.assertEqual([r["code"] for r in ctx.exception.rows], ["I5"])

    def test_void_that_breaks_a_later_report_is_a_conflict(self):
        """Voiding the sale under a buyer report leaves the report in a herd that no longer holds the rabbit (I2)."""
        report = record_herd_tracking(self.rabbit, self.g2, self.today, "ATTESTATION", self.buyer)
        with self.assertRaises(HerdTrackingConflict) as ctx:
            void_herd_tracking(self.sale.id, self.manager, "Korrigering")
        self.assertEqual([(r["code"], r["id"]) for r in ctx.exception.rows], [("I2", report.id)])

    def test_reason_is_required_and_rejects_contact_details(self):
        for reason in ("", "   ", "ring 070-123 45 67", "köparen kopare@example.com", "+46 70 123 45 67"):
            with self.assertRaises(HerdTrackingInvalid, msg=reason):
                void_herd_tracking(self.sale.id, self.owner, reason)
        self.assertIsNone(db.HerdTracking.get_by_id(self.sale.id).voided_at)

    def test_contact_check_spares_dates_and_numbers(self):
        spared = (
            "Såld 2025-09-30 2025-10-01",
            "Fel kanin G1-2511",
            "kull 05",
            "Datum 01 10 2025",
            "kullnr 0 2025-10-01",
            "Såld 2025-10-01 till G1274 05 08 2025",
            "tatuering 0012 3456",
            "G1274-2112",
            "Såld 2025-09-30",
            "år 2020 2021 2022",
        )
        for text in spared:
            with self.subTest(text=text):
                reject_contact_details(text)

    def test_contact_check_rejects_phone_numbers(self):
        rejected = (
            "070.123.45.67",
            "(08) 123 45 67",
            "08/123 45 67",
            "46701234567",
            "+46 70 123 45 67",
            "+46 (0)70 123 45 67",
            "070-123 45 67",
            "ring 0701234567",
        )
        for text in rejected:
            with self.subTest(text=text), self.assertRaises(HerdTrackingInvalid):
                reject_contact_details(text)


class TestOutsideGenebank(VoidBase):
    def setUp(self):
        super().setUp()
        gx_owner = da.register_user("gxowner", "pass")
        gx_owner.add_role("owner", self.gx1.id)
        self.gx_owner = db.User.get_by_id(gx_owner.id)

    def _sold_out(self, number):
        rabbit = make_individual(self.g1, number, date(2024, 1, 1))
        ht_row("BIRTH", individual=rabbit, herd=self.g1, herd_tracking_date=date(2024, 1, 1))
        return rabbit, record_herd_tracking(rabbit, self.gx1, self.sale_day, "TRANSFER", self.owner)

    def test_owner_privilege_on_gx1_gives_no_edit_rights(self):
        """Beslut 7: after a sale out of the genebank only managers/admin act on the rabbit."""
        gx_owner = self.gx_owner
        rabbit, out = self._sold_out("G1-2410")
        self.assertFalse(gx_owner.can_edit(rabbit.id))
        self.assertFalse(gx_owner.can_edit(rabbit.number))
        self.assertFalse(gx_owner.can_transfer(rabbit.id))
        self.assertTrue(self.manager.can_edit(rabbit.id))
        self.assertTrue(self.manager.can_transfer(rabbit.id))
        self.assertFalse(self.owner.can_edit(rabbit.id))
        void_herd_tracking(out.id, self.owner, "Fel, kaninen är kvar")  # the seller's undo still works
        self.assertEqual(db.Individual.get_by_id(rabbit.id).current_herd.herd, "G1")

    def test_gx1_owner_cannot_undo_a_managers_buy_back(self):
        rabbit, _ = self._sold_out("G1-2411")
        back = record_herd_tracking(rabbit, self.g2, self.today, "TRANSFER", self.manager)
        with self.assertRaises(HerdTrackingForbidden):
            void_herd_tracking(back.id, self.gx_owner, "Ångrar")
        self.assertIsNone(db.HerdTracking.get_by_id(back.id).voided_at)

    def test_gx1_owner_cannot_void_an_attestation_in_gx1(self):
        rabbit, _ = self._sold_out("G1-2412")
        report = record_herd_tracking(rabbit, self.gx1, self.today, "ATTESTATION", self.manager)
        with self.assertRaises(HerdTrackingForbidden):
            void_herd_tracking(report.id, self.gx_owner, "Fel kanin")
        self.assertIsNone(db.HerdTracking.get_by_id(report.id).voided_at)

    def test_gx1_herd_code_is_manager_only(self):
        """Beslut 7 extended: can_edit(<GX1/MX1>) gates add_individual, update_herd and save_yearly_report."""
        self.assertFalse(self.gx_owner.can_edit("GX1"))
        self.assertTrue(self.manager.can_edit("GX1"))
        self.assertTrue(self.admin.can_edit("GX1"))
        self.assertTrue(self.owner.can_edit("G1"))
        self.assertTrue(db.User.get_by_id(self.buyer.id).can_edit("G2"))


@unittest.skipUnless(_USE_POSTGRES, "row locks need PostgreSQL")
class TestVoidConcurrency(VoidBase):
    def test_seller_undo_and_buyer_report_serialise(self):
        rabbit_id, sale_id, g2_id = self.rabbit.id, self.sale.id, self.g2.id
        owner_id, buyer_id = self.owner.id, self.buyer.id
        barrier, results = threading.Barrier(2), []

        def run(fn):
            try:
                barrier.wait(timeout=10)
                results.append(fn())
            except HerdTrackingError as exc:
                results.append(exc)
            finally:
                db.DB_PROXY.close()

        undo = lambda: void_herd_tracking(sale_id, db.User.get_by_id(owner_id), "Ångrar")  # noqa: E731
        report = lambda: record_herd_tracking(  # noqa: E731
            db.Individual.get_by_id(rabbit_id), g2_id, self.today, "ATTESTATION", db.User.get_by_id(buyer_id)
        )
        threads = [threading.Thread(target=run, args=(fn,)) for fn in (undo, report)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        errors = [r for r in results if isinstance(r, HerdTrackingError)]
        self.assertEqual(len(results), 2)
        self.assertEqual(len(errors), 1, f"exactly one of undo/report must lose: {results}")
