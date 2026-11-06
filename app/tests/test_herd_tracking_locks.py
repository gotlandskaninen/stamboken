"""Lock before check, one global order Breeding → Individuals (ascending).

The races are simulated deterministically: `lock_individuals` (in da and individual_commands) is wrapped so the seller's
undo-sale lands at the exact moment the request acquires its lock — the latest a concurrent
undo could commit. Code that checks permission/ownership before that lock acts on stale state.

isort:skip_file
"""

import os
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import unittest  # noqa: E402

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.individual_commands as ic  # noqa: E402
from herdbook import APP, limiter  # noqa: E402
from utils import herd_tracking  # noqa: E402
from utils.herd_tracking import record_herd_tracking  # noqa: E402

from tests.database_test import _USE_POSTGRES, DatabaseTest  # noqa: E402
from tests.ht_helpers import ht_row, make_individual  # noqa: E402

limiter.enabled = False


@contextmanager
def capture_sql():
    """Record every SQL statement (text, params) executed inside the block."""
    statements = []
    original = db.DATABASE.execute_sql

    def capture(sql, params=None, *args, **kwargs):
        statements.append((sql, list(params or [])))
        return original(sql, params, *args, **kwargs)

    with mock.patch.object(db.DATABASE, "execute_sql", side_effect=capture):
        yield statements


def _is_lock(sql):
    return "FOR UPDATE" in sql or "FOR NO KEY UPDATE" in sql


def _first(statements, predicate):
    return next((i for i, (sql, _) in enumerate(statements) if predicate(sql)), None)


class SaleBase(DatabaseTest):
    """Seller = self.owner (G1), buyer owns G2; the rabbit was sold G1 → G2 two days ago."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.g1, self.g2 = self.herds[0], self.herds[1]
        self.buyer = da.register_user("buyer", "pass")
        self.buyer.add_role("owner", self.g2.id)
        self.today = date.today()
        self.rabbit = make_individual(self.g1, "G1-2401", date(2024, 1, 1))
        ht_row("BIRTH", individual=self.rabbit, herd=self.g1, herd_tracking_date=date(2024, 1, 1))
        self.sale = record_herd_tracking(self.rabbit, self.g2, self.today - timedelta(days=2), "TRANSFER", self.owner)

    def _rows(self):
        return db.HerdTracking.select().where(db.HerdTracking.individual == self.rabbit.id).count()

    @contextmanager
    def _seller_undoes_at_lock(self):
        """The seller's undo-sale commits just before the request gets its individual lock."""
        original = da.lock_individuals
        state = {"flipped": False}

        def lock_after_undo(ids):
            if not state["flipped"] and self.rabbit.id in {int(i) for i in ids}:
                state["flipped"] = True
                herd_tracking._void_rows([self.sale], self.owner, "Fel köpare", uuid.uuid4())
            return original(ids)

        # update_individual and the v2 PATCH lock through individual_commands, register_breeding through da
        with (
            mock.patch.object(da, "lock_individuals", side_effect=lock_after_undo),
            mock.patch.object(ic, "lock_individuals", side_effect=lock_after_undo),
        ):
            yield state


class TestPermissionUnderTheLock(SaleBase):
    """Permission is (re-)checked while the individual lock is held."""

    def test_legacy_update_refuses_a_buyer_who_lost_the_rabbit_mid_request(self):
        form = {"id": self.rabbit.id, "number": self.rabbit.number, "herd": "G2", "yearly_report_date": str(self.today)}
        with self._seller_undoes_at_lock() as state:
            result = da.update_individual(form, self.buyer.uuid)
        self.assertTrue(state["flipped"], "the update never took the individual lock")
        self.assertEqual(result, {"status": "error", "message": "Forbidden"})
        # Not the herd after it: the undo is simulated inside the request's transaction, which execute's
        # refusal rolls back (a real undo commits on its own).
        self.assertEqual(self._rows(), 2, "no TRANSFER back to the buyer")

    def test_v2_patch_refuses_a_buyer_who_lost_the_rabbit_mid_request(self):
        self.client.post("/api/login", json={"username": "buyer", "password": "pass"})
        with self._seller_undoes_at_lock() as state:
            response = self.client.patch(
                f"/api/individual/{self.rabbit.number}", json={"herd": "G2", "yearly_report_date": str(self.today)}
            )
        self.assertTrue(state["flipped"], "the PATCH never took the individual lock")
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
        self.assertEqual(self._rows(), 2, "no TRANSFER back to the buyer")


