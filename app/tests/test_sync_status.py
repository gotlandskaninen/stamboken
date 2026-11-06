"""Demo-sync status endpoint + staleness."""

import utils.database as db
from herdbook import APP, limiter

from tests.database_test import DatabaseTest

limiter.enabled = False

_DEMO_SYNC_DDL = """
CREATE TABLE IF NOT EXISTS demo_sync_status (
    id           SERIAL PRIMARY KEY,
    started_at   TIMESTAMPTZ NOT NULL,
    finished_at  TIMESTAMPTZ NULL,
    success      BOOLEAN NULL,
    detail       TEXT NULL,
    rows_synced  INTEGER NULL
)
"""


class TestSyncStatus(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        # Belt: the table is created by migration 21 / db.init().
        # The exact DDL is idempotent and keeps this file runnable
        # standalone against a stale pytest volume. Not in the DatabaseTest
        # truncate list → clean it here for determinism.
        db.DATABASE.execute_sql(_DEMO_SYNC_DDL)
        db.DATABASE.execute_sql("DELETE FROM demo_sync_status")

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.get("/api/logout")
        return self.client.post("/api/login", json={"username": username, "password": password})

    def test_sync_status_staleness(self):
        self.login("admin")

        # 1) empty table → stale=true, all row fields null (flat SyncStatus shape)
        resp = self.client.get("/api/v2/admin/sync-status")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["stale"])
        for key in ("started_at", "finished_at", "success", "detail", "rows_synced"):
            self.assertIsNone(body[key])

        # 2) newest finished run 27 h old → stale=true
        db.DATABASE.execute_sql(
            "INSERT INTO demo_sync_status (started_at, finished_at, success, rows_synced) "
            "VALUES (now() - interval '27 hours 10 minutes', now() - interval '27 hours', true, 1100)"
        )
        body = self.client.get("/api/v2/admin/sync-status").get_json()
        self.assertTrue(body["stale"])
        self.assertTrue(body["success"])
        self.assertEqual(body["rows_synced"], 1100)
        self.assertIsNotNone(body["finished_at"])

        # 3) fresh finished run (a FAILED one — failure detail passes
        # through; staleness only asks "did the cron run?")
        db.DATABASE.execute_sql(
            "INSERT INTO demo_sync_status (started_at, finished_at, success, detail) "
            "VALUES (now() - interval '10 minutes', now() - interval '5 minutes', false, "
            "'FK-ordering: insert or update on table violates foreign key')"
        )
        body = self.client.get("/api/v2/admin/sync-status").get_json()
        self.assertFalse(body["stale"])
        self.assertFalse(body["success"])
        self.assertIn("FK-ordering", body["detail"])
        self.assertIsNone(body["rows_synced"])
