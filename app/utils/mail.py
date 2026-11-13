"""
Outgoing mail queue (mejlkön), see docs/mejl.md.

A feature queues a mail with `enqueue_mail` in the transaction of the write it belongs to, so a rollback leaves
no mail. The scheduler leader's `send_pending` sends committed rows. A row holds the template name, ids and a
reference to the recipient, never an address, a finished text or a valid link: the address is looked up and the
text rendered when the mail goes out.
"""

import base64
import hashlib
import hmac
import logging
import os
import re
import smtplib
import ssl
import uuid
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime, formataddr
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, StrictUndefined

import utils.settings as settings
from utils.database import DB_PROXY, MailAttempt, MailMessage, MailSender, Member, MemberApplication, User

logger = logging.getLogger("herdbook.mail")

MAX_PER_RUN = 30
SMTP_TIMEOUT = 60  # seconds, per SMTP step
RECLAIM_AFTER = timedelta(minutes=10)
PAUSE_AFTER_SYSTEMIC = timedelta(minutes=5)
# After the 1st..6th counted failure; the 7th fails the mail.
RETRY_DELAYS = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=6),
    timedelta(hours=12),
)
RETENTION = timedelta(days=396)

MailKind = namedtuple("MailKind", "priority category build")
Recipient = namedtuple("Recipient", "address label")

# kind -> MailKind; build(params) returns the template variables (plus an optional "attachments" list of
# (filename, mime type, bytes)), or None when the mail is no longer relevant, which cancels it.
MAIL_KINDS = {}
# recipient_kind -> resolve(recipient_id) returning a Recipient, or None.
RECIPIENT_KINDS = {}


def mail_kind(name, *, priority, category):
    """Registers the decorated `build(params)` as the builder of mail kind `name` (template `email/<name>.txt`)."""

    def register(build):
        MAIL_KINDS[name] = MailKind(priority, category, build)
        return build

    return register


def recipient_kind(name):
    """Registers the decorated `resolve(recipient_id)` for `recipient_kind = name`."""

    def register(resolve):
        RECIPIENT_KINDS[name] = resolve
        return resolve

    return register


def _utcnow():
    return datetime.now(timezone.utc)


_PARAM_KEY = re.compile(r"[a-z][a-z0-9_]*")


def enqueue_mail(
    kind,
    recipient_kind,
    recipient_id,
    params=None,
    *,
    ref=None,
    herd=None,
    genebank=None,
    dedupe_key=None,
    not_before=None,
    created_by=None,
):
    """
    Queues one mail in the caller's transaction and returns its id, or None when a row with `dedupe_key`
    already exists. `params` holds only ids and flags; `ref` is (ref_type, ref_id), the case the mail is about.
    """
    spec = MAIL_KINDS.get(kind)
    if spec is None:
        raise ValueError(f"unknown mail kind {kind!r}")
    params = params or {}
    for key, value in params.items():
        if not (isinstance(key, str) and _PARAM_KEY.fullmatch(key)) or not (value is None or isinstance(value, int)):
            raise ValueError(f"mail params hold only ids and flags, not {key!r}")
    ref_type, ref_id = ref or (None, None)
    # DO NOTHING rather than a unique violation, which would abort the caller's transaction.
    return (
        MailMessage.insert(
            kind=kind,
            params=params,
            recipient_kind=recipient_kind,
            recipient_id=recipient_id,
            ref_type=ref_type,
            ref_id=ref_id,
            herd=herd,
            genebank=genebank,
            priority=spec.priority,
            category=spec.category,
            dedupe_key=dedupe_key,
            next_attempt_at=not_before or _utcnow(),
            created_by=created_by,
        )
        .on_conflict_ignore()
        .execute()
    )


# --- Secrets: link tokens, Message-ID, address hash ---


def _mac(message):
    secret = settings.mail.link_secret
    if not secret:
        raise RuntimeError("LINK_SECRET is not set")
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256)


def _link_mac(purpose, row_id):
    return base64.urlsafe_b64encode(_mac(f"{purpose}:{row_id}").digest()[:16]).rstrip(b"=").decode()


def link_token(purpose, row_id):
    """`<row id>.<mac>`, mac = base64url(HMAC-SHA256(LINK_SECRET, "<purpose>:<row id>")) cut to 128 bits."""
    return f"{row_id}.{_link_mac(purpose, row_id)}"


_LINK_TOKEN = re.compile(r"([1-9][0-9]{0,18})\.([A-Za-z0-9_-]{22})")


def verify_link(purpose, token):
    """
    The row id a link token was made for, or None when it is malformed, forged, or made with another
    LINK_SECRET (changing the secret invalidates every link). Expiry and revocation are the caller's check.
    """
    match = _LINK_TOKEN.fullmatch(token) if isinstance(token, str) else None
    if match is None or not settings.mail.link_secret:
        return None
    row_id = int(match.group(1))
    return row_id if hmac.compare_digest(_link_mac(purpose, row_id), match.group(2)) else None


