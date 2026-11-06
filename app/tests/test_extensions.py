#!/usr/bin/env python3
"""
Flask-Limiter singleton tests (Phase 17, ADR-0007).

The Limiter lives in app/extensions.py so blueprints can import it without
importing herdbook.py; herdbook.py re-exports it so existing test
boilerplate (`from herdbook import APP, limiter`) keeps working.
"""

import extensions
from herdbook import APP, limiter

from tests.database_test import DatabaseTest

# Disable rate limiting at module load (test convention); the behavioural
# test below re-enables it explicitly and restores this.
limiter.enabled = False


class TestExtensions(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def test_limiter_shared_instance(self):
        """herdbook.limiter IS extensions.limiter — one object, so the
        existing @limiter.limit decorations and blueprint imports share
        state and configuration."""
        self.assertIs(limiter, extensions.limiter)

    def test_login_rate_limit_still_registered(self):
        """The '5 per minute' decoration on /api/login survived the move —
        the 6th rapid attempt returns 429."""
        limiter.enabled = True
        try:
            for attempt in range(5):
                response = self.client.post(
                    "/api/login",
                    json={"username": "finns-inte", "password": "fel"},
                )
                self.assertNotEqual(
                    response.status_code,
                    429,
                    f"rate limit hit too early (attempt {attempt + 1})",
                )
            response = self.client.post(
                "/api/login",
                json={"username": "finns-inte", "password": "fel"},
            )
            self.assertEqual(response.status_code, 429)
        finally:
            limiter.enabled = False
            limiter.reset()

    def test_login_rate_limit_is_keyed_on_the_last_forwarded_address(self):
        """Flask half of the contract next-app relies on. next-app
        passes the browser address nginx appended on as X-Forwarded-For, and
        ProxyFix(x_for=1) keys the limiter on the LAST entry. Each browser
        gets its own 5/minute, and a forged first entry opens no new bucket."""
        limiter.enabled = True

        def attempt(forwarded_for):
            return self.client.post(
                "/api/login",
                json={"username": "finns-inte", "password": "fel"},
                headers={"X-Forwarded-For": forwarded_for},
                environ_base={"REMOTE_ADDR": "172.18.0.5"},  # the next-app container
            ).status_code

        try:
            for _ in range(5):
                self.assertNotEqual(attempt("203.0.113.9"), 429)
            self.assertEqual(attempt("203.0.113.9"), 429)
            self.assertEqual(attempt("198.51.100.1, 203.0.113.9"), 429)
            self.assertNotEqual(attempt("203.0.113.10"), 429)
        finally:
            limiter.enabled = False
            limiter.reset()
