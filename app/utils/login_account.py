"""Account creation after a person in the matrikel has proved control of a login address."""

import os
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

import requests
from flask import current_app, session
from peewee import fn

from utils import data_access, login_code, matrikel, settings
from utils.database import DB_PROXY, AccountRulesSnapshot, Herd, HerdAccessGrant, Member, User
from utils.mail import address_hash

PENDING_FOR = timedelta(minutes=15)


class InvalidPending(Exception):
    """The proof has expired or its member, address or instance changed."""


class AccountConflict(Exception):
    """An account may already belong to this member."""


class RulesUnavailable(Exception):
    """The CMS has no readable published rules."""


class RulesChanged(Exception):
    """The current publication differs from the one displayed."""


def start_pending(person, row, epoch):
    """Replace any previous login with a short-lived proof in a fresh server-side session."""
    session.clear()
    session.update(
        pending_member_id=person.id,
        logout_epoch=epoch,
        pending_demo=settings.service.demo_instance,
        pending_until=(datetime.now(timezone.utc) + PENDING_FOR).timestamp(),
        pending_address=row.address_hash,
        pending_contact=address_hash(person.email),
    )
    current_app.session_interface.regenerate(session)


def pending_valid():
    return (
        not settings.service.demo_instance
        and session.get("pending_demo") is False
        and not session.get("user_id")
        and bool(session.get("pending_member_id"))
        and session.get("logout_epoch") == data_access.logout_epoch()
        and session.get("pending_until", 0) > datetime.now(timezone.utc).timestamp()
    )


def published_rules():
    """Read the current published version through the server-configured CMS endpoint."""
    origin = os.getenv("NEXT_INTERNAL_ORIGIN")
    if not origin:
        return None
    try:
        response = requests.get(
            f"{origin.rstrip('/')}/cms-api/kontoregler/version",
            timeout=3,
            allow_redirects=False,
            headers={"Cache-Control": "no-store"},
        )
        if response.status_code == 200 and isinstance(body := response.json(), dict):
            version, text = body.get("version"), body.get("text")
            if isinstance(version, str) and version.strip() and isinstance(text, str) and text.strip():
                return version, text
    except (requests.RequestException, ValueError):
        pass
    return None


def _existing_account(person, address):
    addresses = {a.strip().lower() for a in (person.email, address) if a}
    linked_accounts = Member.select(Member.user).where(Member.user.is_null(False))
    if (
        User.select()
        .where(
            User.id.not_in(linked_accounts),
            fn.LOWER(fn.BTRIM(User.email)).in_(addresses) | fn.LOWER(fn.BTRIM(User.google_email)).in_(addresses),
        )
        .exists()
    ):
        return True

    herd_ids = {str(h.id) for h in Herd.select(Herd.id).where(Herd.membership == person.membership_id)}
    # A grant can be on a herd outside the membership, where an older owner account may be hers.
    grants = HerdAccessGrant.select(HerdAccessGrant.herd).where(
        (HerdAccessGrant.member == person.id) & HerdAccessGrant.revoked_at.is_null(True)
    )
    herd_ids |= {str(g.herd_id) for g in grants}
    owners = User.select(User._privileges).where(User._privileges.contains('"owner"'))
    # For anyone but the main member, her linked account owns the herds: only an unlinked owner may be this person.
    if person.role != "huvudmedlem":
        owners = owners.where(User.id.not_in(linked_accounts))
    # Older owner roles can have a herd id stored as a string.
    return bool(herd_ids) and any(
        isinstance(role, dict) and role.get("level") == "owner" and str(role.get("herd")).lstrip("0") in herd_ids
        for account in owners
        for role in account.privileges
    )


def create_pending_account(_displayed_version, displayed_sha256):
    """Recheck the proof and possible accounts under lock, then insert and link one new user atomically."""
    rules = published_rules()
    if rules is None:
        raise RulesUnavailable
    version, text = rules
    digest = sha256(text.encode("utf-8")).hexdigest()
    # A reseed can republish the same text under a new revision.
    if digest != displayed_sha256:
        raise RulesChanged

    with DB_PROXY.atomic():
        person_id = session["pending_member_id"]
        try:
            matrikel.lock_person_membership(person_id)
        except matrikel.LinkError as exc:
            raise InvalidPending from exc
        person = Member.select().where(Member.id == person_id).for_update().get()
        if person.user_id is not None:
            raise AccountConflict
        contact = (person.email or "").strip()
        if not contact or address_hash(contact) != session["pending_contact"]:
            raise InvalidPending
        login_code.lock_holder_addresses(person)
        # Existing accounts can acquire an address or an owner role outside the registry.
        # Serialize the duplicate check and insert with all writes to hbuser, including new accounts.
        DB_PROXY.execute_sql("LOCK TABLE hbuser IN SHARE ROW EXCLUSIVE MODE")
        address = login_code.login_address(person, session["pending_address"])
        if not address:
            raise InvalidPending
        login_code.require_open()
        if not pending_valid():
            raise InvalidPending
        try:
            data_access._lock_available_account_email(contact)
        except data_access.AddressInUseError as exc:
            raise AccountConflict from exc
        if _existing_account(person, address):
            raise AccountConflict
        accepted_at = datetime.now(timezone.utc)
        AccountRulesSnapshot.get_or_create(
            sha256=digest, defaults={"text": text, "cms_version": version, "first_accepted_at": accepted_at}
        )
        user = User.create(
            uuid=uuid4(),
            email=contact,
            fullname=f"{person.first_name} {person.last_name}".strip(),
            privileges=[{"level": "viewer", "genebank": n} for n in (1, 2)],
            rules_version=version,
            rules_accepted_at=accepted_at,
            rules_snapshot=digest,
            v2_prod_access=os.getenv("SJALVSKAPAT_KONTO_PROD", "false").lower() == "true",
        )
        try:
            _, conveyed = matrikel.link_member_user(
                person.id, user.id, actor=user, mode="matrikel_epost", invalidate=False
            )
        except matrikel.LinkError as exc:
            raise InvalidPending from exc
        generation = data_access.login_generation(user.uuid)
    matrikel._invalidate_genebanks(h["genebank_id"] for h in conveyed)
    return user, generation
