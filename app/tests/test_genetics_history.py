#!/usr/bin/env python3
"""
History reconcile ("Historiken" / "Avstämning").

One row per closed report year from the first year with at least
MIN_HISTORY_MEMBERS reference members, computed from one REPEATABLE READ read
and published as a whole; an older candidate never overwrites a newer one.

isort:skip_file
"""

import os
import threading
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import psycopg2
import pytest
import utils.database as db
import utils.genetics_service as gs
import utils.pedigree_snapshot as ps
import utils.reference_population as rp
from utils.genetics import calculate_average_founder_contributions, calculate_founder_equivalents

from tests.database_test import DatabaseTest
from tests.genetics_fixtures import rows_from_arrays, synthetic_pedigree
from tests.ht_helpers import ht_row

# No round exists unless a test creates one: year Y closes on 1 April Y+1.
TODAY = date(2024, 6, 1)
WAIT = 10  # seconds; a hang fails the test instead of the suite


def _connect():
    return psycopg2.connect(database=db.DATABASE.database, **db.DATABASE.connect_params)


class HistoryTest(DatabaseTest):
    """Genebank with 10 members in 2020 and 30 in each of 2021–2023."""

    def setUp(self):
        super().setUp()
        self.gb = db.Genebank.create(name="Historik-genbank")
        self.herd = db.Herd.create(genebank=self.gb, herd="H1", herd_name="Aktiv", is_active=True)
        self._n = 0
        with db.DATABASE.atomic():
            self.early = [self._animal(date(2020, 3, 1), range(2020, 2024)) for _ in range(10)]
            self.late = [self._animal(date(2021, 3, 1), range(2021, 2024)) for _ in range(20)]

    def _animal(self, birth, years, father=None, mother=None):
        """A certified animal born in the herd with a life sign on 1 June of each year; returns it."""
        self._n += 1
        number = f"H1-{self._n:03d}"
        breeding = db.Breeding.create(breeding_herd_id=self.herd, birth_date=birth, father=father, mother=mother)
        individual = db.Individual.create(
            origin_herd=self.herd, number=number, breeding=breeding, certificate=f"C-{number}", sex="female"
        )
        for i, year in enumerate(years):
            ht_row(
                "BIRTH" if i == 0 else "ATTESTATION",
                individual=individual,
                from_herd=self.herd,
                herd=self.herd,
                herd_tracking_date=date(year, 6, 1),
            )
        return individual

    def rows(self):
        return list(
            db.GeneticMetricsHistory.select()
            .where(db.GeneticMetricsHistory.genebank == self.gb.id)
            .order_by(db.GeneticMetricsHistory.report_year)
        )

    def years(self):
        return [r.report_year for r in self.rows()]

    def state(self):
        return db.GeneticsHistoryState.get_or_none(db.GeneticsHistoryState.genebank == self.gb.id)

    def _round(self, year, end_date):
        return db.YearlyReportRound.create(
            report_year=year, start_date=date(year, 12, 31), end_date=end_date, created_by=self.admin
        )


