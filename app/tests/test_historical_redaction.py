#!/usr/bin/env python3
"""
Historical credential-material redaction tests.

Seeds synthetic legacy audit rows (INSERTs are not blocked by the
append-only rules) and exercises the extracted redaction helper directly —
the full migrate_27_to_28() never replays in the pytest stack.
Only runs on PostgreSQL (rules + JSONB).
"""

import json
import os
import unittest

import utils.database as db

from tests.database_test import DatabaseTest

_USE_POSTGRES = bool(os.getenv("POSTGRES_HOST")) and bool(os.getenv("POSTGRES_DB"))


def _seed_audit_row(table_name, record_id, old_data, new_data, changed_fields):
    """INSERT bypasses the no-update/no-delete rules — only UPDATE/DELETE
    statements are rewritten to no-ops."""
    db.DATABASE.execute_sql(
        "INSERT INTO audit_log (table_name, record_id, operation, "
        "old_data, new_data, changed_fields, changed_by, changed_at) "
        "VALUES (%s, %s, 'UPDATE', %s::jsonb, %s::jsonb, %s, %s, NOW())",
        (
            table_name,
            record_id,
            json.dumps(old_data),
            json.dumps(new_data),
            changed_fields,
            "test-seed",
        ),
    )


@unittest.skipUnless(_USE_POSTGRES, "audit_log rules require PostgreSQL")
class TestHistoricalRedaction(DatabaseTest):
    def test_credential_material_redacted_historically(self):
        """Both targets scrubbed from old_data and new_data (values
        only — changed_fields keeps the column NAME
        fact-not-value); marker row written with per-target counts."""
        _seed_audit_row(
            "authenticators",
            "seeded-auth-1",
            old_data={"auth_data": "old-hash", "auth": "password"},
            new_data={"auth_data": "new-hash", "auth": "password"},
            changed_fields=["auth_data"],
        )
        _seed_audit_row(
            "hbuser",
            "seeded-hbuser-1",
            old_data={"password_hash": "$2b$12$olddigest", "username": "x"},
            new_data={"password_hash": "$2b$12$newdigest", "username": "x"},
            changed_fields=["password_hash"],
        )

        db._run_phase17_credential_redaction()

        row = db.AuditLog.get(db.AuditLog.record_id == "seeded-auth-1")
        self.assertNotIn("auth_data", row.old_data or {})
        self.assertNotIn("auth_data", row.new_data or {})
        # Fact-not-value: the column NAME survives redaction —
        # the historical trace "a reset happened" is preserved.
        self.assertIn("auth_data", row.changed_fields or [])
        # Non-target keys survive.
        self.assertEqual((row.old_data or {}).get("auth"), "password")

        row = db.AuditLog.get(db.AuditLog.record_id == "seeded-hbuser-1")
        self.assertNotIn("password_hash", row.old_data or {})
        self.assertNotIn("password_hash", row.new_data or {})
        self.assertIn("password_hash", row.changed_fields or [])
        self.assertEqual((row.old_data or {}).get("username"), "x")

        marker = (
            db.AuditLog.select()
            .where(db.AuditLog.record_id == "migration-28-credential-redaction")
            .order_by(db.AuditLog.id.desc())
            .first()
        )
        self.assertIsNotNone(marker)
        self.assertEqual(marker.changed_by, "migration-28")
        payload = marker.new_data or {}
        self.assertGreaterEqual(payload["auth_data_rows"], 1)
        self.assertGreaterEqual(payload["password_hash_rows"], 1)
        self.assertGreaterEqual(payload["total_rows"], 2)

    def test_historical_redaction_bypasses_no_update_rule(self):
        """Regression: a bare UPDATE is silently discarded by
        audit_log_no_update — the redaction must DROP the rule, do its work,
        and reinstate the rule afterwards."""
        _seed_audit_row(
            "authenticators",
            "seeded-auth-rule",
            old_data={"auth_data": "sekrit", "auth": "password"},
            new_data={"auth_data": "sekrit2", "auth": "password"},
            changed_fields=["auth_data"],
        )

        # The rule is installed and swallows bare UPDATEs (the bare-UPDATE trap).
        rule = db.DATABASE.execute_sql(
            "SELECT 1 FROM pg_rules WHERE tablename = 'audit_log' AND rulename = 'audit_log_no_update'"
        ).fetchone()
        self.assertIsNotNone(rule)
        db.DATABASE.execute_sql("UPDATE audit_log SET changed_by = 'bare-update' WHERE record_id = 'seeded-auth-rule'")
        row = db.AuditLog.get(db.AuditLog.record_id == "seeded-auth-rule")
        self.assertNotEqual(row.changed_by, "bare-update")

        # The wrapped redaction gets through where the bare UPDATE could not.
        db._run_phase17_credential_redaction()
        row = db.AuditLog.get(db.AuditLog.record_id == "seeded-auth-rule")
        self.assertNotIn("auth_data", row.old_data or {})
        self.assertNotIn("auth_data", row.new_data or {})

        # Rule reinstated: tampering is swallowed again.
        rule = db.DATABASE.execute_sql(
            "SELECT 1 FROM pg_rules WHERE tablename = 'audit_log' AND rulename = 'audit_log_no_update'"
        ).fetchone()
        self.assertIsNotNone(rule, "audit_log_no_update rule was not restored")
        db.DATABASE.execute_sql("UPDATE audit_log SET changed_by = 'tampered' WHERE record_id = 'seeded-auth-rule'")
        row = db.AuditLog.get(db.AuditLog.record_id == "seeded-auth-rule")
        self.assertNotEqual(row.changed_by, "tampered")