class TestBreedingRegistrationLocksTheParents(SaleBase):
    """register_breeding locks the parents before the ownership check and holds them through the insert."""

    def setUp(self):
        super().setUp()
        self.buck = make_individual(self.g2, "G2-2402", date(2024, 1, 1), sex="male")
        ht_row("BIRTH", individual=self.buck, herd=self.g2, herd_tracking_date=date(2024, 1, 1))
        self.form = {
            "mother": self.rabbit.number,
            "father": self.buck.number,
            "breeding_herd": "G2",
            "date": str(self.today),
        }

    def _breedings(self):
        return db.Breeding.select().where(db.Breeding.mother == self.rabbit.id).count()

    def test_buyer_registration_refused_after_the_seller_undid_the_sale(self):
        before = self._breedings()
        with self._seller_undoes_at_lock() as state:
            result = da.register_breeding(self.form, self.buyer.uuid)
        self.assertTrue(state["flipped"], "register_breeding never locked the mother")
        self.assertEqual(result["status"], "error", result)
        self.assertIn("Honan tillhörde inte", result["message"])
        self.assertEqual(self._breedings(), before, "no breeding for a doe the buyer no longer has")

    @unittest.skipUnless(_USE_POSTGRES, "row locks need PostgreSQL")
    def test_parent_lock_precedes_the_ownership_check_and_the_insert(self):
        with capture_sql() as statements:
            result = da.register_breeding(self.form, self.buyer.uuid)
        self.assertEqual(result["status"], "success", result)
        lock = _first(statements, lambda sql: _is_lock(sql) and 'FROM "individual"' in sql)
        self.assertIsNotNone(lock, "the parents are never locked")
        self.assertEqual(statements[lock][1], sorted([self.rabbit.id, self.buck.id]), "both parents, ascending")
        ownership = _first(statements, lambda sql: '"herd_tracking"' in sql)
        insert = _first(statements, lambda sql: sql.startswith('INSERT INTO "breeding"'))
        self.assertLess(lock, ownership, "the ownership check reads herd tracking only under the lock")
        self.assertLess(lock, insert)


@unittest.skipUnless(_USE_POSTGRES, "row locks need PostgreSQL")
class TestBreedingEditLocksNewParents(SaleBase):
    """update_breeding locks Breeding, then kits + parents in ONE ascending call, before validating."""

    def test_changed_mother_is_locked_after_the_breeding(self):
        other = make_individual(self.g1, "G1-2403", date(2024, 1, 1))
        breeding = db.Breeding.create(
            breed_date=self.today - timedelta(days=5),
            mother=other,
            father=self.parents[1],
            breeding_herd_id=self.g1,
        )
        with capture_sql() as statements:
            result = da.update_breeding({"id": breeding.id, "mother": self.rabbit.number}, self.admin.uuid)
        self.assertEqual(result["status"], "success", result)
        locks = [(sql, params) for sql, params in statements if _is_lock(sql)]
        self.assertIn('FROM "breeding"', locks[0][0], "the Breeding row is the first lock")
        individual_locks = [params for sql, params in locks[1:] if 'FROM "individual"' in sql]
        self.assertTrue(any(self.rabbit.id in params for params in individual_locks), "the new mother is locked")
        self.assertEqual(individual_locks[0], sorted(individual_locks[0]), "ascending within one call")


