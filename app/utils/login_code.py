"""
One-time codes by mail (docs/mejl.md, "Engångskoder"). A row in login_code holds a nonce, never the code: the eight
digits are computed from the nonce and LINK_SECRET (utils.mail.one_time_code). A code belongs to one person, one
purpose (`login` or `ny_adress`) and the browser that asked for it, and holds for ten minutes, once, with three tries.
"""

import hashlib
import hmac
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from peewee import fn

import utils.settings as settings
from utils.data_access import holds_role
from utils.database import DB_PROXY, LoginCode, Member, MemberPreviousAddress
from utils.mail import Recipient, address_hash, forget_recipient, link_token, mail_kind, one_time_code, recipient_kind

logger = logging.getLogger("herdbook.login_code")

VALID_FOR = timedelta(minutes=10)
TRIES = 3
A_PERSON_A_DAY = 5
AN_HOUR = 120  # codes, so mails, in all
WRONG_AN_HOUR = 50  # then code login is closed
KEPT = timedelta(days=1)


class CodeRefused(RuntimeError):
    """This server does not run codes: LINK_SECRET is missing, or production would only log the mail."""


class CodeLoginClosed(Exception):
    """WRONG_AN_HOUR wrong codes in the last hour: no code is issued or accepted until they age out."""


def _utcnow():
    return datetime.now(timezone.utc)


def enabled():
    return os.environ.get("KODINLOGGNING", "false").lower() == "true" and not settings.service.demo_instance


def refuse_unsafe():
    if not settings.mail.link_secret:
        raise CodeRefused("LINK_SECRET is not set")
    if settings.mail.mode == "log" and os.environ.get("FLASK_ENV") == "production":
        raise CodeRefused("MAIL_MODE=log in production: a code would never arrive")


def _lock():
    """One lock for issuing and checking, so the counts below are exact. Held to the end of the transaction."""
    DB_PROXY.execute_sql("SELECT pg_advisory_xact_lock(hashtext('login_code'))")


def closed(now=None):
    """
    Wrong tries on rows made in the last hour and VALID_FOR. A try comes at most VALID_FOR after its row, so every
    wrong code of the last hour counts, and one may count up to VALID_FOR longer; a correct one is taken back when
    it is used (consume).
    """
    since = (now or _utcnow()) - timedelta(hours=1) - VALID_FOR
    wrong = LoginCode.select(fn.COALESCE(fn.SUM(LoginCode.failed), 0)).where(LoginCode.created_at > since).scalar()
    return wrong >= WRONG_AN_HOUR


def browser_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def code(row):
    """The row's code, eight digits as text: leading zeros are part of it."""
    return one_time_code(row.id, row.nonce)


def shown(digits):
    """`4827 1953`: two groups of four, as mails and pages show a code."""
    return f"{digits[:4]} {digits[4:]}"


def issue(person, purpose, browser, address, replaces=None):
    """
    A code for `person`, to `address`, bound to the browser holding the secret `browser`, in the caller's
    transaction (which queues its mail). Earlier unused codes stop working first, also when no new code is made: for
    a new address every one of the person's, as she is logged in and only her latest request counts; for a login
    only the browser's own, made with its previous secret `replaces`, as another's request must never void hers.
    None when a limit stops it: A_PERSON_A_DAY for the person, AN_HOUR in all, or code login closed. The caller
    answers the same either way.
    """
    refuse_unsafe()
    if not DB_PROXY.in_transaction():
        raise RuntimeError("issue() runs in the transaction that queues the code's mail")
    _lock()
    now = _utcnow()
    earlier = (LoginCode.purpose == purpose) & LoginCode.used_at.is_null(True)
    if purpose == "ny_adress":
        _void(earlier & (LoginCode.member == person.id))
    elif replaces:
        _void(earlier & (LoginCode.browser_hash == browser_hash(replaces)))
    if closed(now):
        logger.warning("No code for member %s: code login is closed", person.id)
        return None
    today = LoginCode.select().where((LoginCode.member == person.id) & (LoginCode.created_at > now - timedelta(days=1)))
    if today.count() >= A_PERSON_A_DAY:
        logger.warning("No code for member %s: %s codes today", person.id, A_PERSON_A_DAY)
        return None
    if LoginCode.select().where(LoginCode.created_at > now - timedelta(hours=1)).count() >= AN_HOUR:
        logger.warning("No code for member %s: %s codes in the last hour", person.id, AN_HOUR)
        return None
    return LoginCode.create(
        member=person.id,
        user=person.user_id,
        purpose=purpose,
        address_hash=address_hash(address),
        new_address=address if purpose == "ny_adress" else None,
        nonce=secrets.token_hex(16),
        browser_hash=browser_hash(browser),
        created_at=now,
    )


_SEPARATORS = re.compile(r"[\s-]")
_DIGITS = re.compile(r"[0-9]{8}")


