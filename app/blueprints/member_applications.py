"""
Member application endpoints (Phase 8 / Story 8.2, 8.3).

Public POST for /ansok form submission; manager endpoints for listing,
reviewing, approving and rejecting applications. See ADR-0007 for
blueprint conventions and ADR-0008 for RFC 9457 problem+json.
"""

from datetime import date, datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user
from peewee import IntegrityError, fn

# DB_PROXY is the runtime proxy that data_access.py uses; importing the
# module-level DATABASE symbol directly will be None at call time.
# Note: try_auto_link_member is NOT imported here. Auto-link only
# happens in the OAuth callback (app/herdbook.py), never at approve time.
from utils.database import DB_PROXY, Genebank, Member, MemberApplication, Membership
from utils.matrikel import allocate_member_number, normalize_postal_code, write_matrikel_audit

from blueprints.common import (
    EMAIL_RE,
    json_login_required,
    matrikel_read_required,
    problem,
)

member_applications_bp = Blueprint("member_applications", __name__, url_prefix="/api")


@member_applications_bp.route("/v2/genebanks/public", methods=["GET"])
def list_public_genebanks():
    """
    Minimal unauthenticated genebank listing for the /ansok form.

    The existing `/api/genebanks` endpoint is `@login_required` and returns
    a richer payload. This endpoint intentionally exposes only id+name so
    that applicants can select their gene bank without authentication.
    """
    return jsonify({"genebanks": [{"id": g.id, "name": g.name} for g in Genebank.select().order_by(Genebank.name)]})


_MAX_FIELD_LENGTHS = {
    "first_name": 100,
    "last_name": 100,
    "email": 255,
    "phone": 50,
    "address": 1000,
    "postal_code": 10,
    "city": 100,
    "motivation": 5000,
}


@member_applications_bp.route("/v2/member-applications", methods=["POST"])
def create_application():
    """Public endpoint for /ansok form submission."""
    body = request.get_json(silent=True)
    # Reject JSON arrays / strings / nulls so `body.get(...)` below can't explode.
    if not isinstance(body, dict):
        return problem(400, "Ogiltigt anrop", "Förfrågans innehåll måste vara ett JSON-objekt")

    # Every string field must actually BE a string (or absent/null) — a JSON
    # list/number/object here would 500 on .strip() below instead of 400.
    for key in _MAX_FIELD_LENGTHS:
        value = body.get(key)
        if value is not None and not isinstance(value, str):
            return problem(
                400,
                "Ogiltigt fält",
                f"Fältet '{key}' måste vara en sträng",
                field=key,
            )

    # Trim string inputs BEFORE validating — whitespace-only values
    # should fail the presence check, not pass it.
    first_name = (body.get("first_name") or "").strip()
    last_name = (body.get("last_name") or "").strip()
    email = (body.get("email") or "").strip().lower()

    # The structured address answers BEFORE the generic length loop — an
    # overlong ort must get the contract's message, not "Fält för långt"
    city = (body.get("city") or "").strip() or None
    if city is not None and len(city) > 100:
        return problem(400, "Ogiltig adress", "Postort får vara högst 100 tecken", field="city")
    try:
        postal_code = normalize_postal_code(body.get("postal_code"))
    except ValueError as err:
        return problem(400, "Ogiltigt postnummer", str(err), field="postal_code")

    # Defend against resource-abuse via huge strings. DB would reject on
    # insert, but rejecting early keeps the request path cheap.
    for key, limit in _MAX_FIELD_LENGTHS.items():
        value = body.get(key) or ""
        if isinstance(value, str) and len(value) > limit:
            return problem(
                400,
                "Fält för långt",
                f"Fältet '{key}' överskrider maxlängden {limit} tecken",
                field=key,
            )

    missing = []
    if not first_name:
        missing.append("first_name")
    if not last_name:
        missing.append("last_name")
    if not email:
        missing.append("email")
    if missing:
        return problem(
            400,
            "Obligatoriska fält saknas",
            f"Följande fält krävs: {', '.join(missing)}",
            fields=missing,
        )

    if not EMAIL_RE.match(email):
        return problem(400, "Ogiltig e-postadress", f"'{email}' är inte en giltig e-postadress")

    if body.get("gdpr_consent") is not True:
        return problem(
            400,
            "GDPR-samtycke krävs",
            "Du måste samtycka till behandling av personuppgifter för att ansöka.",
        )

    # Membership is in the association, not a gene bank (Member Model v2).
    # A genebank_id key in the body is ignored; the column is dropped in
    # a later contract migration.
    application = MemberApplication.create(
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=(body.get("phone") or "").strip() or None,
        address=(body.get("address") or "").strip() or None,
        postal_code=postal_code,
        city=city,
        motivation=(body.get("motivation") or "").strip() or None,
        gdpr_consented_at=datetime.now(),
        status="pending",
    )

    return (
        jsonify({"id": application.id, "status": application.status}),
        201,
    )


def _application_to_dict(a: MemberApplication) -> dict:
    return {
        "id": a.id,
        "first_name": a.first_name,
        "last_name": a.last_name,
        "email": a.email,
        "phone": a.phone,
        "address": a.address,
        "postal_code": a.postal_code,
        "city": a.city,
        "motivation": a.motivation,
        "status": a.status,
        "reviewed_by_id": a.reviewed_by_id,
        "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
        "rejection_reason": a.rejection_reason,
        "created_member_id": a.created_member_id,
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat(),
    }


# All reviewer endpoints need BOTH @json_login_required (returns JSON 401
# when session is missing/expired) AND @matrikel_read_required (returns 403
# unless admin/matrikel_admin/manager). Order matters: login check first,
# then role check. Apply to every new reviewer endpoint.


