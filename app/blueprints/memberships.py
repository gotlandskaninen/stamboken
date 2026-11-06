"""
Membership and person mutation endpoints (Member Model v2).

Thin route handlers per ADR-0007 — domain logic and audit writing live in
utils/matrikel.py. All mutations require admin or matrikel_admin,
write matrikel_audit rows, and answer RFC 9457 problem+json on errors.
"""

from datetime import date

from flask import Blueprint, jsonify, request
from flask_login import current_user
from peewee import IntegrityError, fn
from utils.database import DB_PROXY, Herd, HerdAccessGrant, Member, Membership, User
from utils.matrikel import (
    VALID_PERSON_ROLES,
    AddressValidationError,
    ConfirmRequired,
    LinkError,
    add_person,
    anonymize_person,
    create_grant,
    create_membership,
    grant_is_active,
    is_anonymized,
    link_member_user,
    parse_postal_fields,
    raise_counter_to,
    renew_grant,
    resolve_own_membership,
    retire_membership,
    revoke_grant,
    soft_delete_person,
    swap_main_member,
    unlink_member_user,
    write_matrikel_audit,
)

from blueprints.common import (
    EMAIL_RE,
    json_login_required,
    matrikel_admin_required,
    problem,
)

memberships_bp = Blueprint("memberships", __name__, url_prefix="/api")

VALID_MEMBERSHIP_STATUSES = ("active", "inactive", "pending", "friexemplar")


class _MemberNumberClash(Exception):
    """Signals patch_membership's in-transaction clash re-check.

    Raised rather than returned: a `return` inside DB_PROXY.atomic() COMMITS,
    which would keep the raise_counter_to() high-water bump for a number that
    was never assigned. Caught outside the atomic, after the rollback.
    """


def _person_to_dict(p: Member, *, account_details: bool = True) -> dict:
    """Serialize a person row.

    ``account_details=False`` (self-service /v2/my-membership) publishes the
    linked account by id only and omits ``workspace_email`` (the provisioned
    login address) — a huvudmedlem has no business seeing a family member's
    login identifiers; the matrikel UI (admin routes) needs them for the Konto
    column. It also omits the keeper's ``notes`` and the consent timestamp:
    both are admin bookkeeping about the person, not part of the profil
    contract.
    """
    data = {
        "id": p.id,
        "membership_id": p.membership_id,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "email": p.email,
        "phone": p.phone,
        "role": p.role,
        "end_date": p.end_date.isoformat() if p.end_date else None,
        "user_id": p.user_id,
        "user": _account_to_dict(p.user, account_details) if p.user_id else None,
        "workspace_email": p.workspace_email,
        "gdpr_consented_at": p.gdpr_consented_at.isoformat() if p.gdpr_consented_at else None,
        "notes": p.notes,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }
    if not account_details:
        for key in ("workspace_email", "notes", "gdpr_consented_at"):
            data.pop(key)
    return data


def _account_to_dict(user, account_details: bool) -> dict:
    if not account_details:
        return {"id": user.id}
    return {"id": user.id, "username": user.username, "email": user.email}


def _membership_to_dict(ms: Membership, *, account_details: bool = True) -> dict:
    # Mutation-response serializer for POST/PATCH/DELETE /v2/memberships.
    # Intentionally distinct from members.py's same-named read serializer:
    # the frontend consumes these responses only for `id` (create) and
    # revalidation (patch/retire), then re-fetches the authoritative list/
    # detail shapes from GET /v2/members[/<id>]. It therefore does
    # NOT carry the flat main_* list fields or per-person grants; do not wire
    # a read view to this without switching to the members.py serializers.
    # account_details=False is the self-service view: the keeper's notes and
    # payment note stay out, and consent is read via /v2/members/me.
    data = {
        "id": ms.id,
        "member_number": ms.member_number,
        "membership_status": ms.membership_status,
        "address": ms.address,
        "postal_code": ms.postal_code,
        "city": ms.city,
        "postal_address": ms.postal_address,
        "publication_consent": ms.publication_consent or {},
        "payment_note": ms.payment_note,
        "joined_date": ms.joined_date.isoformat() if ms.joined_date else None,
        "notes": ms.notes,
        "created_at": ms.created_at.isoformat(),
        "updated_at": ms.updated_at.isoformat(),
        "herds": [
            {"id": h.id, "herd": h.herd, "herd_name": h.herd_name, "genebank_id": h.genebank_id}
            for h in ms.herds.order_by(Herd.id)
        ],
        "persons": [
            _person_to_dict(p, account_details=account_details)
            for p in Member.select().where(Member.membership == ms).order_by(Member.id)
        ],
    }
    if not account_details:
        for key in ("notes", "payment_note", "publication_consent"):
            data.pop(key)
    return data


