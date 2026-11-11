"""
Certificate v2 service — generate, sign, store, and manage v2 certificates.

This module contains the business logic extracted from the blueprint to keep
route handlers thin (ADR-0007). The blueprint handles HTTP/auth/error mapping.
"""

import json
import logging
import os
import uuid
from datetime import date

import utils.data_access as da
import utils.database as db
from utils import number_assets
from utils.cert_acess import get_certificate_data, upload_certificate, upload_certificate_v2
from utils.certificate_lifecycle import Event, check
from utils.certificates_v2 import (
    CertificateGeneratorV2,
    compute_checksum,
    sign_pdf,
)
from utils.individual_number_v2 import validate_first_certificate
from utils.settings import certs as cert_settings
from utils.settings import service as service_settings

logger = logging.getLogger("herdbook.cert_service_v2")

_generator = CertificateGeneratorV2()

# Association-level signature metadata. Föreningen Gotlandskaninen issues
# certificates for both the Gotlandskanin and Mellerudskanin genebanks, so the
# signer (the association) is the same regardless of which genebank the
# individual belongs to. The reason text mentions the specific genebank for
# traceability, but the contact info is the association's single address.
_ASSOCIATION_CONTACT = "admin@gotlandskaninen.se"
_GENEBANK_TO_BREED = {
    "Gotland": "Gotlandskanin",
    "Mellerud": "Mellerudskanin",
}


def _signature_metadata_for(individual):
    """Return (reason, contact_info) tuple for a certificate signature.

    Föreningen Gotlandskaninen is the signing authority for both genebanks,
    so contact_info is constant. The reason is parameterised with the breed
    name of the individual's origin genebank for traceability.
    """
    genebank_name = ""
    if individual.origin_herd and individual.origin_herd.genebank:
        genebank_name = individual.origin_herd.genebank.name or ""
    breed = _GENEBANK_TO_BREED.get(genebank_name, "genbankskanin")
    reason = f"Signerat av Föreningen Gotlandskaninen för {breed}"
    if cert_settings.demo_watermark:
        reason = f"DEMO – EJ GILTIGT INTYG. {reason}"
    return reason, _ASSOCIATION_CONTACT


def build_cert_data(individual, ind_data, user_id):
    """Assemble template data for the v2 certificate (Template A "Liggare").

    get_certificate_data() merges color_note into notes for the v1 template —
    capture the raw values first, since the v2 template renders them as
    separate fields. Dates are ISO (YYYY-MM-DD) per the design handoff.
    """
    raw_notes = ind_data.get("notes") or ""
    raw_color_note = ind_data.get("color_note") or ""

    cert_data = get_certificate_data(ind_data, user_id)
    cert_data["notes"] = raw_notes
    cert_data["color_note"] = raw_color_note
    cert_data["foot_ring"] = ind_data.get("foot_ring") or ""
    # Color-code system (herdbookcolors) is not in the DB yet — the template
    # skips the chip when empty.
    cert_data["color_code"] = ""
    cert_data["issue_date"] = date.today().isoformat()
    cert_data["public_url"] = f"gotlandskaninen.se/stamboken/individ/{individual.number}"
    cert_data["digital_certificate"] = individual.digital_certificate
    cert_data["demo_watermark"] = cert_settings.demo_watermark
    return cert_data


def compute_doc_hash_stub(cert_data):
    """First 8 hex chars (uppercase) of SHA-256 over the certificate data.

    The stub is printed inside the PDF footer, so it cannot be the hash of
    the final PDF (chicken-and-egg). Per the design handoff's alternative,
    hash the canonical data content instead.
    """
    hashable = {k: str(v) for k, v in cert_data.items() if k != "doc_hash_stub"}
    canonical = json.dumps(hashable, sort_keys=True, ensure_ascii=False)
    return compute_checksum(canonical.encode("utf-8"))[:8].upper()


def generate_and_store(individual, user, ind_data, user_id):
    """Generate, sign, and store a v2 certificate.

    Order of operations (Fix 2 — failure-safe ordering):
    1. Generate + sign PDF (before any DB changes)
    2. Write to filesystem
    3. Upload to S3 (fail the request if S3 fails) — first the token-named
       v2 key (certifikat/v2/{token}.pdf) so downloads survive disk loss,
       then the legacy v1 key ({ind_number}/certificate.pdf, overwritten
       per re-issue)
    4. In a DATABASE.atomic() transaction: create DigitalCertificateV2 row
       + retire the old current row

    The blueprint wraps this call in an outer DATABASE.atomic() together with
    update_individual, so a signing/S3 failure also rolls back the
    digital_certificate assignment on the individual. On rollback an orphaned
    PDF may remain on disk/S3 — harmless, no DB row references it.

    Returns (cert_row, signed_pdf).
    Raises SigningUnavailableError if signing credentials are missing.
    Raises Exception if S3 upload fails.
    """
    token = uuid.uuid4()
    qr_url = f"{service_settings.host}/stamboken/verifiera/{token}"

    cert_data = build_cert_data(individual, ind_data, user_id)

    # Re-issue: reference the certificate this one replaces (printed as
    # "Ersätter intyg utfärdat …"). Read before the atomic block flips it.
    prev = (
        db.DigitalCertificateV2.select()
        .where(
            (db.DigitalCertificateV2.individual == individual) & (db.DigitalCertificateV2.is_current == True)  # noqa: E712
        )
        .first()
    )
    cert_data["replaces_date"] = prev.issued_at.date().isoformat() if prev else ""
    cert_data["doc_hash_stub"] = compute_doc_hash_stub(cert_data)

    # Step 1: Generate + sign PDF (no DB/S3 side effects yet)
    pdf_bytes = _generator.generate_pedigree(cert_data, qr_url=qr_url)
    reason, contact_info = _signature_metadata_for(individual)
    signed_pdf = sign_pdf(pdf_bytes, reason=reason, contact_info=contact_info)

    sha = compute_checksum(signed_pdf)
    file_path = os.path.join("certifikat", "v2", f"{token}.pdf")
    full_path = os.path.join("uppladdningar", file_path)

    # Step 2: Write to filesystem. The directory is created here, not at import: the demo API
    # mounts uppladdningar read-only and must still start.
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "wb") as f:
        f.write(signed_pdf)

    # Step 3: Upload to S3 — fail the request if this fails.
    # Token-named v2 key first: if it fails, the discoverable legacy v1 key
    # is untouched, so the rolled-back request leaves nothing downloadable.
    # An orphaned token object (legacy upload failing after) is harmless —
    # no DB row references it.
    upload_certificate_v2(pdf_bytes=signed_pdf, token=token)
    # The legacy key is the number: wait for a renumber still moving its assets after its commit
    # (number_assets.finish), or that move would put the older PDF over this one. As a photo upload does.
    number_assets.lock_number(individual.number, xact=True)
    upload_certificate(pdf_bytes=signed_pdf, ind_number=individual.number)

    # Step 4: DB transaction — create row + flip old rows
    with db.DATABASE.atomic():
        before = individual.cert_state()
        cert_row = db.DigitalCertificateV2.issue_current(
            individual,
            verification_token=token,
            certificate_type="pedigree",
            issued_by=user,
            file_path=file_path,
            checksum=sha,
        )
        check(before, Event.ISSUE_PDF, individual.cert_state())

    return cert_row, signed_pdf


