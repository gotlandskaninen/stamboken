"""
Matrikel (member registry) domain helpers — Member Model v2.

Member-number allocation is serialized through the single-row
member_number_counter table holding the high-water mark: SELECT ... FOR
UPDATE on the row, increment, use the value. The mark is seeded by
migration 25→26 against existing member numbers AND herd-code suffixes in
both gene banks, so a new number can never collide with an existing G/M
herd.

Audit payload convention: person-scoped audit rows carry the person's id
under the top-level payload key "person_id". redact_person_from_audits()
relies on it to find the rows whose PII must be redacted on GDPR
anonymization — mutation endpoints must follow the convention.
"""

import logging
from datetime import date, datetime

from peewee import Case, IntegrityError, fn

from utils.cache_invalidation import trigger_invalidation

# DB_PROXY is the runtime proxy that data_access.py uses; importing the
# module-level DATABASE symbol directly would be None at call time.
from utils.database import (
    BILLING_FIELDS,
    DB_PROXY,
    Herd,
    HerdAccessGrant,
    MatrikelAudit,
    Member,
    MemberApplication,
    MemberNumberCounter,
    Membership,
    User,
)
from utils.postal import (  # noqa: F401 — public helpers
    format_postal_address,
    normalize_postal_code,
    split_postal_address,
)

logger = logging.getLogger(__name__)

# Payload keys whose values are personal data. Redaction replaces the value,
# never the key — action, actor and ids stay reconstructable.
PII_PAYLOAD_KEYS = frozenset({"first_name", "last_name", "email", "phone", "workspace_email", "notes"})
REDACTED_VALUE = "[borttagen]"
# What clearing a household's address also removes from audit history.
# postal_address is the pre-v29 spelling of the same data, still present in old payloads.
HOUSEHOLD_PII_KEYS = frozenset({"address", "postal_code", "city", "postal_address", "notes", *BILLING_FIELDS})

# The placeholder names anonymize_person() writes (the name columns are NOT
# NULL, so erasure needs a value). They are also the only marker an anonymized
# person row carries — there is no boolean column — so the routes that must
# refuse to write PII back onto an erased row match on exactly this pair
# (is_anonymized below).
ANONYMIZED_FIRST_NAME = "Borttagen"
ANONYMIZED_LAST_NAME = "person"


def is_anonymized(person) -> bool:
    """True when this person row has been through GDPR erasure.

    Not the same as ended: soft-deleted (`end_date`) persons stay editable.
    """
    return person.first_name == ANONYMIZED_FIRST_NAME and person.last_name == ANONYMIZED_LAST_NAME


class AddressValidationError(ValueError):
    """Bad structured-address input — endpoints map it to RFC 9457 400."""

    def __init__(self, title: str, detail: str):
        super().__init__(detail)
        self.title = title
        self.detail = detail


def parse_postal_fields(body: dict) -> dict:
    """Resolve the structured address keys from a request body.

    Accepts `postal_code` / `city` (strings or null) and the legacy alias
    `postal_address` (split with the backfill regex — ADR-0006 keeps the old
    input contract). Returns only the keys the body carried, normalised.
    A body carrying BOTH layouts is rejected: the two could disagree.
    """
    has_split = "postal_code" in body or "city" in body
    has_alias = "postal_address" in body
    if has_split and has_alias:
        raise AddressValidationError("Ogiltig adress", "Ange antingen postal_address eller postal_code/city")
    out: dict = {}
    if has_alias:
        raw = body["postal_address"]
        if raw is not None and not isinstance(raw, str):
            raise AddressValidationError("Ogiltigt fält", "postal_address måste vara en sträng eller null")
        out["postal_code"], out["city"] = split_postal_address(raw)
    if "postal_code" in body:
        raw = body["postal_code"]
        if raw is not None and not isinstance(raw, str):
            raise AddressValidationError("Ogiltigt fält", "postal_code måste vara en sträng eller null")
        try:
            out["postal_code"] = normalize_postal_code(raw)
        except ValueError as err:
            raise AddressValidationError("Ogiltigt postnummer", str(err)) from err
    if "city" in body:
        raw = body["city"]
        if raw is not None and not isinstance(raw, str):
            raise AddressValidationError("Ogiltigt fält", "city måste vara en sträng eller null")
        out["city"] = (raw or "").strip() or None
    # The cap applies after EVERY branch: a legacy
    # alias that did not parse lands whole in city and must not reach the
    # varchar(100) column as a DataError.
    if out.get("city") is not None and len(out["city"]) > 100:
        raise AddressValidationError("Ogiltig adress", "Postort får vara högst 100 tecken")
    return out


