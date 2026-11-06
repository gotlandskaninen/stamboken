"""Tests for bunny roster CRUD API endpoints.

isort:skip_file
"""

import itertools
import os
import threading
import time
import unittest
from datetime import date, timedelta
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from herdbook import APP, limiter  # noqa: E402
from utils.genetics_service import fetch_pedigree_rows  # noqa: E402
from utils.individual_number_v2 import provisional_number  # noqa: E402

from tests.database_test import _USE_POSTGRES, DatabaseTest  # noqa: E402
from tests.test_certificates_v2_api import CertV2Mixin  # noqa: E402

limiter.enabled = False

# Registration needs a certificate (decision 2026-10-30); paper numbers are unique.
_PAPER_NUMBERS = itertools.count(1)


def paper_number_for(bunny_id):
    """What a correct paper says: the number the promote mints, the kit's provisional one,
    or a number of the right form when there is none (a promote the gates refuse first)."""
    bunny = db.Bunny.get_or_none(db.Bunny.id == bunny_id)
    litter = db.Breeding.get_or_none(db.Breeding.id == bunny.breeding_id) if bunny else None
    return (provisional_number(litter, bunny) if litter else None) or "G1-0011"


def _promote_without_certificate(client, bunny_id):
    """A digital promote whose issuance never ran: registered with no certificate yet.

    Since 2026-10-30 the only uncertified registration left is a failed digital issuance;
    unpromote and the post-commit issuance step start from this state.
    """
    with mock.patch("blueprints.bunny_v2._apply_certificate", return_value=(None, None)):
        return client.post(f"/api/v2/bunny/{bunny_id}/promote", json={"certificate_type": "digital"})


def _make_litter(herd, litter_number=1, litter_size=6):
    return db.Breeding.create(
        breeding_herd_id=herd,
        birth_date=date(2030, 3, 25),
        litter_number=litter_number,
        litter_size=litter_size,
    )


class TestRosterAdd(DatabaseTest):
    """POST /api/v2/breeding/<bid>/bunnies — add bunnies to a litter."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post("/api/login", json={"username": username, "password": password})

    def test_admin_can_add_single_bunny(self):
        b = _make_litter(self.herds[0])
        self._login()
        resp = self.client.post(
            f"/api/v2/breeding/{b.id}/bunnies",
            json={"count": 1, "observed_sex": "female"},
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertIn("bunnies", data)
        self.assertEqual(len(data["bunnies"]), 1)
        self.assertEqual(data["bunnies"][0]["slot_order"], 1)
        self.assertEqual(data["bunnies"][0]["observed_sex"], "female")

    def test_owner_can_add_bunnies(self):
        b = _make_litter(self.herds[0])  # G1, owned by self.owner
        self._login("owner", "pass")
        resp = self.client.post(
            f"/api/v2/breeding/{b.id}/bunnies",
            json={"count": 3},
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(len(data["bunnies"]), 3)
        slots = [bun["slot_order"] for bun in data["bunnies"]]
        self.assertEqual(slots, [1, 2, 3])

    def test_viewer_gets_403(self):
        b = _make_litter(self.herds[0])
        self._login("spec", "pass")
        resp = self.client.post(f"/api/v2/breeding/{b.id}/bunnies", json={"count": 1})
        self.assertEqual(resp.status_code, 403)

    def test_foreign_owner_gets_403(self):
        b = _make_litter(self.herds[0])  # G1
        foreign = da.register_user("foreign_owner", "pass")
        foreign.add_role("owner", self.herds[1].id)  # owns G2, not G1
        self._login("foreign_owner", "pass")
        resp = self.client.post(f"/api/v2/breeding/{b.id}/bunnies", json={"count": 1})
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_gets_401(self):
        b = _make_litter(self.herds[0])
        resp = self.client.post(f"/api/v2/breeding/{b.id}/bunnies", json={"count": 1})
        self.assertEqual(resp.status_code, 401)

    def test_unknown_breeding_returns_404(self):
        self._login()
        resp = self.client.post("/api/v2/breeding/99999/bunnies", json={"count": 1})
        self.assertEqual(resp.status_code, 404)

    def test_default_count_is_one(self):
        b = _make_litter(self.herds[0])
        self._login()
        resp = self.client.post(f"/api/v2/breeding/{b.id}/bunnies", json={})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(resp.get_json()["bunnies"]), 1)

    def test_add_beyond_litter_size_returns_409(self):
        b = _make_litter(self.herds[0], litter_size=3)
        self._login()
        resp = self.client.post(f"/api/v2/breeding/{b.id}/bunnies", json={"count": 3})
        self.assertEqual(resp.status_code, 201)
        resp = self.client.post(f"/api/v2/breeding/{b.id}/bunnies", json={"count": 1})
        self.assertEqual(resp.status_code, 409)
        data = resp.get_json()
        self.assertEqual(data["title"], "litter_full")
        self.assertEqual(data["litter_size"], 3)
        self.assertEqual(data["current_count"], 3)

    def test_add_without_litter_size_is_uncapped(self):
        b = _make_litter(self.herds[0], litter_size=None)
        self._login()
        resp = self.client.post(f"/api/v2/breeding/{b.id}/bunnies", json={"count": 10})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(resp.get_json()["bunnies"]), 10)


class TestRosterGet(DatabaseTest):
    """GET /api/v2/breeding/<bid>/roster — list litter roster."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post("/api/login", json={"username": username, "password": password})

    def test_get_roster_returns_bunnies_with_provisional_number(self):
        b = _make_litter(self.herds[0])
        db.Bunny.create(breeding=b, slot_order=1, observed_sex="female")
        self._login()
        resp = self.client.get(f"/api/v2/breeding/{b.id}/roster")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("roster", data)
        self.assertEqual(len(data["roster"]), 1)
        self.assertIn("provisional_number", data["roster"][0])
        self.assertIsNotNone(data["roster"][0]["provisional_number"])

    def test_get_roster_owner_access(self):
        b = _make_litter(self.herds[0])
        db.Bunny.create(breeding=b, slot_order=1)
        self._login("owner", "pass")
        resp = self.client.get(f"/api/v2/breeding/{b.id}/roster")
        self.assertEqual(resp.status_code, 200)

    def test_get_roster_viewer_403(self):
        b = _make_litter(self.herds[0])
        self._login("spec", "pass")
        resp = self.client.get(f"/api/v2/breeding/{b.id}/roster")
        self.assertEqual(resp.status_code, 403)

    def test_get_roster_unauthenticated_401(self):
        b = _make_litter(self.herds[0])
        resp = self.client.get(f"/api/v2/breeding/{b.id}/roster")
        self.assertEqual(resp.status_code, 401)

    def test_get_roster_unknown_breeding_404(self):
        self._login()
        resp = self.client.get("/api/v2/breeding/99999/roster")
        self.assertEqual(resp.status_code, 404)

    def test_get_roster_linked_bunny_has_no_provisional_number(self):
        b = _make_litter(self.herds[0])
        bunny = db.Bunny.create(breeding=b, slot_order=1)
        ind = db.Individual.create(
            number=f"{self.herds[0].herd}-3061",
            origin_herd=self.herds[0],
            breeding=b,
        )
        bunny.individual = ind
        bunny.fate = "registered"
        bunny.save()
        self._login()
        resp = self.client.get(f"/api/v2/breeding/{b.id}/roster")
        self.assertEqual(resp.status_code, 200)
        entry = resp.get_json()["roster"][0]
        self.assertNotIn("provisional_number", entry)
        self.assertIn("individual", entry)


