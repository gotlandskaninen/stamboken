#!/usr/bin/env python3
"""
Tests for Flask Blueprint infrastructure (ADR-0007).

isort:skip_file
"""

import os
import unittest
from datetime import date, datetime
from unittest import mock

# Set configuration file for external accounts
os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from blueprints import register_blueprints  # noqa: E402
from blueprints.common import (  # noqa: E402
    check_genebank_access,
    json_error,
    json_login_required,
    login_required,
    manager_required,
)
from flask import Flask  # noqa: E402
from flask_login import LoginManager, UserMixin  # noqa: E402
from herdbook import APP, limiter  # noqa: E402
from utils.cert_service_v2 import assign_certificate_number  # noqa: E402
from utils.herd_tracking import BIRTH_HERD_CHANGED_REASON, replace_birth_row  # noqa: E402
from utils.individual_number_v2 import renumber_litters  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402
from tests.ht_helpers import ht_row  # noqa: E402
from tests.test_bunny_v2_api import paper_number_for  # noqa: E402

# Disable rate limiting in tests — multiple login() calls in quick succession
# would hit the 5/minute limit and cause 429 responses.
limiter.enabled = False


class TestBlueprintRegistration(unittest.TestCase):
    """Test that blueprints register without errors."""

    def test_arsrapport_blueprint_registered(self):
        """arsrapport blueprint should be registered on APP."""
        bp_names = [bp.name for bp in APP.iter_blueprints()]
        self.assertIn("arsrapport", bp_names)

    def test_tokens_blueprint_registered(self):
        """tokens blueprint should be registered on APP."""
        bp_names = [bp.name for bp in APP.iter_blueprints()]
        self.assertIn("tokens", bp_names)

    def test_register_blueprints_on_fresh_app(self):
        """register_blueprints should work on a new Flask app without errors."""
        app = Flask(__name__)
        register_blueprints(app)
        bp_names = [bp.name for bp in app.iter_blueprints()]
        self.assertIn("arsrapport", bp_names)
        self.assertIn("tokens", bp_names)

    def test_no_new_route_conflicts(self):
        """Blueprint registration should not introduce new duplicate routes."""
        from collections import Counter

        rules = [rule.rule for rule in APP.url_map.iter_rules()]
        dupes = {k: v for k, v in Counter(rules).items() if v > 1}
        # Only pre-existing duplicates allowed (not from our blueprints)
        for route in dupes:
            self.assertNotIn("/arsrapport/", route)
            self.assertNotIn("/tokens/", route)


class TestEndpointRegression(DatabaseTest):
    """Verify pre-existing endpoints still work after blueprint registration."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def test_health_endpoint_unchanged(self):
        """GET /api/health must still return 200 with expected JSON."""
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("status", data)

    def test_genebanks_endpoint_still_requires_auth(self):
        """GET /api/genebanks without auth must still require authentication."""
        response = self.client.get(
            "/api/genebanks",
            headers={"Accept": "application/json"},
        )
        # Endpoint requires login — should get 401 JSON (not 200 or 500)
        self.assertEqual(response.status_code, 401)

    def test_unauthenticated_user_endpoint_returns_json_401(self):
        """GET /api/user without auth must return JSON 401, not a redirect.

        This validates that login_required re-exported from common.py is the
        same Flask-Login login_required whose unauthorized_handler returns
        JSON 401 (configured in herdbook.py).
        """
        response = self.client.get(
            "/api/user",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 401)
        data = response.get_json()
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["message"], "Authentication required")


class TestSharedDecorators(unittest.TestCase):
    """Test that shared decorators in common.py work correctly."""

    def setUp(self):
        """Create a minimal Flask app with a test user for decorator testing."""
        self.app = Flask(__name__)
        self.app.secret_key = "test-secret"
        self.login_manager = LoginManager(self.app)

        class MockUser(UserMixin):
            def __init__(self, user_id, is_admin_val=False, is_manager_val=None):
                self.id = user_id
                self._is_admin = is_admin_val
                self._is_manager = is_manager_val

            @property
            def is_admin(self):
                return self._is_admin

            @property
            def is_manager(self):
                return self._is_manager

        self.MockUser = MockUser
        self._test_user = None

        @self.login_manager.user_loader
        def load_user(user_id):
            return self._test_user

        # Register test routes with decorators
        @self.app.route("/test-login-required")
        @login_required
        def protected():
            return "ok"

        @self.app.route("/test-json-login-required")
        @json_login_required
        def json_protected():
            return "json-ok"

        @self.app.route("/test-manager-required")
        @login_required
        @manager_required
        def manager_only():
            return "manager-ok"

        @self.app.route("/test-genebank-access/<int:genebank_id>")
        @login_required
        @manager_required
        def genebank_scoped(genebank_id):
            error = check_genebank_access(genebank_id)
            if error:
                return error
            return "genebank-ok"

    def test_login_required_rejects_anonymous(self):
        """login_required should reject unauthenticated requests."""
        with self.app.test_client() as client:
            response = client.get("/test-login-required")
            self.assertIn(response.status_code, [401, 302])

    def test_json_login_required_returns_401_problem(self):
        """json_login_required returns RFC 9457 problem+json 401 (ADR-0008)."""
        with self.app.test_client() as client:
            response = client.get("/test-json-login-required")
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.content_type, "application/problem+json")
            data = response.get_json()
            self.assertEqual(data["type"], "about:blank")
            self.assertEqual(data["title"], "Autentisering krävs")
            self.assertEqual(data["status"], 401)
            self.assertEqual(data["detail"], "Du måste vara inloggad.")

    def test_login_required_accepts_authenticated(self):
        """login_required should allow authenticated requests."""
        user = self.MockUser("1")
        self._test_user = user
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["_user_id"] = "1"
            response = client.get("/test-login-required")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"ok")

    def test_manager_required_rejects_regular_user(self):
        """manager_required returns RFC 9457 problem+json 403 for non-managers."""
        user = self.MockUser("1", is_admin_val=False, is_manager_val=None)
        self._test_user = user
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["_user_id"] = "1"
            response = client.get("/test-manager-required")
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.content_type, "application/problem+json")
            data = response.get_json()
            self.assertEqual(data["type"], "about:blank")
            self.assertEqual(data["title"], "Åtkomst nekad")
            self.assertEqual(data["status"], 403)
            self.assertEqual(data["detail"], "Du saknar behörighet för denna åtgärd.")

    def test_manager_required_accepts_manager(self):
        """manager_required should allow manager users."""
        user = self.MockUser("2", is_admin_val=False, is_manager_val=[1])
        self._test_user = user
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["_user_id"] = "2"
            response = client.get("/test-manager-required")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"manager-ok")

    def test_manager_required_accepts_admin(self):
        """manager_required should allow admin users."""
        user = self.MockUser("3", is_admin_val=True, is_manager_val=None)
        self._test_user = user
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["_user_id"] = "3"
            response = client.get("/test-manager-required")
            self.assertEqual(response.status_code, 200)

    def test_check_genebank_access_rejects_wrong_genebank(self):
        """check_genebank_access rejects a manager of another genebank with problem+json 403."""
        # Manager of genebank 1 tries to access genebank 2
        user = self.MockUser("4", is_admin_val=False, is_manager_val=[1])
        self._test_user = user
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["_user_id"] = "4"
            response = client.get("/test-genebank-access/2")
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.content_type, "application/problem+json")
            data = response.get_json()
            self.assertEqual(data["type"], "about:blank")
            self.assertEqual(data["title"], "Åtkomst nekad")
            self.assertEqual(data["status"], 403)
            self.assertEqual(data["detail"], "Du saknar behörighet för denna genbank.")

    def test_check_genebank_access_allows_correct_genebank(self):
        """check_genebank_access should allow a manager for the requested genebank."""
        user = self.MockUser("5", is_admin_val=False, is_manager_val=[1])
        self._test_user = user
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["_user_id"] = "5"
            response = client.get("/test-genebank-access/1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"genebank-ok")

    def test_check_genebank_access_allows_admin_any_genebank(self):
        """check_genebank_access should allow admin for any genebank."""
        user = self.MockUser("6", is_admin_val=True, is_manager_val=None)
        self._test_user = user
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["_user_id"] = "6"
            response = client.get("/test-genebank-access/99")
            self.assertEqual(response.status_code, 200)


class TestProblemHelper(unittest.TestCase):
    """Tests for RFC 9457 Problem Details helper. No DB needed."""

    def test_problem_returns_correct_structure(self):
        """problem() returns RFC 9457 body, status code, and content-type."""
        from blueprints.common import problem

        with APP.test_request_context():
            response, status, headers = problem(400, "Bad Request", "Invalid input")
            data = response.get_json()
            self.assertEqual(status, 400)
            self.assertEqual(data["type"], "about:blank")
            self.assertEqual(data["title"], "Bad Request")
            self.assertEqual(data["status"], 400)
            self.assertEqual(data["detail"], "Invalid input")
            self.assertEqual(headers["Content-Type"], "application/problem+json")

    def test_problem_with_extra_fields(self):
        """problem() passes through extra keyword arguments."""
        from blueprints.common import problem

        with APP.test_request_context():
            response, status, _ = problem(422, "Validation Error", "Field invalid", field="name")
            data = response.get_json()
            self.assertEqual(data["field"], "name")
            self.assertEqual(status, 422)

    def test_problem_404(self):
        """problem() works for 404 responses."""
        from blueprints.common import problem

        with APP.test_request_context():
            response, status, _ = problem(404, "Not Found", "Individual G9999 not found")
            self.assertEqual(status, 404)
            self.assertEqual(response.get_json()["detail"], "Individual G9999 not found")


class TestGetIndividualV2(DatabaseTest):
    """Tests for GET /api/v2/individual/<number> Blueprint v2 endpoint."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username, password):
        """Helper to login via the API."""
        self.client.post("/api/login", json={"username": username, "password": password})

    def test_get_requires_auth(self):
        """GET without session returns 401 JSON."""
        response = self.client.get(
            "/api/v2/individual/G1274-08001",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 401)

    def test_get_nonexistent_returns_404_problem(self):
        """GET on nonexistent individual returns RFC 9457 404 (not 200+null)."""
        self.login("admin", "pass")
        response = self.client.get("/api/v2/individual/DOESNOTEXIST")
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertEqual(data["type"], "about:blank")
        self.assertEqual(data["status"], 404)
        self.assertIn("detail", data)

    def test_get_success_returns_full_individual(self):
        """GET on valid individual returns 200 with full entity."""
        self.login("admin", "pass")
        individuals = self.client.get("/api/individuals?per_page=1")
        items = individuals.get_json().get("items", [])
        if not items:
            self.skipTest("No seed individuals available")
        number = items[0]["number"]

        response = self.client.get(f"/api/v2/individual/{number}")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("number", data)
        self.assertIn("name", data)
        self.assertIn("genebank_id", data)
        self.assertEqual(data["number"], number)

    def test_legacy_get_still_returns_null(self):
        """Legacy GET /api/individual/<n> still returns 200+null (ADR-0006)."""
        self.login("admin", "pass")
        response = self.client.get("/api/individual/DOESNOTEXIST")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json())


