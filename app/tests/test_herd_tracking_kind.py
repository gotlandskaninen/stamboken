"""Central writer caller table: every existing writer states its kind.

isort:skip_file
"""

import os
from datetime import date, datetime, timedelta

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from cli import seed  # noqa: E402
from herdbook import APP, limiter  # noqa: E402
from utils.herd_tracking import legacy_ht_kind  # noqa: E402
from utils.individual_number_v2 import _create_individual_record  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402

limiter.enabled = False


def _rows(individual):
    return list(
        db.HerdTracking.select()
        .where(db.HerdTracking.individual == individual)
        .order_by(db.HerdTracking.herd_tracking_date, db.HerdTracking.id)
    )


class TestWriterKinds(DatabaseTest):
    def test_legacy_kind_rule(self):
        self.assertEqual(legacy_ht_kind("G1", "G1"), "ATTESTATION")
        self.assertEqual(legacy_ht_kind("G1", "G2"), "TRANSFER")

    def test_add_individual_birth_and_direct_move(self):
        birth = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        sold = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        form = {
            "herd": self.herds[1].herd,
            "origin_herd": {"herd": self.herds[0].herd},
            "number": "G1-1999",
            "breeding": self.breeding[0].id,
            "birth_date": birth,
            "selling_date": sold,
        }
        result = da.add_individual(form, self.admin.uuid)
        self.assertEqual(result["status"], "success", result)
        rows = _rows(db.Individual.get(db.Individual.number == "G1-1999"))
        self.assertEqual([(r.kind, r.herd.herd) for r in rows], [("BIRTH", "G1"), ("TRANSFER", "G2")])
        self.assertTrue(all(r.operation_id is not None and r.created_at is not None for r in rows))

    def _legacy_update(self, extra):
        ind = self.individuals[0]
        form = {"id": ind.id, "number": ind.number, **extra}
        return da.update_individual(form, self.manager.uuid)

    def test_update_individual_yearly_report_same_herd_is_attestation(self):
        result = self._legacy_update({"herd": "G1", "yearly_report_date": "2022-01-15"})
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(_rows(self.individuals[0])[-1].kind, "ATTESTATION")

    def test_update_individual_sale_is_transfer(self):
        result = self._legacy_update({"herd": "G2", "selling_date": "2022-01-15"})
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(_rows(self.individuals[0])[-1].kind, "TRANSFER")

    def test_update_individual_sale_to_current_herd_is_attestation(self):
        """Spec-silent legacy case: legacy wrote a same-herd row; it stays a row, as an ATTESTATION."""
        result = self._legacy_update({"herd": "G1", "selling_date": "2022-01-15"})
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(_rows(self.individuals[0])[-1].kind, "ATTESTATION")

    def test_update_individual_yearly_report_to_other_herd_is_transfer(self):
        result = self._legacy_update({"herd": "G2", "yearly_report_date": "2022-01-15"})
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(_rows(self.individuals[0])[-1].kind, "TRANSFER")

    def test_v2_import_with_provided_number_is_birth(self):
        client = APP.test_client(use_cookies=True)
        client.post("/api/login", json={"username": self.admin.email, "password": "pass"})
        response = client.post(
            "/api/v2/individual/import",
            json={"herd": "G1", "birth_date": "2025-05-10", "number": "G1-2511", "sex": "male"},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        rows = _rows(db.Individual.get(db.Individual.number == "G1-2511"))
        self.assertEqual([r.kind for r in rows], ["BIRTH"])

    def test_v2_birth_record_is_birth(self):
        breeding = db.Breeding.create(birth_date=date(2024, 3, 1), breeding_herd_id=self.herds[0], litter_number=1)
        locked = db.Breeding.select().where(db.Breeding.id == breeding.id).get()
        individual = _create_individual_record(self.herds[0], locked, signature=self.manager)
        self.assertEqual([r.kind for r in _rows(individual)], ["BIRTH"])

    def test_seed_track_states_kind_and_is_idempotent_per_kind(self):
        logs = []
        seed._track(
            self.individuals[0], self.herds[0], None, self.manager, date(2023, 1, 1), "ATTESTATION", logs.append
        )
        seed._track(
            self.individuals[0], self.herds[0], None, self.manager, date(2023, 1, 1), "ATTESTATION", logs.append
        )
        same_day = [r for r in _rows(self.individuals[0]) if r.herd_tracking_date == date(2023, 1, 1)]
        self.assertEqual([r.kind for r in same_day], ["ATTESTATION"])
