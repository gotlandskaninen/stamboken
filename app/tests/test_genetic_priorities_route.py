"""The work list fields on /api/<g_id>/genetic-priorities/ and who may read them."""

import os
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402
from tests.ht_helpers import ht_row  # noqa: E402


def _priority(number):
    return {
        "individual_id": number,
        "priority": "critical",
        "reasons": [],
        "genetic_value_score": 90.0,
        "genome_uniqueness": 0.1,
    }


class TestGeneticPrioritiesRoute(DatabaseTest):
    def setUp(self):
        APP.config["TESTING"] = True  # nosemgrep
        self.addCleanup(APP.config.__setitem__, "SESSION_COOKIE_NAME", APP.config["SESSION_COOKIE_NAME"])  # restored
        APP.config["SESSION_COOKIE_NAME"] = "test_session"
        limiter.enabled = False
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, user):
        self.client.post("/api/login", json={"username": user.email, "password": "pass"})

    def _get(self, genebank, rows):
        with patch("herdbook.get_genetic_priorities", return_value=rows):
            return self.client.get(f"/api/{genebank.id}/genetic-priorities/")

    def test_rows_carry_name_sex_birth_date_and_current_herd(self):
        rabbit = self.individuals[0]
        rabbit.name, rabbit.sex = "Testa", "female"
        rabbit.save()
        # Sold to G2 after its birth in G1: the list shows where it is now.
        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[1],
            signature=self.manager,
            individual=rabbit,
            herd_tracking_date=datetime.now() - timedelta(days=10),
        )
        self._login(self.manager)
        res = self._get(self.genebanks[0], [_priority("G1-2111"), _priority("G9-9999")])
        self.assertEqual(res.status_code, 200)
        sold, unknown = res.get_json()["data"]
        self.assertEqual(
            {k: sold[k] for k in ("individual_id", "priority", "name", "sex", "birth_date", "herd")},
            {
                "individual_id": "G1-2111",
                "priority": "critical",
                "name": "Testa",
                "sex": "female",
                "birth_date": "2021-02-01",
                "herd": "G2",
            },
        )
        # A number the database no longer has keeps its priority row, without the added fields.
        self.assertEqual(unknown, _priority("G9-9999"))

    def test_the_memoized_rows_are_not_changed(self):
        rows = [_priority("G1-2111")]
        self._login(self.manager)
        self.assertEqual(self._get(self.genebanks[0], rows).status_code, 200)
        self.assertEqual(rows, [_priority("G1-2111")])

    def test_an_empty_list_answers_200(self):
        self._login(self.manager)
        res = self._get(self.genebanks[0], [])
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["data"], [])

    def test_owner_without_manager_role_is_denied(self):
        self._login(self.owner)
        self.assertEqual(self._get(self.genebanks[0], [_priority("G1-2111")]).status_code, 403)

    def test_manager_of_the_other_genebank_is_denied(self):
        self._login(self.manager)
        self.assertEqual(self._get(self.genebanks[1], [_priority("M3-2111")]).status_code, 403)