def _duplicate_contact_email(email, exclude_member_id, membership=None):
    """Warn-not-block duplicate check: another ACTIVE person uses this contact email.

    ``membership`` limits the check to one household. Self-service passes it:
    a registry-wide answer would tell a huvudmedlem whether any given address
    belongs to a person in another membership.
    """
    if not email:
        return False
    query = Member.select().where(
        fn.LOWER(Member.email) == email.strip().lower(),
        Member.end_date.is_null(True),
        Member.id != exclude_member_id,
    )
    if membership is not None:
        query = query.where(Member.membership == membership)
    return query.exists()


@memberships_bp.route("/v2/memberships", methods=["POST"])
@json_login_required
@matrikel_admin_required
def create_membership_endpoint():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem(400, "Ogiltig begäran", "Begäran måste vara ett JSON-objekt")

    for key in (
        "first_name",
        "last_name",
        "email",
        "phone",
        "address",
        "payment_note",
        "notes",
        "membership_status",
    ):
        if key in body and body[key] is not None and not isinstance(body[key], str):
            return problem(400, "Ogiltigt fält", f"{key} måste vara en sträng eller null")

    first_name = (body.get("first_name") or "").strip()
    last_name = (body.get("last_name") or "").strip()
    if not first_name or not last_name:
        return problem(
            400, "Namn krävs", "first_name och last_name är obligatoriska", fields=["first_name", "last_name"]
        )
    email = (body.get("email") or "").strip() or None
    if email and not EMAIL_RE.match(email):
        return problem(400, "Ogiltig e-postadress", "email har ogiltigt format")
    status = body.get("membership_status") or "active"
    if status not in VALID_MEMBERSHIP_STATUSES:
        return problem(400, "Ogiltig status", f"'{status}' är inte en giltig status")
    if not isinstance(body.get("allocate", False), bool):
        return problem(400, "Ogiltigt fält", "allocate måste vara en boolean")

    try:
        postal = parse_postal_fields(body)
    except AddressValidationError as err:
        return problem(400, err.title, err.detail)

    membership = create_membership(
        {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone": (body.get("phone") or "").strip() or None,
            "address": (body.get("address") or "").strip() or None,
            "postal_code": postal.get("postal_code"),
            "city": postal.get("city"),
            "payment_note": (body.get("payment_note") or "").strip() or None,
            "notes": (body.get("notes") or "").strip() or None,
            "membership_status": status,
            "allocate": bool(body.get("allocate", False)),
        },
        current_user,
    )
    return jsonify(_membership_to_dict(membership)), 201


@memberships_bp.route("/v2/memberships/<int:membership_id>", methods=["DELETE"])
@json_login_required
@matrikel_admin_required
def retire_membership_endpoint(membership_id: int):
    """Soft-retire (the spec's 'delete'): status → inactive, end persons,
    revoke grants. Row-level erasure remains per-person anonymize."""
    ms = Membership.get_or_none(Membership.id == membership_id)
    if ms is None:
        return problem(404, "Hittades inte", f"Medlemskapet {membership_id} finns inte")
    retire_membership(ms, current_user)
    return jsonify(_membership_to_dict(ms))