def _hostname():
    return urlparse(settings.service.host).hostname or "localhost"


def message_id(row_id):
    """Unguessable, the same on every attempt, and different per environment (the hostname)."""
    return f"<mail-{row_id}.{_mac(f'mail:{row_id}').hexdigest()[:16]}@{_hostname()}>"


def address_hash(address):
    """HMAC, not a plain hash, which could be looked up against known addresses."""
    return _mac(_normalize(address) or "").hexdigest()


_ADDRESS = re.compile(r"[^@\s<>,;\"']+@[^@\s<>,;\"']+")
_ADDRESS_LIKE = re.compile(r"<?[^\s<>@]*@[^\s<>]*>?")


def _normalize(raw):
    """The one form of an address used for sending, hashing and the allowlist, or None if it is not one."""
    address = (raw or "").strip().lower()
    return address if _ADDRESS.fullmatch(address) else None


def _scrub(text):
    """SMTP errors often quote the recipient: nothing that looks like an address is stored."""
    return _ADDRESS_LIKE.sub("<adress>", text)[:1000] if text else text


# --- Templates ---

# Mails are text/plain and nothing in them is parsed as markup, so autoescaping would only garble names.
_TEMPLATES = Environment(  # nosemgrep
    loader=FileSystemLoader(str(Path(__file__).resolve().parent.parent / "templates" / "email")),
    autoescape=False,
    undefined=StrictUndefined,
)


def render(kind, variables):
    """(subject, body) of a kind's template with the shared footer. The subject is one line: no header injection."""
    template = _TEMPLATES.get_template(f"{kind}.txt")
    context = template.new_context({"base_url": settings.service.host.rstrip("/"), **variables})
    subject = " ".join("".join(template.blocks["subject"](context)).split())
    body = "".join(template.blocks["body"](context)).strip()
    footer = _TEMPLATES.get_template("_fot.txt").render()  # nosemgrep
    return subject, f"{body}\n\n{footer}"


def _message(row, address, subject, body, attachments):
    msg = EmailMessage()
    msg["From"] = formataddr(("Stamboken", settings.mail.sender))
    msg["Reply-To"] = settings.mail.sender
    msg["To"] = address
    msg["Subject"] = ("[Demo] " if settings.mail.mode == "allowlist" else "") + subject
    msg["Message-ID"] = message_id(row.id)
    msg["Date"] = format_datetime(_utcnow())
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(body)
    for filename, mime, data in attachments:
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg


# --- Sender ---


class _Systemic(Exception):
    """The relay itself refuses (connection, TLS, 421, relay denied): not the mail's fault."""

    def __init__(self, smtp_code, detail):
        super().__init__(detail)
        self.smtp_code = smtp_code
        self.detail = detail


def _connect():
    conn = smtplib.SMTP(
        settings.mail.smtp_host, settings.mail.smtp_port, local_hostname=_hostname(), timeout=SMTP_TIMEOUT
    )
    try:
        conn.ehlo()
        if not conn.has_extn("starttls"):
            raise smtplib.SMTPNotSupportedError("the relay does not offer STARTTLS")
        conn.starttls(context=ssl.create_default_context())
        conn.ehlo()
        return conn
    except BaseException:
        conn.close()
        raise


class _Relay:
    """The run's one SMTP connection, opened when the first mail actually goes out."""

    def __init__(self):
        self.conn = None

    def send(self, msg, address):
        if self.conn is None:
            try:
                self.conn = _connect()
            except Exception as exc:
                code = getattr(exc, "smtp_code", None)
                raise _Systemic(str(code) if code else None, _describe(exc)) from exc
        self.conn.send_message(msg, from_addr=settings.mail.sender, to_addrs=[address])

    def close(self):
        conn, self.conn = self.conn, None
        if conn is not None:
            try:
                conn.quit()
            except Exception:  # pylint: disable=broad-except
                conn.close()


def _describe(exc):
    return f"{type(exc).__name__}: {exc}"


_ENHANCED = re.compile(r"\b([245]\.\d{1,3}\.\d{1,3})\b")


def _classify(code, text):
    """(result, smtp_code) of an SMTP error reply. A 5xx outside the spec's classes counts as permanent."""
    enhanced = _ENHANCED.search(text)
    smtp_code = enhanced.group(1) if enhanced else str(code)
    if code == 421 or smtp_code in ("5.7.0", "5.7.1"):
        return "systemic", smtp_code
    if 400 <= code < 500:
        return "temporary", smtp_code
    return "permanent", smtp_code