# Column limits of the billing_* text fields and their names in error messages.
_BILLING_TEXT_FIELDS = {
    "billing_name": (200, "Fakturamottagare"),
    "billing_address": (1000, "Fakturaadress"),
    "billing_city": (100, "Fakturapostort"),
    "billing_email": (255, "E-post för faktura"),
    "billing_reference": (100, "Fakturareferens"),
}


def parse_billing_fields(body: dict) -> dict:
    """Resolve the billing address keys from a request body.

    Returns only the billing_* keys the body carried: trimmed, blank as None,
    the postal code normalised like the postal address. The e-mail shape is
    left to the caller, which has EMAIL_RE (utils never imports blueprints).
    """
    out: dict = {}
    for key in BILLING_FIELDS:
        if key not in body:
            continue
        raw = body[key]
        if raw is not None and not isinstance(raw, str):
            raise AddressValidationError("Ogiltigt fält", f"{key} måste vara en sträng eller null")
        if key == "billing_postal_code":
            try:
                out[key] = normalize_postal_code(raw)
            except ValueError as err:
                raise AddressValidationError("Ogiltigt postnummer", "Fakturapostnummer ska vara fem siffror") from err
            continue
        value = (raw or "").strip() or None
        limit, label = _BILLING_TEXT_FIELDS[key]
        if value is not None and len(value) > limit:
            raise AddressValidationError("Ogiltig fakturaadress", f"{label} får vara högst {limit} tecken")
        out[key] = value
    return out


def _locked_counter() -> MemberNumberCounter:
    """Return the single counter row, locked FOR UPDATE.

    Requires an open transaction: outside one, the row lock would be
    released as soon as the statement's implicit transaction commits and
    the allocation race would come back.
    """
    if not DB_PROXY.in_transaction():
        raise RuntimeError("member-number counter access requires an open DB_PROXY.atomic() block")
    row = MemberNumberCounter.select().for_update().first()
    if row is None:
        raise RuntimeError("member_number_counter row missing — migration 25→26 seeds it")
    return row


def allocate_member_number() -> int:
    """Allocate the next member number (increment the high-water mark).

    Call inside the same DB_PROXY.atomic() block that creates the
    membership, so a failed approval rolls the number back too.
    """
    row = _locked_counter()
    row.value += 1
    row.save()
    return row.value


def raise_counter_to(value: int) -> None:
    """Raise the high-water mark iff `value` exceeds it (manual number edits)."""
    row = _locked_counter()
    if value > row.value:
        row.value = value
        row.save()


def write_matrikel_audit(actor: User, action: str, membership: Membership, payload: dict) -> MatrikelAudit:
    """Append one matrikel audit row. Payloads carry before/after values."""
    return MatrikelAudit.create(actor=actor, action=action, membership=membership, payload=payload)


def _redact_node(node, keys=PII_PAYLOAD_KEYS):
    """Return (redacted copy, changed) — replaces the values of `keys` in dicts/lists."""
    if isinstance(node, dict):
        out = {}
        changed = False
        for key, value in node.items():
            if key in keys and value is not None:
                out[key] = REDACTED_VALUE
                if value != REDACTED_VALUE:
                    changed = True
            else:
                out[key], sub_changed = _redact_node(value, keys)
                changed = changed or sub_changed
        return out, changed
    if isinstance(node, list):
        out = []
        changed = False
        for item in node:
            new_item, sub_changed = _redact_node(item, keys)
            out.append(new_item)
            changed = changed or sub_changed
        return out, changed
    return node, False


