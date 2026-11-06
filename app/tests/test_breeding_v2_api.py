"""Tests for litter number management API endpoints.

isort:skip_file
"""

import os
import shutil
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.settings as settings  # noqa: E402
from herdbook import APP, limiter  # noqa: E402
from moto import mock_aws  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402
from tests.ht_helpers import ht_row  # noqa: E402

limiter.enabled = False

_USE_POSTGRES = bool(os.getenv("POSTGRES_HOST")) and bool(os.getenv("POSTGRES_DB"))


class TestCheckLitterOrder(DatabaseTest):
    """Tests for GET /api/v2/breeding/check-order."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post(
            "/api/login",
            json={"username": username, "password": password},
        )

    def test_returns_consistent_when_ordered(self):
        """GET /api/v2/breeding/check-order returns consistent=true when in order."""
        herd = self.herds[0]
        db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 2, 1),
            litter_number=1,
            litter_size=3,
        )
        db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 5, 1),
            litter_number=2,
            litter_size=4,
        )
        self._login()
        response = self.client.get(f"/api/v2/breeding/check-order?herd={herd.herd}&year=2030")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["consistent"])

    def test_detects_inconsistent_order(self):
        """GET /api/v2/breeding/check-order detects conflicts."""
        herd = self.herds[0]
        db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 5, 1),
            litter_number=1,
            litter_size=3,
        )
        db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 2, 1),
            litter_number=2,
            litter_size=4,
        )
        self._login()
        response = self.client.get(f"/api/v2/breeding/check-order?herd={herd.herd}&year=2030")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertFalse(data["consistent"])
        self.assertEqual(len(data["conflicts"]), 2)

    def test_requires_authentication(self):
        """Unauthenticated request returns 401."""
        response = self.client.get("/api/v2/breeding/check-order?herd=G1&year=2030")
        self.assertEqual(response.status_code, 401)

    def test_missing_params_returns_400(self):
        """Missing required params returns 400."""
        self._login()
        response = self.client.get("/api/v2/breeding/check-order")
        self.assertEqual(response.status_code, 400)


class TestRenumberLitters(DatabaseTest):
    """Tests for POST /api/v2/breeding/renumber."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post(
            "/api/login",
            json={"username": username, "password": password},
        )

    def test_dry_run_returns_preview(self):
        """POST without confirm returns preview."""
        herd = self.herds[0]
        db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 5, 1),
            litter_number=1,
            litter_size=3,
        )
        db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 2, 1),
            litter_number=2,
            litter_size=4,
        )
        self._login()
        response = self.client.post(
            "/api/v2/breeding/renumber",
            json={"herd_id": herd.herd, "year": 2030},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("changes", data)
        self.assertTrue(len(data["changes"]) > 0)
        # Verify data wasn't changed (dry run)
        b1 = (
            db.Breeding.select()
            .where(
                db.Breeding.breeding_herd_id == herd,
                db.Breeding.birth_date == date(2030, 5, 1),
            )
            .get()
        )
        self.assertEqual(b1.litter_number, 1)

    def test_confirm_applies_changes(self):
        """POST with confirm=true applies renumbering."""
        herd = self.herds[0]
        db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 5, 1),
            litter_number=1,
            litter_size=3,
        )
        db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 2, 1),
            litter_number=2,
            litter_size=4,
        )
        self._login()
        response = self.client.post(
            "/api/v2/breeding/renumber",
            json={"herd_id": herd.herd, "year": 2030, "confirm": True},
        )
        self.assertEqual(response.status_code, 200)
        # Verify data was changed
        b1 = (
            db.Breeding.select()
            .where(
                db.Breeding.breeding_herd_id == herd,
                db.Breeding.birth_date == date(2030, 5, 1),
            )
            .get()
        )
        self.assertEqual(b1.litter_number, 2)  # May is second

    def test_confirm_invalidates_genetics_caches(self):
        """Renumbering changes individual numbers via bulk updates, so the
        genetics caches for the genebank are invalidated; a dry run does not."""
        herd = self.herds[0]
        db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 5, 1), litter_number=1, litter_size=3)
        db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 2, 1), litter_number=2, litter_size=4)
        self._login()
        with patch("utils.cache_invalidation.trigger_invalidation") as invalidate:
            response = self.client.post("/api/v2/breeding/renumber", json={"herd_id": herd.herd, "year": 2030})
            self.assertEqual(response.status_code, 200)
            invalidate.assert_not_called()

            response = self.client.post(
                "/api/v2/breeding/renumber", json={"herd_id": herd.herd, "year": 2030, "confirm": True}
            )
            self.assertEqual(response.status_code, 200)
            invalidate.assert_called_once_with(herd.genebank_id)

    def test_requires_authentication(self):
        """Unauthenticated request returns 401."""
        response = self.client.post(
            "/api/v2/breeding/renumber",
            json={"herd_id": "G1", "year": 2030},
        )
        self.assertEqual(response.status_code, 401)

    def test_renumber_invalid_year_string_returns_400(self):
        """G6: non-numeric year string must return 400, not a broken comparison."""
        herd = self.herds[0]
        self._login()
        response = self.client.post(
            "/api/v2/breeding/renumber",
            json={"herd_id": herd.herd, "year": "notanumber"},
        )
        self.assertEqual(response.status_code, 400)

    def test_renumber_numeric_string_year_is_accepted(self):
        """G6: year supplied as a numeric string (e.g. "2030") is cast and accepted."""
        herd = self.herds[0]
        db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 5, 1),
            litter_number=1,
            litter_size=3,
        )
        self._login()
        response = self.client.post(
            "/api/v2/breeding/renumber",
            json={"herd_id": herd.herd, "year": "2030"},
        )
        self.assertEqual(response.status_code, 200)

    def test_renumber_non_string_herd_id_returns_400(self):
        """A non-string herd_id must return 400."""
        self._login()
        response = self.client.post(
            "/api/v2/breeding/renumber",
            json={"herd_id": 123, "year": 2030},
        )
        self.assertEqual(response.status_code, 400)

    def test_renumber_target_number_held_outside_change_set_returns_409(self):
        """A verbatim-imported Individual occupying a target number → 409, not 500."""
        herd = self.herds[0]
        b1 = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 5, 1), litter_number=1, litter_size=3)
        db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 2, 1), litter_number=2, litter_size=3)
        db.Individual.create(number=f"{herd.herd}-3011", origin_herd=herd, breeding=b1, sex="female")
        self._login()
        # A verbatim number in another year (as legacy imports left them; the import route now refuses it)
        # claims the number the renumber would assign.
        other = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2029, 6, 1), litter_number=1)
        db.Individual.create(number=f"{herd.herd}-3021", origin_herd=herd, breeding=other)
        response = self.client.post(
            "/api/v2/breeding/renumber",
            json={"herd_id": herd.herd, "year": 2030, "confirm": True},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["title"], "Conflict")
        # Rolled back: nothing was renumbered.
        self.assertEqual(db.Breeding.get_by_id(b1.id).litter_number, 1)
        self.assertTrue(db.Individual.select().where(db.Individual.number == f"{herd.herd}-3011").exists())

    def test_owner_of_other_herd_denied(self):
        """Owner of a different herd cannot renumber."""
        herd = self.herds[0]  # G1 herd
        db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 5, 1),
            litter_number=1,
            litter_size=3,
        )
        # Login as viewer (not owner/manager of G1)
        self._login(username="spec", password="pass")
        response = self.client.post(
            "/api/v2/breeding/renumber",
            json={"herd_id": herd.herd, "year": 2030, "confirm": True},
        )
        self.assertEqual(response.status_code, 403)


