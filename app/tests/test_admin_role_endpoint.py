"""POST /api/v2/admin/role.

The legacy /api/manage/role endpoint is UNTOUCHED in Phase 17; its
legacy-compat regression tests live in test_legacy_api_contracts.py.
"""

import os

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402

# Disable rate limiting — multiple login() calls in quick succession
# would hit the 5/minute limit on /api/login and cause 429s.
limiter.enabled = False


class TestV2AdminRoleEndpoint(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.victim = da.register_user("victim@example.com", "pass", username="victim")

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.get("/api/logout")
        self.client.post("/api/login", json={"username": username, "password": password})

    def _post_role(self, operation, user_id, role):
        return self.client.post(
            "/api/v2/admin/role",
            json={"operation": operation, "user_id": user_id, "role": role},
        )

    def test_admin_can_grant_all_roles_via_v2_admin_role(self):
        self.login("admin", "pass")
        grants = [
            {"level": "admin"},
            {"level": "matrikel_admin"},
            {"level": "manager", "genebank": self.genebanks[1].id},  # cross-gb OK for admin
            {"level": "viewer", "genebank": self.genebanks[0].id},
            {"level": "owner", "herd": self.herds[1].id},
        ]
        for role in grants:
            with self.subTest(role=role):
                resp = self._post_role("add", self.victim.id, role)
                self.assertEqual(resp.status_code, 200, resp.data)
                self.assertEqual(resp.get_json()["status"], "updated")
        privs = db.User.get_by_id(self.victim.id).privileges
        for role in grants:
            self.assertIn(role, privs)

    def test_panel_lists_and_revokes_matrikel_admin(self):
        """The panel that routes ALL role writes must show a
        matrikel_admin and be able to revoke the role."""
        matr = da.register_user("matr_r028", "pass")
        matr.add_role("matrikel_admin", None)
        self.login("admin", "pass")
        rows = self.client.get("/api/v2/admin/users?search=matr_r028").get_json()["users"]
        summary = [r["role_summary"] for r in rows if r["id"] == matr.id]
        resp = self._post_role("remove", matr.id, {"level": "matrikel_admin"})
        still_has = db.User.get_by_id(matr.id).has_role("matrikel_admin")
        self.assertEqual(
            (summary, resp.status_code, still_has),
            (["matrikel_admin"], 200, False),
            f"role_summary={summary}; remove -> {resp.status_code} {resp.get_json()}; still matrikel_admin={still_has}",
        )

    def test_v2_admin_role_rejects_matrikel_admin_with_extra_fields(self):
        self.login("admin", "pass")
        resp = self._post_role("add", self.victim.id, {"level": "matrikel_admin", "genebank": self.genebanks[0].id})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("extra fält", resp.get_json()["detail"])
        self.assertFalse(db.User.get_by_id(self.victim.id).has_role("matrikel_admin"))

    def test_manager_gets_403_on_v2_admin_role(self):
        """Even an OWN-GB manager grant — legal on legacy — is admin-only
        on the v2 surface."""
        self.login("man", "pass")
        resp = self._post_role(
            "add",
            self.victim.id,
            {"level": "manager", "genebank": self.genebanks[0].id},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.headers["Content-Type"], "application/problem+json")
        self.assertEqual(resp.get_json()["type"], "admin-required")

    def test_v2_admin_role_returns_problem_json_not_html(self):
        """Three auth states — machine-readable responses, never a redirect
        (retargeted from an earlier, reverted hardening)."""
        # Anonymous → 401 problem+json.
        resp = self._post_role("add", self.victim.id, {"level": "admin"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.headers["Content-Type"], "application/problem+json")
        self.assertEqual(resp.get_json()["type"], "authentication-required")
        self.assertIsNone(resp.headers.get("Location"))
        # Manager → 403 problem+json.
        self.login("man", "pass")
        resp = self._post_role("add", self.victim.id, {"level": "admin"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.headers["Content-Type"], "application/problem+json")
        self.assertIsNone(resp.headers.get("Location"))
        # Admin → 200 application/json.
        self.login("admin", "pass")
        resp = self._post_role("add", self.victim.id, {"level": "admin"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["Content-Type"].startswith("application/json"))

    def test_self_lockout_prevention(self):
        """As the ONLY admin, revoking own admin via the v2 endpoint → 409
        (delegates to the last-admin invariant in update_role)."""
        self.login("admin", "pass")
        resp = self._post_role("remove", self.admin.id, {"level": "admin"})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.headers["Content-Type"], "application/problem+json")
        body = resp.get_json()
        self.assertEqual(body["type"], "last-admin")
        self.assertEqual(body["title"], "Den sista administratörsrollen kan inte tas bort")
        admin = db.User.get_by_id(self.admin.id)
        self.assertTrue(any(p.get("level") == "admin" for p in admin.privileges))

    def test_v2_admin_role_rejects_malformed_role(self):
        self.login("admin", "pass")
        resp = self._post_role("add", self.victim.id, {"level": "root"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.headers["Content-Type"], "application/problem+json")
        self.assertIn("Okänd nivå", resp.get_json()["detail"])
