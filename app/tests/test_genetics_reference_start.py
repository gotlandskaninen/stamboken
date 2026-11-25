"""The reference window's first day: live_start() and the population-metrics field reference_start."""

import os

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

from datetime import date, timedelta  # noqa: E402
from unittest.mock import patch  # noqa: E402

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

    def test_population_metrics_report_the_start(self):
        self.client.post("/api/login", json={"username": "admin", "password": "pass"})
        res = self.client.get(f"/api/{self.genebanks[0].id}/population-metrics/")
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        self.assertEqual(res.get_json()["reference_start"], self.expected.isoformat())

    def test_an_older_snapshot_keeps_the_start_its_members_were_read_with(self):
        gb = self.genebanks[0].id
        served = gs.snapshot(gb)
        self.assertEqual(served.reference_start, self.expected)

        # A later round closes: today's rule moves on while the older snapshot is still served.
        self._round(self.today.year - 2, self.today - timedelta(days=1))
        self.assertEqual(rp.live_start(self.today), date(self.today.year - 2, 1, 1))
        with patch.object(gs, "snapshot", return_value=served):
            self.assertEqual(gs.get_population_metrics(gb)["reference_start"], self.expected.isoformat())

        # A fresh build reads the new rounds with its members.
        ps.reset_for_tests()
        self.assertEqual(gs.snapshot(gb).reference_start, date(self.today.year - 2, 1, 1))
