"""admin_required folded auth + no redirect."""

import os

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.database as db  # noqa: E402, F401 — kept for fixture parity
from blueprints.common import admin_required, check_genebank_manager_access  # noqa: E402
from flask import jsonify  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402

# Disable rate limiting — multiple login() calls in quick succession
# would hit the 5/minute limit on /api/login and cause 429s.
limiter.enabled = False


# Probe route: registered at module import (before APP handles any request).
# The admin blueprint tests cover the real /api/v2/admin/* routes; this probe
# keeps the decorator contract testable in isolation.
@APP.route("/api/v2/_test/admin-probe", methods=["GET"])
@admin_required
def _admin_probe():
    return jsonify({"ok": True})


class TestAdminRequiredDecorator(DatabaseTest):
    PROBE = "/api/v2/_test/admin-probe"

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        # Logout first — /api/login is a no-op for an already-authenticated
        # client, so switching users on one client requires a fresh session.
        self.client.get("/api/logout")
        self.client.post("/api/login", json={"username": username, "password": password})

    def test_admin_endpoint_unauth_returns_401_problem_json(self):
        """No session → 401 problem+json; no redirect."""
        resp = self.client.get(self.PROBE)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.headers["Content-Type"], "application/problem+json")
        self.assertIsNone(resp.headers.get("Location"), "unauth must not redirect")
        self.assertEqual(resp.get_json()["type"], "authentication-required")

    def test_admin_endpoint_non_admin_returns_403_problem_json(self):
        self.login("man", "pass")  # DatabaseTest manager fixture
        resp = self.client.get(self.PROBE)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.headers["Content-Type"], "application/problem+json")
        self.assertIsNone(resp.headers.get("Location"))
        self.assertEqual(resp.get_json()["type"], "admin-required")

    def test_admin_endpoint_no_redirect_ever(self):
        """Parametrised over anonymous / manager / admin: exactly 401 / 403 /
        200 — NEVER 3xx; problem+json on failure, application/json on 200."""
        cases = [
            (None, 401, "application/problem+json"),
            ("man", 403, "application/problem+json"),
            ("admin", 200, "application/json"),
        ]
        for username, expected_status, expected_ct in cases:
            with self.subTest(user=username or "anonymous"):
                self.client = APP.test_client(use_cookies=True)
                if username:
                    self.login(username, "pass")
                resp = self.client.get(self.PROBE)
                self.assertNotIn(
                    resp.status_code,
                    (301, 302, 303, 307, 308),
                    f"redirect for {username or 'anonymous'}",
                )
                self.assertEqual(resp.status_code, expected_status)
                self.assertTrue(resp.headers["Content-Type"].startswith(expected_ct))


class TestCheckGenebankManagerAccess(DatabaseTest):
    """Direct-call tests. problem() needs an app context for jsonify."""

    def _call(self, user, gb_id):
        with APP.app_context():
            return check_genebank_manager_access(user, gb_id)

    def test_admin_passes_any_genebank(self):
        self.assertIsNone(self._call(self.admin, self.genebanks[1].id))

    def test_manager_passes_own_genebank(self):
        self.assertIsNone(self._call(self.manager, self.genebanks[0].id))

    def test_manager_rejected_other_genebank(self):
        result = self._call(self.manager, self.genebanks[1].id)
        self.assertIsNotNone(result)
        resp, status, headers = result  # problem() 3-tuple
        self.assertEqual(status, 403)
        self.assertEqual(headers["Content-Type"], "application/problem+json")
        self.assertEqual(resp.get_json()["type"], "manager-of-genebank-required")

    def test_viewer_rejected(self):
        result = self._call(self.viewer, self.genebanks[0].id)
        self.assertIsNotNone(result)
        _resp, status, _headers = result
        self.assertEqual(status, 403)