def redact_person_from_audits(member: Member) -> int:
    """Redact `member`'s PII from matrikel_audit payloads (GDPR anonymization).

    Touches rows whose payload carries this person's id under "person_id"
    (the audit payload convention above). Keys, action, actor and all ids
    survive; personal values become REDACTED_VALUE. Returns the number of
    rows updated. Idempotent — a second pass returns 0.
    """
    query = MatrikelAudit.select()
    if member.membership_id is not None:
        query = query.where(MatrikelAudit.membership == member.membership_id)

    touched = 0
    for row in query:
        payload = row.payload or {}
        if payload.get("person_id") != member.id:
            continue
        new_payload, changed = _redact_node(payload)
        if changed:
            row.payload = new_payload
            row.save()
            touched += 1
    if touched:
        logger.info("redacted %s matrikel audit row(s) for member=%s", touched, member.id)
    return touched


def redact_household_from_audits(membership: Membership) -> int:
    """Redact the household address and notes from `membership`'s audit payloads.

    A membership PATCH audits before/after values of address, postal_code, city,
    the billing address and notes under "membership_updated" with no person_id, so
    redact_person_from_audits() never reaches them. Idempotent.
    """
    touched = 0
    rows = MatrikelAudit.select().where(
        MatrikelAudit.membership == membership, MatrikelAudit.action == "membership_updated"
    )
    for row in rows:
        new_payload, changed = _redact_node(row.payload or {}, HOUSEHOLD_PII_KEYS)
        if changed:
            row.payload = new_payload
            row.save()
            touched += 1
    return touched


VALID_PERSON_ROLES = ("huvudmedlem", "familjemedlem", "skotare")


def add_person(membership, data, actor):
    """Create a person row under `membership` and audit it.

    `data` keys: first_name, last_name (required), email, phone, role
    (defaults to familjemedlem). Raises ValueError on unknown role. A second
    active huvudmedlem raises IntegrityError from the partial unique index —
    callers translate that to a 409.

    Locks the membership row and rejects an inactive one INSIDE the tx: like
    the other person mutations this closes a TOCTOU race — without it a person
    could be added between retire_membership() reading its active-person set
    and committing, marooning an active person on an inactive membership.
    """
    role = data.get("role") or "familjemedlem"
    if role not in VALID_PERSON_ROLES:
        raise ValueError(f"Ogiltig roll: {role}")
    with DB_PROXY.atomic():
        locked = Membership.select().where(Membership.id == membership.id).for_update().get()
        if locked.membership_status == "inactive":
            raise ValueError("Kan inte lägga till personer i ett inaktivt medlemskap")
        person = Member.create(
            membership=membership,
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=data.get("email") or None,
            phone=data.get("phone") or None,
            role=role,
        )
        write_matrikel_audit(
            actor,
            "person_added",
            membership,
            {
                "person_id": person.id,
                "first_name": person.first_name,
                "last_name": person.last_name,
                "email": person.email,
                "phone": person.phone,
                "role": person.role,
            },
        )
    return person


def soft_delete_person(member, actor):
    """Soft-delete a person row and revoke all their grants in one transaction.

    Raises ValueError if `member` is the membership's active huvudmedlem —
    a membership must never be left headless (swap the main member first).

    Locks the membership row and re-validates INSIDE the transaction: the
    partial unique index only enforces "at most one" active huvudmedlem,
    so "at least one" must be protected by serializing delete against
    swap_main_member (a delete validated before a concurrent swap promotes
    the same person would otherwise leave the membership headless — sol
    review finding 6).
    """
    with DB_PROXY.atomic():
        Membership.select().where(Membership.id == member.membership_id).for_update().get()
        member = Member.get_by_id(member.id)  # re-read under the lock
        if member.role == "huvudmedlem" and member.end_date is None:
            raise ValueError("Medlemskapets aktiva huvudmedlem kan inte tas bort — byt huvudmedlem först")
        if member.end_date is None:
            member.end_date = date.today()
            member.save()
        now = datetime.now()
        revoked = (
            HerdAccessGrant.update(revoked_at=now, updated_at=now)
            .where(
                HerdAccessGrant.member == member,
                HerdAccessGrant.revoked_at.is_null(True),
            )
            .execute()
        )
        write_matrikel_audit(
            actor,
            "person_removed",
            member.membership,
            {"person_id": member.id, "revoked_grants": revoked},
        )


