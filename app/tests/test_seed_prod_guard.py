"""`flask seed create` plants accounts with publicly known passwords (including an
admin), so it must refuse to run when FLASK_ENV=production."""

import os
from unittest import mock

import utils.database as db  # noqa: E402
from herdbook import APP  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402


class TestSeedProdGuard(DatabaseTest):
    def test_refuses_in_production(self):
        with mock.patch.dict(os.environ, {"FLASK_ENV": "production"}):
            result = APP.test_cli_runner().invoke(args=["seed", "create"])
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("production", result.output)
        self.assertFalse(db.User.select().where(db.User.email == "seed-admin@test.local").exists())
