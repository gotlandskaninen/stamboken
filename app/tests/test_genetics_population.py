#!/usr/bin/env python3
"""
Tests for the mean kinship reference population.

The population is derived from the legacy rule: active herd, certificate,
alive, not castrated, and a herd tracking event on or after 1 January of the
most recently closed yearly report round.

isort:skip_file
"""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import utils.data_access as da
import utils.database as db
import utils.genetics_service as gs
import utils.pedigree_snapshot as ps
from utils.genetics import MAX_RABBIT_AGE_DAYS

from tests.database_test import DatabaseTest
from tests.ht_helpers import _void, ht_row

START = date(2025, 1, 1)


class GeneticsPopulationTest(DatabaseTest):
    """Shared fixture: a genebank whose individuals sit on both sides of START."""

    def setUp(self):
        super().setUp()
        self._reset_caches()

    def tearDown(self):
        self._reset_caches()
        super().tearDown()

    @staticmethod
    def _reset_caches():
        ps.reset_for_tests()

    def _round(self, year, end_date):
        return db.YearlyReportRound.create(
            report_year=year,
            start_date=date(year, 12, 31),
            end_date=end_date,
            created_by=self.admin,
        )


class TestReferencePopulationStart(GeneticsPopulationTest):
    """reference_population_start() derives 1 January of the last closed round."""

    def test_uses_most_recent_closed_round(self):
        """The latest round whose end_date has passed decides the start date."""
        self._round(2024, date(2025, 3, 30))
        self._round(2025, date(2026, 3, 30))

        self.assertEqual(gs.reference_population_start(date(2026, 9, 20)), date(2025, 1, 1))
        # Before the 2025 round closed, the 2024 round is the most recent closed one.
        self.assertEqual(gs.reference_population_start(date(2026, 2, 1)), date(2024, 1, 1))

    def test_open_round_only_falls_back_to_previous_year(self):
        """A round that has not closed yet (future or missing end_date) is ignored."""
        self._round(2026, date(2027, 3, 30))
        self._round(2027, None)

        self.assertEqual(gs.reference_population_start(date(2026, 9, 20)), date(2025, 1, 1))

    def test_no_rounds_falls_back_to_previous_year(self):
        """Without any report round the previous calendar year is used."""
        self.assertEqual(gs.reference_population_start(date(2026, 9, 20)), date(2025, 1, 1))
        self.assertEqual(gs.reference_population_start(date(2030, 5, 5)), date(2029, 1, 1))


