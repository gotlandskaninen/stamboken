#!/usr/bin/env python3
"""
Right-to-erasure helper tests.

Only runs on PostgreSQL (rules + JSONB). Fixtures always pass the NOT NULL
hbuser columns: db.User.create(username=..., email=..., uuid=uuid4()).
"""

import os
import unittest
from uuid import uuid4

import utils.data_access as da
import utils.database as db

from tests.database_test import DatabaseTest

_USE_POSTGRES = bool(os.getenv("POSTGRES_HOST")) and bool(os.getenv("POSTGRES_DB"))

ALL_PII_KEYS = [
    "email",
    "fullname",
    "google_email",
    "google_name",
    "profile_picture",
    "google_picture",
    "username",
    "uuid",
]


def _seed_hbuser_row_about(user_id, email, username):
    """A legacy-style hbuser snapshot carrying every PII key + non-PII keys.
    INSERT bypasses the append-only rules."""
    db.DATABASE.execute_sql(
        """
        INSERT INTO audit_log
            (table_name, record_id, operation, old_data, new_data,
             changed_fields, changed_by, ip_address)
        VALUES
            ('hbuser', %s, 'UPDATE',
             jsonb_build_object(
                 'email', %s, 'fullname', 'Full Name',
                 'google_email', 'g@example.com', 'google_name', 'G Name',
                 'profile_picture', '/pic.jpg', 'google_picture', 'https://g/p.jpg',
                 'username', %s, 'uuid', 'deadbeef',
                 'validated', false, 'privileges', '[]'),
             jsonb_build_object(
                 'email', %s, 'fullname', 'Full Name',
                 'google_email', 'g@example.com', 'google_name', 'G Name',
                 'profile_picture', '/pic.jpg', 'google_picture', 'https://g/p.jpg',
                 'username', %s, 'uuid', 'deadbeef',
                 'validated', true, 'privileges', '[]'),
             ARRAY['validated']::TEXT[], 'admin-actor', '10.0.0.9')
        """,
        (str(user_id), email, username, email, username),
    )


def _seed_row_written_by(changed_by, record_id="1"):
    """A herd edit authored by the user (changed_by = username-or-email)."""
    db.DATABASE.execute_sql(
        """
        INSERT INTO audit_log
            (table_name, record_id, operation, old_data, new_data,
             changed_fields, changed_by, ip_address)
        VALUES
            ('herd', %s, 'UPDATE',
             jsonb_build_object('herd_name', 'Gammal', 'email', 'kontakt@example.com'),
             jsonb_build_object('herd_name', 'Ny', 'email', 'kontakt@example.com'),
             ARRAY['herd_name']::TEXT[], %s, '10.0.0.1')
        """,
        (record_id, changed_by),
    )