@unittest.skipUnless(_USE_POSTGRES, "row locks need PostgreSQL")
class TestIndividualEditLockOrder(DatabaseTest):
    """An individual edit locks its Breeding before the individual (the order update_breeding takes)."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.ind = self.individuals[0]

    def _assert_breeding_then_individual(self, statements):
        locks = [(sql, params) for sql, params in statements if _is_lock(sql)]
        self.assertTrue(locks, "no row locks taken")
        self.assertIn('FROM "breeding"', locks[0][0], "the Breeding row is locked first")
        self.assertIn(self.ind.breeding_id, locks[0][1])
        first_ind = next(i for i, (sql, _) in enumerate(locks) if 'FROM "individual"' in sql)
        held = {p for sql, params in locks[:first_ind] if 'FROM "breeding"' in sql for p in params}
        later = {p for sql, params in locks[first_ind:] if 'FROM "breeding"' in sql for p in params}
        self.assertLessEqual(later, held, "no NEW Breeding lock after an individual lock (re-locks are free)")

    def test_legacy_update_individual(self):
        form = {"id": self.ind.id, "number": self.ind.number, "herd": "G1", "yearly_report_date": "2022-01-15"}
        with capture_sql() as statements:
            result = da.update_individual(form, self.manager.uuid)
        self.assertEqual(result["status"], "success", result)
        self._assert_breeding_then_individual(statements)

    def test_v2_patch(self):
        self.client.post("/api/login", json={"username": "man", "password": "pass"})
        with capture_sql() as statements:
            response = self.client.patch(
                f"/api/individual/{self.ind.number}", json={"herd": "G1", "yearly_report_date": "2022-01-15"}
            )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self._assert_breeding_then_individual(statements)


class TestBreedingEditAuthorizedUnderTheLock(SaleBase):
    """update_breeding re-checks can_edit on the litter's herd under the Breeding lock."""

    def setUp(self):
        super().setUp()
        # The litter is in the buyer's G2 (the doe was bought from the seller's G1); the buck sits in G1.
        self.breeding = db.Breeding.create(
            breed_date=self.today - timedelta(days=1),
            mother=self.rabbit,
            father=self.parents[0],
            breeding_herd_id=self.g2,
            breed_notes="före",
        )

    def test_buyer_edit_refused_when_the_litter_moves_mid_request(self):
        """A manager moves the litter to G1 after the unlocked read and before the Breeding lock.
        The buyer still holds the doe, but the litter is no longer in a herd the buyer owns."""
        real_validate_date = da.validate_date
        state = {"flipped": False}

        def move_before_the_lock(value):
            if not state["flipped"]:
                state["flipped"] = True
                db.Breeding.update(breeding_herd_id=self.g1).where(db.Breeding.id == self.breeding.id).execute()
            return real_validate_date(value)

        form = {"id": self.breeding.id, "breed_date": str(self.breeding.breed_date), "breed_notes": "efter"}
        with mock.patch.object(da, "validate_date", side_effect=move_before_the_lock):
            result = da.update_breeding(form, self.buyer.uuid)
        self.assertTrue(state["flipped"], "validate_date was never reached")
        self.assertEqual(result, {"status": "error", "message": "Forbidden"})
        self.assertEqual(db.Breeding.get_by_id(self.breeding.id).breed_notes, "före", "nothing written")

    @unittest.skipUnless(_USE_POSTGRES, "row locks need PostgreSQL")
    def test_stored_parents_are_locked_after_the_breeding(self):
        with capture_sql() as statements:
            result = da.update_breeding({"id": self.breeding.id, "breed_notes": "efter"}, self.buyer.uuid)
        self.assertEqual(result["status"], "success", result)
        locks = [(sql, params) for sql, params in statements if _is_lock(sql)]
        self.assertIn('FROM "breeding"', locks[0][0], "the Breeding row is the first lock")
        parents = sorted([self.rabbit.id, self.parents[0].id])
        self.assertTrue(
            any('FROM "individual"' in sql and params == parents for sql, params in locks[1:]),
            "both stored parents locked in one ascending call",
        )


