#!/usr/bin/env python3
"""
Tests for utils.reference_population: one versioned definition of the
reference population, live (today's MK) and per history year.

One test per condition of the rule and per mode.

isort:skip_file
"""

from datetime import date, timedelta
from unittest.mock import patch

import utils.database as db
import utils.genetics_service as gs
import utils.pedigree_snapshot as ps
import utils.reference_population as rp

from tests.database_test import DatabaseTest
from tests.ht_helpers import _void, ht_row

# Round 2024 closes 2025-03-30: the live start on LIVE_TODAY and the history
# start for 2024 are both 1 January 2024.
START = date(2024, 1, 1)
ROUND_END = date(2025, 3, 30)
HISTORY_AS_OF = date(2025, 3, 31)
LIVE_TODAY = date(2025, 6, 30)
IN_WINDOW = date(2024, 6, 1)
BEFORE_WINDOW = date(2023, 6, 1)

ROLLING_457 = rp.ReferenceDefinition(3, "rolling_days", 457)


def _patched_today(today):
    class Patched(date):
        @classmethod
        def today(cls):
            return today

    return Patched


class ReferencePopulationTest(DatabaseTest):
    def setUp(self):
        super().setUp()
        ps.reset_for_tests()
        self.gb = db.Genebank.create(name="RP-genbank")
        self.mk1 = db.Herd.create(genebank=self.gb, herd="RP1", herd_name="Aktiv", is_active=True)
        self.inactive = db.Herd.create(genebank=self.gb, herd="RP2", herd_name="Inaktiv", is_active=False)
        self.null_active = db.Herd.create(genebank=self.gb, herd="RP3", herd_name="Okänd", is_active=None)
        # The real code, and active, so only the code can exclude it.
        self.gx1 = db.Herd.create(genebank=self.gb, herd="GX1", herd_name="Utanför genbanken", is_active=True)
        self._certificate = 7000

    def tearDown(self):
        ps.reset_for_tests()
        super().tearDown()

    def _round(self, year, end_date):
        return db.YearlyReportRound.create(
            report_year=year, start_date=date(year, 12, 31), end_date=end_date, created_by=self.admin
        )

    def _individual(self, number, tracking=(), certificate=True, birth=None, **kwargs):
        """Individual with tracking rows [(date, herd) | (date, herd, kind), ...]; returns its number."""
        if certificate:
            self._certificate += 1
            kwargs["certificate"] = str(self._certificate)
        if birth is not None:
            kwargs["breeding"] = db.Breeding.create(breeding_herd_id=self.mk1, birth_date=birth)
        individual = db.Individual.create(origin_herd=self.mk1, number=number, **kwargs)
        previous = None
        for row in sorted(tracking, key=lambda r: r[0]):
            tracking_date, herd = row[0], row[1]
            if len(row) > 2:
                kind = row[2]
            elif previous is None:
                kind = "BIRTH" if herd == self.mk1 else "TRANSFER"
            else:
                kind = "TRANSFER" if herd != previous else "ATTESTATION"
            ht_row(
                kind,
                individual=individual,
                from_herd=previous if previous is not None else self.mk1,
                herd=herd,
                herd_tracking_date=tracking_date,
            )
            previous = herd
        self.individual = individual
        return number

    def live(self, today=LIVE_TODAY, definition=rp.CURRENT_DEFINITION):
        return rp.live_members(self.gb.id, today, definition)

    def history(self, year=2024):
        start, as_of = rp.history_window(year)
        return rp.members(self.gb.id, start=start, as_of=as_of, live=False)


