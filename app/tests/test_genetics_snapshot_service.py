"""The service returns the same numbers from the snapshot as the old dense path."""

import threading
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import herdbook
import numpy as np
import utils.database as db
import utils.genetics_service as gs
from herdbook import APP, limiter
from utils.genetics import (
    Individual,
    calculate_generation_numbers,
    calculate_inbreeding_henderson,
    calculate_kinship_matrix,
)

from tests.database_test import DatabaseTest
from tests.ht_helpers import ht_row


def _finishes(fn, timeout=60):
    done = []
    t = threading.Thread(target=lambda: done.append(fn()), daemon=True)
    t.start()
    t.join(timeout)
    return bool(done)


class SnapshotFixture(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.gb = db.Genebank.create(name="Snapgenbank")
        self.herd = db.Herd.create(genebank=self.gb, herd="SN1", herd_name="Snap", is_active=True)
        db.YearlyReportRound.create(
            report_year=2025, start_date=date(2025, 1, 1), end_date=date(2026, 3, 30), created_by=self.admin
        )
        founders = [self._ind(f"SN1-F{i}", sex="male" if i % 2 == 0 else "female") for i in range(6)]
        kids = []
        for i in range(10):
            # Distinct birth dates: (mother, father, birth_date) is unique on Breeding.
            b = db.Breeding.create(
                breeding_herd_id=self.herd,
                father=founders[(i * 2) % 6],
                mother=founders[(i * 2 + 1) % 6],
                birth_date=date(2024, 5, 1) + timedelta(days=i),
            )
            kids.append(self._ind(f"SN1-K{i}", breeding=b, sex="male" if i % 2 == 0 else "female"))
        for ind in founders[:2] + kids:
            ht_row("ATTESTATION", individual=ind, herd=self.herd, herd_tracking_date=date(2025, 12, 31))
        gs.invalidate_cache()

    def _ind(self, number, **kw):
        return db.Individual.create(origin_herd=self.herd, number=number, certificate=f"C{number}", **kw)

    def _old(self):
        rows = gs.fetch_pedigree_rows(self.gb.id)
        members = gs.reference_population_numbers(self.gb.id)
        return [
            Individual(
                id=r["number"],
                sire_id=r["father_number"],
                dam_id=r["mother_number"],
                is_active=r["number"] in members,
                sex=r["sex"],
            )
            for r in rows
        ]


class TestSnapshotService(SnapshotFixture):
    def test_inbreeding_mean_kinship_and_matrix(self):
        old = self._old()
        F_old = calculate_inbreeding_henderson(old)
        K_old, ids_old = calculate_kinship_matrix(old, active_only=True)
        self.assertGreater(len(ids_old), 2)
        F_new = gs.get_inbreeding(self.gb.id)
        self.assertEqual(set(F_new), set(F_old))
        for k, v in F_new.items():
            self.assertAlmostEqual(v, F_old[k], places=12)
        mk = gs.get_mean_kinship(self.gb.id)
        self.assertEqual(set(mk), set(ids_old))
        for i, x in enumerate(ids_old):
            self.assertAlmostEqual(mk[x], float(np.mean(K_old[:, i])), places=12)
        km = gs.get_kinship_matrix(self.gb.id)
        for i, a in enumerate(ids_old):
            for j, b in enumerate(ids_old):
                self.assertAlmostEqual(km[a][b], float(K_old[i, j]), places=12)

    def test_generation_numbers_and_metrics(self):
        old = self._old()
        self.assertEqual(gs.get_generation_numbers(self.gb.id), calculate_generation_numbers(old))
        metrics = gs.get_population_metrics(self.gb.id)
        self.assertEqual(metrics["n_active"], sum(1 for i in old if i.is_active))
        self.assertIsNotNone(metrics["expected_offspring_f"])

    def test_testbreed_full_sibs(self):
        """K0 and K3 share both parents: offspring F = kinship = 0.25."""
        old = self._old()
        K_old, ids_old = calculate_kinship_matrix(old, active_only=False)
        expected = float(K_old[ids_old.index("SN1-K0"), ids_old.index("SN1-K3")])
        self.assertAlmostEqual(expected, 0.25, places=12)
        self.assertAlmostEqual(gs.calculate_testbreed(self.gb.id, "SN1-K0", "SN1-K3"), expected, places=12)

    def test_all_dashboard_consumers_finish(self):
        """Nested memo use must not deadlock."""
        gb = self.gb.id
        self.assertTrue(_finishes(lambda: gs.get_founder_statistics(gb)))
        self.assertTrue(_finishes(lambda: gs.get_breeding_suggestions(gb)))
        self.assertTrue(_finishes(lambda: gs.get_founders_at_risk(gb)))
        self.assertTrue(_finishes(lambda: gs.get_genetic_priorities(gb, n_iterations=50)))

    def test_empty_genebank_keeps_existing_shapes(self):
        empty = db.Genebank.create(name="Tom")
        self.assertEqual(gs.get_mean_kinship(empty.id), {})
        self.assertEqual(gs.get_kinship_matrix(empty.id), {})
        self.assertEqual(gs.get_population_metrics(empty.id)["n_active"], 0)

    def test_key_follows_the_version(self):
        snap = gs.snapshot(self.gb.id)
        self.assertEqual(snap.key[0], db.read_genetics_version())
        kid = db.Individual.get(db.Individual.number == "SN1-K0")
        kid.castration_date = date(2026, 1, 1)
        kid.save()
        gs.snapshot(self.gb.id)
        gs.ps.wait_for_builds(self.gb.id, timeout=5)
        self.assertEqual(gs.snapshot(self.gb.id).key[0], db.read_genetics_version())
        self.assertNotIn("SN1-K0", gs.get_mean_kinship(self.gb.id))

    def test_future_dated_life_sign_counts_the_next_day_without_writes(self):
        today = date.today()
        late = self._ind("SN1-LATE", sex="female")
        ht_row("ATTESTATION", individual=late, herd=self.herd, herd_tracking_date=today + timedelta(days=1))
        self.assertNotIn("SN1-LATE", gs.get_mean_kinship(self.gb.id))
        version = db.read_genetics_version()

        class Later(date):
            @classmethod
            def today(cls):
                return today + timedelta(days=2)

        with patch("utils.genetics_service.date", Later):
            gs.snapshot(self.gb.id)
            gs.ps.wait_for_builds(self.gb.id, timeout=5)
            self.assertIn("SN1-LATE", gs.get_mean_kinship(self.gb.id))
        self.assertEqual(db.read_genetics_version(), version)

    def test_recoverable_carriers_come_from_the_snapshot_read(self):
        """Carrier eligibility is read with the pedigree, not live afterwards."""
        lost_m = self._ind("SN1-LM", sex="male")  # founders outside the reference population
        lost_f = self._ind("SN1-LF", sex="female")
        b = db.Breeding.create(
            breeding_herd_id=self.herd, father=lost_m, mother=lost_f, birth_date=date.today() - timedelta(days=60)
        )
        carrier = self._ind("SN1-REC", breeding=b, sex="female")  # alive, certified, no tracking: not a member
        snap = gs.snapshot(self.gb.id)
        carrier.death_date = date.today()
        carrier.save()
        with gs.ps.pinned(snap):
            at_risk = {f["founder_id"]: f for f in gs.get_founders_at_risk(self.gb.id)}
        self.assertEqual(at_risk["SN1-LM"]["risk_level"], "lost")
        self.assertEqual(at_risk["SN1-LM"]["recoverable_carriers"], ["SN1-REC"])
        self.assertEqual(at_risk["SN1-LF"]["recoverable_carriers"], ["SN1-REC"])

    def _isolation_seen_by_the_load(self):
        seen = []
        real = gs.fetch_pedigree_rows

        def spy(genebank_id):
            cursor = db.DB_PROXY.execute_sql("SHOW transaction_isolation")
            isolation = cursor.fetchone()[0]
            read_only = db.DB_PROXY.execute_sql("SHOW transaction_read_only").fetchone()[0]
            seen.append((isolation, read_only, threading.current_thread().name.startswith("pedigree-build")))
            return real(genebank_id)

        return seen, spy

    def test_load_reads_one_repeatable_read_snapshot(self):
        seen, spy = self._isolation_seen_by_the_load()
        with patch.object(gs, "fetch_pedigree_rows", spy):
            snap = gs.snapshot(self.gb.id)
        self.assertEqual(seen, [("repeatable read", "on", True)])
        version, epoch = db.read_genetics_key()
        self.assertEqual(
            snap.key, (version, date.today(), gs.REFERENCE_DEFINITION_VERSION, gs.ALGORITHM_VERSION, epoch)
        )

    def test_load_inside_a_transaction_reads_committed_state_on_the_build_thread(self):
        seen, spy = self._isolation_seen_by_the_load()
        committed = db.read_genetics_version()
        with patch.object(gs, "fetch_pedigree_rows", spy), db.DB_PROXY.atomic() as txn:
            kid = db.Individual.get(db.Individual.number == "SN1-K1")
            kid.castration_date = date(2026, 1, 1)
            kid.save()
            snap = gs.snapshot(self.gb.id)
            txn.rollback()
        self.assertEqual(seen, [("repeatable read", "on", True)])
        self.assertEqual(snap.key[0], committed)
        self.assertIn("SN1-K1", snap.ref_ids)


class TestTestbreedRoute(SnapshotFixture):
    """POST /api/testbreed for registered animals goes through the snapshot (ADR-0006: shape unchanged)."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.client.post("/api/login", json={"username": "admin", "password": "pass"})

    def _post(self, male, female):
        return self.client.post("/api/testbreed", json={"genebankId": self.gb.id, "male": male, "female": female})

    def test_registered_pair_matches_calculate_testbreed(self):
        for male, female in [("SN1-K0", "SN1-K3"), ("SN1-K0", "SN1-K1"), ("SN1-K2", "SN1-K5")]:
            response = self._post(male, female)
            self.assertEqual(response.status_code, 200)
            expected = round(gs.calculate_testbreed(self.gb.id, male, female) * 100, 2)
            self.assertEqual(response.get_json(), {"offspringCOI": expected})
        self.assertEqual(self._post("SN1-K0", "SN1-K3").get_json(), {"offspringCOI": 25.0})

    def test_number_missing_from_a_fresh_snapshot_is_unrelated(self):
        """Not in this genebank's pedigree (fresh snapshot): no wait, legacy keeps answering 0."""
        gs.snapshot(self.gb.id)
        response = self._post("SN1-NOPE", "SN1-K3")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json(), {"offspringCOI": 0.0})


