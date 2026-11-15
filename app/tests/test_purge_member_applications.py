#!/usr/bin/env python3
"""
The nightly deletion of member applications that never led to membership (12 calendar months).

Only runs on PostgreSQL (interval arithmetic). Addresses are from the reserved example.invalid domain.
"""

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import herdbook
import utils.data_access as da
import utils.database as db

from tests.database_test import DatabaseTest

_USE_POSTGRES = bool(os.getenv("POSTGRES_HOST")) and bool(os.getenv("POSTGRES_DB"))

NOW = datetime(2026, 11, 14, 3, 50, tzinfo=timezone.utc)
OLD = datetime(2025, 11, 13)  # more than 12 calendar months before NOW
YOUNG = datetime(2025, 11, 15)  # less than 12 calendar months before NOW


def _application(status, created_at, reviewed_at=None):
    return db.MemberApplication.create(
        first_name="Test",
        last_name="Sökande",
        email="sokande@example.invalid",
        gdpr_consented_at=created_at,
        status=status,
        created_at=created_at,
        reviewed_at=reviewed_at,
    ).id


def _ids():
    return {a.id for a in db.MemberApplication.select()}


@unittest.skipUnless(_USE_POSTGRES, "interval arithmetic requires PostgreSQL")
class TestPurgeMemberApplications(DatabaseTest):
    def test_old_rejected_and_pending_go_young_and_approved_stay(self):
        rejected_old = _application("rejected", OLD, reviewed_at=OLD)
        pending_old = _application("pending", OLD)
        rejected_young = _application("rejected", OLD, reviewed_at=YOUNG)  # counted from the decision
        pending_young = _application("pending", YOUNG)
        approved_old = _application("approved", OLD, reviewed_at=OLD)

        self.assertEqual(da.purge_member_applications(NOW), 2)

        self.assertEqual(_ids(), {rejected_young, pending_young, approved_old})
        self.assertNotIn(rejected_old, _ids())
        self.assertNotIn(pending_old, _ids())
        self.assertEqual(da.purge_member_applications(NOW), 0)

    def test_rejected_without_reviewed_at_counts_from_submission(self):
        gone = _application("rejected", OLD)
        kept = _application("rejected", YOUNG)
        da.purge_member_applications(NOW)
        self.assertEqual(_ids(), {kept})
        self.assertNotIn(gone, _ids())

    def test_job_logs_and_closes_connection(self):
        with (
            mock.patch.object(da, "purge_member_applications", return_value=3) as purge,
            mock.patch.object(herdbook.genetics.ps, "_close_db_connection") as close,
        ):
            with self.assertLogs(herdbook.APP.logger, "INFO") as logs:
                herdbook._purge_member_applications()
            self.assertIn("Deleted 3 member applications", logs.output[0])
            self.assertIsNotNone(purge.call_args.args[0].tzinfo)
            purge.side_effect = RuntimeError("database gone")
            with self.assertRaises(RuntimeError):
                herdbook._purge_member_applications()
        self.assertEqual(close.call_count, 2)
