"""Every reader filters voids, shares one order, and agrees on the holder."""

from datetime import date, timedelta

import utils.data_access as da
import utils.database as db
from blueprints.testbreed_v2 import _current_genebanks
from utils import genetics_service
from utils import reference_population as rp

from tests.database_test import DatabaseTest
from tests.ht_helpers import _void, count_queries, ht_row, make_individual


class TestReadersAgree(DatabaseTest):
    def setUp(self):
        super().setUp()
        for herd in self.herds:
            herd.is_active = True
            herd.save()
        self.g1, self.g2 = self.herds[0], self.herds[1]
        self.gx1 = db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför", is_active=True)
        self.recent = date.today() - timedelta(days=20)
        self.gb = self.genebanks[0].id

    def _same_day_replaced_birth(self, number):
        """BIRTH + same-day TRANSFER where the BIRTH has the higher id (a replacement)."""
        ind = make_individual(self.g1, number, self.recent)
        ht_row("TRANSFER", individual=ind, herd=self.g2, from_herd=self.g1, herd_tracking_date=self.recent)
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=self.recent)
        return ind

    def test_same_day_all_readers_say_buyer(self):
        ind = self._same_day_replaced_birth("G1-2501")
        self.assertEqual(db.current_holder_row(ind.id).herd.herd, "G2")
        listed = {i["number"]: i for i in da.get_individuals(self.gb, self.admin.uuid)}
        self.assertEqual(listed["G1-2501"]["herd"]["herd"], "G2")
        page = da.get_paginated_individuals(self.admin.uuid, per_page=200, genebank_id=self.gb, search="G1-2501")
        self.assertEqual([i["herd"] for i in page["items"]], ["G2"])
        self.assertIn("G1-2501", [i["number"] for i in da.get_herd("G2", self.admin.uuid)["individuals"]])
        self.assertNotIn("G1-2501", [i["number"] for i in da.get_herd("G1", self.admin.uuid)["individuals"]])
        self.assertTrue(da.was_in_herd_at_date(ind.id, self.g2.id, self.recent))
        self.assertFalse(da.was_in_herd_at_date(ind.id, self.g1.id, self.recent))
        self.assertIn("G1-2501", genetics_service.reference_population_numbers(self.gb, self.recent))

    def test_v1_first_row_is_the_current_herd_everywhere(self):
        """Review Focus 3 — legacy reads herd_tracking[0].herd as the current herd."""
        replaced = self._same_day_replaced_birth("G1-2502")
        undone = make_individual(self.g1, "G1-2503", self.recent - timedelta(days=60))
        ht_row("BIRTH", individual=undone, herd=self.g1, herd_tracking_date=self.recent - timedelta(days=60))
        _void(
            ht_row("TRANSFER", individual=undone, herd=self.g2, from_herd=self.g1, herd_tracking_date=self.recent),
            self.manager,
        )
        for number in ("G1-2502", "G1-2503"):
            data = db.Individual.get(db.Individual.number == number).as_dict()
            self.assertEqual(data["herd_tracking"][0]["herd"], data["herd"]["herd"], number)
        for herd_code in ("G1", "G2"):
            for item in da.get_herd(herd_code, self.admin.uuid)["individuals"]:
                if item["number"] in ("G1-2502", "G1-2503"):
                    self.assertEqual(item["herd_tracking"][0]["herd"], item["herd"]["herd"], item["number"])
                    self.assertTrue(
                        all(set(t) == {"herd_id", "herd", "herd_name", "date", "kind"} for t in item["herd_tracking"])
                    )
        self.assertEqual(replaced.current_herd.herd, "G2")
        listed = {i["number"]: i for i in da.get_individuals(self.gb, self.admin.uuid)}
        self.assertEqual(listed["G1-2503"]["herd"]["herd"], "G1")

    def test_rabbit_without_active_rows_falls_back_to_origin_herd_everywhere(self):
        """A migrated rabbit with no BIRTH whose only row is voided stays listed, in its origin herd."""
        ind = make_individual(self.g1, "G1-2504", self.recent - timedelta(days=60))
        _void(
            ht_row("TRANSFER", individual=ind, herd=self.g2, from_herd=self.g1, herd_tracking_date=self.recent),
            self.manager,
        )
        self.assertEqual(ind.as_dict()["herd"]["herd"], "G1")
        page = da.get_paginated_individuals(self.admin.uuid, per_page=200, genebank_id=self.gb, search="G1-2504")
        self.assertEqual([i["herd"] for i in page["items"]], ["G1"])
        listed = {i["number"]: i for i in da.get_individuals(self.gb, self.admin.uuid)}
        self.assertIn("G1-2504", listed, "legacy genebank list keeps the rabbit")
        self.assertEqual(listed["G1-2504"]["herd"]["herd"], "G1")
        self.assertFalse(listed["G1-2504"]["is_active"], "no life sign: inactive")
        self.assertIn("G1-2504", [i["number"] for i in da.get_herd("G1", self.admin.uuid)["individuals"]])
        self.assertNotIn("G1-2504", [i["number"] for i in da.get_herd("G2", self.admin.uuid)["individuals"]])

    def test_explorer_historical_herd_ignores_voided_rows(self):
        ind = make_individual(self.g1, "G1-2504", self.recent - timedelta(days=60))
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=self.recent - timedelta(days=60))
        _void(
            ht_row("TRANSFER", individual=ind, herd=self.g2, from_herd=self.g1, herd_tracking_date=self.recent),
            self.manager,
        )
        page = da.get_paginated_individuals(
            self.admin.uuid, per_page=200, genebank_id=self.gb, herd_id="G2", include_historical=True
        )
        self.assertNotIn("G1-2504", [i["number"] for i in page["items"]])

    def test_outside_holder_is_inactive_in_lists_and_population(self):
        ind = make_individual(self.g1, "G1-2505", self.recent - timedelta(days=60))
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=self.recent - timedelta(days=60))
        ht_row("TRANSFER", individual=ind, herd=self.gx1, from_herd=self.g1, herd_tracking_date=self.recent)
        listed = {i["number"]: i for i in da.get_individuals(self.gb, self.admin.uuid)}
        self.assertFalse(listed["G1-2505"]["is_active"])
        page = da.get_paginated_individuals(self.admin.uuid, per_page=200, genebank_id=self.gb, status="active")
        self.assertNotIn("G1-2505", [i["number"] for i in page["items"]])
        self.assertNotIn("G1-2505", genetics_service.reference_population_numbers(self.gb, self.recent))

    def test_genetics_presence_ignores_departures_and_voids(self):
        target = date(2023, 12, 30)
        left = make_individual(self.g1, "G1-2306", date(2023, 1, 1))
        ht_row("BIRTH", individual=left, herd=self.g1, herd_tracking_date=date(2023, 1, 1))
        ht_row("TRANSFER", individual=left, herd=self.gx1, from_herd=self.g1, herd_tracking_date=date(2023, 6, 1))
        voided = make_individual(self.g1, "G1-2307", date(2021, 1, 1))
        ht_row("BIRTH", individual=voided, herd=self.g1, herd_tracking_date=date(2021, 1, 1))
        _void(ht_row("ATTESTATION", individual=voided, herd=self.g1, herd_tracking_date=date(2023, 3, 1)), self.manager)
        stayed = make_individual(self.g1, "G1-2308", date(2023, 1, 1))
        ht_row("BIRTH", individual=stayed, herd=self.g1, herd_tracking_date=date(2023, 1, 1))
        active = rp.members(self.gb, start=date(target.year, 1, 1), as_of=target, live=False)
        self.assertNotIn("G1-2306", active)
        self.assertNotIn("G1-2307", active)
        self.assertIn("G1-2308", active)

    def test_a_correction_is_not_a_life_sign_for_genetics(self):
        """An old life sign + a recent CORRECTION is neither referenced nor present."""
        stale = make_individual(self.g1, "G1-2309", date(2021, 1, 1))
        ht_row("BIRTH", individual=stale, herd=self.g1, herd_tracking_date=date(2021, 1, 1))
        ht_row("CORRECTION", individual=stale, herd=self.g2, from_herd=self.g1, herd_tracking_date=self.recent)
        self.assertNotIn("G1-2309", genetics_service.reference_population_numbers(self.gb, self.recent))
        target = date(2023, 12, 30)
        old = make_individual(self.g1, "G1-2310", date(2021, 1, 1))
        ht_row("BIRTH", individual=old, herd=self.g1, herd_tracking_date=date(2021, 1, 1))
        ht_row("CORRECTION", individual=old, herd=self.g2, from_herd=self.g1, herd_tracking_date=date(2023, 6, 1))
        active = rp.members(self.gb, start=date(target.year, 1, 1), as_of=target, live=False)
        self.assertNotIn("G1-2310", active)

    def test_fresh_life_sign_still_counts_after_a_correction(self):
        """Freshness from the life sign, holder from the latest row of any kind (here: a CORRECTION to G2)."""
        ind = make_individual(self.g1, "G1-2311", self.recent - timedelta(days=10))
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=self.recent - timedelta(days=10))
        ht_row("CORRECTION", individual=ind, herd=self.g2, from_herd=self.g1, herd_tracking_date=self.recent)
        start = self.recent - timedelta(days=30)
        self.assertIn("G1-2311", genetics_service.reference_population_numbers(self.gb, start))

    def test_provparning_visibility_ignores_voided_moves(self):
        ind = make_individual(self.g1, "G1-2506", self.recent - timedelta(days=60))
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=self.recent - timedelta(days=60))
        _void(
            ht_row("TRANSFER", individual=ind, herd=self.herds[2], from_herd=self.g1, herd_tracking_date=self.recent),
            self.manager,
        )
        self.assertEqual(_current_genebanks([ind.id]), {ind.id: self.genebanks[0].id})

    def test_get_herd_ignores_voided_rows_in_membership_and_history(self):
        ind = make_individual(self.g1, "G1-2509", self.recent - timedelta(days=60))
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=self.recent - timedelta(days=60))
        _void(
            ht_row("TRANSFER", individual=ind, herd=self.g2, from_herd=self.g1, herd_tracking_date=self.recent),
            self.manager,
        )
        g2 = {i["number"] for i in da.get_herd("G2", self.admin.uuid)["individuals"]}
        self.assertNotIn("G1-2509", g2)
        item = next(i for i in da.get_herd("G1", self.admin.uuid)["individuals"] if i["number"] == "G1-2509")
        self.assertEqual([t["herd"] for t in item["herd_tracking"]], ["G1"])

    def test_correction_holder_over_stale_life_sign_is_inactive(self):
        """Holder row is a recent CORRECTION, last life sign is older than the active window."""
        old = self.recent - timedelta(days=db.ACTIVE_WINDOW_DAYS + 100)
        ind = make_individual(self.g1, "G1-2510", old)
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=old)
        ht_row("CORRECTION", individual=ind, herd=self.g1, herd_tracking_date=self.recent)
        listed = {i["number"]: i for i in da.get_individuals(self.gb, self.admin.uuid)}
        self.assertFalse(listed["G1-2510"]["is_active"])
        for status, expected in (("inactive", True), ("active", False)):
            page = da.get_paginated_individuals(
                self.admin.uuid, per_page=200, genebank_id=self.gb, search="G1-2510", status=status
            )
            self.assertEqual("G1-2510" in [i["number"] for i in page["items"]], expected, status)

    def test_outside_holder_with_fresh_row_is_paginated_inactive(self):
        ind = make_individual(self.g1, "G1-2511", self.recent - timedelta(days=60))
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=self.recent - timedelta(days=60))
        ht_row("TRANSFER", individual=ind, herd=self.gx1, from_herd=self.g1, herd_tracking_date=self.recent)
        page = da.get_paginated_individuals(
            self.admin.uuid, per_page=200, genebank_id=self.gb, search="G1-2511", status="inactive"
        )
        self.assertEqual([i["number"] for i in page["items"]], ["G1-2511"])

    def test_was_in_herd_at_date_ignores_voided_row(self):
        ind = make_individual(self.g1, "G1-2512", self.recent - timedelta(days=60))
        ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=self.recent - timedelta(days=60))
        _void(
            ht_row("TRANSFER", individual=ind, herd=self.g2, from_herd=self.g1, herd_tracking_date=self.recent),
            self.manager,
        )
        self.assertTrue(da.was_in_herd_at_date(ind.id, self.g1.id, self.recent))
        self.assertFalse(da.was_in_herd_at_date(ind.id, self.g2.id, self.recent))

    def test_list_readers_do_not_grow_queries_with_rows(self):
        def add(prefix, count):
            for n in range(count):
                ind = make_individual(self.g1, f"G1-{prefix}{n:02d}", self.recent - timedelta(days=60))
                ht_row("BIRTH", individual=ind, herd=self.g1, herd_tracking_date=self.recent - timedelta(days=60))

        def measure():
            with count_queries() as counter:
                da.get_individuals(self.gb, self.admin.uuid)
                da.get_paginated_individuals(self.admin.uuid, per_page=200, genebank_id=self.gb)
            return counter["n"]

        add("26", 2)
        small = measure()
        add("27", 6)
        large = measure()
        self.assertEqual(small, large, "list readers must stay a fixed number of queries")

    def test_get_herd_query_cost_per_individual_is_bounded(self):
        # Regression ceiling (not a flatness claim) on the pre-existing Individual.as_dict() cost,
        # measured at 17 per individual before and after the reader refactor; any increase fails.
        def herd_queries(count, prefix):
            for n in range(count):
                ind = make_individual(self.g2, f"G2-{prefix}{n:02d}", self.recent - timedelta(days=60))
                ht_row("BIRTH", individual=ind, herd=self.g2, herd_tracking_date=self.recent - timedelta(days=60))
            with count_queries() as counter:
                da.get_herd("G2", self.admin.uuid)
            return counter["n"]

        two = herd_queries(2, "27")
        six = herd_queries(4, "28")  # 2 + 4 = 6 individuals now
        per_individual = (six - two) / 4
        self.assertLessEqual(per_individual, 17, f"get_herd: {two} → {six} queries")