class TestReferencePopulationMembership(GeneticsPopulationTest):
    """One fixture per condition of the rule, asserted as a whole set."""

    def setUp(self):
        super().setUp()
        self.genebank = db.Genebank.create(name="MK-genbank")
        self.active_herd = db.Herd.create(
            genebank=self.genebank, herd="MK1", herd_name="Aktiv besättning", is_active=True
        )
        self.buyer_herd = db.Herd.create(
            genebank=self.genebank, herd="MK2", herd_name="Köparens besättning", is_active=True
        )
        # Mirrors the GX1/MX1 "external sale" herds in production.
        self.sale_herd = db.Herd.create(
            genebank=self.genebank, herd="MKX1", herd_name="Utanför genbanken", is_active=False
        )
        self._next_certificate = 9000

    def _individual(self, number, tracking=(), certificate=True, **kwargs):
        """Create an individual with herd tracking rows [(date, herd), ...]."""
        if certificate:
            self._next_certificate += 1
            kwargs["certificate"] = str(self._next_certificate)
        individual = db.Individual.create(origin_herd=self.active_herd, number=number, **kwargs)
        previous = None
        for tracking_date, herd in sorted(tracking, key=lambda row: row[0]):
            if previous is None:
                kind = "BIRTH" if herd == self.active_herd else "TRANSFER"
            else:
                kind = "TRANSFER" if herd != previous else "ATTESTATION"
            previous = herd
            ht_row(
                kind,
                individual=individual,
                from_herd=self.active_herd,
                herd=herd,
                herd_tracking_date=tracking_date,
            )
        return individual

    def _build_population(self):
        """Create one individual per condition; returns (member numbers, non-member numbers)."""
        members = {
            # Reported inside the window.
            self._individual("MK1-2601", tracking=[(date(2026, 6, 1), self.active_herd)]).number,
            # (a) Only event is 2025-02-01: after START, but far outside the old
            # rolling 13-month window — the rule change is exactly this case.
            self._individual("MK1-2501", tracking=[(date(2025, 2, 1), self.active_herd)]).number,
            # (d) A sale (from_herd != herd) counts as an event.
            self._individual("MK1-2502", tracking=[(date(2025, 6, 1), self.buyer_herd)]).number,
            # A digital certificate is a certificate.
            self._individual(
                "MK1-2503", tracking=[(date(2025, 6, 1), self.active_herd)], certificate=False, digital_certificate=77
            ).number,
        }

        non_members = {
            # (b) Only event predates START.
            self._individual("MK1-2401", tracking=[(date(2024, 12, 31), self.active_herd)]).number,
            # (c) Sold out of the genebank — current herd is inactive.
            self._individual("MK1-2504", tracking=[(date(2025, 6, 1), self.sale_herd)]).number,
            # (e) Promoted from the litter roster, no certificate yet.
            self._individual("MK1-2602", tracking=[(date(2026, 6, 1), self.active_herd)], certificate=False).number,
            self._individual(
                "MK1-2505", tracking=[(date(2025, 6, 1), self.active_herd)], death_date=date(2026, 1, 5)
            ).number,
            self._individual("MK1-2506", tracking=[(date(2025, 6, 1), self.active_herd)], death_note="Dog 2026").number,
            self._individual(
                "MK1-2507", tracking=[(date(2025, 6, 1), self.active_herd)], castration_date=date(2026, 2, 1)
            ).number,
            # No herd tracking at all.
            self._individual("MK1-2508").number,
        }

        return members, non_members

    def test_membership_is_the_whole_rule(self):
        """Every condition decides membership, asserted on the set, not an average."""
        members, non_members = self._build_population()

        selected = gs.reference_population_numbers(self.genebank.id, START)

        self.assertEqual(selected, members)
        self.assertEqual(selected & non_members, set())

    def test_latest_tracking_row_decides_the_current_herd(self):
        """Sold back into an active herd after an external sale ⇒ member again."""
        individual = self._individual(
            "MK1-2509",
            tracking=[(date(2025, 3, 1), self.sale_herd), (date(2025, 9, 1), self.buyer_herd)],
        )

        self.assertIn(individual.number, gs.reference_population_numbers(self.genebank.id, START))

    def test_future_dated_tracking_rows_are_ignored(self):
        """An (erroneous) future-dated row is neither an event nor the current herd."""
        future = date.today() + timedelta(days=30)
        sold_in_future = self._individual(
            "MK1-2510", tracking=[(date(2025, 6, 1), self.active_herd), (future, self.sale_herd)]
        )
        only_future = self._individual("MK1-2511", tracking=[(future, self.active_herd)])

        selected = gs.reference_population_numbers(self.genebank.id, START)

        self.assertIn(sold_in_future.number, selected)
        self.assertNotIn(only_future.number, selected)

    def test_start_date_defaults_to_the_last_closed_round(self):
        """Without an explicit start date the closed round decides the window."""
        self._round(2025, date(2026, 3, 30))
        members, _ = self._build_population()

        self.assertEqual(gs.reference_population_numbers(self.genebank.id), members)

    def test_other_genebanks_are_not_included(self):
        """The population is scoped per genebank."""
        self._build_population()
        other_genebank = db.Genebank.create(name="Annan genbank")
        other_herd = db.Herd.create(genebank=other_genebank, herd="AN1", herd_name="Annan", is_active=True)
        other = db.Individual.create(origin_herd=other_herd, number="AN1-2601", certificate="8001")
        ht_row("BIRTH", individual=other, herd=other_herd, herd_tracking_date=date(2026, 6, 1))

        self.assertNotIn(other.number, gs.reference_population_numbers(self.genebank.id, START))
        self.assertEqual(gs.reference_population_numbers(other_genebank.id, START), {other.number})


