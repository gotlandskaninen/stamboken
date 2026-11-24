"""
Matrikel endpoints (Member Model v2).

Flat membership rows with expandable person rows. Reads are gated by
matrikel_read_required (admin/matrikel_admin/manager), writes and export by
matrikel_admin_required. Self-service /me endpoints put person fields on the
Member row and address/consent on the Membership. See ADR-0007 and ADR-0008.
"""

import csv
import io
import re
import secrets
from datetime import date, datetime, timezone

import utils.settings as settings
from flask import Blueprint, Response, jsonify, request, session
from flask_login import current_user
from peewee import IntegrityError
from utils.csv_safe import csv_safe
from utils.data_access import session_holds
from utils.database import BILLING_FIELDS, DB_PROXY, AuditLog, Herd, HerdAccessGrant, Member, Membership, User
from utils.herd_contact import on_membership_active
from utils.login_code import (
    AddressTaken,
    CodeLoginClosed,
    CodeRefused,
    cancel,
    check,
    consume,
    issue,
    refuse_unsafe,
    reserve_login_address,
)
from utils.mail import _normalize, enqueue_mail
from utils.matrikel import (
    AddressValidationError,
    is_anonymized,
    membership_recipient,
    parse_postal_fields,
    set_member_email,
    set_membership_status,
    write_matrikel_audit,
)
from utils.members import (
    CONSENT_KEYS,
    PROFILE_CONSENT_TEXT_VERSION,
    consent_answered,
    effective_consent,
    set_consent,
    stored_consent,
)
from utils.membership_lifecycle import Status, TransitionRefused

from blueprints.common import (
    EMAIL_RE,
    json_login_required,
    matrikel_admin_required,
    matrikel_read_required,
    membership_organization_fields,
    problem,
)

members_bp = Blueprint("members", __name__, url_prefix="/api")

VALID_MEMBERSHIP_STATUSES = tuple(Status)


