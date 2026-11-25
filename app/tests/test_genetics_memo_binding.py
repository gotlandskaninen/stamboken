"""A result computed on snapshot v is cached under v even if v+1 is published meanwhile."""

import unittest
from datetime import date, timedelta
from unittest.mock import patch

import herdbook
import utils.cache_invalidation as ci
import utils.database as db
import utils.genetics_service as gs
from cachelib import SimpleCache
from utils.genetics import MAX_RABBIT_AGE_DAYS

from tests.database_test import DatabaseTest
from tests.ht_helpers import ht_row, make_individual


class TestMemoBinding(DatabaseTest):
    def setUp(self):
        super().setUp()
        herdbook.CACHE.clear()
        self.gb = self.genebanks[0].id
        # A closed round: the reference population starts 2025-01-01.
        db.YearlyReportRound.create(report_year=2025, end_date=date(2026, 3, 30), created_by=self.admin)
        self.member = self.individuals[0]
        db.Individual.update(certificate="M-1").where(db.Individual.id == self.member.id).execute()
        herd = self.member.current_herd
        db.Herd.update(is_active=True).where(db.Herd.id == herd.id).execute()  # fixture herds start inactive
        ht_row("ATTESTATION", individual=self.member, herd=herd, herd_tracking_date=date(2025, 12, 31))
        self.assertIn(self.member.number, gs.reference_population_numbers(self.gb))  # precondition
        gs.snapshot(self.gb)
        gs.ps.wait_for_builds(self.gb, timeout=5)

    def test_publication_during_computation_does_not_mislabel(self):
        snap_v1 = gs.snapshot(self.gb)
        self.assertIn(self.member.number, gs.get_mean_kinship(self.gb))  # precondition: a real member
        real = gs.get_mean_kinship
        used = []

        def compute_then_write(genebank_id):
            used.append(gs.ps.get_snapshot(genebank_id))
            result = real(genebank_id)
            db.Individual.update(death_date=date(2026, 1, 1)).where(db.Individual.id == self.member.id).execute()
            gs.invalidate_cache(genebank_id)
            gs.ps.wait_for_builds(genebank_id, timeout=5)  # v2 is now published
            return result

        with patch.object(gs, "get_mean_kinship", side_effect=compute_then_write) as computed:
            first = herdbook.get_mean_kinship(self.gb)
            self.assertIs(used[0], snap_v1)
            self.assertIn(self.member.number, first)
            second = herdbook.get_mean_kinship(self.gb)  # v2: the member died
            self.assertNotIn(self.member.number, second)
            calls = computed.call_count
            with gs.ps.pinned(snap_v1):  # v1's value is still cached under v1
                self.assertEqual(herdbook.get_mean_kinship(self.gb), first)
            self.assertEqual(computed.call_count, calls)


class TestMemoAfterADatabaseReplacement(DatabaseTest):
    """The shared memo never serves the previous database's numbers.

    A restored dump (or the nightly demo sync) brings back an older counter, and the next
    edits walk the same numbers again over different pedigree data. The dump restore
    (stamboken-drift) and sync-demo-db.sh run `flask genetics rotate-epoch`; the memo key is
    the snapshot's content, so the different pedigree misses it whatever the counter says.
    """

    def test_rotated_epoch_does_not_serve_the_previous_databases_numbers(self):
        gb = self.genebanks[0].id
        founder_breeding = db.Breeding.create(breeding_herd_id=self.herds[0])  # unknown parents
        x = db.Individual.create(origin_herd=self.herds[0], breeding=founder_breeding, number="G1-X1")
        backend = {herdbook.CACHE: SimpleCache()}
        with patch.dict(herdbook.APP.extensions["cache"], backend):
            self.assertEqual(herdbook.get_inbreeding(gb)["G1-X1"], 0.0)  # memoized under today's key
            v = db.read_genetics_version()

            # Database replaced by one whose counter is one behind; its next pedigree
            # write (X gets full-sibling parents, F = 0.25) reaches V again.
            db.DATABASE.execute_sql("UPDATE genetics_version SET version = %s WHERE id = 1", (v - 1,))
            db.Individual.update(breeding=self.breeding[4]).where(db.Individual.id == x.id).execute()
            self.assertEqual(db.read_genetics_version(), v)  # same counter, different pedigree

            rotated = herdbook.APP.test_cli_runner().invoke(args=["genetics", "rotate-epoch"])  # what the scripts run
            herdbook.genetics.ps.reset_for_tests()  # the API restart after the restore
            snap = herdbook.genetics.snapshot(gb)
            self.assertAlmostEqual(float(snap.F[snap.index["G1-X1"]]), 0.25)  # the fresh snapshot is right
            served = herdbook.get_inbreeding(gb)["G1-X1"]
        self.assertAlmostEqual(served, 0.25, msg=f"memo served F={served} computed from the previous database")
        self.assertEqual(rotated.exit_code, 0, rotated.output)


