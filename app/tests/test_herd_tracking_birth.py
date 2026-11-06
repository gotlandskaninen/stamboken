"""Birth-row writers: void + new BIRTH, found by kind, never by date."""

import unittest
from datetime import date, datetime, timedelta
from unittest import mock

import utils.data_access as da
import utils.database as db
from herdbook import APP
from utils import genetics_service
from utils.herd_tracking import HerdTrackingConflict, HerdTrackingForbidden, HerdTrackingNotFound, replace_birth_row

from tests.database_test import _USE_POSTGRES, DatabaseTest
from tests.ht_helpers import _active, ht_row, make_individual


class TestBirthReplacement(DatabaseTest):
    def setUp(self):
        super().setUp()
        for herd in self.herds:
            herd.is_active = True
            herd.save()
        self.g1, self.g2 = self.herds[0], self.herds[1]
        self.g3 = db.Herd.create(genebank=self.genebanks[0], herd="G3", herd_name="Tre", is_active=True)
        self.gb = self.genebanks[0].id

    def test_same_day_birth_and_sale_then_origin_change_keeps_the_buyer(self):
        """BIRTH + TRANSFER same day → replace BIRTH → holder still the buyer, all readers agree."""
        born = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d")
        breeding = db.Breeding.create(
            breed_date=datetime.now() - timedelta(days=51),
            birth_date=datetime.now() - timedelta(days=20),
            litter_size=1,
            litter_size6w=1,
            breeding_herd_id=self.g1,
        )
        form = {
            "herd": "G2",
            "origin_herd": {"herd": "G1"},
            "number": "G1-2601",
            "breeding": breeding.id,
            "birth_date": born,
            "selling_date": born,
            "certificate": "C-2601",
        }
        self.assertEqual(da.add_individual(form, self.admin.uuid)["status"], "success")
        ind = db.Individual.get(db.Individual.number == "G1-2601")
        self.assertEqual([r.kind for r in _active(ind)], ["TRANSFER", "BIRTH"])

        da.update_origin_herd_ind(ind, self.g3, self.manager)

        ind = db.Individual.get_by_id(ind.id)
        rows = _active(ind)
        self.assertEqual([(r.kind, r.herd.herd) for r in rows], [("TRANSFER", "G2"), ("BIRTH", "G3")])
        self.assertGreater(rows[1].id, rows[0].id, "the replacement BIRTH has the higher id")
        self.assertEqual(ind.current_herd.herd, "G2")
        listed = {i["number"]: i for i in da.get_individuals(self.gb, self.admin.uuid)}
        self.assertEqual(listed[ind.number]["herd"]["herd"], "G2")
        page = da.get_paginated_individuals(self.admin.uuid, per_page=200, genebank_id=self.gb, search=ind.number)
        self.assertEqual([i["herd"] for i in page["items"]], ["G2"])
        self.assertIn(ind.number, [i["number"] for i in da.get_herd("G2", self.admin.uuid)["individuals"]])
        self.assertTrue(da.was_in_herd_at_date(ind.id, self.g2.id, rows[0].herd_tracking_date))
        self.assertIn(ind.number, genetics_service.reference_population_numbers(self.gb, rows[0].herd_tracking_date))
        voided = db.HerdTracking.select().where(
            db.HerdTracking.individual == ind, db.HerdTracking.voided_at.is_null(False)
        )
        self.assertEqual([r.voided_reason for r in voided], ["Ersatt: ändrad ursprungsbesättning"])
        self.assertEqual(voided[0].voided_operation_id, rows[1].operation_id, "void + new BIRTH are one operation")

    def test_birth_row_is_found_by_kind_not_by_date(self):
        ind = make_individual(self.g1, "G1-2602", date(2026, 1, 10))
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=date(2026, 1, 20))  # registration date
        da.update_birth_date_herd_tracking(
            ind, self.manager, new_date=datetime(2026, 1, 12), old_date=datetime(2026, 1, 10)
        )
        self.assertEqual([r.herd_tracking_date for r in _active(ind)], [date(2026, 1, 12)])

    def test_birth_date_after_another_active_row_is_refused(self):
        ind = make_individual(self.g1, "G1-2603", date(2026, 1, 10))
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=date(2026, 1, 10))
        ht_row("TRANSFER", individual=ind, herd=self.g2, from_herd=self.g1, herd_tracking_date=date(2026, 3, 1))
        with self.assertRaises(HerdTrackingConflict) as ctx:
            replace_birth_row(ind, self.manager, date=date(2026, 4, 1), reason="test")
        self.assertEqual([r["code"] for r in ctx.exception.rows], ["I3"])
        self.assertEqual([r.kind for r in _active(ind)], ["TRANSFER", "BIRTH"], "nothing was voided")

    def test_birth_date_change_that_hands_the_rabbit_to_another_genebank_is_admin_only(self):
        """A tolerated legacy row before BIRTH (I3) becomes the holder once the birth moves before it."""
        ind = make_individual(self.g1, "G1-2607", date(2026, 4, 1))
        ht_row("TRANSFER", individual=ind, herd=self.herds[2], from_herd=self.g1, herd_tracking_date=date(2026, 3, 1))
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=date(2026, 4, 1))
        with self.assertRaises(HerdTrackingForbidden):
            replace_birth_row(ind, self.manager, date=date(2026, 2, 1), reason="test")
        self.assertEqual([r.herd_tracking_date for r in _active(ind)], [date(2026, 4, 1), date(2026, 3, 1)])
        replace_birth_row(ind, self.admin, date=date(2026, 2, 1), reason="test")
        self.assertEqual(db.Individual.get_by_id(ind.id).current_herd.herd, "M3")

    def test_origin_change_with_reports_in_the_old_herd_is_refused(self):
        """Behaviour change (I2): the reports would no longer match the holder — use the correction command."""
        ind = make_individual(self.g1, "G1-2604", date(2026, 1, 10))
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=date(2026, 1, 10))
        ht_row("ATTESTATION", individual=ind, herd=self.g1, herd_tracking_date=date(2026, 6, 1))
        with self.assertRaises(HerdTrackingConflict):
            da.update_origin_herd_ind(ind, self.g2, self.manager)
        self.assertEqual(db.Individual.get_by_id(ind.id).origin_herd_id, self.g1.id, "origin change rolled back")

    def test_no_birth_row_keeps_the_legacy_error(self):
        ind = make_individual(self.g1, "G1-2605", date(2026, 1, 10))
        ht_row("TRANSFER", individual=ind, herd=self.g2, from_herd=self.g1, herd_tracking_date=date(2026, 1, 10))
        with self.assertRaises(HerdTrackingNotFound) as ctx:
            replace_birth_row(ind, self.manager, herd=self.g3, reason="test")
        self.assertEqual(str(ctx.exception), "Individual does not have birth_date herdtracking event")
        self.assertIsInstance(ctx.exception, ValueError)

    def test_same_operation_id_replaces_once(self):
        ind = make_individual(self.g1, "G1-2606", date(2026, 1, 10))
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=date(2026, 1, 10))
        op = "6f0a1c9e-2f43-4a57-9d1e-0b7f4e3b2a11"
        first = replace_birth_row(ind, self.manager, herd=self.g3, reason="test", operation_id=op)
        again = replace_birth_row(ind, self.manager, herd=self.g3, reason="test", operation_id=op)
        self.assertEqual(first.id, again.id)
        self.assertEqual(len(_active(ind)), 1)