@memberships_bp.route("/v2/memberships/<int:membership_id>", methods=["PATCH"])
@json_login_required
@matrikel_admin_required
def patch_membership(membership_id: int):
    ms = Membership.get_or_none(Membership.id == membership_id)
    if ms is None:
        return problem(404, "Hittades inte", f"Medlemskapet {membership_id} finns inte")

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem(400, "Ogiltig begäran", "Begäran måste vara ett JSON-objekt")

    # Phase 1 — validate and normalise the body into `desired` (field → value)
    # WITHOUT deciding anything against `ms`: that row was read before any lock
    # is held. What actually changes is decided under the lock.
    desired = {}

    if "membership_status" in body:
        val = body["membership_status"]
        if val not in VALID_MEMBERSHIP_STATUSES:
            return problem(400, "Ogiltig status", f"'{val}' är inte en giltig status")
        desired["membership_status"] = val

    for field in ("address", "payment_note", "notes"):
        if field in body:
            val = body[field]
            if val is not None and not isinstance(val, str):
                return problem(400, "Ogiltigt fält", f"{field} måste vara en sträng eller null")
            if field == "address":
                # The street line is trimmed on every path.
                val = (val or "").strip() or None
            desired[field] = val

    try:
        desired.update(parse_postal_fields(body))
    except AddressValidationError as err:
        return problem(400, err.title, err.detail)

    if "member_number" in body:
        raw = body["member_number"]
        if isinstance(raw, bool) or not isinstance(raw, int):
            return problem(400, "Ogiltigt medlemsnummer", "member_number måste vara ett heltal")
        if raw <= 0:
            return problem(400, "Ogiltigt medlemsnummer", "member_number måste vara större än 0")
        if raw != ms.member_number:
            # Fast path only — the answer that counts is re-run under the
            # counter lock below.
            clash = Membership.select().where(Membership.member_number == raw, Membership.id != ms.id).exists()
            if clash:
                return problem(
                    409,
                    "Medlemsnumret används redan",
                    f"Medlemsnummer {raw} tillhör ett annat medlemskap",
                )
        desired["member_number"] = raw

    if not desired:
        return jsonify(_membership_to_dict(ms))

    before = {}
    after = {}
    try:
        with DB_PROXY.atomic():
            if "member_number" in desired:
                # Lock-order rule: EVERY member_number
                # writer locks the counter row FIRST (raise_counter_to →
                # _locked_counter, FOR UPDATE) and only then touches the unique
                # index via the membership write. Approval allocates in the same
                # order; saving first and locking after would invert the order
                # and can deadlock against a concurrent approval. Taken on the
                # requested number even when it turns out unchanged: that is
                # only known once the membership row is locked, and that lock
                # has to come second.
                raise_counter_to(desired["member_number"])
            # Lock order: counter → membership (→ user → person inside
            # link_member_user). link_access_delta() reads membership_status under
            # the membership lock; a status flip that skipped it could convey herds
            # to a link committed in parallel.
            #
            # Phase 2 — re-read the row under the lock and diff the request
            # against THAT row. Diffing against the request-start read let a
            # re-submit of a status another admin had just changed pass as "no
            # change": nothing written, no audit, and the stale entity echoed
            # back as if it were current.
            ms = Membership.select().where(Membership.id == ms.id).for_update().get()
            for field, new in desired.items():
                if new != getattr(ms, field):
                    before[field] = getattr(ms, field)
                    after[field] = new
            if not after:
                return jsonify(_membership_to_dict(ms))
            if "member_number" in after:
                # Two admins can both pass the clash check above — it runs before
                # any lock. The counter row is the serialisation point for every
                # member_number writer (held FOR UPDATE until this transaction
                # commits), so re-running the query here is what turns the lost
                # race into the same 409 instead of a 500 from the unique index.
                taken = (
                    Membership.select()
                    .where(Membership.member_number == after["member_number"], Membership.id != ms.id)
                    .exists()
                )
                if taken:
                    raise _MemberNumberClash
            for field, new in after.items():
                setattr(ms, field, new)
            # ...and UPDATE only the changed columns: a full-row save would push
            # every attribute the instance carries, changed or not.
            ms.save(only=[getattr(Membership, field) for field in after] + [Membership.updated_at])
            if "member_number" in after:
                write_matrikel_audit(
                    current_user,
                    "member_number_changed",
                    ms,
                    {
                        "before": {"member_number": before["member_number"]},
                        "after": {"member_number": after["member_number"]},
                    },
                )
            if "membership_status" in after:
                write_matrikel_audit(
                    current_user,
                    "membership_status_changed",
                    ms,
                    {
                        "before": {"membership_status": before["membership_status"]},
                        "after": {"membership_status": after["membership_status"]},
                    },
                )
            other_before = {k: v for k, v in before.items() if k not in ("member_number", "membership_status")}
            other_after = {k: v for k, v in after.items() if k not in ("member_number", "membership_status")}
            if other_after:
                write_matrikel_audit(
                    current_user,
                    "membership_updated",
                    ms,
                    {"before": other_before, "after": other_after},
                )
    except _MemberNumberClash:
        # Rolled back — the counter keeps the value it had before this request.
        return problem(
            409,
            "Medlemsnumret används redan",
            f"Medlemsnummer {after['member_number']} tillhör ett annat medlemskap",
        )
    except IntegrityError:
        # The partial unique index on member_number is the backstop for the
        # window between the re-check and the write. Membership carries no other
        # unique constraint, but anything else must still surface as itself.
        if "member_number" not in after:
            raise
        return problem(
            409,
            "Medlemsnumret används redan",
            f"Medlemsnummer {after['member_number']} tillhör ett annat medlemskap",
        )

    return jsonify(_membership_to_dict(ms))


