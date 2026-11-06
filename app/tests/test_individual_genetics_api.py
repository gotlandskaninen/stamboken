"""GET /api/v2/individual/<number>/genetics.

isort:skip_file
"""

import os
import threading
from datetime import date, timedelta
from itertools import count
from unittest.mock import patch

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import blueprints.individuals as individuals_module  # noqa: E402
import numpy as np  # noqa: E402
import utils.database as db  # noqa: E402
import utils.genetics_service as gs  # noqa: E402
from herdbook import APP, limiter  # noqa: E402
from utils.pedigree_math import BANDS, band_for  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402
from tests.ht_helpers import ht_row, make_individual  # noqa: E402

limiter.enabled = False

KEYS = {
    "inbreeding",
    "mean_kinship",
    "band",
    "band_reason",
    "in_reference",
    "alive",
    "pedigree_completeness",
    "reference_size",
    "definition_version",
    "preliminary",
    "stale",
}
ATTESTED = date(2025, 12, 31)  # inside the 2025 round that closed 2026-03-30


def _url(number):
    return f"/api/v2/individual/{number}/genetics"


class GeneticsApiFixture(DatabaseTest):
    """Six generations, four animals per generation 0–4: generation 5 knows all 62 ancestors (completeness 1.0).

    Members: twelve generation-5 animals. Also in generation 5: an unattested
    living animal (T14-NON), a dead one (T14-DEAD) and one sold to GX1 (T14-OUT).
    A generation-4 animal (T14-4-0) knows 30 of 62 ancestors.
    """

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        db.YearlyReportRound.create(
            report_year=2025, start_date=date(2025, 1, 1), end_date=date(2026, 3, 30), created_by=self.admin
        )
        self.gb = db.Genebank.create(name="T14bank")
        self.herd = db.Herd.create(genebank=self.gb, herd="T14", herd_name="T14", is_active=True)
        self.gx1 = db.Herd.create(genebank=self.gb, herd="GX1", herd_name="Utanför", is_active=True)
        self._day = count()
        prev = [self._ind(f"T14-0-{i}", sex="male" if i < 2 else "female") for i in range(4)]
        for g in range(1, 5):
            prev = [self._child(f"T14-{g}-{i}", prev, i, "male" if i < 2 else "female") for i in range(4)]
        self.members = [self._child(f"T14-5-{i}", prev, i, "female") for i in range(12)]
        for ind in self.members:
            ht_row("ATTESTATION", individual=ind, herd=self.herd, herd_tracking_date=ATTESTED)
        self._child("T14-NON", prev, 0, "female")
        dead = self._child("T14-DEAD", prev, 1, "female", death_date=date(2026, 2, 1))
        ht_row("ATTESTATION", individual=dead, herd=self.herd, herd_tracking_date=ATTESTED)
        out = self._child("T14-OUT", prev, 2, "female")
        ht_row("ATTESTATION", individual=out, herd=self.herd, herd_tracking_date=ATTESTED)
        ht_row("TRANSFER", individual=out, from_herd=self.herd, herd=self.gx1, herd_tracking_date=date(2026, 1, 15))

    def _ind(self, number, herd=None, **kw):
        return db.Individual.create(origin_herd=herd or self.herd, number=number, certificate=f"C{number}", **kw)

    def _child(self, number, parents, i, sex, **kw):
        breeding = db.Breeding.create(
            breeding_herd_id=self.herd,
            father=parents[i % 2],
            mother=parents[2 + (i // 2) % 2],
            birth_date=date(2020, 1, 1) + timedelta(days=next(self._day)),
        )
        return self._ind(number, breeding=breeding, sex=sex, **kw)

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post("/api/login", json={"username": username, "password": password})

    def _get(self, number):
        response = self.client.get(_url(number))
        return response, response.get_json()

    def _snap(self, gb=None):
        snap = gs.snapshot((gb or self.gb).id)
        self.assertIsNotNone(snap)
        return snap


class TestIndividualGeneticsAccess(GeneticsApiFixture):
    def test_unknown_and_inaccessible_give_the_same_404(self):
        self._login("spec")  # viewer of genebanks[0] only
        hidden, hidden_body = self._get("T14-5-0")
        self._login()
        unknown, unknown_body = self._get("T14-NOPE")
        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(hidden.content_type, "application/problem+json")
        self.assertEqual(
            {**hidden_body, "detail": hidden_body["detail"].replace("T14-5-0", "<n>")},
            {**unknown_body, "detail": unknown_body["detail"].replace("T14-NOPE", "<n>")},
        )

    def test_requires_login(self):
        self.assertEqual(self.client.get(_url("T14-5-0")).status_code, 401)


class TestIndividualGeneticsValues(GeneticsApiFixture):
    def setUp(self):
        super().setUp()
        self._login()

    def test_living_member_gets_a_band(self):
        response, data = self._get("T14-5-0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data), KEYS)
        snap = self._snap()
        i = snap.index["T14-5-0"]
        self.assertTrue(np.isfinite(data["inbreeding"]))
        np.testing.assert_allclose(data["inbreeding"], snap.F[i], rtol=0, atol=1e-12)
        np.testing.assert_allclose(data["mean_kinship"], snap.mk[i], rtol=0, atol=1e-12)
        self.assertIn(data["band"], BANDS)
        self.assertEqual(data["band"], band_for(data["mean_kinship"], snap.band_cuts))
        self.assertIsNone(data["band_reason"])
        self.assertTrue(data["in_reference"])
        self.assertTrue(data["alive"])
        self.assertEqual(data["pedigree_completeness"], 1.0)
        self.assertEqual(data["reference_size"], 12)
        self.assertEqual(data["definition_version"], 2)
        self.assertTrue(data["preliminary"])
        self.assertFalse(data["stale"])

    def test_living_non_member_is_compared_as_if_member(self):
        rows = gs.fetch_pedigree_rows(self.gb.id)
        members = gs.reference_population_numbers(self.gb.id)
        self.assertNotIn("T14-NON", members)
        as_if = gs.ps.build_snapshot(self.gb.id, rows, members | {"T14-NON"}, key=("as-if",), seq=0)
        expected = float(as_if.mk[as_if.index["T14-NON"]])
        response, data = self._get("T14-NON")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(np.isfinite(data["mean_kinship"]))
        np.testing.assert_allclose(data["mean_kinship"], expected, rtol=0, atol=1e-12)
        self.assertFalse(data["in_reference"])
        self.assertIn(data["band"], BANDS)
        self.assertIsNone(data["band_reason"])

    def test_dead_animal_has_no_mean_kinship_or_band(self):
        response, data = self._get("T14-DEAD")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data["alive"])
        self.assertIsNone(data["mean_kinship"])
        self.assertIsNone(data["band"])
        self.assertEqual(data["band_reason"], "dead")
        self.assertTrue(np.isfinite(data["inbreeding"]))

    def test_outside_genebank(self):
        response, data = self._get("T14-OUT")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(data["band"])
        self.assertEqual(data["band_reason"], "outside_genebank")
        self.assertFalse(data["in_reference"])

    def test_incomplete_pedigree(self):
        response, data = self._get("T14-4-0")
        self.assertEqual(response.status_code, 200)
        np.testing.assert_allclose(data["pedigree_completeness"], 30 / 62, rtol=0, atol=1e-12)
        self.assertIsNone(data["band"])
        self.assertEqual(data["band_reason"], "incomplete_pedigree")
        self.assertIsNotNone(data["mean_kinship"])

    def test_small_reference_keeps_mean_kinship(self):
        gb = db.Genebank.create(name="Smal")
        herd = db.Herd.create(genebank=gb, herd="SM1", herd_name="Smal", is_active=True)
        for i in range(3):
            ind = make_individual(herd, f"SM1-{i}", date(2024, 5, 1 + i), sex="male" if i else "female")
            ht_row("ATTESTATION", individual=ind, herd=herd, herd_tracking_date=ATTESTED)
        response, data = self._get("SM1-0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["reference_size"], 3)
        self.assertTrue(data["in_reference"])
        snap = self._snap(gb)
        np.testing.assert_allclose(data["mean_kinship"], snap.mk[snap.index["SM1-0"]], rtol=0, atol=1e-12)
        self.assertIsNone(data["band"])
        self.assertEqual(data["band_reason"], "small_reference")

    def test_no_members_gives_null_mean_kinship(self):
        gb = db.Genebank.create(name="Tom")
        herd = db.Herd.create(genebank=gb, herd="NM1", herd_name="Tom", is_active=True)
        make_individual(herd, "NM1-0", date(2024, 5, 1))
        response, data = self._get("NM1-0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["reference_size"], 0)
        self.assertIsNone(data["mean_kinship"])
        self.assertIsNone(data["band"])
        self.assertEqual(data["band_reason"], "small_reference")

    def test_stale_while_a_rebuild_is_pending(self):
        snap = self._snap()
        with patch.object(gs, "snapshot_status", return_value=(snap, True)):
            response, data = self._get("T14-5-0")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["stale"])
        self.assertIn(data["band"], BANDS)

    def test_no_snapshot_gives_503(self):
        with patch.object(gs, "snapshot_status", return_value=(None, False)):
            response, data = self._get("T14-5-0")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content_type, "application/problem+json")
        self.assertEqual(data["status"], 503)
        self.assertEqual(response.headers.get("Retry-After"), "5")

    def test_snapshot_read_error_gives_503(self):
        with patch.object(gs, "snapshot_status", side_effect=RuntimeError("key read failed")):
            response, data = self._get("T14-5-0")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content_type, "application/problem+json")
        self.assertEqual(data["status"], 503)
        self.assertEqual(response.headers.get("Retry-After"), "5")

    def test_fresh_snapshot_without_the_animal_gives_503_not_404(self):
        """An accessible animal never gets 404, even if a fresh snapshot lacks it."""
        empty = gs.ps.build_snapshot(self.gb.id, [], set(), key=("empty",), seq=0)
        with patch.object(gs, "snapshot_status", return_value=(empty, False)):
            response, data = self._get("T14-5-0")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content_type, "application/problem+json")
        self.assertEqual(response.headers.get("Retry-After"), "5")

    def test_fresh_snapshot_without_the_animal_warns_once_per_animal(self):
        empty = gs.ps.build_snapshot(self.gb.id, [], set(), key=("empty",), seq=0)
        with (
            patch.object(gs, "snapshot_status", return_value=(empty, False)),
            patch.object(individuals_module, "_warned_missing", set()),
            self.assertLogs(individuals_module.logger, "DEBUG") as logs,
        ):
            self._get("T14-5-0")
            self._get("T14-5-0")
        self.assertEqual([r.levelname for r in logs.records], ["WARNING", "DEBUG"])

    def test_current_herd_in_another_genebank_uses_the_origin_genebank(self):
        """Snapshots hold animals by origin genebank; the current herd's genebank must not be used."""
        other = db.Genebank.create(name="Annan")
        other_herd = db.Herd.create(genebank=other, herd="AN1", herd_name="Annan", is_active=True)
        moved = db.Individual.get(db.Individual.number == "T14-5-1")
        ht_row("TRANSFER", individual=moved, from_herd=self.herd, herd=other_herd, herd_tracking_date=date(2026, 1, 15))
        response, data = self._get("T14-5-1")
        self.assertEqual(response.status_code, 200)
        snap = self._snap()
        i = snap.index["T14-5-1"]
        np.testing.assert_allclose(data["inbreeding"], snap.F[i], rtol=0, atol=1e-12)
        np.testing.assert_allclose(data["mean_kinship"], snap.mk[i], rtol=0, atol=1e-12)
        self.assertEqual(data["in_reference"], bool(snap.ref_mask[i]))
        self.assertEqual(data["reference_size"], snap.n_ref)