class TestUpdateLitterNumber(DatabaseTest):
    """Tests for PATCH /api/v2/breeding/<id>/litter-number."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post(
            "/api/login",
            json={"username": username, "password": password},
        )

    def test_updates_litter_number(self):
        """PATCH sets litter_number on breeding record."""
        herd = self.herds[0]
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 3, 1),
            litter_number=1,
            litter_size=3,
        )
        self._login()
        response = self.client.patch(
            f"/api/v2/breeding/{b.id}/litter-number",
            json={"litter_number": 5},
        )
        self.assertEqual(response.status_code, 200)
        b_refreshed = db.Breeding.get_by_id(b.id)
        self.assertEqual(b_refreshed.litter_number, 5)

    def test_update_invalidates_genetics_caches(self):
        """Moving a litter number renames its individuals, so genetics caches are invalidated."""
        herd = self.herds[0]
        b = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 3, 1), litter_number=1, litter_size=3)
        self._login()
        with patch("utils.cache_invalidation.trigger_invalidation") as invalidate:
            response = self.client.patch(f"/api/v2/breeding/{b.id}/litter-number", json={"litter_number": 5})
        self.assertEqual(response.status_code, 200)
        invalidate.assert_called_once_with(herd.genebank_id)

    def test_requires_authentication(self):
        """Unauthenticated request returns 401."""
        response = self.client.patch(
            "/api/v2/breeding/1/litter-number",
            json={"litter_number": 1},
        )
        self.assertEqual(response.status_code, 401)

    def test_litter_number_zero_returns_400(self):
        """G5: litter_number=0 must return 400 (must be >= 1)."""
        herd = self.herds[0]
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 3, 1),
            litter_number=1,
            litter_size=3,
        )
        self._login()
        response = self.client.patch(
            f"/api/v2/breeding/{b.id}/litter-number",
            json={"litter_number": 0},
        )
        self.assertEqual(response.status_code, 400)

    def test_litter_number_negative_returns_400(self):
        """G5: negative litter_number must return 400."""
        herd = self.herds[0]
        b = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 3, 1),
            litter_number=1,
            litter_size=3,
        )
        self._login()
        response = self.client.patch(
            f"/api/v2/breeding/{b.id}/litter-number",
            json={"litter_number": -1},
        )
        self.assertEqual(response.status_code, 400)


class TestUpdateLitterNumberCascade(DatabaseTest):
    """Cascade — PATCH litter-number moves Individual numbers with the litter."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post(
            "/api/login",
            json={"username": username, "password": password},
        )

    def _make_breeding(self, litter_number=1):
        return db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2030, 3, 1),
            litter_number=litter_number,
            litter_size=3,
        )

    def test_owner_blocked_when_live_individual_exists(self):
        """Owner PATCH on a breeding with a live registered Individual → 403, rolled back."""
        herd = self.herds[0]
        b = self._make_breeding()
        db.Individual.create(number=f"{herd.herd}-3011", origin_herd=herd, breeding=b, sex="female")
        self._login(username="owner", password="pass")
        response = self.client.patch(f"/api/v2/breeding/{b.id}/litter-number", json={"litter_number": 4})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["title"], "Forbidden")
        self.assertEqual(db.Breeding.get_by_id(b.id).litter_number, 1)
        self.assertTrue(db.Individual.select().where(db.Individual.number == f"{herd.herd}-3011").exists())

    def test_manager_patch_cascades_numbers_including_voided(self):
        """Manager PATCH moves every Individual number old-prefix→new-prefix, voided ones too."""
        herd = self.herds[0]
        b = self._make_breeding()
        db.Individual.create(number=f"{herd.herd}-3011", origin_herd=herd, breeding=b, sex="female")
        db.Individual.create(number=f"{herd.herd}-3012", origin_herd=herd, breeding=b, voided=True)
        self._login(username="man", password="pass")
        response = self.client.patch(f"/api/v2/breeding/{b.id}/litter-number", json={"litter_number": 4})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["litter_number"], 4)
        new_numbers = sorted(ic["new_number"] for ic in data["individuals"])
        self.assertEqual(new_numbers, [f"{herd.herd}-3041", f"{herd.herd}-3042"])
        self.assertEqual(db.Breeding.get_by_id(b.id).litter_number, 4)
        self.assertFalse(db.Individual.get(db.Individual.number == f"{herd.herd}-3041").voided)
        self.assertTrue(db.Individual.get(db.Individual.number == f"{herd.herd}-3042").voided)
        self.assertFalse(db.Individual.select().where(db.Individual.number == f"{herd.herd}-3011").exists())

    @unittest.skipUnless(_USE_POSTGRES, "duplicate guard is the PostgreSQL partial unique index")
    def test_patch_to_occupied_litter_number_returns_409(self):
        """PATCH to a litter_number already used in the same herd/year → 409."""
        self._make_breeding(litter_number=2)
        b = self._make_breeding(litter_number=1)
        self._login()
        response = self.client.patch(f"/api/v2/breeding/{b.id}/litter-number", json={"litter_number": 2})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["title"], "Conflict")
        self.assertEqual(db.Breeding.get_by_id(b.id).litter_number, 1)

    def test_viewer_gets_403(self):
        b = self._make_breeding()
        self._login(username="spec", password="pass")
        response = self.client.patch(f"/api/v2/breeding/{b.id}/litter-number", json={"litter_number": 2})
        self.assertEqual(response.status_code, 403)

    def test_owner_can_update_when_no_individuals(self):
        """Owner happy path: no Individuals in the litter → 200 and number changed."""
        b = self._make_breeding()
        self._login(username="owner", password="pass")
        response = self.client.patch(f"/api/v2/breeding/{b.id}/litter-number", json={"litter_number": 3})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(db.Breeding.get_by_id(b.id).litter_number, 3)


