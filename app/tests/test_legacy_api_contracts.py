#!/usr/bin/env python3
"""
Legacy API contract tests.

Verifies all legacy frontend API endpoints return correct response shapes
and status codes. These tests ensure API compatibility per ADR-0006.

isort:skip_file
"""

import os
import unittest
from contextlib import contextmanager
from datetime import datetime
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from herdbook import (
    APP,  # noqa: E402
    limiter,  # noqa: E402
)
from moto import mock_aws  # noqa: E402
from utils.legacy_compat import is_legacy_host, legacy_classroom_url  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402
from tests.ht_helpers import ht_row  # noqa: E402


class FlaskTest(DatabaseTest):
    """Base class for HTTP endpoint contract tests."""

    def setUp(self):
        APP.config["TESTING"] = True  # nosemgrep
        APP.config["DEBUG"] = False  # nosemgrep
        APP.config["SESSION_COOKIE_NAME"] = "test_session"
        APP.config["SESSION_PERMANENT"] = False
        limiter.enabled = False
        APP.static_folder = "../frontend/"
        self.app = APP.test_client(use_cookies=True)
        super().setUp()

    def tearDown(self):
        super().tearDown()

    def login(self, context, user):
        """Helper to login a user."""
        context.post("/api/login", json={"username": user.email, "password": "pass"})


# ============================================================================
# Auth group
# ============================================================================