class TestUpdateIndividualV2(DatabaseTest):
    """Tests for PATCH /api/individual/<number> Blueprint v2 endpoint."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username, password):
        """Helper to login via the API."""
        res = self.client.post("/api/login", json={"username": username, "password": password})
        # Verify login succeeded — CI seed users use email as login, not username
        self.assertEqual(res.status_code, 200, f"Login failed for {username}")

    def test_patch_requires_auth(self):
        """PATCH without session returns 401 JSON."""
        response = self.client.patch(
            "/api/individual/G1274-08001",
            json={"name": "Updated"},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 401)

    def test_patch_empty_body_returns_400_problem(self):
        """PATCH with empty/missing body returns RFC 9457 400."""
        self.login("admin", "pass")
        individuals = self.client.get("/api/individuals?per_page=1")
        items = individuals.get_json().get("items", [])
        if not items:
            self.skipTest("No seed individuals available")
        number = items[0]["number"]

        response = self.client.patch(
            f"/api/individual/{number}",
            data="",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["type"], "about:blank")
        self.assertIn("detail", data)

    def test_patch_nonexistent_returns_404_problem(self):
        """PATCH on nonexistent individual returns RFC 9457 404."""
        self.login("admin", "pass")
        response = self.client.patch(
            "/api/individual/DOESNOTEXIST",
            json={"name": "Updated"},
        )
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertEqual(data["type"], "about:blank")
        self.assertEqual(data["status"], 404)
        self.assertIn("detail", data)

    def test_patch_success_returns_full_individual(self):
        """PATCH on valid individual returns 200 with full entity."""
        self.login("admin", "pass")
        # Use a known individual from seed data
        individuals = self.client.get("/api/individuals?per_page=1")
        items = individuals.get_json().get("items", [])
        if not items:
            self.skipTest("No seed individuals available")
        number = items[0]["number"]

        response = self.client.patch(
            f"/api/individual/{number}",
            json={"notes": "Test update via v2"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        # Should return full individual, not {"status": "success"}
        self.assertIn("number", data)
        self.assertIn("name", data)
        self.assertIn("genebank_id", data)
        self.assertEqual(data["number"], number)

    def test_patch_null_clears_death_fields(self):
        """PATCH with null death_date/death_note clears them (undo death)."""
        self.login("admin", "pass")
        individuals = self.client.get("/api/individuals?per_page=1")
        items = individuals.get_json().get("items", [])
        if not items:
            self.skipTest("No seed individuals available")
        number = items[0]["number"]

        # First set death fields
        self.client.patch(
            f"/api/individual/{number}",
            json={"death_date": "2026-01-01", "death_note": "Test death"},
        )

        # Now clear them (undo death)
        response = self.client.patch(
            f"/api/individual/{number}",
            json={"death_date": None, "death_note": None, "butchered": False},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsNone(data.get("death_date"))
        self.assertIsNone(data.get("death_note"))

    def test_patch_error_returns_problem_details(self):
        """PATCH with invalid data returns RFC 9457 error."""
        self.login("admin", "pass")
        response = self.client.patch(
            "/api/individual/DOESNOTEXIST",
            json={"name": "Test"},
        )
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertEqual(data["type"], "about:blank")
        self.assertIn("title", data)
        self.assertIn("detail", data)

    def test_legacy_patch_still_works(self):
        """Legacy PATCH /api/individual unchanged (ADR-0006 regression)."""
        self.login("admin", "pass")
        individuals = self.client.get("/api/individuals?per_page=1")
        items = individuals.get_json().get("items", [])
        if not items:
            self.skipTest("No seed individuals available")
        number = items[0]["number"]

        # Get the individual ID for legacy endpoint
        ind_data = self.client.get(f"/api/individual/{number}")
        ind = ind_data.get_json()
        if not ind:
            self.skipTest("Could not load individual")

        herd = ind.get("herd", {})
        herd_code = herd.get("herd", "") if isinstance(herd, dict) else ""
        response = self.client.patch(
            "/api/individual",
            json={"id": ind["id"], "number": number, "herd": herd_code, "notes": "Legacy test"},
        )
        # Legacy returns 200 with {"status": "success"} or similar
        self.assertEqual(response.status_code, 200)


class TestJsonError(unittest.TestCase):
    """Test the json_error helper function."""

    def test_json_error_default_status(self):
        """json_error should return 400 by default."""
        app = Flask(__name__)
        with app.app_context():
            response, status = json_error("bad request")
            self.assertEqual(status, 400)
            data = response.get_json()
            self.assertEqual(data["status"], "error")
            self.assertEqual(data["message"], "bad request")

    def test_json_error_custom_status(self):
        """json_error should accept custom status codes."""
        app = Flask(__name__)
        with app.app_context():
            response, status = json_error("not found", 404)
            self.assertEqual(status, 404)

    def test_json_error_matches_project_format(self):
        """json_error output should match the project's standard JSON error format."""
        app = Flask(__name__)
        with app.app_context():
            response, _ = json_error("Åtkomst nekad", 403)
            data = response.get_json()
            self.assertIn("status", data)
            self.assertIn("message", data)
            self.assertEqual(data["status"], "error")


_USE_POSTGRES = bool(os.getenv("POSTGRES_HOST")) and bool(os.getenv("POSTGRES_DB"))