@memberships_bp.route("/v2/memberships/<int:membership_id>/persons", methods=["POST"])
@json_login_required
@matrikel_admin_required
def add_membership_person(membership_id: int):
    ms = Membership.get_or_none(Membership.id == membership_id)
    if ms is None:
        return problem(404, "Hittades inte", f"Medlemskapet {membership_id} finns inte")

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem(400, "Ogiltig begäran", "Begäran måste vara ett JSON-objekt")

    # Type-check every string field before .strip() — a JSON list/number/
    # object would otherwise 500 instead of 400 (repo precedent: member_applications.py create_application).
    for key in ("first_name", "last_name", "email", "phone", "role"):
        if key in body and body[key] is not None and not isinstance(body[key], str):
            return problem(400, "Ogiltigt fält", f"{key} måste vara en sträng eller null")

    first_name = (body.get("first_name") or "").strip()
    last_name = (body.get("last_name") or "").strip()
    if not first_name or not last_name:
        return problem(
            400,
            "Namn krävs",
            "first_name och last_name är obligatoriska",
            fields=["first_name", "last_name"],
        )
    email = (body.get("email") or "").strip() or None
    if email and not EMAIL_RE.match(email):
        return problem(400, "Ogiltig e-postadress", "email har ogiltigt format")
    phone = (body.get("phone") or "").strip() or None
    role = body.get("role") or "familjemedlem"

    try:
        person = add_person(
            ms,
            {"first_name": first_name, "last_name": last_name, "email": email, "phone": phone, "role": role},
            current_user,
        )
    except ValueError as err:
        # Covers unknown role and "inactive membership" (add_person's guard).
        return problem(400, "Kan inte lägga till person", str(err))
    except IntegrityError:
        return problem(409, "Huvudmedlem finns redan", "Medlemskapet har redan en aktiv huvudmedlem")

    data = _person_to_dict(person)
    data["duplicate_contact_email"] = _duplicate_contact_email(email, person.id)
    return jsonify(data), 201


@memberships_bp.route("/v2/persons/<int:person_id>", methods=["PATCH"])
@json_login_required
@matrikel_admin_required
def patch_person(person_id: int):
    person = Member.get_or_none(Member.id == person_id)
    if person is None:
        return problem(404, "Hittades inte", f"Personen {person_id} finns inte")

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem(400, "Ogiltig begäran", "Begäran måste vara ett JSON-objekt")

    # Validation (400s) runs on the body alone, before the transaction; the
    # values are applied to the row re-read under the membership lock below.
    proposed = {}

    for field in ("first_name", "last_name"):
        if field in body:
            val = (body[field] or "").strip() if isinstance(body[field], str) else ""
            if not val:
                return problem(400, "Ogiltigt namn", f"{field} får inte vara tomt")
            proposed[field] = val

    if "email" in body:
        if body["email"] is not None and not isinstance(body["email"], str):
            return problem(400, "Ogiltigt fält", "email måste vara en sträng eller null")
        val = (body["email"] or "").strip() or None
        if val and not EMAIL_RE.match(val):
            return problem(400, "Ogiltig e-postadress", "email har ogiltigt format")
        proposed["email"] = val

    for field in ("phone", "notes"):
        if field in body:
            val = body[field]
            if val is not None and not isinstance(val, str):
                return problem(400, "Ogiltigt fält", f"{field} måste vara en sträng eller null")
            proposed[field] = val

    if "role" in body:
        role = body["role"]
        if role not in VALID_PERSON_ROLES:
            return problem(400, "Ogiltig roll", f"'{role}' är inte en giltig roll")
        proposed["role"] = role

    membership_id = person.membership_id
    try:
        with DB_PROXY.atomic():
            # Lock order root: membership FOR UPDATE, then re-read
            # the person under it BEFORE applying the body. A GDPR erasure
            # (utils.matrikel.anonymize_person) that committed while this
            # request was in flight would otherwise get the body's name, phone
            # and e-mail written straight back onto the scrubbed row.
            Membership.select().where(Membership.id == membership_id).for_update().get()
            person = Member.get_or_none(Member.id == person_id)
            if person is None:
                return problem(404, "Hittades inte", f"Personen {person_id} finns inte")
            if is_anonymized(person):
                # GDPR erasure is the only state that blocks the edit: an ended
                # (soft-deleted) person stays editable exactly as before
                # (ADR-0006), an erased one must never take PII back.
                return problem(409, "Personen är anonymiserad", "En anonymiserad person kan inte ändras")

            before = {}
            after = {}
            for field, val in proposed.items():
                if field == "role" and val != person.role:
                    if person.role == "huvudmedlem" and person.end_date is None:
                        return problem(
                            409,
                            "Huvudmedlem kan inte nedgraderas",
                            "Byt huvudmedlem via main-member-endpointen istället",
                        )
                    if val == "huvudmedlem":
                        # Promotion conveys the membership's herds to a linked
                        # account (User.effective_herd_ids) — only
                        # swap_main_member() may do that: membership lock +
                        # main_member_changed audit, headless memberships
                        # included. PATCH never sets huvudmedlem.
                        return problem(
                            409,
                            "Huvudmedlem sätts via main-member-endpointen",
                            "Byt huvudmedlem via main-member-endpointen istället",
                        )
                if val != getattr(person, field):
                    before[field] = getattr(person, field)
                    after[field] = val
                    setattr(person, field, val)

            if not after:
                return jsonify(_person_to_dict(person))

            # UPDATE only what this body changed: a full-row save() would write
            # member.user_id back from the re-read copy too, and the audit rows
            # must name exactly the columns that moved. `role` stays in `after`,
            # so the huvudmedlem IntegrityError backstop below still fires.
            person.save(only=[getattr(Member, field) for field in after] + [Member.updated_at])
            write_matrikel_audit(
                current_user,
                "person_updated",
                person.membership,
                {"person_id": person.id, "before": before, "after": after},
            )
    except IntegrityError:
        return problem(409, "Huvudmedlem finns redan", "Medlemskapet har redan en aktiv huvudmedlem")

    return jsonify(_person_to_dict(person))


