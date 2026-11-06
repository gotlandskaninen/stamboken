"""History rows are keyed on report year and versioned."""

import unittest

import utils.database as db

from tests.database_test import DatabaseTest


class TestGeneticsHistorySchema(DatabaseTest):
    def setUp(self):
        super().setUp()
        if not isinstance(db.DATABASE, db.PostgresqlDatabase):
            self.skipTest("schema introspection requires PostgreSQL")
        self.table = db.GeneticMetricsHistory._meta.table_name

    def test_history_has_versioned_columns(self):
        cols = {c.name for c in db.DATABASE.get_columns(self.table)}
        for name in ("report_year", "as_of", "definition_version", "pedigree_version", "fge"):
            self.assertIn(name, cols)

    def test_unique_index_on_genebank_report_year_only(self):
        unique = [i.columns for i in db.DATABASE.get_indexes(self.table) if i.unique]
        self.assertIn(["genebank_id", "report_year"], unique)
        self.assertNotIn(["genebank_id", "snapshot_date"], unique)

    def test_history_state_table_exists(self):
        self.assertIn("genetics_history_state", db.DATABASE.get_tables())
        cols = {c.name for c in db.DATABASE.get_columns("genetics_history_state")}
        self.assertEqual(cols, {"genebank_id", "checked_at", "version", "definition_version", "algorithm_version"})

    def test_registry_has_31_to_34(self):
        self.assertGreaterEqual(db.CURRENT_SCHEMA_VERSION, 34)
        self.assertIn((31, 32), db.MIGRATIONS)
        self.assertIn((32, 33), db.MIGRATIONS)
        self.assertIn((33, 34), db.MIGRATIONS)


if __name__ == "__main__":
    unittest.main()
