"""999.5: DELETE is blocked at DB level, generic audit revert/restore is blocked for herd_tracking."""

import os
import unittest

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import peewee  # noqa: E402
import utils.database as db  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import _USE_POSTGRES, DatabaseTest  # noqa: E402

limiter.enabled = False


@unittest.skipUnless(_USE_POSTGRES, "trigger needs PostgreSQL")
class TestHerdTrackingDeleteBlocked(DatabaseTest):
    def test_delete_raises_and_keeps_the_row(self):
        row_id = self.herd_tracking[0].id
        with self.assertRaises(peewee.DatabaseError) as ctx, db.DB_PROXY.atomic():
            db.HerdTracking.delete().where(db.HerdTracking.id == row_id).execute()
        self.assertIn("använd void", str(ctx.exception))
        self.assertTrue(db.HerdTracking.select().where(db.HerdTracking.id == row_id).exists())

    def test_lock_individuals_is_ascending_and_deduplicated(self):
        ids = [self.individuals[3].id, self.individuals[0].id, self.individuals[3].id]
        with db.DB_PROXY.atomic():
            locked = db.lock_individuals(ids)
        self.assertEqual([i.id for i in locked], sorted({self.individuals[0].id, self.individuals[3].id}))
        self.assertEqual(db.lock_individuals([]), [])


class TestHerdTrackingRevertBlocked(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.client.post("/api/login", json={"username": "man", "password": "pass"})

    @unittest.skipUnless(_USE_POSTGRES, "audit_log needs PostgreSQL")
    def test_revert_of_herd_tracking_entry_is_403(self):
        entry = db.AuditLog.select().where(db.AuditLog.table_name == "herd_tracking").first()
        self.assertIsNotNone(entry, "fixture inserts must have produced audit rows")
        response = self.client.post(f"/api/audit-log/{entry.id}/revert", json={})
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True))

    @unittest.skipUnless(_USE_POSTGRES, "audit_log needs PostgreSQL")
    def test_restore_of_herd_tracking_record_is_403(self):
        entry = db.AuditLog.select().where(db.AuditLog.table_name == "herd_tracking").first()
        response = self.client.post(f"/api/audit-log/herd_tracking/{entry.record_id}/restore/{entry.id}")
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True))

    @unittest.skipUnless(_USE_POSTGRES, "audit_log needs PostgreSQL")
    def test_reading_herd_tracking_history_still_works(self):
        row = self.herd_tracking[0]
        response = self.client.get(f"/api/audit-log/herd_tracking/{row.id}")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
