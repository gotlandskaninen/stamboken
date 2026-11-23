"""Account creation after a main member has proved control of a login address."""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import requests
from flask import current_app, session
from peewee import fn

from utils import data_access, login_code, matrikel, settings
from utils.database import DB_PROXY, Herd, Member, User
from utils.mail import address_hash

PENDING_FOR = timedelta(minutes=15)


class InvalidPending(Exception):
    """The proof has expired or its member, address or instance changed."""


class AccountConflict(Exception):
    """An account may already belong to this member."""


def start_pending(person, row):
    """Replace any previous login with a short-lived proof in a fresh server-side session."""
    session.clear()
    session.update(
        pending_member_id=person.id,
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
        and session.get("pending_until", 0) > datetime.now(timezone.utc).timestamp()
    )


def published_rules_version():
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
        if response.status_code == 200:
            body = response.json()
            version = body.get("version") if isinstance(body, dict) else None
            if isinstance(version, str) and version.strip():
                return version
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
    owners = User.select(User._privileges).where(User._privileges.contains('"owner"'))
    # Older owner roles can have a herd id stored as a string.
    return bool(herd_ids) and any(
        isinstance(role, dict) and role.get("level") == "owner" and str(role.get("herd")).lstrip("0") in herd_ids
        for account in owners
        for role in account.privileges
    )


def create_pending_account(version):
    """Recheck the proof and possible accounts under lock, then insert and link one new user atomically."""
    with DB_PROXY.atomic():
        person_id = session["pending_member_id"]
        try:
            matrikel.lock_person_membership(person_id)
        except matrikel.LinkError as exc:
            raise InvalidPending from exc
        person = Member.select().where(Member.id == person_id).for_update().get()
        if person.user_id is not None:
            raise AccountConflict
        if person.role != "huvudmedlem" or address_hash(person.email) != session["pending_contact"]:
            raise InvalidPending
        # Existing accounts can acquire an address or an owner role outside the registry.
        # Serialize the duplicate check and insert with all writes to hbuser, including new accounts.
        DB_PROXY.execute_sql("LOCK TABLE hbuser IN SHARE ROW EXCLUSIVE MODE")
        address = login_code.login_address(person, session["pending_address"])
        if not address or not pending_valid():
            raise InvalidPending
        if _existing_account(person, address):
            raise AccountConflict
        user = User.create(
            uuid=uuid4(),
            email=(person.email or address).strip(),
            fullname=f"{person.first_name} {person.last_name}".strip(),
            privileges=[{"level": "viewer", "genebank": n} for n in (1, 2)],
            rules_version=version,
            rules_accepted_at=datetime.now(timezone.utc),
            v2_prod_access=os.getenv("SJALVSKAPAT_KONTO_PROD", "false").lower() == "true",
        )
        try:
            matrikel.link_member_user(person.id, user.id, actor=user, mode="matrikel_epost")
        except matrikel.LinkError as exc:
            raise InvalidPending from exc
        return user, data_access.login_generation(user.uuid)