class TestIndividualGeneticsRenumber(GeneticsApiFixture):
    """A renumbered animal waits for the snapshot that knows its new number."""

    def setUp(self):
        super().setUp()
        self._login()
        _, before = self._get("T14-5-0")  # cold build of the old snapshot
        self.before = before
        self.gate = threading.Event()
        build = gs.ps._build

        def gated(genebank_id):
            self.gate.wait(30)
            return build(genebank_id)

        patcher = patch.object(gs.ps, "_build", gated)
        patcher.start()
        # Cleanups run last-in first-out: open the gate, drain the build, then unpatch.
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: gs.ps.wait_for_builds(self.gb.id, timeout=30))
        self.addCleanup(self.gate.set)
        db.Individual.update(number="T14-5-0R").where(db.Individual.number == "T14-5-0").execute()

    def test_new_number_waits_for_the_rebuild(self):
        timer = threading.Timer(0.2, self.gate.set)
        timer.start()
        try:
            response, data = self._get("T14-5-0R")
        finally:
            timer.cancel()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data["stale"])
        np.testing.assert_allclose(data["inbreeding"], self.before["inbreeding"], rtol=0, atol=1e-12)
        np.testing.assert_allclose(data["mean_kinship"], self.before["mean_kinship"], rtol=0, atol=1e-12)
        self.assertEqual(data["band"], self.before["band"])
        self.assertTrue(data["in_reference"])
        old, _ = self._get("T14-5-0")
        self.assertEqual(old.status_code, 404)

    def test_rebuild_too_slow_gives_503_with_retry_after(self):
        with patch.object(gs, "REFRESH_WAIT_SECONDS", 0.5):
            response, data = self._get("T14-5-0R")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content_type, "application/problem+json")
        self.assertEqual(data["status"], 503)
        self.assertTrue(response.headers.get("Retry-After"))
