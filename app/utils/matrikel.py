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

import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

from peewee import JOIN, Case, IntegrityError, fn

from utils.cache_invalidation import trigger_invalidation
from utils.data_access import (
    erase_account,
    new_generation,
    profile_pictures_of,
    purge_user_audit_pii,
    remove_profile_picture,
)

# DB_PROXY is the runtime proxy that data_access.py uses; importing the
# module-level DATABASE symbol directly would be None at call time.
from utils.database import (
    BILLING_FIELDS,
    DB_PROXY,
    OUTSIDE_GENEBANK_HERDS,
    Herd,
    HerdAccessGrant,
    LoginCode,
    MatrikelAudit,
    Member,
    MemberApplication,
    MemberChangeRequest,
    MemberNumberCounter,
    MemberPreviousAddress,
    Membership,
    User,
)
from utils.herd_contact import (
    compare_with_register,
    is_matrikel_reader,
    link_herd,
    on_household_erased,
    on_person_anonymizing,
    on_person_leaving,
    snapshot_before_leaving,
)
from utils.inbox_purge import erase_person_from_inbox, remove_originals
from utils.individual_commands import purge_command_free_text
from utils.login_code import (
    AddressTaken,
    lock_addresses,
    reserve_holder,
    reserve_login_address,
    reserve_on_leaving_friexemplar,
    void,
)
from utils.mail import cancel_member_added, enqueue_mail, forget_recipient, queue_member_added, was_main_member
from utils.membership_lifecycle import Event, Status, next_state, state_of
from utils.organization import parse_organization_fields
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
# Clear these membership fields on the row and in its audit history together.
HOUSEHOLD_PII_FIELDS = (
    "address",
    "postal_code",
    "city",
    "notes",
    "organization_name",
    "organization_number",
    *BILLING_FIELDS,
)
# postal_address is the pre-v29 spelling, still present in old payloads.
HOUSEHOLD_PII_KEYS = frozenset((*HOUSEHOLD_PII_FIELDS, "postal_address"))

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


def membership_recipient(membership: Membership) -> tuple[str, str | None]:
    """Postal recipient and optional c/o line: an organization receives, its named active contact is c/o.
    Reads membership.persons, so prefetch the active persons when looping over memberships."""
    main = next((p for p in membership.persons if p.role == "huvudmedlem" and p.end_date is None), None)
    name = f"{main.first_name} {main.last_name}".strip() if main else ""
    if membership.organization_name:
        return membership.organization_name, f"c/o {name}" if name else None
    return name, None


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