class TestMeanKinshipUsesReferencePopulation(GeneticsPopulationTest):
    """get_mean_kinship() returns values for exactly the reference population."""

    def setUp(self):
        super().setUp()
        self.genebank = db.Genebank.create(name="MK-genbank")
        self.herd = db.Herd.create(genebank=self.genebank, herd="MK1", herd_name="Aktiv", is_active=True)
        self._round(2025, date(2026, 3, 30))

        breeding = db.Breeding.create(
            breed_date=datetime(2024, 1, 1), birth_date=datetime(2024, 2, 1), breeding_herd_id=self.herd
        )
        self.in_window = []
        for offset, number in enumerate(("MK1-2511", "MK1-2512", "MK1-2513")):
            individual = db.Individual.create(
                origin_herd=self.herd, breeding=breeding, number=number, certificate=str(9100 + offset), sex="female"
            )
            ht_row("BIRTH", individual=individual, herd=self.herd, herd_tracking_date=date(2025, 6, 1))
            self.in_window.append(individual.number)

        # Last seen in 2024 — outside the reference population.
        stale = db.Individual.create(
            origin_herd=self.herd, breeding=breeding, number="MK1-2402", certificate="9199", sex="male"
        )
        ht_row("BIRTH", individual=stale, herd=self.herd, herd_tracking_date=date(2024, 6, 1))
        self.stale = stale.number

    def test_mean_kinship_covers_exactly_the_members(self):
        """Members get a value; non-members are absent (herdbook.py reads 0 for those)."""
        mean_kinship = gs.get_mean_kinship(self.genebank.id)

        self.assertEqual(set(mean_kinship), set(self.in_window))
        self.assertNotIn(self.stale, mean_kinship)

    def test_population_metrics_count_the_same_members(self):
        """Population metrics run on the same population as mean kinship."""
        metrics = gs.get_population_metrics(self.genebank.id)

        self.assertEqual(metrics["n_active"], len(self.in_window))

    def test_founder_statistics_loss_is_mean_kinship(self):
        """Diversitetsförlust = 1 - GD = mean MK over the members; founders counted if they contribute."""
        stats = gs.get_founder_statistics(self.genebank.id)
        mean_kinship = gs.get_mean_kinship(self.genebank.id)

        # Three unrelated founders: mean kinship incl. self = 0.5 / 3.
        self.assertAlmostEqual(stats["proportional_loss"], sum(mean_kinship.values()) / len(mean_kinship))
        self.assertAlmostEqual(stats["proportional_loss"], 0.5 / 3)
        # The stale individual is a founder without descendants among the members.
        self.assertEqual(stats["n_founders"], 3)
        self.assertEqual(stats["n_founders_total"], 4)

    def test_closing_a_round_moves_the_population(self):
        """A new closed round shifts the start date; stale members drop out."""
        self.assertEqual(set(gs.get_mean_kinship(self.genebank.id)), set(self.in_window))

        # The 2026 round closes: the window moves to 2026-01-01 and every
        # individual whose last event was in 2025 drops out.
        self._round(2026, date(2026, 3, 31))
        gs.snapshot(self.genebank.id)  # stale: starts the background rebuild
        ps.wait_for_builds(self.genebank.id, timeout=5)

        self.assertEqual(gs.get_mean_kinship(self.genebank.id), {})

    def test_moving_start_date_gives_a_new_snapshot(self):
        """The switch is picked up without a restart, not served from the old snapshot."""
        before = gs.snapshot(self.genebank.id)
        self.assertEqual(set(gs.get_mean_kinship(self.genebank.id)), set(self.in_window))
        self.assertIs(gs.snapshot(self.genebank.id), before)

        self._round(2026, date(2026, 3, 31))
        gs.snapshot(self.genebank.id)  # stale: starts the background rebuild
        ps.wait_for_builds(self.genebank.id, timeout=5)

        after = gs.snapshot(self.genebank.id)
        self.assertNotEqual(after.key, before.key)
        self.assertGreater(after.seq, before.seq)
        self.assertEqual(after.ref_ids, [])
        self.assertEqual(gs.get_mean_kinship(self.genebank.id), {})

    def test_new_tracking_row_bumps_the_version(self):
        """A new herd tracking row can change membership, so it bumps the genetics version."""
        before = db.read_genetics_version()

        individual = db.Individual.get(db.Individual.number == self.stale)
        ht_row("TRANSFER", individual=individual, herd=self.herd, herd_tracking_date=date(2025, 7, 1))

        self.assertGreater(db.read_genetics_version(), before)

    def test_void_bumps_the_version(self):
        """Voiding a row keeps the count and max id but can change membership."""
        individual = db.Individual.get(db.Individual.number == self.stale)
        row = ht_row("TRANSFER", individual=individual, herd=self.herd, herd_tracking_date=date(2025, 7, 1))
        user = da.register_user("void-tester", "pass")
        before = db.read_genetics_version()

        _void(row, user)

        self.assertGreater(db.read_genetics_version(), before)

    def test_snapshot_key_notices_a_future_row_becoming_current(self):
        """Same rows, but once today passes a future-dated row it starts to count."""
        today = date.today()
        individual = db.Individual.get(db.Individual.number == self.stale)
        ht_row("TRANSFER", individual=individual, herd=self.herd, herd_tracking_date=today + timedelta(days=10))

        class Later(date):
            @classmethod
            def today(cls):
                return today + timedelta(days=20)

        before = gs.snapshot(self.genebank.id)
        self.assertEqual(before.key[1], today)
        with patch("utils.genetics_service.date", Later):
            gs.snapshot(self.genebank.id)  # stale: starts the background rebuild
            ps.wait_for_builds(self.genebank.id, timeout=5)
            after = gs.snapshot(self.genebank.id)

        self.assertEqual(after.key[1], today + timedelta(days=20))
        self.assertEqual(after.key[0], before.key[0])
        self.assertIn(self.stale, after.ref_ids)

    def test_deactivating_a_herd_bumps_the_version(self):
        """Deactivating a herd drops its animals from the population, so it bumps the version."""
        before = db.read_genetics_version()

        self.herd.is_active = False
        self.herd.save()

        self.assertGreater(db.read_genetics_version(), before)

    def test_kinship_cache_follows_a_membership_change(self):
        """A warm reference matrix is recomputed when the genetics version moves."""
        self.assertEqual(set(gs.get_mean_kinship(self.genebank.id)), set(self.in_window))

        # The stale male is reported again and enters the reference population.
        stale = db.Individual.get(db.Individual.number == self.stale)
        ht_row("TRANSFER", individual=stale, herd=self.herd, herd_tracking_date=date(2025, 7, 1))
        gs.snapshot(self.genebank.id)  # stale: starts the background rebuild
        ps.wait_for_builds(self.genebank.id, timeout=5)

        metrics = gs.get_population_metrics(self.genebank.id)
        mean_kinship = gs.get_mean_kinship(self.genebank.id)

        self.assertEqual(metrics["n_active"], len(self.in_window) + 1)
        self.assertIsNotNone(metrics["expected_offspring_f"])
        self.assertEqual(set(mean_kinship), set(self.in_window) | {self.stale})

    def test_new_round_bumps_the_version(self):
        """Other workers see the start-date switch through the global genetics version."""
        before = db.read_genetics_version()

        self._round(2026, date(2026, 3, 31))

        self.assertGreater(db.read_genetics_version(), before)