class TestBreedingEditAppliesToTheLockedRow(DatabaseTest):
    """update_breeding applies only what this request changed to the row read under the lock,
    and validates that row. A correction committing after the request's unlocked read and before the
    lock is simulated deterministically inside validate_date (same pattern as the other lock tests)."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.target = self.breeding[0]  # G1 litter: mother parents[0] (G1-1911), bred 2021-01-01, born 2021-02-01
        self.corrected_mother = make_individual(self.herds[0], "G1-2001", date(2020, 1, 1))

    @contextmanager
    def _committed_before_the_lock(self, **values):
        real_validate_date = da.validate_date
        ran = []

        def concurrent_correction(value):
            if not ran:
                ran.append(True)
                db.Breeding.update(**values).where(db.Breeding.id == self.target.id).execute()
            return real_validate_date(value)

        with mock.patch.object(da, "validate_date", side_effect=concurrent_correction):
            yield
        self.assertTrue(ran, "validate_date was never reached")

    def test_notes_edit_keeps_mother_corrected_before_lock(self):
        form = {"id": self.target.id, "breed_date": "2021-01-01", "breed_notes": "updated"}
        with self._committed_before_the_lock(mother=self.corrected_mother):
            result = da.update_breeding(form, self.admin.uuid)
        row = db.Breeding.get_by_id(self.target.id)
        self.assertEqual(
            (result.get("status"), row.breed_notes, row.mother_id),
            ("success", "updated", self.corrected_mother.id),
            f"{result}: the committed mother correction was reverted",
        )

    def test_full_legacy_payload_keeps_mother_corrected_before_lock(self):
        """Legacy PATCHes the whole object it read earlier, so its payload still names the old mother.
        A renumber (litter_number) committed in the same window must survive too."""
        self.client.post("/api/login", json={"username": "owner", "password": "pass"})
        breeding = self.client.get(f"/api/breeding/id/{self.target.id}").get_json()["breeding"]
        payload = {k: v for k, v in breeding.items() if k != "individuals" and v is not None}
        payload["breed_notes"] = "från legacy"
        self.assertEqual(payload["mother"], self.parents[0].number)
        with self._committed_before_the_lock(mother=self.corrected_mother, litter_number=7):
            response = self.client.patch("/api/breeding", json=payload)
        row = db.Breeding.get_by_id(self.target.id)
        self.assertEqual(
            (response.status_code, response.get_json(), row.breed_notes, row.mother_id, row.litter_number),
            (200, {"status": "success"}, "från legacy", self.corrected_mother.id, 7),
            "the echoed payload reverted the committed correction",
        )

    def test_date_edit_is_validated_against_the_locked_row(self):
        """A birth-date correction (2021-02-01 -> 2021-01-30) commits before the lock. Moving the
        mating to 2021-01-06 is 26 days against the stale row but 24 against the locked one."""
        with self._committed_before_the_lock(birth_date=date(2021, 1, 30)):
            result = da.update_breeding({"id": self.target.id, "breed_date": "2021-01-06"}, self.owner.uuid)
        row = db.Breeding.get_by_id(self.target.id)
        self.assertEqual(
            (result.get("status"), str(row.breed_date), str(row.birth_date)),
            ("error", "2021-01-01", "2021-01-30"),
            result,
        )
        self.assertIn("Dräktighetsperioden", result["message"])

    def test_survivors_are_checked_against_born_corrected_before_lock(self):
        """Born 5, alive at 6 weeks 3. B corrects born to 4 after A's read; A sets alive to 5.
        The locked row would be (4, 5): more survivors than births, and a certificate quota of 5."""
        db.Breeding.update(litter_size=5, litter_size6w=3).where(db.Breeding.id == self.target.id).execute()
        form = {"id": self.target.id, "birth_date": "2021-02-01", "litter_size6w": 5}
        with self._committed_before_the_lock(litter_size=4):
            result = da.update_breeding(form, self.owner.uuid)
        row = db.Breeding.get_by_id(self.target.id)
        self.assertEqual(
            (result, row.litter_size, row.litter_size6w),
            ({"status": "error", "message": da.LITTER_SIZE6W_ABOVE_BORN}, 4, 3),
        )

    def test_string_echo_of_survivors_keeps_sizes_corrected_before_lock(self):
        """Legacy echoes litter_size6w as "3". Compared raw it counted as a change, went onto the
        locked row and turned B's committed correction (2, 2) into (2, 3), past the size check."""
        db.Breeding.update(litter_size=5, litter_size6w=3).where(db.Breeding.id == self.target.id).execute()
        form = {"id": self.target.id, "birth_date": "2021-02-01", "litter_size6w": "3", "breed_notes": "notis"}
        with self._committed_before_the_lock(litter_size=2, litter_size6w=2):
            result = da.update_breeding(form, self.owner.uuid)
        row = db.Breeding.get_by_id(self.target.id)
        self.assertEqual(
            (result, row.litter_size, row.litter_size6w, row.breed_notes), ({"status": "success"}, 2, 2, "notis")
        )