@unittest.skipUnless(_USE_POSTGRES, "idx_breeding_herd_year_litter is PostgreSQL-only")
class TestBreedingSchemaParity(DatabaseTest):
    """Fresh-DB bootstrap must create the litter-number unique index (migration parity)."""

    def test_unique_litter_number_index_exists(self):
        cursor = db.DB_PROXY.execute_sql(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_breeding_herd_year_litter'"
        )
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertIn("CREATE UNIQUE INDEX", row[0])


class TestRenumberAuth(DatabaseTest):
    """Owner may renumber only when no Individuals are affected; else manager/admin."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post(
            "/api/login",
            json={"username": username, "password": password},
        )

    def _out_of_order_litters(self, herd):
        b1 = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 5, 1), litter_number=1, litter_size=3)
        db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 2, 1), litter_number=2, litter_size=3)
        return b1

    def test_owner_allowed_when_no_individuals_affected(self):
        """Owner can renumber a herd/year whose reorder touches no registered Individuals."""
        herd = self.herds[0]  # G1, owned by self.owner
        self._out_of_order_litters(herd)
        self._login(username="owner", password="pass")
        response = self.client.post(
            "/api/v2/breeding/renumber",
            json={"herd_id": herd.herd, "year": 2030, "confirm": True},
        )
        self.assertEqual(response.status_code, 200)

    def test_owner_blocked_when_individual_affected(self):
        """Owner is denied (403) when the reorder would renumber a registered Individual."""
        herd = self.herds[0]
        b1 = self._out_of_order_litters(herd)
        db.Individual.create(number=f"{herd.herd}-3011", origin_herd=herd, breeding=b1, sex="female")
        self._login(username="owner", password="pass")
        response = self.client.post(
            "/api/v2/breeding/renumber",
            json={"herd_id": herd.herd, "year": 2030, "confirm": True},
        )
        self.assertEqual(response.status_code, 403)

    def test_manager_allowed_when_individual_affected(self):
        """Manager of the genebank may renumber even when Individuals are affected."""
        herd = self.herds[0]
        b1 = self._out_of_order_litters(herd)
        db.Individual.create(number=f"{herd.herd}-3011", origin_herd=herd, breeding=b1, sex="female")
        self._login(username="man", password="pass")  # manager of genebank 0
        response = self.client.post(
            "/api/v2/breeding/renumber",
            json={"herd_id": herd.herd, "year": 2030, "confirm": True},
        )
        self.assertEqual(response.status_code, 200)

    def test_owner_blocked_under_lock_leaves_db_unchanged(self):
        """Fix 3: owner is 403 on the confirm path when a live Individual is affected,
        and the renumber is rolled back (Breeding + Individual numbers untouched)."""
        herd = self.herds[0]
        b1 = self._out_of_order_litters(herd)  # b1 = May = litter 1; Feb sibling = litter 2
        db.Individual.create(number=f"{herd.herd}-3011", origin_herd=herd, breeding=b1, sex="female")
        self._login(username="owner", password="pass")
        response = self.client.post(
            "/api/v2/breeding/renumber",
            json={"herd_id": herd.herd, "year": 2030, "confirm": True},
        )
        self.assertEqual(response.status_code, 403)
        # Rolled back: b1 still litter 1 and the Individual keeps its original number.
        self.assertEqual(db.Breeding.get_by_id(b1.id).litter_number, 1)
        self.assertTrue(db.Individual.select().where(db.Individual.number == f"{herd.herd}-3011").exists())


class TestDeleteBreedingV2(DatabaseTest):
    """DELETE /api/v2/breeding/<id> guards (bunny check + null-mother auth)."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post(
            "/api/login",
            json={"username": username, "password": password},
        )

    def test_delete_breeding_with_bunnies_returns_409(self):
        """DELETE returns 409 has_bunnies when the litter has unpromoted Bunny roster rows.

        The v2 litter list shows its delete button whenever the litter has no promoted
        individuals and never asks for confirmation, so the API is the only guard for the
        roster. The legacy route /api/breeding/delete cascades the roster instead (legacy
        audit ruling 4, covered by test_legacy_api_contracts).
        """
        herd = self.herds[0]
        breeding = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 4, 1),
            litter_size=2,
            litter_number=1,
            mother=self.parents[0],
        )
        db.Bunny.create(breeding=breeding, slot_order=1, fate="undecided")
        self._login()
        response = self.client.delete(f"/api/v2/breeding/{breeding.id}")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["title"], "has_bunnies")
        # Breeding and roster must still exist
        self.assertTrue(db.Breeding.select().where(db.Breeding.id == breeding.id).exists())
        self.assertTrue(db.Bunny.select().where(db.Bunny.breeding == breeding.id).exists())

    def test_delete_null_mother_breeding_succeeds(self):
        """DELETE on a null-mother 'utan kull' litter does not raise AttributeError."""
        herd = self.herds[0]
        breeding = db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=date(2030, 4, 1),
            litter_size=0,
            litter_number=1,
            # mother intentionally omitted (null)
        )
        self._login()
        response = self.client.delete(f"/api/v2/breeding/{breeding.id}")
        # Should succeed (204) not crash with 500
        self.assertEqual(response.status_code, 204)
        self.assertFalse(db.Breeding.select().where(db.Breeding.id == breeding.id).exists())


