"""Scoped /api/manage/herd endpoints."""

import utils.database as db
from herdbook import APP, limiter

from tests.database_test import DatabaseTest

# Disable rate limiting — multiple login() calls in quick succession
# would hit the 5/minute limit on /api/login and cause 429s.
limiter.enabled = False


class TestManageHerdScoped(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.post("/api/login", json={"username": username, "password": password})

    def test_manage_herd_list_admin_returns_paginated(self):
        self.login("admin", "pass")
        resp = self.client.get("/api/manage/herd?page=1&page_size=2")
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json()
        self.assertEqual(body["total"], 3)  # fixture seeds exactly 3 herds
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["page_size"], 2)
        self.assertEqual(len(body["herds"]), 2)
        row = body["herds"][0]
        for key in (
            "id",
            "herd",
            "herd_name",
            "name",
            "is_active",
            "genebank_id",
            "genebank_name",
            "owner_usernames",
        ):
            self.assertIn(key, row, f"missing key {key}")
        self.assertIsInstance(row["owner_usernames"], list)

    def test_manage_herd_list_search_filters(self):
        self.login("admin", "pass")
        code = self.herds[0].herd
        resp = self.client.get(f"/api/manage/herd?q={code}")
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json()
        codes = [r["herd"] for r in body["herds"]]
        self.assertIn(code, codes)
        # Every returned row matches the needle in code, herd name or contact.
        needle = code.lower()
        for r in body["herds"]:
            haystack = f"{r['herd']} {r['herd_name'] or ''} {r['name'] or ''}".lower()
            self.assertIn(needle, haystack)

    def test_manage_herd_list_manager_gets_403(self):
        # Managers read their gb's herds via
        # /api/genebank/<gb_id>; the cross-gb list is admin-only.
        self.login("man", "pass")
        resp = self.client.get("/api/manage/herd")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("application/problem+json", resp.content_type)

    def test_manage_herd_detail_by_id(self):
        self.login("admin", "pass")
        resp = self.client.get(f"/api/manage/herd/{self.herds[0].id}")
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json()
        for key in (
            "id",
            "herd",
            "herd_name",
            "name",
            "name_privacy",
            "physical_address",
            "email",
            "mobile_phone",
            "wire_phone",
            "www",
            "is_active",
            "genebank_id",
            "genebank_name",
            "owners",
        ):
            self.assertIn(key, body, f"missing key {key}")
        # Fixture: self.owner holds {"level": "owner", "herd": herds[0].id}.
        # (Fixture users have username=None — email is the login name —
        # so assert on the numeric id, not the username.)
        self.assertEqual([o["id"] for o in body["owners"]], [self.owner.id])
        self.assertEqual(body["genebank_id"], self.genebanks[0].id)

    def test_manage_herd_detail_by_code(self):
        # User-facing URLs carry the herd CODE (G1274) — the API resolves
        # both the code and the numeric id to the same herd.
        self.login("admin", "pass")
        resp = self.client.get(f"/api/manage/herd/{self.herds[0].herd}")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.get_json()["id"], self.herds[0].id)

    def test_manage_herd_numeric_code_resolves_by_code(self):
        # Nothing enforces letter-prefixed codes — an all-numeric legacy
        # code must resolve as ITSELF, never as another herd's primary
        # key (code lookup runs first).
        self.login("admin", "pass")
        numeric = db.Herd.create(genebank=self.genebanks[0], herd="9123", herd_name="Numerisk")
        try:
            resp = self.client.get("/api/manage/herd/9123")
            self.assertEqual(resp.status_code, 200, resp.data)
            self.assertEqual(resp.get_json()["id"], numeric.id)
            self.assertEqual(resp.get_json()["herd"], "9123")
        finally:
            numeric.delete_instance()

    def test_manage_herd_detail_two_owners(self):
        # A herd can have several owners (museum/family herds) — the
        # detail payload must list ALL of them.
        self.login("admin", "pass")
        entry = {"level": "owner", "herd": self.herds[0].id}
        second = self.manager
        second.privileges = second.privileges + [entry]
        second.save()
        try:
            resp = self.client.get(f"/api/manage/herd/{self.herds[0].id}")
            self.assertEqual(resp.status_code, 200, resp.data)
            ids = [o["id"] for o in resp.get_json()["owners"]]
            self.assertCountEqual(ids, [self.owner.id, second.id])
        finally:
            second.privileges = [p for p in second.privileges if p != entry]
            second.save()

    def test_manage_herd_detail_manager_own_gb_only(self):
        # NOTE: herds[0] and herds[1] are BOTH in genebanks[0] in the
        # DatabaseTest fixture — the cross-gb herd is herds[2] (Mellerud).
        self.login("man", "pass")
        resp_own = self.client.get(f"/api/manage/herd/{self.herds[0].id}")
        self.assertEqual(resp_own.status_code, 200, resp_own.data)
        resp_other = self.client.get(f"/api/manage/herd/{self.herds[2].id}")
        self.assertEqual(resp_other.status_code, 403)

    def test_manage_herd_patch_by_id_updates_and_audits(self):
        self.login("admin", "pass")
        resp = self.client.patch(
            f"/api/manage/herd/{self.herds[0].id}",
            json={"name": "NewName"},
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        h = db.Herd.get_by_id(self.herds[0].id)
        self.assertEqual(h.name, "NewName")
        row = (
            db.AuditLog.select()
            .where(
                (db.AuditLog.table_name == "herd")
                & (db.AuditLog.operation == "UPDATE")
                & (db.AuditLog.record_id == str(self.herds[0].id))
            )
            .order_by(db.AuditLog.changed_at.desc())
            .first()
        )
        self.assertIsNotNone(row)
        self.assertIn("name", row.changed_fields)

    def test_manage_herd_patch_rejects_unknown_privacy_value(self):
        self.login("admin", "pass")
        resp = self.client.patch(
            f"/api/manage/herd/{self.herds[0].id}",
            json={"name_privacy": "hemlig"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["type"], "invalid-field-value")
        self.assertEqual(db.Herd.get_by_id(self.herds[0].id).name_privacy, "private")

    def test_manage_herd_patch_accepts_valid_and_null_privacy(self):
        self.login("admin", "pass")
        for value in ("public", "authenticated", None):
            resp = self.client.patch(f"/api/manage/herd/{self.herds[0].id}", json={"name_privacy": value})
            self.assertEqual(resp.status_code, 200, resp.data)
            self.assertEqual(db.Herd.get_by_id(self.herds[0].id).name_privacy, value)

    def test_manage_herd_patch_rejects_unknown_fields(self):
        self.login("admin", "pass")
        resp = self.client.patch(
            f"/api/manage/herd/{self.herds[0].id}",
            json={"color": "red"},
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["type"], "unknown-fields")
        self.assertIn("color", body["detail"])
