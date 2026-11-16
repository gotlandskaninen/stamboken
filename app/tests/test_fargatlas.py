"""The seed gives colours their atlas numbers as ids."""

from utils import database as db
from utils.fargatlas import ATLAS_FARGER, seed_colors

from tests.database_test import DatabaseTest


class TestSeedColors(DatabaseTest):
    def setUp(self):
        super().setUp()
        # The fixture colours have made-up ids; the seed needs a table of its own.
        db.Individual.update(color=None).execute()
        db.Color.delete().execute()
        self.gotland, self.mellerud = self.genebanks

    def test_atlas_farger_ids(self):
        g = {id_ for id_, gb, _, _ in ATLAS_FARGER if gb == "G"}
        m = {id_ for id_, gb, _, _ in ATLAS_FARGER if gb == "M"}
        self.assertEqual(g, {*range(11, 19), *range(21, 29), *range(31, 40), 41, 42, 43, 46, 49, 51, 52, 54, 71, 99})
        self.assertEqual(m, {100, 101})

    def test_seed_colors_ger_atlasnummer(self):
        colors = seed_colors(self.gotland, self.mellerud)
        self.assertEqual(db.Color.get_by_id(22).name, "Viltgrå")
        self.assertEqual(db.Color.get_by_id(101).genebank, self.mellerud)
        self.assertEqual(colors[("G", "Viltgrå")].id, 22)
        self.assertEqual(colors[("M", "Albino")].id, 101)
        self.assertEqual(colors[("G", "Albino")].id, 12)
        self.assertEqual(len(colors), len(ATLAS_FARGER))

    def test_seed_is_idempotent(self):
        seed_colors(self.gotland, self.mellerud)
        seed_colors(self.gotland, self.mellerud)
        self.assertEqual(db.Color.select().count(), len(ATLAS_FARGER))

    def test_ny_farg_efter_seed(self):
        seed_colors(self.gotland, self.mellerud)
        self.assertGreater(db.Color.create(name="Prov", genebank=self.gotland).id, 101)

    def test_seed_avbryter_vid_krock(self):
        db.Color.create(id=22, name="Annat", genebank=self.gotland)
        with self.assertRaises(ValueError) as raised:
            seed_colors(self.gotland, self.mellerud)
        self.assertIn("down -v", str(raised.exception))

    def test_seed_avbryter_om_namnet_finns_med_annat_id(self):
        db.Color.create(name="Viltgrå", genebank=self.gotland)
        with self.assertRaises(ValueError) as raised:
            seed_colors(self.gotland, self.mellerud)
        self.assertIn("down -v", str(raised.exception))
