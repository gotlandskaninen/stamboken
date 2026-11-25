"""Scoped /api/manage/herd endpoints."""

import utils.data_access as da
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

    def test_manage_herd_list_manager_sees_only_own_genebank(self):
        # #214: the manager's herd page needs the same search and filters as
        # admin, so the list answers managers too, scoped to their genebanks.
        self.login("man", "pass")
        resp = self.client.get("/api/manage/herd")
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json()
        self.assertEqual(sorted(r["herd"] for r in body["herds"]), ["G1", "G2"])
        self.assertEqual(body["total"], 2)

    def test_manage_herd_list_manager_cannot_reach_other_genebank(self):
        self.login("man", "pass")
        other_gb = self.herds[2].genebank_id
        for query in (f"genebank_id={other_gb}", f"genebank_id={other_gb}&q=M3"):
            resp = self.client.get(f"/api/manage/herd?{query}")
            self.assertEqual(resp.status_code, 403, query)  # ADR-0014: a named genebank is checked
            self.assertIn("application/problem+json", resp.content_type)
            self.assertNotIn("M3", resp.get_data(as_text=True))
        resp = self.client.get("/api/manage/herd?q=M3")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual((resp.get_json()["total"], resp.get_json()["herds"]), (0, []))
        own = self.client.get(f"/api/manage/herd?genebank_id={self.herds[0].genebank_id}")
        self.assertEqual(own.get_json()["total"], 2)

    def test_manage_herd_list_viewer_owner_helper_and_matrikel_admin_get_403(self):
        da.register_user("helper", "pass").add_role("helper", self.genebanks[0].id)
        da.register_user("matrikel", "pass").add_role("matrikel_admin")
        for username in ("spec", "owner", "helper", "matrikel"):
            self.client = APP.test_client(use_cookies=True)
            self.login(username, "pass")
            resp = self.client.get("/api/manage/herd")
            self.assertEqual(resp.status_code, 403, username)
            self.assertIn("application/problem+json", resp.content_type)

    def _codes(self, query):
        body = self.client.get(f"/api/manage/herd?{query}").get_json()
        self.assertEqual(body["total"], len(body["herds"]), query)
        return {r["herd"]: r["owner_usernames"] for r in body["herds"]}

    def test_manage_herd_list_owner_includes_the_main_member_not_a_caretaker(self):
        # #214: an active main member with an account owns the membership's herd (transfer_herd_ids), a caretaker
        # with a grant does not — the owner column and both filters agree with that.
        membership = db.Membership.create(member_number=9)
        main = da.register_user("main@example.invalid", "pass", username="huvud")
        carer = da.register_user("carer@example.invalid", "pass", username="skotare")
        db.Member.create(membership=membership, first_name="A", last_name="B", role="huvudmedlem", user=main)
        family = db.Member.create(
            membership=membership, first_name="C", last_name="B", role="familjemedlem", user=carer
        )
        db.Herd.update(membership=membership).where(db.Herd.id == self.herds[1].id).execute()
        db.HerdAccessGrant.create(member=family, herd=self.herds[2], granted_by=self.admin)
        self.login("admin", "pass")

        self.assertEqual(self._codes("has_owner=true"), {"G1": ["owner"], "G2": ["huvud"]})
        self.assertEqual(self._codes("has_owner=false"), {"M3": []})
        detail = self.client.get(f"/api/manage/herd/{self.herds[1].herd}").get_json()
        self.assertEqual([o["username"] for o in detail["owners"]], ["huvud"])

    def test_manage_herd_list_inactive_includes_unknown_status(self):
        # A NULL is_active row shows as Inaktiv, so the Inaktiva filter finds it.
        db.Herd.update(is_active=None).where(db.Herd.id == self.herds[1].id).execute()
        db.Herd.update(is_active=True).where(db.Herd.id != self.herds[1].id).execute()
        self.login("admin", "pass")
        self.assertEqual(set(self._codes("active=false")), {"G2"})
        self.assertEqual(set(self._codes("active=true")), {"G1", "M3"})

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
