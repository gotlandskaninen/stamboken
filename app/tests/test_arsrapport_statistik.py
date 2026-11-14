#!/usr/bin/env python3
"""
Tests for utils.arsrapport_statistik: the yearly report's register statistics
per herd and breeding year. Synthetic herds and rabbits only.

isort:skip_file
"""

from datetime import date

import utils.database as db
from utils.arsrapport_statistik import Kanin, Statistik, innehav, statistik

from tests.database_test import DatabaseTest
from tests.ht_helpers import _void, count_queries, ht_row

YEAR = 2025
NEW_YEARS_EVE = date(YEAR, 12, 31)
NO_LITTERS = dict(kullar=0, kullar_med_ungar=0, ungar=0, levande_6v=0, kullar_okant_6v=0, avelshonor=0, avelshanar=0)


class ArsrapportStatistikTest(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.gotland, self.mellerud = self.genebanks
        self.g1 = db.Herd.create(genebank=self.gotland, herd="G9001", is_active=True)
        self.g2 = db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True)
        self.gx1 = db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.m2 = db.Herd.create(genebank=self.mellerud, herd="M9002", is_active=True)
        self._certificate = 9000

    def _rabbit(self, number, sex, *rows, certified=True, **fields):
        """A rabbit with herd-tracking rows (date, herd, kind); returns the individual."""
        if certified:
            self._certificate += 1
            fields["certificate"] = str(self._certificate)
        rabbit = db.Individual.create(origin_herd=rows[0][1], number=number, sex=sex, **fields)
        for day, herd, kind in rows:
            ht_row(kind, herd=herd, individual=rabbit, herd_tracking_date=day)
        return rabbit

    def _litter(self, herd, birth_date, size, size6w, mother=None, father=None):
        return db.Breeding.create(
            breeding_herd_id=herd,
            birth_date=birth_date,
            litter_size=size,
            litter_size6w=size6w,
            mother=mother,
            father=father,
        )

    def _attested(self, number, sex, herd, **fields):
        """A rabbit attested in `herd` on 31 December of the report year."""
        return self._rabbit(number, sex, (NEW_YEARS_EVE, herd, "ATTESTATION"), **fields)

    def test_litters_in_the_year_only(self):
        self._litter(self.g1, date(YEAR, 1, 1), 5, 4)
        self._litter(self.g1, date(YEAR, 12, 31), 3, 3)
        self._litter(self.g1, date(YEAR - 1, 12, 31), 7, 7)
        self._litter(self.g1, date(YEAR + 1, 1, 1), 6, 6)

        stats = statistik(self.gotland.id, YEAR)[self.g1.id]
        self.assertEqual((stats.kullar, stats.ungar, stats.levande_6v), (2, 8, 7))

    def test_unknown_six_week_count_is_unknown_not_zero(self):
        self._litter(self.g1, date(YEAR, 3, 1), 5, 4)
        self._litter(self.g1, date(YEAR, 6, 1), 6, None)

        g1 = statistik(self.gotland.id, YEAR)[self.g1.id]
        self.assertEqual((g1.kullar, g1.ungar, g1.levande_6v, g1.kullar_okant_6v), (2, 11, None, 1))

    def test_unknown_litter_size_is_unknown_not_zero(self):
        self._litter(self.g1, date(YEAR, 3, 1), 5, 4)
        self._litter(self.g1, date(YEAR, 6, 1), None, 3)
        self._litter(self.g1, date(YEAR, 8, 1), 0, 0)

        g1 = statistik(self.gotland.id, YEAR)[self.g1.id]
        self.assertEqual((g1.kullar, g1.ungar, g1.levande_6v), (3, None, 7))
        # The support condition "a litter with at least one kit born" still has its answer.
        self.assertEqual(g1.kullar_med_ungar, 1)

    def test_breeding_animals_are_distinct_parents_castrated_too(self):
        mother = self._attested("G9001-2401", "female", self.g1)
        other_mother = self._attested("G9001-2402", "female", self.g1)
        father = self._attested("G9001-2403", "male", self.g1)
        castrated = self._attested("G9001-2404", "male", self.g1, castration_date=date(YEAR, 9, 1))
        self._litter(self.g1, date(YEAR, 3, 1), 5, 4, mother, father)
        self._litter(self.g1, date(YEAR, 7, 1), 4, 4, mother, castrated)
        self._litter(self.g1, date(YEAR - 1, 7, 1), 4, 4, other_mother, father)

        stats = statistik(self.gotland.id, YEAR)[self.g1.id]
        self.assertEqual((stats.avelshonor, stats.avelshanar), (1, 2))

    def test_attested_on_new_years_eve_counts(self):
        self._attested("G9001-2501", "female", self.g1)
        self._rabbit(
            "G9001-2502",
            "male",
            (date(YEAR, 3, 1), self.g1, "BIRTH"),
            (NEW_YEARS_EVE, self.g1, "ATTESTATION"),
        )

        self.assertEqual(
            statistik(self.gotland.id, YEAR)[self.g1.id], Statistik(**NO_LITTERS, honor=1, hanar=1, okant_kon=0)
        )

    def test_rabbit_nobody_reported_is_not_counted(self):
        self._attested("G9001-2503", "female", self.g1)
        # The register still expects these in G9001 (the 5.2 list), but that is not a holding.
        self._rabbit("G9001-2401", "female", (date(YEAR - 1, 12, 31), self.g1, "ATTESTATION"))
        self._rabbit("G9001-2504", "female", (date(YEAR, 3, 1), self.g1, "BIRTH"))
        # A later CORRECTION is not a life sign.
        self._rabbit(
            "G9001-2402",
            "female",
            (date(YEAR - 1, 12, 31), self.g1, "ATTESTATION"),
            (date(YEAR + 1, 2, 1), self.g1, "CORRECTION"),
        )

        self.assertEqual(statistik(self.gotland.id, YEAR)[self.g1.id].honor, 1)

    def test_voided_rows_are_ignored(self):
        rabbit = self._rabbit("G9001-2505", "female", (date(YEAR, 3, 1), self.g1, "BIRTH"))
        transfer = ht_row(
            "TRANSFER", from_herd=self.g1, herd=self.g2, individual=rabbit, herd_tracking_date=date(YEAR, 6, 1)
        )
        _void(transfer, self.manager)
        ht_row("ATTESTATION", herd=self.g1, individual=rabbit, herd_tracking_date=NEW_YEARS_EVE)
        # Its only proof is a voided attestation.
        unproven = self._rabbit("G9001-2506", "female", (date(YEAR, 3, 1), self.g1, "BIRTH"))
        _void(ht_row("ATTESTATION", herd=self.g1, individual=unproven, herd_tracking_date=NEW_YEARS_EVE), self.manager)

        stats = statistik(self.gotland.id, YEAR)
        self.assertEqual(stats[self.g1.id].honor, 1)
        self.assertNotIn(self.g2.id, stats)

    def test_sold_before_new_years_eve_counts_with_the_buyer(self):
        self._rabbit(
            "G9001-2402",
            "male",
            (date(YEAR - 1, 12, 31), self.g1, "ATTESTATION"),
            (date(YEAR, 8, 14), self.g2, "TRANSFER"),
            (NEW_YEARS_EVE, self.g2, "ATTESTATION"),
        )

        stats = statistik(self.gotland.id, YEAR)
        self.assertEqual(stats[self.g2.id].hanar, 1)
        self.assertNotIn(self.g1.id, stats)

    def test_sold_in_january_counts_with_the_seller(self):
        self._rabbit(
            "G9001-2507",
            "male",
            (date(YEAR, 3, 1), self.g1, "BIRTH"),
            (date(YEAR + 1, 1, 3), self.g2, "TRANSFER"),
        )

        stats = statistik(self.gotland.id, YEAR)
        self.assertEqual(stats[self.g1.id].hanar, 1)
        self.assertNotIn(self.g2.id, stats)

    def test_dead_on_or_before_new_years_eve_is_not_counted(self):
        self._attested("G9001-2508", "female", self.g1, death_date=NEW_YEARS_EVE)
        self._attested("G9001-2509", "female", self.g1, death_date=date(YEAR, 5, 1))
        self._attested("G9001-2510", "female", self.g1, death_date=date(YEAR + 1, 1, 1))

        self.assertEqual(statistik(self.gotland.id, YEAR)[self.g1.id].honor, 1)

    def test_death_note_without_date(self):
        """Read as reference_population does: dead from the note's year, else from birth + max age."""

        def born(year):
            return db.Breeding.create(breeding_herd_id=self.g2, birth_date=date(year, 5, 1))

        self._attested("G9001-2511", "female", self.g1, death_note=f"{YEAR} slakt")
        self._attested("G9001-2512", "female", self.g1, death_note="död")
        self._attested("G9001-2513", "female", self.g1, death_note="död", breeding=born(YEAR - 9))
        self._attested("G9001-2514", "female", self.g1, death_note=f"{YEAR + 1} slakt")
        self._attested("G9001-2515", "female", self.g1, death_note="död", breeding=born(YEAR - 1))
        self._attested("G9001-2516", "female", self.g1, death_note="")

        self.assertEqual(statistik(self.gotland.id, YEAR)[self.g1.id].honor, 3)

    def test_certificate_required(self):
        self._attested("G9001-2517", "female", self.g1)
        self._attested("G9001-2518", "female", self.g1, certified=False)
        self._attested("G9001-2519", "female", self.g1, certified=False, certificate="")
        self._attested("G9001-2520", "female", self.g1, certified=False, digital_certificate=9500)

        self.assertEqual(statistik(self.gotland.id, YEAR)[self.g1.id].honor, 2)

    def test_unknown_sex_and_castrated(self):
        female = self._attested("G9001-2521", "female", self.g1, castration_date=date(YEAR, 2, 1))
        castrated = self._attested("G9001-2522", "male", self.g1, castration_date=NEW_YEARS_EVE)
        castrated_later = self._attested("G9001-2523", "male", self.g1, castration_date=date(YEAR + 1, 1, 2))
        eunuch = self._attested("G9001-2524", "eunuch", self.g1)
        unknown = self._attested("G9001-2525", None, self.g1)

        stats = statistik(self.gotland.id, YEAR)[self.g1.id]
        self.assertEqual((stats.honor, stats.hanar, stats.okant_kon), (1, 3, 1))
        self.assertCountEqual(
            innehav(self.gotland.id, YEAR)[self.g1.id],
            [
                Kanin(female.id, "female", True),
                Kanin(castrated.id, "male", True),
                Kanin(castrated_later.id, "male", False),
                Kanin(eunuch.id, "male", True),
                Kanin(unknown.id, None, False),
            ],
        )

    def test_only_herds_with_litters_or_holdings_active_or_not(self):
        ended = db.Herd.create(genebank=self.gotland, herd="G9003", is_active=False)
        ended_empty = db.Herd.create(genebank=self.gotland, herd="G9004", is_active=False)
        self._litter(ended, date(YEAR, 4, 1), 3, 3)
        self._attested("G9002-2501", "female", self.g2)
        self._attested("G9002-2502", "male", self.g2)

        stats = statistik(self.gotland.id, YEAR)
        self.assertEqual(stats[self.g2.id], Statistik(**NO_LITTERS, honor=1, hanar=1, okant_kon=0))
        self.assertEqual(stats[ended.id].kullar, 1)
        self.assertNotIn(self.g1.id, stats)
        self.assertNotIn(ended_empty.id, stats)

    def test_genebanks_are_kept_apart(self):
        mother = self._attested("M9002-2501", "female", self.m2)
        self._litter(self.m2, date(YEAR, 4, 1), 6, 5, mother)
        self._litter(self.g1, date(YEAR, 4, 1), 3, 3)

        gotland = statistik(self.gotland.id, YEAR)
        mellerud = statistik(self.mellerud.id, YEAR)
        self.assertNotIn(self.m2.id, gotland)
        self.assertNotIn(self.g1.id, mellerud)
        self.assertEqual(
            mellerud[self.m2.id],
            Statistik(
                kullar=1,
                kullar_med_ungar=1,
                ungar=6,
                levande_6v=5,
                kullar_okant_6v=0,
                avelshonor=1,
                avelshanar=0,
                honor=1,
                hanar=0,
                okant_kon=0,
            ),
        )
        self.assertEqual(
            gotland[self.g1.id],
            Statistik(
                kullar=1,
                kullar_med_ungar=1,
                ungar=3,
                levande_6v=3,
                kullar_okant_6v=0,
                avelshonor=0,
                avelshanar=0,
                honor=0,
                hanar=0,
                okant_kon=0,
            ),
        )

    def test_sold_outside_genebank_is_not_a_herd(self):
        self._rabbit(
            "G9001-2526",
            "female",
            (date(YEAR - 1, 12, 31), self.g1, "ATTESTATION"),
            (date(YEAR, 5, 1), self.gx1, "TRANSFER"),
            (NEW_YEARS_EVE, self.gx1, "ATTESTATION"),
        )
        self._litter(self.gx1, date(YEAR, 4, 1), 3, 3)

        stats = statistik(self.gotland.id, YEAR)
        self.assertNotIn(self.gx1.id, stats)
        self.assertNotIn(self.g1.id, stats)

    def test_two_queries(self):
        self._attested("G9001-2527", "female", self.g1)
        self._litter(self.g1, date(YEAR, 4, 1), 3, 3)
        with count_queries() as queries:
            statistik(self.gotland.id, YEAR)
        self.assertEqual(queries["n"], 2)
