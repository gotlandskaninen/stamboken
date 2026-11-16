#!/usr/bin/env python3
"""
Tests for the register extract and the receipt PDFs (spec 9, fråga 36). Synthetic herds, rabbits and buyers only.

isort:skip_file
"""

from datetime import date, datetime, timezone

import fitz
import utils.arsrapport as arsrapport
import utils.database as db
import utils.mail as mail
from utils.arsrapport_pdf import receipt_pdf, register_extract_pdf

from tests.arsrapport_fixtures import ArsrapportTest
from tests.ht_helpers import ht_row

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
        db.Herd.update(bank_account_number=ACCOUNT, bank_name="Testbanken").where(db.Herd.id == self.h.id).execute()
        self.h = db.Herd.get_by_id(self.h.id)  # the report must carry the account, or the assertion proves nothing
        report = self.reported(
            self.h, self.kvar(kept, vikt=2.8), self.sald(sold, "utanfor", 2025, 10, 3, kopare=BUYER), health="inga"
        )
        self.assertEqual(report.herd.bank_account_number, ACCOUNT)
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
        self.assertNotIn("Testbanken", text)
        self.assertIn("Inga sjukdomsfall eller defekter", text)

    def test_extract_lists_sold_during_the_year(self):
        kept, sold = self.rabbits(self.h, 2)
        self.reported(self.h, self.kvar(kept, vikt=2.8), self.sald(sold, "utanfor", 2025, 10, 3, kopare=BUYER))
        text = text_of(register_extract_pdf(self.h, self.round_))
        self.assertIn("2025-10-03", text)
        self.assertNotIn(BUYER["name"], text)

    def receipt_text(self, **report_fields):
        kept, other = self.rabbits(self.h, 2)
        report = self.reported(self.h, self.kvar(kept, vikt=2.8), self.ej_angiven(other), **report_fields)
        return kept, text_of(receipt_pdf(report, arsrapport._submissions(report)[-1]))  # pylint: disable=protected-access

    def test_receipt_health_not_answered(self):
        _, text = self.receipt_text(health=None)
        self.assertIn("Ej besvarad", text)
        self.assertNotIn("Sjukdomsfall", text)

    def test_receipt_health_cases_with_details(self):
        diseases = {"annat": {"namn": "Snuvan", "antal": 2, "alder": "3 månader"}, "rvhd": {"antal": 1, "alder": ""}}
        kept, other = self.rabbits(self.h, 2)
        defects = [{"individual_id": other.id, "beskrivning": "Sned tand", "foto": None}]
        report = self.reported(
            self.h, self.kvar(kept, vikt=2.8), self.ej_angiven(other), health="ja", diseases=diseases, defects=defects
        )
        text = text_of(receipt_pdf(report, arsrapport._submissions(report)[-1]))  # pylint: disable=protected-access
        for expected in ("Snuvan", "3 månader", "rvhd", "Sned tand", other.number):
            self.assertIn(expected, text)

    def test_extract_keeps_rabbit_moved_after_31_december(self):
        kept, moved = self.rabbits(self.h, 2)
        ht_row(
            "TRANSFER",
            individual=moved,
            herd=db.Herd.get(db.Herd.herd == "GX1"),
            from_herd=self.h,
            herd_tracking_date=date(2026, 1, 3),
        )
        text = text_of(register_extract_pdf(self.h, self.round_))
        self.assertIn(kept.number, text)
        self.assertIn(moved.number, text)

    def test_kvitto_mail_has_the_pdf_attachment(self):
        kept, other = self.rabbits(self.h, 2)
        report = self.reported(self.h, self.kvar(kept, vikt=2.8), self.ej_angiven(other))
        submission = arsrapport._submissions(report)[-1]  # pylint: disable=protected-access
        for kind in ("arsrapport.kvitto", "arsrapport.andrad"):
            built = arsrapport._kvitto({"submission_id": submission.id})  # pylint: disable=protected-access
            ((name, mime, data),) = built["attachments"]
            self.assertEqual((name, mime), ("kvittens.pdf", "application/pdf"), kind)
            self.assertIn(kept.number, text_of(data))
            mail.render(kind, {k: v for k, v in built.items() if k != "attachments"})