class TestAuthContracts(FlaskTest):
    def test_get_user_unauthenticated_returns_401_error(self):
        response = self.app.get("/api/user")
        self.assertEqual(response.status_code, 401)
        data = response.get_json()
        self.assertEqual(data["status"], "error")
        self.assertIn("message", data)

    def test_get_user_authenticated_returns_frontend_data(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get("/api/user")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            for key in (
                "id",
                "email",
                "username",
                "fullname",
                "validated",
                "is_admin",
                "is_manager",
                "is_owner",
                "profile_picture",
                "google_picture",
                "google_name",
                "google_email",
                "use_google_picture",
                "v2_prod_access",
            ):
                self.assertIn(key, data, f"Missing key: {key}")
            self.assertEqual(data["email"], self.admin.email)

    def test_login_success_returns_user_data(self):
        with self.app as ctx:
            response = ctx.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["email"], self.admin.email)
            self.assertIn("is_admin", data)
            self.assertIn("v2_prod_access", data)

    def test_login_invalid_credentials(self):
        response = self.app.post("/api/login", json={"username": "wrong", "password": "wrong"})
        data = response.get_json()
        self.assertTrue(data is None or data.get("status") == "error")

    def test_login_failure_old_behavior_200_null(self):
        """Inventory row: POST /api/login (user_context.tsx:91) — BROKEN, fixed
        ruling 7 (legacy hosts only).

        OLD: a failed login answered HTTP 200 with a null body. post() never
        special-cases status (user_context.tsx:70-80), so handleLogin() saw a
        truthy body on the NEW 401 error response and reported a successful
        login for a wrong password. FIXED: on a legacy host the old contract is
        restored; every other host keeps the 401, which next-app's
        (auth)/actions.ts relies on — see
        test_login_failure_keeps_401_on_v2_host.
        """
        response = self.app.post(
            "/api/login",
            json={"username": "wrong", "password": "wrong"},
            base_url="https://stamboken.gotlandskaninen.se",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json())

    def test_login_failure_keeps_401_on_v2_host(self):
        """The v2 hosts keep the 401 error body — next-app/(auth)/actions.ts:112 depends
        on it to tell a failed login from a successful one."""
        response = self.app.post(
            "/api/login",
            json={"username": "wrong", "password": "wrong"},
            base_url="https://gotlandskaninen.se",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")

    def test_logout_returns_success(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get("/api/logout")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertIn("message", data)

    def test_available_auth_methods_returns_list(self):
        response = self.app.post("/api/login/available")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsInstance(data, list)

    def test_linked_unauthenticated_returns_null(self):
        response = self.app.get("/api/linked")
        self.assertIn(response.data.decode(), ["null", '"null"'])

    def test_linked_post_unauthenticated_returns_null(self):
        """Inventory row: POST /api/linked (settings.tsx:86) — the actual verb legacy sends."""
        response = self.app.post("/api/linked")
        self.assertIn(response.data.decode(), ["null", '"null"'])

    def test_linked_authenticated(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get("/api/linked")
            self.assertEqual(response.status_code, 200)

    def test_link_unauthenticated_returns_null(self):
        response = self.app.get("/api/link/google")
        self.assertIn(response.data.decode(), ["null", '"null"'])

    def test_link_post_unauthenticated_returns_null(self):
        """Inventory row: POST /api/link/{x} (settings.tsx:117) — the actual verb legacy sends."""
        response = self.app.post("/api/link/google")
        self.assertIn(response.data.decode(), ["null", '"null"'])

    def test_unlink_post_unauthenticated_returns_null(self):
        """Inventory row: POST /api/unlink/{x} (settings.tsx:151) — the actual verb legacy sends."""
        response = self.app.post("/api/unlink/google")
        self.assertIn(response.data.decode(), ["null", '"null"'])

    def test_login_google_unauthenticated_redirects(self):
        """Inventory rows: GET /api/login/google (navigation.tsx:111,276,423)."""
        response = self.app.get("/api/login/google")
        self.assertEqual(response.status_code, 302)
        self.assertIn("Location", response.headers)


# ============================================================================
# Genebanks group
# ============================================================================


class TestGenebankContracts(FlaskTest):
    def test_genebanks_unauthenticated_returns_401(self):
        response = self.app.get("/api/genebanks")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")

    def test_genebanks_returns_list_with_ids(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get("/api/genebanks")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("genebanks", data)
            self.assertGreater(len(data["genebanks"]), 0)
            gb = data["genebanks"][0]
            self.assertIn("id", gb)
            self.assertIn("name", gb)

    def test_genebanks_item_has_herds_field(self):
        """response_fields_used includes genebanks[].herds (data_context.tsx:121)."""
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get("/api/genebanks")
            self.assertEqual(response.status_code, 200)
            genebanks = response.get_json()["genebanks"]
            self.assertGreater(len(genebanks), 0)
            gb = genebanks[0]
            self.assertIn("herds", gb)
            self.assertIsInstance(gb["herds"], list)

    def test_genebank_individuals_returns_list(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get(f"/api/genebank/{self.genebanks[0].id}/individuals")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("individuals", data)
            self.assertIsInstance(data["individuals"], list)

    def test_genebank_individuals_item_shape(self):
        """Field-level pin for GET /api/genebank/{x}/individuals (row: data_context.tsx:134)."""
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get(f"/api/genebank/{self.genebanks[0].id}/individuals")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertGreater(len(data["individuals"]), 0)
            ind = data["individuals"][0]
            for key in ("number", "sex", "name"):
                self.assertIn(key, ind, f"Missing key: {key}")
            self.assertIsInstance(ind["number"], str)

    def test_genebank_individuals_unauthenticated_returns_401(self):
        response = self.app.get(f"/api/genebank/{self.genebanks[0].id}/individuals")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")

    def test_colors_returns_dict_by_genebank(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get("/api/colors")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIsInstance(data, dict)
            self.assertGreater(len(data), 0)
            # Each value is a list of {id, name, comment} objects
            first_gb = next(iter(data.values()))
            self.assertIsInstance(first_gb, list)
            self.assertGreater(len(first_gb), 0)
            color = first_gb[0]
            self.assertIn("id", color)
            self.assertIn("name", color)

    def test_colors_unauthenticated_returns_401(self):
        response = self.app.get("/api/colors")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")


# ============================================================================
# Herds group
# ============================================================================


class TestHerdContracts(FlaskTest):
    def test_get_herd_unauthenticated_returns_401(self):
        response = self.app.get(f"/api/herd/{self.herds[0].herd}")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")

    def test_get_herd_returns_shape(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get(f"/api/herd/{self.herds[0].herd}")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["herd"], self.herds[0].herd)
            for key in ("herd_name", "individuals", "id"):
                self.assertIn(key, data, f"Missing key: {key}")

    def test_get_herd_individuals_item_shape(self):
        """Field-level pin for GET /api/herd/{x} — the union of response_fields_used across all
        8 call-site rows (BatchRabbitUpdateForm.tsx, BatchRabbitUpdateStep.tsx x2,
        HerdContactUpdateStep.tsx, YearlyReportForm.tsx, herdForm.tsx, herd_pedigree.tsx,
        herd_view.tsx). Two fields are read by call sites but genuinely absent from BOTH
        backends, so neither is asserted here or anywhere (pre-existing frontend bugs, not
        regressions — see inventory.csv notes on the respective rows):
        - `genebank_id` (HerdContactUpdateStep.tsx:82): old BaseModel.as_dict copies peewee
          field names, and the Herd FK field is `genebank`, not `genebank_id`
          (tmp/theherdbook/app/utils/database.py:125-134,200).
        - `breed` (YearlyReportForm.tsx:82): no `Herd.breed` field exists on either the old
          Herd model (tmp/theherdbook/app/utils/database.py:199-230) or the new one.
        `genebank` — the FK field itself, distinct from `genebank_id` — IS asserted below: it is
        read by YearlyReportForm.tsx:82 and herdForm.tsx:143, and get_herd() itself relies on it
        (app/utils/data_access.py:1307)."""
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get(f"/api/herd/{self.herds[0].herd}")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            for key in (
                "id",
                "name",
                "email",
                "mobile_phone",
                "wire_phone",
                "www",
                "physical_address",
                "herd",
                "herd_name",
                "genebank",
                "bank_account_number",
                "bank_name",
                "is_active",
                "start_date",
                "individuals",
            ):
                self.assertIn(key, data, f"Missing herd-level key: {key}")
            self.assertIsInstance(data["genebank"], int)

            self.assertGreater(len(data["individuals"]), 0)
            ind = next(i for i in data["individuals"] if i["number"] == self.individuals[0].number)
            for key in (
                "id",
                "number",
                "name",
                "birth_date",
                "herd",
                "sex",
                "death_date",
                "death_note",
                "castration_date",
                "certificate",
                "digital_certificate",
                "weights",
                "bodyfat",
                "herd_tracking",
            ):
                self.assertIn(key, ind, f"Missing individuals[] key: {key}")
            self.assertIsInstance(ind["id"], int)

            self.assertGreater(len(ind["weights"]), 0)
            self.assertIn("date", ind["weights"][0])
            self.assertIn("weight", ind["weights"][0])

            self.assertGreater(len(ind["bodyfat"]), 0)
            self.assertIn("date", ind["bodyfat"][0])
            self.assertIn("bodyfat", ind["bodyfat"][0])

            self.assertGreater(len(ind["herd_tracking"]), 0)
            self.assertIn("date", ind["herd_tracking"][0])
            self.assertIn("herd", ind["herd_tracking"][0])

    def test_manage_herd_post_unauthenticated_returns_401(self):
        response = self.app.post("/api/manage/herd", json={"herd": "X99"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")

    def test_manage_herd_post_returns_status(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post(
                "/api/manage/herd",
                json={
                    "herd": "G99",
                    "herd_name": "Testherd",
                    "genebank": self.genebanks[0].id,
                    "is_active": True,
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("status", data)

    def test_manage_herd_patch_returns_status(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.patch(
                "/api/manage/herd",
                json={
                    "id": self.herds[0].id,
                    "herd_name": "Updated name",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("status", response.get_json())


# ============================================================================
# Individuals group
# ============================================================================


class TestIndividualContracts(FlaskTest):
    def test_get_individual_unauthenticated_returns_401(self):
        response = self.app.get(f"/api/individual/{self.individuals[0].number}")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")

    def test_get_individual_returns_shape(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get(f"/api/individual/{self.individuals[0].number}")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["number"], self.individuals[0].number)
            for key in ("name", "sex", "origin_herd", "breeding", "id", "herd_tracking", "inbreeding"):
                self.assertIn(key, data, f"Missing key: {key}")

    def test_post_individual_returns_status(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post(
                "/api/individual",
                json={
                    "number": "G1-9901",
                    "name": "Testkanin",
                    "sex": "male",
                    "herd": self.herds[0].herd,
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("status", data)

    def test_patch_individual_success(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            ind = self.individuals[0]
            response = ctx.patch(
                "/api/individual",
                json={
                    "id": ind.id,
                    "number": ind.number,
                    "name": "Uppdaterad",
                    "herd": ind.origin_herd.herd,
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")

    def test_patch_individual_no_rate_limit_old_behavior(self):
        """Inventory row: PATCH /api/individual (BatchRabbitUpdateForm.tsx:288) — BROKEN,
        fixed.

        OLD: no per-route rate limit, so BatchRabbitUpdateForm's sequential
        per-rabbit PATCH loop (BatchRabbitUpdateForm.tsx:240-292) completed for
        herds with more than 50 rabbits. NEW (before the fix): @limiter.limit("50 per
        minute") 429'd the 51st request mid-batch; patch() parses the HTML 429 body and
        throws. FIXED: the route allows "300 per minute; 2000 per hour", and an app-level
        429 handler answers with JSON (see test_rate_limited_response_is_json).

        Every one of the 51 writes must actually succeed (status 200,
        {"status": "success"} — same shape as test_patch_individual_success),
        and the 51st write's value must be readable back from the database —
        not just a 200 on the final response, which a limiter-induced
        application error could also produce.
        """
        import utils.database as db

        limiter.reset()
        with self.app as ctx:
            self.login(ctx, self.admin)
            limiter.enabled = True
            try:
                ind = self.individuals[0]
                for i in range(51):
                    response = ctx.patch(
                        "/api/individual",
                        json={
                            "id": ind.id,
                            "number": ind.number,
                            "name": f"Batch{i}",
                            "herd": ind.origin_herd.herd,
                        },
                    )
                    # OLD: every sequential PATCH in one submit succeeds, not just the last.
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.get_json()["status"], "success")
            finally:
                limiter.enabled = False
            reloaded = db.Individual.get(db.Individual.id == ind.id)
            self.assertEqual(reloaded.name, "Batch50")

    def _patch_as(self, user, body):
        with self.app as ctx:
            self.login(ctx, user)
            return ctx.patch("/api/individual", json=body)

    def test_patch_whole_get_object_round_trips(self):
        """individual_edit.tsx PATCHes the whole GET object back: the field allowlist keeps that working."""
        with self.app as ctx:
            self.login(ctx, self.owner)
            data = ctx.get(f"/api/individual/{self.individuals[0].number}").get_json()
            data["name"] = "Ekot"
            response = ctx.patch("/api/individual", json=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "success", response.get_json())
        self.assertEqual(db.Individual.get_by_id(self.individuals[0].id).name, "Ekot")

    def test_patch_cannot_void_individual(self):
        """`voided` is not a form field; only manager-only unpromote soft-voids a rabbit.

        The flag is not copied, so the rest of the edit keeps the usual success envelope.
        """
        ind = self.individuals[0]  # G1-2111, paper certificate, owner's herd G1
        response = self._patch_as(
            self.owner,
            {"id": ind.id, "number": ind.number, "herd": "G1", "voided": True, "voided_at": "2021-06-01"},
        )
        self.assertEqual(response.status_code, 200)
        stored = db.Individual.get_by_id(ind.id)
        self.assertEqual((stored.voided, stored.voided_at), (False, None), response.get_json())
        self.assertIsNotNone(da.get_individual(ind.number, self.owner.uuid))

    def test_patch_new_individual_flag_keeps_manager_check(self):
        """A client `new_individual` flag must not skip the manager-only check on a certified rabbit.

        Refused with the error envelope the route already returns for the check without the flag.
        """
        ind = self.individuals[0]  # G1-2111, paper certificate "12"
        body = {"id": ind.id, "number": ind.number, "herd": "G1", "certificate": "999999"}
        plain = self._patch_as(self.owner, body)
        self.assertEqual(plain.get_json(), {"status": "error", "message": "Bara managers kan uppdatera certificate"})
        response = self._patch_as(self.owner, {**body, "new_individual": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), plain.get_json())
        self.assertEqual(db.Individual.get_by_id(ind.id).certificate, "12")

    def test_owner_cannot_rename_certified_individual(self):
        """Renaming a certified rabbit is manager-only, like its other identity fields."""
        ind = self.individuals[0]  # G1-2111, paper certificate "12" (no digital, so no S3 move)
        response = self._patch_as(self.owner, {"id": ind.id, "number": "G2-2611", "herd": "G1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "error", "message": "Bara managers kan uppdatera number"})
        self.assertEqual(db.Individual.get_by_id(ind.id).number, "G1-2111")

    def test_owner_cannot_move_certified_individual_to_another_litter(self):
        """A litter of another birth year renames the rabbit, so a certified rabbit's litter is manager-only."""
        ind = self.individuals[0]  # G1-2111, paper certificate "12", litter born 2021
        later = db.Breeding.create(
            birth_date=datetime(2022, 2, 1),
            mother=self.parents[0],
            father=self.parents[1],
            breeding_herd_id=self.herds[0],
        )
        response = self._patch_as(self.owner, {"id": ind.id, "number": ind.number, "herd": "G1", "breeding": later.id})
        self.assertEqual(response.get_json(), {"status": "error", "message": "Bara managers kan uppdatera breeding"})
        stored = db.Individual.get_by_id(ind.id)
        self.assertEqual((stored.number, stored.breeding_id), ("G1-2111", self.breeding[0].id))

    def test_rename_still_allowed_for_manager_and_uncertified(self):
        """Keeps the legitimate renames: a manager on a certified rabbit, an owner on an uncertified one."""
        for user, ind, number in (
            (self.manager, self.individuals[0], "G1-2118"),
            (self.owner, self.individuals[3], "G1-2119"),
        ):
            response = self._patch_as(user, {"id": ind.id, "number": number, "herd": "G1"})
            self.assertEqual(response.get_json()["status"], "success", response.get_json())
            self.assertEqual(db.Individual.get_by_id(ind.id).number, number)

    def test_patch_cannot_move_individual_into_foreign_litter(self):
        """Legacy gets the route's "Forbidden" envelope; the alias keys are simply not written."""
        ind = self.individuals[3]  # G1-2112, litter breeding[0] (herd G1)
        base = {"id": ind.id, "number": ind.number, "herd": "G1"}
        refused = self._patch_as(self.owner, {**base, "breeding": self.breeding[1].id})
        self.assertEqual(refused.status_code, 200)
        self.assertEqual(refused.get_json(), {"status": "error", "message": "Forbidden"})
        for alias in ({"breeding_id": self.breeding[1].id}, {"origin_herd_id": self.herds[2].id}):
            self._patch_as(self.owner, {**base, **alias})
        stored = db.Individual.get_by_id(ind.id)
        self.assertEqual((stored.breeding_id, stored.origin_herd_id), (self.breeding[0].id, self.herds[0].id))

    def test_patch_cannot_certify_a_rabbit_unpromoted_while_it_waited(self):
        """The void check ran before the lock. An unpromote
        committing while the PATCH waited voided the rabbit and freed its bunny, and the paper certificate
        still landed on the voided row, outside the quota (voided rabbits are not counted)."""
        ind = self.individuals[3]  # G1-2112, uncertified, owner's herd G1
        real_lock = da.lock_individual_for_edit

        def lock_after_an_unpromote(*args, **kwargs):
            db.Individual.update(voided=True, is_active=False).where(db.Individual.id == ind.id).execute()
            return real_lock(*args, **kwargs)

        body = {"id": ind.id, "number": ind.number, "herd": "G1", "certificate": "PAPER-1"}
        with self.app as ctx:
            self.login(ctx, self.owner)
            with mock.patch("utils.individual_commands.lock_individual_for_edit", side_effect=lock_after_an_unpromote):
                response = ctx.patch("/api/individual", json=body)
        self.assertEqual(
            (response.status_code, response.get_json(), db.Individual.get_by_id(ind.id).certificate),
            (200, {"status": "error", "message": "Individual not found"}, None),
        )

    def test_post_paper_certificate_takes_a_litter_slot(self):
        """Legacy create stored a paper certificate without the
        first-certificate rules. A roster litter with litter_size6w=1 and one certified kit took a
        second one."""
        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=datetime(2025, 3, 25),
            litter_number=1,
            litter_size=2,
            litter_size6w=1,
            mother=self.parents[0],
            father=self.parents[1],
        )
        db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2511", certificate="P1")
        body = {
            "herd": "G1",
            "origin_herd": {"herd": "G1"},
            "birth_date": "2025-03-25",
            "breeding": litter.id,
            "number": "G1-2512",
            "certificate": "P2",
        }
        with self.app as ctx:
            self.login(ctx, self.owner)
            response = ctx.post("/api/individual", json=body)
        self.assertEqual(
            (response.status_code, response.get_json()),
            (200, {"status": "error", "message": "certificate_quota_exceeded"}),
        )
        self.assertFalse(db.Individual.select().where(db.Individual.number == "G1-2512").exists())

    def test_non_text_paper_number_takes_the_first_certificate_rules(self):
        """JSON 0 or false passed the first-certificate checks as "no certificate"
        and was stored as "0" or "False", which every route then treats as a paper certificate. Here the
        roster litter has no litter_size6w, so a first certificate is refused on create and on PATCH."""
        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=datetime(2025, 3, 25),
            litter_number=1,
            litter_size=2,
            mother=self.parents[0],
            father=self.parents[1],
        )
        kit = db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2511")
        body = {"herd": "G1", "origin_herd": {"herd": "G1"}, "birth_date": "2025-03-25", "breeding": litter.id}
        with self.app as ctx:
            self.login(ctx, self.owner)
            created = ctx.post("/api/individual", json={**body, "number": "G1-2512", "certificate": False})
            patched = ctx.patch(
                "/api/individual", json={"id": kit.id, "number": kit.number, "herd": "G1", "certificate": 0}
            )
        refused = {"status": "error", "message": "litter_size6w_required"}
        self.assertEqual((created.get_json(), patched.get_json()), (refused, refused))
        self.assertFalse(db.Individual.select().where(db.Individual.number == "G1-2512").exists())
        self.assertIsNone(db.Individual.get_by_id(kit.id).certificate)

    def test_post_does_not_adopt_a_rabbit_created_after_the_number_check(self):
        """form_to_individual looks the number up again. A rabbit
        promoted and unpromoted with that number after the duplicate check was updated in place, and a POST
        without a litter put a paper certificate on the voided row without any litter rule."""
        real = da.form_to_individual
        created = []

        def promoted_and_unpromoted_meanwhile(form, *args, **kwargs):
            created.append(
                db.Individual.create(
                    origin_herd=self.herds[0], breeding=self.breeding[0], number=form["number"], voided=True
                )
            )
            return real(form, *args, **kwargs)

        body = {"herd": "G1", "origin_herd": {"herd": "G1"}, "birth_date": "2021-02-01", "number": "G1-2193"}
        with self.app as ctx:
            self.login(ctx, self.owner)
            with mock.patch.object(da, "form_to_individual", side_effect=promoted_and_unpromoted_meanwhile):
                response = ctx.post("/api/individual", json={**body, "certificate": "P-ADOPT"})
        self.assertEqual(
            (response.get_json(), db.Individual.get_by_id(created[0].id).certificate),
            ({"status": "error", "message": "Individual number already exists"}, None),
        )

    def test_post_cannot_create_individual_in_other_genebank_litter(self):
        """On create: a new Gotland rabbit cannot join a Mellerud litter or be born in a Mellerud herd
        (same envelope as other refusals).

        A fractional id is refused too: the ORM would truncate 2.5 to litter 2 after the check.
        """
        body = {"herd": "G1", "origin_herd": {"herd": "G1"}, "birth_date": "2021-02-01"}
        foreign, own_litter = self.breeding[1].id, self.breeding[0].id
        with self.app as ctx:
            self.login(ctx, self.owner)
            refused = ctx.post("/api/individual", json={**body, "number": "G1-2198", "breeding": foreign})
            fractional = ctx.post("/api/individual", json={**body, "number": "G1-2196", "breeding": foreign + 0.5})
            origin = ctx.post(
                "/api/individual",
                json={**body, "number": "G1-2195", "breeding": own_litter, "origin_herd": {"herd": "M3"}},
            )
            own = ctx.post("/api/individual", json={**body, "number": "G1-2197", "breeding": own_litter})
        self.assertEqual(refused.get_json(), {"status": "error", "message": "Forbidden"})
        self.assertEqual(fractional.get_json()["status"], "error", fractional.get_json())
        self.assertEqual(origin.get_json(), {"status": "error", "message": "Forbidden"})
        created = db.Individual.select().where(db.Individual.number.in_(["G1-2198", "G1-2196", "G1-2195"]))
        self.assertFalse(created.exists())
        self.assertEqual(own.get_json()["status"], "success", own.get_json())

    def test_patch_cannot_set_digital_certificate(self):
        """A digital number comes only from issuance; a PATCH value is refused with the error envelope."""
        ind = self.individuals[3]  # G1-2112, uncertified, owner's herd G1
        body = {"id": ind.id, "number": ind.number, "herd": "G1", "digital_certificate": 2147483647}
        for user in (self.owner, self.manager):
            response = self._patch_as(user, body)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["status"], "error", response.get_json())
            self.assertIsNone(db.Individual.get_by_id(ind.id).digital_certificate)

    def test_patch_issue_digital_flag_is_ignored(self):
        """`issue_digital` is not a request field; the paper certificate stays and no number is assigned."""
        ind = self.individuals[0]  # G1-2111, paper certificate "12"
        response = self._patch_as(self.owner, {"id": ind.id, "number": ind.number, "herd": "G1", "issue_digital": True})
        self.assertEqual(response.status_code, 200)
        stored = db.Individual.get_by_id(ind.id)
        self.assertEqual((stored.certificate, stored.digital_certificate), ("12", None), response.get_json())

    def _digitally_certified_get(self, user):
        ind = self.individuals[3]
        db.Individual.update(digital_certificate=100001).where(db.Individual.id == ind.id).execute()
        with self.app as ctx:
            self.login(ctx, user)
            return ctx.get(f"/api/individual/{ind.number}").get_json()

    def test_manager_cannot_change_digital_certificate(self):
        """Not even a manager rewrites a digital number by PATCH (legacy's cert field allowed it)."""
        data = self._digitally_certified_get(self.manager)
        response = self._patch_as(self.manager, {**data, "digital_certificate": 100002})
        self.assertEqual(response.get_json()["status"], "error", response.get_json())
        self.assertEqual(db.Individual.get_by_id(self.individuals[3].id).digital_certificate, 100001)

    def test_echo_of_stored_digital_certificate_is_not_a_change(self):
        """The stored digital number echoed back as int or string keeps the whole-object PATCH working."""
        data = self._digitally_certified_get(self.manager)
        for echoed in (100001, "100001"):
            response = self._patch_as(self.manager, {**data, "digital_certificate": echoed, "name": "Eko"})
            self.assertEqual(response.get_json()["status"], "success", (echoed, response.get_json()))
        self.assertEqual(db.Individual.get_by_id(self.individuals[3].id).digital_certificate, 100001)

    def test_owner_cannot_clear_digital_certificate_with_string_none(self):
        """The string "None" is not the stored null; as a paper number it would clear the digital certificate."""
        data = self._digitally_certified_get(self.owner)
        response = self._patch_as(self.owner, {**data, "certificate": "None"})
        self.assertEqual(response.get_json(), {"status": "error", "message": "Bara managers kan uppdatera certificate"})
        stored = db.Individual.get_by_id(self.individuals[3].id)
        self.assertEqual((stored.certificate, stored.digital_certificate), (None, 100001))

    def test_rate_limited_response_is_json(self):
        """globals.md G4/G8: a 429 must be parseable by legacy's fetch helpers.

        They call resp.json() unconditionally, so Flask-Limiter's default HTML body makes
        the whole call throw instead of showing a message. /api/login (5 per minute) is the
        cheapest limiter to trip; the handler is app-level, so it covers every app route.
        """
        limiter.reset()
        limiter.enabled = True
        try:
            for _ in range(5):
                self.app.post("/api/login", json={"username": "finns-inte", "password": "fel"})
            response = self.app.post("/api/login", json={"username": "finns-inte", "password": "fel"})
            self.assertEqual(response.status_code, 429)
            data = response.get_json()
            self.assertEqual(data["status"], "error")
            self.assertEqual(data["message"], "För många förfrågningar, försök igen om en stund")
        finally:
            limiter.enabled = False
            limiter.reset()

    def test_checkindnumber_existing_returns_error(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post("/api/checkindnumber", json={"number": self.individuals[0].number})
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "error")

    def test_checkindnumber_unauthenticated_returns_401(self):
        response = self.app.post("/api/checkindnumber", json={"number": "X"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")

    def test_checkintyg_authenticated(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post("/api/checkintyg", json={"number": self.individuals[0].number})
            self.assertEqual(response.status_code, 200)

    def test_checkintyg_unauthenticated_returns_401(self):
        response = self.app.post("/api/checkintyg", json={"number": "X"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")


# ============================================================================
# Breeding group
# ============================================================================


class TestBreedingContracts(FlaskTest):
    def test_breeding_list_unauthenticated_returns_401(self):
        response = self.app.get(f"/api/breeding/{self.herds[0].herd}")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")

    def test_breeding_list_returns_shape(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get(f"/api/breeding/{self.herds[0].herd}")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("breedings", data)
            self.assertIsInstance(data["breedings"], list)
            self.assertGreater(len(data["breedings"]), 0)

    def test_breeding_list_item_shape(self):
        """Field-level pin for GET /api/breeding/{x} (rows: SelectHerdStep.tsx,
        YearlyReportForm.tsx, breeding_form.tsx, breeding_list.tsx)."""
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get(f"/api/breeding/{self.herds[0].herd}")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertGreater(len(data["breedings"]), 0)
            b = data["breedings"][0]
            for key in (
                "id",
                "mother",
                "father",
                "mother_name",
                "father_name",
                "breed_date",
                "birth_date",
                "litter_size",
                "litter_size6w",
                "breed_notes",
                "birth_notes",
                "breeding_herd",
                "individuals",
            ):
                self.assertIn(key, b, f"Missing key: {key}")
            self.assertIsInstance(b["id"], int)
            # breed_date is always set in fixtures (birth_date is not, for every breeding)
            self.assertRegex(b["breed_date"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertIsInstance(b["individuals"], list)

    def test_breeding_post_herd_search(self):
        """POST /api/breeding/<h_id> searches for matching breeding by birth date."""
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post(
                f"/api/breeding/{self.herds[0].herd}",
                json={
                    "birth_date": "2021-02-01",
                    "father": self.parents[1].number,
                    "mother": self.parents[0].number,
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("breedings", data)

    def test_register_breeding_returns_success_with_id(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post(
                "/api/breeding",
                json={
                    "father": self.individuals[0].number,
                    "mother": self.individuals[1].number,
                    "breeding_herd": self.herds[0].herd,
                    "date": datetime.today().strftime("%Y-%m-%d"),
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertIn("breeding_id", data)
            self.assertIsInstance(data["breeding_id"], int)

    def _doe_bought_pregnant(self):
        """A doe born elsewhere and bought into the owner's herd (herds[0]) in 2022."""
        import utils.database as db

        early_breeding = db.Breeding.create(
            breed_date=datetime(2018, 6, 1),
            birth_date=datetime(2018, 7, 15),
            litter_size=3,
            litter_size6w=3,
            breeding_herd_id=self.herds[1],
        )
        doe = db.Individual.create(origin_herd=self.herds[1], breeding=early_breeding, number="G2-1899")
        ht_row("BIRTH", herd=self.herds[1], individual=doe, herd_tracking_date=datetime(2018, 7, 15))
        ht_row(
            "TRANSFER",
            from_herd=self.herds[1],
            herd=self.herds[0],
            individual=doe,
            herd_tracking_date=datetime(2022, 1, 1),
        )
        return doe

    def test_register_breeding_doe_bought_pregnant(self):
        """Inventory row: POST /api/breeding (breeding_context.tsx:105) — BROKEN, fixed by
        (32/572 Gotland and 2/93 Mellerud breedings since 2024).

        OLD: no temporal ownership check at all. NEW (before the fix): the mother had to have
        been in the breeding herd AT the mating date, so the legacy form — which offers every
        doe currently in the herd — refused a doe bought pregnant. FIXED: in the herd now OR
        at the date is enough.
        """
        import utils.database as db

        doe = self._doe_bought_pregnant()
        with self.app as ctx:
            self.login(ctx, self.owner)
            response = ctx.post(
                "/api/breeding",
                json={
                    "father": self.parents[1].number,
                    "mother": doe.number,
                    "breeding_herd": self.herds[0].herd,
                    "date": "2021-06-01",
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            # The breeding must actually be in the database, with this doe.
            created = db.Breeding.get_by_id(data["breeding_id"])
            self.assertEqual(created.mother_id, doe.id)
            self.assertEqual(created.father_id, self.parents[1].id)
            self.assertEqual(str(created.breed_date)[:10], "2021-06-01")
            self.assertEqual(created.breeding_herd_id.herd, self.herds[0].herd)

    def test_register_birth_doe_bought_pregnant(self):
        """Inventory row: POST /api/birth (breeding_context.tsx:160) — BROKEN, fixed by
        Same predicate as POST /api/breeding, applied to birth_date."""
        import utils.database as db

        doe = self._doe_bought_pregnant()
        breeding = db.Breeding.create(
            breed_date=datetime(2021, 6, 1),
            mother=doe,
            father=self.parents[1],
            breeding_herd_id=self.herds[0],
        )
        with self.app as ctx:
            self.login(ctx, self.owner)
            response = ctx.post(
                "/api/birth",
                json={"id": breeding.id, "date": "2021-07-01", "litter_size": 3},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["status"], "success")
            # The birth must actually be recorded on the row.
            reloaded = db.Breeding.get_by_id(breeding.id)
            self.assertEqual(str(reloaded.birth_date)[:10], "2021-07-01")
            self.assertEqual(reloaded.litter_size, 3)

    def test_update_breeding_returns_success(self):
        """Legacy PATCHes the WHOLE Breeding object, not a field subset.

        `updateBreeding(breeding: Breeding)` sends the object it just read back
        unchanged apart from the edited field (breeding_context.tsx:138-144),
        so every PATCH carries the row's existing dates into
        validate_breeding_dates. Sending only {id, breed_notes} would test a
        payload the legacy frontend never produces.
        """
        with self.app as ctx:
            self.login(ctx, self.admin)
            read = ctx.get(f"/api/breeding/id/{self.breeding[0].id}")
            self.assertEqual(read.status_code, 200)
            breeding = read.get_json()["breeding"]
            if isinstance(breeding, list):
                breeding = breeding[0]
            payload = {k: v for k, v in breeding.items() if k != "individuals"}
            payload["breed_notes"] = "Contract test update"
            response = ctx.patch("/api/breeding", json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["status"], "success")

    def test_update_breeding_echo_of_historically_invalid_row(self):
        """Inventory row: PATCH /api/breeding (breeding_context.tsx:138) — BROKEN, fixed by
        (53 real litters).

        OLD: update_breeding never re-validated the row's stored state, so legacy's
        whole-object PATCH of a litter that predates today's date rules saved fine. NEW
        (before the fix): validate_breeding_dates ran on every PATCH and refused the echo
        with a Swedish message legacy's translate map does not know. FIXED: validation only
        runs when the form actually changes breed_date, birth_date, mother, father or
        litter_size.
        """
        import utils.database as db

        invalid_row = db.Breeding.create(
            breed_date=datetime(2021, 1, 1),
            # 151 days gestation — far outside MIN/MAX, as 53 real litters are
            birth_date=datetime(2021, 6, 1),
            mother=self.parents[0],
            father=self.parents[1],
            litter_size=2,
            litter_size6w=2,
            breeding_herd_id=self.herds[0],
        )
        with self.app as ctx:
            self.login(ctx, self.owner)
            read = ctx.get(f"/api/breeding/id/{invalid_row.id}")
            self.assertEqual(read.status_code, 200)
            breeding = read.get_json()["breeding"]
            if isinstance(breeding, list):
                breeding = breeding[0]
            payload = {k: v for k, v in breeding.items() if k != "individuals"}
            payload["breed_notes"] = "Anteckning från legacy"
            response = ctx.patch("/api/breeding", json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["status"], "success")
            # The edit must have been persisted, and the echoed fields left alone.
            reloaded = db.Breeding.get_by_id(invalid_row.id)
            self.assertEqual(reloaded.breed_notes, "Anteckning från legacy")
            self.assertEqual(str(reloaded.breed_date)[:10], "2021-01-01")
            self.assertEqual(str(reloaded.birth_date)[:10], "2021-06-01")
            self.assertEqual(reloaded.litter_size, 2)

    def test_alive_at_6_weeks_cannot_exceed_the_litter_size(self):
        """PATCH /api/breeding and POST /api/birth refuse litter_size6w > litter_size in their 200 envelope.

        A stored row that already breaks the rule still echoes (legacy PATCHes the whole object).
        """
        import utils.database as db

        message = "Antal levande vid 6 veckor kan inte vara fler än antal födda."
        born = db.Breeding.create(
            breed_date=datetime(2021, 6, 1),
            birth_date=datetime(2021, 7, 1),
            mother=self.parents[0],
            father=self.parents[1],
            litter_size=3,
            litter_size6w=5,  # historical data that breaks the rule
            breeding_herd_id=self.herds[0],
        )
        unborn = db.Breeding.create(
            breed_date=datetime(2021, 6, 1),
            mother=self.parents[0],
            father=self.parents[1],
            breeding_herd_id=self.herds[0],
        )
        with self.app as ctx:
            self.login(ctx, self.admin)
            stored = ctx.get(f"/api/breeding/id/{born.id}").get_json()["breeding"]
            stored = stored[0] if isinstance(stored, list) else stored
            echo = ctx.patch(
                "/api/breeding", json={**{k: v for k, v in stored.items() if k != "individuals"}, "breed_notes": "Echo"}
            )
            raised = ctx.patch("/api/breeding", json={"id": born.id, "litter_size": 3, "litter_size6w": 4})
            birth = ctx.post(
                "/api/birth", json={"id": unborn.id, "date": "2021-07-01", "litter_size": 3, "litter_size6w": 4}
            )
        self.assertEqual((echo.status_code, echo.get_json()["status"]), (200, "success"), echo.get_json())
        self.assertEqual((raised.status_code, raised.get_json()), (200, {"status": "error", "message": message}))
        self.assertEqual((birth.status_code, birth.get_json()), (200, {"status": "error", "message": message}))
        self.assertEqual(db.Breeding.get_by_id(born.id).litter_size6w, 5)
        self.assertIsNone(db.Breeding.get_by_id(unborn.id).birth_date)

    def _legacy_breeding_payload(self, ctx, breeding_id, **changes):
        """What breeding_context.updateBreeding sends: the whole object read back, nulls dropped."""
        read = ctx.get(f"/api/breeding/id/{breeding_id}")
        self.assertEqual(read.status_code, 200)
        breeding = read.get_json()["breeding"]
        if isinstance(breeding, list):
            breeding = breeding[0]
        payload = {k: v for k, v in breeding.items() if k != "individuals" and v is not None}
        payload.update(changes)
        return payload

    def test_update_breeding_parent_holder_refused_on_foreign_litter(self):
        """The G1 owner holds G1-1911, the mother of G2's litter breeding[2] (kit G2-2011).
        Holding a parent no longer authorizes moving that litter or changing its birth date or
        parents. The refusal is the route's existing {"status": "error", "message": "Forbidden"}."""
        import utils.database as db

        litter_id = self.breeding[2].id
        kit_id = self.individuals[1].id
        attempts = {
            "move": {"breeding_herd": "G1"},
            "birth_date": {"birth_date": "2020-02-05"},
            "parents": {"mother": self.parents[1].number, "father": self.parents[0].number},
        }
        with self.app as ctx:
            self.login(ctx, self.owner)
            for name, change in attempts.items():
                with self.subTest(name):
                    response = ctx.patch("/api/breeding", json=self._legacy_breeding_payload(ctx, litter_id, **change))
                    litter = db.Breeding.get_by_id(litter_id)
                    kit = db.Individual.get_by_id(kit_id)
                    kit_birth = (
                        db.HerdTracking.select()
                        .where(
                            db.HerdTracking.individual == kit_id, db.HerdTracking.kind == "BIRTH", db.ht_not_voided()
                        )
                        .get()
                    )
                    observed = (
                        response.status_code,
                        response.get_json(),
                        litter.breeding_herd_id.herd,
                        str(litter.birth_date),
                        (litter.mother_id, litter.father_id),
                        kit.number,
                        str(kit_birth.herd_tracking_date)[:10],
                    )
                    self.assertEqual(
                        observed,
                        (
                            200,
                            {"status": "error", "message": "Forbidden"},
                            "G2",
                            "2020-02-01",
                            (self.parents[0].id, self.parents[1].id),
                            "G2-2011",
                            "2021-02-01",
                        ),
                    )

    def test_delete_breeding_authenticated(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            # Register a breeding then delete it (legacy sends raw int)
            reg = ctx.post(
                "/api/breeding",
                json={
                    "father": self.individuals[0].number,
                    "mother": self.individuals[1].number,
                    "breeding_herd": self.herds[0].herd,
                    "date": "2025-06-01",
                },
            )
            new_id = reg.get_json()["breeding_id"]
            response = ctx.post("/api/breeding/delete", json=new_id)
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")

    def test_delete_breeding_unauthenticated_returns_401(self):
        response = self.app.post("/api/breeding/delete", json={"id": 1})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")

    def test_delete_breeding_with_bunnies_old_behavior_succeeded(self):
        """Inventory row: POST /api/breeding/delete (collapsible_sorted_table.tsx:226) —
        BROKEN, fixed.

        OLD: delete_breeding had no Bunny-roster guard, so the legacy "Ta bort"
        button — shown exactly when the litter has no registered individuals yet
        (collapsible_sorted_table.tsx:413-431) — deleted the breeding even after
        birth registration had seeded roster rows. NEW (before the fix): it refused
        with {status: error, code: has_bunnies} once Bunny rows existed. FIXED: the
        unpromoted roster rows are deleted with the breeding in one transaction;
        a litter with promoted individuals is still refused.
        """
        import utils.database as db

        with self.app as ctx:
            self.login(ctx, self.admin)
            reg = ctx.post(
                "/api/breeding",
                json={
                    "father": self.individuals[0].number,
                    "mother": self.individuals[1].number,
                    "breeding_herd": self.herds[0].herd,
                    "date": "2025-07-01",
                },
            )
            new_id = reg.get_json()["breeding_id"]
            # Registering the birth seeds Bunny roster rows for the litter.
            birth = ctx.post(
                "/api/birth",
                json={"id": new_id, "date": "2025-08-01", "litter_size": 3},
            )
            self.assertEqual(birth.get_json()["status"], "success")
            # The cascade is only exercised if the setup really created roster rows.
            self.assertEqual(db.Bunny.select().where(db.Bunny.breeding == new_id).count(), 3)

            response = ctx.post("/api/breeding/delete", json=new_id)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["status"], "success")
            # Both the roster and the litter must be gone.
            self.assertFalse(db.Bunny.select().where(db.Bunny.breeding == new_id).exists())
            self.assertFalse(db.Breeding.select().where(db.Breeding.id == new_id).exists())

    def test_breeding_nextind_returns_number(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post(
                "/api/breeding/nextind/",
                json={
                    "breeding_herd": self.herds[0].herd,
                    "birth_date": "2023-01-01",
                    "id": self.breeding[0].id,
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("status", data)

    def test_breeding_nextind_without_id_new_litter_old_behavior(self):
        """Inventory row: POST /api/breeding/nextind/ (individual_add.tsx:549, fed by the "new
        litter" branch at individual_add.tsx:350 — no matching existing breeding yet, so
        limitedBreedingInput carries no `id`) — BROKEN, fixed.

        OLD: the legacy backend answered 200 with a JSON {status, number} body even for a
        brand-new litter with no breeding id yet. NEW (before the fix): next_individual_number
        called `Breeding.get_by_id(None)`, which raises `Breeding.DoesNotExist`; the
        except-handler put the raw exception OBJECT into `message`, so `jsonify()` itself raised
        `TypeError: Object of type BreedingDoesNotExist is not JSON serializable` — with
        TESTING=True that propagated out of the view entirely (a real deploy would show it as an
        unhandled-exception 500 HTML page). individual_add.tsx could never get a next number for
        a brand-new litter. FIXED: a missing breeding event falls through to the
        chronological-rank fallback (utils/database.py:next_individual_number).
        """
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post(
                "/api/breeding/nextind/",
                json={
                    "breeding_herd": self.herds[0].herd,
                    "birth_date": "2025-09-01",
                    "mother": self.individuals[0].number,
                    "father": self.individuals[1].number,
                    # no "id" — matches limitedBreedingInput's shape for a brand-new litter
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("status", data)
            self.assertIsInstance(data["number"], str)

    def test_breeding_by_date_returns_breedings(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get("/api/breeding/date/2021-01-01")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("breedings", data)
            self.assertIsInstance(data["breedings"], list)

    def test_breeding_by_id_returns_breeding(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get(f"/api/breeding/id/{self.breeding[0].id}")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("breeding", data)

    def test_register_birth_returns_success(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post(
                "/api/birth",
                json={
                    "id": self.breeding[3].id,
                    "date": "2022-02-01",
                    "litter_size": 4,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["status"], "success")

    def test_birth_unauthenticated_returns_401(self):
        response = self.app.post("/api/birth", json={"id": 1, "date": "2022-02-01", "litter_size": 4})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")


# ============================================================================
# Testbreed (regression!)
# ============================================================================


class TestTestbreedContracts(FlaskTest):
    def test_testbreed_returns_offspring_coi(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post(
                "/api/testbreed",
                json={
                    "genebankId": self.genebanks[0].id,
                    "male": self.individuals[0].number,
                    "female": self.individuals[3].number,
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("offspringCOI", data)
            self.assertIsInstance(data["offspringCOI"], (int, float))

    def test_testbreed_with_grandparent_params_returns_coi(self):
        """REGRESSION: testbreed with maleGF/maleGM/femaleGF/femaleGM must not crash."""
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post(
                "/api/testbreed",
                json={
                    "genebankId": self.genebanks[0].id,
                    "male": self.parents[0].number,
                    "female": self.parents[1].number,
                    "maleGF": self.parents[0].number,
                    "maleGM": self.parents[1].number,
                    "femaleGF": self.parents[0].number,
                    "femaleGM": self.parents[1].number,
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("offspringCOI", data)
            self.assertIsInstance(data["offspringCOI"], (int, float))

    def test_testbreed_unauthenticated_returns_401(self):
        response = self.app.post(
            "/api/testbreed",
            json={
                "genebankId": 1,
                "male": "X",
                "female": "Y",
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")


# ============================================================================
# Certificates
# ============================================================================


class TestCertificateContracts(FlaskTest):
    def test_issue_unauthenticated_returns_401(self):
        response = self.app.post(f"/api/certificates/issue/{self.individuals[0].number}")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")

    def test_issue_get_nonexistent_returns_error(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get(f"/api/certificates/issue/{self.individuals[3].number}")
            self.assertIn(response.status_code, (400, 404))

    def test_issue_post_returns_pdf(self):
        """Inventory row: POST /api/certificates/issue/{x} (individual_certificate.tsx:274) — success path.

        This row was mapped only to the unauthenticated-401
        rejection test, so a genuine success response was never verified.
        moto's `mock_aws()` doesn't intercept a boto3 client built with a
        custom `endpoint_url` (utils/s3.py always passes one from
        settings.s3.endpoint), so this patches that setting to None for the
        duration of the mock — `get_s3_client()` builds a fresh client per
        call, so the patch is picked up without touching production code.
        """
        import unittest.mock

        import utils.s3 as s3_module
        import utils.settings as settings

        with unittest.mock.patch.object(settings.s3, "endpoint", None), mock_aws():
            with self.app as ctx:
                self.login(ctx, self.admin)
                ind = self.individuals[3]
                response = ctx.post(
                    f"/api/certificates/issue/{ind.number}",
                    json={
                        "color_id": 1,
                        "birth_date": "2020-12-01",
                        "litter_size": 5,
                        "litter_size6w": 4,
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["Content-Type"], "application/pdf")
                pdf_bytes = response.get_data()
                self.assertTrue(pdf_bytes.startswith(b"%PDF"))
                # the object actually exists in the mocked bucket, not just a 200
                s3_bytes = s3_module.get_s3_client().get_object(f"{ind.number}/certificate.pdf")
                self.assertEqual(s3_bytes, pdf_bytes)
                # the route's own issue_digital still assigns the first number
                self.assertEqual(db.Individual.get_by_id(ind.id).digital_certificate, 100000)

    def test_issue_is_no_genebank_correction(self):
        """herd, selling_date and origin_herd are not certificate fields: an admin's genebank change
        in the issue or update body is ignored, for everyone, and the certificate is signed for the rabbit
        as stored. PATCH /api/individual corrects the genebank first."""
        import unittest.mock

        import utils.settings as settings

        number = self.individuals[3].number  # G1-2112: born in G1, uncertified
        body = {
            "herd": "M3",
            "selling_date": "2021-06-01",
            "origin_herd": {"herd": "M3"},
            "litter_size": 2,
            "litter_size6w": 2,
        }
        with unittest.mock.patch.object(settings.s3, "endpoint", None), mock_aws():
            with self.app as ctx:
                self.login(ctx, self.admin)
                issued = ctx.post(f"/api/certificates/issue/{number}", json=dict(body))
                updated = ctx.patch(f"/api/certificates/update/{number}", json=dict(body))
        self.assertEqual(issued.status_code, 200, issued.data[:200])
        self.assertEqual(updated.status_code, 200, updated.data[:200])
        stored = db.Individual.get_by_id(self.individuals[3].id)
        self.assertEqual(
            (stored.current_herd.herd, stored.origin_herd.herd, stored.digital_certificate), ("G1", "G1", 100000)
        )

    def test_issue_body_cannot_point_issuance_at_another_rabbit(self):
        """Legacy issue is pinned to the URL rabbit; a body id/number cannot hand a number to another one."""
        import unittest.mock

        import utils.settings as settings

        other = db.Individual.create(origin_herd=self.herds[1], breeding=self.breeding[2], number="G2-2012")
        ht_row("BIRTH", herd=self.herds[1], individual=other, herd_tracking_date=datetime(2020, 2, 1))
        ht_row(
            "TRANSFER",
            from_herd=self.herds[1],
            herd=self.herds[0],
            individual=other,
            herd_tracking_date=datetime(2020, 6, 1),
        )
        body = {
            "id": other.id,
            "number": other.number,
            "breeding": self.breeding[2].id,
            "origin_herd": {"herd": "G2"},
            "herd": "G1",
            "litter_size": 2,  # unchanged: the route calls update_breeding on any difference
            "litter_size6w": 2,
        }
        with unittest.mock.patch.object(settings.s3, "endpoint", None), mock_aws():
            with self.app as ctx:
                self.login(ctx, self.owner)
                ctx.post(f"/api/certificates/issue/{self.individuals[3].number}", json=body)
        self.assertIsNone(db.Individual.get_by_id(other.id).digital_certificate)

    def test_update_certificate_success_returns_pdf(self):
        """Inventory row: PATCH /api/certificates/update/{x} (individual_certificate.tsx:321) — success path.

        This row was mapped only to the 404-without-existing-
        certificate test. An update requires a digital certificate to
        already exist (herdbook.py:2184-2185: `certificate_exists and
        present`), so this issues one first, then updates it, within the
        same mocked S3 bucket.
        """
        import unittest.mock

        import utils.s3 as s3_module
        import utils.settings as settings

        with unittest.mock.patch.object(settings.s3, "endpoint", None), mock_aws():
            with self.app as ctx:
                self.login(ctx, self.admin)
                ind = self.individuals[4]
                issued = ctx.post(
                    f"/api/certificates/issue/{ind.number}",
                    json={"color_id": 1, "birth_date": "2020-12-01", "litter_size": 3, "litter_size6w": 2},
                )
                self.assertEqual(issued.status_code, 200)  # precondition: digital cert now exists in S3

                response = ctx.patch(
                    f"/api/certificates/update/{ind.number}",
                    json={
                        "color_id": self.colors[0].id,
                        "birth_date": "2021-02-01",
                        "litter_size": 3,
                        "litter_size6w": 2,
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["Content-Type"], "application/pdf")
                pdf_bytes = response.get_data()
                self.assertTrue(pdf_bytes.startswith(b"%PDF"))
                s3_bytes = s3_module.get_s3_client().get_object(f"{ind.number}/certificate.pdf")
                self.assertEqual(s3_bytes, pdf_bytes)

    @contextmanager
    def _committed_before_the_lock(self, individual_id, **values):
        """Commit `values` between the route's read and its lock: inside certificate_form, which both legacy
        routes call in that window, outside their transaction."""
        from utils.cert_service_v2 import certificate_form

        ran = []

        def concurrent(body):
            ran.append(True)
            db.Individual.update(**values).where(db.Individual.id == individual_id).execute()
            return certificate_form(body)

        with mock.patch("herdbook.certificate_form", side_effect=concurrent):
            yield
        self.assertTrue(ran, "certificate_form was never reached")

    def test_issue_does_not_overwrite_a_certificate_issued_before_the_lock(self):
        """Final review (81bdb0c): v2 issues 100000 while a legacy issue waits for the lock. The legacy read saw
        no certificate; it must not put 100001 over the number the v2 row and PDF carry."""
        import utils.settings as settings

        ind = self.individuals[3]  # G1-2112: uncertified
        with mock.patch.object(settings.s3, "endpoint", None), mock_aws():
            with self.app as ctx:
                self.login(ctx, self.owner)
                with self._committed_before_the_lock(ind.id, digital_certificate=100000):
                    response = ctx.post(f"/api/certificates/issue/{ind.number}", json={})
        self.assertEqual(
            (response.status_code, response.get_json(), db.Individual.get_by_id(ind.id).digital_certificate),
            (400, {"response": "Certificate already exists"}, 100000),
        )

    def test_issue_keeps_a_renumber_committed_before_the_lock(self):
        """Final review (81bdb0c): the pre-lock read went to update_individual, whose stale number renamed the
        rabbit back (G1-2119 -> G1-2112). The PDF belongs under the current number."""
        import utils.s3 as s3_module
        import utils.settings as settings

        ind = self.individuals[3]
        with mock.patch.object(settings.s3, "endpoint", None), mock_aws():
            with self.app as ctx:
                self.login(ctx, self.manager)
                with self._committed_before_the_lock(ind.id, number="G1-2119"):
                    response = ctx.post(f"/api/certificates/issue/{ind.number}", json={})
            stored = db.Individual.get_by_id(ind.id)
            self.assertEqual((response.status_code, stored.number), (200, "G1-2119"))
            self.assertEqual(s3_module.get_s3_client().get_object("G1-2119/certificate.pdf"), response.get_data())

    def test_update_keeps_a_renumber_committed_before_the_lock(self):
        """Final review (81bdb0c): the same stale read on the update route renamed G1-2118 back to G1-2112."""
        import utils.settings as settings

        ind = self.individuals[3]
        with mock.patch.object(settings.s3, "endpoint", None), mock_aws():
            with self.app as ctx:
                self.login(ctx, self.manager)
                issued = ctx.post(f"/api/certificates/issue/{ind.number}", json={})
                self.assertEqual(issued.status_code, 200)
                with self._committed_before_the_lock(ind.id, number="G1-2118"):
                    response = ctx.patch(f"/api/certificates/update/{ind.number}", json={})
        self.assertEqual((response.status_code, db.Individual.get_by_id(ind.id).number), (200, "G1-2118"))

    def test_upload_holds_the_number_lock(self):
        """Final review (24a65b0): the legacy certificate upload to {number}/certificate.pdf did not take the
        number lock a renumber holds while it moves its assets after its commit, so the older PDF could land
        over the new one. It uploads under the lock now, as a photo upload does."""
        import herdbook
        import utils.settings as settings
        from utils import number_assets

        events = []
        real_lock, real_upload = number_assets.lock_number, herdbook.upload_certificate

        def lock(number, xact=False):
            events.append(("lock", number, xact))
            return real_lock(number, xact=xact)

        def upload(pdf_bytes, ind_number):
            events.append(("upload", ind_number))
            return real_upload(pdf_bytes=pdf_bytes, ind_number=ind_number)

        ind = self.individuals[3]
        with (
            mock.patch.object(settings.s3, "endpoint", None),
            mock_aws(),
            mock.patch.object(number_assets, "lock_number", side_effect=lock),
            mock.patch.object(herdbook, "upload_certificate", side_effect=upload),
        ):
            with self.app as ctx:
                self.login(ctx, self.manager)
                response = ctx.post(f"/api/certificates/issue/{ind.number}", json={})
        self.assertEqual(response.status_code, 200, response.data[:200])
        self.assertEqual(events[-2:], [("lock", ind.number, True), ("upload", ind.number)])

    def test_preview_returns_pdf_or_503(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get(f"/api/certificates/preview/{self.individuals[0].number}")
            self.assertIn(response.status_code, (200, 503))
            if response.status_code == 200:
                self.assertEqual(response.headers["Content-Type"], "application/pdf")

    def test_preview_post_returns_pdf(self):
        """Inventory row: POST /api/certificates/preview/{x} (individual_certificate.tsx:245).

        Unlike issue/update, the preview path never calls sign_data(), so it
        does not depend on PDF_SIGNING_KEY — it always answers 200 + a PDF.
        """
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post(
                f"/api/certificates/preview/{self.individuals[0].number}",
                json={
                    "color_id": self.colors[0].id,
                    "birth_date": "2021-02-01",
                    "litter_size": 2,
                    "litter_size6w": 2,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Content-Type"], "application/pdf")

    def test_update_certificate_without_existing_cert_returns_404(self):
        """Inventory row: PATCH /api/certificates/update/{x} (individual_certificate.tsx:321)."""
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.patch(
                f"/api/certificates/update/{self.individuals[0].number}",
                json={"color_id": self.colors[0].id, "birth_date": "2021-02-01"},
            )
            self.assertEqual(response.status_code, 404)
            data = response.get_json()
            self.assertIn("response", data)

    def test_verify_with_bad_data_returns_404_not_valid(self):
        """Inventory row: POST /api/certificates/verify/{x} with an unreadable file
        (certificate_verification.tsx:84-101) — OLD contract: 404 JSON "not valid",
        which the legacy page renders as "intyget är inte giltigt". Before the fix
        the new backend answered 400 (endesive 2.19 returns a list, the 3-tuple
        unpack raised ValueError into the broad except) and the page threw
        "Något gick fel.".
        """
        import unittest.mock

        import utils.settings as settings

        with unittest.mock.patch.object(settings.s3, "endpoint", None), mock_aws():
            with self.app as ctx:
                self.login(ctx, self.admin)
                ind = self.individuals[4]
                # A stored certificate must exist: with none in S3 the checksum lookup
                # raises NoSuchKey and BOTH backends answer 400 (identical code).
                issued = ctx.post(
                    f"/api/certificates/issue/{ind.number}",
                    json={"color_id": 1, "birth_date": "2020-12-01", "litter_size": 3, "litter_size6w": 2},
                )
                self.assertEqual(issued.status_code, 200)

                response = ctx.post(f"/api/certificates/verify/{ind.number}", data=b"not a real certificate")
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.get_json()["response"], "The uploaded certificate is not valid")

    def test_verify_roundtrip_own_certificate_is_valid(self):
        """Inventory row: POST /api/certificates/verify/{x} — success path, BROKEN before the fix.

        Issue a certificate through the legacy endpoint, upload the very same bytes
        to verify: OLD answered 200 "Certificate is valid". NEW (before the fix)
        answered 400 for EVERY certificate, including its own: endesive >= 2.19
        validates the signer with cryptography's strict RFC 5280 path builder,
        which rejects the association's self-signed CA:TRUE signing certificate
        as an end-entity cert (`certs/ca.pem` has that shape, as does the
        production signer — verified on a production PDF in the Phase 20 audit).
        pyHanko with the CA pinned as trust root accepts it.
        """
        import unittest.mock

        import utils.settings as settings

        with unittest.mock.patch.object(settings.s3, "endpoint", None), mock_aws():
            with self.app as ctx:
                self.login(ctx, self.admin)
                ind = self.individuals[3]
                issued = ctx.post(
                    f"/api/certificates/issue/{ind.number}",
                    json={"color_id": 1, "birth_date": "2020-12-01", "litter_size": 5, "litter_size6w": 4},
                )
                self.assertEqual(issued.status_code, 200)
                pdf_bytes = issued.get_data()

                response = ctx.post(f"/api/certificates/verify/{ind.number}", data=pdf_bytes)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["response"], "Certificate is valid")

                # A signed PDF that is not the stored one: signature ok, checksum not → 202 (old contract).
                reissued = ctx.patch(
                    f"/api/certificates/update/{ind.number}",
                    json={"color_id": 1, "birth_date": "2020-12-02", "litter_size": 5, "litter_size6w": 4},
                )
                self.assertEqual(reissued.status_code, 200)
                response = ctx.post(f"/api/certificates/verify/{ind.number}", data=pdf_bytes)
                self.assertEqual(response.status_code, 202)
                self.assertEqual(response.get_json()["response"], "Certificate valid but file not present")

    def test_verify_rejects_field_edited_after_signing(self):
        """An unsigned incremental revision that changes a certificate field is not valid.

        pyHanko's bottom_line tolerates form filling after signing, so without the
        modification-level check a certificate with a new name in a later
        revision verified as 202 "valid but file not present".
        """
        import io
        import unittest.mock

        import utils.settings as settings
        from pyhanko.pdf_utils import generic
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

        with unittest.mock.patch.object(settings.s3, "endpoint", None), mock_aws():
            with self.app as ctx:
                self.login(ctx, self.admin)
                ind = self.individuals[3]
                issued = ctx.post(
                    f"/api/certificates/issue/{ind.number}",
                    json={"color_id": 1, "birth_date": "2020-12-01", "litter_size": 5, "litter_size6w": 4},
                )
                self.assertEqual(issued.status_code, 200)

                writer = IncrementalPdfFileWriter(io.BytesIO(issued.get_data()), strict=False)
                edited = 0
                for ref in writer.root["/AcroForm"]["/Fields"]:
                    field = ref.get_object()
                    if field.get("/T") == "IdNamn":
                        field["/V"] = generic.TextStringObject("Förfalskad")
                        writer.update_container(field)
                        edited += 1
                self.assertEqual(edited, 1)
                tampered = io.BytesIO()
                writer.write(tampered)

                response = ctx.post(f"/api/certificates/verify/{ind.number}", data=tampered.getvalue())
                self.assertEqual(response.status_code, 404)

    def test_update_unauthenticated_returns_401(self):
        response = self.app.patch(f"/api/certificates/update/{self.individuals[0].number}")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")

    def test_verify_unauthenticated_returns_401(self):
        response = self.app.post(
            f"/api/certificates/verify/{self.individuals[0].number}",
            data=b"x",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")

    # issue/update sign only what the caller may write, rendered from the stored rabbit.
    # Refusals keep each route's status and shape: issue 400, update 404, {"response": ...}.

    def _client(self, user):
        client = self.app.application.test_client(use_cookies=True)
        self.login(client, user)
        return client

    def test_issue_by_a_viewer_is_refused_and_signs_nothing(self):
        import unittest.mock

        import utils.database as db
        import utils.s3 as s3_module
        import utils.settings as settings
        from utils.cert_acess import sign_data

        target = self.individuals[4]  # M3-2111, Mellerud: the Gotland viewer cannot even read it
        rabbit = self.individuals[3]  # G1-2112: the viewer can read it, not edit it
        with unittest.mock.patch.object(settings.s3, "endpoint", None), mock_aws():
            issued = self._client(self.admin).post(
                f"/api/certificates/issue/{target.number}", json={"color_id": 1, "litter_size": 2, "litter_size6w": 2}
            )
            self.assertEqual(issued.status_code, 200, "precondition: the genuine M3-2111 certificate")
            s3 = s3_module.get_s3_client()
            genuine = s3.get_object(f"{target.number}/certificate.pdf")
            with unittest.mock.patch("herdbook.sign_data", wraps=sign_data) as sign:
                response = self._client(self.viewer).post(
                    f"/api/certificates/issue/{rabbit.number}",
                    json={"name": "FORGED", "number": target.number, "litter_size": 2, "litter_size6w": 2},
                )
            self.assertEqual(
                s3.get_object(f"{target.number}/certificate.pdf"), genuine, "M3-2111's certificate was overwritten"
            )
        self.assertEqual((response.status_code, response.get_json()), (400, {"response": "Forbidden"}))
        sign.assert_not_called()
        stored = db.Individual.get_by_id(rabbit.id)
        self.assertEqual((stored.name, stored.digital_certificate), (None, None))

    def test_update_by_a_viewer_is_refused_and_signs_nothing(self):
        import unittest.mock

        import utils.database as db
        import utils.s3 as s3_module
        import utils.settings as settings
        from utils.cert_acess import sign_data

        rabbit = self.individuals[3]  # G1-2112: the Gotland viewer can read it, not edit it
        with unittest.mock.patch.object(settings.s3, "endpoint", None), mock_aws():
            issued = self._client(self.admin).post(
                f"/api/certificates/issue/{rabbit.number}", json={"color_id": 1, "litter_size": 2, "litter_size6w": 2}
            )
            self.assertEqual(issued.status_code, 200, "precondition: G1-2112 has a digital certificate")
            s3 = s3_module.get_s3_client()
            genuine = s3.get_object(f"{rabbit.number}/certificate.pdf")
            with unittest.mock.patch("herdbook.sign_data", wraps=sign_data) as sign:
                response = self._client(self.viewer).patch(
                    f"/api/certificates/update/{rabbit.number}",
                    json={"name": "FORGED", "litter_size": 2, "litter_size6w": 2},
                )
            self.assertEqual(
                s3.get_object(f"{rabbit.number}/certificate.pdf"), genuine, "G1-2112's certificate was overwritten"
            )
        self.assertEqual((response.status_code, response.get_json()), (404, {"response": "Forbidden"}))
        sign.assert_not_called()
        self.assertIsNone(db.Individual.get_by_id(rabbit.id).name)

    def test_issue_renders_the_stored_rabbit_not_the_body(self):
        """Fields outside the certificate form (number, parents, birth date, sale) never reach the PDF or S3."""
        import unittest.mock

        import utils.database as db
        import utils.s3 as s3_module
        import utils.settings as settings
        from utils.cert_acess import get_certificate

        target = self.individuals[4]  # M3-2111
        rabbit = self.individuals[3]  # G1-2112: mother G1-1911, born 2021-02-01, held by G1
        body = {
            "name": "Ny",
            "litter_size": 2,
            "litter_size6w": 2,
            "number": target.number,
            "digital_certificate": 1,
            "mother": {"number": "M3-1911"},
            "birth_date": "1999-01-01",
            "herd": {"herd": "G2"},
            "selling_date": "2021-06-01",
        }
        with unittest.mock.patch.object(settings.s3, "endpoint", None), mock_aws():
            admin = self._client(self.admin)
            self.assertEqual(
                admin.post(
                    f"/api/certificates/issue/{target.number}",
                    json={"color_id": 1, "litter_size": 2, "litter_size6w": 2},
                ).status_code,
                200,
            )
            s3 = s3_module.get_s3_client()
            genuine = s3.get_object(f"{target.number}/certificate.pdf")
            with unittest.mock.patch("herdbook.get_certificate", wraps=get_certificate) as render:
                response = admin.post(f"/api/certificates/issue/{rabbit.number}", json=body)
            self.assertEqual(
                s3.get_object(f"{target.number}/certificate.pdf"), genuine, "the body number redirected the S3 key"
            )
            self.assertEqual(response.status_code, 200, response.data[:200])
            self.assertEqual(s3.get_object(f"{rabbit.number}/certificate.pdf"), response.get_data())
        stored = db.Individual.get_by_id(rabbit.id)
        printed = render.call_args.args[0]
        self.assertEqual(
            (printed["number"], printed["M_number"], printed["birth_date"], printed["name"]),
            (rabbit.number, "G1-1911", "2021-02-01", "Ny"),
        )
        self.assertEqual(printed["digital_certificate"], stored.digital_certificate)
        self.assertNotEqual(stored.digital_certificate, 1)
        self.assertEqual((stored.name, stored.current_herd.herd), ("Ny", "G1"))

    def test_refused_update_signs_and_uploads_nothing(self):
        """A breeding or individual update that is refused aborts the request: no PDF is signed or uploaded."""
        import io
        import unittest.mock

        import utils.database as db

        rabbit, certified = self.individuals[3], self.individuals[4]
        db.Individual.update(digital_certificate=100500).where(db.Individual.id == certified.id).execute()
        with (
            unittest.mock.patch("herdbook.sign_data", side_effect=lambda pdf: io.BytesIO(b"%PDF-fake")) as sign,
            unittest.mock.patch("herdbook.upload_certificate", return_value=True) as upload,
            unittest.mock.patch("herdbook.check_certificate_s3", return_value=True),
        ):
            client = self._client(self.admin)
            # update_breeding refuses the litter size; update_individual refuses the colour.
            issue = client.post(
                f"/api/certificates/issue/{rabbit.number}", json={"name": "Ny", "litter_size": 0, "litter_size6w": 0}
            )
            update = client.patch(
                f"/api/certificates/update/{certified.number}", json={"name": "Ny", "color": "Ingen sådan färg"}
            )
        self.assertEqual(
            (issue.status_code, issue.get_json()), (400, {"response": "Litter size must be larger than zero."})
        )
        self.assertEqual(update.status_code, 404, update.data[:200])
        self.assertTrue(update.get_json()["response"].startswith("Unknown color"), update.get_json())
        sign.assert_not_called()
        upload.assert_not_called()
        stored = db.Individual.get_by_id(rabbit.id)
        self.assertEqual((stored.name, stored.digital_certificate), (None, None), "the refused issue committed")
        self.assertEqual(db.Breeding.get_by_id(rabbit.breeding_id).litter_size, 2)
        self.assertIsNone(db.Individual.get_by_id(certified.id).name)

    def test_refused_individual_update_rolls_back_the_litter_update(self):
        """The litter update that already succeeded is rolled back when the individual update is refused."""
        import io
        import unittest.mock

        import utils.database as db

        rabbit = self.individuals[2]  # M3-2122, uncertified; its litter has litter_size 2
        with (
            unittest.mock.patch("herdbook.sign_data", side_effect=lambda pdf: io.BytesIO(b"%PDF-fake")) as sign,
            unittest.mock.patch("herdbook.upload_certificate", return_value=True),
        ):
            response = self._client(self.admin).post(
                f"/api/certificates/issue/{rabbit.number}",
                json={"litter_size": 3, "litter_size6w": 2, "color": "Ingen sådan färg"},
            )
        self.assertEqual(
            db.Breeding.get_by_id(rabbit.breeding_id).litter_size,
            2,
            f"issue returned {response.status_code}: the litter size was saved although the request was refused",
        )
        self.assertEqual(response.status_code, 400, response.data[:200])
        self.assertTrue(response.get_json()["response"].startswith("Unknown color"), response.get_json())
        sign.assert_not_called()
        self.assertIsNone(db.Individual.get_by_id(rabbit.id).digital_certificate)

    def test_issue_respects_the_litter_quota(self):
        """A first certificate past 6 weeks takes one of litter_size6w's slots (under the litter lock)."""
        import unittest.mock

        import utils.database as db
        from utils.cert_acess import sign_data

        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=datetime(2025, 1, 10),
            litter_number=1,
            litter_size=3,
            litter_size6w=1,
            mother=self.parents[0],
            father=self.parents[1],
        )
        db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2511", certificate="P1")
        rabbit = db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2512")
        with unittest.mock.patch("herdbook.sign_data", wraps=sign_data) as sign:
            response = self._client(self.admin).post(
                f"/api/certificates/issue/{rabbit.number}", json={"litter_size": 3, "litter_size6w": 1}
            )
        self.assertIsNone(
            db.Individual.get_by_id(rabbit.id).digital_certificate,
            f"issue returned {response.status_code}: litter_size6w=1 but a second kit got a certificate",
        )
        self.assertEqual((response.status_code, response.get_json()), (400, {"response": "certificate_quota_exceeded"}))
        sign.assert_not_called()

    def test_paper_certificate_via_individual_edit_respects_the_litter_quota(self):
        """An owner's PATCH that sets a first (paper) certificate goes through the same quota."""
        import utils.database as db

        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=datetime(2025, 1, 10),
            litter_number=1,
            litter_size=3,
            litter_size6w=1,
            mother=self.parents[0],
            father=self.parents[1],
        )
        db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2511", certificate="P1")
        legacy = db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2512")
        v2 = db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2513")
        owner = self._client(self.owner)
        legacy_resp = owner.patch(
            "/api/individual", json={"id": legacy.id, "number": legacy.number, "herd": "G1", "certificate": "P2"}
        )
        v2_resp = owner.patch(f"/api/individual/{v2.number}", json={"certificate": "P3", "paper_number": v2.number})
        certified = db.Individual.select().where(
            (db.Individual.breeding == litter) & db.Individual.certificate.is_null(False)
        )
        self.assertEqual(
            certified.count(),
            1,
            f"legacy {legacy_resp.status_code}, v2 {v2_resp.status_code}: litter_size6w=1 but more certified kits",
        )
        # The legacy route keeps its HTTP 200 error envelope (ADR-0006).
        self.assertEqual(
            (legacy_resp.status_code, legacy_resp.get_json()),
            (200, {"status": "error", "message": "certificate_quota_exceeded"}),
        )
        self.assertEqual((v2_resp.status_code, v2_resp.get_json()["detail"]), (400, "certificate_quota_exceeded"))

    def test_issue_in_a_pre_roster_litter_has_no_quota(self):
        """Litters without litter_number (before the roster) keep issuing as before."""
        import unittest.mock

        import utils.database as db
        import utils.settings as settings

        db.Breeding.update(litter_size6w=1).where(db.Breeding.id == self.breeding[0].id).execute()
        rabbit = self.individuals[3]  # G1-2112; its sibling G1-2111 is certified, litter_size6w is now 1
        with unittest.mock.patch.object(settings.s3, "endpoint", None), mock_aws():
            response = self._client(self.admin).post(
                f"/api/certificates/issue/{rabbit.number}", json={"color_id": 1, "litter_size": 2, "litter_size6w": 1}
            )
        self.assertEqual(response.status_code, 200, response.data[:200])
        self.assertIsNotNone(db.Individual.get_by_id(rabbit.id).digital_certificate)

    def _roster_litter_without_litter_size6w(self):
        import utils.database as db

        return db.Breeding.create(
            breeding_herd_id=self.herds[0],
            breed_date=datetime(2024, 12, 10),
            birth_date=datetime(2025, 1, 10),
            litter_number=1,
            litter_size=3,
            mother=self.parents[0],
            father=self.parents[1],
        )

    def test_issue_requires_litter_size6w_and_a_roster_in_sync(self):
        """A first certificate in a roster litter needs litter_size6w, and a roster that agrees with it."""
        import unittest.mock

        import utils.database as db
        from utils.cert_acess import sign_data

        litter = self._roster_litter_without_litter_size6w()
        rabbit = db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2511")
        admin = self._client(self.admin)
        upload = unittest.mock.patch("herdbook.upload_certificate", return_value=True)
        with unittest.mock.patch("herdbook.sign_data", wraps=sign_data) as sign, upload:
            missing = admin.post(f"/api/certificates/issue/{rabbit.number}", json={"litter_size": 3})
        self.assertIsNone(
            db.Individual.get_by_id(rabbit.id).digital_certificate,
            f"issue returned {missing.status_code}: a certificate in a litter without litter_size6w",
        )
        self.assertEqual((missing.status_code, missing.get_json()), (400, {"response": "litter_size6w_required"}))

        # The form declares 2 alive at 6 weeks, but the roster has 3 alive (the rabbit is registered).
        db.Bunny.create(breeding=litter, slot_order=1, fate="registered", individual=rabbit)
        db.Bunny.create(breeding=litter, slot_order=2)
        db.Bunny.create(breeding=litter, slot_order=3)
        with unittest.mock.patch("herdbook.sign_data", wraps=sign_data) as sign, upload:
            out_of_sync = admin.post(
                f"/api/certificates/issue/{rabbit.number}", json={"litter_size": 3, "litter_size6w": 2}
            )
        self.assertIsNone(
            db.Individual.get_by_id(rabbit.id).digital_certificate,
            "3 kits alive in the roster but litter_size6w=2, and a certificate was issued",
        )
        # The route's 400 {"response": key} shape, plus the count as a new field (ADR-0006).
        self.assertEqual(
            (out_of_sync.status_code, out_of_sync.get_json()),
            (400, {"response": "roster_alive_exceeds_6w", "must_mark_dead": 1}),
        )
        sign.assert_not_called()
        self.assertIsNone(db.Breeding.get_by_id(litter.id).litter_size6w, "the refused request saved litter_size6w")

    def test_paper_certificate_via_individual_edit_requires_litter_size6w_and_a_roster_in_sync(self):
        """An owner's PATCH that sets a first (paper) certificate goes through the same two rules."""
        import utils.database as db

        litter = self._roster_litter_without_litter_size6w()
        legacy = db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2512")
        v2 = db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2513")
        owner = self._client(self.owner)

        def patch_both():
            return (
                owner.patch(
                    "/api/individual",
                    json={"id": legacy.id, "number": legacy.number, "herd": "G1", "certificate": "P2"},
                ),
                owner.patch(f"/api/individual/{v2.number}", json={"certificate": "P3", "paper_number": v2.number}),
            )

        missing = patch_both()
        db.Breeding.update(litter_size6w=1).where(db.Breeding.id == litter.id).execute()
        db.Bunny.create(breeding=litter, slot_order=1)
        db.Bunny.create(breeding=litter, slot_order=2)
        out_of_sync = patch_both()
        certified = db.Individual.select().where(
            (db.Individual.breeding == litter) & db.Individual.certificate.is_null(False)
        )
        self.assertEqual(
            certified.count(), 0, f"{[r.status_code for r in missing + out_of_sync]}: a certificate was set"
        )
        # The legacy route keeps its HTTP 200 error envelope (ADR-0006); the count is a new field.
        self.assertEqual(
            (missing[0].status_code, missing[0].get_json()),
            (200, {"status": "error", "message": "litter_size6w_required"}),
        )
        self.assertEqual(
            (out_of_sync[0].status_code, out_of_sync[0].get_json()),
            (200, {"status": "error", "message": "roster_alive_exceeds_6w", "must_mark_dead": 1}),
        )
        self.assertEqual((missing[1].status_code, missing[1].get_json().get("detail")), (400, "litter_size6w_required"))
        self.assertEqual(
            (
                out_of_sync[1].status_code,
                out_of_sync[1].get_json().get("detail"),
                out_of_sync[1].get_json().get("must_mark_dead"),
            ),
            (400, "roster_alive_exceeds_6w", 1),
        )


# ============================================================================
# Årsrapport owner
# ============================================================================


class TestYearlyReportOwnerContracts(FlaskTest):
    def test_get_unauthenticated_returns_401(self):
        response = self.app.get(f"/api/herd/{self.herds[0].herd}/yearlyreport?round_id=1")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")

    def test_get_missing_round_id_returns_400(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get(f"/api/herd/{self.herds[0].herd}/yearlyreport")
            self.assertEqual(response.status_code, 400)
            data = response.get_json()
            self.assertEqual(data["status"], "error")

    def test_get_nonexistent_round_returns_404(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get(f"/api/herd/{self.herds[0].herd}/yearlyreport?round_id=999")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.get_json()["status"], "error")

    def test_post_unauthenticated_returns_401(self):
        response = self.app.post(
            f"/api/herd/{self.herds[0].herd}/yearlyreport",
            json={},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")

    def test_post_report_with_round(self):
        """Create a round then POST a yearly report against it."""
        with self.app as ctx:
            self.login(ctx, self.admin)
            # Create a round first
            rr = ctx.post(
                "/api/manage/yearly_report_round",
                json={
                    "report_year": 2025,
                    "start_date": "2025-01-01",
                    "end_date": "2025-12-31",
                    "is_active": True,
                },
            )
            round_id = rr.get_json()["round"]
            # POST yearly report for herd
            response = ctx.post(
                f"/api/herd/{self.herds[0].herd}/yearlyreport",
                json={
                    "round_id": round_id,
                },
            )
            # Should return success or error with status key
            data = response.get_json()
            self.assertIn("status", data)

    def test_get_report_after_post(self):
        """Create round, POST report, then GET it."""
        with self.app as ctx:
            self.login(ctx, self.admin)
            rr = ctx.post(
                "/api/manage/yearly_report_round",
                json={
                    "report_year": 2024,
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                    "is_active": True,
                },
            )
            round_id = rr.get_json()["round"]
            # POST a report
            ctx.post(
                f"/api/herd/{self.herds[0].herd}/yearlyreport",
                json={
                    "round_id": round_id,
                },
            )
            # GET it back
            response = ctx.get(f"/api/herd/{self.herds[0].herd}/yearlyreport?round_id={round_id}")
            data = response.get_json()
            self.assertIn("status", data)


# ============================================================================
# Årsrapport admin
# ============================================================================


class TestYearlyReportAdminContracts(FlaskTest):
    def test_get_rounds_returns_shape(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get("/api/manage/yearly_report_rounds")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertIn("rounds", data)
            self.assertIsInstance(data["rounds"], list)

    def test_create_round_returns_success_with_id(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post(
                "/api/manage/yearly_report_round",
                json={
                    "report_year": 2025,
                    "start_date": "2025-01-01",
                    "end_date": "2025-12-31",
                    "is_active": True,
                },
            )
            self.assertEqual(response.status_code, 201)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertIn("round", data)
            self.assertIsInstance(data["round"], int)

    def test_create_round_as_owner_returns_403(self):
        with self.app as ctx:
            self.login(ctx, self.owner)
            response = ctx.post("/api/manage/yearly_report_round", json={"report_year": 2025})
            self.assertEqual(response.status_code, 403)

    def test_patch_round_as_admin(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            # Create then patch
            rr = ctx.post(
                "/api/manage/yearly_report_round",
                json={
                    "report_year": 2023,
                    "start_date": "2023-01-01",
                    "end_date": "2023-12-31",
                    "is_active": False,
                },
            )
            round_id = rr.get_json()["round"]
            response = ctx.patch(
                f"/api/manage/yearly_report_round/{round_id}",
                json={
                    "is_active": True,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["status"], "success")

    def test_delete_round_as_admin(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            rr = ctx.post(
                "/api/manage/yearly_report_round",
                json={
                    "report_year": 2022,
                    "start_date": "2022-01-01",
                    "end_date": "2022-12-31",
                },
            )
            round_id = rr.get_json()["round"]
            response = ctx.delete(f"/api/manage/yearly_report_round/{round_id}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["status"], "success")

    def test_get_yearly_reports_for_round_as_admin(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            rr = ctx.post(
                "/api/manage/yearly_report_round",
                json={
                    "report_year": 2021,
                    "start_date": "2021-01-01",
                    "end_date": "2021-12-31",
                },
            )
            round_id = rr.get_json()["round"]
            response = ctx.get(f"/api/manage/yearly-reports/{round_id}/{self.genebanks[0].id}")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertIn("reports", data)

    def test_export_yearly_reports_returns_csv(self):
        """Inventory row: GET /api/manage/yearly-reports/{x}/{x}/export (YearlyReportViewer.tsx:114)."""
        with self.app as ctx:
            self.login(ctx, self.admin)
            rr = ctx.post(
                "/api/manage/yearly_report_round",
                json={
                    "report_year": 2020,
                    "start_date": "2020-01-01",
                    "end_date": "2020-12-31",
                },
            )
            round_id = rr.get_json()["round"]
            response = ctx.get(f"/api/manage/yearly-reports/{round_id}/{self.genebanks[0].id}/export")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "text/csv")
            self.assertIn("attachment", response.headers["Content-Disposition"])
            self.assertGreater(len(response.data), 0)

    def test_patch_round_unauthenticated_returns_401(self):
        response = self.app.patch("/api/manage/yearly_report_round/1", json={})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")

    def test_delete_round_unauthenticated_returns_401(self):
        response = self.app.delete("/api/manage/yearly_report_round/1")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")


# ============================================================================
# Users admin
# ============================================================================


class TestUserAdminContracts(FlaskTest):
    def test_get_users_admin_returns_list(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get("/api/manage/users")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("users", data)
            self.assertIsInstance(data["users"], list)
            self.assertGreater(len(data["users"]), 0)
            user = data["users"][0]
            for key in ("id", "email", "name", "fullname"):
                self.assertIn(key, user, f"Missing key: {key}")

    def test_get_users_owner_returns_null(self):
        with self.app as ctx:
            self.login(ctx, self.owner)
            self.assertIsNone(ctx.get("/api/manage/users").get_json()["users"])

    def test_get_users_unauthenticated_returns_null(self):
        self.assertIsNone(self.app.get("/api/manage/users").get_json()["users"])

    def test_manage_user_get_self(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get("/api/manage/user/")
            self.assertEqual(response.status_code, 200)

    def test_manage_user_post_creates_user(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post(
                "/api/manage/user/",
                json={
                    "email": "newuser@test.example.com",
                    "username": "newuser",
                    "password": "testpass",
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("status", data)
            self.assertIn(data["status"], ("created", "success"))

    def test_manage_user_patch_updates_user(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.patch(
                f"/api/manage/user/{self.viewer.id}",
                json={
                    "id": self.viewer.id,
                    "fullname": "Updated Viewer Name",
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("status", data)

    def test_manage_user_self_patch_no_id_returns_status(self):
        """Inventory row: PATCH /api/manage/user/ (settings.tsx:72) — self-service, no id in URL."""
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.patch(
                "/api/manage/user/",
                json={"email": self.admin.email, "validated": True},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("status", response.get_json())

    def test_manage_user_patch_other_account_as_viewer_is_forbidden(self):
        """The body id picks the target, so a non-manager could rewrite any
        account. Refusal keeps the route's HTTP 200 error envelope (ADR-0006);
        editing one's own account by id keeps working."""
        import utils.database as db

        admin = db.User.get_by_id(self.admin.id)
        admin.validated = True
        admin.fullname = "Real Admin"
        admin.save()

        with self.app as ctx:
            self.login(ctx, self.viewer)
            response = ctx.patch(
                f"/api/manage/user/{self.admin.id}",
                json={"id": self.admin.id, "email": "pwned@example.org", "fullname": "Pwned", "validated": False},
            )
            after = db.User.get_by_id(self.admin.id)
            self.assertEqual(
                (after.email, after.fullname, after.validated),
                ("admin", "Real Admin", True),
                f"viewer rewrote admin account: response={response.get_json()}",
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), {"status": "error", "message": "forbidden"})

            own = ctx.patch(
                f"/api/manage/user/{self.viewer.id}",
                json={"id": self.viewer.id, "email": "spec-new@example.org", "validated": False},
            )
            self.assertEqual(own.get_json(), {"status": "updated"})
            self.assertEqual(db.User.get_by_id(self.viewer.id).email, "spec-new@example.org")

    def test_manage_user_patch_admin_account_as_manager_is_forbidden(self):
        """Managers manage non-admin users only (get_users hides admins)."""
        import utils.database as db

        with self.app as ctx:
            self.login(ctx, self.manager)
            response = ctx.patch(
                f"/api/manage/user/{self.admin.id}",
                json={"id": self.admin.id, "email": "pwned@example.org", "validated": False},
            )
            self.assertEqual(db.User.get_by_id(self.admin.id).email, "admin", response.get_json())
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), {"status": "error", "message": "forbidden"})

            other = ctx.patch(
                f"/api/manage/user/{self.viewer.id}",
                json={"id": self.viewer.id, "email": "spec-by-manager@example.org", "validated": True},
            )
            self.assertEqual(other.get_json(), {"status": "updated"})

    def test_manage_user_self_patch_cannot_take_another_accounts_email(self):
        """A self-service PATCH may not take an address another
        account holds (any casing). The CMS itself keys on google_email +
        validated (resolveFlaskUser.ts), never on this field."""
        import utils.database as db

        cms_admin = "cms-admin@gotlandskaninen.se"
        admin = db.User.get_by_id(self.admin.id)
        admin.email = cms_admin
        admin.validated = True
        admin.save()

        with self.app as ctx:
            self.login(ctx, self.owner)
            patch = ctx.patch("/api/manage/user/", json={"email": cms_admin, "validated": False})
            cased = ctx.patch("/api/manage/user/", json={"email": "CMS-Admin@Gotlandskaninen.se", "validated": False})
            me = ctx.get("/api/user").get_json()

        self.assertEqual(
            me["email"],
            "owner",
            f"owner (id={self.owner.id}) took the CMS admin's email: PATCH -> {patch.get_json()}, "
            f"GET /api/user email={me['email']!r} validated={me['validated']}",
        )
        self.assertEqual(patch.status_code, 200)
        self.assertEqual(patch.get_json(), {"status": "error", "message": "email already in use"})
        self.assertEqual(cased.get_json(), {"status": "error", "message": "email already in use"})

    def test_manage_user_get_by_id_returns_shape(self):
        """Inventory row: GET /api/manage/user/{x} (userForm.tsx:111) — admin looks up another user."""
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get(f"/api/manage/user/{self.viewer.id}")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertIn("data", data)
            for key in ("id", "email", "username", "fullname"):
                self.assertIn(key, data["data"])

    def test_manage_user_post_new_via_id_zero_creates_user(self):
        """Inventory row: POST /api/manage/user/{x} (userForm.tsx:169) — isNew branch posts
        .../0. response_fields_used = status;data — add_user() returns {status: "created",
        data: user.id} (utils/data_access.py:361-362)."""
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post(
                "/api/manage/user/0",
                json={
                    "email": "newuser2@test.example.com",
                    "username": "newuser2",
                    "password": "testpass",
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("status", data)
            self.assertIn("data", data)
            self.assertIsInstance(data["data"], int)

    def test_setpassword_self(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post(
                "/api/manage/setpassword/",
                json={
                    "oldpassword": "pass",
                    "newpassword": "newpass123",
                },
            )
            self.assertEqual(response.status_code, 200)

    def test_setpassword_other_user_as_admin(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post(
                f"/api/manage/setpassword/{self.viewer.id}",
                json={
                    "newpassword": "viewerpass456",
                },
            )
            self.assertEqual(response.status_code, 200)

    def test_setpassword_unauthenticated_fails(self):
        response = self.app.post("/api/manage/setpassword/", json={"newpassword": "x"})
        self.assertEqual(response.status_code, 403)

    def test_manage_role_returns_status(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.post(
                "/api/manage/role",
                json={
                    "user": self.viewer.id,
                    "level": "manager",
                    "genebank": self.genebanks[0].id,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("status", response.get_json())

    def test_manage_role_patch_returns_status(self):
        """Inventory row: PATCH /api/manage/role (userForm.tsx:264) — the
        `GenebankOperation` payload `updateRole()` actually sends
        (action/role/user/genebank; the frontend never sends "level" —
        that's only the internal `_privileges` storage key, database.py:1168)
        must succeed, not just come back with *a* `status` key."""
        import utils.database as db

        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.patch(
                "/api/manage/role",
                json={
                    "action": "add",
                    "role": "manager",
                    "user": self.viewer.id,
                    "genebank": self.genebanks[0].id,
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn(data["status"], ("updated", "unchanged"))
            reloaded = db.User.get(db.User.id == self.viewer.id)
            self.assertTrue(reloaded.has_role("manager", self.genebanks[0].id))

    @unittest.expectedFailure
    def test_manage_role_remove_last_admin_legacy_contract(self):
        """Inventory row: PATCH /api/manage/role (userForm.tsx:264) — RISK, fix-candidate.

        This pins the LEGACY CONTRACT the remedy restores, not the old
        permissive behaviour (the last-admin protection itself is being kept —
        removing the sole admin's admin role must keep failing). userForm.tsx's
        manage_role handler (:264-278) expects a denial to look like
        {status: 'error', message: <string>} with HTTP 200, matching every
        other denial path in this route (see TestManageRoleLegacyCompat).

        TODAY: utils/data_access.py:1028 raises ValidationError("last-admin"),
        rendered as HTTP 409 application/problem+json
        {type, title, status: 409, detail} — no "message" key at all, so
        userForm.tsx falls to its `default:` case and shows nothing to the
        admin. The remedy (herdbook.py:669-674 docstring): catch
        ValidationError in manage_roles and answer {status: error, message:
        ...} with HTTP 200 instead. Once that lands this test starts passing
        and the marker must come off.
        """
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.patch(
                "/api/manage/role",
                json={"action": "remove", "role": "admin", "user": self.admin.id},
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "error")
            self.assertIsInstance(data["message"], str)
            self.assertGreater(len(data["message"]), 0)

    def test_manage_role_unauthenticated_returns_401(self):
        response = self.app.post("/api/manage/role", json={})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")


# ============================================================================
# Admin: /api/active_users, /api/health
# ============================================================================


class TestAdminContracts(FlaskTest):
    def test_health_returns_shape(self):
        response = self.app.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["database"], "connected")
        self.assertIn("timestamp", data)

    def test_active_users_unauthenticated_returns_401(self):
        response = self.app.get("/api/active_users")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["status"], "error")

    def test_active_users_returns_user_list(self):
        with self.app as ctx:
            self.login(ctx, self.admin)
            response = ctx.get("/api/active_users")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIsInstance(data, list)
            # Admin just logged in, so at least one active user
            self.assertGreater(len(data), 0)
            user = data[0]
            self.assertIn("username", user)
            self.assertIn("last_active", user)


# ============================================================================
# Manage-role group — Phase 17 legacy-compat guards.
# POST /api/manage/role is UNTOUCHED in Phase 17 (endpoint split);
# these tests pin the legacy contract so the v2 work can never regress it.
# The untouched route returns HTTP 200 with a status/message body — the
# denial signal is {"status": "error", "message": "forbidden"}, not an
# HTTP 403.
# ============================================================================


class TestManageRoleLegacyCompat(FlaskTest):
    def _victim(self):
        import utils.data_access as da

        return da.register_user("legacy-victim@example.com", "pass", username="legacy-victim")

    def test_manager_can_grant_manager_via_manage_role_in_own_gb(self):
        """Documented residual: legacy manager own-gb grants keep
        working — the earlier hardening stays reverted."""
        victim = self._victim()
        with self.app as ctx:
            self.login(ctx, self.manager)
            resp = ctx.post(
                "/api/manage/role",
                json={
                    "action": "add",
                    "role": "manager",
                    "user": victim.id,
                    "genebank": self.genebanks[0].id,
                },
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json()["status"], "updated")

    def test_manager_can_grant_viewer_via_manage_role_in_own_gb(self):
        victim = self._victim()
        with self.app as ctx:
            self.login(ctx, self.manager)
            resp = ctx.post(
                "/api/manage/role",
                json={
                    "action": "add",
                    "role": "viewer",
                    "user": victim.id,
                    "genebank": self.genebanks[0].id,
                },
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json()["status"], "updated")

    def test_manager_cannot_grant_admin_via_manage_role(self):
        """update_role() has never permitted managers to grant admin —
        unchanged legacy behaviour (denial via body, HTTP stays 200)."""
        victim = self._victim()
        with self.app as ctx:
            self.login(ctx, self.manager)
            resp = ctx.post(
                "/api/manage/role",
                json={"action": "add", "role": "admin", "user": victim.id},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "error")
            self.assertEqual(data["message"], "forbidden")

    def _manage_role(self, actor, **body):
        """POST /api/manage/role as `actor`; returns (status_code, json)."""
        with self.app as ctx:
            self.login(ctx, actor)
            resp = ctx.post("/api/manage/role", json=body)
        return resp.status_code, resp.get_json()

    def test_manager_cannot_grant_global_role_with_own_genebank_id(self):
        """The genebank in the body must not authorize admin or
        matrikel_admin — neither role has a genebank scope. Refusal keeps
        the route's HTTP 200 error envelope."""
        for role in ("admin", "matrikel_admin"):
            with self.subTest(role=role):
                status, body = self._manage_role(
                    self.manager,
                    action="add",
                    role=role,
                    user=self.manager.id,
                    genebank=self.genebanks[0].id,
                )
                after = db.User.get_by_id(self.manager.id)
                self.assertEqual((status, body), (200, {"status": "error", "message": "forbidden"}))
                self.assertFalse(after.has_role(role), f"manager became {role}: {after.privileges}")

    def test_manager_cannot_revoke_global_role_with_own_genebank_id(self):
        """A manager must not strip another user's admin or
        matrikel_admin by naming their own genebank."""
        other_admin = self._victim()  # second admin, so the last-admin guard is not what refuses
        other_admin.add_role("admin")
        other_admin.add_role("matrikel_admin")
        for role in ("admin", "matrikel_admin"):
            with self.subTest(role=role):
                status, body = self._manage_role(
                    self.manager,
                    action="remove",
                    role=role,
                    user=other_admin.id,
                    genebank=self.genebanks[0].id,
                )
                self.assertEqual((status, body), (200, {"status": "error", "message": "forbidden"}))
                self.assertTrue(db.User.get_by_id(other_admin.id).has_role(role))

    def test_manager_cannot_grant_owner_on_foreign_herd_with_own_genebank_id(self):
        """For owner the scope is the herd's real genebank — a genebank
        named in the body must not stand in for it."""
        victim = self._victim()
        foreign_herd = self.herds[2]  # genebanks[1]; the manager only manages genebanks[0]
        self.assertEqual(foreign_herd.genebank_id, self.genebanks[1].id)
        refused = {"status": "error", "message": "forbidden"}
        for extra in ({}, {"genebank": self.genebanks[0].id}):
            with self.subTest(extra=extra):
                status, body = self._manage_role(
                    self.manager, action="add", role="owner", user=victim.id, herd=foreign_herd.id, **extra
                )
                self.assertEqual((status, body), (200, refused))
                self.assertFalse(db.User.get_by_id(victim.id).has_role("owner", foreign_herd.id))

    def test_manager_cannot_grant_owner_with_non_integer_herd_id(self):
        """The herd that is authorized must be the herd that is stored.
        Peewee's Herd.get("<id>") reads a str as a SQL condition and returned
        the first herd, which the manager did manage, while the str itself was
        stored and later coerced to the foreign herd's id."""
        victim = self._victim()
        foreign_id = self.herds[2].id  # genebanks[1]; the manager only manages genebanks[0]
        for herd in (str(foreign_id), float(foreign_id), [foreign_id]):
            for extra in ({}, {"genebank": self.genebanks[0].id}):
                with self.subTest(herd=herd, extra=extra):
                    status, body = self._manage_role(
                        self.manager, action="add", role="owner", user=victim.id, herd=herd, **extra
                    )
                    self.assertEqual(status, 200)
                    self.assertEqual(body["status"], "error")
                    self.assertEqual(db.User.get_by_id(victim.id).privileges, [])

    def test_manager_cannot_grant_owner_via_str_herd_id_that_resolves_to_another_herd(self):
        """The exact exploit: Postgres reads WHERE '1' as true, so
        Herd.get("1") returned the first row, a herd the manager manages,
        while "1" was stored and later meant herd 1, now in another genebank.
        (The UPDATE moves herd 1 to the end of the heap so another herd is first.)"""
        moved = self.herds[0]
        self.assertEqual(moved.id, 1)
        moved.genebank = self.genebanks[1]
        moved.save()
        victim = self._victim()
        status, body = self._manage_role(self.manager, action="add", role="owner", user=victim.id, herd="1")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "error")
        self.assertEqual(db.User.get_by_id(victim.id).privileges, [])

    def test_non_integer_ids_are_malformed_for_admins_too(self):
        """The ids that scope a role must be integers for every caller (the
        v2 endpoint already requires it); the refusal is the 200 envelope."""
        victim = self._victim()
        gb = self.genebanks[0].id
        for body in (
            {"role": "owner", "herd": str(self.herds[0].id)},
            {"role": "owner", "herd": True},
            {"role": "manager", "genebank": str(gb)},
            {"role": "viewer", "genebank": float(gb)},
        ):
            with self.subTest(body=body):
                status, resp = self._manage_role(self.admin, action="add", user=victim.id, **body)
                self.assertEqual((status, resp), (200, {"status": "error", "message": "malformed request"}))
        self.assertEqual(db.User.get_by_id(victim.id).privileges, [])

    def test_manager_cannot_grant_role_with_integral_float_genebank(self):
        """1.0 == 1, so a float genebank passed the manager's scope check and
        was then stored as 1.0."""
        victim = self._victim()
        status, body = self._manage_role(
            self.manager, action="add", role="viewer", user=victim.id, genebank=float(self.genebanks[0].id)
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "error")
        self.assertEqual(db.User.get_by_id(victim.id).privileges, [])

    def test_manager_cannot_revoke_owner_on_foreign_herd_with_own_genebank_id(self):
        """A manager cannot revoke an owner role on a foreign herd by passing their own genebank id."""
        victim = self._victim()
        foreign_herd = self.herds[2]
        victim.add_role("owner", foreign_herd.id)
        status, body = self._manage_role(
            self.manager,
            action="remove",
            role="owner",
            user=victim.id,
            herd=foreign_herd.id,
            genebank=self.genebanks[0].id,
        )
        self.assertEqual((status, body), (200, {"status": "error", "message": "forbidden"}))
        self.assertTrue(db.User.get_by_id(victim.id).has_role("owner", foreign_herd.id))

    def test_manager_cannot_grant_owner_on_unknown_herd_with_own_genebank_id(self):
        """The herd must exist — no dangling owner entry via a body genebank."""
        victim = self._victim()
        status, body = self._manage_role(
            self.manager, action="add", role="owner", user=victim.id, herd=999999, genebank=self.genebanks[0].id
        )
        self.assertEqual((status, body["status"]), (200, "error"))
        self.assertEqual(db.User.get_by_id(victim.id).privileges, [])
        victim.add_role("owner", 999999)
        status, body = self._manage_role(self.manager, action="remove", role="owner", user=victim.id, herd=999999)
        self.assertEqual((status, body["status"]), (200, "error"))
        self.assertTrue(db.User.get_by_id(victim.id).has_role("owner", 999999))

    def test_manager_with_null_scope_cannot_write_dangling_owner(self):
        """An unknown herd has no genebank (None); a stored manager entry
        with a null genebank must not match it."""
        self.manager.privileges = self.manager.privileges + [{"level": "manager", "genebank": None}]
        self.manager.save()
        victim = self._victim()
        for action in ("add", "remove"):
            with self.subTest(action=action):
                status, body = self._manage_role(self.manager, action=action, role="owner", user=victim.id, herd=999999)
                self.assertEqual((status, body["status"]), (200, "error"))
                self.assertEqual(db.User.get_by_id(victim.id).privileges, [])

    def test_manager_can_grant_owner_on_own_gb_herd(self):
        """The legacy SPA sends herd only; a body genebank, matching or not,
        must not change that."""
        for i, extra in enumerate(({}, {"genebank": self.genebanks[0].id}, {"genebank": self.genebanks[1].id})):
            with self.subTest(extra=extra):
                victim = da.register_user(f"owner-target-{i}@ex.se", "pass", username=f"owner-target-{i}")
                status, body = self._manage_role(
                    self.manager, action="add", role="owner", user=victim.id, herd=self.herds[0].id, **extra
                )
                self.assertEqual((status, body), (200, {"status": "updated"}))
                self.assertTrue(db.User.get_by_id(victim.id).has_role("owner", self.herds[0].id))

    def test_admin_who_is_also_manager_can_remove_dangling_owner_entry(self):
        """An unknown herd has no genebank to scope by; admin cleanup must
        work for an admin who also holds manager, as it does for a plain admin."""
        self.admin.add_role("manager", self.genebanks[0].id)
        for extra in ({}, {"genebank": self.genebanks[0].id}):
            with self.subTest(extra=extra):
                victim = da.register_user(f"dangling-{len(extra)}@ex.se", "pass", username=f"dangling-{len(extra)}")
                victim.add_role("owner", 999999)
                status, body = self._manage_role(
                    self.admin, action="remove", role="owner", user=victim.id, herd=999999, **extra
                )
                self.assertEqual((status, body), (200, {"status": "updated"}))
                self.assertEqual(db.User.get_by_id(victim.id).privileges, [])

    def test_admin_who_is_also_manager_can_grant_owner_on_any_herd(self):
        victim = self._victim()
        self.admin.add_role("manager", self.genebanks[0].id)
        status, body = self._manage_role(
            self.admin,
            action="add",
            role="owner",
            user=victim.id,
            herd=self.herds[2].id,
            genebank=self.genebanks[0].id,
        )
        self.assertEqual((status, body), (200, {"status": "updated"}))
        self.assertTrue(db.User.get_by_id(victim.id).has_role("owner", self.herds[2].id))

    def test_admin_can_grant_global_role_with_genebank_in_body(self):
        """The legacy SPA sends genebank (-1 when none is picked) with every
        non-owner role, admin included — admins must keep working."""
        victim = self._victim()
        for role in ("admin", "matrikel_admin"):
            with self.subTest(role=role):
                status, body = self._manage_role(self.admin, action="add", role=role, user=victim.id, genebank=-1)
                self.assertEqual((status, body), (200, {"status": "updated"}))
                self.assertTrue(db.User.get_by_id(victim.id).has_role(role))

    def test_admin_who_is_also_manager_can_grant_global_role(self):
        victim = self._victim()
        self.admin.add_role("manager", self.genebanks[0].id)
        status, body = self._manage_role(
            self.admin, action="add", role="matrikel_admin", user=victim.id, genebank=self.genebanks[0].id
        )
        self.assertEqual((status, body), (200, {"status": "updated"}))
        self.assertTrue(db.User.get_by_id(victim.id).has_role("matrikel_admin"))

    def test_manager_cannot_grant_role_in_other_gb(self):
        victim = self._victim()
        with self.app as ctx:
            self.login(ctx, self.manager)
            resp = ctx.post(
                "/api/manage/role",
                json={
                    "action": "add",
                    "role": "manager",
                    "user": victim.id,
                    "genebank": self.genebanks[1].id,
                },
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "error")
            self.assertEqual(data["message"], "forbidden")


# ============================================================================
# Legacy-host compatibility (utils/legacy_compat.py)
# ============================================================================


class TestLegacyHostCompat(FlaskTest):
    """Behaviour that differs by request host.

    The legacy frontend and v2 share one Flask backend, so `is_legacy_host()`
    is what keeps a restored old contract away from the v2 hosts.
    """

    LEGACY_BASE = "https://stamboken.gotlandskaninen.se"
    V2_BASE = "https://gotlandskaninen.se"

    def test_is_legacy_host_true_for_legacy_vhost(self):
        with APP.test_request_context(base_url=self.LEGACY_BASE):
            self.assertTrue(is_legacy_host())

    def test_is_legacy_host_true_ignoring_port(self):
        with APP.test_request_context(base_url="https://test.gotlandskaninen.se:8443"):
            self.assertTrue(is_legacy_host())

    def test_is_legacy_host_false_for_v2_host(self):
        with APP.test_request_context(base_url=self.V2_BASE):
            self.assertFalse(is_legacy_host())

    def test_is_legacy_host_follows_x_forwarded_host(self):
        """Fix round 1, item 5 — documents WHY nginx must set X-Forwarded-Host itself.

        ProxyFix runs with x_host=1 (herdbook.py:97), so request.host is taken from
        X-Forwarded-Host when present. A client could therefore pick the legacy branch on
        a v2 host unless the proxy overwrites the header. Every `location /api/` and
        `/api-test/` block in nginx/production/herdbook-production.conf now sets
        `proxy_set_header X-Forwarded-Host $host;` (plus X-Forwarded-Port), which is the
        guard — this test pins the behaviour that makes it necessary.
        """
        response = self.app.post(
            "/api/login",
            json={"username": "wrong", "password": "wrong"},
            base_url=self.V2_BASE,
            headers={"X-Forwarded-Host": "stamboken.gotlandskaninen.se"},
        )
        # Legacy contract, chosen purely by the forwarded header.
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json())

    def _deactivate(self, user):
        import utils.database as db

        row = db.User.get_by_id(user.id)
        row.is_active = False
        row.save()

    def test_inactive_account_login_returns_null_on_legacy_host(self):
        """Fix round 1, item 3: the InactiveAccountError branch returned a truthy 401 object,
        which legacy's handleLogin reads as a logged-in user — exactly the failure ruling 7
        addresses. On a legacy host it now answers the old 200 + null; the account is still
        refused, no session is created."""
        self._deactivate(self.viewer)
        response = self.app.post(
            "/api/login",
            json={"username": self.viewer.email, "password": "pass"},
            base_url=self.LEGACY_BASE,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json())

    def test_inactive_account_login_keeps_401_on_v2_host(self):
        """v2 keeps the explicit 401 so its UI can say why the login failed."""
        self._deactivate(self.viewer)
        response = self.app.post(
            "/api/login",
            json={"username": self.viewer.email, "password": "pass"},
            base_url=self.V2_BASE,
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("inaktiverat", response.get_json()["message"])

    def _google_login_not_validated(self, base_url):
        """Drive /api/login/google to the "user exists but is not validated" branch."""
        user = da.register_user("okurs@example.com", "pass", username="okurs", validated=False)
        with (
            mock.patch("herdbook._should_auto_validate_users", return_value=False),
            mock.patch("utils.external_auth.authorized", return_value=True),
            mock.patch("utils.external_auth.get_persistent", return_value="persistent-id"),
            mock.patch("utils.data_access.authenticate_with_credentials", return_value=user),
        ):
            return APP.test_client().get("/api/login/google", base_url=base_url)

    def test_non_validated_google_login_redirects_to_classroom_on_legacy_host(self):
        """Inventory rows: GET /api/login/google (3 rows) — BROKEN, fixed.

        Old production answered a non-validated Google login with a redirect to the
        Classroom course; the new text response left the
        legacy frontend on a blank page.
        """
        response = self._google_login_not_validated(self.LEGACY_BASE)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], legacy_classroom_url())

    def test_non_validated_google_login_keeps_text_on_v2_host(self):
        """v2 onboards in-app, so its hosts keep the current text response."""
        response = self._google_login_not_validated(self.V2_BASE)
        self.assertEqual(response.status_code, 200)
        self.assertIn("validerad", response.data.decode())


if __name__ == "__main__":
    unittest.main()