@memberships_bp.route("/v2/persons/<int:person_id>", methods=["DELETE"])
@json_login_required
@matrikel_admin_required
def delete_person(person_id: int):
    person = Member.get_or_none(Member.id == person_id)
    if person is None:
        return problem(404, "Hittades inte", f"Personen {person_id} finns inte")
    try:
        soft_delete_person(person, current_user)
    except ValueError as err:
        return problem(409, "Kan inte ta bort", str(err))
    return jsonify(_person_to_dict(person))


@memberships_bp.route("/v2/persons/<int:person_id>/anonymize", methods=["POST"])
@json_login_required
@matrikel_admin_required
def anonymize_person_endpoint(person_id: int):
    person = Member.get_or_none(Member.id == person_id)
    if person is None:
        return problem(404, "Hittades inte", f"Personen {person_id} finns inte")
    # The caller's pre-lock instance is stale after the scrub — serialise the
    # instance the operation re-read and wrote under its locks.
    person = anonymize_person(person, current_user)
    return jsonify(_person_to_dict(person))


@memberships_bp.route("/v2/memberships/<int:membership_id>/main-member", methods=["POST"])
@json_login_required
@matrikel_admin_required
def set_main_member(membership_id: int):
    ms = Membership.get_or_none(Membership.id == membership_id)
    if ms is None:
        return problem(404, "Hittades inte", f"Medlemskapet {membership_id} finns inte")
    body = request.get_json(silent=True)
    person_raw = body.get("person_id") if isinstance(body, dict) else None
    if isinstance(person_raw, bool) or not isinstance(person_raw, int):
        return problem(400, "Ogiltig person", "person_id måste vara ett heltal")
    person = Member.get_or_none(Member.id == person_raw)
    if person is None:
        return problem(404, "Hittades inte", f"Personen {person_raw} finns inte")
    try:
        swap_main_member(ms, person, current_user)
    except ValueError as err:
        return problem(409, "Ogiltigt byte av huvudmedlem", str(err))
    return jsonify(_membership_to_dict(ms))


# [Next.js] Phase 19 — kontokoppling
@memberships_bp.route("/v2/persons/<int:person_id>/link-user", methods=["POST"])
@json_login_required
@matrikel_admin_required
def link_person_user(person_id: int):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem(400, "Ogiltig begäran", "Begäran måste vara ett JSON-objekt")
    user_id = body.get("user_id")
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        return problem(400, "Ogiltigt konto", "user_id måste vara ett heltal")
    confirm = body.get("confirm", False)
    if not isinstance(confirm, bool):
        return problem(400, "Ogiltigt fält", "confirm måste vara en boolean")
    confirmed = body.get("confirmed_herd_ids")
    if confirmed is not None and (
        not isinstance(confirmed, list) or any(isinstance(x, bool) or not isinstance(x, int) for x in confirmed)
    ):
        return problem(400, "Ogiltigt fält", "confirmed_herd_ids måste vara en lista med heltal")
    if Member.get_or_none(Member.id == person_id) is None:
        return problem(404, "Hittades inte", f"Personen {person_id} finns inte")
    if User.get_or_none(User.id == user_id) is None:
        return problem(404, "Hittades inte", f"Användaren {user_id} finns inte")
    try:
        person, _conveyed = link_member_user(
            person_id, user_id, actor=current_user, mode="admin", confirmed_herd_ids=confirmed if confirm else None
        )
    except ConfirmRequired as needs:
        return problem(
            409,
            "Kopplingen ger besättningsåtkomst",
            "Bekräfta att kontot får ägaråtkomst till besättningarna",
            type="confirm-required",
            conveys_herds=[{"id": h["id"], "herd": h["herd"], "herd_name": h["herd_name"]} for h in needs.conveys],
        )
    except LinkError as err:
        return problem(err.status, err.title, err.detail, **err.extensions)
    return jsonify(_person_to_dict(person))


