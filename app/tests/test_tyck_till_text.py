"""The text "Tyck till" puts in an issue: nothing from the browser gets in as markup, a mention or a link."""

import unittest
import uuid
from unittest import mock

import utils.settings as settings
import utils.tyck_till as tt

UUID = "3f2b9c1e-8a4d-4e6f-9b7a-1c2d3e4f5a6b"


class TestPaths(unittest.TestCase):
    def test_generic_path(self):
        for path, expected in (
            ("/stamboken/individ/G1234-2601", "/stamboken/individ/[id]"),
            (f"/stamboken/verifiera/{UUID}", "/stamboken/verifiera/[id]"),
            ("/medlem/matrikel/17", "/medlem/matrikel/[id]"),
            ("/stamboken/min-besattning", "/stamboken/min-besattning"),
            ("/stamboken/individ/G1?q=1\n@jonas", "/stamboken/individ/[id]"),
            ("x](http://evil)", "okänd sida"),
            ("", "okänd sida"),
            (None, "okänd sida"),
            ("/" + "a" * 200, "okänd sida"),
        ):
            self.assertEqual(tt.generic_path(path), expected, path)

    def test_mail_path_keeps_the_segments_but_not_the_codes(self):
        self.assertEqual(tt.mail_path(f"/stamboken/verifiera/{UUID}"), "/stamboken/verifiera/[uuid]")
        self.assertEqual(tt.mail_path("/stamboken/individ/G1234-2601"), "/stamboken/individ/G1234-2601")
        self.assertEqual(tt.mail_path("/lank/12.abcdefghijklmnopqrstuv"), "/lank/12.***")
        self.assertEqual(tt.mail_path("/a\nb"), "/a b")
        self.assertEqual(tt.mail_path("x"), "okänd sida")

    def test_mask_codes(self):
        self.assertEqual(tt.mask_codes(f"knappen ”token {UUID}”"), "knappen ”token [uuid]”")
        self.assertEqual(tt.mask_codes(None), "")

    def test_clean_version(self):
        self.assertEqual(tt.clean_version("2.13.0"), "2.13.0")
        for bad in ("1\n@jonas", "", None, "1" * 41):
            self.assertEqual(tt.clean_version(bad), "okänd")