class TestReconcileHistory(HistoryTest):
    def test_one_row_per_closed_year_from_the_first_year_with_30_members(self):
        version = db.read_genetics_version()
        candidate = {r["report_year"]: r for r in gs.desired_history_rows(self.gb.id, TODAY)[1]}

        self.assertEqual(gs.reconcile_history(self.gb.id, today=TODAY), "replaced")

        rows = self.rows()
        # 2020 has 10 members (absent), 2024 is not closed on TODAY.
        self.assertEqual([r.report_year for r in rows], [2021, 2022, 2023])
        for r in rows:
            as_of = date(r.report_year + 1, 4, 1)
            self.assertEqual((r.as_of, r.snapshot_date), (as_of, as_of))
            self.assertEqual(r.definition_version, rp.CURRENT_DEFINITION.version)
            self.assertEqual(r.pedigree_version, version)
            self.assertEqual(r.active_count, 30)
            self.assertEqual(r.population_size, 30)
            # 30 unrelated founders: mean MK = 1/60 (self term), fge = 30, F = 0.
            expected = {"mean_kinship": 1 / 60, "fge": 30.0, "mean_inbreeding": 0.0, "founder_equivalents": 30.0}
            for name, value in expected.items():
                computed = candidate[r.report_year][name]
                self.assertTrue(np.isfinite(computed), name)
                np.testing.assert_allclose(computed, value, rtol=0, atol=1e-12, err_msg=name)
                # The columns are REAL (float4): stored = computed rounded to float32.
                self.assertEqual(np.float32(getattr(r, name)), np.float32(computed), name)
        self.assertEqual(self.state().version, version)

    def test_formula_fix_recomputes_stored_history_at_the_same_pedigree_version(self):
        """Rows a worker before the FE fix published at today's pedigree version are replaced on reconcile."""
        self.assertEqual(gs.reconcile_history(self.gb.id, today=TODAY), "replaced")
        correct = [r.founder_equivalents for r in self.rows()]
        state = self.state()
        # What the old code left behind: wrong FE, a watermark at this version and definition, no algorithm version.
        db.GeneticMetricsHistory.update(founder_equivalents=99.0).where(
            db.GeneticMetricsHistory.genebank == self.gb.id
        ).execute()
        db.GeneticsHistoryState.delete().where(db.GeneticsHistoryState.genebank == self.gb.id).execute()
        db.GeneticsHistoryState.create(
            genebank=self.gb.id,
            checked_at=state.checked_at,
            version=state.version,
            definition_version=state.definition_version,
        )
        self.assertEqual(db.read_genetics_version(), state.version)  # the pedigree did not change

        result = gs.reconcile_history(self.gb.id, today=TODAY)

        self.assertEqual([r.founder_equivalents for r in self.rows()], correct, f"stale FE kept ({result})")
        self.assertEqual(result, "replaced")

    def test_unchanged_run_moves_checked_at_only(self):
        gs.reconcile_history(self.gb.id, today=TODAY)
        before_ids = [r.id for r in self.rows()]
        backdated = datetime.now(timezone.utc) - timedelta(days=1)
        db.GeneticsHistoryState.update(checked_at=backdated).where(
            db.GeneticsHistoryState.genebank == self.gb.id
        ).execute()

        self.assertEqual(gs.reconcile_history(self.gb.id, today=TODAY), "unchanged")

        self.assertEqual([r.id for r in self.rows()], before_ids)  # no delete + reinsert
        self.assertGreater(self.state().checked_at, backdated)

    def test_year_closing_at_midnight_appears_on_the_next_run(self):
        end = date(2024, 3, 30)
        self._round(2023, end)

        self.assertEqual(gs.reconcile_history(self.gb.id, today=end), "replaced")
        self.assertEqual(self.years(), [2021, 2022])
        version = db.read_genetics_version()

        self.assertEqual(gs.reconcile_history(self.gb.id, today=end + timedelta(days=1)), "replaced")

        self.assertEqual(db.read_genetics_version(), version)  # nothing was written in between
        self.assertEqual(self.years(), [2021, 2022, 2023])
        self.assertEqual(self.rows()[-1].as_of, end + timedelta(days=1))

    def test_round_of_the_current_year_that_has_ended_is_included(self):
        self._round(2024, date(2024, 5, 15))  # closes on 16 May, before TODAY (1 June 2024)
        for animal in self.early + self.late:
            ht_row("ATTESTATION", individual=animal, herd=self.herd, herd_tracking_date=date(2024, 5, 1))

        self.assertEqual(gs.reconcile_history(self.gb.id, today=TODAY), "replaced")

        self.assertEqual(self.years(), [2021, 2022, 2023, 2024])
        self.assertEqual(self.rows()[-1].as_of, date(2024, 5, 16))
        self.assertEqual(self.rows()[-1].active_count, 30)

    def test_reopened_round_removes_its_year(self):
        report_round = self._round(2022, date(2023, 3, 30))
        gs.reconcile_history(self.gb.id, today=TODAY)
        self.assertEqual(self.years(), [2021, 2022, 2023])

        report_round.end_date = TODAY + timedelta(days=90)
        report_round.save()

        self.assertEqual(gs.reconcile_history(self.gb.id, today=TODAY), "replaced")
        self.assertEqual(self.years(), [2021, 2023])

    def test_older_candidate_never_overwrites_a_newer_publication(self):
        candidate = gs.desired_history_rows(self.gb.id, TODAY)
        self._animal(date(2021, 3, 1), [2022])  # commits: version moves on, 2022 gets 31 members
        self.assertGreater(db.read_genetics_version(), candidate[0])
        self.assertEqual(gs.reconcile_history(self.gb.id, today=TODAY), "replaced")
        published = [(r.id, r.pedigree_version, r.active_count) for r in self.rows()]
        self.assertGreater(self.state().version, candidate[0])
        self.assertEqual([p[2] for p in published], [30, 31, 30])

        self.assertEqual(gs._publish_history(self.gb.id, *candidate), "discarded")

        self.assertEqual([(r.id, r.pedigree_version, r.active_count) for r in self.rows()], published)

    def test_newer_empty_publication_still_wins(self):
        version, rows = gs.desired_history_rows(self.gb.id, TODAY)
        self.assertTrue(rows)

        self.assertEqual(gs._publish_history(self.gb.id, version + 1, []), "replaced")
        self.assertEqual(gs._publish_history(self.gb.id, version, rows), "discarded")
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.state().version, version + 1)

        self.assertEqual(gs._publish_history(self.gb.id, version + 1, []), "unchanged")

    def _publish_as(self, definition, version, rows):
        """Publish like a worker running reference definition ``definition``."""
        rows = [{**r, "definition_version": definition} for r in rows]
        return gs._publish_history(self.gb.id, version, rows, definition=definition)

    def test_older_definition_never_overwrites_a_newer_one(self):
        """Rollout: a worker still on the current definition publishes after one on the next."""
        version, rows = gs.desired_history_rows(self.gb.id, TODAY)
        current = rp.CURRENT_DEFINITION.version
        # Seeded without the definition argument: the newer worker's publication of one year.
        gs._publish_history(self.gb.id, version, rows[:1])
        for model in (db.GeneticMetricsHistory, db.GeneticsHistoryState):
            model.update(definition_version=current + 1).where(model.genebank == self.gb.id).execute()
        published = [(r.id, r.definition_version) for r in self.rows()]

        candidates = [(version + 5, rows), (version, rows), (version + 5, []), (version, [])]
        for candidate_version, candidate_rows in candidates:
            with self.subTest(version=candidate_version - version, rows=len(candidate_rows)):
                self.assertEqual(gs._publish_history(self.gb.id, candidate_version, candidate_rows), "discarded")
                self.assertEqual(self._publish_as(current, candidate_version, candidate_rows), "discarded")

        self.assertEqual([(r.id, r.definition_version) for r in self.rows()], published)
        self.assertEqual((self.state().definition_version, self.state().version), (current + 1, version))

    def test_higher_definition_always_replaces(self):
        version, rows = gs.desired_history_rows(self.gb.id, TODAY)
        current = rp.CURRENT_DEFINITION.version
        self.assertEqual(gs.reconcile_history(self.gb.id, today=TODAY), "replaced")

        # A lower pedigree version under a higher definition still wins, with rows and empty.
        self.assertEqual(self._publish_as(current + 1, version - 1, rows), "replaced")
        self.assertEqual((self.state().definition_version, self.state().version), (current + 1, version - 1))
        self.assertEqual({r.definition_version for r in self.rows()}, {current + 1})
        self.assertEqual(self._publish_as(current + 2, version - 1, []), "replaced")
        self.assertEqual(self.rows(), [])
        self.assertEqual((self.state().definition_version, self.state().version), (current + 2, version - 1))
        self.assertEqual(self._publish_as(current + 2, version - 1, []), "unchanged")

    def test_history_does_not_depend_on_pedigree_row_order_with_a_cycle(self):
        """A and B are each other's sire; A also has a known dam. Which link is dropped must not depend on row order."""
        a, b, dam = self.early[0], self.early[1], self.early[2]
        db.Breeding.update(father=b.id, mother=dam.id).where(db.Breeding.id == a.breeding_id).execute()
        db.Breeding.update(father=a.id).where(db.Breeding.id == b.breeding_id).execute()
        real = gs.fetch_pedigree_rows

        _, forward = gs.desired_history_rows(self.gb.id, TODAY)
        with patch.object(gs, "fetch_pedigree_rows", lambda gb: list(reversed(real(gb)))):
            _, backward = gs.desired_history_rows(self.gb.id, TODAY)

        self.assertEqual([r["report_year"] for r in forward], [2021, 2022, 2023])
        self.assertEqual([r["report_year"] for r in backward], [2021, 2022, 2023])
        for f, r in zip(forward, backward, strict=True):
            for name in ("mean_inbreeding", "mean_kinship", "fge", "founder_equivalents"):
                self.assertTrue(np.isfinite(f[name]), name)
                np.testing.assert_allclose(r[name], f[name], rtol=0, atol=1e-12, err_msg=f"{f['report_year']} {name}")

    def test_commit_between_historical_reads_does_not_reach_the_candidate(self):
        victim = self.early[0].number  # a member of every year
        original = rp.members
        calls = []

        def members_with_concurrent_commit(*args, **kwargs):
            if not calls:
                conn = _connect()
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE individual SET death_date = %s WHERE number = %s", (date(2020, 1, 2), victim)
                        )
                    conn.commit()
                finally:
                    conn.close()
            calls.append(kwargs["as_of"])
            return original(*args, **kwargs)

        v0 = db.read_genetics_version()
        with patch.object(rp, "members", members_with_concurrent_commit):
            version, rows = gs.desired_history_rows(self.gb.id, TODAY)

        self.assertEqual(db.read_genetics_version(), v0 + 1)  # the write committed
        self.assertGreater(len(calls), 1)  # later years were read after the commit
        self.assertEqual(version, v0)
        self.assertEqual([r["report_year"] for r in rows], [2021, 2022, 2023])
        self.assertEqual([r["pedigree_version"] for r in rows], [v0] * 3)
        self.assertEqual([r["active_count"] for r in rows], [30, 30, 30])  # the victim is still alive here
        # A fresh read sees the write.
        start, as_of = rp.history_window(2022)
        self.assertNotIn(victim, rp.members(self.gb.id, start=start, as_of=as_of, live=False))

    def test_second_reconcile_is_busy_while_one_runs(self):
        original = gs.desired_history_rows
        entered, release = threading.Event(), threading.Event()
        results = []

        def parked(*args, **kwargs):
            entered.set()
            release.wait(WAIT)
            return original(*args, **kwargs)

        def first():
            try:
                results.append(gs.reconcile_history(self.gb.id, today=TODAY))
            except Exception as e:  # pylint: disable=broad-except
                results.append(e)
            finally:
                db.DATABASE.close()

        with patch.object(gs, "desired_history_rows", parked):
            thread = threading.Thread(target=first)
            thread.start()
            try:
                self.assertTrue(entered.wait(WAIT))
                self.assertEqual(gs.reconcile_history(self.gb.id, today=TODAY), "busy")
            finally:
                release.set()
                thread.join(WAIT)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, ["replaced"])
        self.assertEqual(self.years(), [2021, 2022, 2023])

    def test_existing_cycle_does_not_stop_reconcile(self):
        child = self._animal(date(2022, 3, 1), [2022, 2023], father=self.early[1], mother=self.early[2])
        # Raw write: early[1]'s litter gets its own son as father, so the stored pedigree loops.
        db.Breeding.update(father=child).where(db.Breeding.id == self.early[1].breeding_id).execute()

        self.assertEqual(gs.reconcile_history(self.gb.id, today=TODAY), "replaced")

        self.assertEqual(self.years(), [2021, 2022, 2023])
        for r in self.rows():
            self.assertTrue(np.isfinite(r.mean_kinship))

    def test_failed_reconcile_releases_the_session_lock(self):
        """Session advisory locks are re-entrant per connection, so the next reconcile runs on another one."""
        results = []

        def other_connection():
            try:
                results.append(gs.reconcile_history(self.gb.id, today=TODAY))
            finally:
                db.DATABASE.close()

        with patch.object(gs, "desired_history_rows", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                gs.reconcile_history(self.gb.id, today=TODAY)

        thread = threading.Thread(target=other_connection)
        thread.start()
        thread.join(WAIT)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, ["replaced"])


