"""
Integration tests for cache invalidation with live Redis and the database.

These tests require a running Redis instance (provided by docker-compose.pytest.yml).
They test the invalidation flow: trigger → pub/sub → background snapshot rebuild,
and the leader's genetics version poller.
"""

import os
import threading
import unittest
from unittest.mock import patch

import redis
import utils.cache_invalidation as ci
import utils.database as db
import utils.genetics_service as gs

from tests.database_test import DatabaseTest

# Skip if Redis is not available
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/1")
try:
    _test_redis = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=2, decode_responses=True)
    _test_redis.ping()
    REDIS_AVAILABLE = True
except Exception:
    REDIS_AVAILABLE = False


@unittest.skipUnless(REDIS_AVAILABLE, "Redis not available")
class TestCacheIntegration(unittest.TestCase):
    """Integration tests for cache invalidation with live Redis."""

    def setUp(self):
        """Flush test Redis DB before each test."""
        _test_redis.flushdb()

    def test_trigger_sets_debounce_key(self):
        """trigger_invalidation writes a debounce key to Redis."""
        ci.init_redis(REDIS_URL)
        ci.set_cache_and_functions(memoized_funcs=[], breeding_suggestions_func=None)

        ci.trigger_invalidation(1)

        val = _test_redis.get("debounce:1")
        assert val is not None

    def test_pubsub_round_trip(self):
        """Publish a message and verify a subscriber receives it."""
        client = ci.init_redis(REDIS_URL)

        pubsub = client.pubsub()
        pubsub.subscribe("herdbook:cache:invalidate")
        # Consume the subscribe confirmation
        pubsub.get_message(timeout=1)

        client.publish("herdbook:cache:invalidate", "42")
        msg = pubsub.get_message(timeout=2)
        assert msg is not None
        assert msg["data"] == "42"
        pubsub.unsubscribe()

    def tearDown(self):
        _test_redis.flushdb()


@unittest.skipUnless(REDIS_AVAILABLE, "Redis not available")
class TestInvalidationMessage(DatabaseTest):
    """A pub/sub message schedules a background rebuild; readers keep the snapshot meanwhile."""

    def setUp(self):
        super().setUp()
        _test_redis.flushdb()
        self.gb = self.genebanks[0].id
        gs.snapshot(self.gb)
        gs.ps.wait_for_builds(self.gb, timeout=10)

    def tearDown(self):
        _test_redis.flushdb()
        super().tearDown()

    def test_message_schedules_rebuild_and_keeps_snapshot(self):
        before = gs.snapshot(self.gb)
        client = ci.init_redis(REDIS_URL)
        ci.set_cache_and_functions(memoized_funcs=[], breeding_suggestions_func=None)
        pubsub = client.pubsub()
        pubsub.subscribe(ci.PUBSUB_CHANNEL)
        pubsub.get_message(timeout=1)  # subscribe confirmation

        release = threading.Event()
        real_load = gs.ps._load_fn

        def held_load(genebank_id):
            release.wait(10)
            return real_load(genebank_id)

        # A committed pedigree write: without one the retained snapshot is current and nothing rebuilds.
        db.DATABASE.execute_sql("UPDATE genetics_version SET version = version + 1 WHERE id = 1")
        try:
            with patch.object(gs.ps, "_load_fn", held_load):
                ci.trigger_invalidation(self.gb)
                msg = pubsub.get_message(timeout=2)
                self.assertEqual(msg["data"], str(self.gb))
                ci._handle_invalidation_message(msg["data"])

                self.assertFalse(gs.ps._inflight[self.gb].done())  # a rebuild is scheduled
                self.assertIs(gs.snapshot(self.gb), before)  # and the snapshot is still served
                release.set()
                gs.ps.wait_for_builds(self.gb, timeout=10)
        finally:
            release.set()
            pubsub.unsubscribe()

        after = gs.snapshot(self.gb)
        self.assertIsNot(after, before)
        self.assertGreater(after.seq, before.seq)


class TestGeneticsVersionPoller(DatabaseTest):
    """The leader poller hints a rebuild per genebank only when the version moved."""

    def setUp(self):
        super().setUp()
        ci._last_seen_version = None

    def tearDown(self):
        ci._last_seen_version = None
        super().tearDown()

    def test_triggers_once_per_genebank_only_when_version_moved(self):
        with patch.object(ci, "trigger_invalidation") as trigger:
            ci.poll_genetics_version()  # first poll: baseline only
            ci.poll_genetics_version()  # unchanged
            trigger.assert_not_called()

            db.Individual.update(death_date="2026-01-01").where(db.Individual.id == self.individuals[0].id).execute()
            ci.poll_genetics_version()
            self.assertEqual(
                sorted(c.args[0] for c in trigger.call_args_list),
                sorted(gb.id for gb in self.genebanks),
            )

            trigger.reset_mock()
            ci.poll_genetics_version()  # nothing moved since
            trigger.assert_not_called()

    def test_unreadable_version_triggers_nothing(self):
        with patch.object(ci, "trigger_invalidation") as trigger:
            ci.poll_genetics_version()
            with patch.object(db, "read_genetics_version", side_effect=RuntimeError("down")):
                ci.poll_genetics_version()
            trigger.assert_not_called()
