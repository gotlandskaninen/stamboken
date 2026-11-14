"""
Tests for the v2 certificate generation pipeline (WeasyPrint + pyHanko).
"""

import hashlib
import unittest
from pathlib import Path

from utils.certificates_v2 import CertificateGeneratorV2, compute_checksum, sign_pdf


def _sample_data():
    """Return a data dict matching template variables (FORM_KEYS from certificates.py)."""
    return {
        "genebank": "Gotlandskanin",
        "genebank_number": "G1274",
        "genebank_aki": "2301",
        "name": "Testkanin",
        "sex": "Hane",
        "birth_date": "2025-01-15",
        "color": "Vit",
        "eye_color": "Brun",
        "claw_color": "Ljus",
        "belly_color": "Vit",
        "hair_notes": "Normalt",
        "litter_size": "6",
        "litter_size6w": "5",
        "photos": "Ja",
        "notes": "",
        "digital_certificate": "100042",
        "fullname": "Test Testsson",
        "herd": "G1274",
        "issue_date": "2025-03-15",
        "F_genebank_number": "G1274",
        "F_genebank_aki": "2101",
        "F_name": "Pansen",
        "F_color": "Grå",
        "M_genebank_number": "G1274",
        "M_genebank_aki": "2102",
        "M_name": "Moringen",
        "M_color": "Vit",
        "FF_genebank_number": "G1274",
        "FF_genebank_aki": "1901",
        "FF_name": "Faransen",
        "FF_color": "Grå",
        "FM_genebank_number": "G1274",
        "FM_genebank_aki": "1902",
        "FM_name": "Farmansen",
        "FM_color": "Vit",
        "MF_genebank_number": "G1274",
        "MF_genebank_aki": "1903",
        "MF_name": "Morfansen",
        "MF_color": "Grå",
        "MM_genebank_number": "G1274",
        "MM_genebank_aki": "1904",
        "MM_name": "Mormansen",
        "MM_color": "Vit",
        "foot_ring": "",
        "color_code": "",
        "color_note": "",
        "public_url": "gotlandskaninen.se/stamboken/individ/G1274-2301",
        "replaces_date": "",
        "doc_hash_stub": "ABCD1234",
    }


class TestGeneratePedigree(unittest.TestCase):
    """Tests for PDF generation."""

    def setUp(self):
        self.generator = CertificateGeneratorV2()
        self.data = _sample_data()

    def test_returns_pdf_bytes(self):
        """generate_pedigree() returns bytes starting with %PDF-."""
        result = self.generator.generate_pedigree(self.data, qr_url="https://example.com/verify/abc")
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"%PDF-"))

    def test_pdf_has_content(self):
        """Generated PDF should have meaningful size."""
        result = self.generator.generate_pedigree(self.data, qr_url="https://example.com/verify/abc")
        self.assertGreater(len(result), 1000)

    def test_missing_ancestors_renders_without_error(self):
        """Template handles missing ancestor data (no orphaned hyphens)."""
        sparse_data = {
            "genebank": "Gotlandskanin",
            "genebank_number": "G1274",
            "genebank_aki": "2301",
            "name": "Ensam",
            "sex": "Hona",
            "birth_date": "2025-06-01",
            "color": "Grå",
            "eye_color": "Brun",
            "claw_color": "Ljus",
            "belly_color": "Vit",
            "hair_notes": "",
            "litter_size": "3",
            "litter_size6w": "3",
            "photos": "Nej",
            "notes": "",
            "digital_certificate": "100099",
            "fullname": "Test Testsson",
            "herd": "G1274",
            "issue_date": "2025-06-15",
            # All ancestor fields empty — unknown parentage
            "F_genebank_number": "",
            "F_genebank_aki": "",
            "F_name": "",
            "F_color": "",
            "M_genebank_number": "",
            "M_genebank_aki": "",
            "M_name": "",
            "M_color": "",
            "FF_genebank_number": "",
            "FF_genebank_aki": "",
            "FF_name": "",
            "FF_color": "",
            "FM_genebank_number": "",
            "FM_genebank_aki": "",
            "FM_name": "",
            "FM_color": "",
            "MF_genebank_number": "",
            "MF_genebank_aki": "",
            "MF_name": "",
            "MF_color": "",
            "MM_genebank_number": "",
            "MM_genebank_aki": "",
            "MM_name": "",
            "MM_color": "",
            "foot_ring": "",
            "color_code": "",
            "color_note": "",
            "public_url": "gotlandskaninen.se/stamboken/individ/G1274-2301",
            "replaces_date": "",
            "doc_hash_stub": "ABCD1234",
        }
        result = self.generator.generate_pedigree(sparse_data, qr_url="https://example.com/verify/abc")
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"%PDF-"))

    def test_missing_optional_fields_show_dash(self):
        """Empty optional fields render as '—' (em dash) in the PDF."""
        sparse_data = _sample_data()
        sparse_data.update(
            {
                "hair_notes": "",
                "notes": "",
                "foot_ring": "",
                "color_note": "",
            }
        )
        gen = CertificateGeneratorV2()
        template = gen.env.get_template("pedigree.html")
        qr_svg = gen.generate_qr_svg("https://example.com/verify/abc")
        html = template.render(qr_svg=qr_svg, **sparse_data)  # nosemgrep: direct-use-of-jinja2
        # Empty optional fields should render as em dash, not blank
        self.assertIn("\u2014", html)  # — (em dash)