def _heartbeat(now):
    """Every run stamps last_run_at, also when paused or idle; returns paused_until."""
    cursor = DB_PROXY.execute_sql(
        "INSERT INTO mail_sender (id, last_run_at) VALUES (1, %s) "
        "ON CONFLICT (id) DO UPDATE SET last_run_at = EXCLUDED.last_run_at RETURNING paused_until",
        (now,),
    )
    return cursor.fetchone()[0]


def _claim(now):
    """Takes the next due row for this run under a fresh claim_token; committed before anything is sent."""
    cursor = DB_PROXY.execute_sql(
        """
        UPDATE mail_message SET status = 'sending', claimed_at = %s, claim_token = %s::uuid
        WHERE id = (
            SELECT id FROM mail_message WHERE status = 'queued' AND next_attempt_at <= %s
            ORDER BY priority, id LIMIT 1 FOR UPDATE SKIP LOCKED
        )
        RETURNING id
        """,
        (now, str(uuid.uuid4()), now),
    )
    found = cursor.fetchone()
    return MailMessage.get_by_id(found[0]) if found else None


def _finish(row, now, attempt=None, **fields):
    """Writes a claimed row's outcome, but only while the claim is still ours. Returns True (the run goes on)."""
    if fields.get("last_error"):
        fields["last_error"] = _scrub(fields["last_error"])
    with DB_PROXY.atomic():
        won = (
            MailMessage.update(claimed_at=None, claim_token=None, **fields)
            .where((MailMessage.id == row.id) & (MailMessage.claim_token == row.claim_token))
            .execute()
        )
        if won and attempt:
            MailAttempt.create(message=row.id, at=now, source="smtp", **attempt)
    if not won:
        logger.warning("Mail %s was reclaimed by another sender; this result is dropped", row.id)
    return True


def _failed(row, now, result, smtp_code, detail, address=None):
    """A counted failure: retried on the ladder while temporary, otherwise failed."""
    detail = _scrub(detail)
    attempts = row.attempts + 1
    if result == "temporary" and attempts <= len(RETRY_DELAYS):
        fields = {"status": "queued", "next_attempt_at": now + RETRY_DELAYS[attempts - 1]}
    else:
        fields = {"status": "failed"}
    if address and (smtp_code or "")[:4] in ("5.1.", "5.2.", "5.3."):
        fields["address_hash"] = address_hash(address)  # the recipient's mailbox refused: the bounce flag
    attempt = {"result": result, "smtp_code": smtp_code, "detail": detail}
    return _finish(row, now, attempt, attempts=attempts, last_error=detail, **fields)


def _systemic(row, now, smtp_code, detail):
    """Not counted on the mail: the row goes back as it was, the run stops and the sender pauses."""
    detail = _scrub(detail)
    attempt = {"result": "systemic", "smtp_code": smtp_code, "detail": detail}
    _finish(row, now, attempt, status="queued", last_error=detail)
    MailSender.update(paused_until=now + PAUSE_AFTER_SYSTEMIC).where(MailSender.id == 1).execute()
    return False


def _allowed(address):
    return any(
        address == entry or (entry.startswith("@") and address.endswith(entry)) for entry in settings.mail.allowlist
    )


def _send_one(row, relay, now):
    """Builds, sends and records one claimed row. False stops the run."""
    kind = MAIL_KINDS.get(row.kind)
    resolve = RECIPIENT_KINDS.get(row.recipient_kind)
    if kind is None:
        return _finish(row, now, status="cancelled", last_error=f"okänd mejltyp: {row.kind}")
    if resolve is None:
        return _finish(row, now, status="cancelled", last_error=f"okänd mottagartyp: {row.recipient_kind}")
    mode = settings.mail.mode
    try:
        recipient = resolve(row.recipient_id)
        address = _normalize(recipient.address) if recipient else None
        if address is None:
            return _finish(row, now, status="cancelled", last_error="mottagaren saknar e-post")
        variables = kind.build(row.params)
        if variables is None:
            return _finish(row, now, status="cancelled", last_error="mejlet är inte längre aktuellt")
        attachments = variables.pop("attachments", [])
        subject, body = render(row.kind, variables)
        msg = None if mode == "log" else _message(row, address, subject, body, attachments)
    except Exception as exc:  # pylint: disable=broad-except  # a bug or a lost database: retried like a 4xx
        logger.exception("Building mail %s failed", row.id)
        return _failed(row, now, "temporary", None, f"bygget misslyckades: {_describe(exc)}")

    if mode == "log":
        logger.info("Mail %s (%s) to %s %s logged, not sent", row.id, row.kind, row.recipient_kind, row.recipient_id)
        if os.environ.get("FLASK_ENV") != "production":
            logger.info("Mail %s:\n%s\n\n%s", row.id, subject, body)
        return _finish(row, now, status="logged")
    if mode == "allowlist" and not _allowed(address):
        return _finish(row, now, status="blocked", last_error="spärrat: adressen finns inte i MAIL_ALLOWLIST")

    try:
        relay.send(msg, address)
    except _Systemic as exc:
        return _systemic(row, now, exc.smtp_code, exc.detail)
    except smtplib.SMTPRecipientsRefused as exc:
        code, text = next(iter(exc.recipients.values()))
        return _smtp_error(row, now, code, text, address)
    except smtplib.SMTPResponseException as exc:
        return _smtp_error(row, now, exc.smtp_code, exc.smtp_error, address)
    except (smtplib.SMTPException, OSError) as exc:  # disconnect or timeout on this mail
        relay.close()  # the next mail reconnects; if that fails, it is systemic
        return _failed(row, now, "temporary", None, _describe(exc))
    return _finish(
        row,
        now,
        {"result": "sent", "smtp_code": "250"},
        status="sent",
        sent_at=now,
        attempts=row.attempts + 1,
        address_hash=address_hash(address),
        last_error=None,
    )