class TestBreedingReassignedBeforeTheLock(DatabaseTest):
    """The individual's breeding changes between the helper's read and its lock → 409, retry."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.ind = self.individuals[0]
        self.other = self.breeding[2]  # another litter the concurrent request moves the rabbit into

    @contextmanager
    def _moved_after_breeding_lock(self):
        original = ic.lock_breedings

        def move_then_return(ids):
            locked = original(ids)
            db.Individual.update(breeding=self.other.id).where(db.Individual.id == self.ind.id).execute()
            return locked

        with mock.patch.object(ic, "lock_breedings", side_effect=move_then_return):
            yield

    def _rows(self):
        return db.HerdTracking.select().where(db.HerdTracking.individual == self.ind.id).count()

    def test_legacy_update_is_a_409_and_writes_nothing(self):
        before = self._rows()
        form = {"id": self.ind.id, "number": self.ind.number, "herd": "G1", "yearly_report_date": "2022-01-15"}
        with self._moved_after_breeding_lock():
            result = da.update_individual(form, self.manager.uuid)
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(result.get("problem_status"), 409, result)
        self.assertEqual(result["message"], "Kaninen ändrades samtidigt. Försök igen.")
        self.assertEqual(self._rows(), before)

    @unittest.skipUnless(_USE_POSTGRES, "row locks need PostgreSQL")
    def test_v2_patch_is_a_409_without_a_breeding_lock_after_the_individual(self):
        before = self._rows()
        self.client.post("/api/login", json={"username": "man", "password": "pass"})
        with self._moved_after_breeding_lock(), capture_sql() as statements:
            response = self.client.patch(
                f"/api/individual/{self.ind.number}", json={"herd": "G1", "yearly_report_date": "2022-01-15"}
            )
        self.assertEqual(response.status_code, 409, response.get_data(as_text=True))
        self.assertEqual(self._rows(), before)
        locks = [sql for sql, _ in statements if _is_lock(sql)]
        first_ind = next(i for i, sql in enumerate(locks) if 'FROM "individual"' in sql)
        self.assertFalse(
            any('FROM "breeding"' in sql for sql in locks[first_ind:]), "no Breeding lock after the Individual lock"
        )


@unittest.skipUnless(_USE_POSTGRES, "row locks need PostgreSQL")
class TestRenumberLockOrder(DatabaseTest):
    """Renumbering locks Breedings, then ALL affected individuals in one ascending call."""

    def test_individuals_locked_ascending_before_the_first_update(self):
        from utils.individual_number_v2 import renumber_litters

        herd = self.herds[0]
        may = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 5, 1), litter_number=1, litter_size=3)
        feb = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 2, 1), litter_number=2, litter_size=3)
        low = db.Individual.create(number="G1-3011", origin_herd=herd, breeding=may, sex="female")
        high = db.Individual.create(number="G1-3021", origin_herd=herd, breeding=feb, sex="female")
        with capture_sql() as statements:
            renumber_litters(herd.herd, 2030, confirm=True)
        first_update = _first(statements, lambda sql: sql.startswith('UPDATE "individual"'))
        locks = [(i, sql, params) for i, (sql, params) in enumerate(statements) if _is_lock(sql)]
        self.assertIn('FROM "breeding"', locks[0][1], "Breeding locks first")
        ind_locks = [(i, params) for i, sql, params in locks if 'FROM "individual"' in sql]
        self.assertTrue(ind_locks, "the renumbered individuals are never locked")
        index, params = ind_locks[0]
        self.assertEqual(params, sorted([low.id, high.id]), "one ascending call over every affected individual")
        self.assertLess(index, first_update)
        self.assertEqual(db.Individual.get_by_id(high.id).number, "G1-3011")


class TestCanonicalBreedingId(DatabaseTest):
    """A target breeding id the ORM would coerce is canonicalised before locking, or refused."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.ind = self.individuals[0]  # breeding[0]
        self.target = self.breeding[2]  # same parents, another litter

    def _form(self, breeding):
        return {"id": self.ind.id, "number": self.ind.number, "herd": "G1", "breeding": breeding}

    @unittest.skipUnless(_USE_POSTGRES, "row locks need PostgreSQL")
    def test_float_and_padded_ids_lock_the_target_breeding(self):
        for raw in (float(self.target.id), f" {self.target.id} "):
            db.Individual.update(breeding=self.breeding[0].id).where(db.Individual.id == self.ind.id).execute()
            with self.subTest(raw=raw):
                with capture_sql() as statements:
                    da.update_individual(self._form(raw), self.manager.uuid)
                locks = [params for sql, params in statements if _is_lock(sql) and 'FROM "breeding"' in sql]
                self.assertIn(self.target.id, {p for params in locks for p in params}, raw)

    def test_non_integral_id_is_refused(self):
        result = da.update_individual(self._form(self.target.id + 0.5), self.manager.uuid)
        self.assertEqual(result["status"], "error", result)
        self.assertIn("Unknown breeding event", result["message"])
        self.assertEqual(db.Individual.get_by_id(self.ind.id).breeding_id, self.breeding[0].id)

    def test_v2_non_integral_id_is_a_400(self):
        self.client.post("/api/login", json={"username": "man", "password": "pass"})
        response = self.client.patch(f"/api/individual/{self.ind.number}", json={"breeding": self.target.id + 0.5})
        self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        self.assertEqual(db.Individual.get_by_id(self.ind.id).breeding_id, self.breeding[0].id)