class TestHistoryWithUnknownBirthDates(HistoryTest):
    def test_unknown_birth_dates_do_not_suppress_history(self):
        """Historical membership admits unknown births, so the year range must not start at the first known one."""
        db.Breeding.update(birth_date=None).where(
            db.Breeding.id.in_([i.breeding_id for i in self.early + self.late])
        ).execute()

        self.assertEqual(gs.reconcile_history(self.gb.id, today=TODAY), "replaced")

        rows = self.rows()
        self.assertEqual([r.report_year for r in rows], [2021, 2022, 2023])
        self.assertEqual([(r.active_count, r.population_size) for r in rows], [(30, 30)] * 3)

    def test_life_sign_early_in_a_year_counts_for_the_previous_year(self):
        """With unknown births, a life sign dated before 1 April falls in the previous year's window too."""
        gb = db.Genebank.create(name="Tidig-genbank")
        herd = db.Herd.create(genebank=gb, herd="H2", herd_name="Aktiv", is_active=True)
        for n in range(rp.MIN_HISTORY_MEMBERS):
            breeding = db.Breeding.create(breeding_herd_id=herd, birth_date=None)
            individual = db.Individual.create(
                origin_herd=herd, number=f"H2-{n:03d}", breeding=breeding, certificate=f"C-H2-{n}", sex="female"
            )
            ht_row("BIRTH", individual=individual, from_herd=herd, herd=herd, herd_tracking_date=date(2022, 2, 1))

        self.assertEqual(gs.reconcile_history(gb.id, today=TODAY), "replaced")

        rows = db.GeneticMetricsHistory.select().where(db.GeneticMetricsHistory.genebank == gb.id)
        first = min(rows, key=lambda r: r.report_year)
        self.assertEqual((first.report_year, first.active_count), (2021, rp.MIN_HISTORY_MEMBERS))