class TestConditions(ReferencePopulationTest):
    """The 'Villkor' table, one test per condition and mode."""

    def setUp(self):
        super().setUp()
        self._round(2024, ROUND_END)

    # --- Livstecken ---------------------------------------------------------

    def test_life_sign_in_window_live(self):
        number = self._individual("RP-1", tracking=[(IN_WINDOW, self.mk1)])
        self.assertIn(number, self.live())

    def test_life_sign_in_window_history(self):
        number = self._individual("RP-1", tracking=[(IN_WINDOW, self.mk1)])
        self.assertIn(number, self.history())

    def test_life_sign_on_round_end_date_counts_history(self):
        """as_of is the day after end_date, so a row dated on end_date counts."""
        number = self._individual("RP-1", tracking=[(BEFORE_WINDOW, self.mk1), (ROUND_END, self.mk1)])
        self.assertIn(number, self.history())

    def test_correction_is_not_a_life_sign_live(self):
        number = self._individual("RP-1", tracking=[(BEFORE_WINDOW, self.mk1), (IN_WINDOW, self.mk1, "CORRECTION")])
        self.assertNotIn(number, self.live())

    def test_correction_is_not_a_life_sign_history(self):
        number = self._individual("RP-1", tracking=[(BEFORE_WINDOW, self.mk1), (IN_WINDOW, self.mk1, "CORRECTION")])
        self.assertNotIn(number, self.history())

    def _voided_life_sign(self):
        number = self._individual("RP-1", tracking=[(BEFORE_WINDOW, self.mk1)])
        row = ht_row(
            "ATTESTATION", individual=self.individual, from_herd=self.mk1, herd=self.mk1, herd_tracking_date=IN_WINDOW
        )
        _void(row, self.manager)
        return number

    def test_voided_life_sign_live(self):
        self.assertNotIn(self._voided_life_sign(), self.live())

    def test_voided_life_sign_history(self):
        self.assertNotIn(self._voided_life_sign(), self.history())

    def test_life_sign_after_as_of_history(self):
        """Reported after the round closed: not in that year's history (but live today)."""
        number = self._individual("RP-1", tracking=[(BEFORE_WINDOW, self.mk1), (date(2025, 5, 1), self.mk1)])
        self.assertNotIn(number, self.history())
        self.assertIn(number, self.live())

    def test_future_dated_life_sign_live(self):
        number = self._individual("RP-1", tracking=[(BEFORE_WINDOW, self.mk1), (date(2025, 8, 1), self.mk1)])
        self.assertNotIn(number, self.live())

    # --- Aktuell besättning -------------------------------------------------

    def test_current_herd_live(self):
        sold = self._individual("RP-1", tracking=[(IN_WINDOW, self.mk1), (date(2025, 5, 1), self.gx1)])
        sold_back = self._individual("RP-2", tracking=[(IN_WINDOW, self.gx1), (date(2025, 5, 1), self.mk1, "TRANSFER")])
        sold_later = self._individual("RP-3", tracking=[(IN_WINDOW, self.mk1), (date(2025, 8, 1), self.gx1)])

        live = self.live()

        self.assertNotIn(sold, live)
        self.assertIn(sold_back, live)
        self.assertIn(sold_later, live)  # the future row is not the current herd yet

    def test_current_herd_history(self):
        sold = self._individual("RP-1", tracking=[(IN_WINDOW, self.mk1), (date(2025, 1, 15), self.gx1)])
        sold_after_as_of = self._individual("RP-2", tracking=[(IN_WINDOW, self.mk1), (date(2025, 5, 1), self.gx1)])

        history = self.history()

        self.assertNotIn(sold, history)
        self.assertIn(sold_after_as_of, history)

    def _voided_sale(self):
        number = self._individual("RP-1", tracking=[(IN_WINDOW, self.mk1)])
        row = ht_row(
            "TRANSFER",
            individual=self.individual,
            from_herd=self.mk1,
            herd=self.gx1,
            herd_tracking_date=date(2025, 1, 15),
        )
        _void(row, self.manager)
        return number

    def test_voided_row_is_not_the_current_herd_live(self):
        self.assertIn(self._voided_sale(), self.live())

    def test_voided_row_is_not_the_current_herd_history(self):
        self.assertIn(self._voided_sale(), self.history())

    # --- Besättningen aktiv -------------------------------------------------

    def test_herd_active_live(self):
        inactive = self._individual("RP-1", tracking=[(IN_WINDOW, self.inactive)])
        unknown = self._individual("RP-2", tracking=[(IN_WINDOW, self.null_active)])
        active = self._individual("RP-3", tracking=[(IN_WINDOW, self.mk1)])

        self.assertEqual(self.live() & {inactive, unknown, active}, {active})

    def test_herd_active_is_ignored_history(self):
        inactive = self._individual("RP-1", tracking=[(IN_WINDOW, self.inactive)])
        unknown = self._individual("RP-2", tracking=[(IN_WINDOW, self.null_active)])

        self.assertEqual(self.history() & {inactive, unknown}, {inactive, unknown})

    # --- Född ---------------------------------------------------------------

    def test_born_history(self):
        later = self._individual("RP-1", tracking=[(IN_WINDOW, self.mk1)], birth=date(2025, 4, 15))
        on_as_of = self._individual("RP-2", tracking=[(IN_WINDOW, self.mk1)], birth=HISTORY_AS_OF)
        unknown = self._individual("RP-3", tracking=[(IN_WINDOW, self.mk1)])

        history = self.history()

        self.assertNotIn(later, history)
        self.assertIn(on_as_of, history)
        self.assertIn(unknown, history)

    # --- Död ----------------------------------------------------------------

    def test_dead_live(self):
        dated = self._individual("RP-1", tracking=[(IN_WINDOW, self.mk1)], death_date=date(2025, 12, 1))
        noted = self._individual("RP-2", tracking=[(IN_WINDOW, self.mk1)], death_note="2026 död")
        empty_note = self._individual("RP-3", tracking=[(IN_WINDOW, self.mk1)], death_note="")

        self.assertEqual(self.live() & {dated, noted, empty_note}, {empty_note})

    def test_death_date_history(self):
        after = self._individual("RP-1", tracking=[(IN_WINDOW, self.mk1)], death_date=date(2025, 4, 1))
        on_as_of = self._individual("RP-2", tracking=[(IN_WINDOW, self.mk1)], death_date=HISTORY_AS_OF)

        history = self.history()

        self.assertIn(after, history)
        self.assertNotIn(on_as_of, history)

    def test_death_note_with_year_history(self):
        """'2019 död' without a date: dead from 1 January 2019."""
        number = self._individual("RP-1", tracking=[(date(2018, 6, 1), self.mk1)], death_note="2019 död")

        def members(as_of):
            return rp.members(self.gb.id, start=date(2018, 1, 1), as_of=as_of, live=False)

        self.assertIn(number, members(date(2018, 12, 31)))
        self.assertNotIn(number, members(date(2019, 1, 1)))

    def test_death_note_without_year_history(self):
        """No year in the note: dead from birth + MAX_RABBIT_AGE_DAYS; unknown birth: always dead."""
        # 2010-06-01 + 8 * 365 days = 2018-05-30
        aged = self._individual(
            "RP-1", tracking=[(date(2018, 1, 15), self.mk1)], birth=date(2010, 6, 1), death_note="slaktad"
        )
        no_birth = self._individual("RP-2", tracking=[(date(2018, 1, 15), self.mk1)], death_note="slaktad")

        def members(as_of):
            return rp.members(self.gb.id, start=date(2018, 1, 1), as_of=as_of, live=False)

        self.assertEqual(members(date(2018, 5, 29)) & {aged, no_birth}, {aged})
        self.assertEqual(members(date(2018, 5, 30)) & {aged, no_birth}, set())

    # --- Kastrerad ----------------------------------------------------------

    def test_castrated_live(self):
        number = self._individual("RP-1", tracking=[(IN_WINDOW, self.mk1)], castration_date=date(2026, 1, 1))
        self.assertNotIn(number, self.live())

    def test_castrated_history(self):
        after = self._individual("RP-1", tracking=[(IN_WINDOW, self.mk1)], castration_date=date(2025, 4, 1))
        on_as_of = self._individual("RP-2", tracking=[(IN_WINDOW, self.mk1)], castration_date=HISTORY_AS_OF)

        history = self.history()

        self.assertIn(after, history)
        self.assertNotIn(on_as_of, history)

    # --- Intyg --------------------------------------------------------------

    def _certificates(self):
        paper = self._individual("RP-1", tracking=[(IN_WINDOW, self.mk1)])
        digital = self._individual(
            "RP-2", tracking=[(IN_WINDOW, self.mk1)], certificate=False, digital_certificate=4711
        )
        none = self._individual("RP-3", tracking=[(IN_WINDOW, self.mk1)], certificate=False)
        return {paper, digital, none}, {paper, digital}

    def test_certificate_live(self):
        numbers, expected = self._certificates()
        self.assertEqual(self.live() & numbers, expected)

    def test_certificate_history(self):
        numbers, expected = self._certificates()
        self.assertEqual(self.history() & numbers, expected)

    # --- Makulerad individ --------------------------------------------------

    def test_voided_individual_live(self):
        number = self._individual("RP-1", tracking=[(IN_WINDOW, self.mk1)], voided=True)
        self.assertNotIn(number, self.live())

    def test_voided_individual_history(self):
        number = self._individual("RP-1", tracking=[(IN_WINDOW, self.mk1)], voided=True)
        self.assertNotIn(number, self.history())

    # --- Genbank ------------------------------------------------------------

    def test_other_genebank_is_not_included(self):
        other_gb = db.Genebank.create(name="Annan")
        other_herd = db.Herd.create(genebank=other_gb, herd="AN1", herd_name="Annan", is_active=True)
        other = db.Individual.create(origin_herd=other_herd, number="AN1-1", certificate="8001")
        ht_row("BIRTH", individual=other, herd=other_herd, herd_tracking_date=IN_WINDOW)

        self.assertNotIn("AN1-1", self.live())
        self.assertNotIn("AN1-1", self.history())

    # --- rolling_days, live -------------------------------------------------

    def test_rolling_days_live_window(self):
        """2025-06-30 - 457 days = 2024-03-30, inclusive."""
        on_start = self._individual("RP-1", tracking=[(BEFORE_WINDOW, self.mk1), (date(2024, 3, 30), self.mk1)])
        before = self._individual("RP-2", tracking=[(BEFORE_WINDOW, self.mk1), (date(2024, 3, 29), self.mk1)])

        self.assertEqual(self.live(definition=ROLLING_457) & {on_start, before}, {on_start})
        # round_start (1 January 2024) admits both.
        self.assertEqual(self.live() & {on_start, before}, {on_start, before})