class TestTestbreedWaitsForMissingNumbers(SnapshotFixture):
    """A supplied number missing from a STALE snapshot waits for the rebuild, never answers 0.

    K0 (male), K3 and K9 (females) are children of F0 x F1: K0 x K3 are full siblings (F 25 %).
    K3 and the grandparent F0 are renumbered while the rebuild is held at a gate.
    """

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        limiter_off = patch.object(limiter, "enabled", False)  # many logins in a row
        limiter_off.start()
        self.addCleanup(limiter_off.stop)
        self.client.post("/api/login", json={"username": "admin", "password": "pass"})
        gs.snapshot(self.gb.id)  # cold build: the snapshot that knows the old numbers
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
        db.Individual.update(number="SN1-K3R").where(db.Individual.number == "SN1-K3").execute()
        db.Individual.update(number="SN1-F0R").where(db.Individual.number == "SN1-F0").execute()

    def _release_soon(self):
        timer = threading.Timer(0.2, self.gate.set)
        timer.start()
        self.addCleanup(timer.cancel)

    def _v2(self, female, male):
        return self.client.post(
            "/api/v2/testbreed", json={"genebank_id": self.gb.id, "female": female, "males": [male]}
        )

    def _legacy(self, **payload):
        return self.client.post("/api/testbreed", json={"genebankId": self.gb.id, **payload})

    def test_v2_renumbered_partner_waits_for_the_rebuild(self):
        self._release_soon()
        response = self._v2("SN1-K3R", {"number": "SN1-K0"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        result = response.get_json()["results"][0]
        self.assertEqual(result["offspring_f"], 25.0)
        self.assertEqual(result["verdict"], "high")

    def test_v2_renumbered_grandparent_of_a_virtual_male_waits_for_the_rebuild(self):
        self._release_soon()
        response = self._v2("SN1-K9", {"number": None, "parents": {"father": "SN1-F0R", "mother": "SN1-F1"}})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["results"][0]["offspring_f"], 25.0)

    def test_v2_rebuild_too_slow_gives_503_with_retry_after(self):
        with patch.object(gs, "REFRESH_WAIT_SECONDS", 0.5):
            response = self._v2("SN1-K3R", {"number": "SN1-K0"})
        self.assertEqual(response.status_code, 503, response.get_data(as_text=True))
        self.assertEqual(response.content_type, "application/problem+json")
        self.assertEqual(response.get_json()["status"], 503)
        self.assertEqual(response.headers.get("Retry-After"), "5")

    def test_legacy_renumbered_partner_waits_for_the_rebuild(self):
        self._release_soon()
        response = self._legacy(male="SN1-K0", female="SN1-K3R")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json(), {"offspringCOI": 25.0})

    def test_legacy_rebuild_too_slow_answers_its_error_path(self):
        with patch.object(gs, "REFRESH_WAIT_SECONDS", 0.5):
            response = self._legacy(male="SN1-K0", female="SN1-K3R")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {"error": "Error processing your request"})