class TestAliveAt6WeeksWithinLitterSize(DatabaseTest):
    """litter_size6w (alive at 6 weeks) can never exceed litter_size (born) where it is written."""

    MESSAGE = "Antal levande vid 6 veckor kan inte vara fler än antal födda."

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.client.post("/api/login", json={"username": "admin", "password": "pass"})

    def test_birth_and_edit_refuse_more_alive_than_born(self):
        unborn = db.Breeding.create(
            breeding_herd_id=self.herds[0], breed_date=date(2025, 1, 1), mother=self.parents[0], father=self.parents[1]
        )
        birth = self.client.post(
            f"/api/v2/breeding/{unborn.id}/birth", json={"date": "2025-02-01", "litter_size": 3, "litter_size6w": 4}
        )
        self.assertEqual((birth.status_code, birth.get_json().get("detail")), (400, self.MESSAGE))
        self.assertIsNone(db.Breeding.get_by_id(unborn.id).birth_date)

        born = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2025, 1, 10),
            litter_number=1,
            litter_size=3,
            litter_size6w=2,
            mother=self.parents[0],
            father=self.parents[1],
        )
        for body in ({"litter_size6w": 4}, {"litter_size": 1}):
            with self.subTest(body):
                edit = self.client.patch(f"/api/v2/breeding/{born.id}", json=body)
                self.assertEqual((edit.status_code, edit.get_json().get("detail")), (400, self.MESSAGE))
        stored = db.Breeding.get_by_id(born.id)
        self.assertEqual((stored.litter_size, stored.litter_size6w), (3, 2))
        # Clearing it stays allowed.
        self.assertEqual(
            self.client.patch(f"/api/v2/breeding/{born.id}", json={"litter_size6w": None}).status_code, 200
        )

    def test_registration_refuses_more_alive_than_born(self):
        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2025, 1, 10),
            litter_number=1,
            litter_size=3,
            mother=self.parents[0],
            father=self.parents[1],
        )
        response = self.client.post(
            "/api/v2/individual",
            json={
                "breeding_id": litter.id,
                "sex": "female",
                "color": "bleighe",
                "litter_size6w": 4,
                "certificate_type": "paper",
                "paper_certificate": "GK-TEST-001",
                "paper_number": "G1-2511",
            },
        )
        self.assertEqual((response.status_code, response.get_json().get("detail")), (400, self.MESSAGE))
        self.assertIsNone(db.Breeding.get_by_id(litter.id).litter_size6w)