class TestBunnyPatch(DatabaseTest):
    """PATCH /api/v2/bunny/<id> — update a bunny."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post("/api/login", json={"username": username, "password": password})

    def _make_bunny(self, herd=None, **kwargs):
        herd = herd or self.herds[0]
        b = _make_litter(herd)
        return db.Bunny.create(breeding=b, slot_order=1, **kwargs)

    def test_patch_updates_observed_sex(self):
        bunny = self._make_bunny(observed_sex="female")
        self._login()
        resp = self.client.patch(f"/api/v2/bunny/{bunny.id}", json={"observed_sex": "male"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["observed_sex"], "male")

    def test_patch_updates_notes(self):
        bunny = self._make_bunny()
        self._login()
        resp = self.client.patch(f"/api/v2/bunny/{bunny.id}", json={"notes": "extra white tip"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(db.Bunny.get_by_id(bunny.id).notes, "extra white tip")

    def test_patch_rejects_registered_fate(self):
        bunny = self._make_bunny()
        self._login()
        resp = self.client.patch(f"/api/v2/bunny/{bunny.id}", json={"fate": "registered"})
        self.assertEqual(resp.status_code, 400)

    def test_patch_rejects_unknown_fate(self):
        bunny = self._make_bunny()
        self._login()
        resp = self.client.patch(f"/api/v2/bunny/{bunny.id}", json={"fate": "flew_away"})
        self.assertEqual(resp.status_code, 400)

    def test_patch_accepts_valid_fate(self):
        bunny = self._make_bunny()
        self._login()
        resp = self.client.patch(f"/api/v2/bunny/{bunny.id}", json={"fate": "died"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["fate"], "died")

    def test_patch_owner_can_patch_own_herd(self):
        bunny = self._make_bunny()
        self._login("owner", "pass")
        resp = self.client.patch(f"/api/v2/bunny/{bunny.id}", json={"observed_color": "svart"})
        self.assertEqual(resp.status_code, 200)

    def test_patch_viewer_gets_403(self):
        bunny = self._make_bunny()
        self._login("spec", "pass")
        resp = self.client.patch(f"/api/v2/bunny/{bunny.id}", json={"notes": "test"})
        self.assertEqual(resp.status_code, 403)

    def test_patch_unauthenticated_gets_401(self):
        bunny = self._make_bunny()
        resp = self.client.patch(f"/api/v2/bunny/{bunny.id}", json={"notes": "test"})
        self.assertEqual(resp.status_code, 401)

    def test_patch_unknown_bunny_404(self):
        self._login()
        resp = self.client.patch("/api/v2/bunny/99999", json={"notes": "x"})
        self.assertEqual(resp.status_code, 404)

    def test_patch_fate_on_registered_bunny_returns_409(self):
        """G3: changing fate on a registered (individual-linked) bunny must return 409, not 500."""
        b = _make_litter(self.herds[0])
        bunny = db.Bunny.create(breeding=b, slot_order=1)
        ind = db.Individual.create(
            number=f"{self.herds[0].herd}-3081",
            origin_herd=self.herds[0],
            breeding=b,
        )
        bunny.individual = ind
        bunny.fate = "registered"
        bunny.save()
        self._login()
        resp = self.client.patch(f"/api/v2/bunny/{bunny.id}", json={"fate": "culled"})
        self.assertEqual(resp.status_code, 409)
        bunny_fresh = db.Bunny.get_by_id(bunny.id)
        self.assertEqual(bunny_fresh.fate, "registered")
        self.assertIsNotNone(bunny_fresh.individual_id)

    def test_patch_non_fate_fields_on_registered_bunny_is_allowed(self):
        """G3: non-fate fields (notes) on a registered bunny must still succeed."""
        b = _make_litter(self.herds[0])
        bunny = db.Bunny.create(breeding=b, slot_order=1)
        ind = db.Individual.create(
            number=f"{self.herds[0].herd}-3082",
            origin_herd=self.herds[0],
            breeding=b,
        )
        bunny.individual = ind
        bunny.fate = "registered"
        bunny.save()
        self._login()
        resp = self.client.patch(f"/api/v2/bunny/{bunny.id}", json={"notes": "extra marking"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(db.Bunny.get_by_id(bunny.id).notes, "extra marking")


class TestRosterReorder(DatabaseTest):
    """POST /api/v2/breeding/<bid>/roster/reorder — reorder bunnies."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post("/api/login", json={"username": username, "password": password})

    def test_reorder_changes_slot_order(self):
        b = _make_litter(self.herds[0])
        b1 = db.Bunny.create(breeding=b, slot_order=1)
        b2 = db.Bunny.create(breeding=b, slot_order=2)
        b3 = db.Bunny.create(breeding=b, slot_order=3)
        self._login()
        resp = self.client.post(
            f"/api/v2/breeding/{b.id}/roster/reorder",
            json={"order": [b3.id, b1.id, b2.id]},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("roster", data)
        self.assertEqual(data["roster"][0]["id"], b3.id)
        self.assertEqual(data["roster"][1]["id"], b1.id)
        self.assertEqual(data["roster"][2]["id"], b2.id)

    def test_reorder_wrong_ids_returns_400(self):
        b = _make_litter(self.herds[0])
        b1 = db.Bunny.create(breeding=b, slot_order=1)
        self._login()
        resp = self.client.post(
            f"/api/v2/breeding/{b.id}/roster/reorder",
            json={"order": [b1.id, 99999]},
        )
        self.assertEqual(resp.status_code, 400)

    def test_reorder_viewer_gets_403(self):
        b = _make_litter(self.herds[0])
        db.Bunny.create(breeding=b, slot_order=1)
        self._login("spec", "pass")
        resp = self.client.post(
            f"/api/v2/breeding/{b.id}/roster/reorder",
            json={"order": []},
        )
        self.assertEqual(resp.status_code, 403)

    def test_reorder_unauthenticated_gets_401(self):
        b = _make_litter(self.herds[0])
        resp = self.client.post(
            f"/api/v2/breeding/{b.id}/roster/reorder",
            json={"order": []},
        )
        self.assertEqual(resp.status_code, 401)

    def test_reorder_unknown_breeding_404(self):
        self._login()
        resp = self.client.post("/api/v2/breeding/99999/roster/reorder", json={"order": []})
        self.assertEqual(resp.status_code, 404)

    def test_reorder_duplicate_ids_returns_400(self):
        b = _make_litter(self.herds[0])
        b1 = db.Bunny.create(breeding=b, slot_order=1)
        b2 = db.Bunny.create(breeding=b, slot_order=2)
        self._login()
        resp = self.client.post(
            f"/api/v2/breeding/{b.id}/roster/reorder",
            json={"order": [b1.id, b1.id]},  # duplicate id, b2 missing
        )
        self.assertEqual(resp.status_code, 400)
        # Slot orders must not have changed.
        self.assertEqual(db.Bunny.get_by_id(b1.id).slot_order, 1)
        self.assertEqual(db.Bunny.get_by_id(b2.id).slot_order, 2)


class TestBunnyDelete(DatabaseTest):
    """DELETE /api/v2/bunny/<id> — delete a bunny."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post("/api/login", json={"username": username, "password": password})

    def _make_bunny(self, herd=None):
        herd = herd or self.herds[0]
        b = _make_litter(herd)
        return db.Bunny.create(breeding=b, slot_order=1)

    def test_delete_unlinked_bunny_returns_204(self):
        bunny = self._make_bunny()
        bunny_id = bunny.id
        self._login()
        resp = self.client.delete(f"/api/v2/bunny/{bunny_id}")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(db.Bunny.select().where(db.Bunny.id == bunny_id).exists())

    def test_delete_linked_bunny_returns_409(self):
        b = _make_litter(self.herds[0])
        bunny = db.Bunny.create(breeding=b, slot_order=1)
        ind = db.Individual.create(
            number=f"{self.herds[0].herd}-3071",
            origin_herd=self.herds[0],
            breeding=b,
        )
        bunny.individual = ind
        bunny.fate = "registered"
        bunny.save()
        self._login()
        resp = self.client.delete(f"/api/v2/bunny/{bunny.id}")
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(db.Bunny.select().where(db.Bunny.id == bunny.id).exists())

    def test_delete_owner_can_delete_own_herd(self):
        bunny = self._make_bunny()
        self._login("owner", "pass")
        resp = self.client.delete(f"/api/v2/bunny/{bunny.id}")
        self.assertEqual(resp.status_code, 204)

    def test_delete_viewer_gets_403(self):
        bunny = self._make_bunny()
        self._login("spec", "pass")
        resp = self.client.delete(f"/api/v2/bunny/{bunny.id}")
        self.assertEqual(resp.status_code, 403)

    def test_delete_unauthenticated_gets_401(self):
        bunny = self._make_bunny()
        resp = self.client.delete(f"/api/v2/bunny/{bunny.id}")
        self.assertEqual(resp.status_code, 401)

    def test_delete_unknown_bunny_404(self):
        self._login()
        resp = self.client.delete("/api/v2/bunny/99999")
        self.assertEqual(resp.status_code, 404)


def _old_litter(herd, litter_number=1, litter_size=6, birth_date=date(2025, 1, 10)):
    """A litter old enough (and historical-year) to promote cleanly; all born alive at 6 weeks."""
    return db.Breeding.create(
        breeding_herd_id=herd,
        birth_date=birth_date,
        litter_number=litter_number,
        litter_size=litter_size,
        litter_size6w=litter_size,
    )


class TestBunnyPromote(DatabaseTest):
    """POST /api/v2/bunny/<id>/promote."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post("/api/login", json={"username": username, "password": password})

    def _promote(self, bunny_id, **body):
        if "certificate_type" not in body:
            body.update(certificate_type="paper", paper_certificate=f"PAP-{next(_PAPER_NUMBERS)}")
        if body["certificate_type"] == "paper":
            body.setdefault("paper_number", paper_number_for(bunny_id))
        return self.client.post(f"/api/v2/bunny/{bunny_id}/promote", json=body)

    def test_promote_requires_a_certificate(self):
        """Decision 2026-10-30: no registration without a certificate (paper with its number, or digital)."""
        litter = _old_litter(self.herds[0])
        b = db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female", observed_color="bleighe")
        self._login()
        required = "Intyg krävs: välj pappersintyg eller digitalt intyg."
        for body, detail in (
            ({}, required),
            ({"certificate_type": "none"}, required),
            ({"certificate_type": "paper"}, "Intygsnummer krävs för pappersintyg."),
        ):
            with self.subTest(body=body):
                resp = self.client.post(f"/api/v2/bunny/{b.id}/promote", json=body)
                self.assertEqual((resp.status_code, resp.get_json()["detail"]), (400, detail))
        self.assertFalse(db.Individual.select().where(db.Individual.breeding == litter).exists())
        self.assertIsNone(db.Bunny.get_by_id(b.id).individual_id)

    def test_promote_mints_number_in_slot_order_and_inherits_traits(self):
        litter = _old_litter(self.herds[0])  # G1, born 2025 → "25" suffix
        b1 = db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female", observed_color="bleighe")
        b2 = db.Bunny.create(breeding=litter, slot_order=2, observed_sex="male", observed_color="bleighe")
        self._login()

        resp1 = self._promote(b1.id)
        self.assertEqual(resp1.status_code, 201)
        self.assertEqual(resp1.get_json()["individual"]["number"], "G1-2511")
        created1 = db.Individual.get(db.Individual.number == "G1-2511")
        self.assertEqual(created1.sex, "female")
        self.assertEqual(created1.color.name, "bleighe")  # inherited observed_color

        resp2 = self._promote(b2.id)
        self.assertEqual(resp2.status_code, 201)
        self.assertEqual(resp2.get_json()["individual"]["number"], "G1-2512")
        self.assertEqual(db.Individual.get(db.Individual.number == "G1-2512").sex, "male")

        # The roster reflects the registrations.
        self.assertEqual(db.Bunny.get_by_id(b1.id).fate, "registered")
        self.assertEqual(db.Bunny.get_by_id(b2.id).fate, "registered")

    def test_promote_explicit_sex_color_override_observed(self):
        litter = _old_litter(self.herds[0])
        b = db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female", observed_color="bleighe")
        self._login()
        resp = self._promote(b.id, sex="male", color="stgröhn")
        self.assertEqual(resp.status_code, 201)
        created = db.Individual.get(db.Individual.number == resp.get_json()["individual"]["number"])
        self.assertEqual(created.sex, "male")
        self.assertEqual(created.color.name, "stgröhn")

    def test_promote_without_sex_returns_422(self):
        litter = _old_litter(self.herds[0])
        b = db.Bunny.create(breeding=litter, slot_order=1, observed_color="bleighe")
        self._login()
        resp = self._promote(b.id)  # no observed_sex, no explicit sex
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["title"], "sex_required")

    def test_promote_without_color_returns_422(self):
        litter = _old_litter(self.herds[0])
        b = db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female")
        self._login()
        resp = self._promote(b.id)  # no observed_color, no explicit color
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["title"], "color_required")

    def test_promote_with_unofficial_color_returns_422(self):
        litter = _old_litter(self.herds[0])
        b = db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female")
        self._login()
        resp = self._promote(b.id, color="rymdblå")  # not in the genebank color list
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["title"], "unknown_color")

    def test_promote_litter_size_unset_returns_422_not_500(self):
        litter = _old_litter(self.herds[0], litter_size=None)
        b = db.Bunny.create(breeding=litter, slot_order=1)
        self._login()
        resp = self._promote(b.id)
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["title"], "litter_size_required")

    def test_promote_too_young_returns_422(self):
        litter = _old_litter(self.herds[0], birth_date=date.today() - timedelta(days=10))
        b = db.Bunny.create(breeding=litter, slot_order=1)
        self._login()
        resp = self._promote(b.id)
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["title"], "too_young")

    def test_promote_current_year_conflict_returns_409(self):
        # Two current-year litters whose stored numbers disagree with birth order.
        # Same-day births keep the setup inside the current year on any calendar
        # date (chronological order falls back to Breeding.id), and the age gate
        # is lifted so the order conflict is what trips.
        today = date.today()
        _old_litter(self.herds[0], litter_number=2, birth_date=today)
        litter_b = _old_litter(self.herds[0], litter_number=1, birth_date=today)
        b = db.Bunny.create(breeding=litter_b, slot_order=1)
        self._login()
        with mock.patch("blueprints.bunny_v2.MIN_PROMOTE_AGE_DAYS", 0):
            resp = self._promote(b.id)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["title"], "litter_order_conflict")
        self.assertIn("conflicts", resp.get_json())

    def test_promote_out_of_order_returns_409(self):
        litter = _old_litter(self.herds[0])
        db.Bunny.create(breeding=litter, slot_order=1)
        b2 = db.Bunny.create(breeding=litter, slot_order=2)
        self._login()
        resp = self._promote(b2.id)  # skip the lowest keeper
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["title"], "out_of_order")

    def test_promote_tenth_hits_cap_not_500(self):
        # litter_size6w=10 keeps all ten kits within the certificate rules, so the 9-rabbit cap is what trips.
        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2025, 1, 10),
            litter_number=1,
            litter_size=9,
            litter_size6w=10,
        )
        bunnies = [
            db.Bunny.create(breeding=litter, slot_order=i, observed_sex="female", observed_color="bleighe")
            for i in range(1, 11)
        ]
        self._login()
        for bunny in bunnies[:9]:
            self.assertEqual(self._promote(bunny.id).status_code, 201)
        resp = self._promote(bunnies[9].id)  # 10th exceeds the 9-rabbit ceiling
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["title"], "litter_full")
        self.assertNotEqual(resp.status_code, 500)

    def test_owner_can_promote(self):
        litter = _old_litter(self.herds[0])  # G1 owned by self.owner
        b = db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female", observed_color="bleighe")
        self._login("owner", "pass")
        resp = self._promote(b.id)
        self.assertEqual(resp.status_code, 201)

    def test_promote_viewer_gets_403(self):
        litter = _old_litter(self.herds[0])
        b = db.Bunny.create(breeding=litter, slot_order=1)
        self._login("spec", "pass")
        resp = self._promote(b.id)
        self.assertEqual(resp.status_code, 403)

    def test_promote_unknown_bunny_404(self):
        self._login()
        resp = self._promote(99999)
        self.assertEqual(resp.status_code, 404)

    def test_promote_paper_certificate_sets_filename(self):
        litter = _old_litter(self.herds[0])
        b = db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female", observed_color="bleighe")
        self._login()
        resp = self._promote(b.id, certificate_type="paper", paper_certificate="PAP-700")
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(data["certificate"], "PAP-700")
        self.assertIsNone(data["certificate_error"])
        created = db.Individual.get(db.Individual.number == data["individual"]["number"])
        self.assertEqual(created.certificate, "PAP-700")

    def test_promote_with_a_certificate_respects_the_quota(self):
        """litter_size6w=1 and one certified kit already: a paper or digital promote is refused."""
        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2025, 1, 10),
            litter_number=1,
            litter_size=3,
            litter_size6w=1,
        )
        db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2511", certificate="P1")
        bunny = db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female", observed_color="bleighe")
        self._login()
        for body in ({"certificate_type": "paper", "paper_certificate": "P2"}, {"certificate_type": "digital"}):
            with self.subTest(body["certificate_type"]):
                resp = self._promote(bunny.id, **body)
                live = db.Individual.select().where((db.Individual.breeding == litter) & ~db.Individual.voided)
                self.assertEqual(
                    live.count(), 1, f"promote returned {resp.status_code}; litter_size6w=1 but a second kit registered"
                )
                self.assertEqual(resp.status_code, 422, resp.get_json())
                self.assertEqual(resp.get_json()["title"], "certificate_quota_exceeded")

    def _roster_litter(self, fates, litter_size6w=None):
        """A roster litter past 6 weeks (4 born) with one roster row per fate, in slot order."""
        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2025, 1, 10),
            litter_number=1,
            litter_size=4,
            litter_size6w=litter_size6w,
        )
        bunnies = [
            db.Bunny.create(breeding=litter, slot_order=i, fate=fate, observed_sex="female", observed_color="bleighe")
            for i, fate in enumerate(fates, start=1)
        ]
        return litter, bunnies

    def test_promote_with_a_certificate_requires_litter_size6w(self):
        """A paper or digital certificate needs litter_size6w."""
        litter, bunnies = self._roster_litter(["undecided"] * 3)
        self._login()
        for body in ({"certificate_type": "paper", "paper_certificate": "P2"}, {"certificate_type": "digital"}):
            with self.subTest(body["certificate_type"]):
                resp = self._promote(bunnies[0].id, **body)
                self.assertEqual(
                    (resp.status_code, resp.get_json().get("title")),
                    (422, "litter_size6w_required"),
                    "a certificate was issued in a litter without litter_size6w",
                )
                self.assertFalse(db.Individual.select().where(db.Individual.breeding == litter).exists())

        db.Breeding.update(litter_size6w=3).where(db.Breeding.id == litter.id).execute()
        resp = self._promote(bunnies[0].id, certificate_type="paper", paper_certificate="P2")
        self.assertEqual(resp.status_code, 201, resp.get_json())

    def test_promote_with_a_certificate_refuses_a_roster_out_of_sync(self):
        """More kits alive in the roster than litter_size6w: the breeder must mark the dead ones first."""
        litter, bunnies = self._roster_litter(["undecided", "undecided", "undecided", "died"], litter_size6w=2)
        self._login()
        for body in ({"certificate_type": "paper", "paper_certificate": "P2"}, {"certificate_type": "digital"}):
            with self.subTest(body["certificate_type"]):
                resp = self._promote(bunnies[0].id, **body)
                problem = resp.get_json()
                self.assertEqual(
                    (resp.status_code, problem.get("title"), problem.get("must_mark_dead")),
                    (422, "roster_alive_exceeds_6w", 1),
                    "3 kits alive in the roster but litter_size6w=2, and the certificate was not refused",
                )
                self.assertEqual(
                    problem["detail"],
                    "Kullen har 3 levande i rostern men 2 levande vid 6 veckor. "
                    "Markera 1 kaniner som döda innan intyg kan utfärdas.",
                )
                self.assertFalse(db.Individual.select().where(db.Individual.breeding == litter).exists())
        self.assertEqual([db.Bunny.get_by_id(b.id).fate for b in bunnies[:3]], ["undecided"] * 3, "a kit was marked")

        # The breeder marks the kit that died: the roster agrees and the certificate is issued.
        db.Bunny.update(fate="died").where(db.Bunny.id == bunnies[2].id).execute()
        resp = self._promote(bunnies[0].id, certificate_type="paper", paper_certificate="P2")
        self.assertEqual(resp.status_code, 201, resp.get_json())

    def test_promote_digital_cert_failure_keeps_individual(self):
        # A failing v2 pipeline (signing unavailable) → digital issuance fails
        # ~503. The Individual must stay promoted with NO digital_certificate
        # and no DigitalCertificateV2 row left behind.
        from utils.certificates_v2 import SigningUnavailableError

        litter = _old_litter(self.herds[0])
        b = db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female", observed_color="bleighe")
        self._login()
        # Stub the parentless-litter-hostile data/render steps so signing is what fails.
        with (
            mock.patch("utils.cert_service_v2.get_certificate_data", return_value={}),
            mock.patch("utils.cert_service_v2._generator"),
            mock.patch(
                "utils.cert_service_v2.sign_pdf",
                side_effect=SigningUnavailableError("signering otillgänglig"),
            ),
        ):
            resp = self._promote(b.id, certificate_type="digital")
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertIsNone(data["certificate"])
        self.assertIsNotNone(data["certificate_error"])  # transient problem-detail dict
        created = db.Individual.get(db.Individual.number == data["individual"]["number"])
        self.assertIsNone(created.digital_certificate)
        self.assertIsNone(created.certificate)
        self.assertEqual(
            db.DigitalCertificateV2.select().where(db.DigitalCertificateV2.individual == created).count(), 0
        )
        self.assertEqual(db.Bunny.get_by_id(b.id).fate, "registered")

    def test_promote_digital_cert_signer_failure_persists_with_error_detail(self):
        # A raising signer must not roll back the promotion; the response stays
        # 201 and carries the failure as a transient certificate_error detail.
        litter = _old_litter(self.herds[0])
        b = db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female", observed_color="bleighe")
        self._login()
        # Stub the parentless-litter-hostile data/render steps so the signer is what raises.
        with (
            mock.patch("utils.cert_service_v2.get_certificate_data", return_value={}),
            mock.patch("utils.cert_service_v2._generator"),
            mock.patch("utils.cert_service_v2.sign_pdf", side_effect=RuntimeError("signer_down")),
        ):
            resp = self._promote(b.id, certificate_type="digital")
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertIsNone(data["certificate"])
        self.assertEqual(data["certificate_error"]["status"], 503)
        self.assertIn("signer_down", data["certificate_error"]["detail"])
        created = db.Individual.get(db.Individual.number == data["individual"]["number"])
        self.assertIsNone(created.digital_certificate)
        self.assertEqual(db.Bunny.get_by_id(b.id).fate, "registered")

    def test_promote_duplicate_paper_certificate_returns_409(self):
        # Pre-seed an individual with a known paper certificate number.
        litter = _old_litter(self.herds[0])
        db.Individual.create(
            number=f"{self.herds[0].herd}-4099",
            origin_herd=self.herds[0],
            breeding=litter,
            certificate="CERT-DUPE",
        )
        litter2 = _old_litter(self.herds[0], litter_number=2)
        b = db.Bunny.create(breeding=litter2, slot_order=1, observed_sex="female", observed_color="bleighe")
        self._login()
        resp = self._promote(b.id, certificate_type="paper", paper_certificate="CERT-DUPE")
        self.assertEqual(resp.status_code, 409)
        # Found by the number check before the insert, not by the unique index.
        self.assertEqual(resp.get_json()["title"], "number_conflict")
        self.assertEqual([c["kind"] for c in resp.get_json()["conflicts"]], ["certificate_taken"])