@unittest.skipUnless(_USE_POSTGRES, "Audit endpoints require PostgreSQL")
class TestAuditBlueprint(DatabaseTest):
    """Tests for audit log Blueprint endpoints (ADR-0007)."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        # Clear audit entries from insert_default()
        db.DATABASE.execute_sql("TRUNCATE audit_log RESTART IDENTITY")

    def login(self, username, password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.post("/api/login", json={"username": username, "password": password})

    def _get_audit_entry(self, table_name, record_id):
        """Get the most recent audit entry for a specific record."""
        return (
            db.AuditLog.select()
            .where(db.AuditLog.table_name == table_name)
            .where(db.AuditLog.record_id == str(record_id))
            .order_by(db.AuditLog.id.desc())
            .first()
        )

    def _get_latest_hbuser_update(self):
        """Get the most recent UPDATE audit entry for hbuser."""
        return (
            db.AuditLog.select()
            .where(db.AuditLog.table_name == "hbuser")
            .where(db.AuditLog.operation == "UPDATE")
            .order_by(db.AuditLog.id.desc())
            .first()
        )

    # --- GET /api/audit-log/<table>/<record_id> ---

    def test_get_audit_history_as_admin(self):
        """Admin can fetch audit history for an individual."""
        self.login("admin")
        ind = self.individuals[0]
        ind.name = "AuditHistoryTest"
        ind.save()

        response = self.client.get(f"/api/audit-log/individual/{ind.id}")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIsInstance(data["data"], list)
        self.assertGreater(len(data["data"]), 0)

    def test_get_audit_history_omits_editor_ip_address(self):
        """The editor's IP is PII (purge_user_audit_pii NULLs it, the admin reader
        omits it): neither a genebank manager nor an admin gets it per record."""
        ind = self.individuals[0]
        db.DATABASE.execute_sql("SELECT set_config('audit.ip', '203.0.113.9', false)")
        try:
            ind.name = "R025"
            ind.save()
        finally:
            db.DATABASE.execute_sql("SELECT set_config('audit.ip', '', false)")
        # precondition: the trigger stamped the editor's address
        self.assertEqual(self._get_audit_entry("individual", ind.id).ip_address, "203.0.113.9")

        for username in ("man", "admin"):
            # Fresh client per role: /api/login keeps an already-authenticated session.
            self.client = APP.test_client(use_cookies=True)
            self.login(username)
            self.assertEqual(self.client.get("/api/user").get_json()["email"], username)
            response = self.client.get(f"/api/audit-log/individual/{ind.id}")
            self.assertEqual(response.status_code, 200)
            entries = response.get_json()["data"]
            self.assertGreater(len(entries), 0)
            for entry in entries:
                self.assertNotIn("ip_address", entry, username)

    def test_get_audit_history_for_bunny(self):
        """Admin can fetch bunny audit history (genebank resolved via breeding)."""
        self.login("admin")
        bunny = db.Bunny.create(breeding=self.breeding[0], slot_order=1)
        bunny.observed_color = "vit"
        bunny.save()

        response = self.client.get(f"/api/audit-log/bunny/{bunny.id}")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertGreater(len(data["data"]), 0)

    def test_get_audit_history_403_for_viewer(self):
        """Viewer (non-manager) gets 403 on audit history."""
        self.login("spec")
        response = self.client.get(f"/api/audit-log/individual/{self.individuals[0].id}")
        self.assertEqual(response.status_code, 403)

    def test_get_audit_history_403_wrong_genebank(self):
        """Manager of genebank A gets 403 for individual in genebank B."""
        self.login("man")  # manager of genebanks[0] (Gotland)
        # individuals[2] is in herds[2] which belongs to genebanks[1] (Mellerud)
        response = self.client.get(f"/api/audit-log/individual/{self.individuals[2].id}")
        self.assertEqual(response.status_code, 403)

    def test_revert_403_wrong_genebank(self):
        """Manager cannot revert audit entries for records in another genebank."""
        ind = self.individuals[2]  # Mellerud genebank
        ind.name = "CrossGBRevertTest"
        ind.save()

        entry = self._get_audit_entry("individual", ind.id)
        self.assertIsNotNone(entry, "Expected audit entry for Mellerud individual")

        self.login("man")  # manager of Gotland (wrong genebank)
        response = self.client.post(f"/api/audit-log/{entry.id}/revert")
        self.assertEqual(response.status_code, 403)

    def test_get_audit_history_401_unauthenticated(self):
        """Unauthenticated request gets 401."""
        response = self.client.get(f"/api/audit-log/individual/{self.individuals[0].id}")
        self.assertEqual(response.status_code, 401)

    def test_get_audit_history_invalid_table(self):
        """Invalid table name returns 400."""
        self.login("admin")
        response = self.client.get("/api/audit-log/nonexistent/1")
        self.assertEqual(response.status_code, 400)

    def test_hbuser_audit_requires_admin(self):
        """Manager (non-admin) gets 403 for hbuser audit history."""
        self.login("man")
        response = self.client.get(f"/api/audit-log/hbuser/{self.admin.id}")
        self.assertEqual(response.status_code, 403)

    def test_hbuser_audit_allowed_for_admin(self):
        """Admin can read hbuser audit history."""
        self.login("admin")
        response = self.client.get(f"/api/audit-log/hbuser/{self.admin.id}")
        self.assertEqual(response.status_code, 200)

    # --- POST /api/audit-log/<audit_id>/revert ---

    def test_revert_restores_old_value(self):
        """Revert an UPDATE entry restores the old field value."""
        self.login("admin")
        ind = self.individuals[0]
        old_name = ind.name
        ind.name = "RevertTest"
        ind.save()

        entry = self._get_audit_entry("individual", ind.id)
        self.assertIsNotNone(entry, "Expected audit entry after name change")

        response = self.client.post(f"/api/audit-log/{entry.id}/revert")
        self.assertEqual(response.status_code, 200)

        refreshed = db.Individual.get_by_id(ind.id)
        self.assertEqual(refreshed.name, old_name)

    def test_revert_blocked_on_hbuser(self):
        """Revert on hbuser table is blocked (privilege escalation)."""
        self.login("admin")
        self.manager.email = "changed@test.example.com"
        self.manager.save()

        entry = self._get_latest_hbuser_update()
        if not entry:
            self.skipTest("No hbuser audit entry generated")

        response = self.client.post(f"/api/audit-log/{entry.id}/revert")
        self.assertEqual(response.status_code, 403)

    def test_revert_rejects_fields_not_in_changed_fields(self):
        """Revert with fields not in changed_fields returns 400."""
        self.login("admin")
        ind = self.individuals[0]
        ind.name = "FieldTamperTest"
        ind.save()

        entry = self._get_audit_entry("individual", ind.id)
        self.assertIsNotNone(entry)

        response = self.client.post(
            f"/api/audit-log/{entry.id}/revert",
            json={"fields": ["origin_herd_id"]},
        )
        self.assertEqual(response.status_code, 400)

    def _renamed_individual(self, name):
        ind = db.Individual.get_by_id(self.individuals[0].id)
        old_name = ind.name
        ind.name = name
        ind.save()
        return ind, old_name, self._get_audit_entry("individual", ind.id)

    def test_revert_with_json_content_type_and_empty_body(self):
        """fetchApi sends Content-Type: application/json even without a body.
        The v2 'Ångra' button sends exactly that, and the revert must run, not answer 400."""
        self.login("man")
        ind, old_name, entry = self._renamed_individual("R084")

        resp = self.client.post(f"/api/audit-log/{entry.id}/revert", headers={"Content-Type": "application/json"})

        self.assertEqual(
            (resp.status_code, db.Individual.get_by_id(ind.id).name),
            (200, old_name),
            f"revert with Content-Type json + empty body -> {resp.status_code} {resp.data[:120]!r}",
        )

    def test_revert_accepts_an_empty_object_and_explicit_fields(self):
        self.login("man")
        ind, old_name, entry = self._renamed_individual("R084 object")
        resp = self.client.post(f"/api/audit-log/{entry.id}/revert", json={})
        self.assertEqual((resp.status_code, db.Individual.get_by_id(ind.id).name), (200, old_name))

        ind, old_name, entry = self._renamed_individual("R084 fields")
        resp = self.client.post(f"/api/audit-log/{entry.id}/revert", json={"fields": ["name"]})
        self.assertEqual((resp.status_code, db.Individual.get_by_id(ind.id).name), (200, old_name))

    def test_revert_refuses_a_malformed_body_instead_of_reverting(self):
        """A JSON list used to give 500; a body that is not {"fields": [names]} must change nothing."""
        self.login("man")
        ind, _old_name, entry = self._renamed_individual("R084 malformed")
        for body in ('["fields"]', '"name"', '{"fields": "name"}', '{"fields": [1]}', '{"fields": ["name"]'):
            with self.subTest(body=body), mock.patch.dict(APP.config, {"PROPAGATE_EXCEPTIONS": False}):
                resp = self.client.post(f"/api/audit-log/{entry.id}/revert", data=body, content_type="application/json")
                self.assertEqual(resp.status_code, 400, resp.data[:120])
                self.assertEqual(db.Individual.get_by_id(ind.id).name, "R084 malformed")

    # --- POST /api/audit-log/<table>/<record_id>/restore/<audit_id> ---

    def test_restore_restores_full_state(self):
        """Restore reverts record to state before a specific change."""
        self.login("admin")
        ind = self.individuals[0]
        original_name = ind.name

        ind.name = "Change1"
        ind.save()
        ind.name = "Change2"
        ind.save()

        response = self.client.get(f"/api/audit-log/individual/{ind.id}")
        entries = response.get_json()["data"]
        oldest_id = entries[-1]["id"]

        response = self.client.post(f"/api/audit-log/individual/{ind.id}/restore/{oldest_id}")
        self.assertEqual(response.status_code, 200)

        refreshed = db.Individual.get_by_id(ind.id)
        self.assertEqual(refreshed.name, original_name)

    def test_restore_blocked_on_hbuser(self):
        """Restore on hbuser table is blocked."""
        self.login("admin")
        self.manager.email = "restore-test@test.example.com"
        self.manager.save()

        entry = self._get_latest_hbuser_update()
        if not entry:
            self.skipTest("No hbuser audit entry generated")

        response = self.client.post(f"/api/audit-log/hbuser/{self.manager.id}/restore/{entry.id}")
        self.assertEqual(response.status_code, 403)

    # --- Flask hook integration ---

    def test_flask_hooks_stamp_changed_by(self):
        """Authenticated request stamps changed_by via Flask hooks."""
        self.login("admin")
        ind = self.individuals[0]

        self.client.patch(
            f"/api/individual/{ind.number}",
            json={"individual": ind.number, "name": "HookTest", "herd": self.herds[0].herd},
        )

        entry = self._get_audit_entry("individual", ind.id)
        self.assertIsNotNone(entry, "Expected audit entry from PATCH request")
        self.assertEqual(entry.changed_by, self.admin.username or self.admin.email)

    # --- audit undo must not write what the domain services own ---

    def _revert(self, entry, **body):
        return self.client.post(f"/api/audit-log/{entry.id}/revert", json=body or None)

    def _restore(self, table, record_id, entry):
        return self.client.post(f"/api/audit-log/{table}/{record_id}/restore/{entry.id}")

    def _roster_bunny(self):
        # litter_size6w: a certified promotion needs it in a roster litter
        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=datetime(2025, 1, 10),
            litter_number=1,
            litter_size=6,
            litter_size6w=6,
        )
        return db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female", observed_color="bleighe")

    def _promote(self, bunny, **body):
        if body["certificate_type"] == "paper":
            body["paper_number"] = paper_number_for(bunny.id)
        resp = self.client.post(f"/api/v2/bunny/{bunny.id}/promote", json=body)
        self.assertEqual(resp.status_code, 201, resp.data)
        return db.Bunny.get_by_id(bunny.id).individual_id

    def _promote_uncertified(self, bunny):
        """A digital promote whose issuance never ran: registered without a certificate, so unpromote is allowed."""
        with mock.patch("blueprints.bunny_v2._apply_certificate", return_value=(None, None)):
            return self._promote(bunny, certificate_type="digital")

    def test_revert_of_certified_promotion_is_refused(self):
        """unpromote_bunny refuses once a certificate is issued (409). POST /api/audit-log/<id>/revert
        on the promotion UPDATE wrote fate/individual_id back with raw SQL, freed the slot while the
        certified Individual stayed live, and the slot could be promoted into a second live Individual."""
        bunny = self._roster_bunny()
        self.login("man")
        individual_id = self._promote(bunny, certificate_type="paper", paper_certificate="PAP-R027")

        # sanity: the coordinated service refuses because of the certificate
        resp = self.client.post(f"/api/v2/bunny/{bunny.id}/unpromote")
        self.assertEqual(resp.status_code, 409, resp.data)

        entry = self._get_audit_entry("bunny", bunny.id)
        self.assertIsNotNone(entry, "promotion must have produced a bunny UPDATE audit row")
        self.assertIn("individual_id", entry.changed_fields)

        resp = self._revert(entry, fields=["fate", "individual_id"])
        after = db.Bunny.get_by_id(bunny.id)
        second = self.client.post(
            f"/api/v2/bunny/{bunny.id}/promote",
            json={
                "certificate_type": "paper",
                "paper_certificate": "PAP-R027-2",
                "paper_number": paper_number_for(bunny.id),
            },
        )
        live = (
            db.Individual.select()
            .where((db.Individual.breeding == bunny.breeding_id) & (db.Individual.voided == False))  # noqa: E712
            .count()
        )
        self.assertEqual(
            (after.fate, after.individual_id),
            ("registered", individual_id),
            f"audit revert -> {resp.status_code} {resp.get_json()}; certified Individual {individual_id} "
            f"still live but bunny now fate={after.fate!r} individual_id={after.individual_id}; "
            f"re-promote -> {second.status_code}; live Individuals in litter = {live}",
        )
        self.assertEqual(resp.status_code, 409, resp.get_json())
        self.assertEqual(live, 1)

    def test_revert_of_an_unpromote_does_not_relink_the_slot(self):
        """After a plain unpromote the entry shows 'Ångra'; it re-linked the slot (fate='registered')
        to the voided Individual."""
        bunny = self._roster_bunny()
        self.login("man")
        individual_id = self._promote_uncertified(bunny)
        self.assertEqual(self.client.post(f"/api/v2/bunny/{bunny.id}/unpromote").status_code, 200)
        entry = self._get_audit_entry("bunny", bunny.id)
        self.assertIn("individual_id", entry.changed_fields)

        resp = self._revert(entry)

        after = db.Bunny.get_by_id(bunny.id)
        self.assertEqual((resp.status_code, after.fate, after.individual_id), (409, "undecided", None), resp.get_json())
        self.assertTrue(db.Individual.get_by_id(individual_id).voided)

    def test_restore_cannot_relink_a_bunny(self):
        """Restore skips individual_id, and fate with it when the snapshot holds another link (the bunny
        CHECK ties them). The rest of the snapshot is restored; the link and fate stay as they are."""
        bunny = self._roster_bunny()
        self.login("man")
        individual_id = self._promote_uncertified(bunny)
        promotion = self._get_audit_entry("bunny", bunny.id)  # snapshot: unlinked
        db.Bunny.update(label="Efter").where(db.Bunny.id == bunny.id).execute()

        resp = self._restore("bunny", bunny.id, promotion)  # would unlink the live Individual
        after = db.Bunny.get_by_id(bunny.id)
        self.assertEqual(
            (resp.status_code, after.individual_id, after.label), (200, individual_id, None), resp.get_json()
        )
        self.assertIn("individual_id", resp.get_json()["message"])

        self.assertEqual(self.client.post(f"/api/v2/bunny/{bunny.id}/unpromote").status_code, 200)
        unpromotion = self._get_audit_entry("bunny", bunny.id)  # snapshot: linked to the voided Individual
        resp = self._restore("bunny", bunny.id, unpromotion)
        after = db.Bunny.get_by_id(bunny.id)
        self.assertEqual((resp.status_code, after.fate, after.individual_id), (200, "undecided", None), resp.get_json())

    def test_undo_of_label_notes_and_fate_of_an_unlinked_bunny_still_works(self):
        bunny = self._roster_bunny()
        self.login("man")
        for column, value in (("label", "Lilla"), ("notes", "anteckning"), ("fate", "died")):
            with self.subTest(column=column):
                before = getattr(db.Bunny.get_by_id(bunny.id), column)
                db.Bunny.update(**{column: value}).where(db.Bunny.id == bunny.id).execute()
                entry = self._get_audit_entry("bunny", bunny.id)
                self.assertEqual(entry.changed_fields, [column])
                resp = self._revert(entry)
                self.assertEqual((resp.status_code, getattr(db.Bunny.get_by_id(bunny.id), column)), (200, before))

        db.Bunny.update(label="Före").where(db.Bunny.id == bunny.id).execute()
        first = self._get_audit_entry("bunny", bunny.id)
        db.Bunny.update(label="Efter").where(db.Bunny.id == bunny.id).execute()
        resp = self._restore("bunny", bunny.id, first)
        self.assertEqual((resp.status_code, db.Bunny.get_by_id(bunny.id).label), (200, None), resp.get_json())

    def _active_birth_herd_id(self, individual_id):
        return db.HerdTracking.get(
            (db.HerdTracking.individual == individual_id)
            & (db.HerdTracking.kind == "BIRTH")
            & db.HerdTracking.voided_at.is_null()
        ).herd_id

    def test_restore_keeps_birth_row_and_origin_herd_coupled(self):
        """update_individual keeps the active BIRTH herd_tracking row in step with origin_herd
        (replace_birth_row). Restore wrote the snapshot column back with raw SQL and left the BIRTH row
        in the other herd, which the audit UI (herd_tracking is blocked) cannot repair. It now skips
        origin_herd_id and says so."""
        ind = self.individuals[0]  # G1-2111, BIRTH in herds[0]
        # What update_individual does when a manager changes the origin herd (same genebank).
        replace_birth_row(ind, self.manager, herd=self.herds[1], reason=BIRTH_HERD_CHANGED_REASON)
        db.Individual.update(origin_herd=self.herds[1]).where(db.Individual.id == ind.id).execute()
        self.assertEqual(self._active_birth_herd_id(ind.id), self.herds[1].id, "precondition")
        entry = self._get_audit_entry("individual", ind.id)
        self.assertIn("origin_herd_id", entry.changed_fields)

        self.login("man")
        resp = self._restore("individual", ind.id, entry)

        origin = db.Individual.get_by_id(ind.id).origin_herd_id
        birth_herd = self._active_birth_herd_id(ind.id)
        self.assertEqual(
            birth_herd,
            origin,
            f"restore -> {resp.status_code} {resp.get_json()}; origin_herd_id={origin} but the active "
            f"BIRTH row is in herd {birth_herd} (herds[0]={self.herds[0].id}, herds[1]={self.herds[1].id})",
        )
        self.assertEqual((resp.status_code, origin), (200, self.herds[1].id))
        self.assertIn("origin_herd_id", resp.get_json()["message"])

    def _locked_column_cases(self):
        """(table, id, column, new value): one real UPDATE per column the audit undo must not write."""
        ind, litter = self.individuals[0], self.breeding[0]
        return [
            ("individual", ind.id, "origin_herd_id", self.herds[1].id),
            ("individual", ind.id, "breeding_id", self.breeding[2].id),
            ("individual", ind.id, "number", "G1-9999"),
            ("individual", ind.id, "digital_certificate", 100001),
            ("individual", ind.id, "certificate", "PAP-X"),
            ("individual", ind.id, "voided", True),
            ("individual", ind.id, "voided_at", datetime(2025, 3, 1, 12, 0)),
            ("individual", ind.id, "is_active", False),
            ("breeding", litter.id, "birth_date", date(2021, 3, 1)),
            ("breeding", litter.id, "breeding_herd_id", self.herds[1].id),
            ("breeding", litter.id, "litter_number", 7),
        ]

    def test_revert_refuses_and_restore_skips_columns_the_domain_services_keep_in_step(self):
        """The coupled columns (BIRTH rows, numbers and S3 keys, voiding) are never written by undo.
        Revert refuses (409); restore restores the rest and names the column it skipped (200)."""
        self.login("man")
        model = {"individual": db.Individual, "breeding": db.Breeding}
        for table, record_id, column, value in self._locked_column_cases():
            with self.subTest(table=table, column=column):
                model[table].update(**{column: value}).where(model[table].id == record_id).execute()
                entry = self._get_audit_entry(table, record_id)
                self.assertEqual(entry.changed_fields, [column])

                for resp, status in ((self._revert(entry), 409), (self._restore(table, record_id, entry), 200)):
                    self.assertEqual(resp.status_code, status, resp.get_json())
                    self.assertIn(column, resp.get_json()["message"])
                stored = db.DATABASE.execute_sql(
                    f'SELECT "{column}" FROM "{table}" WHERE "{db.AUDITED_TABLES[table][0]}" = %s', (record_id,)
                ).fetchone()[0]
                self.assertEqual(stored, value, "the column was written")

    def test_revert_of_an_entry_that_also_changed_a_coupled_column_is_refused_whole(self):
        """The bare 'Ångra' reverts every changed field: an entry that moved the origin herd as well as the
        name is refused, not half-done. Name only, or fields=["name"], still reverts."""
        self.login("man")
        ind = db.Individual.get_by_id(self.individuals[0].id)
        old_name = ind.name
        db.Individual.update(name="Mixed", origin_herd=self.herds[1]).where(db.Individual.id == ind.id).execute()
        entry = self._get_audit_entry("individual", ind.id)
        self.assertCountEqual(entry.changed_fields, ["name", "origin_herd_id"])

        resp = self._revert(entry)
        self.assertEqual((resp.status_code, db.Individual.get_by_id(ind.id).name), (409, "Mixed"))
        resp = self._revert(entry, fields=["name"])
        self.assertEqual((resp.status_code, db.Individual.get_by_id(ind.id).name), (200, old_name))

    def test_restore_ignores_coupled_columns_that_still_hold_the_snapshot_value(self):
        """A restore names only the coupled columns it skipped with another value. On a voided individual the
        snapshot and the stored row agree on voided_at, as the trigger and row_to_json both write it."""
        self.login("man")
        ind = db.Individual.get_by_id(self.individuals[0].id)
        old_name = ind.name
        db.Individual.update(voided=True, voided_at=datetime(2025, 3, 1, 12, 0, 0, 123456), is_active=False).where(
            db.Individual.id == ind.id
        ).execute()
        db.Individual.update(name="Renamed").where(db.Individual.id == ind.id).execute()
        entry = self._get_audit_entry("individual", ind.id)

        resp = self._restore("individual", ind.id, entry)

        self.assertEqual((resp.status_code, db.Individual.get_by_id(ind.id).name), (200, old_name), resp.get_json())
        self.assertEqual(resp.get_json()["message"], "Post återställd")
        self.assertTrue(db.Individual.get_by_id(ind.id).voided)

    def test_restore_skips_columns_a_later_domain_change_wrote(self):
        """Restore of a rename still works after a domain service changed a coupled column: a digital certificate,
        an origin-herd move, a litter move or a new number. The name comes back, the coupled column stays."""
        ind_id = self.individuals[0].id

        def move_origin():
            replace_birth_row(
                db.Individual.get_by_id(ind_id), self.manager, herd=self.herds[1], reason=BIRTH_HERD_CHANGED_REASON
            )
            db.Individual.update(origin_herd=self.herds[1]).where(db.Individual.id == ind_id).execute()

        later = {
            "digital_certificate": lambda: assign_certificate_number(db.Individual.get_by_id(ind_id)),
            "origin_herd_id": move_origin,
            "breeding_id": lambda: (
                db.Individual.update(breeding=self.breeding[2]).where(db.Individual.id == ind_id).execute()
            ),
            "number": lambda: db.Individual.update(number="G1-9998").where(db.Individual.id == ind_id).execute(),
        }
        self.login("man")
        for column, change in later.items():
            with self.subTest(column=column):
                old_name = db.Individual.get_by_id(ind_id).name
                db.Individual.update(name=f"Ny {column}").where(db.Individual.id == ind_id).execute()
                rename = self._get_audit_entry("individual", ind_id)
                change()
                changed = getattr(db.Individual.get_by_id(ind_id), column)

                resp = self._restore("individual", ind_id, rename)

                stored = db.Individual.get_by_id(ind_id)
                self.assertEqual((resp.status_code, stored.name), (200, old_name), resp.get_json())
                self.assertEqual(getattr(stored, column), changed)
                self.assertIn(column, resp.get_json()["message"])

    def _update_entry_changing(self, table, record_id, column):
        """The latest UPDATE audit entry of the record whose changed_fields hold `column`."""
        entries = (
            db.AuditLog.select()
            .where((db.AuditLog.table_name == table) & (db.AuditLog.record_id == str(record_id)))
            .where(db.AuditLog.operation == "UPDATE")
            .order_by(db.AuditLog.id.desc())
        )
        return next(entry for entry in entries if column in (entry.changed_fields or []))

    def test_undo_keeps_alive_at_6_weeks_at_most_born(self):
        """Final review (24a65b0): (born 5, alive 4) -> (5, 2), then born corrected -> (3, 2). Reverting only the
        survivor change wrote (3, 4), past the rule update_breeding enforces. A restore of the whole snapshot
        brings back (5, 4), which is valid."""
        from utils.individual_number_v2 import LITTER_SIZE6W_ABOVE_BORN

        litter_id = self.breeding[0].id
        db.Breeding.update(litter_size=5, litter_size6w=4).where(db.Breeding.id == litter_id).execute()
        db.Breeding.update(litter_size6w=2).where(db.Breeding.id == litter_id).execute()
        survivors = self._update_entry_changing("breeding", litter_id, "litter_size6w")
        db.Breeding.update(litter_size=3).where(db.Breeding.id == litter_id).execute()
        self.login("man")

        resp = self._revert(survivors, fields=["litter_size6w"])
        row = db.Breeding.get_by_id(litter_id)
        self.assertEqual(
            (resp.status_code, resp.get_json()["message"], row.litter_size, row.litter_size6w),
            (409, LITTER_SIZE6W_ABOVE_BORN, 3, 2),
        )
        resp = self._restore("breeding", litter_id, survivors)
        row = db.Breeding.get_by_id(litter_id)
        self.assertEqual((resp.status_code, row.litter_size, row.litter_size6w), (200, 5, 4), resp.get_json())

        # As in update_breeding, only a change is checked. A historical row that already breaks the rule
        # still restores an unrelated column, writing its unchanged sizes back.
        db.Breeding.update(litter_size=3, litter_size6w=5).where(db.Breeding.id == litter_id).execute()
        db.Breeding.update(breed_notes="ändrad").where(db.Breeding.id == litter_id).execute()
        notes = self._update_entry_changing("breeding", litter_id, "breed_notes")
        resp = self._restore("breeding", litter_id, notes)
        row = db.Breeding.get_by_id(litter_id)
        self.assertEqual(
            (resp.status_code, row.breed_notes, row.litter_size, row.litter_size6w), (200, None, 3, 5), resp.get_json()
        )

    def test_undo_of_a_paper_promotion_cannot_clear_its_certificate(self):
        """A paper promotion stores the certificate number in its own UPDATE. Reverting or restoring that entry
        cleared it, and unpromote's certificate guard then let the certified Individual be voided."""
        bunny = self._roster_bunny()
        self.login("man")
        individual_id = self._promote(bunny, certificate_type="paper", paper_certificate="PAP-1")
        entry = self._update_entry_changing("individual", individual_id, "certificate")

        resp = self._revert(entry)
        stored = db.Individual.get_by_id(individual_id).certificate
        self.assertEqual((resp.status_code, stored), (409, "PAP-1"), resp.get_json())
        resp = self._restore("individual", individual_id, entry)
        stored = db.Individual.get_by_id(individual_id).certificate
        self.assertEqual((resp.status_code, stored), (200, "PAP-1"), resp.get_json())
        self.assertIn("certificate", resp.get_json()["message"])
        self.assertEqual(self.client.post(f"/api/v2/bunny/{bunny.id}/unpromote").status_code, 409)

    def test_undo_of_a_paper_to_digital_conversion_cannot_bring_the_paper_number_back(self):
        """Issuing a digital certificate clears the paper one in the same UPDATE (assign_certificate_number).
        Reverting only `certificate` in that entry put the paper number back next to the digital one."""
        bunny = self._roster_bunny()
        self.login("man")
        individual_id = self._promote(bunny, certificate_type="paper", paper_certificate="PAP-2")
        assign_certificate_number(db.Individual.get_by_id(individual_id))
        digital = db.Individual.get_by_id(individual_id).digital_certificate
        entry = self._update_entry_changing("individual", individual_id, "digital_certificate")
        self.assertCountEqual(entry.changed_fields, ["certificate", "digital_certificate"])

        for undo, status in (
            (lambda: self._revert(entry, fields=["certificate"]), 409),
            (lambda: self._restore("individual", individual_id, entry), 200),
        ):
            resp = undo()
            stored = db.Individual.get_by_id(individual_id)
            self.assertEqual(
                (resp.status_code, stored.certificate, stored.digital_certificate),
                (status, None, digital),
                resp.get_json(),
            )

    def test_undo_of_a_renumbering_cannot_write_litter_number(self):
        """renumber_litters moves a litter and its kits' numbers together, in two passes through a temporary
        negative litter_number. Undoing either UPDATE wrote litter_number alone: back to the old number while
        the kits keep the new one, or to the temporary negative value."""
        herd = self.herds[0]
        litter = db.Breeding.create(breeding_herd_id=herd, birth_date=date(2030, 5, 1), litter_number=3, litter_size=3)
        kit = db.Individual.create(number=f"{herd.herd}-3031", origin_herd=herd, breeding=litter, sex="female")
        renumber_litters(herd.herd, 2030, confirm=True)
        entries = list(
            db.AuditLog.select()
            .where((db.AuditLog.table_name == "breeding") & (db.AuditLog.record_id == str(litter.id)))
            .where(db.AuditLog.operation == "UPDATE")
            .order_by(db.AuditLog.id)
        )
        self.assertEqual(
            [(e.old_data["litter_number"], e.new_data["litter_number"]) for e in entries], [(3, -1), (-1, 1)]
        )

        def check(resp, status):
            stored = (db.Breeding.get_by_id(litter.id).litter_number, db.Individual.get_by_id(kit.id).number)
            self.assertEqual((resp.status_code, *stored), (status, 1, f"{herd.herd}-3011"), resp.get_json())
            self.assertIn("litter_number", resp.get_json()["message"])

        self.login("man")
        for entry in entries:
            with self.subTest(old_litter_number=entry.old_data["litter_number"]):
                check(self._revert(entry), 409)
                check(self._restore("breeding", litter.id, entry), 200)

    # --- herd rows: audit undo keeps update_herd's rules ---

    def _audit_update(self, table, record_id, **old):
        """An UPDATE audit entry whose old_data is the stored row with `old` swapped in."""
        pk = db.AUDITED_TABLES[table][0]
        row = db.DATABASE.execute_sql(
            f'SELECT row_to_json(t) FROM "{table}" t WHERE "{pk}" = %s', (record_id,)
        ).fetchone()[0]
        return db.AuditLog.create(
            table_name=table,
            record_id=str(record_id),
            operation="UPDATE",
            old_data={**row, **old},
            new_data=row,
            changed_fields=list(old),
        )

    def _login_as(self, username):
        self.client = APP.test_client(use_cookies=True)
        self.login(username)

    def test_herd_identity_and_ownership_are_admin_only_in_audit_undo(self):
        """update_herd drops herd, genebank and membership unless the caller is admin (herd_id is never
        written); a revert or restore of a herd row must not be a way round that. A manager's revert is
        refused, a manager's restore skips them."""
        herd = self.herds[0]
        membership = db.Membership.create()
        entries = {
            "herd": self._audit_update("herd", herd.id, herd="G9"),
            "genebank_id": self._audit_update("herd", herd.id, genebank_id=self.genebanks[1].id),
            "membership_id": self._audit_update("herd", herd.id, membership_id=membership.id),
        }
        self._login_as("man")
        for column, entry in entries.items():
            with self.subTest(column=column):
                for resp, status in ((self._revert(entry), 409), (self._restore("herd", herd.id, entry), 200)):
                    self.assertEqual(resp.status_code, status, resp.get_json())
                    self.assertIn(column, resp.get_json()["message"])
        stored = db.Herd.get_by_id(herd.id)
        self.assertEqual((stored.herd, stored.genebank_id, stored.membership_id), ("G1", self.genebanks[0].id, None))

        self._login_as("admin")
        for column, entry in entries.items():
            with self.subTest(column=column, admin=True):
                self.assertEqual(self._revert(entry).status_code, 200)
        stored = db.Herd.get_by_id(herd.id)
        self.assertEqual(
            (stored.herd, stored.genebank_id, stored.membership_id), ("G9", self.genebanks[1].id, membership.id)
        )
        resp = self._restore("herd", herd.id, entries["herd"])  # the snapshot: back in the first genebank
        self.assertEqual((resp.status_code, db.Herd.get_by_id(herd.id).genebank_id), (200, self.genebanks[0].id))

    def test_audit_undo_refuses_an_invalid_herd_privacy_value(self):
        """update_herd refuses a *_privacy that is not None/public/authenticated/private (readers fail
        closed on it, but it must not get into the table); undo takes the value from an old snapshot."""
        herd = self.herds[0]
        bad = self._audit_update("herd", herd.id, name_privacy="Public ")
        for username in ("man", "admin"):
            self._login_as(username)
            with self.subTest(user=username):
                for resp in (self._revert(bad), self._restore("herd", herd.id, bad)):
                    self.assertEqual(resp.status_code, 409, resp.get_json())
                    self.assertIn("name_privacy", resp.get_json()["message"])
        self.assertEqual(db.Herd.get_by_id(herd.id).name_privacy, "private")

        self._login_as("man")
        for level in (None, "public", "authenticated", "private"):
            with self.subTest(level=level):
                entry = self._audit_update("herd", herd.id, email_privacy=level)
                self.assertEqual(self._revert(entry).status_code, 200)
                self.assertEqual(db.Herd.get_by_id(herd.id).email_privacy, level)

    def test_restore_refuses_an_invalid_privacy_value_the_row_already_holds(self):
        """Restore writes every snapshot column, also those equal to the stored row: an invalid *_privacy that
        both hold (an old row) is written again and must be refused like any other."""
        herd = self.herds[0]
        db.Herd.update(name_privacy="Public ").where(db.Herd.id == herd.id).execute()
        entry = self._audit_update("herd", herd.id, herd_name="Gammalt namn")
        for username in ("man", "admin"):
            self._login_as(username)
            with self.subTest(user=username):
                resp = self._restore("herd", herd.id, entry)
                self.assertEqual(resp.status_code, 409, resp.get_json())
                self.assertIn("name_privacy", resp.get_json()["message"])
        self.assertNotEqual(db.Herd.get_by_id(herd.id).herd_name, "Gammalt namn")

    def test_restore_does_not_overwrite_a_privacy_correction_made_after_its_read(self):
        """A correction of the invalid value between restore's read of the row and its UPDATE (a concurrent
        update_herd) must not be overwritten with the invalid snapshot value."""
        herd = self.herds[0]
        db.Herd.update(name_privacy="Public ").where(db.Herd.id == herd.id).execute()
        entry = self._audit_update("herd", herd.id, herd_name="Gammalt namn")
        read = da._stored_row

        def read_then_correct(*args):
            row = read(*args)
            db.Herd.update(name_privacy="private").where(db.Herd.id == herd.id).execute()
            return row

        self._login_as("man")
        with mock.patch.object(da, "_stored_row", side_effect=read_then_correct):
            resp = self._restore("herd", herd.id, entry)
        self.assertEqual((resp.status_code, db.Herd.get_by_id(herd.id).name_privacy), (409, "private"), resp.get_json())


