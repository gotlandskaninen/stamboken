"""POST /api/auth/google must not log in an account that is not validated yet."""

from unittest import mock

import utils.database as db
from herdbook import APP, limiter
from utils.legacy_compat import legacy_classroom_url

from tests.database_test import DatabaseTest
from tests.google_login import token_login

limiter.enabled = False


class TestGoogleTokenValidated(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        db.User.update(validated=False).where(db.User.id == self.viewer.id).execute()

    def _login(self, auto_validate):
        with mock.patch("herdbook._should_auto_validate_users", return_value=auto_validate):
            return token_login(self.client, lambda method, ident: db.User.get_by_id(self.viewer.id))

    def test_unvalidated_user_gets_no_session(self):
        res = self._login(auto_validate=False)
        self.assertEqual(res.status_code, 401, res.get_data(as_text=True))
        self.assertIn(legacy_classroom_url(), res.get_json()["error"])  # the way to get validated
        self.assertFalse(db.User.get_by_id(self.viewer.id).validated)
        self.assertEqual(self.client.get("/api/user").status_code, 401)

    def test_auto_validate_validates_and_logs_in(self):
        res = self._login(auto_validate=True)
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        self.assertTrue(db.User.get_by_id(self.viewer.id).validated)
        self.assertEqual(self.client.get("/api/user").status_code, 200)