def swap_main_member(membership, new_main, actor):
    """Atomically demote the current active huvudmedlem and promote `new_main`.

    Same serialization as soft_delete_person: lock the membership row, then
    re-read and re-validate the candidate inside the transaction, so a
    concurrent delete cannot end the person this swap is about to promote.
    """
    with DB_PROXY.atomic():
        Membership.select().where(Membership.id == membership.id).for_update().get()
        new_main = Member.get_by_id(new_main.id)  # re-read under the lock
        if new_main.membership_id != membership.id:
            raise ValueError("Personen tillhör inte medlemskapet")
        if new_main.end_date is not None:
            raise ValueError("Personen är inte aktiv")
        if new_main.role == "huvudmedlem":
            raise ValueError("Personen är redan huvudmedlem")
        current = (
            Member.select()
            .where(
                Member.membership == membership,
                Member.role == "huvudmedlem",
                Member.end_date.is_null(True),
            )
            .first()
        )
        if current is not None:
            current.role = "familjemedlem"
            current.save()
        new_main.role = "huvudmedlem"
        new_main.save()
        write_matrikel_audit(
            actor,
            "main_member_changed",
            membership,
            {
                "previous_person_id": current.id if current is not None else None,
                "new_person_id": new_main.id,
            },
        )


def _applications_of(person):
    """WHERE clause for every application that carries `person`'s PII.

    The application linked via created_member, plus the other submissions of
    the same applicant: the public form accepts repeats, and only one of them is
    linked on approval. Those match on name AND e-mail together (households
    legitimately share one contact e-mail), whether pending, rejected or since
    approved into another membership (a reviewer may approve a duplicate while
    the erasure runs), under each identity the person has: the row as it is now
    and every linked application (the row's name or e-mail may have been edited
    since). Call BEFORE the row is overwritten; peewee captures the values at
    build time.
    """
    identities = {(person.first_name, person.last_name, person.email)}
    for app_row in MemberApplication.select().where(MemberApplication.created_member == person):
        identities.add((app_row.first_name, app_row.last_name, app_row.email))
    where = MemberApplication.created_member == person
    for first_name, last_name, email in identities:
        if not email or email == REDACTED_VALUE:
            continue  # nothing to match on (no e-mail, or already erased)
        where |= (
            (fn.LOWER(MemberApplication.email) == email.strip().lower())
            & (fn.LOWER(MemberApplication.first_name) == first_name.strip().lower())
            & (fn.LOWER(MemberApplication.last_name) == last_name.strip().lower())
        )
    return where


def anonymize_person(member, actor):
    """GDPR erasure: anonymize the person row, keep membership history.

    Placeholder names (columns are NOT NULL), nulls contact fields +
    workspace_email + gdpr_consented_at + notes, detaches the user, revokes
    grants, sets end_date, redacts prior audit payloads and writes a final
    person_anonymized audit row. Also scrubs any member_application rows
    linked via created_member — the approved application is a direct PII
    duplicate and would otherwise defeat erasure (review status/linkage are
    kept for the audit trail; a still pending one is closed as rejected);
    other submissions of the same applicant are scrubbed likewise
    (_applications_of). When no active person is left
    on the membership, its postal and billing address and notes are cleared too. Deliberately
    allowed on an active main member — the right to erasure trumps the
    headless-membership invariant.

    Detaches the account through the same locked unlink path as the endpoint
    (mode="anonymize") and invalidates the genebanks whose
    access the account loses. Returns the scrubbed person: the caller's
    pre-lock instance is stale afterwards.
    """
    with DB_PROXY.atomic():
        # current user_id under the membership lock, never the caller's stale copy
        person, user = _lock_for_detach(member.id)
        membership = person.membership
        before = user.effective_herd_ids() if user is not None else set()
        redact_person_from_audits(person)
        now = datetime.now()
        HerdAccessGrant.update(revoked_at=now, updated_at=now).where(
            HerdAccessGrant.member == person,
            HerdAccessGrant.revoked_at.is_null(True),
        ).execute()
        if person.user_id is not None:
            _detach_user_locked(person, actor=actor, mode="anonymize")
        applications_to_redact = _applications_of(person)
        person.first_name = ANONYMIZED_FIRST_NAME
        person.last_name = ANONYMIZED_LAST_NAME
        person.email = None
        person.phone = None
        person.workspace_email = None
        person.gdpr_consented_at = None
        person.notes = None
        if person.end_date is None:
            person.end_date = date.today()
        person.save()
        if not Member.select().where(Member.membership == membership, Member.end_date.is_null(True)).exists():
            # Last active person gone: the household address, the billing
            # address and the free-text notes were theirs, on the row and in the
            # audit history. payment_note stays — accounting history survives.
            Membership.update(
                address=None, postal_code=None, city=None, notes=None, **dict.fromkeys(BILLING_FIELDS), updated_at=now
            ).where(Membership.id == membership.id).execute()
            redact_household_from_audits(membership)
        applications_redacted = (
            MemberApplication.update(
                first_name=ANONYMIZED_FIRST_NAME,
                last_name=ANONYMIZED_LAST_NAME,
                email="[borttagen]",
                phone=None,
                address=None,
                postal_code=None,
                city=None,
                **dict.fromkeys(BILLING_FIELDS),
                motivation=None,
                rejection_reason=None,  # reviewer free text can quote the applicant
                updated_at=now,
                # A scrubbed shell must not stay in the review queue, or approve would
                # turn it into a numbered membership named "Borttagen person".
                status=Case(None, [(MemberApplication.status == "pending", "rejected")], MemberApplication.status),
            )
            .where(applications_to_redact)
            .execute()
        )
        write_matrikel_audit(
            actor,
            "person_anonymized",
            membership,
            {"person_id": person.id, "applications_redacted": applications_redacted},
        )
        lost = before - User.get_by_id(user.id).effective_herd_ids() if user is not None else set()
        lost_genebanks = (
            {h.genebank_id for h in Herd.select(Herd.genebank).where(Herd.id.in_(list(lost)))} if lost else set()
        )
    _invalidate_genebanks(lost_genebanks)
    return person