class TestCreateBreedingV2(DatabaseTest):
    """Tests for POST /api/v2/breeding — register mating."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username, password="pass"):  # nosemgrep: hardcoded-password-default-argument
        res = self.client.post("/api/login", json={"username": username, "password": password})
        self.assertEqual(res.status_code, 200, f"Login failed for {username}")

    def test_requires_auth(self):
        """POST without session returns 401."""
        response = self.client.post("/api/v2/breeding", json={"mother": "G1-1911"})
        self.assertEqual(response.status_code, 401)

    def test_success_returns_201_with_full_entity(self):
        """POST with valid data returns 201 + full breeding record."""
        self.login("admin")
        response = self.client.post(
            "/api/v2/breeding",
            json={
                "mother": self.parents[0].number,  # G1-1911
                "father": self.parents[1].number,  # G2-1711
                "breeding_herd": self.herds[0].herd,  # G1
                "date": "2023-06-15",
                "notes": "Test v2 breeding",
            },
        )
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        # Full entity must include these fields
        self.assertIn("id", data)
        self.assertIn("mother", data)
        self.assertIn("father", data)
        self.assertIn("breeding_herd", data)
        self.assertEqual(data["mother"], self.parents[0].number)
        self.assertEqual(data["father"], self.parents[1].number)

    def test_invalid_mother_returns_400_problem(self):
        """POST with unknown mother returns RFC 9457 400."""
        self.login("admin")
        response = self.client.post(
            "/api/v2/breeding",
            json={
                "mother": "NONEXISTENT",
                "father": self.parents[1].number,
                "breeding_herd": self.herds[0].herd,
                "date": "2023-06-15",
            },
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["type"], "about:blank")
        self.assertIn("detail", data)

    def test_empty_body_returns_400(self):
        """POST with empty body returns 400."""
        self.login("admin")
        response = self.client.post("/api/v2/breeding", data="", content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_forbidden_returns_403(self):
        """POST by user without edit permission returns 403."""
        self.login("spec")  # viewer, no edit rights
        response = self.client.post(
            "/api/v2/breeding",
            json={
                "mother": self.parents[0].number,
                "father": self.parents[1].number,
                "breeding_herd": self.herds[0].herd,
                "date": "2023-07-15",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_legacy_post_still_works(self):
        """Legacy POST /api/breeding still returns old format (ADR-0006)."""
        self.login("admin")
        response = self.client.post(
            "/api/breeding",
            json={
                "mother": self.parents[0].number,
                "father": self.parents[1].number,
                "breeding_herd": self.herds[0].herd,
                "date": "2023-08-15",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("status", data)


class TestUpdateBreedingV2(DatabaseTest):
    """Tests for PATCH /api/v2/breeding/<id> — update breeding."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username, password="pass"):  # nosemgrep: hardcoded-password-default-argument
        res = self.client.post("/api/login", json={"username": username, "password": password})
        self.assertEqual(res.status_code, 200, f"Login failed for {username}")

    def test_requires_auth(self):
        """PATCH without session returns 401."""
        response = self.client.patch(f"/api/v2/breeding/{self.breeding[0].id}", json={"breed_notes": "x"})
        self.assertEqual(response.status_code, 401)

    def test_nonexistent_returns_404(self):
        """PATCH on nonexistent breeding returns 404."""
        self.login("admin")
        response = self.client.patch("/api/v2/breeding/999999", json={"breed_notes": "x"})
        self.assertEqual(response.status_code, 404)

    def test_success_returns_200_with_full_entity(self):
        """PATCH on valid breeding returns 200 + full updated entity."""
        self.login("admin")
        breeding = self.breeding[0]
        response = self.client.patch(
            f"/api/v2/breeding/{breeding.id}",
            json={
                "breeding_herd": self.herds[0].herd,
                "breed_notes": "Updated via v2",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("id", data)
        self.assertIn("mother", data)
        self.assertIn("father", data)
        self.assertEqual(data["breed_notes"], "Updated via v2")

    def test_forbidden_returns_403(self):
        """PATCH by user without permission returns 403."""
        self.login("spec")  # viewer
        response = self.client.patch(
            f"/api/v2/breeding/{self.breeding[0].id}",
            json={"breeding_herd": self.herds[0].herd, "breed_notes": "x"},
        )
        self.assertEqual(response.status_code, 403)

    def test_pending_mating_edit_with_null_litter_size(self):
        """BreedingList.handleEditSubmit sends litter_size: null for a mating without a birth.
        null keeps the stored value instead of int(None) -> TypeError -> 500."""
        mating = self.breeding[3]  # M3 mating, no birth, no litter_size
        payload = {
            "breeding_herd": "M3",
            "breed_date": "2022-01-01",
            "breed_notes": "updated",
            "birth_notes": "",
            "litter_size": None,
            "litter_size6w": None,
        }
        self.login("admin")
        response = self.client.patch(f"/api/v2/breeding/{mating.id}", json=payload)
        row = db.Breeding.get_by_id(mating.id)
        self.assertEqual(
            (response.status_code, row.breed_notes, row.litter_size),
            (200, "updated", None),
            response.get_data(as_text=True),
        )

    def test_non_numeric_litter_size_type_is_a_400(self):
        """A JSON list litter_size is 'Unknown litter size.' (400), not a TypeError 500."""
        self.login("admin")
        response = self.client.patch(f"/api/v2/breeding/{self.breeding[0].id}", json={"litter_size": [3]})
        self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["detail"], "Unknown litter size.")

    # G2's litter breeding[2] has the G1 owner's doe G1-1911 as mother and kit G2-2011.
    # Holding a parent no longer authorizes edits to it; the litter's herd does.

    def _foreign_litter(self):
        litter = db.Breeding.get_by_id(self.breeding[2].id)
        kit = db.Individual.get_by_id(self.individuals[1].id)
        birth_row = (
            db.HerdTracking.select()
            .where(db.HerdTracking.individual == kit.id, db.HerdTracking.kind == "BIRTH", db.ht_not_voided())
            .get()
        )
        return litter, kit, str(birth_row.herd_tracking_date)[:10]

    def test_parent_holder_cannot_move_another_herds_litter(self):
        self.login("owner")  # owns G1 only
        response = self.client.patch(f"/api/v2/breeding/{self.breeding[2].id}", json={"breeding_herd": "G1"})
        litter, kit, _ = self._foreign_litter()
        self.assertEqual(
            (response.status_code, litter.breeding_herd_id.herd, kit.number, kit.current_herd.herd),
            (403, "G2", "G2-2011", "G2"),
            response.get_data(as_text=True)[:200],
        )
        # An owner of BOTH herds may not move it either (admin/manager rule, as for origin_herd) ...
        both = da.register_user("g1-g2-owner", "pass")
        both.add_role("owner", self.herds[0].id)
        both.add_role("owner", self.herds[1].id)
        self.client.get("/api/logout")
        self.login("g1-g2-owner")
        response = self.client.patch(f"/api/v2/breeding/{self.breeding[2].id}", json={"breeding_herd": "G1"})
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True)[:200])
        # ... while a manager of the genebank still can.
        self.client.get("/api/logout")
        self.login("man")
        response = self.client.patch(f"/api/v2/breeding/{self.breeding[2].id}", json={"breeding_herd": "G1"})
        litter, kit, _ = self._foreign_litter()
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:200])
        self.assertEqual((litter.breeding_herd_id.herd, kit.number), ("G1", "G1-2011"))

    def test_cross_genebank_litter_move_is_admin_only(self):
        """Moving a litter into another genebank moves its kits there too, which only an
        admin may do (as a correction). A manager of one genebank, or of both, is refused."""
        self.login("man")  # manager of Gotland only
        response = self.client.patch(f"/api/v2/breeding/{self.breeding[2].id}", json={"breeding_herd": "M3"})
        litter, kit, _ = self._foreign_litter()
        self.assertEqual(
            (response.status_code, litter.breeding_herd_id.herd, kit.number),
            (403, "G2", "G2-2011"),
            response.get_data(as_text=True)[:200],
        )
        self.manager.add_role("manager", self.genebanks[1].id)
        response = self.client.patch(f"/api/v2/breeding/{self.breeding[2].id}", json={"breeding_herd": "M3"})
        litter, kit, _ = self._foreign_litter()
        self.assertEqual(
            (response.status_code, litter.breeding_herd_id.herd, kit.number),
            (403, "G2", "G2-2011"),
            response.get_data(as_text=True)[:200],
        )
        self.client.get("/api/logout")
        self.login("admin")
        response = self.client.patch(f"/api/v2/breeding/{self.breeding[2].id}", json={"breeding_herd": "M3"})
        litter, kit, _ = self._foreign_litter()
        birth_herd = (
            db.HerdTracking.select()
            .where(db.HerdTracking.individual == kit.id, db.HerdTracking.kind == "BIRTH", db.ht_not_voided())
            .get()
            .herd.herd
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:200])
        self.assertEqual(
            (litter.breeding_herd_id.herd, kit.number, kit.origin_herd.herd, birth_herd), ("M3", "M3-2011", "M3", "M3")
        )

    def test_cross_genebank_litter_move_is_admin_only_when_no_holder_changes(self):
        """Final review: above, the manager of both genebanks was refused only because a never-sold kit's
        holder changed genebank. With every kit sold on within its genebank, or no kit at all, nothing
        downstream sees the change: the litter rule itself refuses it (legacy keeps its 200 envelope)."""
        ht_row(
            "TRANSFER",
            from_herd=self.herds[1],
            herd=self.herds[0],
            signature=self.manager,
            individual=self.individuals[1],
            herd_tracking_date=datetime(2021, 6, 1),
        )
        self.manager.add_role("manager", self.genebanks[1].id)
        self.login("man")
        sold_out = self.client.patch(f"/api/v2/breeding/{self.breeding[2].id}", json={"breeding_herd": "M3"})
        kitless = self.client.patch("/api/breeding", json={"id": self.breeding[3].id, "breeding_herd": "G1"})
        litter, kit, _ = self._foreign_litter()
        self.assertEqual(
            (sold_out.status_code, sold_out.get_json().get("detail"), litter.breeding_herd_id.herd, kit.number),
            (403, "Forbidden", "G2", "G2-2011"),
        )
        self.assertEqual(
            (kitless.status_code, kitless.get_json(), db.Breeding.get_by_id(self.breeding[3].id).breeding_herd_id.herd),
            (200, {"status": "error", "message": "Forbidden"}, "M3"),
        )
        self.client.get("/api/logout")
        self.login("admin")
        kitless = self.client.patch("/api/breeding", json={"id": self.breeding[3].id, "breeding_herd": "G1"})
        self.assertEqual(
            (kitless.get_json(), db.Breeding.get_by_id(self.breeding[3].id).breeding_herd_id.herd),
            ({"status": "success"}, "G1"),
        )

    def test_parent_holder_cannot_change_foreign_litter_birth_date(self):
        self.login("owner")
        response = self.client.patch(f"/api/v2/breeding/{self.breeding[2].id}", json={"birth_date": "2020-02-05"})
        litter, _, kit_birth = self._foreign_litter()
        self.assertEqual(
            (response.status_code, str(litter.birth_date), kit_birth),
            (403, "2020-02-01", "2021-02-01"),
            response.get_data(as_text=True)[:200],
        )

    def test_parent_holder_cannot_change_foreign_litter_parents(self):
        # The guard for certified kits is covered in test_breeding_v2_api; this test is about the validation.
        db.Individual.update(certificate=None, digital_certificate=None).where(
            db.Individual.breeding == self.breeding[2]
        ).execute()
        swap = {"mother": self.parents[1].number, "father": self.parents[0].number}
        self.login("owner")
        response = self.client.patch(f"/api/v2/breeding/{self.breeding[2].id}", json=swap)
        litter, _, _ = self._foreign_litter()
        self.assertEqual(
            (response.status_code, litter.mother_id, litter.father_id),
            (403, self.parents[0].id, self.parents[1].id),
            response.get_data(as_text=True)[:200],
        )
        # The owner of the litter's herd keeps the right to correct it.
        g2_owner = da.register_user("g2-owner", "pass")
        g2_owner.add_role("owner", self.herds[1].id)
        self.client.get("/api/logout")
        self.login("g2-owner")
        response = self.client.patch(f"/api/v2/breeding/{self.breeding[2].id}", json=swap)
        litter, _, _ = self._foreign_litter()
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:200])
        self.assertEqual((litter.mother_id, litter.father_id), (self.parents[1].id, self.parents[0].id))


