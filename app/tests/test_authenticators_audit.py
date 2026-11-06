#!/usr/bin/env python3
"""
Split-exclusion audit-trigger tests on authenticators.

INSERT/UPDATE/DELETE must all strip snapshot_excluded values from snapshots
while preserving the changed-fact in changed_fields (the changed column name survives, its value does not).
Only runs on PostgreSQL (triggers + JSONB).
"""

import os
import unittest

import utils.data_access as da
import utils.database as db

from tests.database_test import DatabaseTest

_USE_POSTGRES = bool(os.getenv("POSTGRES_HOST")) and bool(os.getenv("POSTGRES_DB"))


@unittest.skipUnless(_USE_POSTGRES, "Audit triggers require PostgreSQL")
class TestAuthenticatorsAudit(DatabaseTest):
    def setUp(self):
        super().setUp()
        # Google-only-style user WITHOUT a password authenticator, so the
        # INSERT below is the row's first write (mirrors the first-password-
        # reset leak scenario). register_user with a falsy
        # password skips authenticator creation.
        self.auth_user = da.register_user("authaudit@example.com", None, username="authaudit")
        db.DATABASE.execute_sql("TRUNCATE audit_log RESTART IDENTITY")
        db.DATABASE.execute_sql("SELECT set_config('audit.user', 'test-runner', false)")

    def _latest(self, operation):
        return (
            db.AuditLog.select()
            .where((db.AuditLog.table_name == "authenticators") & (db.AuditLog.operation == operation))
            .order_by(db.AuditLog.id.desc())
            .first()
        )

    def _insert_authenticator(self, auth_data="fake-hash"):
        db.DATABASE.execute_sql(
            "INSERT INTO authenticators (user_id, auth, auth_data) VALUES (%s, %s, %s)",
            (self.auth_user.id, "password", auth_data),
        )

    def test_authenticators_insert_strips_auth_data(self):
        """INSERT branch — new_data must not contain auth_data; the fact of
        the write appears in changed_fields."""
        self._insert_authenticator()
        row = self._latest("INSERT")
        self.assertIsNotNone(row)
        self.assertIn("auth_data", row.changed_fields)
        self.assertNotIn("auth_data", row.new_data or {})
        self.assertIsNone(row.old_data)

    def test_authenticators_delete_strips_auth_data(self):
        """DELETE branch — old_data must not contain auth_data."""
        self._insert_authenticator()
        db.DATABASE.execute_sql("DELETE FROM authenticators WHERE user_id = %s", (self.auth_user.id,))
        row = self._latest("DELETE")
        self.assertIsNotNone(row)
        self.assertIn("auth_data", row.changed_fields)
        self.assertNotIn("auth_data", row.old_data or {})
        self.assertIsNone(row.new_data)

    def test_all_three_branches_uniformly_strip_snapshot_excluded(self):
        """Uniform stripping sweep. The UPDATE leg is the original
        core: touching ONLY a snapshot-excluded column must still emit a row
        (fact preserved) with the value scrubbed from BOTH snapshots."""
        self._insert_authenticator("hash-1")
        db.DATABASE.execute_sql(
            "UPDATE authenticators SET auth_data = %s WHERE user_id = %s",
            ("hash-2", self.auth_user.id),
        )
        db.DATABASE.execute_sql("DELETE FROM authenticators WHERE user_id = %s", (self.auth_user.id,))
        for operation, snapshot_field in (
            ("INSERT", "new_data"),
            ("UPDATE", "old_data"),
            ("UPDATE", "new_data"),
            ("DELETE", "old_data"),
        ):
            row = self._latest(operation)
            self.assertIsNotNone(row, f"{operation} did not emit an audit row")
            self.assertIn("auth_data", row.changed_fields, f"{operation} lost the changed-fact")
            payload = getattr(row, snapshot_field) or {}
            self.assertNotIn(
                "auth_data",
                payload,
                f"{operation} leaked auth_data into {snapshot_field}",
            )

    def test_change_detection_excluded_columns_still_skip(self):
        """Noise suppression preserved — an UPDATE touching only hbuser
        last_active emits NO audit row."""
        before = db.AuditLog.select().where(db.AuditLog.table_name == "hbuser").count()
        db.DATABASE.execute_sql(
            "UPDATE hbuser SET last_active = NOW() WHERE user_id = %s",
            (self.auth_user.id,),
        )
        after = db.AuditLog.select().where(db.AuditLog.table_name == "hbuser").count()
        self.assertEqual(before, after)
