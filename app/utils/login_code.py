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
from utils.database import DB_PROXY, LoginCode, Member, MemberPreviousAddress, Membership
from utils.mail import Recipient, address_hash, forget_recipient, mail_kind, one_time_code, recipient_kind
from utils.membership_lifecycle import Status

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


def _may_use_code(person):
    """Serialize issuing and redeeming a code with changes to the membership's status."""
    if person is None:
        return False
    eligible = Membership.select(Membership.id).where(
        Membership.id == person.membership_id, Membership.membership_status != Status.FRIEXEMPLAR
    )
    return eligible.for_update().first() is not None


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
    if not _may_use_code(person):
        return None
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


def check(purpose, browser, entered, member_id=None):
    """
    The browser's live code row for `purpose` when `entered` is its code, else None. The try is counted on the row
    first, in the statement that checks the limit of TRIES, and commits on its own, before the comparison: the
    caller cannot roll a wrong try back. A right code is then used with consume() in the transaction that acts on
    it. Raises CodeLoginClosed when code login is closed; the row is not touched then.
    """
    refuse_unsafe()
    if DB_PROXY.in_transaction():
        raise RuntimeError("check() commits the try on its own: call it outside a transaction")
    with DB_PROXY.atomic():
        _lock()
        now = _utcnow()
        if closed(now):
            raise CodeLoginClosed
        params = [browser_hash(browser), purpose, now - VALID_FOR]
        mine = ""
        if member_id is not None:
            mine, params = "AND member_id = %s", [*params, member_id]
        cursor = DB_PROXY.execute_sql(
            f"""
            UPDATE login_code SET failed = failed + 1
            WHERE id = (
                SELECT c.id FROM login_code c JOIN member USING (member_id) JOIN membership USING (membership_id)
                WHERE c.browser_hash = %s AND c.purpose = %s AND c.used_at IS NULL AND c.created_at > %s {mine}
                    AND membership_status <> 'friexemplar'
                ORDER BY c.id DESC LIMIT 1
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


def consume(row):
    """
    Uses the row check() gave, in the caller's transaction: one UPDATE, so of two uses at once at most one wins. The
    try check() counted is taken back, as it was right. False when the row has been used, voided or has expired.
    """
    if not _may_use_code(row.member):
        return False
    now = _utcnow()
    used = LoginCode.update(used_at=now, failed=LoginCode.failed - 1, new_address=None).where(
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


# Current and still-valid previous addresses of potential holders, including addresses in their seven-day wait.
_PERSON_ADDRESSES = """
    SELECT m.member_id, m.membership_id, lower(btrim(m.email)) AS address FROM member m
    WHERE m.end_date IS NULL AND (m.role = 'huvudmedlem' OR m.user_id IS NOT NULL) AND btrim(m.email) <> ''
    UNION
    SELECT m.member_id, m.membership_id, lower(btrim(r.address))
    FROM member_previous_address r JOIN member m USING (member_id)
    WHERE m.end_date IS NULL AND (m.role = 'huvudmedlem' OR m.user_id IS NOT NULL) AND r.login_until > %(now)s
        AND btrim(r.address) <> ''
"""

# Both sources are contact addresses only while the membership is a friexemplar.
_ADDRESSES = f"""
    SELECT a.member_id, a.address FROM ({_PERSON_ADDRESSES}) a JOIN membership ms ON ms.membership_id = a.membership_id
    WHERE ms.membership_status <> 'friexemplar'
"""


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
    if person.membership.membership_status == Status.FRIEXEMPLAR:
        return
    rows = MemberPreviousAddress.select().where(MemberPreviousAddress.member == person_id)
    lock_addresses([person.email, *(r.address for r in rows)])
    now = _utcnow()
    for address in [person.email, *(r.address for r in rows.where(MemberPreviousAddress.login_until > now))]:
        reserve_login_address(address, person_id)


def login_address_taken(address, person_id):
    """Whether another person holds the address now. A write must still reserve it under the address lock."""
    return (
        DB_PROXY.execute_sql(
            f"SELECT 1 FROM ({_ADDRESSES}) a WHERE address = %(address)s AND member_id <> %(person)s LIMIT 1",
            {"now": _utcnow(), "address": address.strip().lower(), "person": person_id},
        ).fetchone()
        is not None
    )


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
    if login_address_taken(address, person_id):
        raise AddressTaken(AddressTaken.title)


def reserve_on_leaving_friexemplar(membership_id):
    """Before leaving friexemplar, check for competing holders both inside and outside this membership."""
    rows = DB_PROXY.execute_sql(
        f"SELECT member_id, address FROM ({_PERSON_ADDRESSES}) a WHERE membership_id = %(membership)s "
        'ORDER BY address COLLATE "C"',
        {"membership": membership_id, "now": _utcnow()},
    )
    previous = None
    for person_id, address in rows:
        if address == previous:
            raise AddressTaken(AddressTaken.title)
        reserve_login_address(address, person_id)
        previous = address


@recipient_kind("login_code")
def _code_recipient(row_id):
    """
    The address the code goes to, read when it goes: none once the code is used, voided or too old, or the person's
    account has changed. Only a new address (ny_adress) has one yet; the login code's comes with the login page.
    """
    row = LoginCode.get_or_none(LoginCode.id == row_id)
    if row is None or row.used_at or row.created_at <= _utcnow() - VALID_FOR or row.purpose != "ny_adress":
        return None
    person = row.member
    if person.user_id != row.user_id or person.membership.membership_status == Status.FRIEXEMPLAR:
        return None
    return Recipient(row.new_address, f"{person.first_name} {person.last_name}")


@mail_kind("konto.kod", priority=0, category="T")
def _code_mail(params):
    row = LoginCode.get_or_none(LoginCode.id == params["code_id"])
    return {"code": shown(code(row))} if row else None


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