class TestAppendOnlyModel(DatabaseTest):
    def test_save_of_a_persisted_row_raises(self):
        row = ht_row("ATTESTATION", individual=self.individuals[0], herd=self.herds[0], herd_tracking_date="2022-01-01")
        row.herd = self.herds[1]
        with self.assertRaises(RuntimeError):
            row.save()


class TestBreedingEditIsAtomic(DatabaseTest):
    """A refused sibling leaves every kit and the breeding untouched; v2 answers 409, legacy never 500."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.g1, self.g2 = self.herds[0], self.herds[1]
        self.breeding = db.Breeding.create(
            breed_date=datetime(2026, 1, 1),
            birth_date=datetime(2026, 2, 1),
            mother=self.parents[0],
            father=self.parents[1],
            litter_size=2,
            litter_size6w=2,
            breeding_herd_id=self.g1,
        )
        self.kits = []
        for n in ("G1-2601", "G1-2602"):
            kit = db.Individual.create(origin_herd=self.g1, breeding=self.breeding, number=n, sex="female")
            ht_row("BIRTH", individual=kit, herd=self.g1, herd_tracking_date=date(2026, 2, 1))
            self.kits.append(kit)
        # The SECOND kit has a report in the old herd: its BIRTH cannot move (I2).
        ht_row("ATTESTATION", individual=self.kits[1], herd=self.g1, herd_tracking_date=date(2026, 6, 1))
        self.client.post("/api/login", json={"username": "admin", "password": "pass"})

    def _assert_nothing_changed(self):
        for kit, number in zip(self.kits, ("G1-2601", "G1-2602"), strict=True):
            fresh = db.Individual.get_by_id(kit.id)
            self.assertEqual((fresh.origin_herd_id, fresh.number), (self.g1.id, number))
            rows = _active(kit)
            self.assertEqual(rows[-1].kind, "BIRTH")
            self.assertEqual((rows[-1].herd_id, rows[-1].herd_tracking_date), (self.g1.id, date(2026, 2, 1)))
            self.assertFalse(
                db.HerdTracking.select().where(
                    db.HerdTracking.individual == kit, db.HerdTracking.voided_at.is_null(False)
                )
            )
        fresh = db.Breeding.get_by_id(self.breeding.id)
        self.assertEqual(fresh.breeding_herd_id_id, self.g1.id)
        self.assertEqual(fresh.birth_date, date(2026, 2, 1))

    def test_v2_breeding_herd_change_refused_on_second_kit_is_409_and_atomic(self):
        response = self.client.patch(f"/api/v2/breeding/{self.breeding.id}", json={"breeding_herd": "G2"})
        self.assertEqual(response.status_code, 409, response.get_data(as_text=True))
        self.assertTrue(response.get_json()["rows"])
        self._assert_nothing_changed()

    def test_v2_birth_date_change_refused_on_second_kit_is_409_and_atomic(self):
        response = self.client.patch(f"/api/v2/breeding/{self.breeding.id}", json={"birth_date": "2026-07-01"})
        self.assertEqual(response.status_code, 409, response.get_data(as_text=True))
        self._assert_nothing_changed()

    def test_legacy_breeding_refusal_is_an_error_dict_not_a_500(self):
        response = self.client.patch("/api/breeding", json={"id": self.breeding.id, "breeding_herd": "G2"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["status"], "error")
        self._assert_nothing_changed()


class TestUnchangedOriginHerd(DatabaseTest):
    """Fix round 2: resending the SAME origin_herd must not touch the history."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.g1, self.g2 = self.herds[0], self.herds[1]
        self.client.post("/api/login", json={"username": "admin", "password": "pass"})

    def _litter(self, numbers):
        breeding = db.Breeding.create(
            breed_date=datetime(2026, 1, 1),
            birth_date=datetime(2026, 2, 1),
            mother=self.parents[0],
            father=self.parents[1],
            litter_size=len(numbers),
            litter_size6w=len(numbers),
            breeding_herd_id=self.g1,
        )
        kits = []
        for n in numbers:
            kit = db.Individual.create(origin_herd=self.g1, breeding=breeding, number=n, sex="female")
            ht_row("BIRTH", individual=kit, herd=self.g1, herd_tracking_date=date(2026, 2, 1))
            kits.append(kit)
        return breeding, kits

    def _ht_state(self, kit):
        return [(r.id, r.voided_at) for r in db.HerdTracking.select().where(db.HerdTracking.individual == kit)]

    def _payload(self, breeding):
        return {"herd": "G1", "origin_herd": {"herd": "G1"}, "breeding": breeding.id}

    def test_v2_patch_same_origin_herd_writes_nothing(self):
        breeding, (kit,) = self._litter(["G1-2611"])
        before = self._ht_state(kit)
        response = self.client.patch(f"/api/individual/{kit.number}", json=self._payload(breeding))
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(self._ht_state(kit), before)

    def test_legacy_update_same_origin_herd_writes_nothing(self):
        breeding, (kit,) = self._litter(["G1-2612"])
        before = self._ht_state(kit)
        form = {"id": kit.id, "number": kit.number, **self._payload(breeding)}
        self.assertEqual(da.update_individual(form, self.admin.uuid)["status"], "success")
        self.assertEqual(self._ht_state(kit), before)

    def test_multi_kit_same_origin_herd_succeeds_and_keeps_breeding_herd(self):
        breeding, (kit, _) = self._litter(["G1-2613", "G1-2614"])
        before = self._ht_state(kit)
        response = self.client.patch(f"/api/individual/{kit.number}", json=self._payload(breeding))
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(self._ht_state(kit), before)
        self.assertEqual(db.Breeding.get_by_id(breeding.id).breeding_herd_id_id, self.g1.id)

    def test_replace_birth_row_with_identical_herd_and_date_is_a_noop(self):
        _, (kit,) = self._litter(["G1-2615"])
        before = self._ht_state(kit)
        row = replace_birth_row(kit, self.manager, herd=self.g1, date=date(2026, 2, 1), reason="test")
        self.assertEqual(row.kind, "BIRTH")
        self.assertEqual(self._ht_state(kit), before)

    def test_real_origin_change_on_single_kit_replaces_birth_and_sets_breeding_herd(self):
        breeding, (kit,) = self._litter(["G1-2616"])
        payload = {"herd": "G1", "origin_herd": {"herd": "G2"}, "breeding": breeding.id}
        response = self.client.patch(f"/api/individual/{kit.number}", json=payload)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual([r.herd.herd for r in _active(kit)], ["G2"])
        self.assertEqual(db.HerdTracking.select().where(db.HerdTracking.individual == kit).count(), 2)
        self.assertEqual(db.Breeding.get_by_id(breeding.id).breeding_herd_id_id, self.g2.id)


