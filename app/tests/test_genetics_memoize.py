"""
The memoized genetics wrappers in herdbook.py must not cache a failure.

A failed computation (e.g. a pedigree error) returns {} to the caller, but
that {} must not be memoized for KINSHIP_LIFETIME: the next call recomputes.
A successful result is still memoized.
"""

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import herdbook
from cachelib import SimpleCache

CASES = (
    ("get_inbreeding", "get_inbreeding"),
    ("get_kinship", "get_kinship_matrix"),
    ("get_mean_kinship", "get_mean_kinship"),
)


class TestGeneticsFailuresNotMemoized(unittest.TestCase):
    def test_failure_is_not_cached_but_success_is(self):
        # An isolated in-memory backend, so the test does not share Redis
        # state with other (parallel) tests.
        backend = {herdbook.CACHE: SimpleCache()}
        with patch.dict(herdbook.APP.extensions["cache"], backend):
            for offset, (wrapper_name, service_name) in enumerate(CASES):
                with self.subTest(wrapper_name):
                    wrapper = getattr(herdbook, wrapper_name)
                    g_id = 987650 + offset
                    results = [RuntimeError("pedigree cycle"), {"X": 0.25}, {"Y": 1.0}]
                    snap = SimpleNamespace(genebank_id=g_id, key=(1, date.today(), 2, 1, "e"))  # no database here
                    with (
                        patch.object(herdbook.genetics, "snapshot", return_value=snap),
                        patch.object(herdbook.genetics, service_name, side_effect=results) as service,
                    ):
                        self.assertEqual(wrapper(g_id), {})
                        self.assertEqual(wrapper(g_id), {"X": 0.25})  # failure was not cached
                        self.assertEqual(wrapper(g_id), {"X": 0.25})  # success was cached
                        self.assertEqual(service.call_count, 2)

    def test_unreadable_snapshot_returns_empty_like_before(self):
        backend = {herdbook.CACHE: SimpleCache()}
        with (
            patch.dict(herdbook.APP.extensions["cache"], backend),
            patch.object(herdbook.genetics, "snapshot", side_effect=RuntimeError("database down")),
        ):
            for wrapper_name, _ in CASES:
                with self.subTest(wrapper_name):
                    self.assertEqual(getattr(herdbook, wrapper_name)(987660), {})