class TestDeleteBreedingV2(DatabaseTest):
    """Tests for DELETE /api/v2/breeding/<id> — delete breeding."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username, password="pass"):  # nosemgrep: hardcoded-password-default-argument
        res = self.client.post("/api/login", json={"username": username, "password": password})
        self.assertEqual(res.status_code, 200, f"Login failed for {username}")

    def test_requires_auth(self):
        """DELETE without session returns 401."""
        response = self.client.delete(f"/api/v2/breeding/{self.breeding[0].id}")
        self.assertEqual(response.status_code, 401)

    def test_nonexistent_returns_404(self):
        """DELETE on nonexistent breeding returns 404."""
        self.login("admin")
        response = self.client.delete("/api/v2/breeding/999999")
        self.assertEqual(response.status_code, 404)

    def test_success_on_empty_breeding_returns_204(self):
        """DELETE on breeding with no individuals returns 204."""
        self.login("admin")
        # breeding[3] has no children and no birth_date
        breeding = self.breeding[3]
        response = self.client.delete(f"/api/v2/breeding/{breeding.id}")
        self.assertEqual(response.status_code, 204)

    def test_breeding_with_individuals_returns_409(self):
        """DELETE on breeding with individuals returns 409 conflict."""
        self.login("admin")
        # breeding[0] has individuals[0] and individuals[3] as children
        breeding = self.breeding[0]
        response = self.client.delete(f"/api/v2/breeding/{breeding.id}")
        self.assertEqual(response.status_code, 409)
        data = response.get_json()
        self.assertEqual(data["type"], "about:blank")
        self.assertIn("detail", data)

    def test_forbidden_returns_403(self):
        """DELETE by user without edit permission returns 403."""
        self.login("spec")  # viewer of Gotland — can see but not edit
        # breeding[4] is in herds[0] (Gotland), so viewer can see it
        breeding = self.breeding[4]
        response = self.client.delete(f"/api/v2/breeding/{breeding.id}")
        self.assertEqual(response.status_code, 403)


class TestRegisterBirthV2(DatabaseTest):
    """Tests for POST /api/v2/breeding/<id>/birth — register birth."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username, password="pass"):  # nosemgrep: hardcoded-password-default-argument
        res = self.client.post("/api/login", json={"username": username, "password": password})
        self.assertEqual(res.status_code, 200, f"Login failed for {username}")

    def test_requires_auth(self):
        """POST without session returns 401."""
        response = self.client.post(
            f"/api/v2/breeding/{self.breeding[3].id}/birth",
            json={"date": "2022-02-01", "litter_size": 3},
        )
        self.assertEqual(response.status_code, 401)

    def test_nonexistent_breeding_returns_404(self):
        """POST birth on nonexistent breeding returns 404."""
        self.login("admin")
        response = self.client.post(
            "/api/v2/breeding/999999/birth",
            json={"date": "2022-02-01", "litter_size": 3},
        )
        self.assertEqual(response.status_code, 404)

    def test_success_returns_200_with_full_entity(self):
        """POST birth on valid breeding returns 200 + full updated breeding."""
        self.login("admin")
        # breeding[3] has no birth_date yet
        breeding = self.breeding[3]
        response = self.client.post(
            f"/api/v2/breeding/{breeding.id}/birth",
            json={"date": "2022-02-01", "litter_size": 4, "litter_size6w": 3, "notes": "Birth v2"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("id", data)
        self.assertIn("mother", data)
        self.assertEqual(data["litter_size"], 4)
        self.assertIsNotNone(data["birth_date"])

    def test_already_registered_returns_409(self):
        """POST birth on breeding that already has birth_date returns 409."""
        self.login("admin")
        # breeding[0] already has birth_date
        breeding = self.breeding[0]
        response = self.client.post(
            f"/api/v2/breeding/{breeding.id}/birth",
            json={"date": "2021-03-01", "litter_size": 2},
        )
        self.assertEqual(response.status_code, 409)

    def test_birth_seeds_roster_with_one_row_per_kit(self):
        """Registering a birth auto-creates litter_size bunny rows."""
        self.login("admin")
        breeding = self.breeding[3]
        response = self.client.post(
            f"/api/v2/breeding/{breeding.id}/birth",
            json={"date": "2022-02-01", "litter_size": 4},
        )
        self.assertEqual(response.status_code, 200)
        rows = db.Bunny.select().where(db.Bunny.breeding == breeding).order_by(db.Bunny.slot_order)
        self.assertEqual([r.slot_order for r in rows], [1, 2, 3, 4])

    def test_out_of_order_birth_returns_litter_number_conflicts(self):
        """A birth dated before an existing kull in the same year surfaces conflicts."""
        self.login("admin")
        first = self.breeding[3]  # breed_date 2022-01-01, no birth yet
        response = self.client.post(
            f"/api/v2/breeding/{first.id}/birth",
            json={"date": "2022-02-01", "litter_size": 2},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("litter_number_conflicts", response.get_json())

        # Different mother: the same doe can't have two litters 17 days apart
        # (the birth-interval validation would reject the registration).
        earlier = db.Breeding.create(
            breed_date=datetime(2021, 12, 15),
            mother=self.parents[0],
            father=first.father,
            breeding_herd_id=first.breeding_herd_id,
        )
        response = self.client.post(
            f"/api/v2/breeding/{earlier.id}/birth",
            json={"date": "2022-01-15", "litter_size": 2},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("litter_number_conflicts", data)
        self.assertTrue(data["litter_number_conflicts"])


class TestUpdateHerdV2(DatabaseTest):
    """Tests for PATCH /api/v2/herd/<herd_id> — update herd info."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username, password="pass"):  # nosemgrep: hardcoded-password-default-argument
        res = self.client.post("/api/login", json={"username": username, "password": password})
        self.assertEqual(res.status_code, 200, f"Login failed for {username}")

    def test_requires_auth(self):
        """PATCH without session returns 401."""
        response = self.client.patch(
            f"/api/v2/herd/{self.herds[0].herd}",
            json={"herd_name": "Updated"},
        )
        self.assertEqual(response.status_code, 401)

    def test_nonexistent_returns_404(self):
        """PATCH on nonexistent herd returns 404."""
        self.login("admin")
        response = self.client.patch("/api/v2/herd/NOPE999", json={"herd_name": "X"})
        self.assertEqual(response.status_code, 404)

    def test_success_returns_200_with_full_herd(self):
        """PATCH on valid herd returns 200 + full herd entity."""
        self.login("admin")
        response = self.client.patch(
            f"/api/v2/herd/{self.herds[0].herd}",
            json={"herd_name": "Updated Herd Name"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("herd", data)
        self.assertIn("herd_name", data)
        self.assertEqual(data["herd_name"], "Updated Herd Name")

    def test_forbidden_returns_403(self):
        """PATCH by user without permission returns 403."""
        self.login("spec")  # viewer
        response = self.client.patch(
            f"/api/v2/herd/{self.herds[0].herd}",
            json={"herd_name": "X"},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