@unittest.skipUnless(_USE_POSTGRES, "audit_log rules require PostgreSQL")
class TestPurgeUserAuditPii(DatabaseTest):
    def _make_user(self, username, email):
        return db.User.create(username=username, email=email, uuid=uuid4())

    def test_redacts_all_pii_keys_from_snapshots(self):
        """Every key redacted, incl. the later additions
        username, uuid and google_picture."""
        user = self._make_user("doomed", "doomed@example.com")
        _seed_hbuser_row_about(user.id, "doomed@example.com", "doomed")

        n = da.purge_user_audit_pii(user.id, "doomed", "doomed@example.com")
        self.assertGreaterEqual(n, 1)

        row = (
            db.AuditLog.select()
            .where(
                (db.AuditLog.table_name == "hbuser")
                & (db.AuditLog.record_id == str(user.id))
                & (db.AuditLog.operation == "UPDATE")
            )
            .first()
        )
        self.assertIsNotNone(row)
        for key in ALL_PII_KEYS:
            self.assertNotIn(key, row.old_data or {}, f"{key} left in old_data")
            self.assertNotIn(key, row.new_data or {}, f"{key} left in new_data")

    def test_pseudonymises_changed_by_and_nulls_ip_on_rows_written_by_user(self):
        """Matched on changed_by IN (username, email);
        regression against the earlier numeric-id match that hit nothing."""
        user = self._make_user("author", "author@example.com")
        _seed_row_written_by("author", record_id="7")
        _seed_row_written_by("author@example.com", record_id="8")

        n = da.purge_user_audit_pii(user.id, "author", "author@example.com")
        self.assertGreaterEqual(n, 2)

        for record_id in ("7", "8"):
            row = db.AuditLog.get((db.AuditLog.table_name == "herd") & (db.AuditLog.record_id == record_id))
            self.assertEqual(row.changed_by, f"raderad-{user.id}")
            self.assertIsNone(row.ip_address)

    def test_zero_history_returns_zero(self):
        """No history: returns 0, does not raise."""
        user = self._make_user("fresh", "fresh@example.com")
        # Creating the user itself fired the hbuser INSERT trigger — clear it
        # to model a genuinely history-less account (TRUNCATE bypasses rules).
        db.DATABASE.execute_sql("TRUNCATE audit_log RESTART IDENTITY")
        self.assertEqual(da.purge_user_audit_pii(user.id, "fresh", "fresh@example.com"), 0)

    def test_preserves_non_pii_and_other_users_rows(self):
        """Non-PII keys survive in matched rows; other
        users' rows are completely untouched."""
        user = self._make_user("target", "target@example.com")
        other = self._make_user("bystander", "bystander@example.com")
        _seed_hbuser_row_about(user.id, "target@example.com", "target")
        _seed_hbuser_row_about(other.id, "bystander@example.com", "bystander")

        da.purge_user_audit_pii(user.id, "target", "target@example.com")

        purged = (
            db.AuditLog.select()
            .where(
                (db.AuditLog.table_name == "hbuser")
                & (db.AuditLog.record_id == str(user.id))
                & (db.AuditLog.operation == "UPDATE")
            )
            .first()
        )
        self.assertIn("validated", purged.old_data or {})
        self.assertIn("privileges", purged.old_data or {})
        self.assertIn("validated", purged.new_data or {})

        untouched = (
            db.AuditLog.select()
            .where(
                (db.AuditLog.table_name == "hbuser")
                & (db.AuditLog.record_id == str(other.id))
                & (db.AuditLog.operation == "UPDATE")
            )
            .first()
        )
        self.assertEqual((untouched.old_data or {}).get("email"), "bystander@example.com")
        self.assertEqual(untouched.changed_by, "admin-actor")
        self.assertEqual(untouched.ip_address, "10.0.0.9")

    def test_rule_reinstated_after_purge(self):
        """A bare UPDATE after the purge is silently
        swallowed by the reinstated rule."""
        user = self._make_user("ruletest", "ruletest@example.com")
        _seed_hbuser_row_about(user.id, "ruletest@example.com", "ruletest")
        da.purge_user_audit_pii(user.id, "ruletest", "ruletest@example.com")

        db.DATABASE.execute_sql(
            "UPDATE audit_log SET changed_by = 'hacker' WHERE table_name = 'hbuser' AND record_id = %s",
            (str(user.id),),
        )
        row = (
            db.AuditLog.select()
            .where((db.AuditLog.table_name == "hbuser") & (db.AuditLog.record_id == str(user.id)))
            .first()
        )
        self.assertNotEqual(row.changed_by, "hacker")

    def test_marker_row_shape(self):
        """Marker: changed_by='system', operation='REDACT',
        record_id prefix, integer rows_redacted (no PII — only the numeric
        user_id survives as the pseudonym key)."""
        user = self._make_user("markertest", "markertest@example.com")
        _seed_hbuser_row_about(user.id, "markertest@example.com", "markertest")
        n = da.purge_user_audit_pii(user.id, "markertest", "markertest@example.com")

        marker = (
            db.AuditLog.select()
            .where(
                (db.AuditLog.table_name == "audit_log") & (db.AuditLog.record_id.startswith(f"purge-user-{user.id}-"))
            )
            .order_by(db.AuditLog.id.desc())
            .first()
        )
        self.assertIsNotNone(marker)
        self.assertEqual(marker.operation, "REDACT")
        self.assertEqual(marker.changed_by, "system")
        self.assertEqual((marker.new_data or {}).get("rows_redacted"), n)

    def test_purge_user_redacts_actor_rows(self):
        """ADR-0017: the user's command log rows lose their free text whatever their age; the actor stays."""
        user = self._make_user("actor", "actor@example.com")
        other = self._make_user("bystander", "bystander@example.com")
        ind = self.individuals[3]
        for who, notes in ((user, "egen text"), (other, "annans text")):
            db.IndividualCommand.create(
                operation_id=uuid4(),
                request_id=uuid4(),
                command="EditDescription",
                individual=ind,
                actor=who,
                before={"notes": None, "name": None},
                after={"notes": notes, "name": "Agnes"},
            )
        da.purge_user_audit_pii(user.id, "actor", "actor@example.com")
        purged = db.IndividualCommand.get(db.IndividualCommand.actor == user.id)
        self.assertEqual((purged.before, purged.after), ({"name": None}, {"name": "Agnes"}))
        self.assertIsNotNone(purged.redacted_at)
        kept = db.IndividualCommand.get(db.IndividualCommand.actor == other.id)
        self.assertEqual((kept.after, kept.redacted_at), ({"notes": "annans text", "name": "Agnes"}, None))
