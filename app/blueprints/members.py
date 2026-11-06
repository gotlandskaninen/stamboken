"""
Matrikel endpoints (Member Model v2).

Flat membership rows with expandable person rows. Reads are gated by
matrikel_read_required (admin/matrikel_admin/manager), writes and export by
matrikel_admin_required. Self-service /me endpoints put person fields on the
Member row and address/consent on the Membership. See ADR-0007 and ADR-0008.
"""

import csv
import io
from datetime import date

from flask import Blueprint, Response, jsonify, request
from flask_login import current_user
from peewee import IntegrityError
from utils.csv_safe import csv_safe
from utils.database import DB_PROXY, Herd, HerdAccessGrant, Member, Membership
from utils.matrikel import AddressValidationError, is_anonymized, parse_postal_fields, write_matrikel_audit
from utils.members import CONSENT_KEYS, consent_answered, effective_consent, stored_consent

from blueprints.common import (
    EMAIL_RE,
    json_login_required,
    matrikel_admin_required,
    matrikel_read_required,
    problem,
)

members_bp = Blueprint("members", __name__, url_prefix="/api")

VALID_MEMBERSHIP_STATUSES = ("active", "inactive", "pending", "friexemplar")


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
        "membership_status": ms.membership_status,
        "address": ms.address,
        "postal_code": ms.postal_code,
        "city": ms.city,
        "postal_address": ms.postal_address,
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
        match = Membership.id.in_(person_match)
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

    with DB_PROXY.atomic():
        # Decide from the row AS LOCKED, never from the request-start read
        # Two admins both see `active`, one deactivates, and the
        # other's stale `active` would otherwise look like "no change" — no
        # audit row — while its UPDATE put the status back, and with it every
        # linked huvudmedlem's herd access (same rule as memberships.py).
        ms = Membership.select().where(Membership.id == ms.id).for_update().get()
        changed = []
        if new_status is not None and new_status != ms.membership_status:
            write_matrikel_audit(
                actor=current_user,
                action="membership_status_changed",
                membership=ms,
                # Nested {"before": {field: ...}, "after": {...}} shape —
                # same convention as the membership mutations, so the
                # append-only matrikel_audit table carries one shape per action.
                payload={
                    "before": {"membership_status": ms.membership_status},
                    "after": {"membership_status": new_status},
                },
            )
            ms.membership_status = new_status
            changed.append(Membership.membership_status)
        if "notes" in body:
            ms.notes = (body["notes"] or "").strip() or None
            changed.append(Membership.notes)
        # UPDATE only the changed columns — a full-row save would push every
        # attribute the instance carries, changed or not.
        ms.save(only=changed + [Membership.updated_at])
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
        Member.select(Member.first_name, Member.last_name)
        .where(Member.membership == ms, Member.role == "huvudmedlem", Member.end_date.is_null(True))
        .order_by(Member.id)
        .first()
    )
    # Additive: /v2/my-membership hides other persons from
    # non-main members, so the profile card gets the name here.
    data["main_member_name"] = f"{main.first_name} {main.last_name}".strip() if main else None
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

    if "email" in body:
        raw_email = body["email"]
        if not isinstance(raw_email, str):
            return problem(400, "Ogiltigt fält", "email måste vara en sträng")
        new_email = raw_email.strip().lower()
        if not EMAIL_RE.match(new_email):
            return problem(400, "Ogiltig e-postadress", f"'{new_email}' är inte en giltig e-postadress")
        person_updates["email"] = new_email

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
            for field, value in person_updates.items():
                setattr(m, field, value)
            for field, value in membership_updates.items():
                setattr(ms, field, value)
            if membership_updates:
                ms.save(only=[getattr(Membership, f) for f in membership_updates] + [Membership.updated_at])
            m.save(only=[getattr(Member, f) for f in person_updates] + [Member.updated_at])
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
        ms.publication_consent = merged
        # Consent only — never carry membership_status or the address along
        # (same rule as the contact route).
        ms.save(only=[Membership.publication_consent, Membership.updated_at])
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


@members_bp.route("/v2/members/export", methods=["GET"])
@json_login_required
@matrikel_admin_required
def export_members():
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
        ]
    )

    # MATR file order: friexemplar/number-less memberships first, then
    # ascending member number.
    for ms in q.order_by(Membership.member_number.asc(nulls="FIRST"), Membership.id):
        # One row per ACTIVE person, huvudmedlem first.
        persons = sorted(
            Member.select().where(Member.membership == ms, Member.end_date.is_null(True)),
            key=lambda p: (p.role != "huvudmedlem", p.id),
        )
        if not persons:
            # Nobody left to mail (every person ended/anonymized), and a
            # nameless row is rejected by the importer's "Namn Efternamn"
            # check — skip the membership entirely.
            continue

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

        for index, person in enumerate(persons):
            main_row = index == 0
            writer.writerow(
                [
                    # Membership-level cells only on the main row; the Nr is
                    # repeated because that is how the importer groups the
                    # family rows back into one membership.
                    g_flag if main_row else "",
                    m_flag if main_row else "",
                    nr,
                    csv_safe(f"{person.first_name} {person.last_name}".strip()),
                    csv_safe(ms.address) if main_row else "",
                    csv_safe(ms.postal_code) if main_row else "",
                    csv_safe(ms.city) if main_row else "",
                    csv_safe(person.phone),
                    csv_safe(person.email),
                    csv_safe(ms.payment_note) if main_row else "",
                    csv_safe(ms.notes) if main_row else "",
                ]
            )

    filename = f"matrikel_export_{date.today().isoformat()}.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
        persons = sorted(
            Member.select().where(Member.membership == ms, Member.end_date.is_null(True)),
            key=lambda p: (p.role != "huvudmedlem", p.id),
        )
        if not persons:
            continue
        # {} = never answered: blank PII + "ej angivet" so the keeper
        # can fall back to the yearly-report answer by hand. No automatic seeding.
        answered = consent_answered(ms)
        consent = effective_consent(ms) if answered else {key: False for key in CONSENT_KEYS}
        samtycke = "angivet" if answered else "ej angivet"
        nr = str(ms.member_number) if ms.member_number is not None else ""
        for person in persons:
            writer.writerow(
                [
                    nr,
                    csv_safe(f"{person.first_name} {person.last_name}".strip()) if consent["name"] else "",
                    csv_safe(person.phone) if consent["phone"] else "",
                    csv_safe(person.email) if consent["email"] else "",
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
