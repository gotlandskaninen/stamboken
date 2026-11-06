"""
Tests for `flask breeding check-collisions` (cli/breeding.py).

The queries are PostgreSQL-only (regexp_match, MODE() WITHIN GROUP, date
arithmetic), so they run against the pytest stack's database and are skipped
on the SQLite fallback.
"""

import os
import unittest
from datetime import date

import utils.database as db
from herdbook import APP

from tests.database_test import DatabaseTest

_USE_POSTGRES = bool(os.getenv("POSTGRES_HOST")) and bool(os.getenv("POSTGRES_DB"))


@unittest.skipUnless(_USE_POSTGRES, "check-collisions uses PostgreSQL-only SQL")
class BreedingCollisionCheckTest(DatabaseTest):
    def _run(self, since_year=2015, fail=False):
        """Kör kommandot som Flask gör det; returnerar CliRunner-resultatet."""
        args = ["breeding", "check-collisions", "--since-year", str(since_year)]
        if fail:
            args.append("--fail")
        result = APP.test_cli_runner().invoke(args=args)
        if result.exception and not isinstance(result.exception, SystemExit):
            raise result.exception
        return result

    @staticmethod
    def _section(output, title_prefix):
        """The lines belonging to one category (its rows are indented)."""
        lines = output.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith(title_prefix))
        rows = []
        for line in lines[start + 1 :]:
            if line and not line.startswith("  "):
                break
            rows.append(line)
        return "\n".join(rows)

    def _litter(self, herd, mother, father, birth_date, number):
        breeding = db.Breeding.create(
            breeding_herd_id=herd,
            mother=mother,
            father=father,
            birth_date=birth_date,
            litter_size=1,
        )
        db.Individual.create(origin_herd=herd, breeding=breeding, number=number)
        return breeding

    def test_same_mother_ten_days_apart_is_reported(self):
        first = self._litter(self.herds[0], self.parents[0], self.parents[1], date(2022, 3, 1), "G1-2211")
        second = self._litter(self.herds[0], self.parents[0], self.parents[1], date(2022, 3, 11), "G1-2212")

        output = self._run().output
        category1 = self._section(output, "Kategori 1")
        self.assertIn(str(first.id), category1)
        self.assertIn(str(second.id), category1)
        row = next(line for line in category1.splitlines() if str(first.id) in line)
        self.assertEqual(row.split()[-1], "10")  # dagar mellan kullarna
        self.assertNotIn("Totalt 0 kollisionsträff(ar)", output)

    def test_same_litter_digit_with_different_mothers_is_reported(self):
        first = self._litter(self.herds[0], self.parents[0], self.parents[1], date(2023, 3, 1), "G1-2311")
        second = self._litter(self.herds[0], self.individuals[0], self.parents[1], date(2023, 7, 1), "G1-2312")

        output = self._run().output
        # Same herd, same year, litter digit 1 in both offspring numbers.
        category2 = self._section(output, "Kategori 2 —")
        self.assertIn(f"{first.id} {second.id}", category2)
        # Different mothers, so it needs renumbering rather than a merge.
        category3 = self._section(output, "Kategori 3")
        self.assertIn(f"{first.id} {second.id}", category3)
        # More than 35 days apart, so not a category 1 hit.
        self.assertNotIn(str(first.id), self._section(output, "Kategori 1"))

    def test_clean_fixture_reports_nothing(self):
        output = self._run().output
        self.assertIn("Totalt 0 kollisionsträff(ar)", output)
        self.assertIn("inga träffar", self._section(output, "Kategori 1"))

    def test_fail_flag_exits_one_only_when_something_is_found(self):
        self.assertEqual(self._run(fail=True).exit_code, 0)

        self._litter(self.herds[0], self.parents[0], self.parents[1], date(2022, 3, 1), "G1-2211")
        self._litter(self.herds[0], self.parents[0], self.parents[1], date(2022, 3, 11), "G1-2212")
        self.assertEqual(self._run(fail=True).exit_code, 1)
        # Utan flaggan är det bara en rapport.
        self.assertEqual(self._run().exit_code, 0)

    def test_since_year_excludes_older_litters(self):
        self._litter(self.herds[0], self.parents[0], self.parents[1], date(2016, 3, 1), "G1-1611")
        self._litter(self.herds[0], self.parents[0], self.parents[1], date(2016, 3, 11), "G1-1612")

        self.assertNotIn("Totalt 0 kollisionsträff(ar)", self._run(since_year=2015).output)
        self.assertIn("Totalt 0 kollisionsträff(ar)", self._run(since_year=2020).output)