class TestBunnyPromoteDigitalV2(CertV2Mixin, DatabaseTest):
    """Promote with certificate_type=digital issues a real v2 certificate.

    Runs the full pipeline: WeasyPrint render, pyHanko signing (committed
    test creds in certs/), moto S3, and a DigitalCertificateV2 row whose
    token makes the intyg verifiable.
    """

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post("/api/login", json={"username": username, "password": password})

    def _promote(self, bunny_id, **body):
        return self.client.post(f"/api/v2/bunny/{bunny_id}/promote", json=body)

    def test_promote_digital_issues_v2_certificate(self):
        self._start_mock_aws()
        # Unlike _old_litter, this litter has parents so the real
        # get_certificate_data can build the pedigree.
        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2025, 1, 10),
            litter_number=1,
            litter_size=6,
            litter_size6w=6,
            mother=self.individuals[0],
            father=self.individuals[1],
        )
        b = db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female", observed_color="bleighe")
        self._login()
        resp = self._promote(b.id, certificate_type="digital")
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertIsNone(data["certificate_error"])
        created = db.Individual.get(db.Individual.number == data["individual"]["number"])
        self.assertIsNotNone(created.digital_certificate)
        self.assertEqual(data["certificate"], str(created.digital_certificate))
        cert_row = db.DigitalCertificateV2.get(db.DigitalCertificateV2.individual == created)
        self.assertTrue(cert_row.is_current)
        self.assertEqual(len(cert_row.checksum), 64)
        self.assertIsNotNone(cert_row.verification_token)
        self.assertEqual(db.Bunny.get_by_id(b.id).fate, "registered")

    def test_digital_issuance_rechecks_the_quota_under_the_litter_lock(self):
        """The digital certificate is issued after the promote commit; a slot taken meanwhile refuses it."""
        from blueprints.bunny_v2 import _issue_digital_certificate

        self._start_mock_aws()
        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2025, 1, 10),
            litter_number=1,
            litter_size=6,
            litter_size6w=1,
            mother=self.individuals[0],
            father=self.individuals[1],
        )
        b = db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female", observed_color="bleighe")
        self._login()
        resp = _promote_without_certificate(self.client, b.id)
        self.assertEqual(resp.status_code, 201, resp.get_json())
        promoted = db.Individual.get(db.Individual.number == resp.get_json()["individual"]["number"])
        # A concurrent promotion certifies the litter's only 6-week slot first.
        db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2519", certificate="P9")

        with self.assertRaisesRegex(ValueError, "certificate_quota_exceeded"):
            _issue_digital_certificate(promoted, self.admin.uuid)
        self.assertIsNone(db.Individual.get_by_id(promoted.id).digital_certificate)

    def test_digital_issuance_keeps_a_change_committed_after_the_promote(self):
        """Final review: issuance runs after the promote commit with the promote's instance. Saving that whole
        row restored a death recorded in between; only the certificate columns are written."""
        from blueprints.bunny_v2 import _issue_digital_certificate

        self._start_mock_aws()
        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2025, 1, 10),
            litter_number=1,
            litter_size=6,
            litter_size6w=6,
            mother=self.individuals[0],
            father=self.individuals[1],
        )
        b = db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female", observed_color="bleighe")
        self._login()
        resp = _promote_without_certificate(self.client, b.id)
        self.assertEqual(resp.status_code, 201, resp.get_json())
        promoted = db.Individual.get(db.Individual.number == resp.get_json()["individual"]["number"])
        db.Individual.update(death_date=date(2026, 10, 1), death_note="död").where(
            db.Individual.id == promoted.id
        ).execute()

        number = _issue_digital_certificate(promoted, self.admin.uuid)
        stored = db.Individual.get_by_id(promoted.id)
        self.assertEqual(
            (stored.digital_certificate, stored.death_date, stored.death_note), (number, date(2026, 10, 1), "död")
        )

    def test_digital_issuance_is_decided_on_the_locked_rabbit(self):
        """Final review (81bdb0c): issuance after the promote commit decided on its earlier read. An unpromote
        committing while it waited for the litter lock voided the rabbit and freed its slot (voided rabbits are
        not counted), and the rabbit still got a verifiable certificate. The same for a rabbit another
        route certified meanwhile, and for a user without the right to issue."""
        import blueprints.bunny_v2 as bunny_v2

        self._start_mock_aws()
        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2025, 1, 10),
            litter_number=1,
            litter_size=6,
            litter_size6w=6,
            mother=self.individuals[0],
            father=self.individuals[1],
        )
        self._login()
        promoted = []
        for slot in (1, 2, 3):
            b = db.Bunny.create(breeding=litter, slot_order=slot, observed_sex="female", observed_color="bleighe")
            resp = _promote_without_certificate(self.client, b.id)
            self.assertEqual(resp.status_code, 201, resp.get_json())
            promoted.append(db.Individual.get(db.Individual.number == resp.get_json()["individual"]["number"]))
        unpromoted, certified, other = promoted

        def unpromote():
            db.Individual.update(voided=True, is_active=False).where(db.Individual.id == unpromoted.id).execute()
            db.Bunny.update(individual=None, fate="undecided").where(db.Bunny.individual == unpromoted.id).execute()

        def certify():
            db.Individual.update(digital_certificate=100500).where(db.Individual.id == certified.id).execute()

        real_database = bunny_v2.DATABASE
        for individual, user, concurrent, error in (
            (unpromoted, self.admin, unpromote, "individual_lookup_failed"),
            (certified, self.admin, certify, "certificate_exists"),
            (other, self.viewer, lambda: None, "forbidden"),
        ):
            # Commits as issuance opens its transaction: after any read before it, before its locks.
            database = mock.Mock(atomic=lambda concurrent=concurrent: concurrent() or real_database.atomic())
            with self.subTest(error=error), mock.patch.object(bunny_v2, "DATABASE", database):
                with self.assertRaisesRegex(ValueError, error):
                    bunny_v2._issue_digital_certificate(individual, user.uuid)
        self.assertEqual(db.DigitalCertificateV2.select().count(), 0)
        self.assertEqual(db.Individual.get_by_id(certified.id).digital_certificate, 100500)