def _person_to_dict(p: Member) -> dict:
    return {
        "id": p.id,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "email": p.email,
        "phone": p.phone,
        "role": p.role,
        "end_date": p.end_date.isoformat() if p.end_date else None,
        "user_id": p.user_id,
        "user": {"id": p.user.id, "username": p.user.username, "email": p.user.email} if p.user_id else None,
        "workspace_email": p.workspace_email,
        "gdpr_consented_at": p.gdpr_consented_at.isoformat() if p.gdpr_consented_at else None,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


def _membership_to_dict(ms: Membership, persons: list[Member] | None = None) -> dict:
    # Flat main-member fields (None-safe) match the frontend MembershipRow
    # contract (matrikel/types.ts): the matrikel list renders
    # main_first_name/main_last_name/main_email/main_phone directly.
    # `persons` may be pre-fetched by the caller (list endpoint batches them).
    if persons is None:
        persons = list(Member.select().where(Member.membership == ms).order_by(Member.id))
    main = next((p for p in persons if p.role == "huvudmedlem" and p.end_date is None), None)
    return {
        "id": ms.id,
        "member_number": ms.member_number,
        **membership_organization_fields(ms, account_details=True),
        "membership_status": ms.membership_status,
        "address": ms.address,
        "postal_code": ms.postal_code,
        "city": ms.city,
        "postal_address": ms.postal_address,
        **{field: getattr(ms, field) for field in BILLING_FIELDS},
        "publication_consent": effective_consent(ms),
        "payment_note": ms.payment_note,
        "joined_date": ms.joined_date.isoformat() if ms.joined_date else None,
        "notes": ms.notes,
        "main_first_name": main.first_name if main else None,
        "main_last_name": main.last_name if main else None,
        "main_email": main.email if main else None,
        "main_phone": main.phone if main else None,
        "persons": [_person_to_dict(p) for p in persons],
        "created_at": ms.created_at.isoformat(),
        "updated_at": ms.updated_at.isoformat(),
    }


def _parse_int_arg(name: str, default: int, minimum: int = 1, maximum: int | None = None):
    """Defensively parse an integer query-string parameter.

    Returns the default on missing; raises a problem-response-compatible
    ValueError on bogus input so the caller can convert to 400.
    """
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{name} måste vara ett heltal") from e
    if value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


@members_bp.route("/v2/members", methods=["GET"])
@json_login_required
@matrikel_read_required
def list_members():
    q = Membership.select()

    search = request.args.get("search", "").strip()
    if search:
        like = f"%{search}%"
        person_match = Member.select(Member.membership).where(
            (Member.first_name**like) | (Member.last_name**like) | (Member.email**like)
        )
        match = Membership.id.in_(person_match) | (Membership.organization_name**like)
        # A purely numeric search also matches on member number. ASCII-only:
        # isdigit() alone accepts characters int() rejects (e.g. "²"), and the
        # length cap bounds the value to int4 before conversion.
        if search.isascii() and search.isdigit() and len(search) <= 10:
            number = int(search)
            if number <= 2_147_483_647:
                match = match | (Membership.member_number == number)
        q = q.where(match)

    status = request.args.get("status")
    if status:
        q = q.where(Membership.membership_status == status)

    try:
        page = _parse_int_arg("page", default=1, minimum=1)
        per_page = _parse_int_arg("per_page", default=25, minimum=1, maximum=100)
    except ValueError as e:
        return problem(400, "Ogiltig frågeparameter", str(e))

    total = q.count()
    items = list(q.order_by(Membership.member_number.asc(nulls="LAST"), Membership.id).paginate(page, per_page))

    # One person query for the whole page — otherwise _membership_to_dict
    # re-queries the persons of every membership on the page (per_page
    # extra round trips on the busiest matrikel endpoint).
    persons_by_membership: dict[int, list[Member]] = {}
    if items:
        for person in Member.select().where(Member.membership.in_([ms.id for ms in items])).order_by(Member.id):
            persons_by_membership.setdefault(person.membership_id, []).append(person)

    return jsonify(
        {
            "items": [_membership_to_dict(ms, persons_by_membership.get(ms.id, [])) for ms in items],
            "total": total,
            "page": page,
            "per_page": per_page,
        }
    )


@members_bp.route("/v2/members/<int:membership_id>", methods=["GET"])
@json_login_required
@matrikel_read_required
def get_membership(membership_id: int):
    ms = Membership.get_or_none(Membership.id == membership_id)
    if ms is None:
        return problem(404, "Hittades inte", f"Medlemskapet {membership_id} finns inte")

    data = _membership_to_dict(ms)
    data["herds"] = [
        {"id": h.id, "herd": h.herd, "herd_name": h.herd_name, "genebank_id": h.genebank_id, "is_active": h.is_active}
        for h in Herd.select().where(Herd.membership == ms)
    ]
    # Nest grants per person (frontend Person.grants), each with
    # the herd code string. No top-level grants[] array — the detail page
    # reads persons[].grants[].
    grants_by_person: dict[int, list] = {}
    for g in (
        HerdAccessGrant.select(HerdAccessGrant, Herd)
        .join(Herd)
        .where(HerdAccessGrant.member << [p["id"] for p in data["persons"]])
    ):
        grants_by_person.setdefault(g.member_id, []).append(
            {
                "id": g.id,
                "member_id": g.member_id,
                "herd_id": g.herd_id,
                "herd": g.herd.herd,
                "valid_until": g.valid_until.isoformat() if g.valid_until else None,
                "revoked_at": g.revoked_at.isoformat() if g.revoked_at else None,
            }
        )
    for person in data["persons"]:
        person["grants"] = grants_by_person.get(person["id"], [])
    return jsonify(data)


@members_bp.route("/v2/members/<int:membership_id>", methods=["PATCH"])
@json_login_required
@matrikel_admin_required
def patch_membership(membership_id: int):
    ms = Membership.get_or_none(Membership.id == membership_id)
    if ms is None:
        return problem(404, "Hittades inte", f"Medlemskapet {membership_id} finns inte")

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem(400, "Ogiltigt anrop", "Förfrågans innehåll måste vara ett JSON-objekt")

    new_status = None
    if "membership_status" in body:
        new_status = body["membership_status"]
        if new_status not in VALID_MEMBERSHIP_STATUSES:
            return problem(400, "Ogiltig status", f"'{new_status}' är inte en giltig status")
    if "notes" in body and body["notes"] is not None and not isinstance(body["notes"], str):
        # A JSON list/number/object would 500 on .strip() below instead of 400.
        return problem(400, "Ogiltigt fält", "notes måste vara en sträng eller null")

    try:
        with DB_PROXY.atomic():
            # Decide from the row AS LOCKED, never from the request-start read
            # Two admins both see `active`, one deactivates, and the
            # other's stale `active` would otherwise look like "no change" — no
            # audit row — while its UPDATE put the status back, and with it every
            # linked huvudmedlem's herd access (same rule as memberships.py).
            ms = Membership.select().where(Membership.id == ms.id).for_update().get()
            changed = []
            activated = False
            if new_status is not None and new_status != ms.membership_status:
                activated = set_membership_status(ms, new_status, current_user)
                changed.append(Membership.membership_status)
            if "notes" in body:
                ms.notes = (body["notes"] or "").strip() or None
                changed.append(Membership.notes)
            # UPDATE only the changed columns — a full-row save would push every
            # attribute the instance carries, changed or not.
            ms.save(only=changed + [Membership.updated_at])
            if activated:  # after the save: the comparison reads the saved membership (#117)
                on_membership_active(ms.id)
    except AddressTaken:
        return problem(409, AddressTaken.title, "En annan medlem kan redan logga in med e-postadressen")
    except TransitionRefused:
        # Raised, not returned: a `return` inside atomic() would commit the rest of the request.
        return problem(
            409,
            "Medlemskapet är avslutat",
            "Ett inaktivt medlemskap utan huvudmedlem kan inte byta status. Utse en ny huvudmedlem, "
            "eller skapa ett nytt medlemskap om inga personer finns kvar.",
        )
    return jsonify(_membership_to_dict(ms))


def _member_for_current_user() -> Member | None:
    return Member.get_or_none((Member.user == current_user.id) & Member.end_date.is_null(True))


def _relock_me(membership_id: int, person_id: int):
    """Re-read the caller's person row under the membership lock.

    Both self-service mutations authorize on a row read at request start, so a
    main-member swap, an unlink or a GDPR erasure committing in between would
    leave them writing on a stale authorization. Every one of those writers
    takes this membership row FOR UPDATE first, so re-deciding under it is the
    serialization point — role included, not just the linkage.

    Lock order: membership, then person, both FOR UPDATE.
    Returns (person, membership, None) when the request may save,
    (None, None, <problem response>) otherwise.
    """
    ms = Membership.select().where(Membership.id == membership_id).for_update().get()
    m = Member.select().where(Member.id == person_id).for_update().first()
    # Anonymized (GDPR erasure) or no longer this account's ACTIVE row —
    # _member_for_current_user() only ever returns an ACTIVE linked row, so an
    # ended or detached one means the link went away mid-request.
    if m is None or is_anonymized(m) or m.end_date is not None or m.user_id != current_user.id:
        return (
            None,
            None,
            problem(409, "Kontot är inte längre kopplat", "Uppgifterna kunde inte sparas — ladda om sidan"),
        )
    if m.role != "huvudmedlem":
        # Same 403 the pre-lock gate answers: a demotion that committed while
        # this request was in flight must not let the ex-main member write the
        # household's address or consent.
        return (
            None,
            None,
            problem(403, "Endast huvudmedlem", "Endast huvudmedlemmen kan ändra medlemskapets uppgifter."),
        )
    return m, ms, None


def _me_response(m: Member) -> dict:
    ms = m.membership
    data = _person_to_dict(m)
    data["membership"] = {
        "id": ms.id,
        "member_number": ms.member_number,
        **membership_organization_fields(ms, account_details=False),
        "membership_status": ms.membership_status,
        "address": ms.address,
        "postal_code": ms.postal_code,
        "city": ms.city,
        "postal_address": ms.postal_address,
        "joined_date": ms.joined_date.isoformat() if ms.joined_date else None,
    }
    data["publication_consent"] = effective_consent(ms)
    # Additive: {} = never answered. The profil page needs it to
    # decide whether the first Spara must submit all four keys — a partial
    # PATCH of an all-off answer would otherwise leave the row "ej angivet".
    data["consent_answered"] = consent_answered(ms)
    main = (
        Member.select(Member.first_name, Member.last_name, Member.role, Membership.id, Membership.organization_name)
        .join(Membership)
        .where(Member.membership == ms, Member.role == "huvudmedlem", Member.end_date.is_null(True))
        .order_by(Member.id)
        .first()
    )
    # Additive: /v2/my-membership hides other persons from
    # non-main members, so the profile card gets the name here.
    data["main_member_name"] = main.display_name if main else None
    return data


@members_bp.route("/v2/members/me", methods=["GET"])
@json_login_required
def get_me():
    m = _member_for_current_user()
    if m is None or m.membership_id is None:
        return problem(
            404,
            "Medlem saknas",
            "Ingen medlemspost är kopplad till ditt konto. Kontakta din genbanksansvarige.",
        )
    return jsonify(_me_response(m))


@members_bp.route("/v2/members/me/contact", methods=["PATCH"])
@json_login_required
def patch_me_contact():
    m = _member_for_current_user()
    if m is None or m.membership_id is None:
        return problem(404, "Medlem saknas", "Ingen medlemspost är kopplad till ditt konto.")
    if m.role != "huvudmedlem":
        # Persons who are not main members see their entry READ-ONLY —
        # address/consent are household-level and belong to the main member
        return problem(
            403,
            "Endast huvudmedlem",
            "Endast huvudmedlemmen kan ändra medlemskapets uppgifter.",
        )

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem(400, "Ogiltigt anrop", "Uppdateringen måste vara ett JSON-objekt")

    # Every string field must actually BE a string (or null) — a JSON
    # list/number/object would 500 on .strip()/save below instead of 400
    # (repo precedent: member_applications.py create_application).
    for key in ("phone", "address"):
        if key in body and body[key] is not None and not isinstance(body[key], str):
            return problem(400, "Ogiltigt fält", f"{key} måste vara en sträng eller null")

    # Track exactly which columns this body touches — a full-row save() would
    # write member.user_id and membership_status back from the instance this
    # request read: it would NULL a link
    # committed in between, resurrect one an admin just removed, or undo a
    # status flip and restore herd access. Values are collected here and applied
    # to the rows re-read under the membership lock below.
    person_updates: dict[str, str | None] = {}
    membership_updates: dict[str, str | None] = {}

    if "phone" in body:
        person_updates["phone"] = (body["phone"] or "").strip() or None

    # The e-mail is never written here: a new address gets a code (_ask_for_code), and the change waits for it.
    new_email = None
    if "email" in body:
        raw_email = body["email"]
        if not isinstance(raw_email, str):
            return problem(400, "Ogiltigt fält", "email måste vara en sträng")
        new_email = raw_email.strip().lower()
        if not EMAIL_RE.match(new_email):
            return problem(400, "Ogiltig e-postadress", f"'{new_email}' är inte en giltig e-postadress")
        if new_email == (m.email or "").strip().lower():
            new_email = None  # the form sends the address on every save
        elif _normalize(new_email) is None:  # the sender would refuse it, and the code would never arrive
            return problem(400, "Ogiltig e-postadress", f"'{new_email}' är inte en giltig e-postadress")
    refused = None
    if new_email is not None and settings.service.demo_instance:
        # The demo never replaces an account's mark (new_generation): the change could not end the sessions.
        refused, new_email = DEMO_REFUSAL, None

    try:
        # Split keys only — the postal_address alias is an admin/legacy input,
        # never a self-service one. Unknown keys
        # stay ignored, as they always were on this route.
        postal = parse_postal_fields({k: body[k] for k in ("postal_code", "city") if k in body})
    except AddressValidationError as err:
        return problem(400, err.title, err.detail)
    if "address" in body:
        # The postal address lives on the membership — one address change
        # per household.
        membership_updates["address"] = (body["address"] or "").strip() or None
    membership_updates.update(postal)

    person_id, membership_id = m.id, m.membership_id
    try:
        # Both writes in one transaction — a contact PATCH is one edit, and the
        # membership row must not survive a person write that conflicts.
        with DB_PROXY.atomic():
            # Lock order root: membership FOR UPDATE, then re-read
            # the person under it BEFORE applying the body. A GDPR erasure
            # (utils.matrikel.anonymize_person), an unlink or a main-member swap
            # that committed while this request was in flight would otherwise
            # get the body's phone, e-mail and address written straight back
            # onto the scrubbed, detached or demoted row.
            m, ms, err = _relock_me(membership_id, person_id)
            if err is not None:
                return err
            changed = [f for f, v in membership_updates.items() if getattr(ms, f) != v]
            changed += [f for f, v in person_updates.items() if getattr(m, f) != v]
            if changed:  # D19: a paper form signed before this change must not overwrite it; the names only
                payload = {"person_id": m.id, "fields": changed, "source": "profil"}
                write_matrikel_audit(current_user, "kontakt_andrad", ms, payload)
            for field, value in person_updates.items():
                setattr(m, field, value)
            for field, value in membership_updates.items():
                setattr(ms, field, value)
            if membership_updates:
                ms.save(only=[getattr(Membership, f) for f in membership_updates] + [Membership.updated_at])
            m.save(only=[getattr(Member, f) for f in person_updates] + [Member.updated_at])
            if new_email is not None:
                if ms.membership_status == Status.FRIEXEMPLAR:
                    refused, new_email = "E-postadressen för ett friexemplar kan bara bytas i matrikeln.", None
                else:
                    refuse_unsafe()
                    _ask_for_code(m, new_email)
    except CodeRefused:
        return _codes_unavailable()
    except IntegrityError:
        # DEAD BACKSTOP: the legacy
        # per-genebank contact-email index `idx_member_genebank_email_unique`
        # was dropped in migrate_26_to_27, and no unique index on
        # `member.email` remains (the survivors are on user_id,
        # LOWER(workspace_email) and the single-active-huvudmedlem partial —
        # none of which this route's `save(only=…)` columns can violate).
        # Kept, not deleted: it is the guard if a contact-email uniqueness
        # constraint is ever reintroduced.
        return problem(
            409,
            "E-postadressen används redan",
            "En annan medlem använder redan e-postadressen.",
        )
    # The same answer whether a code went or not: the member cannot test which addresses are in the matrikel.
    answer = {**_me_response(m), "email_code_sent": new_email is not None}
    if refused:
        answer["email_refused"] = refused
    return jsonify(answer)


DEMO_REFUSAL = "E-postadressen kan inte bytas i testmiljön."


def _codes_unavailable():
    return problem(503, "E-postadressen kan inte bytas just nu", "Försök igen senare.")


def _ask_for_code(m, address):
    """
    A code to `address` for the member's own change of address (purpose ny_adress), in the caller's transaction,
    bound to this session: a new request replaces the session's secret and voids every earlier code of the member
    for a new address (issue). No mail when
    another person holds the address or a limit stops it; the caller answers the same. A held address still spends
    one of the member's codes a day, or the limit would tell her which addresses are in the matrikel.
    """
    token = secrets.token_urlsafe(32)
    session["login_request"] = token
    try:
        with DB_PROXY.atomic():
            reserve_login_address(address, m.id)  # only a check here: nothing is written under the lock
        held = False
    except AddressTaken:
        held = True
    row = issue(m, "ny_adress", token, address)
    if row is not None and not held:
        enqueue_mail("konto.kod", "login_code", row.id, {"code_id": row.id}, ref=("membership", m.membership_id))


def _wrong_code():
    return problem(400, "Koden stämmer inte", "Koden stämmer inte eller har gått ut. Be om en ny kod om det behövs.")


@members_bp.route("/v2/members/me/contact/kod", methods=["DELETE"])
@json_login_required
def cancel_me_email():
    """Avbryt: this session's pending code for a new address stops working. A request in another session stays."""
    cancel(session.pop("login_request", None))
    return "", 204


@members_bp.route("/v2/members/me/contact/verifiera", methods=["POST"])
@json_login_required
def verify_me_email():
    """
    The member's code for her new address: the change is made (set_member_email, by="self"), and with it every
    session of her account ends, this one too. A wrong code, one from another browser, and an address another person
    has taken since all answer the same.
    """
    m = _member_for_current_user()
    if m is None or m.membership_id is None:
        return problem(404, "Medlem saknas", "Ingen medlemspost är kopplad till ditt konto.")
    if m.role != "huvudmedlem":
        return problem(403, "Endast huvudmedlem", "Endast huvudmedlemmen kan ändra medlemskapets uppgifter.")
    body = request.get_json(silent=True)
    entered = body.get("code") if isinstance(body, dict) else None
    if not isinstance(entered, str):
        return problem(400, "Ogiltigt fält", "code måste vara en sträng")
    token = session.get("login_request")
    try:
        row = check("ny_adress", token, entered, m.id) if token else None
    except CodeRefused:
        return _codes_unavailable()
    except CodeLoginClosed:
        return problem(503, "Koder tas inte emot just nu", "Försök igen om en timme.")
    if row is None:
        return _wrong_code()
    person_id, membership_id = m.id, m.membership_id
    with DB_PROXY.atomic():
        # membership → user → person, as set_member_email takes them
        Membership.select().where(Membership.id == membership_id).for_update().get()
        User.select().where(User.id == current_user.id).for_update().get()
        if not session_holds(session):  # revoked while the request waited for the account's row
            return problem(401, "Sessionen gäller inte längre", "Logga in igen.")
        m, ms, err = _relock_me(membership_id, person_id)
        if err is not None:
            return err
        if not row.new_address or row.user_id != m.user_id or not consume(row):
            return _wrong_code()
        try:
            with DB_PROXY.atomic():
                previous = m.email
                m = set_member_email(m, row.new_address, current_user, by="self")
                if m.email != previous:
                    payload = {"person_id": m.id, "fields": ["email"], "source": "profil"}
                    write_matrikel_audit(current_user, "kontakt_andrad", ms, payload)
        except AddressTaken:
            return _wrong_code()  # taken since the code went; the code stays used (the return commits)
    session.pop("login_request", None)
    return jsonify(_me_response(m))


@members_bp.route("/v2/members/me/consent", methods=["PATCH"])
@json_login_required
def patch_me_consent():
    m = _member_for_current_user()
    if m is None or m.membership_id is None:
        return problem(404, "Medlem saknas", "Ingen medlemspost är kopplad till ditt konto.")
    if m.role != "huvudmedlem":
        return problem(
            403,
            "Endast huvudmedlem",
            "Endast huvudmedlemmen kan ändra medlemskapets uppgifter.",
        )

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem(400, "Ogiltigt anrop", "Uppdateringen måste vara ett JSON-objekt")

    # PARTIAL update: the body carries only the switches this member
    # actually changed. Unknown keys are refused rather than ignored — a typo
    # would otherwise look to the member like a saved consent.
    unknown = sorted(key for key in body if key not in CONSENT_KEYS)
    if unknown:
        return problem(400, "Ogiltigt fält", f"Okända samtyckesnycklar: {', '.join(unknown)}")

    # Validate every supplied consent key is a real JSON boolean —
    # rejecting strings like "false" that would otherwise coerce to True.
    updates: dict[str, bool] = {}
    for key in CONSENT_KEYS:
        if key in body:
            value = body[key]
            if not isinstance(value, bool):
                return problem(
                    400,
                    "Ogiltigt samtyckesvärde",
                    f"Samtyckesnyckeln '{key}' måste vara en JSON-boolean (true/false)",
                )
            updates[key] = value
    if not updates:
        # Never a silent no-op: an empty body would leave the row at {} — "ej
        # angivet" in the Koharen export — while the member believes the answer
        # was recorded.
        return problem(400, "Inga publiceringsval angivna", "Ange minst ett publiceringsval att spara")

    person_id, membership_id = m.id, m.membership_id
    with DB_PROXY.atomic():
        # Lock order root: membership FOR UPDATE, then re-read the
        # caller's person row AND the stored consent UNDER that lock, and merge
        # the submitted keys onto it. Saving a blob built from a request-start
        # read is last-writer-wins — a second tab would re-enable a consent this
        # member just withdrew, and the Koharen export would print it (GDPR) —
        # and authorizing on that read lets a demoted, unlinked or erased row
        # still rewrite the household's publication choices.
        m, ms, err = _relock_me(membership_id, person_id)
        if err is not None:
            return err
        # Only the four documented keys are ever stored: anything else that got
        # into the JSONB by another path is dropped on the next save, and a
        # stored value that is not a literal true is persisted as false
        # (fail-closed).
        merged = {k: v is True for k, v in stored_consent(ms).items() if k in CONSENT_KEYS}
        merged.update(updates)
        set_consent(ms, merged, source="profil", text_version=PROFILE_CONSENT_TEXT_VERSION, user=current_user.id)
    return jsonify(_me_response(m))


@members_bp.route("/v2/members/stats", methods=["GET"])
@json_login_required
@matrikel_read_required
def member_stats():
    today = date.today()
    jan1 = date(today.year, 1, 1)

    # friexemplar rows are excluded from member counts.
    memberships = Membership.select().where(Membership.membership_status != "friexemplar")
    persons = Member.select().join(Membership).where(Membership.membership_status != "friexemplar")

    return jsonify(
        {
            "memberships": {
                "total": memberships.count(),
                "active": memberships.where(Membership.membership_status == "active").count(),
                "inactive": memberships.where(Membership.membership_status == "inactive").count(),
                "pending": memberships.where(Membership.membership_status == "pending").count(),
                "new_this_year": memberships.where(Membership.joined_date >= jan1).count(),
            },
            "persons": {
                "total": persons.count(),
                "active": persons.where(Member.end_date.is_null(True)).count(),
            },
            "friexemplar": Membership.select().where(Membership.membership_status == "friexemplar").count(),
        }
    )


# Membership.invoice_address keys and their MATR export headers, in column order.
INVOICE_KEYS = ("name", "address", "postal_code", "city", "email", "reference")
INVOICE_HEADER = (
    "Fakturamottagare",
    "Fakturaadress",
    "Fakturapostnummer",
    "Fakturapostort",
    "E-post för faktura",
    "Fakturareferens",
)


@members_bp.route("/v2/members/export", methods=["GET"])
@json_login_required
@matrikel_admin_required
def export_members():
    if settings.service.demo_instance:
        return problem(403, "Inte i testmiljön", DEMO_EXPORT_REFUSED)
    # Matrikel/mailing-list export in the MATR paper layout, so the matrikel
    # keeper keeps the spreadsheet format he already works in — and the file
    # round-trips straight back through `flask members import`
    # (app/cli/members.py, same columns and grouping semantics). friexemplar
    # rows are included so it doubles as the magazine mailing list. Only active + friexemplar export: MATR has no
    # status column, so a pending membership would come back ACTIVE on re-import
    # (and inactive ones are not members at all).
    #
    # The paper file's single "Postadress" column is written as the structured
    # "Postnummer" + "Postort" pair — the documented ADR-0006 exception:
    # this CSV's only consumers are the matrikel keeper and our own
    # importer, which accepts both layouts.
    #
    # The Faktura* columns are Membership.invoice_address: the
    # address the fee invoice goes to, which is the postal address unless the
    # membership has a billing address. The importer ignores them.
    q = Membership.select().where(Membership.membership_status.in_(("active", "friexemplar")))

    buf = io.StringIO()
    buf.write("\ufeff")  # UTF-8 BOM for Excel
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL)  # a ";" inside a value stays in its cell in sv Excel
    writer.writerow(
        [
            "G",
            "M",
            "Nr",
            "Namn Efternamn",
            "Adress",
            "Postnummer",
            "Postort",
            "Telefonnr",
            "e-postadress",
            "Bet senast",
            "Noteringar",
            *INVOICE_HEADER,
            "c/o",
        ]
    )

    # MATR file order: friexemplar/number-less memberships first, then
    # ascending member number.
    q = q.order_by(Membership.member_number.asc(nulls="FIRST"), Membership.id)
    active_persons = (
        Member.select().where(Member.end_date.is_null(True)).order_by(Member.role != "huvudmedlem", Member.id)
    )
    for ms in q.prefetch(active_persons):
        persons = ms.persons
        if ms.organization_name and (not persons or persons[0].role != "huvudmedlem"):
            # The organization still receives the magazine without an active contact.
            persons = [None, *persons]
        if not persons:
            continue
        _, care_of = membership_recipient(ms)

        herd_codes = [h.herd or "" for h in Herd.select().where(Herd.membership == ms)]
        g_flag = "G" if any(code.startswith("G") for code in herd_codes) else ""
        m_flag = "M" if any(code.startswith("M") for code in herd_codes) else ""

        if ms.member_number is not None:
            nr = str(ms.member_number)
        elif ms.membership_status == "friexemplar":
            nr = "0"  # the paper file's friexemplar marker
        else:
            # Active membership without a number — a data anomaly; leave the
            # cell empty so it stands out instead of masquerading as Nr 0.
            nr = ""

        invoice = ms.invoice_address
        invoice_cells = [csv_safe(invoice[key]) for key in INVOICE_KEYS]

        for index, person in enumerate(persons):
            main_row = index == 0
            name = ms.organization_name if main_row and ms.organization_name else person.display_name
            writer.writerow(
                [
                    # Membership-level cells only on the main row; the Nr is
                    # repeated because that is how the importer groups the
                    # family rows back into one membership.
                    g_flag if main_row else "",
                    m_flag if main_row else "",
                    nr,
                    csv_safe(name),
                    csv_safe(ms.address) if main_row else "",
                    csv_safe(ms.postal_code) if main_row else "",
                    csv_safe(ms.city) if main_row else "",
                    csv_safe(person.phone if person else None),
                    csv_safe(person.email if person else None),
                    csv_safe(ms.payment_note) if main_row else "",
                    csv_safe(ms.notes) if main_row else "",
                    *(invoice_cells if main_row else [""] * len(INVOICE_KEYS)),
                    csv_safe(care_of) if main_row else "",
                ]
            )

    filename = f"matrikel_export_{date.today().isoformat()}.csv"
    log_member_export("matr")
    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",  # a cached copy would skip the audit row
        },
    )