def check(purpose, browser, entered, member_id=None, *, link=False):
    """
    Return the live row for this browser and credential. A link lookup spends no try.
    Count a numeric try before comparing. Address changes commit the count independently.
    Sign-in checks inside its redemption transaction and commits every wrong numeric try.
    """
    refuse_unsafe()
    if DB_PROXY.in_transaction() and purpose != "login":
        raise RuntimeError("check() commits the try on its own: call it outside a transaction")
    with DB_PROXY.atomic():
        _lock()
        now = _utcnow()
        if closed(now):
            raise CodeLoginClosed
        if link:
            if purpose != "login" or not isinstance(entered, str) or not entered.isascii():
                return None
            row = login_row(browser)
            if row and hmac.compare_digest(login_link_token(row), entered):
                return row
            return None
        params = [browser_hash(browser), purpose, now - VALID_FOR]
        mine = ""
        if member_id is not None:
            mine, params = "AND member_id = %s", [*params, member_id]
        cursor = DB_PROXY.execute_sql(
            f"""
            UPDATE login_code SET failed = failed + 1
            WHERE id = (
                SELECT id FROM login_code
                WHERE browser_hash = %s AND purpose = %s AND used_at IS NULL AND created_at > %s {mine}
                ORDER BY id DESC LIMIT 1
            ) AND failed < %s
            RETURNING id
            """,
            [*params, TRIES],
        )
        found = cursor.fetchone()
    if found is None:
        return None
    row = LoginCode.get_by_id(found[0])
    digits = _SEPARATORS.sub("", entered) if isinstance(entered, str) else ""
    # fullmatch first: compare_digest takes ASCII only
    if not _DIGITS.fullmatch(digits) or not hmac.compare_digest(code(row), digits):
        return None
    return row


def consume(row, *, link=False):
    """
    Uses the row check() gave, in the caller's transaction: one UPDATE, so of two uses at once at most one wins. The
    try check() counted is taken back, as it was right. False when the row has been used, voided or has expired.
    """
    now = _utcnow()
    used = LoginCode.update(used_at=now, failed=LoginCode.failed - (0 if link else 1), new_address=None).where(
        (LoginCode.id == row.id) & LoginCode.used_at.is_null(True) & (LoginCode.created_at > now - VALID_FOR)
    )
    return used.execute() == 1


def _void(where):
    return LoginCode.update(used_at=_utcnow(), new_address=None).where(where).execute()


def cancel(browser, purpose="ny_adress"):
    """The browser's unused codes for `purpose` stop working: on logout, and when the member cancels her change."""
    if not browser:
        return 0
    return _void(
        (LoginCode.browser_hash == browser_hash(browser))
        & (LoginCode.purpose == purpose)
        & LoginCode.used_at.is_null(True)
    )


def void(member_id):
    """The person's address changed: none of her unused codes works any more, wherever it was sent."""
    return _void((LoginCode.member == member_id) & LoginCode.used_at.is_null(True))


def expire(now):
    """Leader job every minute: an expired code keeps no new address."""
    return (
        LoginCode.update(new_address=None)
        .where(LoginCode.new_address.is_null(False) & (LoginCode.created_at <= now - VALID_FOR))
        .execute()
    )


def purge(now):
    """
    Nightly: rows older than KEPT go, and the mail queue forgets where their mails went, in one transaction, so an
    interrupted run leaves nothing half done and the next one finishes it. At most AN_HOUR * 24 rows a day.
    """
    with DB_PROXY.atomic():
        gone = LoginCode.delete().where(LoginCode.created_at < now - KEPT).returning(LoginCode.id).execute()
        ids = [row.id for row in gone]
        for row_id in ids:
            forget_recipient("login_code", row_id)
    return len(ids)


# Every address a person holds for login, or will hold once a wait is over (utils.matrikel.set_member_email): her
# address, and a previous one while it still counts; an empty string is none. A holder is a person not ended who is
# the main member of her membership or has an account. That is wider than who gets a code (the membership must not
# be inactive too), so reactivating a membership cannot give a main member an address another person holds.
_ADDRESSES = """
    SELECT m.member_id, lower(btrim(m.email)) AS address FROM member m
    WHERE m.end_date IS NULL AND (m.role = 'huvudmedlem' OR m.user_id IS NOT NULL) AND btrim(m.email) <> ''
    UNION
    SELECT m.member_id, lower(btrim(r.address)) FROM member_previous_address r JOIN member m USING (member_id)
    WHERE m.end_date IS NULL AND (m.role = 'huvudmedlem' OR m.user_id IS NOT NULL) AND r.login_until > %(now)s
        AND btrim(r.address) <> ''
"""


def login_holder(address):
    """Resolve only an unambiguous reservation, including addresses still in their waiting period."""
    rows = DB_PROXY.execute_sql(
        f"SELECT member_id FROM ({_ADDRESSES}) a WHERE address = %(address)s LIMIT 2",
        {"now": _utcnow(), "address": address},
    ).fetchall()
    return Member.get_or_none(Member.id == rows[0][0]) if len(rows) == 1 else None


