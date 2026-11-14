"""A scheduler lock file left by a dead leader worker must not block leader election.

isort:skip_file
"""

import os
import tempfile
from unittest.mock import patch

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import herdbook  # noqa: E402
import utils.cache_invalidation as ci  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402


class TestSchedulerLeaderElection(DatabaseTest):
    def test_respawned_worker_takes_over_after_leader_died(self):
        lock = os.path.join(tempfile.mkdtemp(), "scheduler.lock")
        open(lock, "w").close()  # what the dead leader left behind: the file, no live holder
        with (
            patch.object(herdbook, "SCHEDULER_LOCK_PATH", lock),
            patch.object(ci, "init_redis"),
            patch.object(ci, "start_pubsub_listener"),
            patch.object(ci, "set_cache_and_functions"),
            patch.object(herdbook, "_warm_genetics_in_background"),
            patch.object(herdbook.gblogging, "create_genebank_logs"),
            patch.object(herdbook.apscheduler.schedulers.background, "BackgroundScheduler") as scheduler_cls,
        ):
            herdbook.initialize_app()  # the replacement worker gunicorn forks
        self.assertEqual(scheduler_cls.call_count, 1)
