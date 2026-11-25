"""The work list fields on /api/<g_id>/genetic-priorities/ and who may read them."""

import csv
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.database as db  # noqa: E402
import utils.pedigree_snapshot as ps  # noqa: E402
import utils.settings as settings  # noqa: E402
import utils.work_list as work_list  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402
from tests.ht_helpers import ht_row  # noqa: E402


def _priority(number, priority="critical", reasons=()):
    return {
        "individual_id": number,
        "priority": priority,
        "reasons": list(reasons),
        "genetic_value_score": 90.0,
        "genome_uniqueness": 0.1,
    }


class RouteTest(DatabaseTest):
    def setUp(self):
        APP.config["TESTING"] = True  # nosemgrep
        self.addCleanup(APP.config.__setitem__, "SESSION_COOKIE_NAME", APP.config["SESSION_COOKIE_NAME"])  # restored
        APP.config["SESSION_COOKIE_NAME"] = "test_session"
        limiter.enabled = False
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, user):
        self.client.post("/api/login", json={"username": user.email, "password": "pass"})


class TestGeneticPrioritiesRoute(RouteTest):
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

    def test_a_failed_details_read_still_answers_the_priorities(self):
        self._login(self.manager)
        with patch("utils.data_access.work_list_details", side_effect=RuntimeError("boom")):
            res = self._get(self.genebanks[0], [_priority("G1-2111")])
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["data"], [_priority("G1-2111")])


EXPORT = "/api/v2/genetics/{}/priorities.csv"


class TestPrioritiesExport(RouteTest):
    def _export(self, genebank, rows, query=""):
        with patch.dict(APP.extensions, {"genetic_priorities": lambda g_id: rows}):
            return self.client.get(EXPORT.format(genebank.id) + query)

    def _audit(self):
        return list(db.AuditLog.select().where(db.AuditLog.operation == "READ").order_by(db.AuditLog.id))

    def test_the_file_has_swedish_headers_and_safe_cells(self):
        rabbit = self.individuals[0]
        rabbit.name, rabbit.sex = '=HYPERLINK("x")', "eunuch"
        rabbit.save()
        rows = [
            _priority("G1-2111", reasons=["Sole active carrier of founder G1-1911"]),
            _priority("G1-2112", "important"),
            _priority("G9-9999", "normal"),
        ]
        self._login(self.manager)
        res = self._export(self.genebanks[0], rows)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["Cache-Control"], "no-store")
        self.assertIn('attachment; filename="avelsprioritet-genbank-', res.headers["Content-Disposition"])
        text = res.get_data(as_text=True)
        self.assertTrue(text.startswith("\ufeff"))
        header, first, second, gone = csv.reader(text[1:].splitlines(), delimiter=";")
        self.assertEqual(header, work_list.HEADER)
        self.assertEqual(
            first,
            [
                "G1-2111",
                ' =HYPERLINK("x")',
                "G1",
                "Hane (kastrerad)",
                "2021-02-01",
                "Högsta",
                "90",
                "10,0",
                "Enda kaninen i beräkningen med gener från founderdjuret G1-1911",
            ],
        )
        self.assertEqual(second[:6], ["G1-2112", "", "G1", "Okänt", "2021-02-01", "Hög"])
        self.assertEqual(gone[:6], ["G9-9999", "", "", "", "", "Övriga"])  # no details: empty cells

    def test_each_download_is_audited_with_who_what_and_which_rabbits(self):
        rows = [_priority("G1-2111"), _priority("G1-2112", "important"), _priority("G2-2011", "normal")]
        self._login(self.manager)
        res = self._export(self.genebanks[0], rows, "?levels=critical,important&per_herd=1")
        self.assertEqual(res.status_code, 200)
        (row,) = self._audit()
        self.assertEqual(row.table_name, "individual")
        self.assertTrue(row.record_id.startswith("export-avelsprioritet-"))
        self.assertEqual(row.changed_by, self.manager.username or self.manager.email)
        self.assertEqual(
            row.new_data,
            {
                "action": "avelsprioritet",
                "genebank": self.genebanks[0].id,
                "levels": ["critical", "important"],
                "per_herd": True,
                "rows": 2,
                "numbers": ["G1-2111", "G1-2112"],
            },
        )

    def test_refused_without_an_audit_row(self):
        self._login(self.owner)
        self.assertEqual(self._export(self.genebanks[0], [_priority("G1-2111")]).status_code, 403)
        self.client.get("/api/logout")
        self._login(self.manager)
        self.assertEqual(self._export(self.genebanks[1], [_priority("M3-2111")]).status_code, 403)
        with patch.object(settings.service, "demo_instance", True):
            res = self._export(self.genebanks[0], [_priority("G1-2111")])
        self.assertEqual(res.status_code, 403)
        self.assertIn("där varje uttag loggas", res.get_json()["detail"])
        self.assertEqual(self._export(self.genebanks[0], [], "?levels=critical,kritisk").status_code, 400)
        self.assertEqual(self._audit(), [])

    def test_head_answers_without_a_row(self):
        self._login(self.manager)
        with patch.dict(APP.extensions, {"genetic_priorities": lambda g_id: [_priority("G1-2111")]}):
            res = self.client.head(EXPORT.format(self.genebanks[0].id))
        self.assertEqual(res.status_code, 405)
        self.assertEqual(res.headers["Allow"], "GET")
        self.assertEqual(self._audit(), [])

    def test_no_file_when_the_audit_row_fails(self):
        self._login(self.manager)
        with (
            patch("blueprints.genetics.log_export", side_effect=RuntimeError("audit down")),
            patch.dict(APP.config, {"PROPAGATE_EXCEPTIONS": False}),
        ):
            res = self._export(self.genebanks[0], [_priority("G1-2111")])
        self.assertEqual(res.status_code, 500)
        self.assertNotIn("Individnummer", res.get_data(as_text=True))
        self.assertNotIn("G1-2111", res.get_data(as_text=True))

    def test_reads_the_priorities_herdbook_hands_over(self):
        # Unpatched: without APP.extensions["genetic_priorities"] in herdbook.py this answers 500.
        ps.reset_for_tests()
        self.addCleanup(ps.reset_for_tests)
        self._login(self.manager)
        res = self.client.get(EXPORT.format(self.genebanks[0].id))
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_data(as_text=True).startswith('\ufeff"Individnummer";'))

    def test_an_export_row_cannot_be_reverted_and_answers_404(self):
        self._login(self.manager)
        self.assertEqual(self._export(self.genebanks[0], [_priority("G1-2111")]).status_code, 200)
        (row,) = self._audit()
        self.assertEqual(self.client.post(f"/api/audit-log/{row.id}/revert", json={}).status_code, 404)


