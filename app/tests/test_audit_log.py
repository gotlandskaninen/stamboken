#!/usr/bin/env python3
"""
Tests for the audit_log PostgreSQL trigger.

These tests only run when PostgreSQL is available (skipped on SQLite).
"""

import os
import unittest
from datetime import datetime

import utils.data_access as da
import utils.database as db

from tests.database_test import DatabaseTest

_USE_POSTGRES = bool(os.getenv("POSTGRES_HOST")) and bool(os.getenv("POSTGRES_DB"))


@unittest.skipUnless(_USE_POSTGRES, "Audit triggers require PostgreSQL")
class TestAuditTrigger(DatabaseTest):
    """Test that the audit trigger captures INSERT/UPDATE/DELETE."""

    def _get_audit_entries(self, table_name, record_id=None):
        """Helper to query audit_log entries."""
        query = db.AuditLog.select().where(db.AuditLog.table_name == table_name)
        if record_id is not None:
            query = query.where(db.AuditLog.record_id == str(record_id))
        return list(query.order_by(db.AuditLog.id))

    def _clear_audit_log(self):
        """Clear all audit entries (test isolation)."""
        db.DATABASE.execute_sql("TRUNCATE audit_log RESTART IDENTITY")

    def setUp(self):
        super().setUp()
        # Clear audit entries created by insert_default()
        self._clear_audit_log()

    def test_insert_creates_audit_entry(self):
        """INSERT on a tracked table creates an audit_log entry."""
        individual = self.individuals[0]

        new_weight = db.Weight.create(
            individual=individual,
            weight=2.5,
            weight_date=datetime.now().date(),
        )

        entries = self._get_audit_entries("weight", new_weight.id)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.operation, "INSERT")
        self.assertIsNone(entry.old_data)
        self.assertIsNotNone(entry.new_data)
        self.assertEqual(entry.new_data["weight"], 2.5)

    def test_update_creates_audit_entry_with_old_and_new(self):
        """UPDATE on a tracked table records old and new data."""
        individual = self.individuals[0]
        old_name = individual.name
        new_name = "Teständrad"

        individual.name = new_name
        individual.save()

        entries = self._get_audit_entries("individual", individual.id)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.operation, "UPDATE")
        self.assertEqual(entry.old_data["name"], old_name)
        self.assertEqual(entry.new_data["name"], new_name)
        self.assertIsInstance(entry.changed_fields, list)
        self.assertIn("name", entry.changed_fields)

    def test_delete_creates_audit_entry(self):
        """DELETE on a tracked table records the deleted row."""
        new_weight = db.Weight.create(
            individual=self.individuals[0],
            weight=3.0,
            weight_date=datetime.now().date(),
        )
        self._clear_audit_log()

        weight_id = new_weight.id
        new_weight.delete_instance()

        entries = self._get_audit_entries("weight", weight_id)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.operation, "DELETE")
        self.assertIsNotNone(entry.old_data)
        self.assertIsNone(entry.new_data)

    def test_update_no_change_creates_no_audit_entry(self):
        """UPDATE that changes nothing should not create an audit entry."""
        # Load fresh from DB to ensure field values match exactly
        individual = db.Individual.get_by_id(self.individuals[0].id)
        individual.save()

        entries = self._get_audit_entries("individual", individual.id)
        self.assertEqual(len(entries), 0)

    def test_excluded_columns_not_tracked(self):
        """Changes to excluded columns (e.g. last_active on hbuser) are ignored."""
        user = self.admin
        user.last_active = datetime.now()
        user.save()

        entries = self._get_audit_entries("hbuser", user.id)
        # Should be empty since only last_active changed
        self.assertEqual(len(entries), 0)

    def test_changed_fields_lists_only_modified_columns(self):
        """changed_fields should only contain columns that actually changed."""
        individual = self.individuals[0]
        individual.name = "NyttNamn"
        individual.save()

        entries = self._get_audit_entries("individual", individual.id)
        self.assertEqual(len(entries), 1)
        # changed_fields is a text[] from PG, read as list by Peewee
        self.assertIn("name", entries[0].changed_fields)
        # Fields that didn't change should not be listed
        self.assertNotIn("number", entries[0].changed_fields)

    def test_audit_user_from_session_variable(self):
        """changed_by is populated from the audit.user session variable."""
        # Use set_config() because 'user' is a reserved keyword in PostgreSQL
        db.DATABASE.execute_sql("SELECT set_config('audit.user', 'testuser', false)")
        try:
            individual = self.individuals[0]
            individual.name = "AuditTest"
            individual.save()

            entries = self._get_audit_entries("individual", individual.id)
            self.assertEqual(entries[0].changed_by, "testuser")
        finally:
            db.DATABASE.execute_sql("SELECT set_config('audit.user', '', false)")

    def test_audit_ip_from_session_variable(self):
        """ip_address is populated from the audit.ip session variable."""
        db.DATABASE.execute_sql("SELECT set_config('audit.ip', '192.168.1.42', false)")
        try:
            individual = self.individuals[0]
            individual.name = "IPTest"
            individual.save()

            entries = self._get_audit_entries("individual", individual.id)
            self.assertEqual(entries[0].ip_address, "192.168.1.42")
        finally:
            db.DATABASE.execute_sql("SELECT set_config('audit.ip', '', false)")

    def test_delete_on_audit_log_is_blocked(self):
        """DELETE on audit_log should be silently blocked (append-only, NFR-S8)."""
        individual = self.individuals[0]
        individual.name = "AppendOnlyTest"
        individual.save()

        entries_before = self._get_audit_entries("individual", individual.id)
        self.assertTrue(len(entries_before) > 0)

        # DELETE should be silently ignored by the rule
        db.DATABASE.execute_sql("DELETE FROM audit_log")

        entries_after = self._get_audit_entries("individual", individual.id)
        self.assertEqual(len(entries_before), len(entries_after))

    def test_update_on_audit_log_is_blocked(self):
        """UPDATE on audit_log should be silently blocked (append-only, NFR-S8)."""
        individual = self.individuals[0]
        individual.name = "AppendOnlyUpdate"
        individual.save()

        entries = self._get_audit_entries("individual", individual.id)
        original_op = entries[0].operation

        # UPDATE should be silently ignored by the rule
        db.DATABASE.execute_sql(
            "UPDATE audit_log SET operation = 'TAMPERED' WHERE id = %s",
            (entries[0].id,),
        )

        refreshed = db.AuditLog.get_by_id(entries[0].id)
        self.assertEqual(refreshed.operation, original_op)

    def test_all_tracked_tables_have_triggers(self):
        """All tables in AUDITED_TABLES should have audit_trigger attached."""
        cursor = db.DATABASE.execute_sql("""
            SELECT event_object_table
            FROM information_schema.triggers
            WHERE trigger_name = 'audit_trigger'
            ORDER BY event_object_table
        """)
        triggered_tables = {row[0] for row in cursor.fetchall()}

        for table in db.AUDITED_TABLES:
            self.assertIn(
                table,
                triggered_tables,
                f"Missing audit trigger on table '{table}'",
            )

    def test_delete_lists_all_tracked_columns(self):
        """DELETE audit entries list every non-detection-excluded column
        (was NULL before the Phase 17 split-exclusion rewrite)."""
        new_weight = db.Weight.create(
            individual=self.individuals[0],
            weight=4.0,
            weight_date=datetime.now().date(),
        )
        self._clear_audit_log()

        weight_id = new_weight.id
        new_weight.delete_instance()

        entries = self._get_audit_entries("weight", weight_id)
        self.assertEqual(len(entries), 1)
        self.assertIsInstance(entries[0].changed_fields, list)
        self.assertIn("weight", entries[0].changed_fields)

    def test_split_exclusion_tuple_shape(self):
        """Every entry is (pk_col, snapshot_excluded,
        change_detection_excluded); genebank + authenticators are audited."""
        for table, entry in db.AUDITED_TABLES.items():
            self.assertIsInstance(entry, tuple, f"{table}: entry is not a tuple")
            self.assertEqual(
                len(entry),
                3,
                f"{table}: expected (pk_col, snapshot_excluded, "
                f"change_detection_excluded) 3-tuple, got {len(entry)}-tuple",
            )
            pk_col, snapshot_excluded, change_detection_excluded = entry
            self.assertIsInstance(pk_col, str)
            self.assertIsInstance(snapshot_excluded, list)
            self.assertIsInstance(change_detection_excluded, list)

        # hbuser: password_hash kept as belt for pre-v6 rows;
        # last_active noise suppression preserved.
        _, snapshot_excluded, change_detection_excluded = db.AUDITED_TABLES["hbuser"]
        self.assertIn("password_hash", snapshot_excluded)
        self.assertIn("last_active", change_detection_excluded)

        # authenticators: passwords live in auth_data today.
        pk_col, snapshot_excluded, change_detection_excluded = db.AUDITED_TABLES["authenticators"]
        self.assertEqual(pk_col, "auth_id")
        self.assertIn("auth_data", snapshot_excluded)
        self.assertEqual(change_detection_excluded, [])

        # genebank: name edits need a trail.
        pk_col, snapshot_excluded, change_detection_excluded = db.AUDITED_TABLES["genebank"]
        self.assertEqual(pk_col, "genebank_id")
        self.assertEqual(snapshot_excluded, [])
        self.assertEqual(change_detection_excluded, [])

        # Prior single-list `excluded` entries migrated into the THIRD slot.
        _, _, change_detection_excluded = db.AUDITED_TABLES["individual"]
        self.assertIn("updated_at", change_detection_excluded)

    def test_restore_record_with_snapshot_excluded_table(self):
        """Regression: restore_record() must 3-unpack
        AUDITED_TABLES. hbuser has a non-empty snapshot_excluded list; a
        restore on it exercises the unpack site at data_access.py:3204."""
        user = self.admin
        user.fullname = "Före Ändring"
        user.save()
        self._clear_audit_log()
        user.fullname = "Efter Ändring"
        user.save()
        entries = self._get_audit_entries("hbuser", user.id)
        self.assertEqual(len(entries), 1)
        result, status = da.restore_record("hbuser", user.id, entries[0].id)
        self.assertEqual(status, 200, f"restore_record failed: {result}")
        self.assertEqual(db.User.get_by_id(user.id).fullname, "Före Ändring")

    def test_imported_rows_cannot_be_reverted_or_restored(self):
        """Rows not written by the trigger (schema_name 'v1': the old
        Stamboken's change logs) are history only — their snapshots are
        partial and in v1's value format."""
        individual = self.individuals[0]
        name = individual.name
        entry = db.AuditLog.create(
            schema_name="v1",
            table_name="individual",
            record_id=str(individual.id),
            operation="UPDATE",
            old_data={"name": "Från v1"},
            new_data={"name": name},
            changed_fields=["name"],
        )
        self.assertEqual(da.revert_audit_entry(entry.id)[1], 400)
        self.assertEqual(da.restore_record("individual", individual.id, entry.id)[1], 400)
        self.assertEqual(db.Individual.get_by_id(individual.id).name, name)
        history = da.get_audit_history("individual", individual.id)["data"]
        self.assertEqual([e["schema_name"] for e in history], ["v1"])

    def test_migration_from_v20_db_with_legacy_triggers_no_double_audit(self):
        """The legacy shared-name `audit_trigger` must be
        REPLACED, not stacked. If replacement missed the legacy name, both
        triggers would fire — two rows per write plus TG_ARGV errors."""
        # Simulate a v20 database state on hbuser: legacy trigger + old function.
        db.DATABASE.execute_sql("DROP TRIGGER IF EXISTS audit_trigger ON hbuser")
        db.DATABASE.execute_sql("""
            CREATE OR REPLACE FUNCTION audit_trigger_func_legacy() RETURNS trigger
            AS $$ BEGIN
                INSERT INTO audit_log (table_name, record_id, operation, new_data)
                VALUES (TG_TABLE_NAME, NEW.user_id::text, TG_OP, to_jsonb(NEW));
                RETURN NEW;
            END $$ LANGUAGE plpgsql;
        """)
        db.DATABASE.execute_sql("""
            CREATE TRIGGER audit_trigger AFTER INSERT OR UPDATE ON hbuser
            FOR EACH ROW EXECUTE FUNCTION audit_trigger_func_legacy();
        """)

        # The migration path re-runs _create_audit_table_and_triggers().
        db._create_audit_table_and_triggers()

        row = db.DATABASE.execute_sql("""
            SELECT COUNT(*) FROM pg_trigger
            WHERE tgname = 'audit_trigger'
              AND tgrelid = 'hbuser'::regclass
              AND NOT tgisinternal
        """).fetchone()
        self.assertEqual(row[0], 1)

        self._clear_audit_log()
        new_user = da.register_user("orphan@example.com", "pass", username="orphan")
        entries = self._get_audit_entries("hbuser", new_user.id)
        self.assertEqual(len(entries), 1)

        db.DATABASE.execute_sql("DROP FUNCTION IF EXISTS audit_trigger_func_legacy()")