class TestRenumberMovesCertificate(DatabaseTest):
    """The v1 certificate lives at S3 ``{number}/certificate.pdf``; renumbering must take it along.

    Every v1 lookup derives the key from the CURRENT number (v2 download fallback, legacy
    issue/update/verify). Before the fix a litter swap served each rabbit the other's certificate
    and a plain renumber made it unreachable.
    """

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        p = patch.object(settings.s3, "endpoint", None)
        p.start()
        self.addCleanup(p.stop)
        m = mock_aws()
        m.start()
        self.addCleanup(m.stop)
        from utils.cert_acess import upload_certificate

        herd = self.herds[0]
        self.herd = herd
        # Litter #1 born AFTER litter #2: renumber swaps them.
        self.b1 = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 3, 1), litter_number=1)
        self.b2 = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 2, 1), litter_number=2)
        self.a = db.Individual.create(
            number=f"{herd.herd}-3011", origin_herd=herd, breeding=self.b1, sex="female", digital_certificate=100001
        )
        self.b = db.Individual.create(
            number=f"{herd.herd}-3021", origin_herd=herd, breeding=self.b2, sex="female", digital_certificate=100002
        )
        upload_certificate(pdf_bytes=b"%PDF-A", ind_number=self.a.number)
        upload_certificate(pdf_bytes=b"%PDF-B", ind_number=self.b.number)
        self.client.post("/api/login", json={"username": "admin", "password": "pass"})

    def test_litter_swap_keeps_each_rabbits_own_certificate(self):
        resp = self.client.post(
            "/api/v2/breeding/renumber", json={"herd_id": self.herd.herd, "year": 2030, "confirm": True}
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        new_a = db.Individual.get_by_id(self.a.id).number
        new_b = db.Individual.get_by_id(self.b.id).number
        self.assertEqual((new_a, new_b), (f"{self.herd.herd}-3021", f"{self.herd.herd}-3011"))
        got_b = self.client.get(f"/api/v2/certificates/{new_b}")
        self.assertEqual(
            got_b.data[:6], b"%PDF-B", f"rabbit B ({new_b}) download -> {got_b.status_code} {got_b.data[:20]!r}"
        )
        got_a = self.client.get(f"/api/v2/certificates/{new_a}")
        self.assertEqual(got_a.data[:6], b"%PDF-A", f"rabbit A ({new_a}) download -> {got_a.status_code}")

    def test_single_litter_renumber_keeps_certificate_reachable(self):
        resp = self.client.patch(f"/api/v2/breeding/{self.b2.id}/litter-number", json={"litter_number": 3})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        new_b = db.Individual.get_by_id(self.b.id).number
        self.assertEqual(new_b, f"{self.herd.herd}-3031")
        got = self.client.get(f"/api/v2/certificates/{new_b}")
        self.assertEqual(
            (got.status_code, got.data[:6]),
            (200, b"%PDF-B"),
            f"rabbit B ({new_b}) download -> {got.status_code} {got.data[:60]!r}",
        )
        from botocore.exceptions import ClientError
        from utils.cert_acess import check_certificate_s3

        with self.assertRaises(ClientError, msg="the old key is removed, so a future G1-3021 cannot inherit it"):
            check_certificate_s3(f"{self.herd.herd}-3021")


class TestRenumberMovesPhoto(DatabaseTest):
    """Photos are stored as kaniner/{number}.jpg (+ _thumb) and both frontends build the URL from the
    CURRENT number. Before the fix a litter swap showed each rabbit the other's photo and a plain renumber a
    broken image.
    """

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        self._upload_dir = tempfile.mkdtemp()
        self._old_env = os.environ.get("UPLOAD_FOLDER")
        os.environ["UPLOAD_FOLDER"] = self._upload_dir
        super().setUp()
        self.kaniner = os.path.join(self._upload_dir, "kaniner")
        os.makedirs(self.kaniner)
        herd = self.herds[0]
        self.herd = herd
        self.b1 = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2026, 3, 1), litter_number=1)
        self.b2 = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2026, 2, 1), litter_number=2)
        self.a = db.Individual.create(
            number=f"{herd.herd}-2611", origin_herd=herd, breeding=self.b1, sex="female", has_photo=True
        )
        self.b = db.Individual.create(
            number=f"{herd.herd}-2621", origin_herd=herd, breeding=self.b2, sex="female", has_photo=True
        )
        for ind, tag in ((self.a, b"photo-of-A"), (self.b, b"photo-of-B")):
            for suffix in (".jpg", "_thumb.jpg"):
                with open(os.path.join(self.kaniner, f"{ind.number}{suffix}"), "wb") as f:
                    f.write(tag + suffix.encode())
        self.client.post("/api/login", json={"username": "admin", "password": "pass"})

    def tearDown(self):
        shutil.rmtree(self._upload_dir, ignore_errors=True)
        if self._old_env is None:
            os.environ.pop("UPLOAD_FOLDER", None)
        else:
            os.environ["UPLOAD_FOLDER"] = self._old_env
        super().tearDown()

    def _photo_at(self, name):
        path = os.path.join(self.kaniner, name)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return f.read()

    def test_litter_swap_keeps_each_rabbits_own_photo(self):
        resp = self.client.post(
            "/api/v2/breeding/renumber", json={"herd_id": self.herd.herd, "year": 2026, "confirm": True}
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        new_b = db.Individual.get_by_id(self.b.id)
        self.assertEqual(new_b.number, f"{self.herd.herd}-2611")
        self.assertTrue(new_b.has_photo)
        got = self._photo_at(f"{new_b.number}.jpg")
        self.assertEqual(got, b"photo-of-B.jpg", f"photo served for rabbit B at {new_b.number}.jpg = {got!r}")
        self.assertEqual(self._photo_at(f"{new_b.number}_thumb.jpg"), b"photo-of-B_thumb.jpg")
        self.assertEqual(self._photo_at(f"{self.herd.herd}-2621.jpg"), b"photo-of-A.jpg")
        self.assertEqual([f for f in os.listdir(self.kaniner) if f.startswith("~")], [])

    def test_single_litter_renumber_keeps_photo_reachable(self):
        resp = self.client.patch(f"/api/v2/breeding/{self.b1.id}/litter-number", json={"litter_number": 5})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        new_a = db.Individual.get_by_id(self.a.id)
        self.assertEqual(new_a.number, f"{self.herd.herd}-2651")
        got = self._photo_at(f"{new_a.number}.jpg")
        self.assertEqual(
            got,
            b"photo-of-A.jpg",
            f"has_photo={new_a.has_photo} but {new_a.number}.jpg = {got!r}; files: {sorted(os.listdir(self.kaniner))}",
        )
        self.assertEqual(self._photo_at(f"{new_a.number}_thumb.jpg"), b"photo-of-A_thumb.jpg")
        self.assertEqual(
            sorted(os.listdir(self.kaniner)),
            sorted(f"{self.herd.herd}-{n}" for n in ("2621.jpg", "2621_thumb.jpg", "2651.jpg", "2651_thumb.jpg")),
        )


class TestUpdateBreedingCertifiedGuard(DatabaseTest):
    """Parents and birth date of a litter with a certified kit are manager-only, as MoveToLitter is."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.b = db.Breeding.create(
            breed_date=date(2023, 1, 15),
            birth_date=date(2023, 2, 15),
            mother=self.parents[0],
            father=self.parents[1],
            litter_size=3,
            litter_size6w=3,
            breeding_herd_id=self.herds[0],
        )

    def _login(self, username):
        self.client.post("/api/login", json={"username": username, "password": "pass"})

    def _kit(self, **kw):
        kit = db.Individual.create(origin_herd=self.herds[0], breeding=self.b, sex="female", **kw)
        ht_row("BIRTH", individual=kit, herd=self.herds[0], herd_tracking_date=self.b.birth_date)
        return kit

    def _patch(self, body):
        return self.client.patch(f"/api/v2/breeding/{self.b.id}", json=body)

    def test_owner_refused_for_birth_date_and_parents_with_certified_kit(self):
        self._kit(number="G1-2101", certificate="C-GUARD-1")
        self._login("owner")
        for body in ({"birth_date": "2023-02-16"}, {"father": self.parents[3].number}):
            response = self._patch(body)
            self.assertEqual(response.status_code, 403, body)
            self.assertEqual(response.get_json()["title"], "Forbidden")
        stored = db.Breeding.get_by_id(self.b.id)
        self.assertEqual((stored.birth_date, stored.father_id), (date(2023, 2, 15), self.parents[1].id))

    def test_owner_refused_with_digital_certificate_via_legacy_envelope(self):
        self._kit(number="G1-2101", digital_certificate=987001)
        result = da.update_breeding({"id": self.b.id, "birth_date": "2023-02-16"}, self.owner.uuid)
        self.assertEqual(result["status"], "error")
        self.assertIn("genbanksansvarig", result["message"])

    def test_manager_may_change_birth_date_with_certified_kit(self):
        self._kit(number="G1-2101", certificate="C-GUARD-1")
        self._login("man")
        response = self._patch({"birth_date": "2023-02-16"})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(db.Breeding.get_by_id(self.b.id).birth_date, date(2023, 2, 16))

    def test_owner_may_change_litter_size_and_echoed_values_with_certified_kit(self):
        self._kit(number="G1-2101", certificate="C-GUARD-1")
        self._login("owner")
        response = self._patch({"litter_size": 4, "birth_date": "2023-02-15", "mother": self.parents[0].number})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(db.Breeding.get_by_id(self.b.id).litter_size, 4)

    def test_owner_may_change_birth_date_with_only_uncertified_kits(self):
        self._kit(number="G1-2101")
        self._login("owner")
        response = self._patch({"birth_date": "2023-02-16"})
        self.assertEqual(response.status_code, 200, response.get_json())