def normalize_color(form, individual):
    """Normalize color_id from form data to Color object lookup."""
    color_id = form.get("color_id")
    if color_id is not None:
        try:
            color = db.Color.get(db.Color.id == color_id)
            form["color"] = color.name
        except db.Color.DoesNotExist:
            pass
        form.pop("color_id", None)
    return form


# What the legacy certificate form sends (individual_certificate.tsx), plus v2's color_id.
CERTIFICATE_FORM_FIELDS = frozenset(
    {
        "name",
        "sex",
        "color",
        "color_id",
        "color_note",
        "eye_color",
        "claw_color",
        "belly_color",
        "hair_notes",
        "notes",
        "has_photo",
        "litter_size",
        "litter_size6w",
    }
)
# v2 also takes a sale and the reason for an admin's genebank correction: update_individual applies
# the transfer rules to them, and the PDF is rendered from the re-read rabbit.
CERTIFICATE_V2_FIELDS = CERTIFICATE_FORM_FIELDS | {"herd", "selling_date", "reason"}


def certificate_form(body, fields=CERTIFICATE_FORM_FIELDS):
    """The part of a certificate request body the certificate may change.

    Everything outside `fields` (number, certificate numbers, litter, parents, birth date; on
    legacy also herd and sale) is ignored: the certificate is rendered from the stored rabbit.
    """
    if not isinstance(body, dict):
        return {}
    return {key: value for key, value in body.items() if key in fields}


def certificate_update(ind_data, form):
    """The update_individual form for a certificate: the stored rabbit plus the certificate form.

    mother/father are left out: they are litter data, not Individual fields, and update_individual
    refuses an unknown one (founder, import) with "Invalid parents".
    """
    return {**{key: value for key, value in ind_data.items() if key not in ("mother", "father")}, **form}


def check_first_certificate_quota(individual_id):
    """validate_first_certificate for the rabbit's litter as stored now.

    Call under the caller's Breeding lock, after any litter-size update and before the first
    certificate number is written. Raises ValueError("certificate_quota_exceeded").
    """
    breeding_id = db.Individual.get_by_id(individual_id).breeding_id
    if breeding_id is not None:
        validate_first_certificate(db.Breeding.get_by_id(breeding_id))


def update_breeding_if_changed(ind_data, form, user_id):
    """Update Breeding record if litter_size or litter_size6w changed.

    Returns update_breeding's result (an error dict refuses the certificate), or None when
    nothing changed.
    """
    breeding_id = ind_data.get("breeding")
    if not breeding_id:
        return None
    breed_data = db.Breeding.get(db.Breeding.id == breeding_id).as_dict()
    # JSON payloads may carry litter sizes as strings — cast before comparing
    # so "5" vs 5 doesn't trigger a redundant update_breeding call.
    try:
        l_size = int(form["litter_size"]) if form.get("litter_size") is not None else form.get("litter_size")
        l_size6w = int(form["litter_size6w"]) if form.get("litter_size6w") is not None else form.get("litter_size6w")
    except (TypeError, ValueError):
        return {"status": "error", "message": "Unknown litter size."}
    if ("litter_size" in form and breed_data.get("litter_size") != l_size) or (
        "litter_size6w" in form and breed_data.get("litter_size6w") != l_size6w
    ):
        if "litter_size" in form:
            breed_data["litter_size"] = l_size
        if "litter_size6w" in form:
            breed_data["litter_size6w"] = l_size6w
        return da.update_breeding(breed_data, user_id)
    return None


def invalidate_caches(individual):
    """Invalidate caches after certificate changes."""
    try:
        from utils.cache_invalidation import get_genebank_id_for_herd, trigger_invalidation

        origin_herd = individual.origin_herd
        herd_code = origin_herd.herd if origin_herd else ""
        for gid in get_genebank_id_for_herd(herd_code):
            trigger_invalidation(gid)
    except Exception as e:
        logger.warning(f"Cache invalidation failed after certificate update: {e}")