class TestLiveMatchesSliceOne(ReferencePopulationTest):
    """live_members(today) is exactly the slice-1 reference_population_numbers()."""

    def test_same_set_as_reference_population_numbers(self):
        self._round(2024, ROUND_END)
        future = date.today() + timedelta(days=30)
        self._individual("RP-1", tracking=[(IN_WINDOW, self.mk1)])
        self._individual("RP-2", tracking=[(IN_WINDOW, self.gx1), (date(2025, 2, 1), self.mk1, "TRANSFER")])
        self._individual("RP-3", tracking=[(IN_WINDOW, self.mk1)], certificate=False, digital_certificate=4711)
        self._individual("RP-4", tracking=[(date(2023, 12, 31), self.mk1)])
        self._individual("RP-5", tracking=[(IN_WINDOW, self.inactive)])
        self._individual("RP-6", tracking=[(IN_WINDOW, self.null_active)])
        self._individual("RP-7", tracking=[(IN_WINDOW, self.mk1), (date(2025, 2, 1), self.gx1)])
        self._individual("RP-8", tracking=[(IN_WINDOW, self.mk1)], death_date=date(2025, 1, 5))
        self._individual("RP-9", tracking=[(IN_WINDOW, self.mk1)], death_note="Dog 2026")
        self._individual("RP-10", tracking=[(IN_WINDOW, self.mk1)], castration_date=date(2025, 2, 1))
        self._individual("RP-11", tracking=[(IN_WINDOW, self.mk1)], certificate=False)
        self._individual("RP-12", tracking=[(IN_WINDOW, self.mk1)], voided=True)
        self._individual("RP-13", tracking=[(future, self.mk1)])
        self._individual("RP-14", tracking=[(IN_WINDOW, self.mk1), (future, self.gx1)])
        self._individual("RP-15")

        expected = {"RP-1", "RP-2", "RP-3", "RP-14"}

        self.assertEqual(rp.live_members(self.gb.id, date.today()), expected)
        self.assertEqual(gs.reference_population_numbers(self.gb.id), expected)