def create_membership(data, actor):
    """Create a membership with its initial huvudmedlem in one transaction.

    Admin/matrikel_admin may create memberships
    directly (not only via application approval or CSV import). `data` keys: first_name, last_name (required), email,
    phone, membership_status (default 'active'), address, postal_code, city,
    payment_note, notes, allocate (bool — allocate a member_number). The
    address is always structured here: the endpoint resolves the legacy
    `postal_address` alias with parse_postal_fields() before calling, and the
    CSV importer creates Membership rows directly. Locks the counter FIRST
    when allocating, matching the approval lock order.
    """
    status = data.get("membership_status") or "active"
    with DB_PROXY.atomic():
        number = allocate_member_number() if data.get("allocate") else None
        membership = Membership.create(
            member_number=number,
            membership_status=status,
            address=data.get("address") or None,
            postal_code=data.get("postal_code") or None,
            city=data.get("city") or None,
            payment_note=data.get("payment_note") or None,
            notes=data.get("notes") or None,
        )
        main = Member.create(
            membership=membership,
            role="huvudmedlem",
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=data.get("email") or None,
            phone=data.get("phone") or None,
        )
        write_matrikel_audit(
            actor,
            "membership_created",
            membership,
            {"person_id": main.id, "member_number": number, "membership_status": status},
        )
    return membership


def retire_membership(membership, actor):
    """Soft-retire a membership: status → inactive, end every active person,
    revoke every active grant, in one transaction. This is the 'delete'
    capability; row-level
    erasure remains per-person anonymize_person (GDPR). Idempotent on an
    already-inactive membership.
    """
    now = datetime.now()
    with DB_PROXY.atomic():
        Membership.select().where(Membership.id == membership.id).for_update().get()
        persons = list(Member.select().where(Member.membership == membership, Member.end_date.is_null(True)))
        for person in persons:
            HerdAccessGrant.update(revoked_at=now, updated_at=now).where(
                HerdAccessGrant.member == person,
                HerdAccessGrant.revoked_at.is_null(True),
            ).execute()
            person.end_date = date.today()
            person.save()
        membership.membership_status = "inactive"
        # `membership` is the CALLER's pre-lock instance — a full-row save would
        # overwrite a notes/address PATCH that committed while we waited for the
        # lock. Write only the column this operation owns (T5a deferred minor).
        membership.save(only=[Membership.membership_status, Membership.updated_at])
        write_matrikel_audit(
            actor,
            "membership_retired",
            membership,
            {"ended_person_ids": [p.id for p in persons]},
        )


def _plus_one_year(d):
    """`d` plus one calendar year (Feb 29 clamps to Feb 28)."""
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(year=d.year + 1, day=28)