class TestPedigreeTemplateV2(unittest.TestCase):
    """Rendered HTML of the template: identity rows, breed line, footer."""

    def _html(self, **over):
        data = _sample_data()
        data.update(breed="Gotlandskanin", microchip="")
        data.update(over)
        gen = CertificateGeneratorV2()
        template = gen.env.get_template("pedigree.html")
        return template.render(qr_svg="", **data)  # nosemgrep: direct-use-of-jinja2

    def test_foot_ring_and_chip_both(self):
        html = self._html(foot_ring="FGK 218", microchip="752098100012345")
        self.assertIn("Benring", html)
        self.assertIn("FGK 218", html)
        self.assertIn("Chipnummer", html)
        self.assertIn("752098100012345", html)
        self.assertNotIn("Fotringsnr", html)

    def test_reissue_of_v1(self):
        html = self._html(replaces_v1=True, digital_certificate="345")
        self.assertIn("Ersätter det tidigare digitala intyget nr 345", html)
        self.assertNotIn("Ersätter det tidigare", self._html())
        both = self._html(replaces_v1=True, replaces_date="2026-11-01")
        self.assertIn("Ersätter intyg utfärdat 2026-11-01", both)
        self.assertNotIn("Ersätter det tidigare", both)

    def test_only_foot_ring(self):
        html = self._html(foot_ring="FGK 218")
        self.assertIn("FGK 218", html)
        self.assertNotIn("Chipnummer", html)

    def test_only_chip(self):
        html = self._html(microchip="752098100012345")
        self.assertIn("752098100012345", html)
        self.assertNotIn("Benring", html)

    def test_neither_foot_ring_nor_chip(self):
        html = self._html()
        self.assertNotIn("Benring", html)
        self.assertNotIn("Chipnummer", html)

    def test_missing_sex_is_not_none(self):
        self.assertNotIn("None", self._html(sex=""))

    def test_no_jordbruksverket(self):
        self.assertNotIn("Jordbruksverket", self._html())

    def test_breed_under_title(self):
        html = self._html(breed="Mellerudskanin", genebank="Mellerud")
        self.assertIn('<p class="breed">Mellerudskanin</p>', html)

    def test_individual_number_in_one_field(self):
        self.assertIn("G1274-2301", self._html())

    def test_unknown_parent_has_no_stray_dash(self):
        html = self._html(F_genebank_number=None, F_genebank_aki=None)
        self.assertNotIn("\u2014-", html)


