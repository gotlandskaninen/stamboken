#!/usr/bin/env python3
"""
Phase 17 migration 21→22 tests.

(genebank.signatory was part of the original migration but was removed
before release — certificates are attested per individual by the issuing
user, never at genebank level; the column never shipped.)

The pytest stack bootstraps fresh databases at CURRENT_SCHEMA_VERSION, so
these tests verify the END STATE (models + init()) and re-run the extracted
idempotent DDL body directly. Migration replay from a real v21 dump is
verified manually against local-production.
"""

import os
import unittest

import utils.database as db

from tests.database_test import DatabaseTest

_USE_POSTGRES = bool(os.getenv("POSTGRES_HOST")) and bool(os.getenv("POSTGRES_DB"))


@unittest.skipUnless(_USE_POSTGRES, "Schema DDL tests require PostgreSQL")
class TestMigration22(DatabaseTest):
    def test_genebank_has_audit_trigger(self):
        """First-time attach on genebank AND authenticators; shared trigger
        NAME audit_trigger (never audit_{table}_trigger)."""
        for table in ("genebank", "authenticators"):
            row = db.DATABASE.execute_sql(
                "SELECT 1 FROM information_schema.triggers "
                "WHERE trigger_name = 'audit_trigger' AND event_object_table = %s",
                (table,),
            ).fetchone()
            self.assertIsNotNone(row, f"audit_trigger missing on {table}")

    def test_hbuser_snapshot_excludes_password_hash(self):
        _, snapshot_excluded, change_detection_excluded = db.AUDITED_TABLES["hbuser"]
        self.assertIn("password_hash", snapshot_excluded)
        self.assertIn("last_active", change_detection_excluded)

    def test_is_active_backfilled_true(self):
        """Column present, NOT NULL, and every existing row is TRUE.
        The migrated-path backfill (playhouse add_column with default=True)
        is additionally verified against local-production."""
        row = db.DATABASE.execute_sql(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'hbuser' AND column_name = 'is_active'"
        ).fetchone()
        self.assertIsNotNone(row, "hbuser.is_active column missing")
        self.assertEqual(row[0], "NO")
        self.assertTrue(all(u.is_active for u in db.User.select()))
        # Peewee FieldAccessor shadows UserMixin.is_active.
        self.assertIsInstance(db.User.get_by_id(self.admin.id).is_active, bool)

    def test_genebank_name_edit_produces_audit_row(self):
        db.DATABASE.execute_sql("SELECT set_config('audit.user', 'test-runner', false)")
        gb = db.Genebank.get_by_id(self.genebanks[0].id)
        gb.name = "Nytt genbanksnamn"
        gb.save()
        row = (
            db.AuditLog.select()
            .where((db.AuditLog.table_name == "genebank") & (db.AuditLog.operation == "UPDATE"))
            .order_by(db.AuditLog.id.desc())
            .first()
        )
        self.assertIsNotNone(row)
        self.assertIn("name", row.changed_fields)

    def test_demo_sync_status_table_exists(self):
        rows = db.DATABASE.execute_sql(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'demo_sync_status' ORDER BY ordinal_position"
        ).fetchall()
        self.assertEqual(
            [r[0] for r in rows],
            ["id", "started_at", "finished_at", "success", "detail", "rows_synced"],
        )

    def test_migration_rerun_is_idempotent(self):
        """'Idempotent — safe.' Re-running the DDL body must neither
        raise nor stack a second trigger."""
        db._apply_phase17_schema_changes()
        db._apply_phase17_schema_changes()
        row = db.DATABASE.execute_sql(
            "SELECT COUNT(*) FROM pg_trigger "
            "WHERE tgname = 'audit_trigger' "
            "  AND tgrelid = 'genebank'::regclass AND NOT tgisinternal"
        ).fetchone()
        self.assertEqual(row[0], 1)
        cols = [c.name for c in db.DATABASE.get_columns("hbuser")]
        self.assertEqual(cols.count("is_active"), 1)

    def test_schema_version_is_22(self):
        self.assertGreaterEqual(db.CURRENT_SCHEMA_VERSION, 22)
        latest = db.SchemaHistory.select().order_by(db.SchemaHistory.version.desc()).first()
        self.assertGreaterEqual(latest.version, 22)
