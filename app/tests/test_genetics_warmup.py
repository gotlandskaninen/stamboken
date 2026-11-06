"""Startup warm-up: every worker builds its snapshots; only the scheduler leader warms the shared memo.

isort:skip_file
"""

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import call, patch

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import herdbook  # noqa: E402
import utils.cache_invalidation as ci  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402


def test_worker_warm_builds_only_the_snapshot_and_reference_kinship():
    banks = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    with (
        patch("herdbook.threading") as threading_mock,
        patch("herdbook.time"),
        patch.object(herdbook.da, "get_all_genebanks", return_value=banks),
        patch.object(herdbook.genetics, "snapshot") as snapshot,
        patch.object(herdbook.genetics.ps, "_close_db_connection"),
        patch.object(herdbook, "reload_genetics_caches") as reload_caches,
    ):
        herdbook._warm_genetics_in_background()
        threading_mock.Thread.call_args.kwargs["target"]()  # run the thread body here
    reload_caches.assert_not_called()
    assert snapshot.call_args_list == [call(1), call(2)]
    assert snapshot.return_value.reference_kinship.call_count == 2


class TestLeaderWarmsTheMemo(DatabaseTest):
    def test_only_the_scheduler_leader_registers_the_memo_warm_once(self):
        lock = os.path.join(tempfile.mkdtemp(), "scheduler.lock")
        with (
            patch.object(herdbook, "SCHEDULER_LOCK_PATH", lock),
            patch.object(ci, "init_redis"),
            patch.object(ci, "start_pubsub_listener"),
            patch.object(ci, "set_cache_and_functions"),
            patch.object(herdbook, "_warm_genetics_in_background") as worker_warm,
            patch.object(herdbook.gblogging, "create_genebank_logs"),
            patch.object(herdbook.apscheduler.schedulers.background, "BackgroundScheduler") as scheduler_cls,
        ):
            herdbook.initialize_app()  # first worker: takes the lock, becomes leader
            herdbook.initialize_app()  # second worker: lock exists
        self.assertEqual(worker_warm.call_count, 2)  # every worker builds its own snapshots
        self.assertEqual(scheduler_cls.call_count, 1)
        memo_jobs = [
            c for c in scheduler_cls.return_value.add_job.call_args_list if herdbook.reload_genetics_caches in c.args
        ]
        self.assertEqual(len(memo_jobs), 1)
        self.assertEqual(memo_jobs[0].kwargs.get("trigger"), "date")
