"""An account with a role keeps a Google login on the association's domain. ALLOW_ROLE_PASSWORD_LOGIN lifts these rules
for development and tests, and production refuses to start with it."""

import os
import unittest
from unittest import mock

import utils.settings as settings


class TestAllowRolePasswordLoginGuard(unittest.TestCase):
    def _run(self, **env):
        with mock.patch.dict(os.environ, env):
            try:
                settings.refuse_role_password_login_in_production()
                return "started"
            except RuntimeError:
                return "refused"

    def test_production_refuses_the_setting(self):
        self.assertEqual(self._run(FLASK_ENV="production", ALLOW_ROLE_PASSWORD_LOGIN="true"), "refused")
        self.assertEqual(self._run(FLASK_ENV="production", ALLOW_ROLE_PASSWORD_LOGIN="TRUE"), "refused")

    def test_allowed_combinations(self):
        self.assertEqual(self._run(FLASK_ENV="production", ALLOW_ROLE_PASSWORD_LOGIN="false"), "started")
        self.assertEqual(self._run(FLASK_ENV="development", ALLOW_ROLE_PASSWORD_LOGIN="true"), "started")
        self.assertEqual(self._run(FLASK_ENV="testing", ALLOW_ROLE_PASSWORD_LOGIN="true"), "started")
