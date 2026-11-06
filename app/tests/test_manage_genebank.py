"""PATCH /api/manage/genebank/<gb_id>."""

import utils.database as db
from herdbook import APP, limiter

from tests.database_test import DatabaseTest

# Disable rate limiting — multiple login() calls in quick succession
# would hit the 5/minute limit on /api/login and cause 429s.
limiter.enabled = False


class TestManageGenebank(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.post("/api/login", json={"username": username, "password": password})

    def test_genebank_edit_admin_can_all_fields(self):
        self.login("admin", "pass")
        resp = self.client.patch(
            f"/api/manage/genebank/{self.genebanks[0].id}",
            json={"name": "Nytt namn"},
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        gb = db.Genebank.get_by_id(self.genebanks[0].id)
        self.assertEqual(gb.name, "Nytt namn")
        body = resp.get_json()
        self.assertEqual(body["name"], "Nytt namn")

    def test_genebank_edit_manager_own_gb_only(self):
        # Fixture: "man" is manager of genebanks[0] only.
        self.login("man", "pass")
        resp_own = self.client.patch(
            f"/api/manage/genebank/{self.genebanks[0].id}",
            json={"name": "Genbank ett"},
        )
        self.assertEqual(resp_own.status_code, 200, resp_own.data)
        resp_other = self.client.patch(
            f"/api/manage/genebank/{self.genebanks[1].id}",
            json={"name": "Försök"},
        )
        self.assertEqual(resp_other.status_code, 403)
        self.assertIn("application/problem+json", resp_other.content_type)

    def test_genebank_edit_audit_row_appears(self):
        self.login("admin", "pass")
        resp = self.client.patch(
            f"/api/manage/genebank/{self.genebanks[0].id}",
            json={"name": "Audit Test"},
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        row = (
            db.AuditLog.select()
            .where(
                (db.AuditLog.table_name == "genebank")
                & (db.AuditLog.operation == "UPDATE")
                & (db.AuditLog.record_id == str(self.genebanks[0].id))
            )
            .order_by(db.AuditLog.changed_at.desc())
            .first()
        )
        self.assertIsNotNone(row)
        self.assertIn("name", row.changed_fields)
        # register_user("admin", "pass") sets email="admin" (username is
        # None); before_request tags audit rows with username OR email.
        self.assertEqual(row.changed_by, "admin")

    def test_genebank_edit_rejects_unknown_fields(self):
        self.login("admin", "pass")
        resp = self.client.patch(
            f"/api/manage/genebank/{self.genebanks[0].id}",
            json={"color": "red"},
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body["type"], "unknown-fields")
        self.assertIn("color", body["detail"])
