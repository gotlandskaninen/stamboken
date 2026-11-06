"""
Certificate generation pipeline v2: WeasyPrint (HTML->PDF) + pyHanko (digital signatures).
"""

import hashlib
import io
import logging
from pathlib import Path

import qrcode
import qrcode.image.svg
from jinja2 import Environment, FileSystemLoader
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers
from pyhanko.sign.fields import SigSeedSubFilter
from weasyprint import HTML

from utils.settings import certs as cert_settings

logger = logging.getLogger("herdbook.cert")

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "certificates"


class CertificateGeneratorV2:
    """Generates pedigree certificates as PDFs from HTML templates."""

    def __init__(self, template_dir=None):
        tpl_dir = template_dir or _TEMPLATE_DIR
        # nosemgrep: python.flask.security.xss.audit.direct-use-of-jinja2.direct-use-of-jinja2
        self.env = Environment(loader=FileSystemLoader(str(tpl_dir)), autoescape=True)

    def generate_pedigree(self, data, qr_url):
        """Render the pedigree HTML template and convert to PDF bytes.

        Args:
            data: dict with keys matching FORM_KEYS from certificates.py
            qr_url: URL for the QR code (public verification link)

        Returns:
            bytes: PDF document
        """
        qr_svg = self.generate_qr_svg(qr_url)
        template = self.env.get_template("pedigree.html")
        # nosemgrep: python.flask.security.xss.audit.direct-use-of-jinja2.direct-use-of-jinja2
        html = template.render(qr_svg=qr_svg, **data)
        return HTML(string=html, base_url=str(self.env.loader.searchpath[0])).write_pdf()

    def generate_qr_svg(self, url):
        """Generate a QR code as an inline SVG string."""
        factory = qrcode.image.svg.SvgPathImage
        qr = qrcode.QRCode(
            version=2,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(image_factory=factory)
        return img.to_string(encoding="unicode")


class SigningUnavailableError(Exception):
    """Raised when signing credentials are not available."""


def sign_pdf(pdf_bytes, reason, contact_info, location="Sweden"):
    """Sign a PDF using pyHanko with PAdES-B-B.

    Args:
        pdf_bytes: bytes of the unsigned PDF
        reason: signing reason (e.g. "Signerat för Gotlandskaninen")
        contact_info: signer contact (e.g. "admin@gotlandskaninen.se")
        location: signing location, defaults to "Sweden"

    Returns:
        bytes: signed PDF
    """
    if not cert_settings.private_key.exists() or not cert_settings.ca.exists():
        raise SigningUnavailableError(
            f"Signing credentials not found: key={cert_settings.private_key}, ca={cert_settings.ca}"
        )
    signer = signers.SimpleSigner.load(
        str(cert_settings.private_key),
        str(cert_settings.ca),
        key_passphrase=None,
    )
    w = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes))
    result = signers.sign_pdf(
        w,
        signers.PdfSignatureMetadata(
            field_name="Signature1",
            subfilter=SigSeedSubFilter.PADES,
            reason=reason,
            location=location,
            contact_info=contact_info,
        ),
        signer=signer,
    )
    return result.getvalue()


def compute_checksum(pdf_bytes):
    """Return SHA-256 hex digest of pdf_bytes."""
    return hashlib.sha256(pdf_bytes).hexdigest()


def verify_pdf_signature(pdf_bytes):
    """Return True iff pdf_bytes carries a signature that validates against our pinned CA.

    Shared by the legacy `POST /api/certificates/verify/{x}` path and the v2
    verify endpoint. The association signs with a self-signed certificate that
    is used both as signer and trust root; pyHanko accepts that shape, whereas
    endesive >= 2.19 (cryptography's strict RFC 5280 path validator) rejects it
    as "basicConstraints.cA must not be asserted in an EE certificate" for
    every certificate ever issued. `strict=False` is needed to read the PDFs
    the old endesive pipeline produced. Any parse or validation failure means
    "not valid", never an exception.

    The signature must cover the document as uploaded: `bottom_line` alone
    tolerates form filling in a later, unsigned revision, which would let
    anyone change the name on a certificate and still have it verify.
    """
    # Imported lazily: pyhanko's validation stack is heavy and only needed here.
    from pyhanko.keys import load_cert_from_pemder
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.diff_analysis import ModificationLevel
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    try:
        validation_context = ValidationContext(
            trust_roots=[load_cert_from_pemder(str(ca)) for ca in cert_settings.trust_cas if ca.is_file()],
            allow_fetching=False,
        )
        reader = PdfFileReader(io.BytesIO(pdf_bytes), strict=False)
        for sig in reader.embedded_signatures:
            status = validate_pdf_signature(sig, signer_validation_context=validation_context)
            if status.bottom_line and status.modification_level == ModificationLevel.NONE:
                return True
    except Exception:  # pylint: disable=broad-except
        logger.info("PDF signature validation failed", exc_info=True)
    return False
