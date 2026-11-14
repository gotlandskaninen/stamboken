#!/usr/bin/env python3
"""
Tests for utils.arsrapport_statistik: the yearly report's register statistics
per herd and breeding year. Synthetic herds and rabbits only.

isort:skip_file
"""

from datetime import date

import utils.database as db
from utils.arsrapport_statistik import Statistik, statistik

from tests.database_test import DatabaseTest
from tests.ht_helpers import _void, count_queries, ht_row

YEAR = 2025
NEW_YEARS_EVE = date(YEAR, 12, 31)
EMPTY = Statistik(0, 0, 0, 0, 0, 0, 0, 0)


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
        """A rabbit attested in `herd` on 31 December the year before."""
        return self._rabbit(number, sex, (date(YEAR - 1, 12, 31), herd, "ATTESTATION"), **fields)

    def test_litters_in_the_year_only(self):
        self._litter(self.g1, date(YEAR, 1, 1), 5, 4)
        self._litter(self.g1, date(YEAR, 12, 31), 3, 3)
        self._litter(self.g1, date(YEAR - 1, 12, 31), 7, 7)
        self._litter(self.g1, date(YEAR + 1, 1, 1), 6, 6)

        stats = statistik(self.gotland.id, YEAR)[self.g1.id]
        self.assertEqual((stats.kullar, stats.ungar, stats.levande_6v), (2, 8, 7))

    def test_unknown_six_week_count_is_not_zero(self):
        self._litter(self.g1, date(YEAR, 3, 1), 5, 4)
        self._litter(self.g1, date(YEAR, 6, 1), 6, None)
        self._litter(self.g2, date(YEAR, 6, 1), 6, None)

        stats = statistik(self.gotland.id, YEAR)
        g1, g2 = stats[self.g1.id], stats[self.g2.id]
        self.assertEqual((g1.kullar, g1.ungar, g1.levande_6v, g1.kullar_okant_6v), (2, 11, 4, 1))
        # Only unknown: no known survivors, and the unknown litter is still reported.
        self.assertEqual((g2.levande_6v, g2.kullar_okant_6v), (0, 1))

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

    def test_voided_transfer_is_ignored(self):
        rabbit = self._rabbit("G9001-2501", "female", (date(YEAR, 3, 1), self.g1, "BIRTH"))
        transfer = ht_row(
            "TRANSFER", from_herd=self.g1, herd=self.g2, individual=rabbit, herd_tracking_date=date(YEAR, 6, 1)
        )
        _void(transfer, self.manager)

        stats = statistik(self.gotland.id, YEAR)
        self.assertEqual(stats[self.g1.id].honor, 1)
        self.assertEqual(stats[self.g2.id].honor, 0)

    def test_sold_before_new_years_eve_counts_with_the_buyer(self):
        self._rabbit(
            "G9001-2402",
            "male",
            (date(YEAR - 1, 12, 31), self.g1, "ATTESTATION"),
            (date(YEAR, 8, 14), self.g2, "TRANSFER"),
        )

        stats = statistik(self.gotland.id, YEAR)
        self.assertEqual((stats[self.g1.id].hanar, stats[self.g2.id].hanar), (0, 1))

    def test_sold_in_january_counts_with_the_seller(self):
        self._rabbit(
            "G9001-2403",
            "male",
            (date(YEAR - 1, 12, 31), self.g1, "ATTESTATION"),
            (date(YEAR + 1, 1, 3), self.g2, "TRANSFER"),
        )

        stats = statistik(self.gotland.id, YEAR)
        self.assertEqual((stats[self.g1.id].hanar, stats[self.g2.id].hanar), (1, 0))

    def test_dead_on_or_before_new_years_eve_is_not_counted(self):
        self._attested("G9001-2404", "female", self.g1, death_date=NEW_YEARS_EVE)
        self._attested("G9001-2405", "female", self.g1, death_date=date(YEAR, 5, 1))
        self._attested("G9001-2406", "female", self.g1, death_date=date(YEAR + 1, 1, 1))

        self.assertEqual(statistik(self.gotland.id, YEAR)[self.g1.id].honor, 1)

    def test_old_rabbit_without_life_sign_is_not_counted(self):
        self._attested("G9001-2407", "female", self.g1)
        self._rabbit("G9001-2301", "female", (date(YEAR - 2, 12, 31), self.g1, "ATTESTATION"))
        # A CORRECTION moves the holder but is not a life sign.
        self._rabbit(
            "G9001-2302",
            "female",
            (date(YEAR - 2, 12, 31), self.g2, "ATTESTATION"),
            (date(YEAR, 4, 1), self.g1, "CORRECTION"),
        )

        self.assertEqual(statistik(self.gotland.id, YEAR)[self.g1.id].honor, 1)

    def test_certificate_required_and_castrated_counted(self):
        self._attested("G9001-2408", "female", self.g1, certified=False)
        self._attested("G9001-2409", "male", self.g1, castration_date=date(YEAR, 2, 1))
        self._attested("G9001-2410", "female", self.g1, certified=False, digital_certificate=9500)

        stats = statistik(self.gotland.id, YEAR)[self.g1.id]
        self.assertEqual((stats.honor, stats.hanar), (1, 1))

    def test_genebanks_are_kept_apart(self):
        mother = self._attested("M9002-2401", "female", self.m2)
        self._litter(self.m2, date(YEAR, 4, 1), 6, 5, mother)
        self._litter(self.g1, date(YEAR, 4, 1), 3, 3)

        gotland = statistik(self.gotland.id, YEAR)
        mellerud = statistik(self.mellerud.id, YEAR)
        self.assertNotIn(self.m2.id, gotland)
        self.assertNotIn(self.g1.id, mellerud)
        self.assertEqual(mellerud[self.m2.id], Statistik(1, 6, 5, 0, 1, 0, 1, 0))
        self.assertEqual(gotland[self.g1.id], Statistik(1, 3, 3, 0, 0, 0, 0, 0))

    def test_herd_without_litters(self):
        self._attested("G9002-2401", "female", self.g2)
        self._attested("G9002-2402", "male", self.g2)

        stats = statistik(self.gotland.id, YEAR)
        self.assertEqual(stats[self.g2.id], Statistik(0, 0, 0, 0, 0, 0, 1, 1))
        self.assertEqual(stats[self.g1.id], EMPTY)

    def test_sold_outside_genebank_is_not_a_herd(self):
        self._rabbit(
            "G9001-2411",
            "female",
            (date(YEAR - 1, 12, 31), self.g1, "ATTESTATION"),
            (date(YEAR, 5, 1), self.gx1, "TRANSFER"),
        )

        stats = statistik(self.gotland.id, YEAR)
        self.assertNotIn(self.gx1.id, stats)
        self.assertEqual(stats[self.g1.id].honor, 0)

    def test_two_queries(self):
        with count_queries() as queries:
            statistik(self.gotland.id, YEAR)
        self.assertEqual(queries["n"], 2)