@member_applications_bp.route("/v2/member-applications", methods=["GET"])
@json_login_required
@matrikel_read_required
def list_applications():
    status_filter = request.args.get("status", "pending")
    # Gene banks are gone from applications — every reviewer sees the
    # whole queue.
    q = (
        MemberApplication.select()
        .where(MemberApplication.status == status_filter)
        .order_by(MemberApplication.created_at.desc())
    )
    return jsonify({"items": [_application_to_dict(a) for a in q]})


@member_applications_bp.route("/v2/member-applications/<int:app_id>", methods=["GET"])
@json_login_required
@matrikel_read_required
def get_application(app_id: int):
    a = MemberApplication.get_or_none(MemberApplication.id == app_id)
    if a is None:
        return problem(404, "Hittades inte", f"Ansökan {app_id} finns inte")

    return jsonify(_application_to_dict(a))


@member_applications_bp.route("/v2/member-applications/count", methods=["GET"])
@json_login_required
@matrikel_read_required
def count_applications():
    status_filter = request.args.get("status", "pending")
    count = MemberApplication.select().where(MemberApplication.status == status_filter).count()
    return jsonify({status_filter: count})


@member_applications_bp.route("/v2/member-applications/<int:app_id>/approve", methods=["POST"])
@json_login_required
@matrikel_read_required
def approve_application(app_id: int):
    """Approve: one transaction allocates the next member number and creates
    Membership + huvudmedlem person row + audit.
    No gene bank anywhere; no request body is read."""
    a_peek = MemberApplication.get_or_none(MemberApplication.id == app_id)
    if a_peek is None:
        return problem(404, "Hittades inte", f"Ansökan {app_id} finns inte")

    if a_peek.status != "pending":
        return problem(
            409,
            "Redan granskad",
            f"Ansökan är redan behandlad (status: {a_peek.status})",
            created_member_id=a_peek.created_member_id,
        )

    # Duplicate contact-email check is a WARNING, not a block — families
    # legitimately share one contact email.
    duplicate_contact_email = bool(
        a_peek.email
        and Member.select()
        .where(
            fn.LOWER(Member.email) == a_peek.email.strip().lower(),
            Member.end_date.is_null(True),
        )
        .exists()
    )

    try:
        with DB_PROXY.atomic():
            a = MemberApplication.select().where(MemberApplication.id == app_id).for_update().first()
            # The row can vanish between the pre-check and the lock — guard
            # against None so a concurrent delete gives a clean 404, not a 500.
            if a is None:
                return problem(404, "Hittades inte", f"Ansökan {app_id} finns inte")
            # Re-check status inside the FOR UPDATE lock — another reviewer
            # may have approved while we were pre-checking.
            if a.status != "pending":
                return problem(
                    409,
                    "Redan granskad",
                    f"Ansökan är redan behandlad (status: {a.status})",
                    created_member_id=a.created_member_id,
                )

            membership = Membership.create(
                member_number=allocate_member_number(),
                membership_status="active",
                address=a.address,
                postal_code=a.postal_code,
                city=a.city,
                publication_consent={},
                joined_date=date.today(),
            )
            member = Member.create(
                membership=membership,
                role="huvudmedlem",
                first_name=a.first_name,
                last_name=a.last_name,
                email=a.email,
                phone=a.phone,
                gdpr_consented_at=a.gdpr_consented_at,
            )
            a.status = "approved"
            a.reviewed_by = current_user
            a.reviewed_at = datetime.now()
            a.created_member = member
            a.save()
            write_matrikel_audit(
                actor=current_user,
                action="membership_created",
                membership=membership,
                payload={
                    "application_id": a.id,
                    "member_number": membership.member_number,
                    "person_id": member.id,
                },
            )

            # Member.user_id is intentionally left NULL. Per the auto-link
            # policy, linking to an existing User requires proof of email
            # ownership in the same auth session — only Google OAuth login
            # satisfies that.
    except IntegrityError:
        # Defensive: unique member_number index — cannot fire while all
        # numbers come from the serialized counter, but a 409 beats a 500.
        return problem(409, "Medlemsnummer upptaget", "Numret är redan tilldelat — försök igen.")

    body = _application_to_dict(a)
    body["duplicate_contact_email"] = duplicate_contact_email
    return jsonify(body)


@member_applications_bp.route("/v2/member-applications/<int:app_id>/reject", methods=["POST"])
@json_login_required
@matrikel_read_required
def reject_application(app_id: int):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem(400, "Ogiltigt anrop", "Förfrågans innehåll måste vara ett JSON-objekt")
    reason = (body.get("rejection_reason") or "").strip()
    if len(reason) < 3:
        return problem(
            400,
            "Motivering krävs",
            "Motiveringen måste vara minst 3 tecken",
        )
    if len(reason) > 1000:
        return problem(
            400,
            "Motivering för lång",
            "Motiveringen får vara högst 1000 tecken",
        )

    with DB_PROXY.atomic():
        a = MemberApplication.select().where(MemberApplication.id == app_id).for_update().first()
        if a is None:
            return problem(404, "Hittades inte", f"Ansökan {app_id} finns inte")

        if a.status != "pending":
            return problem(
                409,
                "Redan granskad",
                f"Ansökan är redan behandlad (status: {a.status})",
            )

        a.status = "rejected"
        a.rejection_reason = reason
        a.reviewed_by = current_user
        a.reviewed_at = datetime.now()
        a.save()

    return jsonify(_application_to_dict(a))