class TestBunnyBodyValidation(DatabaseTest):
    """Malformed request bodies on the bunny_v2 routes."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post("/api/login", json={"username": username, "password": password})

    def test_add_non_object_body_returns_400(self):
        b = _make_litter(self.herds[0])
        self._login()
        resp = self.client.post(f"/api/v2/breeding/{b.id}/bunnies", json=[1, 2])
        self.assertEqual(resp.status_code, 400)

    def test_reorder_non_object_body_returns_400(self):
        b = _make_litter(self.herds[0])
        self._login()
        resp = self.client.post(f"/api/v2/breeding/{b.id}/roster/reorder", json="x")
        self.assertEqual(resp.status_code, 400)

    def test_promote_non_object_body_returns_400(self):
        litter = _old_litter(self.herds[0])
        bunny = db.Bunny.create(breeding=litter, slot_order=1)
        self._login()
        resp = self.client.post(f"/api/v2/bunny/{bunny.id}/promote", json=[1, 2])
        self.assertEqual(resp.status_code, 400)

    def test_patch_non_object_body_returns_400(self):
        b = _make_litter(self.herds[0])
        bunny = db.Bunny.create(breeding=b, slot_order=1)
        self._login()
        resp = self.client.patch(f"/api/v2/bunny/{bunny.id}", json="x")
        self.assertEqual(resp.status_code, 400)

    def test_patch_unknown_field_is_silently_ignored(self):
        # Pins the documented contract: unknown fields are ignored, not rejected.
        b = _make_litter(self.herds[0])
        bunny = db.Bunny.create(breeding=b, slot_order=1, label="A")
        self._login()
        resp = self.client.patch(f"/api/v2/bunny/{bunny.id}", json={"bunny": "x"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(db.Bunny.get_by_id(bunny.id).label, "A")

    def test_reorder_non_int_elements_returns_400(self):
        b = _make_litter(self.herds[0])
        b1 = db.Bunny.create(breeding=b, slot_order=1)
        b2 = db.Bunny.create(breeding=b, slot_order=2)
        self._login()
        resp = self.client.post(
            f"/api/v2/breeding/{b.id}/roster/reorder",
            json={"order": [[b1.id], [b2.id]]},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(db.Bunny.get_by_id(b1.id).slot_order, 1)
        self.assertEqual(db.Bunny.get_by_id(b2.id).slot_order, 2)

    def test_add_oversized_label_returns_400(self):
        b = _make_litter(self.herds[0])
        self._login()
        resp = self.client.post(f"/api/v2/breeding/{b.id}/bunnies", json={"count": 1, "label": "x" * 41})
        self.assertEqual(resp.status_code, 400)

    def test_patch_oversized_observed_color_returns_400(self):
        b = _make_litter(self.herds[0])
        bunny = db.Bunny.create(breeding=b, slot_order=1)
        self._login()
        resp = self.client.patch(f"/api/v2/bunny/{bunny.id}", json={"observed_color": "x" * 61})
        self.assertEqual(resp.status_code, 400)


class TestBunnyUnpromote(DatabaseTest):
    """POST /api/v2/bunny/<id>/unpromote (manager/admin only)."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        # /api/login is a no-op when already authenticated, so log out first to
        # genuinely switch users within one test client.
        self.client.get("/api/logout")
        return self.client.post("/api/login", json={"username": username, "password": password})

    def _make_promoted(self, paper_certificate=None):
        """Create + promote a bunny (as admin). Returns (litter, bunny, number).

        With a paper number the rabbit is certified; without, it is registered with no certificate yet
        (a failed digital issuance), which unpromote still allows.
        """
        litter = _old_litter(self.herds[0])
        bunny = db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female", observed_color="bleighe")
        self._login("admin", "pass")
        if paper_certificate:
            resp = self.client.post(
                f"/api/v2/bunny/{bunny.id}/promote",
                json={
                    "certificate_type": "paper",
                    "paper_certificate": paper_certificate,
                    "paper_number": paper_number_for(bunny.id),
                },
            )
        else:
            resp = _promote_without_certificate(self.client, bunny.id)
        assert resp.status_code == 201, resp.get_json()
        return litter, bunny, resp.get_json()["individual"]["number"]

    def test_owner_cannot_unpromote_403(self):
        _, bunny, _ = self._make_promoted()
        self._login("owner", "pass")
        resp = self.client.post(f"/api/v2/bunny/{bunny.id}/unpromote")
        self.assertEqual(resp.status_code, 403)
        # Individual remains live (not voided).
        self.assertIsNotNone(db.Bunny.get_by_id(bunny.id).individual_id)

    def test_manager_can_unpromote_soft_voids(self):
        litter, bunny, number = self._make_promoted()
        self._login("man", "pass")
        resp = self.client.post(f"/api/v2/bunny/{bunny.id}/unpromote")
        self.assertEqual(resp.status_code, 200)
        ind = db.Individual.get(db.Individual.number == number)
        self.assertTrue(ind.voided)
        self.assertIsNotNone(ind.voided_at)
        freed = db.Bunny.get_by_id(bunny.id)
        self.assertIsNone(freed.individual_id)
        self.assertEqual(freed.fate, "undecided")

    def test_manager_cannot_unpromote_after_an_admin_genebank_correction(self):
        """Unpromoting voids every row, an admin's move into Mellerud included: then admin only."""
        _, bunny, number = self._make_promoted()
        ind = db.Individual.get(db.Individual.number == number)
        db.HerdTracking.create(
            kind="TRANSFER",
            operation_id="6f0a1c9e-2f43-4a57-9d1e-0b7f4e3b2a12",
            individual=ind,
            from_herd=self.herds[0],
            herd=self.herds[2],
            signature=self.admin,
            herd_tracking_date=date(2025, 6, 1),
            notes="Felregistrerad",
        )
        self._login("man", "pass")
        resp = self.client.post(f"/api/v2/bunny/{bunny.id}/unpromote")
        self.assertEqual(resp.status_code, 403, resp.get_json())
        self.assertFalse(db.Individual.get_by_id(ind.id).voided)
        self.assertEqual(db.Bunny.get_by_id(bunny.id).individual_id, ind.id)
        self._login("admin", "pass")
        self.assertEqual(self.client.post(f"/api/v2/bunny/{bunny.id}/unpromote").status_code, 200)

    def test_admin_can_unpromote(self):
        _, bunny, number = self._make_promoted()  # logged in as admin
        resp = self.client.post(f"/api/v2/bunny/{bunny.id}/unpromote")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(db.Individual.get(db.Individual.number == number).voided)

    def test_unpromote_voids_herd_tracking_instead_of_deleting(self):
        _, bunny, number = self._make_promoted()
        self._login("man", "pass")
        resp = self.client.post(f"/api/v2/bunny/{bunny.id}/unpromote")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        ind = db.Individual.get(db.Individual.number == number)
        rows = list(db.HerdTracking.select().where(db.HerdTracking.individual == ind))
        self.assertGreaterEqual(len(rows), 1, "rows are kept, not deleted")
        self.assertTrue(all(r.voided_at is not None for r in rows))
        self.assertEqual({r.voided_reason for r in rows}, {"avpromoverad"})
        self.assertEqual({r.voided_by_user_id for r in rows}, {self.manager.id})
        self.assertEqual(len({r.voided_operation_id for r in rows}), 1, "one operation voids them all")

    def test_unpromote_voids_and_hides_from_listings(self):
        _, bunny, number = self._make_promoted()
        herd_id = self.herds[0].herd
        genebank_id = self.genebanks[0].id
        self.assertIn(number, [i["number"] for i in da.get_herd(herd_id, self.admin.uuid)["individuals"]])
        self.assertIn(number, [i["number"] for i in da.get_individuals(genebank_id, self.admin.uuid)])

        self._login("man", "pass")
        resp = self.client.post(f"/api/v2/bunny/{bunny.id}/unpromote")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()["individual"]
        self.assertTrue(payload["voided"])
        self.assertFalse(payload["is_active"])

        ind = db.Individual.get(db.Individual.number == number)
        self.assertTrue(ind.voided)
        self.assertFalse(ind.is_active)
        self.assertNotIn(number, [i["number"] for i in da.get_herd(herd_id, self.admin.uuid)["individuals"]])
        self.assertNotIn(number, [i["number"] for i in da.get_individuals(genebank_id, self.admin.uuid)])

    def test_unpromote_retires_slot_not_reused(self):
        litter, bunny, number = self._make_promoted()  # G1-2511, slot 1
        self.assertEqual(number, "G1-2511")
        self._login("man", "pass")
        self.assertEqual(self.client.post(f"/api/v2/bunny/{bunny.id}/unpromote").status_code, 200)
        # Re-promote the now-freed bunny: slot 1 is retired, so it gets slot 2.
        self._login("admin", "pass")
        resp = self.client.post(
            f"/api/v2/bunny/{bunny.id}/promote",
            json={"certificate_type": "paper", "paper_certificate": "PAP-901", "paper_number": "G1-2512"},
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.get_json()["individual"]["number"], "G1-2512")

    def test_unpromote_after_certificate_returns_409(self):
        _, bunny, _ = self._make_promoted(paper_certificate="PAP-900")
        self._login("man", "pass")
        resp = self.client.post(f"/api/v2/bunny/{bunny.id}/unpromote")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["title"], "certificate_issued")

    def test_unpromote_unknown_bunny_404(self):
        self._login("man", "pass")
        resp = self.client.post("/api/v2/bunny/99999/unpromote")
        self.assertEqual(resp.status_code, 404)

    def test_unpromote_of_a_parent_is_refused_and_keeps_the_pedigree(self):
        """A voided parent drops out of the genetics pedigree while its kits still name it."""
        _, bunny, number = self._make_promoted()
        doe = db.Individual.get(db.Individual.number == number)
        kid_litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            breed_date=date(2025, 8, 1),
            birth_date=date(2025, 9, 1),
            mother=doe,
            father=self.individuals[1],
        )
        db.Individual.create(origin_herd=self.herds[0], breeding=kid_litter, number="G1-2599")

        self._login("man", "pass")
        resp = self.client.post(f"/api/v2/bunny/{bunny.id}/unpromote")

        rows = fetch_pedigree_rows(self.genebanks[0].id)
        kid = next(r for r in rows if r["number"] == "G1-2599")
        self.assertIn(
            kid["mother_number"],
            {r["number"] for r in rows},
            f"unpromote -> {resp.status_code}: kit G1-2599 names a mother the genetics pedigree no longer has",
        )
        self.assertEqual(resp.status_code, 409, resp.get_json())
        self.assertEqual(resp.get_json()["title"], "has_offspring")

    def test_parent_writers_refuse_an_unpromoted_rabbit(self):
        """register_breeding and a parent change in update_breeding refuse a voided parent."""
        _, bunny, number = self._make_promoted()
        doe_id = db.Individual.get(db.Individual.number == number).id
        self._login("man", "pass")
        self.assertEqual(self.client.post(f"/api/v2/bunny/{bunny.id}/unpromote").status_code, 200)

        self._login("admin", "pass")
        mating = {"mother": number, "father": self.individuals[1].number, "breeding_herd": "G1", "date": "2025-09-01"}
        litter_id = self.breeding[0].id
        observed = {
            "v2_register": self.client.post("/api/v2/breeding", json=mating),
            "legacy_register": self.client.post("/api/breeding", json=mating),
            "v2_update": self.client.patch(f"/api/v2/breeding/{litter_id}", json={"mother": number}),
            "legacy_update": self.client.patch("/api/breeding", json={"id": litter_id, "mother": number}),
        }
        self.assertFalse(
            db.Breeding.select().where(db.Breeding.mother == doe_id).exists(),
            f"a litter names the unpromoted doe: { {k: r.status_code for k, r in observed.items()} }",
        )
        for key in ("v2_register", "v2_update"):
            self.assertEqual(observed[key].status_code, 400, key)
            self.assertEqual(observed[key].get_json()["detail"], "Unknown mother", key)
        for key in ("legacy_register", "legacy_update"):  # the legacy HTTP 200 error envelope (ADR-0006)
            self.assertEqual(observed[key].status_code, 200, key)
            self.assertEqual(observed[key].get_json(), {"status": "error", "message": "Unknown mother"}, key)

    def test_stale_litter_edit_does_not_restore_a_replaced_parent(self):
        """update_breeding reads the litter before its lock; a notes-only edit must not write that stale
        mother back after a concurrent change replaced her and she was unpromoted."""
        litter = self.breeding[0]  # mother G1-1911 (X)
        x_id = litter.mother_id
        y = db.Individual.create(origin_herd=self.herds[0], breeding=self.breeding[2], number="G1-2091", sex="female")
        original, injected = db.User.can_edit, []

        def can_edit(user, identifier):
            if not injected:  # the first call runs after the pre-lock read, before the lock
                injected.append(True)
                db.Breeding.update(mother=y).where(db.Breeding.id == litter.id).execute()
                db.Individual.update(voided=True).where(db.Individual.id == x_id).execute()
            return original(user, identifier)

        with mock.patch.object(db.User, "can_edit", can_edit):
            result = da.update_breeding({"id": litter.id, "birth_notes": "ny anteckning"}, self.admin.uuid)
        self.assertTrue(injected)
        stored = db.Breeding.get_by_id(litter.id)
        self.assertEqual(stored.mother_id, y.id, f"{result}: the edit wrote back the voided mother from its snapshot")
        self.assertEqual((result["status"], stored.birth_notes), ("success", "ny anteckning"))


