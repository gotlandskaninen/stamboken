"""Phase 19 — pure postal helpers (no database)."""

import unittest

from utils.postal import format_postal_address, normalize_postal_code, split_postal_address


class TestNormalizePostalCode(unittest.TestCase):
    def test_table(self):
        for raw, expected in (
            (None, None),
            ("", None),
            ("   ", None),
            ("62355", "623 55"),
            ("623 55", "623 55"),
            ("  623 55  ", "623 55"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_postal_code(raw), expected)

    def test_rejects_non_five_digit(self):
        for bad in ("6235", "623555", "S-623 55", "abcde", "623-55", "623  55"):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as ctx:
                normalize_postal_code(bad)
            self.assertEqual(str(ctx.exception), "Postnummer ska vara fem siffror")

    def test_rejects_non_string(self):
        with self.assertRaises(ValueError):
            normalize_postal_code(62355)


class TestSplitAndFormat(unittest.TestCase):
    def test_split_legacy_layouts(self):
        self.assertEqual(split_postal_address("623 55 Visby"), ("623 55", "Visby"))
        self.assertEqual(split_postal_address("62355 Visby"), ("623 55", "Visby"))
        self.assertEqual(split_postal_address("  621 45   Visby  "), ("621 45", "Visby"))
        self.assertEqual(split_postal_address("623 55 Lärbro, Gotland"), ("623 55", "Lärbro, Gotland"))

    def test_split_non_parsing_goes_to_city(self):
        self.assertEqual(split_postal_address("Box 12 Visby"), (None, "Box 12 Visby"))
        self.assertEqual(split_postal_address("62355"), (None, "62355"))

    def test_split_blank(self):
        self.assertEqual(split_postal_address(None), (None, None))
        self.assertEqual(split_postal_address("   "), (None, None))

    def test_format(self):
        self.assertEqual(format_postal_address("623 55", "Visby"), "623 55 Visby")
        self.assertEqual(format_postal_address(None, "Visby"), "Visby")
        self.assertEqual(format_postal_address("623 55", None), "623 55")
        self.assertIsNone(format_postal_address(None, None))