class TestRecoverableCarriers(GeneticsPopulationTest):
    """Recovery candidates for a lost founder: plausibly alive, breedable non-members."""

    def setUp(self):
        super().setUp()
        self.genebank = db.Genebank.create(name="MK-genbank")
        self.herd = db.Herd.create(genebank=self.genebank, herd="MK1", herd_name="Aktiv", is_active=True)
        self._round(2025, date(2026, 3, 30))
        self._certificate = 9300

        # One reference member (unrelated founder) so the population is not empty.
        member = self._create("MK1-M", birth_date=None)
        ht_row("TRANSFER", individual=member, herd=self.herd, herd_tracking_date=date(2025, 6, 1))

        # Founder with no descendants among the members: "lost". It has no birth date.
        self.founder = self._create("MK1-FA", birth_date=None)

    def _create(self, number, birth_date, certificate=True, **kwargs):
        if birth_date is not None or kwargs.pop("child", False):
            kwargs["breeding"] = db.Breeding.create(
                breeding_herd_id=self.herd, father=self.founder, birth_date=birth_date
            )
        if certificate:
            self._certificate += 1
            kwargs.setdefault("certificate", str(self._certificate))
        return db.Individual.create(origin_herd=self.herd, number=number, **kwargs)

    def test_only_plausibly_alive_breedable_carriers_are_listed(self):
        today = date.today()
        young = today - timedelta(days=365)
        self._create("MK1-young", young)
        self._create("MK1-digital", young - timedelta(days=1), certificate=False, digital_certificate=4711)
        self._create("MK1-old", today - timedelta(days=MAX_RABBIT_AGE_DAYS + 30))
        self._create("MK1-nobirth", None, child=True)
        self._create("MK1-slaktad", young - timedelta(days=2), death_note="slaktad")
        self._create("MK1-dead", young - timedelta(days=3), death_date=today - timedelta(days=10))
        self._create("MK1-castrated", young - timedelta(days=4), castration_date=today - timedelta(days=30))
        self._create("MK1-uncert", young - timedelta(days=5), certificate=False)
        self._create("MK1-voided", young - timedelta(days=6), voided=True)

        result = {entry["founder_id"]: entry for entry in gs.get_founders_at_risk(self.genebank.id)}

        self.assertEqual(result["MK1-FA"]["risk_level"], "lost")
        self.assertEqual(set(result["MK1-FA"]["recoverable_carriers"]), {"MK1-young", "MK1-digital"})


