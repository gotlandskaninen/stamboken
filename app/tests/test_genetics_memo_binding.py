"""A result computed on snapshot v is cached under v even if v+1 is published meanwhile."""

from datetime import date
from unittest.mock import patch

import herdbook
import utils.database as db
import utils.genetics_service as gs
from cachelib import SimpleCache

from tests.database_test import DatabaseTest
from tests.ht_helpers import ht_row


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
    """The shared memo key identifies the database, not only its genetics version counter.

    A restored dump (or the nightly demo sync) brings back an older counter, and the next
    edits walk the same numbers again over different pedigree data. The dump restore
    (stamboken-drift) and sync-demo-db.sh run `flask genetics rotate-epoch` so the restarted workers never
    get the previous database's numbers from the memo.
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