class TestBirthRegistrationLocksTheParents(SaleBase):
    """register_birth re-checks the doe's ownership under the Breeding + parent locks."""

    def setUp(self):
        super().setUp()
        self.buck = make_individual(self.g1, "G1-2404", date(2024, 1, 1), sex="male")
        ht_row("BIRTH", individual=self.buck, herd=self.g1, herd_tracking_date=date(2024, 1, 1))
        # Mated at the seller's before the sale: the buyer bought her pregnant.
        self.litter = db.Breeding.create(
            breed_date=self.today - timedelta(days=31),
            mother=self.rabbit,
            father=self.buck,
            breeding_herd_id=self.g1,
        )
        self.form = {"id": self.litter.id, "date": str(self.today), "litter_size": 3}

    def test_buyer_birth_refused_after_the_seller_undid_the_sale(self):
        with self._seller_undoes_at_lock() as state:
            result = da.register_birth(self.form, self.buyer.uuid)
        self.assertTrue(state["flipped"], "register_birth never locked the doe")
        self.assertEqual(result["status"], "error", result)
        self.assertIn("Honan tillhörde inte", result["message"])
        self.assertIsNone(db.Breeding.get_by_id(self.litter.id).birth_date, "nothing written")

    @unittest.skipUnless(_USE_POSTGRES, "row locks need PostgreSQL")
    def test_breeding_then_parents_ascending_before_the_write(self):
        with capture_sql() as statements:
            result = da.register_birth(self.form, self.buyer.uuid)
        self.assertEqual(result["status"], "success", result)
        locks = [(i, sql, params) for i, (sql, params) in enumerate(statements) if _is_lock(sql)]
        self.assertIn('FROM "breeding"', locks[0][1], "Breeding locks first")
        ind_locks = [(i, params) for i, sql, params in locks if 'FROM "individual"' in sql]
        self.assertTrue(ind_locks, "the parents are never locked")
        self.assertEqual(ind_locks[0][1], sorted([self.rabbit.id, self.buck.id]))
        write = _first(statements, lambda sql: sql.startswith('UPDATE "breeding"'))
        self.assertLess(ind_locks[0][0], write)


class TestBirthRegistrationDecidesOnTheLockedLitter(DatabaseTest):
    """Final review (24a65b0): register_birth decided on its unlocked read and saved that whole row. A change
    committed before its lock was written back, among them an admin's move of the litter to another genebank,
    and the manager's genebank bypass was decided on the old genebank."""

    def test_changes_committed_before_the_lock_are_kept(self):
        real = da.validate_breeding_dates  # runs on the unlocked read, before the lock
        for month, name, concurrent, expected in (
            (3, "notes corrected", {"breed_notes": "rättad"}, {"status": "success"}),
            (
                7,
                "litter moved to M3",
                {"breeding_herd_id": self.herds[2], "breed_notes": "rättad"},
                {"status": "error", "message": "Kullen ändrades samtidigt. Försök igen."},
            ),
        ):
            with self.subTest(name):
                litter = db.Breeding.create(
                    breed_date=date(2022, month, 1),
                    mother=self.parents[0],
                    father=self.parents[1],
                    breeding_herd_id=self.herds[0],
                )

                def committed_meanwhile(*args, litter=litter, concurrent=concurrent, **kwargs):
                    db.Breeding.update(**concurrent).where(db.Breeding.id == litter.id).execute()
                    return real(*args, **kwargs)

                form = {"id": litter.id, "date": f"2022-{month + 1:02d}-01", "litter_size": 3}
                with mock.patch.object(da, "validate_breeding_dates", side_effect=committed_meanwhile):
                    result = da.register_birth(form, self.manager.uuid)
                row = db.Breeding.get_by_id(litter.id)
                herd = concurrent.get("breeding_herd_id", self.herds[0]).herd
                self.assertEqual(
                    ({k: result.get(k) for k in expected}, row.breeding_herd_id.herd, row.breed_notes),
                    (expected, herd, "rättad"),
                )
                self.assertEqual(row.birth_date is not None, expected["status"] == "success")