# [Next.js]
@memberships_bp.route("/v2/persons/<int:person_id>/link-user", methods=["DELETE"])
@json_login_required
@matrikel_admin_required
def unlink_person_user(person_id: int):
    if Member.get_or_none(Member.id == person_id) is None:
        return problem(404, "Hittades inte", f"Personen {person_id} finns inte")
    try:
        person, _lost = unlink_member_user(person_id, actor=current_user)
    except LinkError as err:
        return problem(err.status, err.title, err.detail, **err.extensions)
    return jsonify(_person_to_dict(person))


# [Next.js] Lightweight picker search — matrikel_admin, never admin fields
@memberships_bp.route("/v2/users/search", methods=["GET"])
@json_login_required
@matrikel_admin_required
def search_users():
    q = (request.args.get("q") or "").strip().lower()
    if len(q) < 2:
        return problem(400, "För kort sökning", "Ange minst två tecken")
    pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = (
        User.select(User.id, User.username, User.email)
        .where(
            User.is_active == True,  # noqa: E712
            (fn.LOWER(User.username) % pattern) | (fn.LOWER(User.email) % pattern),
        )
        # COLLATE "C": byte order, so the test's Python sort agrees with PostgreSQL
        .order_by(User.username.collate('"C"'), User.id)
        .limit(10)
    )
    return jsonify({"users": [{"id": u.id, "username": u.username, "email": u.email} for u in rows]})


def _grant_to_dict(g: HerdAccessGrant) -> dict:
    return {
        "id": g.id,
        "member_id": g.member_id,
        "herd_id": g.herd_id,
        "herd": g.herd.herd,
        "valid_until": g.valid_until.isoformat() if g.valid_until else None,
        "revoked_at": g.revoked_at.isoformat() if g.revoked_at else None,
        "granted_by_id": g.granted_by_id,
        "active": grant_is_active(g),
        "created_at": g.created_at.isoformat(),
        "updated_at": g.updated_at.isoformat(),
    }


@memberships_bp.route("/v2/persons/<int:person_id>/grants", methods=["POST"])
@json_login_required
@matrikel_admin_required
def create_person_grant(person_id: int):
    # matrikel_admin/admin may grant on ANY herd — the own-herd restriction
    # applies only to the main-member self-service path.
    person = Member.get_or_none(Member.id == person_id)
    if person is None:
        return problem(404, "Hittades inte", f"Personen {person_id} finns inte")

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem(400, "Ogiltig begäran", "Begäran måste vara ett JSON-objekt")

    herd_raw = body.get("herd_id")
    if isinstance(herd_raw, bool) or not isinstance(herd_raw, int):
        return problem(400, "Ogiltig besättning", "herd_id måste vara ett heltal")
    herd = Herd.get_or_none(Herd.id == herd_raw)
    if herd is None:
        return problem(404, "Hittades inte", f"Besättningen {herd_raw} finns inte")

    valid_until = None
    if body.get("valid_until") is not None:
        try:
            valid_until = date.fromisoformat(body["valid_until"])
        except (TypeError, ValueError):
            return problem(400, "Ogiltigt datum", "valid_until måste vara YYYY-MM-DD")

    try:
        grant = create_grant(person, herd, valid_until, current_user)
    except ValueError as err:
        return problem(409, "Ogiltigt tillstånd", str(err))
    return jsonify(_grant_to_dict(grant)), 201


@memberships_bp.route("/v2/grants/<int:grant_id>/renew", methods=["POST"])
@json_login_required
@matrikel_admin_required
def renew_person_grant(grant_id: int):
    grant = HerdAccessGrant.get_or_none(HerdAccessGrant.id == grant_id)
    if grant is None:
        return problem(404, "Hittades inte", f"Tillståndet {grant_id} finns inte")
    try:
        grant = renew_grant(grant, current_user)
    except ValueError as err:
        return problem(409, "Kan inte förnyas", str(err))
    return jsonify(_grant_to_dict(grant))


@memberships_bp.route("/v2/grants/<int:grant_id>", methods=["DELETE"])
@json_login_required
@matrikel_admin_required
def revoke_person_grant(grant_id: int):
    grant = HerdAccessGrant.get_or_none(HerdAccessGrant.id == grant_id)
    if grant is None:
        return problem(404, "Hittades inte", f"Tillståndet {grant_id} finns inte")
    grant = revoke_grant(grant, current_user)
    return jsonify(_grant_to_dict(grant))