@unittest.skipUnless(_USE_POSTGRES, "row locks need PostgreSQL")
class TestUnpromoteVsMatingInterleaving(DatabaseTest):
    """Unpromote and register_breeding serialise on the parent's Individual lock, in either order."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        super().setUp()
        litter = _old_litter(self.herds[0])
        self.bunny = db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female", observed_color="bleighe")
        client = APP.test_client(use_cookies=True)
        client.post("/api/login", json={"username": "admin", "password": "pass"})
        resp = _promote_without_certificate(client, self.bunny.id)
        assert resp.status_code == 201, resp.get_json()
        self.doe = db.Individual.get(db.Individual.number == resp.get_json()["individual"]["number"])
        self.mating = {
            "mother": self.doe.number,
            "father": self.individuals[1].number,
            "breeding_herd": "G1",
            "date": "2025-09-01",
        }
        self.results = {}

    def _unpromote(self):
        try:
            client = APP.test_client(use_cookies=True)
            client.post("/api/login", json={"username": "man", "password": "pass"})
            self.results["unpromote"] = client.post(f"/api/v2/bunny/{self.bunny.id}/unpromote")
        finally:
            db.DB_PROXY.close()

    def _register(self):
        try:
            self.results["register"] = da.register_breeding(dict(self.mating), self.admin.uuid)
        finally:
            db.DB_PROXY.close()

    @staticmethod
    def _pause(entered, release, original):
        def paused(*args, **kwargs):
            entered.set()
            release.wait(15)
            return original(*args, **kwargs)

        return paused

    def _wait_for_lock_wait(self, thread):
        """Poll until another backend waits on a lock (no sleep-based guess); False if `thread` ended first."""
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and thread.is_alive():
            waiting = db.DATABASE.execute_sql(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'"
            ).fetchone()[0]
            if waiting:
                return True
            time.sleep(0.05)
        return False

    def _run(self, first, second, entered, release):
        holder = threading.Thread(target=first)
        holder.start()
        self.assertTrue(entered.wait(10), "the first writer never reached its pause point")
        waiter = threading.Thread(target=second)
        waiter.start()
        self.assertTrue(self._wait_for_lock_wait(waiter), "the second writer must queue behind the first one's lock")
        release.set()
        for thread in (holder, waiter):
            thread.join(20)
            self.assertFalse(thread.is_alive(), "a writer is still blocked — lock never released")

    def test_mating_first_then_unpromote_refuses(self):
        entered, release = threading.Event(), threading.Event()
        # register_breeding pauses after it has locked the parents, before its insert.
        with mock.patch.object(
            da, "validate_breeding_dates", side_effect=self._pause(entered, release, da.validate_breeding_dates)
        ):
            self._run(self._register, self._unpromote, entered, release)
        self.assertEqual(self.results["register"]["status"], "success", self.results["register"])
        status = self.results["unpromote"].status_code
        self.assertFalse(
            db.Individual.get_by_id(self.doe.id).voided,
            f"unpromote -> {status}: it voided a doe whose mating committed while it waited",
        )
        self.assertEqual(status, 409)
        self.assertEqual(self.results["unpromote"].get_json()["title"], "has_offspring")

    def test_unpromote_first_then_mating_refuses(self):
        import blueprints.bunny_v2 as bunny_v2

        entered, release = threading.Event(), threading.Event()
        # unpromote pauses after it has locked and voided the doe, before its commit.
        with mock.patch.object(
            bunny_v2,
            "void_all_for_unpromote",
            side_effect=self._pause(entered, release, bunny_v2.void_all_for_unpromote),
        ):
            self._run(self._unpromote, self._register, entered, release)
        self.assertEqual(self.results["unpromote"].status_code, 200, self.results["unpromote"].get_json())
        self.assertFalse(
            db.Breeding.select().where(db.Breeding.mother == self.doe.id).exists(),
            f"register -> {self.results['register']}: a mating names the unpromoted doe",
        )
        self.assertEqual(self.results["register"], {"status": "error", "message": "Unknown mother"})
