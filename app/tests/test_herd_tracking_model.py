"""Ordering within a day and projections — model-level readers."""

import unittest
from datetime import date, datetime, timedelta

import utils.database as db

from tests.database_test import _USE_POSTGRES, DatabaseTest
from tests.ht_helpers import _void, ht_row, make_individual


class TestHerdTrackingReaders(DatabaseTest):
    def setUp(self):
        super().setUp()
        for herd in self.herds:
            herd.is_active = True
            herd.save()
        self.g1, self.g2 = self.herds[0], self.herds[1]
        self.gx1 = db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför", is_active=True)
        self.today = date.today()

    def test_birth_sorts_first_within_a_day(self):
        """A replacing BIRTH (higher id) must not hide a same-day TRANSFER."""
        ind = make_individual(self.g1, "G1-2401", date(2024, 3, 1))
        sale = ht_row("TRANSFER", individual=ind, herd=self.g2, from_herd=self.g1, herd_tracking_date=date(2024, 3, 1))
        birth = ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=date(2024, 3, 1))
        self.assertGreater(birth.id, sale.id)
        self.assertEqual(db.current_holder_row(ind.id).id, sale.id)
        self.assertEqual(db.Individual.get_by_id(ind.id).current_herd.herd, "G2")
        ordered = list(db.HerdTracking.select().where(db.HerdTracking.individual == ind).order_by(*db.ht_order_desc()))
        self.assertEqual([r.id for r in ordered], [sale.id, birth.id])
        self.assertEqual(sorted(ordered, key=db.ht_sort_key), list(reversed(ordered)))

    def test_voided_rows_are_ignored(self):
        ind = make_individual(self.g1, "G1-2402", date(2024, 3, 1))
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=date(2024, 3, 1))
        sale = ht_row("TRANSFER", individual=ind, herd=self.g2, from_herd=self.g1, herd_tracking_date=date(2024, 6, 1))
        _void(sale, self.manager)
        self.assertEqual(db.Individual.get_by_id(ind.id).current_herd.herd, "G1")
        self.assertEqual(db.current_holder_row(ind.id, as_of=date(2024, 7, 1)).herd_id, self.g1.id)

    def test_active_rule_window_life_signs_and_outside_herds(self):
        ind = make_individual(self.g1, "G1-2403", self.today - timedelta(days=800))
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=self.today - timedelta(days=800))
        report = ht_row(
            "ATTESTATION", individual=ind, herd=self.g1, herd_tracking_date=self.today - timedelta(days=394)
        )
        self.assertTrue(db.Individual.get_by_id(ind.id).active)
        db.HerdTracking.update(herd_tracking_date=self.today - timedelta(days=396)).where(
            db.HerdTracking.id == report.id
        ).execute()
        self.assertFalse(db.Individual.get_by_id(ind.id).active)
        # A CORRECTION is not a life sign.
        ht_row("CORRECTION", individual=ind, herd=self.g2, herd_tracking_date=self.today - timedelta(days=10))
        self.assertFalse(db.Individual.get_by_id(ind.id).active)
        self.assertEqual(db.latest_life_sign_date(ind.id), self.today - timedelta(days=396))

    def test_outside_genebank_holder_is_inactive_even_if_herd_is_active(self):
        ind = make_individual(self.g1, "G1-2404", self.today - timedelta(days=200))
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=self.today - timedelta(days=200))
        ht_row("TRANSFER", individual=ind, herd=self.gx1, from_herd=self.g1, herd_tracking_date=self.today)
        self.assertFalse(db.Individual.get_by_id(ind.id).active)

    def test_v1_as_dict_filters_voids_keeps_shape_and_server_order(self):
        ind = make_individual(self.g1, "G1-2405", date(2024, 3, 1))
        sale = ht_row("TRANSFER", individual=ind, herd=self.g2, from_herd=self.g1, herd_tracking_date=date(2024, 3, 1))
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=date(2024, 3, 1))
        undone = ht_row(
            "TRANSFER", individual=ind, herd=self.g1, from_herd=self.g2, herd_tracking_date=date(2024, 9, 1)
        )
        _void(undone, self.manager)
        data = db.Individual.get_by_id(ind.id).as_dict()
        self.assertEqual([t["herd"] for t in data["herd_tracking"]], ["G2", "G1"])
        self.assertEqual(set(data["herd_tracking"][0]), {"herd_id", "herd", "herd_name", "date", "kind"})
        self.assertEqual(data["herd_tracking"][0]["herd"], data["herd"]["herd"])
        self.assertEqual(data["herd_tracking"][0]["herd_id"], sale.herd_id)

    def _bulk_scenarios(self):
        """Rabbits probing the FILTER (CORRECTION), same-day ties and voids; returns ids by name."""
        t = self.today
        corr = make_individual(self.g1, "G1-2410", t - timedelta(days=900))
        ht_row("BIRTH", individual=corr, herd=self.g1, herd_tracking_date=t - timedelta(days=900))
        ht_row("ATTESTATION", individual=corr, herd=self.g1, herd_tracking_date=t - timedelta(days=100))
        ht_row("CORRECTION", individual=corr, herd=self.g2, herd_tracking_date=t - timedelta(days=5))
        tie = make_individual(self.g1, "G1-2411", t - timedelta(days=300))
        ht_row("TRANSFER", individual=tie, herd=self.g2, from_herd=self.g1, herd_tracking_date=t - timedelta(days=300))
        ht_row("BIRTH", individual=tie, herd=self.g1, herd_tracking_date=t - timedelta(days=300))
        voided = make_individual(self.g1, "G1-2412", t - timedelta(days=300))
        ht_row("BIRTH", individual=voided, herd=self.g1, herd_tracking_date=t - timedelta(days=300))
        sale = ht_row("TRANSFER", individual=voided, herd=self.g2, from_herd=self.g1, herd_tracking_date=t)
        _void(sale, self.manager)
        return {"corr": corr.id, "tie": tie.id, "voided": voided.id}

    def _assert_bulk_matches_scalar_readers(self, rows, ids):
        for ind_id in ids.values():
            holder = db.current_holder_row(ind_id)
            self.assertEqual(rows[ind_id]["herd"], holder.herd_id)
            self.assertEqual(rows[ind_id]["ht_date"], holder.herd_tracking_date)
            self.assertEqual(rows[ind_id]["life_sign_date"], db.latest_life_sign_date(ind_id))
        # (a) CORRECTION is the holder row but not a life sign
        corr = rows[ids["corr"]]
        self.assertLess(corr["life_sign_date"], corr["ht_date"])
        self.assertEqual(corr["herd"], self.g2.id)
        # (b) same-day TRANSFER then higher-id BIRTH: BIRTH sorts first in the day, so TRANSFER holds
        self.assertEqual(rows[ids["tie"]]["herd"], self.g2.id)
        # (c) the voided latest row is ignored
        self.assertEqual(rows[ids["voided"]]["herd"], self.g1.id)

    def test_latest_per_individual_agrees_with_current_holder_row(self):
        ids = self._bulk_scenarios()
        latest = db.latest_ht_per_individual().alias("latest_ht")
        rows = {
            r["i_id"]: r
            for r in db.Individual.select(latest.c.i_id, latest.c.herd, latest.c.ht_date, latest.c.life_sign_date)
            .join(latest, on=(db.Individual.id == latest.c.i_id))
            .where(latest.c.rank == 1)
            .dicts()
        }
        for ind in self.individuals + self.parents:
            holder = db.current_holder_row(ind.id)
            if holder is None:
                self.assertNotIn(ind.id, rows)
                continue
            self.assertEqual(rows[ind.id]["herd"], holder.herd_id)
            self.assertEqual(rows[ind.id]["life_sign_date"], db.latest_life_sign_date(ind.id))
        self._assert_bulk_matches_scalar_readers(rows, ids)

    @unittest.skipUnless(_USE_POSTGRES, "DISTINCT ON is PostgreSQL-only")
    def test_distinct_on_variant_matches_rank_variant(self):
        ids = self._bulk_scenarios()
        cols = ("i_id", "herd", "ht_date", "life_sign_date")
        ranked = db.latest_ht_per_individual().alias("ranked")
        distinct = db.latest_ht_per_individual(distinct_on=True).alias("distinct_on")
        by_rank = {
            r["i_id"]: {c: r[c] for c in cols}
            for r in db.Individual.select(*[ranked.c[c] for c in cols])
            .join(ranked, on=(db.Individual.id == ranked.c.i_id))
            .where(ranked.c.rank == 1)
            .dicts()
        }
        by_distinct = {
            r["i_id"]: {c: r[c] for c in cols}
            for r in db.Individual.select(*[distinct.c[c] for c in cols])
            .join(distinct, on=(db.Individual.id == distinct.c.i_id))
            .dicts()
        }
        self.assertEqual(by_rank, by_distinct)
        self._assert_bulk_matches_scalar_readers(by_distinct, ids)

    def test_coerce_date(self):
        self.assertEqual(db.coerce_date(datetime(2024, 1, 2, 13, 0)), date(2024, 1, 2))
        self.assertEqual(db.coerce_date("2024-01-02"), date(2024, 1, 2))
        self.assertEqual(db.coerce_date(date(2024, 1, 2)), date(2024, 1, 2))
        with self.assertRaises(TypeError):
            db.coerce_date(5)