KOHAREN_HEADER = ["Nr", "Namn", "Telefon", "E-post", "Gatuadress", "Postnummer", "Postort", "Samtycke"]


# [Next.js] Phase 19 — consent-aware Koharen listing (new route; the MATR export's contract is untouched, ADR-0006)
@members_bp.route("/v2/members/koharen-export", methods=["GET"])
@json_login_required
@matrikel_admin_required
def export_koharen():
    buf = io.StringIO()
    buf.write("\ufeff")  # UTF-8 BOM for Excel
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL)  # a ";" inside a value stays in its cell in sv Excel
    writer.writerow(KOHAREN_HEADER)
    q = Membership.select().where(Membership.membership_status == "active")
    for ms in q.order_by(Membership.member_number.asc(nulls="LAST"), Membership.id):
        persons = Member.select().where(Member.membership == ms, Member.end_date.is_null(True))
        if ms.organization_name:
            persons = [persons.where(Member.role == "huvudmedlem").first()]
        else:
            persons = persons.order_by(Member.role != "huvudmedlem", Member.id)
        # {} = never answered: blank PII + "ej angivet" so the keeper
        # can fall back to the yearly-report answer by hand. No automatic seeding.
        answered = consent_answered(ms)
        consent = effective_consent(ms) if answered else {key: False for key in CONSENT_KEYS}
        samtycke = "angivet" if answered else "ej angivet"
        nr = str(ms.member_number) if ms.member_number is not None else ""
        for person in persons:
            name = ms.organization_name or person.display_name
            writer.writerow(
                [
                    nr,
                    csv_safe(name) if consent["name"] else "",
                    csv_safe(person.phone) if consent["phone"] and person else "",
                    csv_safe(person.email) if consent["email"] and person else "",
                    csv_safe(ms.address) if consent["address"] else "",
                    csv_safe(ms.postal_code) if consent["address"] else "",
                    csv_safe(ms.city) if consent["address"] else "",
                    samtycke,
                ]
            )
    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="koharen-matrikel.csv"'},
    )


