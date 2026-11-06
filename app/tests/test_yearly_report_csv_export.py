"""Formula-injection protection in the yearly report CSV export."""

import csv
import io
import unittest
from unittest import mock

import utils.data_access as da

PAYLOAD = '=HYPERLINK("http://example.invalid","x")'
TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _report(**overrides):
    report = {
        "herd": 7,
        "name": PAYLOAD,
        "status": "Aktiv genbank",
        "litter_count": -1,
        "total_kits_born": 4,
        "living_kits_6weeks": 3,
        "registered_females_yearend": 2,
        "registered_males_yearend": 1,
        "breeding_females_used": 2,
        "breeding_males_used": 1,
        "publish": "Nej, ingen publicering",
        "email": "+" + "a@example.invalid",
        "eligible_for_support": True,
        "bank_account": "-123",
        "bank_name": "@bank",
        "defects_malformations": "\t" + PAYLOAD,
        "disease_cases": "Inga rapporterade sjukdomsfall",
        "submission_date": "2020-12-31",
        "fullname": PAYLOAD,
    }
    report.update(overrides)
    return report


class TestYearlyReportCsvFormulaInjection(unittest.TestCase):
    def _rows(self, report):
        with mock.patch.object(da, "get_yearly_reports", return_value=[report]):
            data = da.export_yearly_reports_csv(1, 1)
        return list(csv.reader(io.StringIO(data.lstrip("﻿"), newline=""), delimiter=";"))

    def test_text_cells_starting_with_formula_prefix_are_neutralized(self):
        rows = self._rows(_report())
        self.assertEqual(len(rows), 2)
        for i, cell in enumerate(rows[1]):
            if i != 3:  # litter_count is a real (negative) number
                self.assertFalse(cell.startswith(TRIGGERS), (i, cell))
        self.assertEqual(rows[1][13], " -123")
        self.assertEqual(rows[1][1], " " + PAYLOAD)

    def test_counts_are_numbers_only_when_they_are_numbers(self):
        # The counts come from the report form's JSON, so a "count" can be any string.
        row = self._rows(_report(name="Hage", litter_count=-1, total_kits_born="=1+1", living_kits_6weeks=None))[1]
        self.assertEqual(row[:6], ["7", "Hage", "Aktiv genbank", "-1", " =1+1", ""])

    def test_quote_in_a_field_cannot_open_a_new_cell(self):
        breakout = 'x";=1+1;"'
        rows = self._rows(_report(name=breakout, fullname="Hage"))
        self.assertEqual(rows[1][1], breakout)
        self.assertEqual(len(rows[1]), 19)

    def test_line_break_in_a_field_cannot_open_a_new_row(self):
        for brk in ("\r", "\n", "\r\n"):
            rows = self._rows(_report(name=f"Oak{brk}=1+1", fullname="Hage"))
            self.assertEqual(len(rows), 2, repr(brk))
            self.assertEqual(rows[1][1], f"Oak{brk}=1+1")
            self.assertEqual(len(rows[1]), 19)
