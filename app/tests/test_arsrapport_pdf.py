#!/usr/bin/env python3
"""
Tests for the register extract and the receipt PDFs (spec 9, fråga 36). Synthetic herds, rabbits and buyers only.

isort:skip_file
"""

from datetime import date, datetime, timezone

import fitz
import utils.arsrapport as arsrapport
import utils.database as db
from utils.arsrapport_pdf import receipt_pdf, register_extract_pdf

from tests.arsrapport_fixtures import ArsrapportTest

BUYER = {"name": "Zelda Uniquebuyer", "town": "Visby"}
ACCOUNT = "12345678901"


def text_of(pdf: bytes) -> str:
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        return " ".join(page.get_text() for page in doc)


class PdfTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        self.at(date(2026, 1, 5))
        self.round_ = self.round(2025)
        self.h = db.Herd.create(genebank=self.gotland, herd="G9001", herd_name="Testbesättning", is_active=True)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)

    def test_extract_lists_the_31_december_rabbits(self):
        rabbits = self.rabbits(self.h, 6)
        db.Breeding.create(
            breeding_herd_id=self.h,
            mother=rabbits[0],
            father=rabbits[1],
            breed_date=date(2025, 4, 1),
            birth_date=date(2025, 5, 2),
            litter_size=5,
            litter_size6w=4,
        )
        text = text_of(register_extract_pdf(self.h, self.round_))
        for rabbit in rabbits:
            self.assertIn(rabbit.number, text)
        self.assertIn("Registerutdrag, bara för kontroll", text)
        self.assertIn("2025-05-02", text)  # the litter line, with its mother and father
        self.assertEqual(text.count(rabbits[0].number), 2)  # on the list, and as the litter's mother

    def test_receipt_has_choices_and_no_buyer_or_account(self):
        kept, sold = self.rabbits(self.h, 2)
        report = self.reported(
            self.h, self.kvar(kept, vikt=2.8), self.sald(sold, "utanfor", 2025, 10, 3, kopare=BUYER), health="inga"
        )
        submission = arsrapport._submissions(report)[-1]  # pylint: disable=protected-access
        submission.created_at = datetime(2026, 1, 5, 11, 0, tzinfo=timezone.utc)
        text = text_of(receipt_pdf(report, submission))
        self.assertIn(kept.number, text)
        self.assertIn(sold.number, text)
        self.assertIn("utanför genbanken", text)
        self.assertIn("2.8", text)
        self.assertNotIn(BUYER["name"], text)
        self.assertNotIn(BUYER["town"], text)
        self.assertNotIn(ACCOUNT, text)

    def test_extract_lists_sold_during_the_year(self):
        kept, sold = self.rabbits(self.h, 2)
        self.reported(self.h, self.kvar(kept, vikt=2.8), self.sald(sold, "utanfor", 2025, 10, 3, kopare=BUYER))
        text = text_of(register_extract_pdf(self.h, self.round_))
        self.assertIn("2025-10-03", text)
        self.assertNotIn(BUYER["name"], text)