def login_address(person, hashed_address):
    """Resolve the original recipient again, using today's account, membership and address validity."""
    if person.end_date or person.membership.membership_status == "inactive":
        return None
    if person.user_id:
        if not person.user.is_active or holds_role(person.user, password_override=False):
            return None
    elif person.role != "huvudmedlem":
        return None
    now = _utcnow()
    previous = MemberPreviousAddress.select(MemberPreviousAddress.address).where(
        (MemberPreviousAddress.member == person.id) & (MemberPreviousAddress.login_until > now)
    )
    addresses = [p.address for p in previous]
    if person.email and (person.email_login_from is None or person.email_login_from <= now):
        addresses.append(person.email)
    for address in addresses:
        normalized = address.strip().lower()
        if address_hash(normalized) == hashed_address:
            holder = login_holder(normalized)
            if holder and holder.id == person.id:
                return normalized
    return None


def login_row(browser):
    """The browser's current redeemable login row. Only check() counts a numeric try."""
    return (
        LoginCode.select()
        .where(
            (LoginCode.browser_hash == browser_hash(browser))
            & (LoginCode.purpose == "login")
            & LoginCode.used_at.is_null(True)
            & (LoginCode.failed < TRIES)
            & (LoginCode.created_at > _utcnow() - VALID_FOR)
        )
        .order_by(LoginCode.id.desc())
        .first()
    )


class AddressTaken(Exception):
    """Another person holds the address for login. Only the matrikel admin and the approver of an application see it."""

    title = "Adressen används redan av en annan medlem"


def lock_addresses(addresses):
    """The locks on `addresses`, always in one order, so two writers that lock several cannot deadlock."""
    for address in sorted({(a or "").strip().lower() for a in addresses} - {""}):
        DB_PROXY.execute_sql("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"login_address:{address}",))


def reserve_holder(person_id):
    """
    A person becomes a holder again (main member, or an account linked): her address and every previous one that
    still counts are all reserved for her, or AddressTaken and the caller's change is rolled back.
    """
    person = Member.get_by_id(person_id)
    rows = MemberPreviousAddress.select().where(MemberPreviousAddress.member == person_id)
    lock_addresses([person.email, *(r.address for r in rows)])
    now = _utcnow()
    for address in [person.email, *(r.address for r in rows.where(MemberPreviousAddress.login_until > now))]:
        reserve_login_address(address, person_id)


def reserve_login_address(address, person_id):
    """
    Makes `address` a login address of `person_id` alone, in the caller's transaction that writes it: under a lock
    on the address, held to the commit, no other holder may have it. Raises AddressTaken. Every write that can make an
    address a login address calls it; a missed one makes two holders, and neither gets a code.
    """
    address = (address or "").strip().lower()
    if not address:
        return
    if not DB_PROXY.in_transaction():
        raise RuntimeError("reserve_login_address() runs in the transaction that writes the address")
    DB_PROXY.execute_sql("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"login_address:{address}",))
    taken = DB_PROXY.execute_sql(
        f"SELECT 1 FROM ({_ADDRESSES}) a WHERE address = %(address)s AND member_id <> %(person)s LIMIT 1",
        {"now": _utcnow(), "address": address, "person": person_id},
    ).fetchone()
    if taken:
        raise AddressTaken(AddressTaken.title)


def login_link_token(row):
    """Bind the mail link to the same row and nonce as its eight digits."""
    return link_token(f"login:{row.nonce}", row.id)


@recipient_kind("login_code")
def _code_recipient(row_id):
    """Recheck the row, account and original destination on each delivery attempt."""
    row = LoginCode.get_or_none(LoginCode.id == row_id)
    if row is None or row.used_at or row.created_at <= _utcnow() - VALID_FOR:
        return None
    person = row.member
    if person.user_id != row.user_id:
        return None
    if row.purpose == "ny_adress":
        address = row.new_address
    elif row.purpose == "login" and enabled() and row.failed < TRIES and not closed():
        try:
            refuse_unsafe()
        except CodeRefused:
            return None
        address = login_address(person, row.address_hash)
    else:
        return None
    return Recipient(address, f"{person.first_name} {person.last_name}") if address else None


@mail_kind("konto.kod", priority=0, category="T")
def _code_mail(params):
    row = LoginCode.get_or_none(LoginCode.id == params["code_id"])
    if row is None:
        return None
    return {"code": shown(code(row)), "token": login_link_token(row) if row.purpose == "login" else None}


def address_collisions(now=None):
    """How many login addresses two or more persons hold, a write having missed the reservation. Never which."""
    return DB_PROXY.execute_sql(
        f"SELECT count(*) FROM (SELECT address FROM ({_ADDRESSES}) a GROUP BY address HAVING count(*) > 1) c",
        {"now": now or _utcnow()},
    ).fetchone()[0]


def alarms(now=None):
    """The status view's alarms of code login (utils.mail.sender_alarms)."""
    found = []
    if closed(now):
        found.append(
            {"code": "kodinloggning_stangd", "message": "Kodinloggningen är stängd: för många felaktiga koder"}
        )
    collisions = address_collisions(now)
    if collisions:
        found.append({"code": "adresskrock", "message": f"{collisions} inloggningsadresser hör till fler än en person"})
    return found
