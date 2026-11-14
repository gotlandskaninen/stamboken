#!/usr/bin/env python3
"""
The nightly removal of IP addresses older than 12 months from audit_log.

Only runs on PostgreSQL (rules). Addresses are from the documentation range 192.0.2.0/24.
"""

import os
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import herdbook
import utils.data_access as da
import utils.database as db

from tests.database_test import DatabaseTest

_USE_POSTGRES = bool(os.getenv("POSTGRES_HOST")) and bool(os.getenv("POSTGRES_DB"))

NOW = datetime(2026, 11, 14, 3, 45, tzinfo=timezone.utc)
CUTOFF = datetime(2025, 11, 14, 3, 45, tzinfo=timezone.utc)  # NOW less 12 calendar months


def _seed(changed_at, ip="192.0.2.7"):
    """One audit row, written straight into the table (INSERT passes the rules). Returns its id."""
    return db.DATABASE.execute_sql(
        """
        INSERT INTO audit_log
            (table_name, record_id, operation, old_data, new_data, changed_fields, changed_by, ip_address, changed_at)
        VALUES ('herd', '1', 'UPDATE', '{"herd_name": "Gammal"}', '{"herd_name": "Ny"}',
                ARRAY['herd_name']::TEXT[], 'editor', %s, %s)
        RETURNING id
        """,
        (ip, changed_at),
    ).fetchone()[0]


def _row(row_id):
    """The whole row as a dict, ip_address included."""
    return db.DATABASE.execute_sql("SELECT to_jsonb(a) FROM audit_log a WHERE id = %s", (row_id,)).fetchone()[0]


def _markers():
    return db.DATABASE.execute_sql(
        "SELECT record_id, new_data FROM audit_log WHERE operation = 'REDACT' AND record_id LIKE %s", ("purge-ip-%",)
    ).fetchall()


def _rule_exists():
    return db.DATABASE.execute_sql(
        "SELECT count(*) FROM pg_rules WHERE tablename = 'audit_log' AND rulename = 'audit_log_no_update'"
    ).fetchone()[0]


@unittest.skipUnless(_USE_POSTGRES, "audit_log rules require PostgreSQL")
class TestPurgeAuditIp(DatabaseTest):
    def setUp(self):
        super().setUp()
        db.DATABASE.execute_sql("TRUNCATE audit_log RESTART IDENTITY")  # TRUNCATE passes the rules

    def test_old_rows_lose_only_the_ip_and_young_rows_are_untouched(self):
        old = [_seed(NOW - timedelta(days=400)) for _ in range(6)] + [_seed(CUTOFF - timedelta(seconds=1))]
        young = [_seed(CUTOFF), _seed(NOW - timedelta(days=30))]  # exactly 12 months old is kept
        before = {row_id: _row(row_id) for row_id in old + young}

        self.assertEqual(da.purge_audit_ip(NOW, batch=2), len(old))  # three full batches and one short

        for row_id in old:
            after = _row(row_id)
            self.assertIsNone(after.pop("ip_address"))
            expected = dict(before[row_id])
            expected.pop("ip_address")
            self.assertEqual(after, expected)
        for row_id in young:
            self.assertEqual(_row(row_id), before[row_id])

    def test_a_run_leaves_one_marker_with_the_count(self):
        _seed(NOW - timedelta(days=400))
        _seed(NOW - timedelta(days=400))
        da.purge_audit_ip(NOW, batch=1)
        self.assertEqual(_markers(), [("purge-ip-20261114T034500Z", {"rows_redacted": 2})])

    def test_second_run_changes_nothing_and_leaves_no_marker(self):
        _seed(NOW - timedelta(days=400))
        _seed(NOW - timedelta(days=400), ip=None)
        self.assertEqual(da.purge_audit_ip(NOW), 1)
        self.assertEqual(da.purge_audit_ip(NOW), 0)
        self.assertEqual(len(_markers()), 1)

    def test_plain_update_is_still_refused_after_a_purge(self):
        row_id = _seed(NOW - timedelta(days=400))
        da.purge_audit_ip(NOW)
        db.DATABASE.execute_sql("UPDATE audit_log SET ip_address = '192.0.2.99', changed_by = 'x' WHERE id = %s", (row_id,))
        row = _row(row_id)
        self.assertIsNone(row["ip_address"])
        self.assertEqual(row["changed_by"], "editor")

    def test_a_held_lock_ends_the_run_and_keeps_the_rule(self):
        row_id = _seed(NOW - timedelta(days=400))
        locked, release = threading.Event(), threading.Event()

        def hold_lock():
            try:
                with db.DATABASE.atomic():
                    db.DATABASE.execute_sql("LOCK TABLE audit_log IN ACCESS SHARE MODE")
                    locked.set()
                    release.wait(timeout=10)
            finally:
                db.DB_PROXY.close()

        holder = threading.Thread(target=hold_lock)
        holder.start()
        try:
            self.assertTrue(locked.wait(timeout=10))
            with mock.patch.object(da, "AUDIT_IP_LOCK_TIMEOUT", "100ms"):
                self.assertEqual(da.purge_audit_ip(NOW), 0)
        finally:
            release.set()
            holder.join(timeout=10)
        self.assertEqual(_rule_exists(), 1)
        self.assertEqual(_row(row_id)["ip_address"], "192.0.2.7")
        self.assertEqual(_markers(), [])

    def test_migration_creates_the_partial_index(self):
        self.addCleanup(db.check_migrations)
        db.DATABASE.execute_sql("DROP INDEX IF EXISTS idx_audit_log_ip_retention")
        db.SchemaHistory.delete().where(db.SchemaHistory.version >= 38).execute()
        db.check_migrations()
        indexdef = db.DATABASE.execute_sql(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_audit_log_ip_retention'"
        ).fetchone()[0]
        self.assertIn("WHERE (ip_address IS NOT NULL)", indexdef)

    def test_job_logs_and_closes_connection(self):
        with (
            mock.patch.object(da, "purge_audit_ip", return_value=3) as purge,
            mock.patch.object(herdbook.genetics.ps, "_close_db_connection") as close,
        ):
            herdbook._purge_audit_ip()
            self.assertIsNotNone(purge.call_args.args[0].tzinfo)
            purge.side_effect = RuntimeError("database gone")
            with self.assertRaises(RuntimeError):
                herdbook._purge_audit_ip()
        self.assertEqual(close.call_count, 2)