class TestHistoryIndependentOfToday(ReferencePopulationTest):
    def test_same_year_same_set_on_two_days(self):
        self._round(2024, ROUND_END)
        self._individual("RP-1", tracking=[(IN_WINDOW, self.mk1)], death_date=date(2025, 5, 1))
        self._individual("RP-2", tracking=[(IN_WINDOW, self.mk1), (date(2025, 6, 1), self.gx1)])
        self._individual("RP-3", tracking=[(IN_WINDOW, self.mk1)], castration_date=date(2025, 9, 1))
        self._individual("RP-4", tracking=[(BEFORE_WINDOW, self.mk1), (date(2025, 5, 15), self.mk1)])

        results = []
        for today in (date(2025, 4, 5), date(2026, 10, 4)):
            with patch("utils.reference_population.date", _patched_today(today)):
                results.append(self.history())

        self.assertEqual(results[0], {"RP-1", "RP-2", "RP-3"})
        self.assertEqual(results[1], results[0])


class TestHistoryAsOf(ReferencePopulationTest):
    def test_day_after_round_end(self):
        self._round(2025, date(2026, 3, 30))
        self.assertEqual(rp.history_as_of(2025), date(2026, 3, 31))

    def test_no_round_is_first_of_april(self):
        self.assertEqual(rp.history_as_of(2025), date(2026, 4, 1))

    def test_round_without_end_date(self):
        self._round(2025, None)
        self.assertIsNone(rp.history_as_of(2025))
        self.assertIsNone(rp.history_window(2025))
        self.assertFalse(rp.is_closed(2025, date(2030, 1, 1)))

    def test_is_closed(self):
        self._round(2025, date(2026, 3, 30))
        self.assertFalse(rp.is_closed(2025, date(2026, 3, 30)))
        self.assertTrue(rp.is_closed(2025, date(2026, 3, 31)))
        # No round: closed from 1 April the year after.
        self.assertFalse(rp.is_closed(2030, date(2031, 3, 31)))
        self.assertTrue(rp.is_closed(2030, date(2031, 4, 1)))

    def test_reopened_round_is_not_closed(self):
        """A round whose end date was moved into the future is open again."""
        self._round(2025, date(2026, 12, 31))
        self.assertFalse(rp.is_closed(2025, date(2026, 10, 4)))

    def test_round_start_window(self):
        self._round(2024, ROUND_END)
        self.assertEqual(rp.history_window(2024), (START, HISTORY_AS_OF))
        self.assertEqual(rp.history_window(2030), (date(2030, 1, 1), date(2031, 4, 1)))