def _snapshot_of(pedigree, genebank_id=4242):
    """A snapshot built straight from genetics Individuals; members are the is_active ones."""
    rows = [{"number": i.id, "sex": i.sex, "father_number": i.sire_id, "mother_number": i.dam_id} for i in pedigree]
    members = {i.id for i in pedigree if i.is_active}
    return ps.build_snapshot(genebank_id, rows, members, key=("test",), seq=1)


class TestGeneDropSeeding(GeneticsPopulationTest):
    """Gene drop results are reproducible per seed; only the default run is memoised on the snapshot."""

    PEDIGREE = [
        gs.Individual("A", None, None, is_active=False),
        gs.Individual("B", None, None, is_active=False),
        gs.Individual("C", "A", "B", is_active=True),
        gs.Individual("D", "A", "B", is_active=True),
    ]

    def test_only_the_default_run_is_memoized(self):
        """R039: a caller-chosen seed or iteration count must not add a snapshot memo entry per call."""
        snap = _snapshot_of(self.PEDIGREE)
        with (
            patch.object(gs, "snapshot", return_value=snap),
        ):
            first = gs.get_gene_drop_statistics(4242, n_iterations=10, seed=1)
            for seed in range(2, 6):
                gs.get_gene_drop_statistics(4242, n_iterations=10, seed=seed)
            again = gs.get_gene_drop_statistics(4242, n_iterations=10, seed=1)
            default = gs.get_gene_drop_statistics(4242)

        self.assertEqual(set(snap.derived), {"gene_drop_1000_None"}, "one memo entry per seed")
        self.assertEqual(again, first)  # a seed still reproduces its run
        self.assertIs(default, snap.derived["gene_drop_1000_None"])

    def test_priorities_use_a_fixed_seed(self):
        """Every worker computes the same priorities."""
        snap = _snapshot_of(self.PEDIGREE)
        with (
            patch.object(gs, "snapshot", return_value=snap),
            patch.object(gs, "gene_drop_simulation", wraps=gs.gene_drop_simulation) as simulation,
        ):
            gs.get_genetic_priorities(4242, n_iterations=10)

        self.assertEqual(simulation.call_args.kwargs["seed"], gs.PRIORITIES_SEED)


class TestReferenceKinshipComputedOnce(GeneticsPopulationTest):
    """A cold overview builds the reference kinship matrix once, with identical results."""

    PEDIGREE = [
        gs.Individual("A", None, None, is_active=False, sex="male"),
        gs.Individual("B", None, None, is_active=False, sex="female"),
        gs.Individual("C", "A", "B", is_active=True, sex="male"),
        gs.Individual("D", "A", "B", is_active=True, sex="female"),
        gs.Individual("E", None, None, is_active=True, sex="female"),
        gs.Individual("F", "C", "E", is_active=True, sex="male"),
    ]

    def test_population_metrics_and_founder_statistics_share_the_matrix(self):
        import utils.genetics as genetics

        snap = _snapshot_of(self.PEDIGREE, 4343)
        with (
            patch.object(gs, "snapshot", return_value=snap),
            patch.object(ps, "reference_block", wraps=ps.reference_block) as block_spy,
        ):
            metrics = gs.get_population_metrics(4343)
            stats = gs.get_founder_statistics(4343)
            mean_kinship = gs.get_mean_kinship(4343)
            calls = block_spy.call_count

        self.assertEqual(calls, 1)
        self.assertEqual(metrics, genetics.calculate_population_metrics(self.PEDIGREE))
        self.assertEqual(mean_kinship, genetics.calculate_mean_kinship(self.PEDIGREE))
        self.assertEqual(stats, genetics.calculate_founder_statistics(self.PEDIGREE))
