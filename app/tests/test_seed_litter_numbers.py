"""Unit tests for the seed's litter-number backfill (cli/seed.py).

Pure helpers — no database. _plan_litter_numbers holds the whole decision
(minted number vs chronological rank, bucket collisions, what is left alone);
_assign_litter_numbers only reads the Breeding rows, hands it plain _Litter
records and saves the plan.
"""

import unittest
from datetime import date

from cli.seed import (
    _Litter,
    _litter_number_from_offspring,
    _parse_litter_number,
    _plan_litter_numbers,
)


def _litter(breeding_id, birth_date=None, *, herd="G1274", breed_date=None, litter_number=None, numbers=()):
    return _Litter(
        breeding_id=breeding_id,
        herd=herd,
        birth_date=birth_date,
        breed_date=breed_date,
        litter_number=litter_number,
        offspring_numbers=tuple(numbers),
    )


class ParseLitterNumberTest(unittest.TestCase):
    def test_minted_number_yields_its_litter(self):
        # {herd}-{YY}{litter}{slot}: siblings of litter 1, born 2021
        self.assertEqual(_parse_litter_number("G1274-2111", "G1274", 2021), 1)
        self.assertEqual(_parse_litter_number("G1274-2114", "G1274", 2021), 1)
        self.assertEqual(_parse_litter_number("G1274-1921", "G1274", 2019), 2)
        self.assertEqual(_parse_litter_number("G95-9811", "G95", 1998), 1)

    def test_two_digit_litter(self):
        self.assertEqual(_parse_litter_number("G1274-21123", "G1274", 2021), 12)

    def test_zero_padded_litter_is_not_a_minted_number(self):
        # generate_individual_number serialises the litter integer unpadded, so
        # a leading zero there (litter "01") was never issued by the generator.
        self.assertIsNone(_parse_litter_number("G1274-21011", "G1274", 2021))
        self.assertIsNone(_parse_litter_number("G1274-2101", "G1274", 2021))

    def test_slot_zero_is_not_a_minted_number(self):
        # Slots start at 1 — a trailing 0 means the number was never issued
        # by generate_individual_number (bulk pagination fixtures).
        self.assertIsNone(_parse_litter_number("G1274-2050", "G1274", 2020))

    def test_other_herds_prefix_is_rejected(self):
        # Kit registered under another herd's prefix than the breeding herd.
        self.assertIsNone(_parse_litter_number("G1274-2115", "G1398", 2021))

    def test_year_suffix_must_match_the_litter_year(self):
        self.assertIsNone(_parse_litter_number("G1274-2116", "G1274", 2019))

    def test_missing_or_unparsable_number(self):
        self.assertIsNone(_parse_litter_number(None, "G1274", 2021))
        self.assertIsNone(_parse_litter_number("G1274", "G1274", 2021))
        self.assertIsNone(_parse_litter_number("G1274-21", "G1274", 2021))


class LitterNumberFromOffspringTest(unittest.TestCase):
    def test_most_common_parse_wins(self):
        numbers = ("G1274-2131", "G1274-2132", "G1274-2141")
        self.assertEqual(_litter_number_from_offspring(numbers, "G1274", 2021), 3)

    def test_tie_breaks_to_the_smallest_number_whatever_the_row_order(self):
        # migrate_21_to_22 uses MODE() WITHIN GROUP (ORDER BY ...::int): among
        # the most frequent parses it takes the first in ascending order, so a
        # tie must not depend on the order the rows came back in.
        self.assertEqual(_litter_number_from_offspring(("G1274-2151", "G1274-2121"), "G1274", 2021), 2)
        self.assertEqual(_litter_number_from_offspring(("G1274-2121", "G1274-2151"), "G1274", 2021), 2)

    def test_numbers_that_were_never_minted_are_ignored(self):
        self.assertEqual(_litter_number_from_offspring(("G1274-2120", "G1274-2121"), "G1274", 2021), 2)

    def test_no_minted_numbers_at_all(self):
        self.assertIsNone(_litter_number_from_offspring((), "G1274", 2021))
        self.assertIsNone(_litter_number_from_offspring(("G1274-2120", "G1274"), "G1274", 2021))


class PlanLitterNumbersTest(unittest.TestCase):
    def test_minted_number_is_preserved(self):
        litters = [_litter(1, date(2021, 3, 1), numbers=("G1274-2131", "G1274-2132"))]
        self.assertEqual(_plan_litter_numbers(litters), {1: 3})

    def test_taken_number_falls_through_to_the_next_free_one(self):
        # Two litters minted under the same prefix — the second still gets a
        # number instead of being cleared to NULL as the migration's dedupe does.
        litters = [
            _litter(1, date(2021, 3, 1), numbers=("G1274-2111",)),
            _litter(2, date(2021, 5, 1), numbers=("G1274-2111",)),
        ]
        self.assertEqual(_plan_litter_numbers(litters), {1: 1, 2: 2})

    def test_litters_without_minted_numbers_rank_chronologically(self):
        litters = [
            _litter(7, date(2021, 9, 1)),
            _litter(3, date(2021, 2, 1)),
            _litter(5, date(2021, 2, 1)),
        ]
        self.assertEqual(_plan_litter_numbers(litters), {3: 1, 5: 2, 7: 3})

    def test_mating_awaiting_birth_gets_nothing(self):
        litters = [_litter(1, None, breed_date=date(2021, 6, 1))]
        self.assertEqual(_plan_litter_numbers(litters), {})

    def test_row_without_any_date_is_skipped(self):
        self.assertEqual(_plan_litter_numbers([_litter(1)]), {})

    def test_already_numbered_row_is_untouched_and_blocks_its_bucket(self):
        litters = [
            _litter(1, date(2021, 3, 1), litter_number=1, numbers=("G1274-2111",)),
            _litter(2, date(2021, 4, 1), numbers=("G1274-2111",)),
        ]
        self.assertEqual(_plan_litter_numbers(litters), {2: 2})

    def test_numbered_mating_awaiting_birth_still_reserves_its_number(self):
        # The bucket year is EXTRACT(YEAR FROM COALESCE(birth_date, breed_date +
        # 30 days)), so this mating belongs to 2021 though it was bred in 2020.
        litters = [
            _litter(1, None, breed_date=date(2020, 12, 20), litter_number=1),
            _litter(2, date(2021, 4, 1)),
        ]
        self.assertEqual(_plan_litter_numbers(litters), {2: 2})

    def test_buckets_are_per_herd_and_year(self):
        litters = [
            _litter(1, date(2021, 3, 1)),
            _litter(2, date(2021, 4, 1), herd="G1398"),
            _litter(3, date(2022, 5, 1)),
        ]
        self.assertEqual(_plan_litter_numbers(litters), {1: 1, 2: 1, 3: 1})

    def test_plan_is_idempotent(self):
        litters = [
            _litter(1, date(2021, 3, 1), numbers=("G1274-2131",)),
            _litter(2, date(2021, 4, 1), numbers=("G1274-2131",)),
            _litter(3, date(2021, 5, 1)),
            _litter(4, date(2021, 6, 1), litter_number=2),
            _litter(5, None, breed_date=date(2021, 7, 1)),
            _litter(6, date(2021, 8, 1), herd="G1398"),
        ]
        plan = _plan_litter_numbers(litters)
        self.assertEqual(plan, {1: 3, 2: 1, 3: 4, 6: 1})

        numbered = [
            litter._replace(litter_number=plan.get(litter.breeding_id, litter.litter_number)) for litter in litters
        ]
        self.assertEqual(_plan_litter_numbers(numbered), {})


if __name__ == "__main__":
    unittest.main()