def grant_is_active(grant):
    """Not revoked, not expired (valid THROUGH valid_until), person row active."""
    if grant.revoked_at is not None:
        return False
    if grant.valid_until is not None and grant.valid_until < date.today():
        return False
    return grant.member.end_date is None


def create_grant(member, herd, valid_until, actor):
    """Create — or re-activate — the unique (member, herd) grant row.

    Re-grant semantics: the row is reused for its whole lifecycle; a
    re-grant clears revoked_at and sets a new valid_until. Skotare grants
    default to today + 1 year; familjemedlem/huvudmedlem grants default to
    NULL (until revoked). Raises ValueError for an inactive person row.

    Serializes on the membership row (same order as the person mutations):
    without the lock, two concurrent calls both read no-row and the second
    INSERT escapes as IntegrityError from the (member, herd) unique index.
    The person re-read keeps the active check honest under the same lock.
    """
    with DB_PROXY.atomic():
        Membership.select().where(Membership.id == member.membership_id).for_update().get()
        member = Member.get_by_id(member.id)  # re-read under the lock
        if member.end_date is not None:
            raise ValueError("Personen är inte aktiv")
        if valid_until is None and member.role == "skotare":
            valid_until = _plus_one_year(date.today())
        grant = HerdAccessGrant.get_or_none(
            HerdAccessGrant.member == member,
            HerdAccessGrant.herd == herd,
        )
        if grant is None:
            grant = HerdAccessGrant.create(
                member=member,
                herd=herd,
                valid_until=valid_until,
                granted_by=actor,
            )
        else:
            grant.revoked_at = None
            grant.valid_until = valid_until
            grant.granted_by = actor
            grant.save()
        write_matrikel_audit(
            actor,
            "grant_created",
            member.membership,
            {
                "grant_id": grant.id,
                "person_id": member.id,
                "herd_id": herd.id,
                "valid_until": valid_until.isoformat() if valid_until else None,
            },
        )
    return grant


def renew_grant(grant, actor):
    """Renew = valid_until := today + 1 year. Only non-revoked grants.

    Takes the membership lock first (lock hierarchy: membership →
    user → person): link_access_delta() reads the grant's validity under that
    lock, so a renewal can never slip between a link's delta read and commit.
    """
    with DB_PROXY.atomic():
        Membership.select().where(Membership.id == grant.member.membership_id).for_update().get()
        grant = HerdAccessGrant.get_by_id(grant.id)  # re-read under the lock
        if grant.revoked_at is not None:
            raise ValueError("Ett återkallat tillstånd kan inte förnyas — skapa det på nytt istället")
        grant.valid_until = _plus_one_year(date.today())
        grant.granted_by = actor
        grant.save()
        write_matrikel_audit(
            actor,
            "grant_renewed",
            grant.member.membership,
            {
                "grant_id": grant.id,
                "person_id": grant.member_id,
                "valid_until": grant.valid_until.isoformat(),
            },
        )
    return grant


def revoke_grant(grant, actor):
    """Revoke = set revoked_at (independent of expiry). Same lock as renew_grant."""
    with DB_PROXY.atomic():
        Membership.select().where(Membership.id == grant.member.membership_id).for_update().get()
        grant = HerdAccessGrant.get_by_id(grant.id)  # re-read under the lock
        grant.revoked_at = datetime.now()
        grant.save()
        write_matrikel_audit(
            actor,
            "grant_revoked",
            grant.member.membership,
            {"grant_id": grant.id, "person_id": grant.member_id, "herd_id": grant.herd_id},
        )
    return grant


def suspension_candidates():
    """Active persons with a Workspace login but no active herd access.

    The spec's one Phase 9 addition: a person whose only herd access has
    lapsed and who holds a @gotlandskaninen.se account is a suspension
    candidate. Returns Member rows where end_date IS NULL, workspace_email
    is set, and grant_is_active() is False for every grant they hold. v2
    only exposes the query; Phase 9 decides what to do with it.
    """
    candidates = []
    for person in Member.select().where(
        Member.end_date.is_null(True),
        Member.workspace_email.is_null(False),
    ):
        grants = HerdAccessGrant.select().where(HerdAccessGrant.member == person)
        if not any(grant_is_active(g) for g in grants):
            candidates.append(person)
    return candidates


