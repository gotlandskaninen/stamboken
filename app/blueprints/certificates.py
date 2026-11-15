"""
Certificate v2 endpoints — thin route handlers.

PDF generation in cert_service_v2.py, data assembly in cert_acess.py.
See ADR-0007 for conventions. Each route marked # [Next.js].
"""

import logging
import os

import utils.data_access as da
import utils.database as db
from flask import Blueprint, jsonify, request, session
from peewee import DoesNotExist
from utils.cert_service_v2 import (
    CERTIFICATE_V2_FIELDS,
    certificate_form,
    certificate_update,
    check_first_certificate_quota,
    generate_and_store,
    invalidate_caches,
    normalize_color,
    update_breeding_if_changed,
)
from utils.certificates_v2 import (
    SigningUnavailableError,
    compute_checksum,
    verify_pdf_signature,
)
from utils.individual_commands import assign_certificate_number
from utils.individual_number_v2 import RosterAliveExceeds6w

from .common import json_login_required, problem

logger = logging.getLogger("herdbook.cert_v2_api")

certificates_bp = Blueprint("certificates_v2", __name__, url_prefix="/api")


class _IndividualUpdateError(Exception):
    """Internal: raised inside DB transaction to trigger rollback when
    da.update_individual() or da.update_breeding() returns an error dict instead of raising.
    Carries the dict's problem_status/title (e.g. 409 for a pedigree cycle), else 400."""

    def __init__(self, result):
        super().__init__(result.get("message", "Kunde inte uppdatera individen"))
        self.status = result.get("problem_status", 400)
        self.title = result.get("title", "Bad Request")
        self.rows = result.get("rows", [])
        # roster_alive_exceeds_6w: how many kits the breeder must mark dead
        self.extra = {key: result[key] for key in ("must_mark_dead",) if key in result}


def _check_certificate_quota(individual_id):
    """The first-certificate rules of validate_first_certificate.

    Refused like POST /v2/individual: 400 with the error key as detail.
    """
    try:
        check_first_certificate_quota(individual_id)
    except RosterAliveExceeds6w as exc:
        raise _IndividualUpdateError({"message": str(exc), "must_mark_dead": exc.must_mark_dead}) from exc
    except ValueError as exc:
        raise _IndividualUpdateError({"message": str(exc)}) from exc


def _reread_under_lock(individual_id, user, form):
    """The rabbit as committed, read under the caller's lock, and its certificate form on that row.

    The route's read predates the lock: writing it back would revert a death, origin correction or
    renumber committed since, and authority is decided on the origin herd as it is now.
    certificate_form drops id/number: issuance stays pinned to the URL rabbit.
    """
    individual = db.Individual.get_by_id(individual_id)
    if individual.voided:
        raise _IndividualUpdateError({"message": "Individual not found", "problem_status": 404, "title": "Not Found"})
    if not user.can_issue_certificate(individual):
        raise _IndividualUpdateError(
            {
                "message": "Du har inte behörighet att utfärda intyg för denna kanin",
                "problem_status": 403,
                "title": "Forbidden",
            }
        )
    return individual, certificate_update(individual.as_dict(), form)


def _cert_entity(cert_row):
    """Build JSON entity from a DigitalCertificateV2 row."""
    return {
        "id": cert_row.id,
        "individual_number": cert_row.individual.number,
        "verification_token": str(cert_row.verification_token),
        "certificate_type": cert_row.certificate_type,
        "digital_certificate": cert_row.individual.digital_certificate,
        "issued_by": cert_row.issued_by.fullname or "Uppfödare",
        "issued_at": cert_row.issued_at.isoformat(),
        "checksum": cert_row.checksum,
    }


