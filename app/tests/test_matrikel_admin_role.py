"""Tests for the matrikel_admin privilege level (Member Model v2)."""

import json
from datetime import datetime

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402

# Disable rate limiting in tests — the matrix class logs in more than
# 5 times/minute when the file runs in isolation (see Test Conventions).
limiter.enabled = False


class TestMatrikelAdminRolePlumbing(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.matrikel_user = da.register_user("matrikel", "pass")
        self.matrikel_user.add_role("matrikel_admin", None)

    def test_add_role_persists_matrikel_admin(self):
        user = db.User.get_by_id(self.matrikel_user.id)
        self.assertIn({"level": "matrikel_admin"}, user.privileges)

    def test_has_role(self):
        self.assertTrue(self.matrikel_user.has_role("matrikel_admin"))
        self.assertFalse(self.owner.has_role("matrikel_admin"))

    def test_remove_role(self):
        self.matrikel_user.remove_role("matrikel_admin", None)
        user = db.User.get_by_id(self.matrikel_user.id)
        self.assertNotIn({"level": "matrikel_admin"}, user.privileges)
        self.assertFalse(user.has_role("matrikel_admin"))

    def test_is_matrikel_admin_property(self):
        self.assertTrue(self.matrikel_user.is_matrikel_admin)
        self.assertFalse(self.admin.is_matrikel_admin)
        self.assertFalse(self.manager.is_matrikel_admin)
        self.assertFalse(self.owner.is_matrikel_admin)

    def test_frontend_data_flag(self):
        self.assertTrue(self.matrikel_user.frontend_data()["is_matrikel_admin"])
        self.assertFalse(self.owner.frontend_data()["is_matrikel_admin"])

    def test_update_role_admin_can_grant_and_revoke(self):
        op = {"action": "add", "role": "matrikel_admin", "user": self.viewer.id}
        self.assertEqual(da.update_role(op, self.admin.uuid)["status"], "updated")
        self.assertTrue(db.User.get_by_id(self.viewer.id).has_role("matrikel_admin"))
        op["action"] = "remove"
        self.assertEqual(da.update_role(op, self.admin.uuid)["status"], "updated")
        self.assertFalse(db.User.get_by_id(self.viewer.id).has_role("matrikel_admin"))

    def test_update_role_manager_cannot_grant(self):
        op = {"action": "add", "role": "matrikel_admin", "user": self.viewer.id}
        result = da.update_role(op, self.manager.uuid)
        self.assertEqual(result, {"status": "error", "message": "forbidden"})
        self.assertFalse(db.User.get_by_id(self.viewer.id).has_role("matrikel_admin"))

    def test_matrikel_admin_has_no_studbook_rights(self):
        self.assertFalse(self.matrikel_user.is_admin)
        self.assertIsNone(self.matrikel_user.is_manager)
        self.assertEqual(self.matrikel_user.accessible_genebanks, [])
        # ... and cannot manage roles (update_role requires admin/manager).
        op = {"action": "add", "role": "owner", "user": self.viewer.id, "herd": self.herds[0].id}
        result = da.update_role(op, self.matrikel_user.uuid)
        self.assertEqual(result, {"status": "error", "message": "forbidden"})


class TestReviewerDecoratorMatrix(DatabaseTest):
    """Matrix: admin / matrikel_admin / manager / owner / anonymous against
    the five member-application reviewer endpoints."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.matrikel_user = da.register_user("matrikel", "pass")
        self.matrikel_user.add_role("matrikel_admin", None)
        ts = datetime.now()
        self.app_gb0 = db.MemberApplication.create(
            first_name="A",
            last_name="A",
            email="a@a.example.com",
            genebank=self.genebanks[0],
            gdpr_consented_at=ts,
            status="pending",
        )
        self.app_gb1 = db.MemberApplication.create(
            first_name="B",
            last_name="B",
            email="b@b.example.com",
            genebank=self.genebanks[1],
            gdpr_consented_at=ts,
            status="pending",
        )

    def login(self, username):  # nosemgrep: hardcoded-password-default-argument
        self.client.post("/api/login", json={"username": username, "password": "pass"})

    def test_anonymous_gets_401_everywhere(self):
        self.assertEqual(self.client.get("/api/v2/member-applications").status_code, 401)
        self.assertEqual(self.client.get("/api/v2/member-applications/count").status_code, 401)
        self.assertEqual(self.client.get(f"/api/v2/member-applications/{self.app_gb0.id}").status_code, 401)
        self.assertEqual(self.client.post(f"/api/v2/member-applications/{self.app_gb0.id}/approve").status_code, 401)
        self.assertEqual(self.client.post(f"/api/v2/member-applications/{self.app_gb0.id}/reject").status_code, 401)

    def test_owner_gets_403_everywhere(self):
        self.login("owner")
        self.assertEqual(self.client.get("/api/v2/member-applications").status_code, 403)
        self.assertEqual(self.client.get("/api/v2/member-applications/count").status_code, 403)
        self.assertEqual(self.client.get(f"/api/v2/member-applications/{self.app_gb0.id}").status_code, 403)
        self.assertEqual(self.client.post(f"/api/v2/member-applications/{self.app_gb0.id}/approve").status_code, 403)
        self.assertEqual(self.client.post(f"/api/v2/member-applications/{self.app_gb0.id}/reject").status_code, 403)

    def test_manager_sees_whole_queue(self):
        # Gene banks were removed from applications — no scoping left.
        self.login("man")
        ids = [a["id"] for a in self.client.get("/api/v2/member-applications").get_json()["items"]]
        self.assertIn(self.app_gb0.id, ids)
        self.assertIn(self.app_gb1.id, ids)
        self.assertEqual(self.client.get(f"/api/v2/member-applications/{self.app_gb1.id}").status_code, 200)

    def test_matrikel_admin_sees_whole_queue(self):
        self.login("matrikel")
        resp = self.client.get("/api/v2/member-applications")
        self.assertEqual(resp.status_code, 200, resp.data)
        ids = [a["id"] for a in resp.get_json()["items"]]
        self.assertIn(self.app_gb0.id, ids)
        self.assertIn(self.app_gb1.id, ids)
        resp = self.client.get("/api/v2/member-applications/count")
        self.assertEqual(resp.get_json(), {"pending": 2})
        self.assertEqual(self.client.get(f"/api/v2/member-applications/{self.app_gb1.id}").status_code, 200)

    def test_matrikel_admin_can_approve(self):
        self.login("matrikel")
        resp = self.client.post(f"/api/v2/member-applications/{self.app_gb1.id}/approve")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIsNotNone(resp.get_json()["created_member_id"])
        app_row = db.MemberApplication.get_by_id(self.app_gb1.id)
        self.assertEqual(app_row.status, "approved")
        self.assertEqual(app_row.reviewed_by_id, self.matrikel_user.id)

    def test_matrikel_admin_can_reject(self):
        self.login("matrikel")
        resp = self.client.post(
            f"/api/v2/member-applications/{self.app_gb0.id}/reject",
            data=json.dumps({"rejection_reason": "Testavslag"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(db.MemberApplication.get_by_id(self.app_gb0.id).status, "rejected")