def resolve_own_membership(user):
    """Return the user's ACTIVE person row (Member), or None.

    "Active" = end_date IS NULL. Since migration 29 a user holds at most ONE
    person row at all — idx_member_user_unique enforces it — so there is
    never more than one candidate; the ordering is kept only as a
    deterministic tie-break should the index ever be dropped. The membership
    itself is `row.membership`.
    """
    return (
        Member.select()
        .where(Member.user == user, Member.end_date.is_null(True))
        .order_by((Member.role == "huvudmedlem").desc(), Member.id)
        .first()
    )


# --------------------------------------------------------------------------
# Kontokoppling — ONE lock-owning operation writes
# member.user_id. Lock order everywhere: membership → user → person, all
# FOR UPDATE. The invariant: a link never conveys herd access without an
# explicit admin confirmation of exactly the herds it conveys.
# --------------------------------------------------------------------------

LINK_MODES = ("admin", "cli", "oauth")


class LinkError(Exception):
    """Refused link/unlink — maps 1:1 to an RFC 9457 problem (default 409)."""

    def __init__(self, title: str, detail: str, status: int = 409, **extensions):
        super().__init__(detail)
        self.title, self.detail, self.status, self.extensions = title, detail, status, extensions


class ConfirmRequired(Exception):
    """The link would convey herd access; an explicit admin confirmation of exactly these herds is needed."""

    def __init__(self, conveys: list[dict]):
        super().__init__("confirm-required")
        self.conveys = conveys


def _herd_dicts(herd_ids) -> list[dict]:
    if not herd_ids:
        return []
    return [
        {"id": h.id, "herd": h.herd, "herd_name": h.herd_name, "genebank_id": h.genebank_id}
        for h in Herd.select().where(Herd.id.in_(list(herd_ids))).order_by(Herd.herd)
    ]


def link_access_delta(person: Member, user: User) -> list[dict]:
    """Herds `user` would GAIN by being linked to `person` — the same rules as
    User.effective_herd_ids(): (membership herds if huvudmedlem) ∪ (herds of
    the person's active grants — possibly outside the membership), both only
    on an active person on an active membership, minus what the user already
    has. Caller holds the locks."""
    membership = person.membership
    if person.end_date is not None or membership.membership_status != "active":
        return []
    herd_ids: set[int] = set()
    if person.role == "huvudmedlem":
        herd_ids |= {h.id for h in Herd.select(Herd.id).where(Herd.membership == membership)}
    today = date.today()
    for grant in HerdAccessGrant.select(HerdAccessGrant.herd).where(
        HerdAccessGrant.member == person,
        HerdAccessGrant.revoked_at.is_null(True),
        HerdAccessGrant.valid_until.is_null(True) | (HerdAccessGrant.valid_until >= today),
    ):
        herd_ids.add(grant.herd_id)
    return _herd_dicts(herd_ids - user.effective_herd_ids())


def _invalidate_genebanks(genebank_ids) -> None:
    """Best-effort, after commit: a cache failure must never turn a durable
    link/unlink into a 500 — the herd endpoints wrap trigger_invalidation
    the same way."""
    for genebank_id in sorted(set(genebank_ids)):
        try:
            trigger_invalidation(genebank_id)
        except Exception:  # pylint: disable=broad-except
            logger.exception("cache invalidation failed for genebank %s after a user-link change", genebank_id)


def _lock_membership(person_id: int) -> int:
    """Lock the person's membership row FIRST — the root of the hierarchy that
    swap_main_member / create_grant and (from Step 5b) both status PATCH routes
    take. Returns the membership id; LinkError 404 if the person vanished."""
    probe = Member.select(Member.id, Member.membership).where(Member.id == person_id).first()
    if probe is None:
        raise LinkError("Hittades inte", f"Personen {person_id} finns inte", status=404)
    Membership.select().where(Membership.id == probe.membership_id).for_update().get()
    return probe.membership_id


def _lock_for_link(person_id: int, user_id: int):
    """membership → user → person, all FOR UPDATE. Returns (person, user)."""
    _lock_membership(person_id)
    user = User.select().where(User.id == user_id).for_update().first()
    if user is None:
        raise LinkError("Hittades inte", f"Användaren {user_id} finns inte", status=404)
    person = Member.select().where(Member.id == person_id).for_update().get()
    return person, user