def _require_main_member():
    """Resolve the caller's active person row and require role huvudmedlem.

    Must be called inside an open DB_PROXY.atomic() block: it takes the
    membership row FOR UPDATE and re-reads the person under that lock, so a
    concurrent main-member swap, unlink or GDPR erasure (each of which
    serializes on the same membership lock) cannot leave a stale
    authorization for the rest of the request. The linkage is re-checked
    under the lock too, not only the role — resolve_own_membership() ran
    before the lock was granted.
    Returns (person, None) on success, (None, <problem response>) otherwise.
    """
    me = resolve_own_membership(current_user)
    if me is None:
        return None, problem(404, "Ingen medlemskoppling", "Ditt konto är inte kopplat till någon medlemspost")
    Membership.select().where(Membership.id == me.membership_id).for_update().get()
    me = Member.select().where(Member.id == me.id).for_update().first()  # re-read under the lock
    if me is None or is_anonymized(me) or me.user_id != current_user.id:
        # The account was unlinked or the person erased mid-request (both
        # detach) — same title as the self-service /me routes: reload, never
        # act on the membership with an authorization that no longer holds.
        # The detail is deliberately NOT save-shaped: this gate also fronts the
        # two DELETE routes (persons, grants), which save nothing.
        return None, problem(
            409,
            "Kontot är inte längre kopplat",
            "Ditt konto är inte längre kopplat till medlemskapet — ladda om sidan",
        )
    if me.end_date is not None or me.role != "huvudmedlem":
        return None, problem(403, "Endast huvudmedlem", "Endast huvudmedlemmen kan administrera medlemskapet")
    return me, None


@memberships_bp.route("/v2/my-membership", methods=["GET"])
@json_login_required
def get_my_membership():
    me = resolve_own_membership(current_user)
    if me is None:
        return problem(404, "Ingen medlemskoppling", "Ditt konto är inte kopplat till någon medlemspost")
    membership = me.membership
    if me.role == "huvudmedlem":
        persons = list(
            Member.select().where(Member.membership == membership, Member.end_date.is_null(True)).order_by(Member.id)
        )
    else:
        # Non-main persons see only their own entry (read-only in the UI).
        persons = [me]
    person_dicts = []
    for p in persons:
        entry = _person_to_dict(p, account_details=False)
        entry["grants"] = [
            _grant_to_dict(g)
            for g in HerdAccessGrant.select().where(HerdAccessGrant.member == p).order_by(HerdAccessGrant.id)
        ]
        person_dicts.append(entry)
    data = _membership_to_dict(membership, account_details=False)
    data["persons"] = person_dicts
    # Herds nested inside membership (frontend reads
    # myMembership.membership.herds) — the herds the main member may grant
    # access to.
    data["herds"] = [
        {"id": h.id, "herd": h.herd, "herd_name": h.herd_name}
        for h in Herd.select().where(Herd.membership == membership).order_by(Herd.id)
    ]
    return jsonify({"is_main_member": me.role == "huvudmedlem", "membership": data})


@memberships_bp.route("/v2/my-membership/persons", methods=["POST"])
@json_login_required
def my_membership_add_person():
    with DB_PROXY.atomic():
        me, err = _require_main_member()
        if err is not None:
            return err

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return problem(400, "Ogiltig begäran", "Begäran måste vara ett JSON-objekt")

        # Type-check every string field before .strip() — a JSON list/number/
        # object would otherwise 500 instead of 400.
        for key in ("first_name", "last_name", "email", "phone", "role"):
            if key in body and body[key] is not None and not isinstance(body[key], str):
                return problem(400, "Ogiltigt fält", f"{key} måste vara en sträng eller null")

        first_name = (body.get("first_name") or "").strip()
        last_name = (body.get("last_name") or "").strip()
        if not first_name or not last_name:
            return problem(
                400,
                "Namn krävs",
                "first_name och last_name är obligatoriska",
                fields=["first_name", "last_name"],
            )
        email = (body.get("email") or "").strip() or None
        if email and not EMAIL_RE.match(email):
            return problem(400, "Ogiltig e-postadress", "email har ogiltigt format")
        phone = (body.get("phone") or "").strip() or None
        role = body.get("role") or "familjemedlem"
        if role not in ("familjemedlem", "skotare"):
            return problem(400, "Ogiltig roll", "Endast familjemedlem eller skötare kan läggas till via självservice")

        try:
            person = add_person(
                me.membership,
                {"first_name": first_name, "last_name": last_name, "email": email, "phone": phone, "role": role},
                current_user,
            )
        except ValueError as verr:
            # add_person rejects an inactive membership (its FOR UPDATE guard).
            return problem(400, "Kan inte lägga till person", str(verr))
        data = _person_to_dict(person, account_details=False)
        data["duplicate_contact_email"] = _duplicate_contact_email(email, person.id, me.membership)
        return jsonify(data), 201