class TestIssue(unittest.TestCase):
    def test_private_titles_are_fixed(self):
        self.assertEqual(tt.issue_title("fel", "privat", "Anna Svensson"), "Tyck till: något fungerar inte")
        self.assertEqual(tt.issue_title("onskemal", "privat", "x"), "Tyck till: önskemål")

    def test_public_title_is_the_first_line_cut_at_70(self):
        self.assertEqual(tt.issue_title("fel", "publik", "Knappen syns inte\nmer text"), "Tyck till: Knappen syns inte")
        self.assertEqual(tt.issue_title("fel", "publik", "   \n \r\n  Andra raden \nt"), "Tyck till: Andra raden")
        self.assertEqual(tt.issue_title("fel", "publik", "a" * 70), "Tyck till: " + "a" * 70)
        self.assertEqual(tt.issue_title("fel", "publik", "a" * 71), "Tyck till: " + "a" * 70 + "…")

    def test_body_fences_the_text_longer_than_any_backtick_run(self):
        text = "före ``` mitt i ````` @jonas <img src=x> efter"
        body = tt.issue_body("fel", "publik", text, "/stamboken/individ/G1", "2.13.0", "mobil", 0, "tt-0a1b2c3d")
        fence = "``````"
        self.assertTrue(body.startswith(f"{fence}\n{text}\n{fence}\n"))
        outside = body.split(fence)[2]
        self.assertNotIn("@", outside)
        self.assertNotIn("<", outside)
        self.assertEqual(tt.issue_body("fel", "publik", "x", "", "", "", 0, "tt-1").split("\n")[0], "```")

    def test_body_facts(self):
        body = tt.issue_body("fel", "privat", "Text", "/stamboken/individ/G1", "2.13.0", "mobil", 2, "tt-0a1b2c3d")
        for line in ("Sida: /stamboken/individ/[id]", "Version: 2.13.0", "Enhet: mobil", "Referens: tt-0a1b2c3d"):
            self.assertIn(line, body)
        self.assertIn("Bilder: 2, skickas med mejl till föreningen", body)
        public = tt.issue_body("fel", "publik", "Text", "x", "1\n@jonas", "x@y", 2, "tt-0a1b2c3d")
        self.assertNotIn("Bilder", public)
        self.assertIn("Version: okänd\nEnhet: okänd", public)
        self.assertNotIn("@", public)

    def test_body_names_what_was_pointed_at_as_inline_code(self):
        uuid = "3f2b8c1e-0a4d-4e5f-9a6b-7c8d9e0f1a2b"
        for visibility in ("publik", "privat"):
            with self.subTest(visibility=visibility):
                body = tt.issue_body(
                    "fel", visibility, "Text", "/stamboken/x", "2.13.0", "mobil", 0, "tt-1", "knappen ”Kullista”"
                )
                self.assertIn("Sida: /stamboken/x\nPekade på: ` knappen ”Kullista” `\nVersion:", body)
        hostile = f"knappen\n”@jonas `x` <img src=x> {uuid}”" + " " * 300
        line = next(
            line
            for line in tt.issue_body("fel", "publik", "T", "/a", "1", "mobil", 0, "tt-1", hostile).splitlines()
            if line.startswith("Pekade på:")
        )
        self.assertEqual(line, "Pekade på: `` knappen ”@jonas `x` <img src=x> [uuid]” ``")
        self.assertNotIn("Pekade på", tt.issue_body("fel", "publik", "T", "/a", "1", "mobil", 0, "tt-1", "  "))
        self.assertNotIn("Pekade på", tt.issue_body("fel", "publik", "T", "/a", "1", "mobil", 0, "tt-1"))

    def test_a_public_issue_names_rows_and_text_by_kind_only(self):
        def line(visibility, pekat):
            body = tt.issue_body("fel", visibility, "T", "/a", "1", "mobil", 0, "tt-1", pekat)
            return next((x for x in body.splitlines() if x.startswith("Pekade på:")), None)

        for pekat, public in {
            "raden ”Kontaktperson Anna Andersson”": "Pekade på: ` raden `",
            "texten ”Ring 070-123 45 67”": "Pekade på: ` texten `",
            "länken ”Anna Andersson”": "Pekade på: ` länken `",
            "rutan ”Köpare Berit”": "Pekade på: ` rutan `",
            "knappen ”Spara kull”": "Pekade på: ` knappen ”Spara kull” `",
            "rubriken ”Kullista”": "Pekade på: ` rubriken ”Kullista” `",
            "fältet ”E-post”": "Pekade på: ` fältet ”E-post” `",
            "en dold uppgift": None,
            "något annat ”Anna”": None,
        }.items():
            with self.subTest(pekat=pekat):
                self.assertEqual(line("publik", pekat), public)
        self.assertEqual(
            line("privat", "raden ”Kontaktperson Anna Andersson”"),
            "Pekade på: ` raden ”Kontaktperson Anna Andersson” `",
        )

    def test_pointed_drops_codes_glued_to_labels_compact_or_cut(self):
        uuid = "3f2b8c1e-0a4d-4e5f-9a6b-7c8d9e0f1a2b"
        cases = {
            f"raden ”Länk42.{'A' * 22}”": "raden ”Länk[kod]”",
            f"raden ”token{uuid.replace('-', '')}”": "raden ”token[kod]”",
            f"texten ”token {uuid[:-1]}…”": "texten ”token [kod]…”",
            f"texten ”{uuid}”": "texten ”[uuid]”",
            "länken ”test.person+x@example.org”": "länken ”[e-post]”",
            "raden ”G1274-2312 Ada, född 2026-11-02, version 2.15.1”": "raden ”G1274-2312 Ada, född 2026-11-02, version 2.15.1”",
        }
        for given, expected in cases.items():
            with self.subTest(given=given):
                self.assertEqual(tt.pointed(given), expected)

    def test_labels(self):
        self.assertEqual(tt.labels("fel"), ["tyck till", "bug"])
        self.assertEqual(tt.labels("onskemal"), ["tyck till", "enhancement"])
        with mock.patch.object(settings.service, "demo_instance", True):
            self.assertEqual(tt.labels("fel"), ["tyck till", "bug", "testmiljö"])

    def test_reference_is_stable_and_per_submission(self):
        first, second = uuid.uuid4(), uuid.uuid4()
        self.assertRegex(tt.reference(first), r"^tt-[0-9a-f]{8}$")
        self.assertEqual(tt.reference(first), tt.reference(first))
        self.assertNotEqual(tt.reference(first), tt.reference(second))
