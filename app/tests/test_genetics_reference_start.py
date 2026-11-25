"""The reference window's first day: live_start() and the population-metrics field reference_start."""

import os

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

from datetime import date, timedelta  # noqa: E402

import utils.database as db  # noqa: E402
import utils.pedigree_snapshot as ps  # noqa: E402
import utils.reference_population as rp  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402

limiter.enabled = False  # several logins in a row


class TestReferenceStart(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        ps.reset_for_tests()
        self.addCleanup(ps.reset_for_tests)
        today = date.today()
        # A round for last year that closed ten days ago: the window starts 1 January last year.
        db.YearlyReportRound.create(
            report_year=today.year - 1,
            start_date=date(today.year - 1, 12, 31),
            end_date=today - timedelta(days=10),
            created_by=self.admin,
        )
        self.expected = date(today.year - 1, 1, 1)

    def test_live_start_follows_the_definition(self):
        today = date.today()
        self.assertEqual(rp.live_start(today), self.expected)
        self.assertEqual(rp.live_start(today), rp.reference_population_start(today))
        rolling = rp.ReferenceDefinition(3, "rolling_days", 457)
        self.assertEqual(rp.live_start(today, rolling), today - timedelta(days=457))

    def test_population_metrics_report_the_start(self):
        self.client.post("/api/login", json={"username": "admin", "password": "pass"})
        res = self.client.get(f"/api/{self.genebanks[0].id}/population-metrics/")
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        self.assertEqual(res.get_json()["reference_start"], self.expected.isoformat())