@memberships_bp.route("/v2/my-membership/persons/<int:person_id>", methods=["DELETE"])
@json_login_required
def my_membership_delete_person(person_id: int):
    with DB_PROXY.atomic():
        me, err = _require_main_member()
        if err is not None:
            return err
        person = Member.get_or_none(Member.id == person_id, Member.membership == me.membership)
        if person is None:
            return problem(404, "Hittades inte", f"Personen {person_id} finns inte i ditt medlemskap")
        try:
            soft_delete_person(person, current_user)
        except ValueError as verr:
            return problem(409, "Kan inte ta bort", str(verr))
        return jsonify(_person_to_dict(person, account_details=False))


@memberships_bp.route("/v2/my-membership/persons/<int:person_id>/grants", methods=["POST"])
@json_login_required
def my_membership_create_grant(person_id: int):
    with DB_PROXY.atomic():
        me, err = _require_main_member()
        if err is not None:
            return err
        person = Member.get_or_none(Member.id == person_id, Member.membership == me.membership)
        if person is None:
            return problem(404, "Hittades inte", f"Personen {person_id} finns inte i ditt medlemskap")

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return problem(400, "Ogiltig begäran", "Begäran måste vara ett JSON-objekt")
        herd_raw = body.get("herd_id")
        if isinstance(herd_raw, bool) or not isinstance(herd_raw, int):
            return problem(400, "Ogiltig besättning", "herd_id måste vara ett heltal")
        herd = Herd.get_or_none(Herd.id == herd_raw)
        if herd is None:
            return problem(404, "Hittades inte", f"Besättningen {herd_raw} finns inte")
        if herd.membership_id != me.membership_id:
            return problem(
                403,
                "Inte medlemskapets besättning",
                "Tillstånd kan bara ges till medlemskapets egna besättningar",
            )

        valid_until = None
        if body.get("valid_until") is not None:
            try:
                valid_until = date.fromisoformat(body["valid_until"])
            except (TypeError, ValueError):
                return problem(400, "Ogiltigt datum", "valid_until måste vara YYYY-MM-DD")

        try:
            grant = create_grant(person, herd, valid_until, current_user)
        except ValueError as verr:
            return problem(409, "Ogiltigt tillstånd", str(verr))
        return jsonify(_grant_to_dict(grant)), 201


def _own_membership_grant(grant_id: int, me: Member):
    """Resolve a grant for self-service: BOTH the granted person and the
    grant's herd must belong to the caller's membership. Checking only the
    person would let a main member renew an admin-issued grant on a FOREIGN
    herd — restoring access self-service is explicitly not allowed to create
    (main member grants are 'own herds only'). Foreign-herd grants are admin-managed end to end."""
    grant = HerdAccessGrant.get_or_none(HerdAccessGrant.id == grant_id)
    if grant is None or grant.member.membership_id != me.membership_id:
        return None, problem(404, "Hittades inte", f"Tillståndet {grant_id} finns inte i ditt medlemskap")
    if grant.herd.membership_id != me.membership_id:
        return None, problem(
            403,
            "Inte medlemskapets besättning",
            "Tillståndet gäller en annan medlems besättning och hanteras av föreningen",
        )
    return grant, None


@memberships_bp.route("/v2/my-membership/grants/<int:grant_id>/renew", methods=["POST"])
@json_login_required
def my_membership_renew_grant(grant_id: int):
    with DB_PROXY.atomic():
        me, err = _require_main_member()
        if err is not None:
            return err
        grant, err = _own_membership_grant(grant_id, me)
        if err is not None:
            return err
        try:
            grant = renew_grant(grant, current_user)
        except ValueError as verr:
            return problem(409, "Kan inte förnyas", str(verr))
        return jsonify(_grant_to_dict(grant))


@memberships_bp.route("/v2/my-membership/grants/<int:grant_id>", methods=["DELETE"])
@json_login_required
def my_membership_revoke_grant(grant_id: int):
    with DB_PROXY.atomic():
        me, err = _require_main_member()
        if err is not None:
            return err
        grant, err = _own_membership_grant(grant_id, me)
        if err is not None:
            return err
        grant = revoke_grant(grant, current_user)
        return jsonify(_grant_to_dict(grant))