@certificates_bp.route("/v2/certificates/issue/<i_number>", methods=["POST"])  # [Next.js]
@json_login_required
def issue_certificate(i_number):
    """Issue a new v2 certificate for an individual."""
    user_id = session.get("user_id", None)
    user = da.fetch_user_info(user_id)

    ind_dict = da.get_individual(i_number, user_id)
    if ind_dict is None:
        return problem(404, "Not Found", f"Individual {i_number} not found")

    try:
        individual = db.Individual.get(db.Individual.number == i_number)
    except DoesNotExist:
        return problem(404, "Not Found", f"Individual {i_number} not found")

    if not user.can_issue_certificate(individual):
        return problem(403, "Forbidden", "Du har inte behörighet att utfärda intyg för denna kanin")

    if individual.digital_certificate is not None:
        return problem(400, "Bad Request", "Certifikat finns redan — använd update-endpointen")

    # A blank paper number (legacy stores "") is no certificate and counts as none (certified_count).
    if individual.certificate:
        return problem(400, "Bad Request", "Papperscertifikat finns redan — konvertera via update-endpointen")

    form = certificate_form(request.json, CERTIFICATE_V2_FIELDS)

    # The breeder keeps certificate authority after a transfer, but editing
    # individual data still requires edit rights on the current herd.
    can_edit_individual = user.can_edit(individual.id)
    if form and not can_edit_individual:
        return problem(
            403, "Forbidden", "Kaninen tillhör en annan besättning — du kan utfärda intyg men inte ändra uppgifter"
        )

    form = normalize_color(form, individual)
    try:
        breeding_id = da.canonical_breeding_id(ind_dict.get("breeding"))
    except ValueError as exc:
        return problem(400, "Bad Request", str(exc))

    # One transaction around individual update + certificate generation: a
    # signing/S3 failure must not leave the individual marked as certified
    # without a certificate row.
    try:
        with db.DATABASE.atomic():
            if can_edit_individual:
                # Global lock order up front: Breeding, then the rabbit + the litter's parents in one
                # ascending call — update_breeding_if_changed locks those parents.
                da.lock_individual_for_edit(individual.id, breeding_id, with_parents=True)
            else:
                da.lock_individual_for_edit(individual.id)  # the litter lock the quota is decided under
            individual, ind_dict = _reread_under_lock(individual.id, user, form)
            if individual.digital_certificate is not None or individual.certificate:
                raise _IndividualUpdateError({"message": "Intyg finns redan — använd update-endpointen"})
            if can_edit_individual:
                # Litter sizes first: update_individual checks the litter quota against the
                # litter_size6w this request sets.
                result = update_breeding_if_changed(ind_dict, form, user_id)
                if result and result.get("status") == "error":
                    raise _IndividualUpdateError(result)
                result = da.update_individual(
                    ind_dict, user_id, issue_digital=True, genebank_change_reason=form.get("reason")
                )
                if isinstance(result, dict) and result.get("status") == "error":
                    raise _IndividualUpdateError(result)
            else:
                _check_certificate_quota(individual.id)
                assign_certificate_number(individual)
            # update_individual mutates ind_dict in place (parents/color become
            # Peewee objects) — refetch the canonical dict before rendering, or
            # the PDF silently loses its pedigree. By id: the URL number may be stale.
            individual = db.Individual.get_by_id(individual.id)
            ind_dict = da.get_individual(individual.number, user_id)
            cert_row, _ = generate_and_store(individual, user, ind_dict, user_id)
    except _IndividualUpdateError as exc:
        return problem(exc.status, exc.title, str(exc), rows=exc.rows, **exc.extra)
    except da.HerdTrackingError as exc:  # e.g. 409: the litter changed before the lock
        return problem(exc.status, exc.title, exc.detail, rows=exc.rows)
    except SigningUnavailableError:
        return problem(503, "Service Unavailable", "Certifikatsignering är tillfälligt otillgänglig")

    invalidate_caches(individual)
    return jsonify(_cert_entity(cert_row)), 201