@unittest.skipUnless(_USE_POSTGRES, "row locks need PostgreSQL")
class TestBreedingEditLockOrder(DatabaseTest):
    """update_breeding locks Breeding first, then its kits in ascending id."""

    def setUp(self):
        super().setUp()
        self.g1 = self.herds[0]
        self.breeding = db.Breeding.create(
            breed_date=datetime(2026, 1, 1),
            birth_date=datetime(2026, 2, 1),
            mother=self.parents[0],
            father=self.parents[1],
            litter_size=2,
            litter_size6w=2,
            breeding_herd_id=self.g1,
        )
        self.kits = []
        for n in ("G1-2631", "G1-2632"):
            kit = db.Individual.create(origin_herd=self.g1, breeding=self.breeding, number=n, sex="female")
            ht_row("BIRTH", individual=kit, herd=self.g1, herd_tracking_date=date(2026, 2, 1))
            self.kits.append(kit)
        # Rewrite the lower-id kit so an unordered scan returns it LAST (new heap tuple).
        db.Individual.update(name="Flyttad").where(db.Individual.id == self.kits[0].id).execute()

    def _locks(self, statements):
        return [(sql, params) for sql, params in statements if "FOR UPDATE" in sql or "FOR NO KEY UPDATE" in sql]

    def test_breeding_is_locked_first_then_kits_ascending(self):
        statements = []
        original = db.DATABASE.execute_sql

        def capture(sql, params=None, *args, **kwargs):
            statements.append((sql, list(params or [])))
            return original(sql, params, *args, **kwargs)

        with mock.patch.object(db.DATABASE, "execute_sql", side_effect=capture):
            result = da.update_breeding({"id": self.breeding.id, "birth_date": "2026-02-03"}, self.admin.uuid)
        self.assertEqual(result["status"], "success", result)
        locks = self._locks(statements)
        self.assertTrue(locks, "no row locks taken")
        self.assertIn('FROM "breeding"', locks[0][0], "the Breeding row is the first lock")
        kit_ids = {k.id for k in self.kits}
        locked = [p for sql, params in locks[1:] if 'FROM "individual"' in sql for p in params if p in kit_ids]
        first_seen = list(dict.fromkeys(locked))
        self.assertEqual(first_seen, sorted(kit_ids), "kits are locked in ascending id order")
