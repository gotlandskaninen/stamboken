#!/usr/bin/env python3
"""
The nightly deletion of member applications that never led to membership (12 calendar months).

Only runs on PostgreSQL (interval arithmetic). Addresses are from the reserved example.invalid domain.
"""

import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

import herdbook
import utils.cache_invalidation as ci
import utils.data_access as da
import utils.database as db

from tests.database_test import DatabaseTest

_USE_POSTGRES = bool(os.getenv("POSTGRES_HOST")) and bool(os.getenv("POSTGRES_DB"))

NOW = datetime(2026, 11, 14, 3, 50, tzinfo=timezone.utc)
OLD = datetime(2025, 11, 13)  # more than 12 calendar months before NOW
YOUNG = datetime(2025, 11, 20)  # clearly less than 12 calendar months before NOW, margin included


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
        rejected_young = _application("rejected", YOUNG, reviewed_at=YOUNG)
        pending_young = _application("pending", YOUNG)
        approved_old = _application("approved", OLD, reviewed_at=OLD)

        self.assertEqual(da.purge_member_applications(NOW), 2)  # rejected_old and pending_old

        self.assertEqual(_ids(), {rejected_young, pending_young, approved_old})
        self.assertNotIn(rejected_old, _ids())
        self.assertNotIn(pending_old, _ids())
        self.assertEqual(da.purge_member_applications(NOW), 0)

    def test_one_day_margin_deletes_a_row_whose_12_months_end_before_the_next_run(self):
        kept = _application("pending", datetime(2025, 11, 15, 12, 0))  # 12 months end after tonight's cutoff
        last_day = _application("pending", datetime(2025, 11, 15, 1, 0))  # 12 months end before tomorrow's run
        da.purge_member_applications(datetime(2026, 11, 14, 3, 50).astimezone())
        self.assertEqual(_ids(), {kept})
        self.assertNotIn(last_day, _ids())

    def test_rejected_counts_from_submission_not_from_the_decision(self):
        gone = _application("rejected", OLD, reviewed_at=YOUNG)  # decided late, submitted over 12 months ago
        kept = _application("rejected", YOUNG)
        da.purge_member_applications(NOW)
        self.assertEqual(_ids(), {kept})
        self.assertNotIn(gone, _ids())

    def test_leap_day_application_goes_by_28_february(self):
        leap = _application("pending", datetime(2028, 2, 29, 1, 0))
        da.purge_member_applications(datetime(2029, 2, 26, 23, 0).astimezone())
        self.assertIn(leap, _ids())
        da.purge_member_applications(datetime(2029, 2, 27, 3, 50).astimezone())
        self.assertNotIn(leap, _ids())

    def test_twelve_months_not_365_days_and_equality_at_the_cutoff_counts(self):
        row = _application("pending", datetime(2027, 3, 1, 3, 50))  # 12 months end 2028-03-01, a leap year
        da.purge_member_applications(datetime(2028, 2, 28, 3, 50).astimezone())
        self.assertIn(row, _ids())  # 365 days would already have ended on 2028-02-29
        da.purge_member_applications(datetime(2028, 2, 29, 3, 50).astimezone())  # cutoff 2028-03-01 03:50 exactly
        self.assertNotIn(row, _ids())

    def test_margin_is_a_local_calendar_day_across_the_autumn_clock_change(self):
        row = _application("pending", datetime(2025, 10, 25, 3, 15))
        old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/Stockholm"
        time.tzset()
        try:  # 03:50 local on 2026-10-24 is 01:50 UTC; the next day is 25 hours long
            da.purge_member_applications(datetime(2026, 10, 24, 1, 50, tzinfo=timezone.utc))
        finally:
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            time.tzset()
        self.assertNotIn(row, _ids())


class TestPurgeMemberApplicationsJob(unittest.TestCase):
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

    def test_the_leader_registers_the_job_at_03_50(self):
        lock = os.path.join(tempfile.mkdtemp(), "scheduler.lock")
        with (
            mock.patch.object(herdbook, "SCHEDULER_LOCK_PATH", lock),
            mock.patch.object(ci, "init_redis"),
            mock.patch.object(ci, "start_pubsub_listener"),
            mock.patch.object(ci, "set_cache_and_functions"),
            mock.patch.object(herdbook, "_warm_genetics_in_background"),
            mock.patch.object(herdbook.apscheduler.schedulers.background, "BackgroundScheduler") as scheduler_cls,
        ):
            herdbook.initialize_app()
        (job,) = [
            c
            for c in scheduler_cls.return_value.add_job.call_args_list
            if herdbook._purge_member_applications in c.args
        ]
        self.assertEqual(job.args[1], "cron")
        self.assertEqual(
            {k: job.kwargs[k] for k in ("hour", "minute", "id", "max_instances")},
            {"hour": 3, "minute": 50, "id": "member_application_purge", "max_instances": 1},
        )