class TestBuildCertData(unittest.TestCase):
    def test_breed_and_microchip(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from utils.cert_service_v2 import build_cert_data

        ind = SimpleNamespace(
            origin_herd=SimpleNamespace(genebank=SimpleNamespace(name="Mellerud"), name="Uppfödare", herd_name=None, herd="M12"),
            microchip="752098100012345",
            number="G1-1",
            digital_certificate="1",
        )
        current = {"fullname": "Den som utfärdar", "herd": "MX1"}
        with patch("utils.cert_service_v2.get_certificate_data", return_value=current):
            data = build_cert_data(ind, {}, 1)
        self.assertEqual(data["breed"], "Mellerudskanin")
        # The breeder attests, with the origin herd, not the issuing user or the current (buyer's) herd
        self.assertEqual(data["fullname"], "Uppfödare")
        self.assertEqual(data["herd"], "M12")
        self.assertEqual(data["microchip"], "752098100012345")
        ind.microchip = None
        with patch("utils.cert_service_v2.get_certificate_data", return_value={}):
            self.assertEqual(build_cert_data(ind, {}, 1)["microchip"], "")


class TestSignPdf(unittest.TestCase):
    """Tests for PDF signing."""

    def setUp(self):
        self.generator = CertificateGeneratorV2()
        self.pdf_bytes = self.generator.generate_pedigree(_sample_data(), qr_url="https://example.com/verify/abc")

    def test_signed_pdf_larger(self):
        """sign_pdf() produces larger output (signature added)."""
        signed = sign_pdf(self.pdf_bytes, reason="Test", contact_info="test@example.com")
        self.assertIsInstance(signed, bytes)
        self.assertTrue(signed.startswith(b"%PDF-"))
        self.assertGreater(len(signed), len(self.pdf_bytes))

    def test_signed_pdf_uses_pades(self):
        """sign_pdf() applies a PAdES (ETSI.CAdES.detached) signature, not PKCS7."""
        signed = sign_pdf(self.pdf_bytes, reason="Test", contact_info="test@example.com")
        # PAdES signatures use the /ETSI.CAdES.detached subfilter
        self.assertIn(b"ETSI.CAdES.detached", signed)
        self.assertNotIn(b"adbe.pkcs7.detached", signed)


class TestComputeChecksum(unittest.TestCase):
    """Tests for SHA-256 checksum."""

    def test_returns_64_char_hex(self):
        """compute_checksum() returns 64-char hex string."""
        result = compute_checksum(b"test data")
        self.assertIsInstance(result, str)
        self.assertEqual(len(result), 64)
        int(result, 16)  # Must be valid hex

    def test_matches_hashlib(self):
        """Checksum should match direct hashlib SHA-256."""
        data = b"some pdf bytes"
        self.assertEqual(compute_checksum(data), hashlib.sha256(data).hexdigest())


class TestQrSvgGeneration(unittest.TestCase):
    """Tests for QR code SVG generation."""

    def test_qr_svg_is_valid(self):
        """QR SVG generation produces valid SVG."""
        gen = CertificateGeneratorV2()
        svg = gen.generate_qr_svg("https://example.com/verify/abc")
        self.assertIsInstance(svg, str)
        self.assertIn("<svg", svg)
        self.assertIn("</svg>", svg)


class TestSigningGuard(unittest.TestCase):
    """Tests for signing credential validation."""

    def test_missing_credentials_raises_error(self):
        """sign_pdf() raises SigningUnavailableError when cert files missing."""
        from unittest.mock import patch

        from utils.certificates_v2 import SigningUnavailableError, sign_pdf

        with patch("utils.certificates_v2.cert_settings") as mock_settings:
            mock_settings.private_key = Path("/nonexistent/key.pem")
            mock_settings.ca = Path("/nonexistent/ca.pem")
            with self.assertRaises(SigningUnavailableError):
                sign_pdf(b"%PDF-fake", reason="Test", contact_info="test@example.com")


class TestGenebankSignatureMetadata(unittest.TestCase):
    """Tests for signature metadata derivation.

    Föreningen Gotlandskaninen is a single association hosting both the
    Gotlandskanin and Mellerudskanin genebanks. The contact info is therefore
    constant; only the breed name in the reason text varies by genebank.
    """

    def test_gotland_individual_mentions_gotlandskanin(self):
        """Individuals from the Gotland genebank get Gotlandskanin in the reason."""
        from types import SimpleNamespace

        from utils.cert_service_v2 import _ASSOCIATION_CONTACT, _signature_metadata_for

        individual = SimpleNamespace(origin_herd=SimpleNamespace(genebank=SimpleNamespace(name="Gotland")))
        reason, contact = _signature_metadata_for(individual)
        self.assertIn("Gotlandskanin", reason)
        self.assertIn("Föreningen Gotlandskaninen", reason)
        self.assertEqual(contact, _ASSOCIATION_CONTACT)

    def test_mellerud_individual_mentions_mellerudskanin(self):
        """Individuals from the Mellerud genebank get Mellerudskanin in the reason."""
        from types import SimpleNamespace

        from utils.cert_service_v2 import _ASSOCIATION_CONTACT, _signature_metadata_for

        individual = SimpleNamespace(origin_herd=SimpleNamespace(genebank=SimpleNamespace(name="Mellerud")))
        reason, contact = _signature_metadata_for(individual)
        self.assertIn("Mellerudskanin", reason)
        self.assertIn("Föreningen Gotlandskaninen", reason)
        self.assertEqual(contact, _ASSOCIATION_CONTACT)

    def test_unknown_genebank_falls_back_gracefully(self):
        """Unknown genebank names produce valid metadata without crashing."""
        from types import SimpleNamespace

        from utils.cert_service_v2 import _ASSOCIATION_CONTACT, _signature_metadata_for

        individual = SimpleNamespace(origin_herd=SimpleNamespace(genebank=SimpleNamespace(name="Nonexistent")))
        reason, contact = _signature_metadata_for(individual)
        self.assertIn("Föreningen Gotlandskaninen", reason)
        self.assertEqual(contact, _ASSOCIATION_CONTACT)

    def test_missing_origin_herd_falls_back_gracefully(self):
        """Individuals without origin_herd still produce valid metadata."""
        from types import SimpleNamespace

        from utils.cert_service_v2 import _ASSOCIATION_CONTACT, _signature_metadata_for

        individual = SimpleNamespace(origin_herd=None)
        reason, contact = _signature_metadata_for(individual)
        self.assertIn("Föreningen Gotlandskaninen", reason)
        self.assertEqual(contact, _ASSOCIATION_CONTACT)


if __name__ == "__main__":
    unittest.main()
