#!/usr/bin/env python3
"""
Basic auth checks a password on every route, so failed checks must draw on
the same 5/minute budget as /api/login; otherwise the header is a way to guess
passwords at the global default rate instead.
"""

import base64

from herdbook import APP, limiter

from tests.database_test import DatabaseTest

# Disable rate limiting at module load (test convention); each test
# re-enables it in setUp and restores this in tearDown.
limiter.enabled = False


def _basic(username, password):
    creds = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


class TestBasicAuthRateLimit(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        super().setUp()
        limiter.enabled = True
        # Cleanup, not tearDown: it runs even if setUp fails, so the limiter never stays on.
        self.addCleanup(limiter.reset)
        self.addCleanup(setattr, limiter, "enabled", False)
        limiter.reset()
        self.client = APP.test_client()

    def test_failed_basic_auth_is_limited_like_login(self):
        codes = [self.client.get("/api/user", headers=_basic("admin", f"wrong{i}")).status_code for i in range(5)]
        self.assertNotIn(429, codes, "limited before the login budget of 5 was spent")
        self.assertEqual(self.client.get("/api/user", headers=_basic("admin", "wrong")).status_code, 429)
        # Over the limit even the right password is refused, or a guess would still be checked.
        self.assertEqual(self.client.get("/api/user", headers=_basic("admin", "pass")).status_code, 429)

    def test_failed_basic_auth_spends_the_login_budget(self):
        for i in range(5):
            self.client.get("/api/user", headers=_basic("admin", f"wrong{i}"))
        response = self.client.post("/api/login", json={"username": "admin", "password": "pass"})
        self.assertEqual(response.status_code, 429)

    def test_successful_basic_auth_is_not_counted(self):
        for _ in range(10):
            response = self.client.get("/api/user", headers=_basic("admin", "pass"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["email"], "admin")