def _smtp_error(row, now, code, text, address):
    text = text.decode(errors="replace") if isinstance(text, bytes) else str(text)
    result, smtp_code = _classify(code, text)
    detail = f"{code} {text}"
    if result == "systemic":
        return _systemic(row, now, smtp_code, detail)
    return _failed(row, now, result, smtp_code, detail, address)


def send_pending(now=None):
    """
    One run of the scheduler's mail_send job: up to MAX_PER_RUN due rows, one claimed at a time, over one
    SMTP connection. Returns the number of rows taken.
    """
    now = now or _utcnow()
    paused_until = _heartbeat(now)
    if paused_until is not None and paused_until > now:
        return 0
    MailMessage.update(status="queued", claimed_at=None, claim_token=None).where(
        (MailMessage.status == "sending") & (MailMessage.claimed_at < now - RECLAIM_AFTER)
    ).execute()
    relay = _Relay()
    taken = 0
    try:
        while taken < MAX_PER_RUN:
            row = _claim(now)
            if row is None:
                break
            taken += 1
            if not _send_one(row, relay, now):
                break
    finally:
        relay.close()
    return taken


# --- Bounces, erasure and retention ---

_MESSAGE_ID = re.compile(r"\s*<mail-(\d+)\.([0-9a-f]{16})@([^<>\s]+)>\s*")


def record_bounce(message_id_header, diagnostic):
    """
    Marks the row behind a delivery report's Message-ID as bounced. Returns False when the id is not one of
    this environment's mails, so the caller can hand the report to a human instead.
    """
    match = _MESSAGE_ID.fullmatch(message_id_header or "")
    if match is None or match.group(3).lower() != _hostname().lower():
        return False
    row_id = int(match.group(1))
    if not hmac.compare_digest(match.group(2), _mac(f"mail:{row_id}").hexdigest()[:16]):
        return False
    detail = _scrub(diagnostic)
    enhanced = _ENHANCED.search(diagnostic or "")
    with DB_PROXY.atomic():
        if not MailMessage.update(status="bounced", last_error=detail).where(MailMessage.id == row_id).execute():
            return False
        MailAttempt.create(
            message=row_id,
            at=_utcnow(),
            source="bounce",
            result="bounce",
            smtp_code=enhanced.group(1) if enhanced else None,
            detail=detail,
        )
    return True


def forget_recipient(kind, recipient_id):
    """Called by the jobs that delete a recipient source: no trace of the address stays in the queue."""
    return (
        MailMessage.update(address_hash=None)
        .where((MailMessage.recipient_kind == kind) & (MailMessage.recipient_id == recipient_id))
        .execute()
    )


def purge_old_mail(now):
    """Deletes rows older than 13 months; their attempts follow (ON DELETE CASCADE)."""
    return MailMessage.delete().where(MailMessage.created_at < now - RETENTION).execute()


# --- Recipients ---


@recipient_kind("member")
def _member(member_id):
    m = Member.get_or_none(Member.id == member_id)
    return Recipient(m.email, f"{m.first_name} {m.last_name}") if m else None


@recipient_kind("user")
def _user(user_id):
    u = User.get_or_none(User.id == user_id)
    # Never the username: register_user's first argument is the e-mail address.
    return Recipient(u.email, u.fullname or f"Konto {u.id}") if u else None


@recipient_kind("application")
def _application(application_id):
    a = MemberApplication.get_or_none(MemberApplication.id == application_id)
    return Recipient(a.email, f"{a.first_name} {a.last_name}") if a else None


# --- Kinds ---


@mail_kind("ansokan.mottagen", priority=1, category="T")
def _application_received(params):
    found = MemberApplication.select().where(MemberApplication.id == params["application_id"]).exists()
    return {} if found else None