class TestHistoryFounderEquivalents(HistoryTest):
    """Each year's FE equals calculate_founder_equivalents over that year's members."""

    def setUp(self):
        super().setUp()
        with db.DATABASE.atomic():
            self._animal(date(2021, 2, 1), [2021])  # a founder that is a member in 2021 only
            kid = self._animal(date(2022, 3, 1), [2022, 2023], father=self.early[0], mother=self.early[1])
            self._animal(date(2023, 3, 1), [2023], father=kid, mother=self.late[0])
            self._animal(date(2023, 3, 1), [2023], father=kid, mother=kid)  # inbred
            gone = self._animal(date(2021, 3, 1), [])
            gone.voided = True
            gone.save()
            # Father outside the pedigree (voided): a phantom founder of its own on that side.
            self._animal(date(2022, 3, 1), [2022, 2023], father=gone, mother=self.late[1])

    def test_founder_equivalents_match_the_reference_function(self):
        version, rows = gs.desired_history_rows(self.gb.id, TODAY)
        snap = ps.build_snapshot(self.gb.id, gs.fetch_pedigree_rows(self.gb.id), set(), key=("t",), seq=0)

        self.assertEqual([r["report_year"] for r in rows], [2021, 2022, 2023])
        absent_somewhere = False
        for r in rows:
            start, as_of = rp.history_window(r["report_year"])
            members = rp.members(self.gb.id, start=start, as_of=as_of, live=False)
            ids = [i for i in snap.ids if i in members]
            expected = calculate_founder_equivalents(snap.individuals, ids)
            self.assertTrue(np.isfinite(r["founder_equivalents"]))
            np.testing.assert_allclose(r["founder_equivalents"], expected, rtol=0, atol=1e-12)
            avg, founders = calculate_average_founder_contributions(snap.individuals, ids)
            absent_somewhere |= any(avg[f] == 0 for f in founders)
        self.assertTrue(absent_somewhere)  # some founder contributes nothing to some year
        self.assertNotEqual(rows[-1]["founder_equivalents"], rows[-1]["active_count"])  # not the trivial case

    def test_one_unknown_parent_is_a_founder_of_its_own(self):
        """A, then X (sire A, dam unknown), sorted; the history pass gives FE 2 like the live one (was 4)."""
        fe = gs._founder_equivalents([-1, 0], [-1, -1], np.array([0]), np.array([False, True]))
        self.assertAlmostEqual(fe, 2.0, msg=f"history FE for one offspring of a founder and an unknown dam = {fe}")