def log_member_export(action, **details):
    """One audit_log row per download of the MATR export or the address list: who, when and which, never a value."""
    AuditLog.create(
        table_name=Membership._meta.table_name,
        record_id=f"export-{action}-{datetime.now(timezone.utc).isoformat()}",
        operation="READ",
        new_data={"action": action, **details},
        changed_by=current_user.username or current_user.email,
    )


# The demo is a nightly copy of production: an export there would carry real members
# while its audit row is gone at the next sync.
DEMO_EXPORT_REFUSED = "Exporten går bara att göra i den riktiga Stamboken, där varje uttag loggas."

ADDRESS_LIST_HEADER = ["Nr", "Namn Efternamn", "Adress", "Postadress", "Betala nu"]


def fee_unpaid(payment_note, year):
    """True when the latest year in the payment note is before `year`.

    Two layouts: the paper matrikel's bare "25", and the guide's "Betalt 2026-11-16 Swish".
    A note without a year (empty, "gratis") never gives a reminder.
    """
    note = (payment_note or "").strip()
    if re.fullmatch(r"\d{2}", note, re.ASCII):
        return 2000 + int(note) < year
    years = [int(y) for y in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", note, re.ASCII)]
    return bool(years) and max(years) < year


# The printer's mailing list for Koharen (#186), in the layout the printer already gets:
# one row per household with the huvudmedlem's name only (an organization with "c/o" its contact),
# sorted by postal code.
# New route; the MATR export's contract is untouched (ADR-0006).
@members_bp.route("/v2/members/address-list", methods=["GET"])
@json_login_required
@matrikel_admin_required
def export_address_list():
    if settings.service.demo_instance:
        return problem(403, "Inte i testmiljön", DEMO_EXPORT_REFUSED)
    fee_reminder = request.args.get("fee_reminder") == "1"  # only for the year's first two issues
    year = date.today().year
    rows = []
    active_persons = (
        Member.select().where(Member.end_date.is_null(True)).order_by(Member.role != "huvudmedlem", Member.id)
    )
    memberships = Membership.select().where(Membership.membership_status.in_(("active", "friexemplar")))
    for ms in memberships.prefetch(active_persons):
        if not ms.address and not ms.postal_address:
            continue
        if ms.organization_name:
            # As in MATR: the organization receives even without an active contact.
            recipient, care_of = membership_recipient(ms)
            name = f"{recipient}, {care_of}" if care_of else recipient
        elif ms.persons:
            name = ms.persons[0].display_name  # the huvudmedlem, else the first active person
        else:
            continue
        if ms.member_number is not None:
            nr = str(ms.member_number)
        else:
            nr = "0" if ms.membership_status == "friexemplar" else ""
        unpaid = fee_reminder and ms.membership_status == "active" and fee_unpaid(ms.payment_note, year)
        sort_key = (ms.postal_code is None, ms.postal_code or "", ms.id)  # a foreign address has no postal code: last
        rows.append(
            (
                sort_key,
                [
                    nr,
                    csv_safe(name),
                    csv_safe(ms.address),
                    csv_safe(ms.postal_address),
                    "Betala nu" if unpaid else "",
                ],
            )
        )

    buf = io.StringIO()
    buf.write("\ufeff")  # UTF-8 BOM for Excel
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
    writer.writerow(ADDRESS_LIST_HEADER)
    writer.writerows(row for _, row in sorted(rows, key=lambda r: r[0]))
    log_member_export("address-list", rows=len(rows), fee_reminder=fee_reminder)
    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="koharen-adresslista-{date.today().isoformat()}.csv"',
            "Cache-Control": "no-store",  # personal data: never kept by a browser or a proxy
        },
    )
