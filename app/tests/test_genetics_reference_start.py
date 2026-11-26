"""The reference window's first day: live_start() and the population-metrics field reference_start."""

import os

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

from datetime import date, timedelta  # noqa: E402
from unittest.mock import patch  # noqa: E402

import herdbook  # noqa: E402
import utils.database as db  # noqa: E402
import utils.genetics_service as gs  # noqa: E402
import utils.pedigree_snapshot as ps  # noqa: E402
import utils.reference_population as rp  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402

limiter.enabled = False  # several logins in a row


class TestReferenceStart(DatabaseTest):
    """Dates three and two years back: neither is the fallback, 1 January last year."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        ps.reset_for_tests()
        self.addCleanup(ps.reset_for_tests)
        self.today = date.today()
        self.older = self._round(self.today.year - 3, self.today - timedelta(days=400))
        self.expected = date(self.today.year - 3, 1, 1)

    def _round(self, year, end_date):
        return db.YearlyReportRound.create(
            report_year=year, start_date=date(year, 12, 31), end_date=end_date, created_by=self.admin
        )

    def test_live_start_follows_the_definition(self):
        self.assertEqual(rp.live_start(self.today), self.expected)
        self.assertNotEqual(self.expected, date(self.today.year - 1, 1, 1))  # not the fallback
        rolling = rp.ReferenceDefinition(3, "rolling_days", 457)
        self.assertEqual(rp.live_start(self.today, rolling), self.today - timedelta(days=457))

    def _metrics(self, gb):
        self.client.post("/api/login", json={"username": "admin", "password": "pass"})
        res = self.client.get(f"/api/{gb}/population-metrics/")
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        return res.get_json()

    def test_population_metrics_report_the_start(self):
        self.assertEqual(self._metrics(self.genebanks[0].id)["reference_start"], self.expected.isoformat())
        self.assertNotIn("reference_start", gs.get_population_metrics(self.genebanks[0].id))  # not memoized

    def test_an_older_snapshot_keeps_the_start_its_members_were_read_with(self):
        gb = self.genebanks[0].id
        served = gs.snapshot(gb)
        self.assertEqual(served.reference_start, self.expected)

        # A later round closes: today's rule moves on while the older snapshot is still served.
        self._round(self.today.year - 2, self.today - timedelta(days=1))
        self.assertEqual(rp.live_start(self.today), date(self.today.year - 2, 1, 1))
        with patch.object(gs, "snapshot", return_value=served):
            self.assertEqual(self._metrics(gb)["reference_start"], self.expected.isoformat())

        # A fresh build reads the new rounds with its members.
        ps.reset_for_tests()
        self.assertEqual(gs.snapshot(gb).reference_start, date(self.today.year - 2, 1, 1))

    def test_metrics_from_the_cache_get_the_pinned_snapshots_date(self):
        """A memo keyed on content can hold numbers from a snapshot with another date: the route adds its own."""
        gb = self.genebanks[0].id
        served = gs.snapshot(gb)
        cached = {"n_active": 99, "mean_kinship": 0.01}
        with patch.object(herdbook, "_get_population_metrics_cached", return_value=cached) as memo:
            body = self._metrics(gb)
        memo.assert_called_once()
        self.assertEqual(body, {**cached, "reference_start": served.reference_start.isoformat()})
        self.assertEqual(cached, {"n_active": 99, "mean_kinship": 0.01})  # the cached dict is not changed

    def test_a_failed_snapshot_has_no_date_but_a_genebank_without_members_has_one(self):
        """Both answer zeros; only the date tells the page an empty genebank from a failed calculation."""
        empty = db.Genebank.create(name="Tom genbank")
        body = self._metrics(empty.id)
        self.assertEqual((body["n_active"], body["reference_start"]), (0, self.expected.isoformat()))

        with patch.object(gs, "snapshot", return_value=None):  # the first build failed
            body = self._metrics(self.genebanks[0].id)
        self.assertEqual((body["n_active"], body["reference_start"]), (0, None))