class TestWorkListOrder(unittest.TestCase):
    def test_per_herd_keeps_the_levels_and_puts_g9_before_g10(self):
        rows = [
            {"individual_id": "a", "priority": "important", "herd": "G9"},
            {"individual_id": "b", "priority": "critical", "herd": "G10"},
            {"individual_id": "c", "priority": "critical", "herd": "G9"},
            {"individual_id": "d", "priority": "critical"},
        ]
        picked = work_list.select(rows, ["critical", "important"], per_herd=True)
        self.assertEqual([r["individual_id"] for r in picked], ["d", "c", "b", "a"])
        self.assertEqual([r["individual_id"] for r in work_list.select(rows, ["critical"], False)], ["b", "c", "d"])

    def test_ties_round_up_as_on_the_page(self):
        csv_text = work_list.priorities_csv(
            [
                {
                    **_priority("G1-1", reasons=["Genome uniqueness 0.1225 is above 75th percentile (0.0125)"]),
                    "genetic_value_score": 12.5,
                    "genome_uniqueness": 0.1225,
                }
            ]
        )
        row = list(csv.reader(csv_text[1:].splitlines(), delimiter=";"))[1]
        self.assertEqual(row[6:8], ["13", "12,3"])
        self.assertEqual(
            row[8],
            "Unika gener 12,3\u00a0%, över gränsen för de 25\u00a0% med flest unika gener (1,3\u00a0%)",
        )

    def test_reasons_read_as_on_the_page(self):
        self.assertEqual(
            work_list.swedish_reason("Mean kinship 0.0023 is below 5th percentile (0.0023)", "G1-1"),
            "Medelsläktskap 0,23\u00a0%, på eller under gränsen för de 5\u00a0% minst släkta (0,23\u00a0%)",
        )
        self.assertEqual(
            work_list.swedish_reason("Sole active carrier of founder G1-1", "G1-1"),
            "Är själv founderdjur och har inga ättlingar i beräkningen",
        )