@certificates_bp.route("/v2/certificates/update/<i_number>", methods=["PATCH"])  # [Next.js]
@json_login_required
def update_certificate(i_number):
    """Re-issue/update a certificate (v1->v2 upgrade or v2 re-issue)."""
    user_id = session.get("user_id", None)
    user = da.fetch_user_info(user_id)

    ind_dict = da.get_individual(i_number, user_id)
    if ind_dict is None:
        return problem(404, "Not Found", f"Individual {i_number} not found")

    try:
        individual = db.Individual.get(db.Individual.number == i_number)
    except DoesNotExist:
        return problem(404, "Not Found", f"Individual {i_number} not found")

    if not user.can_issue_certificate(individual):
        return problem(403, "Forbidden", "Du har inte behörighet att uppdatera intyg för denna kanin")

    if individual.digital_certificate is None and not individual.certificate:
        return problem(400, "Bad Request", "Inget certifikat att uppdatera — utfärda ett nytt först")

    form = certificate_form(request.json, CERTIFICATE_V2_FIELDS)

    can_edit_individual = user.can_edit(individual.id)
    if form and not can_edit_individual:
        return problem(
            403, "Forbidden", "Kaninen tillhör en annan besättning — du kan utfärda intyg men inte ändra uppgifter"
        )

    form = normalize_color(form, individual)
    try:
        breeding_id = da.canonical_breeding_id(ind_dict.get("breeding"))
    except ValueError as exc:
        return problem(400, "Bad Request", str(exc))

    try:
        with db.DATABASE.atomic():
            if can_edit_individual:
                # Global lock order up front: Breeding, then the rabbit + the litter's parents in one
                # ascending call — update_breeding_if_changed locks those parents.
                da.lock_individual_for_edit(individual.id, breeding_id, with_parents=True)
            else:
                da.lock_individual_for_edit(individual.id)
            individual, ind_dict = _reread_under_lock(individual.id, user, form)
            # Paper→digital conversion assigns a digital number (this also clears
            # the paper certificate, in IssueDigitalCertificate or the scoped helper).
            issue_digital = individual.digital_certificate is None
            if issue_digital and not individual.certificate:
                raise _IndividualUpdateError({"message": "Inget certifikat att uppdatera — utfärda ett nytt först"})
            if can_edit_individual:
                result = da.update_individual(
                    ind_dict, user_id, issue_digital=issue_digital, genebank_change_reason=form.get("reason")
                )
                if isinstance(result, dict) and result.get("status") == "error":
                    raise _IndividualUpdateError(result)
                result = update_breeding_if_changed(ind_dict, form, user_id)
                if result and result.get("status") == "error":
                    raise _IndividualUpdateError(result)
            elif issue_digital:
                assign_certificate_number(individual)
            individual = db.Individual.get_by_id(individual.id)
            ind_dict = da.get_individual(individual.number, user_id)
            cert_row, _ = generate_and_store(individual, user, ind_dict, user_id)
    except _IndividualUpdateError as exc:
        return problem(exc.status, exc.title, str(exc), rows=exc.rows, **exc.extra)
    except da.HerdTrackingError as exc:  # e.g. 409: the litter changed before the lock
        return problem(exc.status, exc.title, exc.detail, rows=exc.rows)
    except SigningUnavailableError:
        return problem(503, "Service Unavailable", "Certifikatsignering är tillfälligt otillgänglig")

    invalidate_caches(individual)
    return jsonify(_cert_entity(cert_row)), 200


@certificates_bp.route("/v2/certificates/<i_number>")  # [Next.js]
@json_login_required
def download_certificate(i_number):
    """Download the latest v2 certificate PDF."""
    user_id = session.get("user_id", None)

    ind_dict = da.get_individual(i_number, user_id)
    if ind_dict is None:
        return problem(404, "Not Found", f"Individual {i_number} not found")

    try:
        individual = db.Individual.get(db.Individual.number == i_number)
    except DoesNotExist:
        return problem(404, "Not Found", f"Individual {i_number} not found")

    if not da.fetch_user_info(user_id).can_view_certificate(individual):
        return problem(403, "Forbidden", "Bara ägaren, uppfödaren och genbanksansvarig kan hämta intyget")

    try:
        cert = (
            db.DigitalCertificateV2.select()
            .where(
                (db.DigitalCertificateV2.individual == individual) & (db.DigitalCertificateV2.is_current == True)  # noqa: E712
            )
            .get()
        )
    except DoesNotExist:
        # Legacy fallback only for v1-certified individuals. The v2 pipeline
        # uploads to S3 before the DB commit, so a rolled-back issuance can
        # leave an orphaned legacy-key PDF — without this guard that orphan
        # would be served here despite the individual never being certified.
        if individual.digital_certificate is None:
            return problem(404, "Not Found", "Inget certifikat finns")

        from utils.cert_acess import create_pdf_response, download_certificate_s3

        try:
            cert_bytes = download_certificate_s3(i_number)
            return create_pdf_response(cert_bytes, f"{i_number}_certificate.pdf")
        except Exception:
            logger.exception("S3 certificate download failed for %s", i_number)
            return problem(404, "Not Found", "Inget certifikat finns")

    full_path = os.path.join("uppladdningar", cert.file_path)
    if not os.path.exists(full_path):
        # Disk copy lost — try the token-named S3 copy before giving up.
        from utils.cert_acess import create_pdf_response, download_certificate_v2

        try:
            pdf_bytes = download_certificate_v2(cert.verification_token)
            return create_pdf_response(pdf_bytes, f"{i_number}_certificate.pdf")
        except Exception:
            logger.exception("S3 v2 certificate fallback failed for %s", i_number)
            return problem(404, "Not Found", "Certifikatfil saknas")

    with open(full_path, "rb") as f:
        pdf_bytes = f.read()

    from utils.cert_acess import create_pdf_response

    return create_pdf_response(pdf_bytes, f"{i_number}_certificate.pdf")


