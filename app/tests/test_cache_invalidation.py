"""Tests for cache invalidation module."""

import time
import unittest
from unittest.mock import MagicMock, patch

from utils.cache_invalidation import (
    _handle_invalidation_message,
    get_genebank_ids_for_individual,
    poll_debounce_keys,
    set_cache_and_functions,
    trigger_invalidation,
)


class TestGetGenebankIds(unittest.TestCase):
    """Test genebank ID resolution for invalidation."""

    @patch("utils.cache_invalidation.DBIndividual")
    def test_returns_genebank_id_for_individual(self, mock_ind):
        """Resolving an individual's genebank ID."""
        mock_ind.get_by_id.return_value = MagicMock(origin_herd=MagicMock(genebank=MagicMock(id=1)))
        result = get_genebank_ids_for_individual(42)
        assert result == {1}

    @patch("utils.cache_invalidation.DBIndividual")
    def test_returns_empty_set_on_not_found(self, mock_ind):
        """Missing individual returns empty set."""
        mock_ind.get_by_id.side_effect = Exception("not found")
        result = get_genebank_ids_for_individual(999)
        assert result == set()


class TestTriggerInvalidation(unittest.TestCase):
    """Test the trigger_invalidation function."""

    def setUp(self):
        """Set up mock functions so a stray recompute would be visible."""
        self.mock_funcs = [MagicMock(name=f"func_{i}") for i in range(7)]
        self.mock_breeding = MagicMock(name="breeding_suggestions")
        set_cache_and_functions(memoized_funcs=self.mock_funcs, breeding_suggestions_func=self.mock_breeding)

    @patch("utils.cache_invalidation._redis_client")
    def test_publishes_to_pubsub(self, mock_redis):
        """trigger_invalidation publishes genebank_id to pub/sub channel."""
        trigger_invalidation(1)
        mock_redis.publish.assert_called_once_with("herdbook:cache:invalidate", "1")

    @patch("utils.cache_invalidation._redis_client")
    def test_sets_debounce_key(self, mock_redis):
        """trigger_invalidation records debounce intent in Redis."""
        trigger_invalidation(1)
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == "debounce:1"

    @patch("utils.cache_invalidation._redis_client")
    def test_only_publishes_and_debounces(self, mock_redis):
        """Memo keys follow the snapshot: nothing is deleted, nothing recomputed inline."""
        trigger_invalidation(1)
        assert {c[0] for c in mock_redis.method_calls} == {"publish", "set"}
        for func in self.mock_funcs:
            func.assert_not_called()


class TestPubSubHandler(unittest.TestCase):
    """Test the pub/sub message handler."""

    @patch("utils.cache_invalidation.genetics_service")
    def test_clears_per_worker_dicts(self, mock_genetics):
        """Handler clears genetics_service dicts for the genebank."""
        _handle_invalidation_message("1")
        mock_genetics.invalidate_cache.assert_called_once_with(1)
        mock_genetics.ps._close_db_connection.assert_called_once_with()  # listener thread holds no connection


class TestDebouncePolling(unittest.TestCase):
    """Test the debounce polling mechanism."""

    @patch("utils.cache_invalidation._redis_client")
    @patch("utils.cache_invalidation._recompute_genebank")
    def test_fires_after_delay(self, mock_recompute, mock_redis):
        """Debounce fires recomputation when timestamp is old enough."""
        mock_redis.keys.return_value = ["debounce:1"]
        mock_redis.get.return_value = str(int(time.time()) - 31)

        poll_debounce_keys()

        mock_recompute.assert_called_once_with(1)
        mock_redis.delete.assert_called_once_with("debounce:1")

    @patch("utils.cache_invalidation._redis_client")
    @patch("utils.cache_invalidation._recompute_genebank")
    def test_waits_during_window(self, mock_recompute, mock_redis):
        """Debounce does not fire while within the delay window."""
        mock_redis.keys.return_value = ["debounce:1"]
        mock_redis.get.return_value = str(int(time.time()) - 10)

        poll_debounce_keys()

        mock_recompute.assert_not_called()