HISTORY_COMPUTE_BUDGET_S = 5.0  # 25 years on a prebuilt snapshot; the build is measured on real data


class TestTrendsAndScheduling(HistoryTest):
    def _row(self, year, as_of, **kw):
        values = dict(
            genebank=self.gb.id, report_year=year, snapshot_date=as_of, as_of=as_of, definition_version=3,
            pedigree_version=1, population_size=40, active_count=35, mean_inbreeding=0.01,
            mean_kinship=0.02, founder_equivalents=12.0, data_quality="high",
        )  # fmt: skip
        values.update(kw)
        return db.GeneticMetricsHistory.create(**values)

    def _fresh_state(self, age):
        db.GeneticsHistoryState.delete().execute()
        db.GeneticsHistoryState.create(
            genebank=self.gb.id, checked_at=datetime.now(timezone.utc) - age, version=1, definition_version=3
        )

    def test_trends_keys_year_mapping_and_filtering(self):
        self._fresh_state(timedelta(hours=1))
        self._row(2024, date(2025, 4, 1))
        self._row(2025, date(2026, 3, 31))
        self._row(2026, date(2027, 4, 1))

        rows = gs.get_genetics_trends(self.gb.id)

        self.assertEqual([r["year"] for r in rows], [2024, 2025, 2026])
        self.assertEqual(
            set(rows[0]),
            {
                "year", "snapshot_date", "population_size", "active_count", "mean_inbreeding", "mean_kinship",
                "effective_population_size", "founder_equivalents", "data_quality", "definition_version",
            },
        )  # fmt: skip
        self.assertEqual(rows[1]["snapshot_date"], "2026-03-31")
        self.assertEqual(rows[1]["definition_version"], 3)
        self.assertEqual([r["year"] for r in gs.get_genetics_trends(self.gb.id, end_year=2025)], [2024, 2025])
        self.assertEqual([r["year"] for r in gs.get_genetics_trends(self.gb.id, start_year=2025)], [2025, 2026])

    def test_stale_burst_starts_exactly_one_reconcile(self):
        self._fresh_state(timedelta(hours=30))
        calls = []
        release = threading.Event()

        def slow_reconcile(genebank_id):
            calls.append(genebank_id)
            release.wait(WAIT)  # in flight until every caller has been through
            return "unchanged"

        barrier = threading.Barrier(20)

        def caller():
            barrier.wait(WAIT)
            gs.maybe_reconcile_in_background(self.gb.id)

        with patch.object(gs, "reconcile_history", slow_reconcile), patch.object(gs.ps, "_close_db_connection"):
            threads = [threading.Thread(target=caller) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(WAIT)
            release.set()
            gs._reconcile_executor.submit(lambda: None).result(WAIT)  # drain

        self.assertEqual(calls, [self.gb.id])

    def test_fresh_state_starts_no_reconcile(self):
        self._fresh_state(timedelta(hours=1))
        with patch.object(gs, "reconcile_history") as reconcile:
            gs.maybe_reconcile_in_background(self.gb.id)
            gs._reconcile_executor.submit(lambda: None).result(WAIT)
        reconcile.assert_not_called()

    def test_cli_commands_call_reconcile(self):
        from herdbook import APP, genetics_cli

        runner = APP.test_cli_runner()
        with patch("herdbook.genetics.reconcile_history", return_value="replaced") as reconcile:
            for args in (["recompute-history", "7"], ["backfill-history", "7", "--start-year", "2000"]):
                result = runner.invoke(genetics_cli, args)
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIn("replaced", result.output)
        self.assertEqual([c.args for c in reconcile.call_args_list], [(7,), (7,)])

    def test_nightly_job_survives_a_failing_genebank(self):
        from herdbook import _reconcile_all_history

        first, second = SimpleNamespace(id=1), SimpleNamespace(id=2)

        def reconcile(genebank_id):
            if genebank_id == 1:
                raise RuntimeError("boom")
            return "unchanged"

        with (
            patch("herdbook.da.get_all_genebanks", return_value=[first, second]),
            patch("herdbook.genetics.reconcile_history", side_effect=reconcile) as mock,
            patch("herdbook.genetics.ps._close_db_connection") as close,
        ):
            _reconcile_all_history()
        self.assertEqual([c.args for c in mock.call_args_list], [(1,), (2,)])
        self.assertEqual(close.call_count, 2)  # after the failing genebank, and when the job ends


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("RUN_SLOW") != "1", reason="set RUN_SLOW=1 to run measurements")
class TestHistoryComputeTiming(unittest.TestCase):
    """Gotland-sized history compute: ~16 700 animals, 25 years of ~820 members (pure, no database).

    The synthetic pedigree is far more densely inbred than the real one, so its
    build (Henderson F) is printed, not asserted; only the per-year maths is.
    """

    def test_compute_within_budget(self):
        founders, cohorts, per_cohort, n_members = 500, 25, 648, 820
        sire, dam, sex = synthetic_pedigree(n_founders=founders, cohorts=cohorts, per_cohort=per_cohort, seed=11)
        rows, ids = rows_from_arrays(sire, dam, sex)
        births = {ids[i]: date(1999, 5, 1) for i in range(founders)}
        for c in range(cohorts):
            for i in range(founders + c * per_cohort, founders + (c + 1) * per_cohort):
                births[ids[i]] = date(2000 + c, 5, 1)
        rng = np.random.default_rng(3)
        years = {}
        for c in range(cohorts):
            # Members are drawn from the year's cohort and the two before it.
            pool = np.arange(founders + max(0, c - 2) * per_cohort, founders + (c + 1) * per_cohort)
            chosen = rng.choice(pool, min(n_members, len(pool)), replace=False)
            years[2000 + c] = (date(2001 + c, 4, 1), {ids[i] for i in chosen})

        started = time.perf_counter()
        snap = ps.build_snapshot(1, rows, set(), key=("history", 0), seq=0)
        built = time.perf_counter() - started
        started = time.perf_counter()
        out = gs._history_rows_on(snap, 0, births, years)
        elapsed = time.perf_counter() - started

        print(f"\nsnapshot build (not asserted): {len(rows)} animals, {built:.2f} s")
        print(f"history compute: {len(out)} years, {elapsed:.2f} s")
        self.assertEqual(len(rows), 16700)
        self.assertEqual(len(out), cohorts)
        self.assertLessEqual(elapsed, HISTORY_COMPUTE_BUDGET_S)