def _lock_for_detach(person_id: int):
    """Same hierarchy for unlink/anonymize. The user to lock is the person's
    CURRENT user_id read under the membership lock — never a value captured
    before it: every linker takes the membership lock
    first, so user_id cannot move once we hold it. Returns (person, user | None)."""
    _lock_membership(person_id)
    current_user_id = Member.select(Member.user).where(Member.id == person_id).get().user_id
    user = User.select().where(User.id == current_user_id).for_update().first() if current_user_id else None
    person = Member.select().where(Member.id == person_id).for_update().get()
    return person, user


def link_member_user(person_id, user_id, *, actor, mode, confirmed_herd_ids=None):
    """THE writer of member.user_id. Opens its own transaction and
    owns every lock — callers pass ids, never pre-locked rows.

    Returns (person, conveyed). Raises LinkError (404/409 shapes) or
    ConfirmRequired when the link would convey herd access and `mode` is
    not "admin" or the admin did not confirm exactly that herd set. The
    IntegrityError of idx_member_user_unique is mapped to a 409 (backstop).
    """
    if mode not in LINK_MODES:
        raise ValueError(f"unknown link mode {mode!r}")
    if mode != "admin" and confirmed_herd_ids is not None:
        raise ValueError("only mode='admin' may confirm a conveying link")
    with DB_PROXY.atomic():
        person, user = _lock_for_link(person_id, user_id)
        if person.end_date is not None:
            raise LinkError("Personen är avslutad", "En avslutad person kan inte kopplas till ett konto")
        if not user.is_active:
            raise LinkError("Kontot är inaktivt", "Ett inaktivt konto kan inte kopplas")
        if person.user_id is not None:
            raise LinkError("Personen har redan ett konto", "Koppla bort det befintliga kontot först")
        holder = Member.select().where(Member.user == user).first()
        if holder is not None:
            name = f"{holder.first_name} {holder.last_name}".strip()
            # A friexemplar/pending membership has no number — never render "nr None".
            number = holder.membership.member_number or "–"
            ended = f" (avslutad {holder.end_date.isoformat()})" if holder.end_date else ""
            raise LinkError(
                "Kontot är redan kopplat",
                f"Kontot är redan kopplat till {name} i medlemskap nr {number}{ended}",
                holder_person_id=holder.id,
            )
        conveyed = link_access_delta(person, user)  # under the locks, right before the save
        conveyed_ids = {h["id"] for h in conveyed}
        if conveyed_ids and (mode != "admin" or confirmed_herd_ids is None or set(confirmed_herd_ids) != conveyed_ids):
            raise ConfirmRequired(conveyed)
        person.user = user
        try:
            person.save()
        except IntegrityError as exc:
            raise LinkError("Kontot är redan kopplat", "Kontot är redan kopplat till en annan person") from exc
        write_matrikel_audit(
            actor,
            "person_user_linked",
            person.membership,
            {"person_id": person.id, "user_id": user.id, "conveys_herd_ids": sorted(conveyed_ids), "source": mode},
        )
    _invalidate_genebanks(h["genebank_id"] for h in conveyed)
    return person, conveyed


def _detach_user_locked(person: Member, *, actor: User, mode: str) -> int:
    """Inside an open transaction with membership → user → person locked."""
    user_id = person.user_id
    person.user = None
    person.save()
    write_matrikel_audit(
        actor, "person_user_unlinked", person.membership, {"person_id": person.id, "user_id": user_id, "source": mode}
    )
    return user_id


def unlink_member_user(person_id, *, actor, mode="admin"):
    """Detach the account — allowed on ended persons too (the release valve
    for the blocked-relink case). Returns (person, lost_genebank_ids)."""
    with DB_PROXY.atomic():
        person, user = _lock_for_detach(person_id)
        if user is None:
            raise LinkError("Personen har inget kopplat konto", "Det finns inget konto att koppla bort")
        before = user.effective_herd_ids()
        _detach_user_locked(person, actor=actor, mode=mode)
        lost = before - User.get_by_id(user.id).effective_herd_ids()
        lost_genebanks = (
            {h.genebank_id for h in Herd.select(Herd.genebank).where(Herd.id.in_(list(lost)))} if lost else set()
        )
    _invalidate_genebanks(lost_genebanks)
    return person, lost_genebanks