class TestTestbreedAfterAFailedColdBuild(SnapshotFixture):
    """With no snapshot at all, test mating fails like a not-ready one instead of answering 0 %."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        limiter_off = patch.object(limiter, "enabled", False)
        limiter_off.start()
        self.addCleanup(limiter_off.stop)
        self.client.post("/api/login", json={"username": "admin", "password": "pass"})
        gs.ps.reset_for_tests()  # no snapshot yet: the next read is a cold build

    def test_failed_cold_build_is_not_answered_as_zero(self):
        # K0 (male) and K3 (female) are full siblings: offspring F is 25 %.
        with patch.object(gs.ps, "_load_fn", side_effect=RuntimeError("db")):
            v2 = self.client.post(
                "/api/v2/testbreed",
                json={"genebank_id": self.gb.id, "female": "SN1-K3", "males": [{"number": "SN1-K0"}]},
            )
            legacy = self.client.post(
                "/api/testbreed", json={"genebankId": self.gb.id, "male": "SN1-K0", "female": "SN1-K3"}
            )
        body = v2.get_json() or {}
        result = (body.get("results") or [{}])[0]
        self.assertEqual(
            v2.status_code,
            503,
            f"v2 full-sib mating: {v2.status_code} offspring_f={result.get('offspring_f')} "
            f"verdict={result.get('verdict')}",
        )
        self.assertEqual(v2.headers.get("Retry-After"), "5")
        # Legacy keeps its own error path (ADR-0006): 500 with the existing body.
        self.assertEqual(
            (legacy.status_code, legacy.get_json()),
            (500, {"error": "Error processing your request"}),
            f"legacy full-sib mating: {legacy.get_json()}",
        )


def test_snapshot_with_keeps_waiting_when_the_running_build_predates_the_write():
    """The build already running when the request arrives can lack the number; wait for the next one."""
    older = SimpleNamespace(index={"A": 0})
    running = SimpleNamespace(index={"A": 0})
    current = SimpleNamespace(index={"A": 0, "B": 1})
    statuses = iter([(older, True), (running, True), (current, False)])
    with (
        patch.object(gs, "snapshot_status", lambda _gb: next(statuses)),
        patch.object(gs.ps, "wait_for_builds", lambda _gb, timeout: True),
    ):
        assert gs.snapshot_with(1, ["A", "B"]) is current


class TestLegacyIndividualOneSnapshot(SnapshotFixture):
    """GET /api/individual/<n> reads F and MK from one snapshot."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.client.post("/api/login", json={"username": "admin", "password": "pass"})

    def _unrelate_k0(self):
        """Give SN1-K0 two new, unrelated founder parents (its MK drops) and publish that snapshot."""
        father = self._ind("SN1-NA", sex="male")
        mother = self._ind("SN1-NB", sex="female")
        kid = db.Individual.get(db.Individual.number == "SN1-K0")
        kid.breeding = db.Breeding.create(
            breeding_herd_id=self.herd, father=father, mother=mother, birth_date=date(2024, 6, 1)
        )
        kid.save()
        gs.ps.mark_stale(self.gb.id)
        gs.ps.wait_for_builds(self.gb.id, timeout=10)

    def test_inbreeding_and_mean_kinship_come_from_one_snapshot(self):
        before = gs.get_mean_kinship(self.gb.id)["SN1-K0"]
        real = herdbook.get_ind_inbreeding

        def publish_after_first_read(i_number, g_id):
            value = real(i_number, g_id)
            self._unrelate_k0()
            return value

        with patch.object(herdbook, "get_ind_inbreeding", publish_after_first_read):
            response = self.client.get("/api/individual/SN1-K0")
        self.assertEqual(response.status_code, 200)
        after = gs.get_mean_kinship(self.gb.id)["SN1-K0"]
        self.assertNotEqual("%.2f" % (before * 100), "%.2f" % (after * 100))  # the publication changed MK
        self.assertEqual(response.get_json()["MK"], "%.2f" % (before * 100))

    def test_values_come_from_the_origin_genebank_after_a_cross_genebank_transfer(self):
        """genebank_id is the current herd's, but snapshots hold animals by origin genebank."""
        other = db.Genebank.create(name="Annan")
        other_herd = db.Herd.create(genebank=other, herd="AN1", herd_name="Annan", is_active=True)
        # K0 x K3 are full siblings: their offspring has F = 25 %.
        inbred = db.Breeding.create(
            breeding_herd_id=self.herd,
            father=db.Individual.get(db.Individual.number == "SN1-K0"),
            mother=db.Individual.get(db.Individual.number == "SN1-K3"),
            birth_date=date(2025, 6, 1),
        )
        kid = self._ind("SN1-IN", breeding=inbred, sex="female")
        ht_row("TRANSFER", individual=kid, from_herd=self.herd, herd=other_herd, herd_tracking_date=date(2026, 1, 15))
        gs.invalidate_cache()

        expected_mk = gs.get_mean_kinship(self.gb.id)["SN1-IN"]
        self.assertGreater(expected_mk, 0, "precondition: SN1-IN has non-zero MK in its origin genebank")

        data = self.client.get("/api/individual/SN1-IN").get_json()
        self.assertEqual(data["genebank_id"], other.id, "precondition: current herd is in the other genebank")
        self.assertEqual(
            (data["inbreeding"], data["MK"]),
            ("25.00", "%.2f" % (expected_mk * 100)),
            f"legacy route shows F/MK {data['inbreeding']!r}/{data['MK']!r} (read from genebank "
            f"{data['genebank_id']}); origin genebank: 25.00/{expected_mk * 100:.2f}",
        )