def write_matrikel_audit(actor: User | None, action: str, membership: Membership, payload: dict) -> MatrikelAudit:
    """Append one matrikel audit row. Payloads carry before/after values. No actor: the nightly job wrote it."""
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
    """Redact the household's identifying fields from its audit payloads.

    A membership PATCH records the before/after values under "membership_updated"
    with no person_id, so redact_person_from_audits() never reaches them. Idempotent.
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


class PersonNameRequired(ValueError):
    def __init__(self):
        super().__init__("Både förnamn och efternamn krävs")


def _new_person_names(data, *, optional):
    first = (data.get("first_name") or "").strip()
    last = (data.get("last_name") or "").strip()
    if not optional and not (first and last):
        raise PersonNameRequired
    return {"first_name": first, "last_name": last}


def add_person(membership, data, actor):
    """Create a person row under `membership` and audit it.

    `data` keys: first_name, last_name (optional for an organization's contact), email, phone, role
    (defaults to familjemedlem). Raises ValueError on unknown role. A second
    active huvudmedlem raises IntegrityError from the partial unique index —
    callers translate that to a 409. A main member's address is reserved for her (reserve_login_address): AddressTaken.

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
            **_new_person_names(data, optional=locked.organization_name and role == "huvudmedlem"),
            email=data.get("email") or None,
            phone=data.get("phone") or None,
            role=role,
        )
        if role == "huvudmedlem" and locked.membership_status != Status.FRIEXEMPLAR:
            reserve_login_address(person.email, person.id)
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
        queue_member_added(person)
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
            contacts = snapshot_before_leaving(member)
            member.end_date = date.today()
            member.save()
            on_person_leaving(member, contacts)
        cancel_member_added([member.id])
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
    The new main member's addresses become login addresses, her previous ones
    that still count too: AddressTaken when another person holds one, also
    the old main member who keeps an account.
    """
    with DB_PROXY.atomic():
        membership = Membership.select().where(Membership.id == membership.id).for_update().get()
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
            if membership.organization_name and not (current.first_name and current.last_name):
                raise ValueError("Ange kontaktpersonens för- och efternamn innan personen blir familjemedlem")
            current.role = "familjemedlem"
            current.save()
        new_main.role = "huvudmedlem"
        new_main.save()
        reserve_holder(new_main.id)
        cancel_member_added([new_main.id])
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


def anonymize_person(member, actor, deferred_originals=None, deferred_accounts=None):
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

    `actor` is None when the nightly job (anonymize_ended_persons) erases for
    retention: then only the application that created this person is scrubbed.
    The applicant's other submissions may belong to a member who came back, and
    the ones that never led to membership are #69's job.
    Detaches the account through the same locked unlink path as the endpoint
    (mode="anonymize") and invalidates the genebanks whose
    access the account loses. Erases the intake queue's originals and texts
    that show the person as seller or buyer, and what they sent
    (erase_person_from_inbox). Takes the person's previous addresses and codes,
    with the queue's trace of where their mails went. Empties the account
    (erase_account) and purges its old values from audit_log
    (purge_user_audit_pii, last in the transaction); an account with a role
    in RETENTION_HOLD_LEVELS refuses the erasure (LinkError) before any write.
    A caller inside its own transaction passes `deferred_originals` and
    `deferred_accounts`, purges those accounts last in it, and after its commit
    removes those files and the accounts' profile pictures (profile_pictures_of,
    read before the purge).
    Returns the scrubbed person: the caller's pre-lock instance is stale
    afterwards.
    """
    with DB_PROXY.atomic():
        # current user_id under the membership lock, never the caller's stale copy
        person, user = _lock_for_detach(member.id)
        if user is not None and any(p["level"] in RETENTION_HOLD_LEVELS for p in user.privileges or []):
            raise LinkError("Kontot har en roll", "Ta bort kontots roller innan personen anonymiseras")
        membership = person.membership
        erased_before = is_anonymized(person)  # read under the lock: a repeated erasure is no transition
        contacts = snapshot_before_leaving(person)  # the herds' contact, with her values still in it
        on_person_anonymizing(person)
        before = user.effective_herd_ids() if user is not None else set()
        if user is not None:  # her name leaves the public certificate check page too (stamboken #6)
            User.update(name_on_check_page=False).where(User.id == user.id).execute()
        redact_person_from_audits(person)
        # the old and new e-mail of each change (Fable 8); a queued mail to one finds no address and is cancelled
        MemberChangeRequest.delete().where(MemberChangeRequest.member == person.id).execute()
        now = datetime.now()
        HerdAccessGrant.update(revoked_at=now, updated_at=now).where(
            HerdAccessGrant.member == person,
            HerdAccessGrant.revoked_at.is_null(True),
        ).execute()
        if person.user_id is not None:
            _detach_user_locked(person, actor=actor, mode="anonymize")
        applications_to_redact = (
            _applications_of(person) if actor is not None else MemberApplication.created_member == person
        )
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
        on_person_leaving(person, contacts)
        # this call erases the last person, not only ends her (the address below): ended persons' farm rows wait
        # until then, and rows added after that erasure stay
        if not erased_before and all(map(is_anonymized, Member.select().where(Member.membership == membership))):
            on_household_erased(membership.id)
        if not Member.select().where(Member.membership == membership, Member.end_date.is_null(True)).exists():
            # Last active person gone: erase household details. payment_note stays for accounting.
            Membership.update(**dict.fromkeys(HOUSEHOLD_PII_FIELDS), updated_at=now).where(
                Membership.id == membership.id
            ).execute()
            redact_household_from_audits(membership)
        application_ids = [
            row.id
            for row in MemberApplication.update(
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
            # the rows this statement redacted, not a list read before it: an application committed in between
            # is redacted here too, and its mail must be forgotten with it
            .returning(MemberApplication.id)
            .execute()
        ]
        applications_redacted = len(application_ids)
        forget_recipient("member", person.id)  # the queue keeps no address hash or dedupe key of the erased
        if user is not None:
            forget_recipient("user", user.id)  # nor of the account's mail (notices, applications, the intake queue)
        for previous in (
            MemberPreviousAddress.delete()
            .where(MemberPreviousAddress.member == person.id)
            .returning(MemberPreviousAddress.id)
        ):
            forget_recipient("member_previous_address", previous.id)
        for code in LoginCode.delete().where(LoginCode.member == person.id).returning(LoginCode.id):
            forget_recipient("login_code", code.id)
        for application_id in application_ids:
            forget_recipient("application", application_id)
        write_matrikel_audit(
            actor,
            "person_anonymized",
            membership,
            {"person_id": person.id, "applications_redacted": applications_redacted},
        )
        if user is not None:
            erase_account(user)  # `user` keeps the values read under the lock
        lost = before - User.get_by_id(user.id).effective_herd_ids() if user is not None else set()
        lost_genebanks = (
            {h.genebank_id for h in Herd.select(Herd.genebank).where(Herd.id.in_(list(lost)))} if lost else set()
        )
        # the intake queue's photos that show the person, and what they sent (their account read before the detach)
        originals = erase_person_from_inbox(person, user.id if user is not None else None)
        pictures = set()
        if user is not None and deferred_accounts is None:
            pictures = profile_pictures_of(user)  # before the purge takes their names
            purge_user_audit_pii(user.id, user.username, user.email)  # last: it locks audit_log until the commit
    if deferred_originals is None:
        remove_originals(originals)  # only after the commit: a row never names a removed file
    else:
        deferred_originals.extend(originals)
    for name in pictures:
        remove_profile_picture(name)
    if user is not None and deferred_accounts is not None:
        deferred_accounts.append(user)
    _invalidate_genebanks(lost_genebanks)
    return person


ENDED_MEMBER_RETENTION = "12 months"  # a PostgreSQL interval: calendar months, as the privacy policy says (#34)
# Account roles that keep an ended person from automatic erasure. Every account is a viewer, so viewer is not one;
# a legacy owner entry counts only on an active herd (_retention_hold).
RETENTION_HOLD_LEVELS = frozenset({"admin", "matrikel_admin", "manager"})


def _retention_hold(user) -> str | None:
    """Why this account keeps its person from automatic erasure: "role", "active_herd" or None."""
    if user is None:
        return None
    privileges = user.privileges or []
    if any(p["level"] in RETENTION_HOLD_LEVELS for p in privileges):
        return "role"
    owned = [p["herd"] for p in privileges if p["level"] == "owner"]
    if owned and Herd.select().where(Herd.id.in_(owned), Herd.is_active == True).exists():  # noqa: E712
        return "active_herd"
    return None


def _due_in(membership, cutoff):
    """
    The persons of `membership` the nightly job anonymizes (#70), and the holds it leaves to the administrator.

    A membership without an active person has ended: its persons are due once the LATEST end_date (anonymized
    persons included) is before `cutoff`, all together, so the household address is never cleared early. Any
    person's account role, or an active herd of the membership or of a person's legacy owner entry, holds the
    whole membership. In a membership that still has an active person, each ended person is due once their own
    end_date is before `cutoff`, held only by their own account. Returns (due persons, held) where held is a list
    of (membership_id, person_id or None for the whole membership, reason).
    """
    persons = list(Member.select().where(Member.membership == membership).order_by(Member.id))
    erasable = [p for p in persons if p.end_date is not None and not is_anonymized(p)]
    if any(p.end_date is None for p in persons):
        due, held = [], []
        for person in erasable:
            if person.end_date < cutoff:
                reason = _retention_hold(person.user)
                if reason:
                    held.append((membership.id, person.id, reason))
                else:
                    due.append(person)
        return due, held
    if max(p.end_date for p in persons) >= cutoff:
        return [], []
    reason = next((r for r in map(_retention_hold, (p.user for p in erasable)) if r), None)
    if reason is None and Herd.select().where(Herd.membership == membership, Herd.is_active == True).exists():  # noqa: E712
        reason = "active_herd"
    return ([], [(membership.id, None, reason)]) if reason else (erasable, [])


def _memberships_with_ended_persons(cutoff):
    """Memberships with a person ended before `cutoff` and not yet anonymized: the nightly job's candidates."""
    not_erased = ~((Member.first_name == ANONYMIZED_FIRST_NAME) & (Member.last_name == ANONYMIZED_LAST_NAME))
    ended = Member.select(Member.membership).where(Member.end_date < cutoff, not_erased)
    return list(Membership.select(Membership.id).where(Membership.id.in_(ended)).order_by(Membership.id))


def anonymize_ended_persons(now):
    """
    Nightly job (#70): anonymize_person, with no user as actor, on the persons _due_in finds. Each membership is
    decided again and erased in one transaction that first locks every row _due_in reads: the membership (retire,
    delete and add lock it), its accounts (update_role locks them) and the herds that can hold it (update_herd
    writes them). A change to any of them commits before the decision or waits until after the erasure; a herd
    moved INTO the membership after the herd lock lands as if moved just after the erasure. Lock order
    membership, accounts, herds, as in _lock_for_detach. All three are NO KEY locks: they still wait for those
    writers, but not for an insert's foreign-key check on the row, which may hold another of these rows while it
    waits. A failure rolls back that membership only and is logged. Returns (anonymized persons, failed
    memberships, held).
    """
    cutoff = DB_PROXY.execute_sql(
        "SELECT (%s::timestamptz - %s::interval)::date", (now, ENDED_MEMBER_RETENTION)
    ).fetchone()[0]
    done, failed, held = 0, 0, []
    for membership in _memberships_with_ended_persons(cutoff):
        originals, erased, pictures = [], [], set()
        try:
            with DB_PROXY.atomic():
                Membership.select().where(Membership.id == membership.id).for_update("FOR NO KEY UPDATE").get()
                person_users = Member.select(Member.user).where(Member.membership == membership)
                accounts = list(
                    User.select().where(User.id.in_(person_users)).order_by(User.id).for_update("FOR NO KEY UPDATE")
                )
                owned = [p["herd"] for user in accounts for p in user.privileges or [] if p["level"] == "owner"]
                herds = Herd.select(Herd.id).where((Herd.membership == membership) | Herd.id.in_(owned))
                list(herds.order_by(Herd.id).for_update("FOR NO KEY UPDATE"))
                due, membership_held = _due_in(membership, cutoff)
                # An ended person conveys no herd, and the owner entries erase_account drops are on inactive herds (an
                # active one holds): an invalidation inside this tx only schedules a rebuild of an unchanged genebank.
                for person in due:
                    anonymize_person(person, None, deferred_originals=originals, deferred_accounts=erased)
                # Every account's command rows before the first purge's DROP RULE: an Undo that holds one of them
                # writes audit_log, which that purge locks until the commit.
                for account in erased:
                    purge_command_free_text(datetime.now(timezone.utc), actor_id=account.id)
                    pictures |= profile_pictures_of(account)  # before the purge takes their names
                for account in erased:  # last: the purge locks audit_log until the commit
                    purge_user_audit_pii(account.id, account.username, account.email)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Automatic anonymization failed for membership=%s", membership.id)
            failed += 1
            continue
        remove_originals(originals)  # after this membership's commit, as anonymize_person does after its own
        for name in pictures:
            remove_profile_picture(name)
        done += len(due)
        held += membership_held
    return done, failed, held


WAIT = timedelta(days=7)
# A previous address is purged this long after it stops counting: its besked has gone by then (retries end in 21 h).
PREVIOUS_KEPT = timedelta(days=2)
SET_BY = ("self", "other", "matrikel")


def _same(a, b):
    return (a or "").strip().lower() == (b or "").strip().lower()


def _expire_previous_addresses(member_ids):
    now = datetime.now(timezone.utc)
    MemberPreviousAddress.update(login_until=now, purge_at=now + PREVIOUS_KEPT).where(
        MemberPreviousAddress.member.in_(member_ids), MemberPreviousAddress.login_until > now
    ).execute()


def set_member_email(person, address, actor, *, by):
    """
    THE writer of an existing person's Member.email. For a person who holds a login address (a main member, or a
    person with an account; utils.login_code) the address is reserved (AddressTaken) and:

    - by="self", the member after a code to the new address: the old address counts for login seven more days, the
      new one at once;
    - by="other": the old one seven more days, the new one only after them (email_login_from);
    - by="matrikel": the old one stops, the new one counts at once.

    During a wait the first previous address stays fixed: a new change restarts its clock, but never makes the
    address in between count, nor one that has stopped. Changing back to it ends the wait. The address replaced,
    and during a wait the first previous one, hear of the change (kontakt.epost_besked); an address that does not
    count gets a row with login_until NULL for it. The account's sessions end (new_generation). Every change voids
    the person's unused codes. A family member or keeper someone put in (add_person) and not yet told gets
    medlemskap.tillagd (queue_member_added).
    Opens its own transaction; returns the person as written.
    """
    if by not in SET_BY:
        raise ValueError(f"unknown change {by!r}")
    address = (address or "").strip() or None
    with DB_PROXY.atomic():
        person, user = _lock_for_detach(person.id)  # membership → user → person
        friexemplar = person.membership.membership_status == Status.FRIEXEMPLAR
        if friexemplar and person.email != address:
            _expire_previous_addresses([person.id])
        if _same(person.email, address):
            if person.email != address:  # the same address, spelled otherwise
                Member.update(email=address).where(Member.id == person.id).execute()
            return Member.get_by_id(person.id)
        holder = (
            not friexemplar and person.end_date is None and (person.role == "huvudmedlem" or person.user_id is not None)
        )
        told, login_from = [], None
        if holder:
            # Every address this change can touch, locked in one order before the previous ones are read: a clock
            # restarted on an old address must not race another person reserving it as it stops counting.
            rows = MemberPreviousAddress.select(MemberPreviousAddress.address)
            lock_addresses(
                [address, person.email, *(r.address for r in rows.where(MemberPreviousAddress.member == person.id))]
            )
            reserve_login_address(address, person.id)
            now = datetime.now(timezone.utc)
            told, back = _keep_previous(person, address, actor, by, now)
            if by == "other" and not back:
                login_from = now + WAIT
        Member.update(email=address, email_login_from=login_from, updated_at=datetime.now()).where(
            Member.id == person.id
        ).execute()
        if _added_by_another(person):  # the address came later or changed, or the notice never reached her
            queue_member_added(Member.get_by_id(person.id))
        void(person.id)
        for row in told:
            params = {"previous_id": row.id, "by_self": by == "self", "by_matrikel": by == "matrikel"}
            ref = ("membership", person.membership_id)
            enqueue_mail("kontakt.epost_besked", "member_previous_address", row.id, params, ref=ref)
        if holder and user is not None:
            new_generation(user.uuid)
    return Member.get_by_id(person.id)


def _added_by_another(person):
    """add_person put her in as family member or keeper, and she was never main member: not the register import."""
    added = MatrikelAudit.select().where(
        (MatrikelAudit.membership == person.membership_id)
        & (MatrikelAudit.action == "person_added")
        & (MatrikelAudit.payload["person_id"] == str(person.id))
        & MatrikelAudit.payload["role"].in_(("familjemedlem", "skotare"))
    )
    return added.exists() and not was_main_member(person)


def _keep_previous(person, address, actor, by, now):
    """
    The previous-address rows of a change (set_member_email): (the rows to tell, whether the change went back). The
    address replaced is always told; during a wait the first previous address is told too, as the change may come
    from whoever took over the account.
    """
    waiting = (
        MemberPreviousAddress.select()
        .where((MemberPreviousAddress.member == person.id) & (MemberPreviousAddress.login_until > now))
        .order_by(MemberPreviousAddress.id)
        .first()
    )
    back = waiting is not None and _same(waiting.address, address)
    until = None if by == "matrikel" or back else now + WAIT
    told = []
    if waiting is not None:
        waiting.login_until, waiting.purge_at, waiting.changed_by = until, (until or now) + PREVIOUS_KEPT, actor
        waiting.save()
        if not back:
            told.append(waiting)
            until = None  # the address in between never counts
    if person.email is not None:
        if person.email_login_from is not None and person.email_login_from > now:
            until = None  # it never counted, and never will
        told.append(
            MemberPreviousAddress.create(
                member=person.id,
                address=person.email,
                login_until=until,
                purge_at=(until or now) + PREVIOUS_KEPT,
                changed_by=actor,
            )
        )
    return told, back


def purge_previous_addresses(now):
    """
    Nightly: previous addresses past their purge_at go, and the mail queue forgets where their mails went, in one
    transaction, so an interrupted run leaves nothing half done and the next one finishes it.
    """
    with DB_PROXY.atomic():
        gone = MemberPreviousAddress.delete().where(MemberPreviousAddress.purge_at < now)
        ids = [row.id for row in gone.returning(MemberPreviousAddress.id).execute()]
        for row_id in ids:
            forget_recipient("member_previous_address", row_id)
    return len(ids)


def new_membership(status, **fields):
    """The only place a Membership row is created: `status` must be a Status the CREATE rows allow."""
    status = Status(status).value
    next_state(None, Event.CREATE, status)
    return Membership.create(membership_status=status, **fields)


def set_membership_status(membership, new_status, actor):
    """Move `membership` to `new_status` if membership_lifecycle has a row for it, and audit the change.

    Call inside the caller's transaction with the membership row locked FOR UPDATE. Raises
    TransitionRefused (nothing written) when the table has none, e.g. for a retired membership.
    Sets the attribute only: the caller saves it with the rest of its columns. Returns whether the membership
    becomes active: then the caller calls herd_contact.on_membership_active after its save, in the same
    transaction, so that the herds linked meanwhile are compared with all of the saved membership (#117).
    """
    new_status = Status(new_status).value
    has_main = (
        Member.select()
        .where(Member.membership == membership, Member.role == "huvudmedlem", Member.end_date.is_null(True))
        .exists()
    )
    next_state(state_of(membership.membership_status, has_main), Event.SET_STATUS, new_status)
    if (membership.membership_status == Status.FRIEXEMPLAR) != (new_status == Status.FRIEXEMPLAR):
        # an address a friexemplar kept from before (or from earlier as a member) never counts again
        _expire_previous_addresses(Member.select(Member.id).where(Member.membership == membership))
    if membership.membership_status == Status.FRIEXEMPLAR and new_status != Status.FRIEXEMPLAR:
        reserve_on_leaving_friexemplar(membership.id)
    write_matrikel_audit(
        actor,
        "membership_status_changed",
        membership,
        # Nested {"before": {field: ...}, "after": {...}} shape, like the other membership mutations.
        {"before": {"membership_status": membership.membership_status}, "after": {"membership_status": new_status}},
    )
    activated = new_status == Status.ACTIVE and membership.membership_status != Status.ACTIVE
    membership.membership_status = new_status
    return activated


def create_membership(data, actor):
    """Create a membership with its initial huvudmedlem in one transaction.

    Admin/matrikel_admin may create memberships
    directly (not only via application approval or CSV import). `data` keys: organization_name,
    organization_number, first_name, last_name (optional for an organization's contact), email,
    phone, membership_status (default 'active'), address, postal_code, city,
    payment_note, notes, allocate (bool — allocate a member_number). The
    address is always structured here: the endpoint resolves the legacy
    `postal_address` alias with parse_postal_fields() before calling, and the
    CSV importer creates Membership rows directly. Locks the counter FIRST
    when allocating, matching the approval lock order. AddressTaken when
    another person holds the main member's address for login.
    """
    status = data.get("membership_status") or "active"
    organization = parse_organization_fields(data)
    names = _new_person_names(data, optional=organization.get("organization_name"))
    with DB_PROXY.atomic():
        number = allocate_member_number() if data.get("allocate") else None
        membership = new_membership(
            status,
            member_number=number,
            **organization,
            address=data.get("address") or None,
            postal_code=data.get("postal_code") or None,
            city=data.get("city") or None,
            payment_note=data.get("payment_note") or None,
            notes=data.get("notes") or None,
        )
        main = Member.create(
            membership=membership,
            role="huvudmedlem",
            **names,
            email=data.get("email") or None,
            phone=data.get("phone") or None,
        )
        if status != Status.FRIEXEMPLAR:
            reserve_login_address(main.email, main.id)
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
        contacts = snapshot_before_leaving(persons[0]) if persons else None
        for person in persons:
            HerdAccessGrant.update(revoked_at=now, updated_at=now).where(
                HerdAccessGrant.member == person,
                HerdAccessGrant.revoked_at.is_null(True),
            ).execute()
            person.end_date = date.today()
            person.save()
        cancel_member_added([p.id for p in persons])
        membership.membership_status = "inactive"
        # `membership` is the CALLER's pre-lock instance — a full-row save would
        # overwrite a notes/address PATCH that committed while we waited for the
        # lock. Write only the column this operation owns (T5a deferred minor).
        membership.save(only=[Membership.membership_status, Membership.updated_at])
        if persons:  # one pass covers everyone who left
            on_person_leaving(persons[0], contacts)
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
        holder = (
            Member.select(
                Member.id,
                Member.first_name,
                Member.last_name,
                Member.role,
                Member.end_date,
                Membership.id,
                Membership.member_number,
                Membership.organization_name,
            )
            .join(Membership)
            .where(Member.user == user)
            .first()
        )
        if holder is not None:
            # A friexemplar/pending membership has no number — never render "nr None".
            number = holder.membership.member_number or "–"
            ended = f" (avslutad {holder.end_date.isoformat()})" if holder.end_date else ""
            raise LinkError(
                "Kontot är redan kopplat",
                f"Kontot är redan kopplat till {holder.display_name} i medlemskap nr {number}{ended}",
                holder_person_id=holder.id,
            )
        try:
            reserve_holder(person.id)
        except AddressTaken as exc:
            detail = "En annan medlem kan redan logga in med personens e-postadress"
            raise LinkError(AddressTaken.title, detail) from exc
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


def _detach_user_locked(person: Member, *, actor: User | None, mode: str) -> int:
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


def legacy_owner_index(*fields) -> tuple[dict[int, dict[int, User]], set[int]]:
    """Herd id -> {user id: user} with role owner, and the users with an incomplete owner role."""
    owners: dict[int, dict[int, User]] = {}
    incomplete: set[int] = set()
    for user in User.select(*fields).order_by(User.id):
        for role in user.privileges:
            if not isinstance(role, dict) or "level" not in role:
                incomplete.add(user.id)  # link_access_delta reads role["level"]
                continue
            if role["level"] != "owner":
                continue
            herd_id = role.get("herd")
            if isinstance(herd_id, str) and re.fullmatch(r"[0-9]+", herd_id):
                herd_id = int(herd_id)  # Match historical ids for the listing only.
            if isinstance(herd_id, bool) or not isinstance(herd_id, int):
                incomplete.add(user.id)
                continue
            owners.setdefault(herd_id, {})[user.id] = user
    return owners, incomplete


_DUPLICATE_HERD_CODE = "koden finns i flera genbanker"


def _other_genebank_codes(genebank_id: int):
    return Herd.select(Herd.herd).where(Herd.genebank != genebank_id)


def membership_herd_candidates(membership_id: int, genebank_id: int) -> list[dict]:
    rows = (
        Herd.select(
            Herd.id,
            Herd.herd,
            Herd.herd_name,
            Herd.is_active,
            Herd.membership,
            Membership.id,
            Membership.member_number,
            Herd.herd.in_(_other_genebank_codes(genebank_id)).alias("duplicate_code"),
        )
        .join(Membership, JOIN.LEFT_OUTER)
        .where(Herd.genebank == genebank_id, Herd.herd.not_in(OUTSIDE_GENEBANK_HERDS))
    )
    result = []
    for herd in sorted(rows, key=lambda h: (int(re.sub(r"\D", "", h.herd) or 0), h.herd, h.id)):
        link = "ingen"
        if herd.membership_id is not None:
            link = "detta" if herd.membership_id == membership_id else "annat"
        result.append(
            {
                **_link_herd_summary(herd),
                "link": link,
                "unavailable_reason": _DUPLICATE_HERD_CODE if herd.duplicate_code else None,
                "member_number": herd.membership.member_number if link == "annat" else None,
            }
        )
    return result


def _link_herd_summary(herd: Herd) -> dict:
    return {"id": herd.id, "herd": herd.herd, "herd_name": herd.herd_name, "is_active": bool(herd.is_active)}


_CONTACT_LABELS = {"name": "Namn", "email": "E-post", "mobile_phone": "Mobil", "physical_address": "Adress"}
_CONTACT_EFFECTS = {
    "person": "Besättningens kopia av namnet töms.",
    "fritext": "Besättningens namn behålls och väntar på val av kontaktperson.",
    "lika": "Besättningens kopia töms. Uppgiften hämtas från matrikeln.",
    "olika": "Uppgifterna skiljer sig. Besättningens värde behålls i väntan på val.",
    "bara_besattningen": "Besättningens egen uppgift behålls.",
    "bara_matrikeln": "Uppgiften hämtas från matrikeln. Raden visas inte förrän någon väljer.",
    "bada_tomma": "Uppgiften saknas på båda ställena. Raden visas inte förrän någon väljer.",
}


def _account_summary(user: User) -> dict:
    return {"id": user.id, "username": user.username}


def _contact_link_preview(herd: Herd) -> tuple[list[dict], dict]:
    changes, cases = compare_with_register(herd)
    rows = []
    for field, case in cases.items():
        effect = _CONTACT_EFFECTS[case]
        if field == "name" and "contact_member" in changes:
            person = (
                Member.select(Member.first_name, Member.last_name, Member.role, Membership.organization_name)
                .join(Membership)
                .where(Member.id == changes["contact_member"])
                .get()
            )
            effect = f"{person.display_name} blir kontaktperson. {effect}"
        rows.append({"field": field, "label": _CONTACT_LABELS[field], "case": case, "effect": effect})
    return rows, changes


def _herd_link_preview(
    herd: Herd, membership: Membership, main: User | None, accounts: dict[int, User]
) -> tuple[dict, dict]:
    active = membership.membership_status == Status.ACTIVE
    owners, _ = legacy_owner_index(User.id, User.username, User._privileges, User.is_active)
    legacy_owners = [
        {**_account_summary(u), "in_membership": uid in accounts, "gains_household_grants": active and u == main}
        for uid, u in owners.get(herd.id, {}).items()
        if u.is_active
    ]
    grant_holders = (
        User.select(User.id, User.username)
        .join(Member)
        .join(Membership)
        .switch(Member)
        .join(HerdAccessGrant)
        .where(
            User.is_active,
            Member.end_date.is_null(True),
            Membership.membership_status == Status.ACTIVE,
            HerdAccessGrant.herd == herd,
            HerdAccessGrant.revoked_at.is_null(True),
            HerdAccessGrant.valid_until.is_null(True) | (HerdAccessGrant.valid_until >= date.today()),
        )
        .distinct()
        .order_by(User.id)
    )
    new_access, new_readers, contact_rows, contact_changes = None, [], None, {}
    try:
        if main is not None and main.is_active and (not active or herd.id not in main.transfer_herd_ids()):
            new_access = {
                **_account_summary(main),
                # integer ids, as the write policies compare; no SQL on stored role values
                "already_edits": herd.id in main.effective_herd_ids(),
                "already_manages": main.is_admin or herd.genebank_id in (main.is_manager or []),
            }
        if active:
            potential_readers = [u for u in accounts.values() if u.is_active and not is_matrikel_reader(u, herd)]
            herd.membership = membership  # in memory only; link_herd re-reads the locked row
            new_readers = [_account_summary(u) for u in potential_readers if is_matrikel_reader(u, herd)]
    except (KeyError, TypeError) as err:
        raise LinkError("Åtkomsten kan inte beräknas", "Ett konto i medlemskapet har en ofullständig roll.") from err
    if active:
        contact_rows, contact_changes = _contact_link_preview(herd)
    return {
        "herd": {**_link_herd_summary(herd), "genebank_id": herd.genebank_id, "genebank_name": herd.genebank.name},
        "membership": {
            "id": membership.id,
            "member_number": membership.member_number,
            "membership_status": membership.membership_status,
        },
        "new_access": new_access,
        "inactive_main_account": _account_summary(main) if main is not None and not main.is_active else None,
        "new_readers": new_readers,
        "legacy_owners": legacy_owners,
        "grant_holders": [_account_summary(u) for u in grant_holders],
        "contact_rows": contact_rows,
    }, contact_changes


def link_membership_herd(membership_id: int, herd_id: int, confirm_token: str | None, actor: User) -> dict:
    """Preview under link_herd's locks, or commit the exact preview the administrator confirmed."""
    with DB_PROXY.atomic():
        membership = Membership.select().where(Membership.id == membership_id).for_update().first()
        if membership is None:
            raise LinkError("Hittades inte", f"Medlemskapet {membership_id} finns inte", status=404)
        main_member = (
            Member.select(Member.id, Member.user)
            .where(Member.membership == membership, Member.role == "huvudmedlem", Member.end_date.is_null(True))
            .first()
        )
        if main_member is None:  # RETIRED or HEADLESS, regardless of the stored status.
            raise LinkError(
                "Medlemskapet saknar aktiv huvudmedlem",
                "Medlemskapet saknar aktiv huvudmedlem och kan därför inte få en besättning.",
            )
        # Role and account changes lock users independently of the membership. Lock the
        # household accounts by id before the herd, in the same order as anonymization.
        accounts = {
            u.id: u
            for u in User.select(User.id, User.username, User._privileges, User.is_active)
            .join(Member)
            .where(Member.membership == membership, Member.end_date.is_null(True))
            .order_by(User.id)
            .for_update("FOR SHARE")
        }
        herd = Herd.select().where(Herd.id == herd_id).for_update().first()
        if herd is None:
            raise LinkError("Hittades inte", f"Besättningen {herd_id} finns inte", status=404)
        if herd.herd in OUTSIDE_GENEBANK_HERDS:
            raise LinkError(
                "Besättningen kan inte kopplas",
                "Besättningen samlar kaniner sålda utanför genbanken.",
                type="herd-unavailable",
            )
        if _other_genebank_codes(herd.genebank_id).where(Herd.herd == herd.herd).exists():
            raise LinkError(
                "Besättningen kan inte kopplas",
                f"Besättningen kan inte kopplas eftersom {_DUPLICATE_HERD_CODE}.",
                type="herd-unavailable",
            )
        if herd.membership_id is not None:
            target = "detta medlemskap"
            if herd.membership_id != membership_id:
                number = herd.membership.member_number
                target = f"medlemskap nr {number}" if number is not None else "ett annat medlemskap utan nummer"
            raise LinkError(
                "Besättningen är redan kopplad",
                f"Besättningen är redan kopplad till {target}.",
                type="herd-unavailable",
            )

        preview, changes = _herd_link_preview(herd, membership, accounts.get(main_member.user_id), accounts)
        confirmation = (preview, changes, main_member.id, main_member.user_id)
        token = hashlib.sha256(json.dumps(confirmation, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if confirm_token != token:
            raise LinkError(
                "Bekräfta kopplingen",
                "Granska vad kopplingen ger och bekräfta.",
                type="confirm-required",
                preview=preview,
                confirm_token=token,
            )
        cases = link_herd(herd.id, membership.id, herd_code=herd.herd, genebank_id=herd.genebank_id)
        if cases is None:
            raise LinkError(
                "Besättningen har ändrats", "Försök igen för att granska besättningen på nytt.", type="stale"
            )
        write_matrikel_audit(
            actor,
            "herd_membership_linked",
            membership,
            {"herd_id": herd.id, "main_member_id": main_member.id, "source": "matrikel"},
        )
    _invalidate_genebanks([herd.genebank_id])
    return {**preview["herd"], "membership_id": membership_id}