@certificates_bp.route("/v2/certificates/preview/<i_number>")  # [Next.js]
@json_login_required
def preview_certificate(i_number):
    """Generate an unsigned preview PDF (not stored)."""
    user_id = session.get("user_id", None)

    ind_dict = da.get_individual(i_number, user_id)
    if ind_dict is None:
        return problem(404, "Not Found", f"Individual {i_number} not found")

    try:
        individual = db.Individual.get(db.Individual.number == i_number)
    except DoesNotExist:
        return problem(404, "Not Found", f"Individual {i_number} not found")

    if not da.fetch_user_info(user_id).can_view_certificate(individual):
        return problem(403, "Forbidden", "Bara ägaren, uppfödaren och genbanksansvarig kan hämta intyget")

    from utils.cert_service_v2 import _generator, build_cert_data, compute_doc_hash_stub

    cert_data = build_cert_data(individual, ind_dict, user_id)
    cert_data["digital_certificate"] = individual.digital_certificate or "PREVIEW"
    cert_data["replaces_date"] = ""
    cert_data["doc_hash_stub"] = compute_doc_hash_stub(cert_data)

    pdf_bytes = _generator.generate_pedigree(cert_data, qr_url="https://example.com/preview")

    from utils.cert_acess import create_pdf_response

    return create_pdf_response(pdf_bytes, f"{i_number}_preview.pdf")


@certificates_bp.route("/v2/certificates/verify/<token>", methods=["GET"])  # [Next.js]
def verify_certificate_get(token):
    """Public: look up certificate metadata by verification token."""
    try:
        cert = db.DigitalCertificateV2.get(db.DigitalCertificateV2.verification_token == token)
    except (DoesNotExist, ValueError):
        return problem(404, "Not Found", "Intyget kunde inte hittas")

    individual = cert.individual

    # Superseded check: an authentic but re-issued certificate is no longer
    # the current version — the page shows the newer issue date.
    replaced_by_date = None
    if not cert.is_current:
        newest = (
            db.DigitalCertificateV2.select()
            .where(
                (db.DigitalCertificateV2.individual == individual) & (db.DigitalCertificateV2.is_current == True)  # noqa: E712
            )
            .first()
        )
        replaced_by_date = newest.issued_at.isoformat() if newest else None

    return jsonify(
        {
            "verified": True,
            "certificate_type": cert.certificate_type,
            "individual_name": individual.name,
            "individual_number": individual.number,
            "genebank": individual.origin_herd.genebank.name if individual.origin_herd else "",
            "digital_certificate": individual.digital_certificate,
            "issued_by": cert.issued_by.fullname or "Uppfödare",
            "issued_at": cert.issued_at.isoformat(),
            "is_current": cert.is_current,
            "replaced_by_date": replaced_by_date,
        }
    )


@certificates_bp.route("/v2/certificates/verify/<token>", methods=["POST"])  # [Next.js]
def verify_certificate_post(token):
    """Public: verify uploaded PDF against stored checksum + signature."""
    try:
        cert = db.DigitalCertificateV2.get(db.DigitalCertificateV2.verification_token == token)
    except (DoesNotExist, ValueError):
        return problem(404, "Not Found", "Intyget kunde inte hittas")

    uploaded_pdf = request.get_data()
    if not uploaded_pdf:
        return problem(400, "Bad Request", "Ingen PDF-data skickades")
    if not uploaded_pdf.startswith(b"%PDF"):
        return problem(400, "Bad Request", "Filen är inte en giltig PDF")

    checksum_match = compute_checksum(uploaded_pdf) == cert.checksum

    # Pinned to the association CA — signature_valid must attest that the PDF
    # was signed by Föreningen Gotlandskaninen, not merely carry any
    # cryptographically valid signature. Shared with the legacy verify path.
    signature_valid = verify_pdf_signature(uploaded_pdf)

    return jsonify(
        {
            "verified": checksum_match and signature_valid,
            "checksum_match": checksum_match,
            "signature_valid": signature_valid,
        }
    )