class TestMemoFollowsTheInputs(DatabaseTest):
    """The shared memo is keyed on what the results are computed from.

    The genetics version moves on any write in either genebank, every herd-tracking
    column included, and the snapshot key carries the day: neither alone may cost
    a genebank its cached results, the slow gene drop above all.
    """

    def setUp(self):
        super().setUp()
        self.gb = self.genebanks[0].id
        self.herd = self.herds[0]
        # A closed round: the reference population starts 2025-01-01.
        db.YearlyReportRound.create(report_year=2025, end_date=date(2026, 3, 30), created_by=self.admin)
        db.Herd.update(is_active=True).where(db.Herd.id == self.herd.id).execute()  # fixture herds start inactive
        self.male = make_individual(self.herd, "G1-M1", date(2024, 5, 1), sex="male")
        self.female = make_individual(self.herd, "G1-F1", date(2024, 5, 2))
        self.attestations = [
            ht_row("ATTESTATION", individual=ind, herd=self.herd, herd_tracking_date=date(2025, 12, 31))
            for ind in (self.male, self.female)
        ]
        backend = patch.dict(herdbook.APP.extensions["cache"], {herdbook.CACHE: SimpleCache()})
        backend.start()
        self.addCleanup(backend.stop)
        self.computed = {}
        for name in ("get_genetic_priorities", "get_founders_at_risk"):
            patcher = patch.object(gs, name, side_effect=getattr(gs, name))
            self.computed[name] = patcher.start()
            self.addCleanup(patcher.stop)
        self.assertEqual(gs.reference_population_numbers(self.gb), {"G1-M1", "G1-F1"})  # precondition
        gs.snapshot(self.gb)
        gs.ps.wait_for_builds(self.gb, timeout=10)

    def _rebuilt(self):
        """The snapshot after the rebuild a write or a new day asks for: never the retained one."""
        before = gs.snapshot(self.gb)
        gs.invalidate_cache(self.gb)
        gs.ps.wait_for_builds(self.gb, timeout=10)
        after = gs.snapshot(self.gb)
        self.assertIsNot(after, before)
        self.assertNotEqual(after.key, before.key)
        return before, after

    def _calls(self):
        herdbook.get_genetic_priorities(self.gb)
        herdbook.get_founders_at_risk(self.gb)
        return {name: mock.call_count for name, mock in self.computed.items()}

    def _assert_kept(self, write):
        first = herdbook.get_genetic_priorities(self.gb)
        calls = self._calls()
        write()
        before, after = self._rebuilt()
        self.assertEqual(herdbook._memo_key(after), herdbook._memo_key(before))
        self.assertEqual(self._calls(), calls)  # served from the memo, nothing recomputed
        self.assertEqual(herdbook.get_genetic_priorities(self.gb), first)

    def _assert_recomputed(self, write):
        calls = self._calls()
        write()
        before, after = self._rebuilt()
        self.assertNotEqual(herdbook._memo_key(after), herdbook._memo_key(before))
        self.assertEqual(self._calls()["get_genetic_priorities"], calls["get_genetic_priorities"] + 1)
        return before, after

    def test_herd_tracking_note_keeps_the_key(self):
        row = self.attestations[0]
        self._assert_kept(
            lambda: db.HerdTracking.update(notes="ny anteckning").where(db.HerdTracking.id == row.id).execute()
        )

    def test_write_in_the_other_genebank_keeps_the_key(self):
        mellerud = self.herds[2]

        def write():
            make_individual(mellerud, "M3-NY", date(2026, 6, 1))
            db.Individual.update(death_date=date(2026, 11, 1)).where(db.Individual.number == "M3-1911").execute()

        self._assert_kept(write)

    def test_new_day_with_the_same_inputs_keeps_the_key(self):
        before = gs.snapshot(self.gb)
        calls = self._calls()
        today = date.today()

        class Tomorrow(date):
            @classmethod
            def today(cls):
                return today + timedelta(days=1)

        with patch("utils.genetics_service.date", Tomorrow):
            gs.snapshot(self.gb)  # the day moved the key: a rebuild starts
            gs.ps.wait_for_builds(self.gb, timeout=10)
            after = gs.snapshot(self.gb)
            self.assertNotEqual(after.key[1], before.key[1])
            self.assertEqual(after.ref_ids, before.ref_ids)
            self.assertEqual(after.recovery_eligible, before.recovery_eligible)
            self.assertEqual(herdbook._memo_key(after), herdbook._memo_key(before))
            self.assertEqual(self._calls(), calls)

    def test_new_day_that_ages_out_a_carrier_recomputes_only_founders_at_risk(self):
        """Carrier eligibility has an age cap, so it moves with the date; only founders at risk reads it."""
        today = date.today()
        make_individual(self.herd, "G1-OLD", today - timedelta(days=MAX_RABBIT_AGE_DAYS))  # eligible for one more day
        gs.invalidate_cache(self.gb)
        gs.ps.wait_for_builds(self.gb, timeout=10)
        self.assertIn("G1-OLD", gs.snapshot(self.gb).recovery_eligible)  # precondition
        calls = self._calls()

        class Tomorrow(date):
            @classmethod
            def today(cls):
                return today + timedelta(days=1)

        with patch("utils.genetics_service.date", Tomorrow):
            gs.snapshot(self.gb)
            gs.ps.wait_for_builds(self.gb, timeout=10)
            self.assertNotIn("G1-OLD", gs.snapshot(self.gb).recovery_eligible)
            self.assertEqual(
                self._calls(),
                {
                    "get_genetic_priorities": calls["get_genetic_priorities"],
                    "get_founders_at_risk": calls["get_founders_at_risk"] + 1,
                },
            )

    def test_debounced_warm_up_computes_the_latest_write(self):
        """The leader warms the state the write produced, so the next visit does not compute it."""
        ci.set_cache_and_functions(memoized_funcs=[herdbook.get_genetic_priorities], breeding_suggestions_func=None)
        self.addCleanup(ci.set_cache_and_functions, memoized_funcs=[], breeding_suggestions_func=None)
        herdbook.get_genetic_priorities(self.gb)
        # No build in flight: nothing has read the snapshot since the write.
        db.Individual.update(death_date=date(2026, 11, 1)).where(db.Individual.id == self.female.id).execute()
        ci._recompute_genebank(self.gb)
        warmed = self.computed["get_genetic_priorities"].call_count
        gs.ps.wait_for_builds(self.gb, timeout=10)
        self.assertFalse(gs.snapshot_status(self.gb)[1])
        herdbook.get_genetic_priorities(self.gb)
        self.assertEqual(self.computed["get_genetic_priorities"].call_count, warmed)

    def test_relevant_changes_move_the_key(self):
        cases = {
            "new registered individual": lambda: db.Individual.create(
                origin_herd=self.herd, breeding=self.breeding[0], number="G1-KID"
            ),
            "parent change": lambda: (
                db.Breeding.update(father=self.male).where(db.Breeding.id == self.breeding[0].id).execute()
            ),
            "death date": lambda: (
                db.Individual.update(death_date=date(2026, 11, 1)).where(db.Individual.id == self.female.id).execute()
            ),
        }
        for name, write in cases.items():
            with self.subTest(name):
                self._assert_recomputed(write)

    def test_membership_alone_moves_the_key(self):
        """An existing animal gains a life sign in the window: the same pedigree rows, one more member."""
        candidate = make_individual(self.herd, "G1-F2", date(2024, 6, 1))  # certified, no life sign: not a member
        self._rebuilt()
        before, after = self._assert_recomputed(
            lambda: ht_row("ATTESTATION", individual=candidate, herd=self.herd, herd_tracking_date=date(2025, 12, 31))
        )
        self.assertEqual(after.ids, before.ids)
        self.assertEqual(set(after.ref_ids) - set(before.ref_ids), {"G1-F2"})


class TestMemoKeyCoversTheBody(unittest.TestCase):
    """The memoized bodies live in herdbook.py, outside CODE_VERSION: a changed body misses the old entries."""

    BODIES = {
        "_get_population_metrics_cached": (),
        "_get_founder_statistics_cached": (),
        "_get_founders_at_risk_cached": (),
        "_get_genetic_priorities_cached": (),
        "_get_breeding_suggestions_cached": (20, 0.0625, 3, 1),
    }

    def test_a_changed_body_changes_the_key(self):
        with patch.dict(herdbook.APP.extensions["cache"], {herdbook.CACHE: SimpleCache()}):
            for name, params in self.BODIES.items():
                with self.subTest(name):
                    body = getattr(herdbook, name)
                    key = body.make_cache_key(body.uncached, 1, "content-key", *params)
                    with patch("inspect.getsource", return_value="def body(): return 'changed'"):
                        changed = body.make_cache_key(body.uncached, 1, "content-key", *params)
                    self.assertNotEqual(changed, key)