class TestRollingDays(ReferencePopulationTest):
    def test_leap_year(self):
        """2024-03-31 - 457 days crosses 29 February 2024."""
        self._round(2023, date(2024, 3, 30))
        self.assertEqual(rp.history_as_of(2023), date(2024, 3, 31))
        self.assertEqual(rp.history_window(2023, ROLLING_457), (date(2022, 12, 30), date(2024, 3, 31)))

    def test_round_ending_in_may(self):
        self._round(2024, date(2025, 5, 15))
        self.assertEqual(rp.history_window(2024, ROLLING_457), (date(2024, 2, 14), date(2025, 5, 16)))
        self.assertEqual(rp.history_window(2024), (START, date(2025, 5, 16)))


class TestDefinitionWiring(ReferencePopulationTest):
    def test_current_definition(self):
        self.assertIs(rp.CURRENT_DEFINITION, rp.DEFINITIONS[2])
        self.assertEqual(rp.CURRENT_DEFINITION, rp.ReferenceDefinition(2, "round_start"))
        self.assertTrue(rp.CURRENT_DEFINITION.preliminary)
        self.assertEqual(rp.MIN_HISTORY_MEMBERS, 30)

    def test_genetics_service_uses_the_module(self):
        self.assertEqual(gs.REFERENCE_DEFINITION_VERSION, rp.CURRENT_DEFINITION.version)
        self.assertIs(gs.reference_population_start, rp.reference_population_start)

    def test_snapshot_load_uses_live_members(self):
        with patch.object(gs, "live_members", wraps=rp.live_members) as spy:
            key, _rows, _members, _eligible = gs._read_snapshot_inputs(self.gb.id)

        spy.assert_called_once_with(self.gb.id, key[1])
