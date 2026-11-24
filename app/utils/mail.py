"""
Outgoing mail queue (mejlkön), see docs/mejl.md.

A feature queues a mail with `enqueue_mail` in the transaction of the write it belongs to, so a rollback leaves
no mail. The scheduler leader's `send_pending` sends committed rows. A row holds the template name, ids and a
reference to the recipient, never an address, a finished text or a valid link: the address is looked up and the
text rendered when the mail goes out.
"""

import base64
import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
import smtplib
import socket
import ssl
import threading
import uuid
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime, formataddr
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from peewee import fn

import utils.settings as settings
import utils.tyck_till as tyck_till
from utils.database import (
    DB_PROXY,
    BuyerContact,
    MailAttempt,
    MailMessage,
    MailSender,
    Member,
    MemberApplication,
    MemberPreviousAddress,
    User,
)
from utils.log_masking import mask_tokens

logger = logging.getLogger("herdbook.mail")

MAX_PER_RUN = 30
SMTP_TIMEOUT = 60  # seconds, per SMTP step
# Seconds for one mail's whole SMTP conversation, connecting included. The claim is renewed just before it, so
# a sender never still talks to the relay when another may reclaim the row.
SEND_DEADLINE = 120
RECLAIM_AFTER = timedelta(minutes=10)
PAUSE_AFTER_SYSTEMIC = timedelta(minutes=5)
REFUSALS_BEFORE_PAUSE = 3  # permanent failures in a row in one run: the relay refuses everything
STALLED_AFTER = timedelta(minutes=5)  # no sender run for this long: the scheduler is dead
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
NO_ADDRESS = "mottagaren saknar e-post"

MailKind = namedtuple("MailKind", "priority category build")
Recipient = namedtuple("Recipient", "address label")

# kind -> MailKind; build(params) returns the template variables (plus an optional "attachments" list of
# (filename, mime type, bytes)), or None when the mail is no longer relevant, which cancels it, or raises Later.
MAIL_KINDS = {}
# recipient_kind -> resolve(recipient_id) returning a Recipient, or None.
RECIPIENT_KINDS = {}


def mail_kind(name, *, priority, category):
    """Registers the decorated `build(params)` as the builder of mail kind `name` (template `email/<name>.txt`)."""

    def register(build):
        MAIL_KINDS[name] = MailKind(priority, category, build)
        return build

    return register


class Later(Exception):
    """A builder's answer: the mail is still wanted but must wait (a limit). It is queued again, no attempt counted."""

    def __init__(self, until, why):
        super().__init__(why)
        self.until = until
        self.why = why


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
    """One key for four uses, so every input starts with its own prefix: `link:`, `msgid:`, `addr:` or `code:`."""
    secret = settings.mail.link_secret
    if not secret:
        raise RuntimeError("LINK_SECRET is not set")
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256)


def _link_mac(purpose, row_id):
    # The hostname binds a link to its environment: the demo is a copy of production with the same row ids.
    message = f"link:{_hostname()}:{purpose}:{row_id}"
    return base64.urlsafe_b64encode(_mac(message).digest()[:16]).rstrip(b"=").decode()


def link_token(purpose, row_id):
    """`<row id>.<mac>`, mac = base64url(HMAC-SHA256(LINK_SECRET, "link:<host>:<purpose>:<row id>")) cut to 128 bits."""
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


def one_time_code(row_id, nonce):
    """A login_code row's eight digits: HMAC-SHA256(LINK_SECRET, "code:<host>:<row id>:<nonce>") mod 10^8, as text."""
    digest = _mac(f"code:{_hostname()}:{row_id}:{nonce}").digest()
    return f"{int.from_bytes(digest[:8], 'big') % 10**8:08d}"


def message_id(row_id):
    """Unguessable, the same on every attempt, and different per environment (the hostname)."""
    return f"<mail-{row_id}.{_mac(f'msgid:{row_id}').hexdigest()[:16]}@{_hostname()}>"


def address_hash(address):
    """HMAC, not a plain hash, which could be looked up against known addresses."""
    return _mac(f"addr:{_normalize(address) or ''}").hexdigest()


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


def _message(row, address, subject, body, attachments, reply_to=None):
    msg = EmailMessage()
    msg["From"] = formataddr(("Stamboken", settings.mail.sender))
    msg["Reply-To"] = reply_to or settings.mail.sender
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


def _connect(conn):
    conn.connect(settings.mail.smtp_host, settings.mail.smtp_port)
    conn.ehlo()
    if not conn.has_extn("starttls"):
        raise smtplib.SMTPNotSupportedError("the relay does not offer STARTTLS")
    conn.starttls(context=ssl.create_default_context())
    conn.ehlo()


class _ClaimLost(Exception):
    """The row is no longer this sender's: reclaimed by another, or its recipient erased. Nothing was sent."""


class _Relay:
    """The run's one SMTP connection, opened when the first mail actually goes out."""

    def __init__(self):
        self.conn = None
        self.dropped = False  # the previous mail lost the connection
        self.timed_out = False
        self.refused = 0  # permanent failures in a row

    def send(self, msg, address, still_ours):
        """
        One mail's whole SMTP conversation, connecting included, cut off at SEND_DEADLINE. Per-step socket
        timeouts alone do not bound it: a relay can drip its replies a byte at a time. `still_ours` is asked
        once the connection is up, as late as it gets: connecting can take seconds, and a recipient erased
        meanwhile gets no mail.
        """
        self.timed_out = False
        timer = threading.Timer(SEND_DEADLINE, self._cut)
        timer.start()
        try:
            self._send(msg, address, still_ours)
        finally:
            timer.cancel()
            timer.join()
            if self.timed_out:
                self.close()  # its socket is shut down, also if the reply came just in time

    def _send(self, msg, address, still_ours):
        if self.conn is None:
            self.conn = smtplib.SMTP(local_hostname=_hostname(), timeout=SMTP_TIMEOUT)  # set first: _cut reaches it
            try:
                _connect(self.conn)
            except Exception as exc:
                conn, self.conn = self.conn, None
                conn.close()
                code = getattr(exc, "smtp_code", None)
                raise _Systemic(str(code) if code else None, _describe(self._why(exc))) from exc
        if not still_ours():
            raise _ClaimLost
        try:
            self.conn.send_message(msg, from_addr=settings.mail.sender, to_addrs=[address])
        except Exception as exc:
            if not _lost(exc):
                self.dropped = False  # the relay answered
                raise
            self.close()  # the next mail reconnects; if that fails, it is systemic
            if self.dropped:  # twice in a row: the relay drops us, not this mail
                raise _Systemic(None, _describe(self._why(exc))) from exc
            self.dropped = True
            if self.timed_out:
                raise self._why(exc) from exc
            raise
        self.dropped = False

    def _cut(self):
        """Timer thread: shutting the socket down makes the blocked conversation fail at once."""
        self.timed_out = True
        sock = getattr(self.conn, "sock", None)
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)

    def _why(self, exc):
        """A cut by the deadline is a timeout, not the disconnect it looks like."""
        return TimeoutError(f"no reply within {SEND_DEADLINE} s") if self.timed_out else exc

    def close(self):
        conn, self.conn = self.conn, None
        if conn is not None:
            try:
                conn.quit()
            except Exception:  # pylint: disable=broad-except
                conn.close()


def _describe(exc):
    return f"{type(exc).__name__}: {exc}"


def _lost(exc):
    """The connection broke or timed out, as opposed to the relay answering (an SMTPException is an OSError too)."""
    return isinstance(exc, smtplib.SMTPServerDisconnected) or (
        isinstance(exc, OSError) and not isinstance(exc, smtplib.SMTPException)
    )


_ENHANCED = re.compile(r"\b([245]\.\d{1,3}\.\d{1,3})\b")


def _classify(code, text):
    """
    (result, smtp_code) of an SMTP error reply. A refusal at RCPT or DATA is about this recipient or this
    message, whatever its code (5.7.x policy too), unless the relay is closing the connection (421).
    """
    enhanced = _ENHANCED.search(text)
    smtp_code = enhanced.group(1) if enhanced else str(code)
    if code == 421:
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


def _renew(row):
    """
    Restarts the claim's clock just before the mail goes, so the row cannot be reclaimed until long after
    SEND_DEADLINE. False when another sender has taken the row since (this one was slow) or the recipient has
    been erased (forget_recipient): it must not send.
    """
    renewed = MailMessage.update(claimed_at=_utcnow()).where(
        (MailMessage.id == row.id) & (MailMessage.claim_token == row.claim_token)
    )
    return renewed.execute() == 1


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


def _strikes(row, now):
    """
    How many of this row's systemic outcomes, since its last counted one (a retry starts over), were followed
    by other mail going through before the next: a refusal that keeps hitting only this mail is its own.
    """
    cursor = DB_PROXY.execute_sql(
        """
        SELECT count(*) FROM (
            SELECT at, lead(at, 1, %s) OVER (ORDER BY at, id) AS next_at FROM mail_attempt
            WHERE message_id = %s AND result = 'systemic' AND at > coalesce(
                (SELECT max(at) FROM mail_attempt WHERE message_id = %s AND result <> 'systemic'), '-infinity')
        ) own
        WHERE EXISTS (SELECT 1 FROM mail_attempt o WHERE o.result = 'sent' AND o.at > own.at AND o.at < own.next_at)
        """,
        (now, row.id, row.id),
    )
    return cursor.fetchone()[0]


def _systemic(row, now, smtp_code, detail):
    """
    Not counted on the mail: the run stops, the sender pauses, and the row waits until after the pause so the
    mail behind it goes first. The third time while other mail went through in between, the row fails.
    """
    detail = _scrub(detail)
    if _strikes(row, now) >= 2:
        _failed(row, now, "permanent", smtp_code, detail)
        return False  # the connection may not survive what the relay said; the next run reconnects
    paused_until = now + PAUSE_AFTER_SYSTEMIC
    attempt = {"result": "systemic", "smtp_code": smtp_code, "detail": detail}
    _finish(row, now, attempt, status="queued", next_attempt_at=paused_until + RETRY_DELAYS[0], last_error=detail)
    MailSender.update(paused_until=paused_until).where(MailSender.id == 1).execute()
    return False


def _refused_in_a_row(relay, now, result):
    """
    A relay that refuses every recipient (quota, policy, our IP) answers each mail with a 5xx at RCPT or DATA.
    Three permanent failures in a row stop the run and pause the sender like a systemic failure; the three
    rows stay failed. Returns False when the run stops.
    """
    relay.refused = relay.refused + 1 if result == "permanent" else 0
    if relay.refused < REFUSALS_BEFORE_PAUSE:
        return True
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
            return _finish(row, now, status="cancelled", last_error=NO_ADDRESS)
        variables = kind.build(row.params)
        if variables is None:
            return _finish(row, now, status="cancelled", last_error="mejlet är inte längre aktuellt")
        attachments = variables.pop("attachments", [])
        reply_to = variables.pop("reply_to", None)
        subject, body = render(row.kind, variables)
        msg = None if mode == "log" else _message(row, address, subject, body, attachments, reply_to)
    except Later as later:
        return _finish(row, now, status="queued", next_attempt_at=later.until, last_error=later.why)
    except Exception as exc:  # pylint: disable=broad-except  # a bug or a lost database: retried like a 4xx
        detail = f"bygget misslyckades: {_describe(exc)}"
        logger.error("Building mail %s failed: %s", row.id, _scrub(detail))  # no traceback: it may hold the address
        return _failed(row, now, "temporary", None, detail)

    if mode == "log":
        logger.info("Mail %s (%s) to %s %s logged, not sent", row.id, row.kind, row.recipient_kind, row.recipient_id)
        if os.environ.get("FLASK_ENV") != "production" and row.kind != "tyck_till.inskick":  # free text and address
            logger.info("Mail %s:\n%s\n\n%s", row.id, mask_tokens(subject), mask_tokens(body))
        return _finish(row, now, status="logged")
    if mode == "allowlist" and not _allowed(address):
        return _finish(row, now, status="blocked", last_error="spärrat: adressen finns inte i MAIL_ALLOWLIST")
    try:
        relay.send(msg, address, lambda: _renew(row))
    except _ClaimLost:
        logger.warning("Mail %s was reclaimed by another sender or lost its recipient; it is not sent", row.id)
        return True
    except _Systemic as exc:
        return _systemic(row, now, exc.smtp_code, exc.detail)
    except smtplib.SMTPSenderRefused as exc:  # MAIL FROM: our sender or IP refused, every mail would fail alike...
        # ...except 552, the relay's size limit checked against SIZE=, which is this mail's own failure
        return _smtp_error(row, now, relay, exc.smtp_code, exc.smtp_error, None, systemic=exc.smtp_code != 552)
    except smtplib.SMTPRecipientsRefused as exc:
        code, text = next(iter(exc.recipients.values()))
        return _smtp_error(row, now, relay, code, text, address)
    except smtplib.SMTPResponseException as exc:
        return _smtp_error(row, now, relay, exc.smtp_code, exc.smtp_error, address)
    except Exception as exc:  # pylint: disable=broad-except  # disconnect, timeout or anything else on this mail
        relay.close()  # the next mail reconnects; if that fails, it is systemic
        relay.refused = 0
        return _failed(row, now, "temporary", None, _describe(exc))
    relay.refused = 0
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


def _smtp_error(row, now, relay, code, text, address, systemic=False):
    text = text.decode(errors="replace") if isinstance(text, bytes) else str(text)
    result, smtp_code = _classify(code, text)
    detail = f"{code} {text}"
    if systemic or result == "systemic":
        return _systemic(row, now, smtp_code, detail)
    _failed(row, now, result, smtp_code, detail, address)
    return _refused_in_a_row(relay, now, result)


def send_pending(now=None):
    """
    One run of the scheduler's mail_send job: up to MAX_PER_RUN due rows, one claimed at a time, over one
    SMTP connection. Returns the number of rows taken.
    """
    settings.refuse_unsafe_mail_settings()  # not only at import: any other mode would fall through to a real send
    fixed = now
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
            # A fresh time per row: a slow run claiming with its start time would look reclaimable at once.
            tick = fixed or _utcnow()
            row = _claim(tick)
            if row is None:
                break
            taken += 1
            if not _send_one(row, relay, tick):
                break
    finally:
        relay.close()
    return taken


# --- Bounces, erasure and retention ---

_MESSAGE_ID = re.compile(r"\s*<mail-(\d+)\.([0-9a-f]{16})@([^<>\s]+)>\s*")


def record_bounce(message_id_header, diagnostic):
    """
    Marks the row behind a delivery report's Message-ID as bounced. Returns False when the id is not one of
    this environment's mails, or the row is not `sent` (a bounce never revives or overwrites another state),
    so the caller can hand the report to a human instead.
    """
    match = _MESSAGE_ID.fullmatch(message_id_header or "")
    if match is None or match.group(3).lower() != _hostname().lower():
        return False
    row_id = int(match.group(1))
    if not hmac.compare_digest(match.group(2), _mac(f"msgid:{row_id}").hexdigest()[:16]):
        return False
    detail = _scrub(diagnostic)
    enhanced = _ENHANCED.search(diagnostic or "")
    with DB_PROXY.atomic():
        bounced = MailMessage.update(status="bounced", last_error=detail).where(
            (MailMessage.id == row_id) & (MailMessage.status == "sent")
        )
        if not bounced.execute():
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
    """
    Called by the jobs that delete a recipient source: no trace of the address stays in the queue, and mail not
    yet sent is cancelled. One being built or sent right now loses its claim, so the sender does not send it
    (_renew) and does not write the address hash back (_finish). Returns the number of rows.
    """
    rows = (MailMessage.recipient_kind == kind) & (MailMessage.recipient_id == recipient_id)
    MailMessage.update(status="cancelled", claim_token=None, claimed_at=None, last_error="mottagaren är raderad").where(
        rows & MailMessage.status.in_(("queued", "sending"))
    ).execute()
    # a dedupe_key may hold the address's HMAC
    return MailMessage.update(address_hash=None, dedupe_key=None).where(rows).execute()


def purge_old_mail(now):
    """Deletes rows older than 13 months; their attempts follow (ON DELETE CASCADE)."""
    return MailMessage.delete().where(MailMessage.created_at < now - RETENTION).execute()


# --- Status views ---


def recipient_label(row):
    """The recipient as a name, looked up now; never the address, also when someone typed one as their name."""
    resolve = RECIPIENT_KINDS.get(row.recipient_kind)
    recipient = resolve(row.recipient_id) if resolve else None
    return _scrub(recipient.label) if recipient else None


def message_view(row):
    return {
        "id": row.id,
        "kind": row.kind,
        "category": row.category,
        "priority": row.priority,
        "status": row.status,
        "recipient_kind": row.recipient_kind,
        "recipient": recipient_label(row),
        "ref_type": row.ref_type,
        "ref_id": row.ref_id,
        "herd_id": row.herd_id,
        "genebank_id": row.genebank_id,
        "attempts": row.attempts,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat(),
        "next_attempt_at": row.next_attempt_at.isoformat(),
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
    }


def sender_alarms(now=None):
    """The status view's alarms: the relay refusing, the queue stalled, code login closed, and the last mail out."""
    now = now or _utcnow()
    sender = MailSender.get_or_none(MailSender.id == 1)
    last_smtp = (
        MailAttempt.select(MailAttempt.result)
        .where(MailAttempt.source == "smtp")
        .order_by(MailAttempt.at.desc(), MailAttempt.id.desc())
        .first()
    )
    last_run_at = sender.last_run_at if sender else None
    alarms = []
    paused = sender is not None and sender.paused_until is not None and sender.paused_until > now
    if paused or (last_smtp is not None and last_smtp.result == "systemic"):
        alarms.append({"code": "relay_refusing", "message": "Reläet tar inte emot e-post från servern"})
    if (
        settings.mail.mode == "log"
        and os.environ.get("FLASK_ENV") == "production"
        and not settings.service.demo_instance
    ):
        alarms.append({"code": "log_mode", "message": "Utskicksläget är log: inget mejl skickas på riktigt"})
    if last_run_at is None or last_run_at < now - STALLED_AFTER:
        alarms.append({"code": "queue_stalled", "message": "Kön står still"})
    from utils.login_code import alarms as code_alarms  # pylint: disable=import-outside-toplevel  # imports this

    alarms += code_alarms(now)
    last_sent = MailMessage.select(MailMessage.sent_at).where(MailMessage.sent_at.is_null(False))
    last_sent = last_sent.order_by(MailMessage.sent_at.desc()).first()
    return {
        "alarms": alarms,
        "last_run_at": last_run_at.isoformat() if last_run_at else None,
        "paused_until": sender.paused_until.isoformat() if sender and sender.paused_until else None,
        "last_sent_at": last_sent.sent_at.isoformat() if last_sent else None,
    }


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


@recipient_kind("buyer_contact")
def _buyer_contact(contact_id):
    c = BuyerContact.get_or_none(BuyerContact.id == contact_id)
    # Never the name: only a genebank's managers and helpers see a buyer, and each read is logged (ADR-0016).
    return Recipient(c.email, f"Köpare {c.id}") if c else None


@recipient_kind("member_previous_address")
def _previous_address(row_id):
    """An address a person had (utils.matrikel.set_member_email); gone once the row is purged or the person erased."""
    r = MemberPreviousAddress.get_or_none(MemberPreviousAddress.id == row_id)
    return Recipient(r.address, f"{r.member.first_name} {r.member.last_name}") if r else None


@recipient_kind("tyck_till")
def _tyck_till_recipient(_id):
    return Recipient(settings.tyck_till.recipient, "Tyck till")


# --- Kinds ---


@mail_kind("ansokan.mottagen", priority=1, category="T")
def _application_received(params):
    found = MemberApplication.select().where(MemberApplication.id == params["application_id"]).exists()
    return {} if found else None


@mail_kind("ansokan.ny", priority=1, category="N")
def _application_new(params):
    pending = (
        MemberApplication.select()
        .where((MemberApplication.id == params["application_id"]) & (MemberApplication.status == "pending"))
        .exists()
    )
    return {} if pending else None


@mail_kind("ansokan.godkand", priority=1, category="T")
def _application_approved(params):
    # None once the person has left: the number is that of the membership the application was approved into.
    person = Member.get_or_none((Member.id == params["member_id"]) & Member.end_date.is_null(True))
    return {"member_number": person.membership.member_number} if person else None


_ADDED_AS = {"familjemedlem": "familjemedlem", "skotare": "skötare"}


@mail_kind("medlemskap.tillagd", priority=1, category="T")
def _member_added(params):
    """To a person someone else put into a membership (GDPR art. 14); none once the person has left it."""
    person = Member.get_or_none((Member.id == params["member_id"]) & Member.end_date.is_null(True))
    if person is None or person.role not in _ADDED_AS:  # left, or made main member since the mail was queued
        return None
    # The limit per address is kept here, on the address the mail goes to now and on mails that have gone: it
    # holds across memberships and after an address was changed. Over it, the mail waits until the oldest of
    # those mails is a day old, so the notices waiting go in order (#191).
    if settings.mail.link_secret:  # without it (log mode only) there is no HMAC, and nothing is sent to count
        gone = (
            (MailMessage.kind == "medlemskap.tillagd")
            & (MailMessage.status == "sent")
            & (MailMessage.address_hash == address_hash(person.email))
            & (MailMessage.sent_at > _utcnow() - timedelta(days=1))
        )
        count, first = (
            MailMessage.select(fn.COUNT(MailMessage.id), fn.MIN(MailMessage.sent_at)).where(gone).scalar(as_tuple=True)
        )
        if count >= ADDED_TO_AN_ADDRESS_A_DAY:
            raise Later(first + timedelta(days=1), "uppskjutet: adressens gräns per dygn")
    main = Member.get_or_none(
        (Member.membership == person.membership_id) & (Member.role == "huvudmedlem") & Member.end_date.is_null(True)
    )
    return {
        "role": _ADDED_AS[person.role],
        # one line: a name typed with a line break must not add lines of its own to the mail
        "main": " ".join(f"{main.first_name} {main.last_name}".split()) if main else None,
        "phone": bool(person.phone),
    }


@mail_kind("kontakt.epost_besked", priority=0, category="T")
def _address_changed(params):
    """To the previous address: it was changed, and by whom. Never the new address."""
    return {"by": "self" if params["by_self"] else "matrikel" if params["by_matrikel"] else "other"}


ADDED_A_DAY = 10  # medlemskap.tillagd mails one membership can cause in a day
ADDED_TO_AN_ADDRESS_A_DAY = 3  # and one address can get: a family may share one, nobody needs more


def queue_member_added(person):
    """
    medlemskap.tillagd in the transaction that adds `person` or gives it an address (the caller holds the
    membership's row lock): only someone put in by another (never a main member, who applied or was written in
    from the register) and only with an e-mail. The person's one row (its dedupe_key) is the record that the
    notice went: a row that never reached the person (refused, bounced, stopped for want of an address, or
    being sent to the address just replaced) is queued again; one that went, or that someone stopped, is not.

    A main member chooses the addresses, so the association's mail must not become a way to flood them: a
    membership's notices are spread over days, at most ADDED_A_DAY a day, and an address gets at most
    ADDED_TO_AN_ADDRESS_A_DAY a day (_member_added, when the mail goes).
    """
    if person.role not in _ADDED_AS or not person.email or person.end_date is not None:
        return None
    ref = ("membership", person.membership_id)
    now = _utcnow()
    # Every row of the membership due in the last day or later holds a place: older notices go first.
    held = (
        (MailMessage.kind == "medlemskap.tillagd")
        & (MailMessage.ref_type == ref[0])
        & (MailMessage.ref_id == ref[1])
        & (MailMessage.next_attempt_at > now - timedelta(days=1))
    )
    not_before = now + timedelta(days=MailMessage.select().where(held).count() // ADDED_A_DAY)
    key = f"medlemskap.tillagd:{person.id}"
    params = {"member_id": person.id}
    queued = enqueue_mail(
        "medlemskap.tillagd", "member", person.id, params, ref=ref, dedupe_key=key, not_before=not_before
    )
    if queued is None:
        # A row being sent loses its claim, so it does not go to the address replaced (_renew).
        MailMessage.update(
            status="queued", next_attempt_at=not_before, attempts=0, last_error=None, claim_token=None, claimed_at=None
        ).where(
            (MailMessage.dedupe_key == key)
            & (
                MailMessage.status.in_(("failed", "bounced", "sending"))
                | ((MailMessage.status == "cancelled") & (MailMessage.last_error == NO_ADDRESS))
            )
        ).execute()
    return queued


def cancel_member_added(member_ids):
    """
    The people left their membership or became its main member: their unsent medlemskap.tillagd is stopped, also
    one being sent right now, which loses its claim (_renew), in the caller's transaction.
    """
    return (
        MailMessage.update(
            status="cancelled", claim_token=None, claimed_at=None, last_error="personen har lämnat medlemskapet"
        )
        .where(
            (MailMessage.kind == "medlemskap.tillagd")
            & (MailMessage.recipient_kind == "member")
            & MailMessage.recipient_id.in_(list(member_ids))
            & MailMessage.status.in_(("queued", "sending"))
        )
        .execute()
    )


def queue_application_mails(application_id, address):
    """
    The receipt to the applicant and a notice to each matrikel admin, in the caller's transaction. The public
    form takes any address, so `address` gets at most one receipt a day, keyed on its HMAC, never on itself.
    """
    params = {"application_id": application_id}
    ref = ("member_application", application_id)
    # Without LINK_SECRET (log mode only, nothing is sent) there is no HMAC, and no need for the limit.
    once_a_day = f"ansokan.mottagen:{address_hash(address)}:{_utcnow().date()}" if settings.mail.link_secret else None
    enqueue_mail("ansokan.mottagen", "application", application_id, params, ref=ref, dedupe_key=once_a_day)
    candidates = User.select().where(User.is_active & User._privileges.contains("matrikel_admin"))
    for user in candidates:
        if user.is_matrikel_admin:
            enqueue_mail("ansokan.ny", "user", user.id, params, ref=ref)


@mail_kind("tyck_till.inskick", priority=1, category="N")
def _tyck_till(params):
    """A "Tyck till" submission to the association: its text, images and contacts are read from the folder."""
    inskick_id = uuid.UUID(int=params["inskick"])
    folder = tyck_till.folder(inskick_id)
    try:
        data = json.loads((folder / "inskick.json").read_text())
    except FileNotFoundError:
        return None
    repo = tyck_till.REPOS["privat" if params["repo"] else "publik"]
    name, email = None, _normalize(data.get("email"))
    if email is None and data.get("contact") and data.get("user_id"):  # the account's name and address, as of now
        user = User.get_or_none(User.id == data["user_id"])
        name, email = (user.fullname, _normalize(user.email)) if user else (None, None)
    return {
        "repo": repo.split("/")[1],
        "number": params["issue"],
        "url": f"https://github.com/{repo}/issues/{params['issue']}",
        "ref": tyck_till.reference(inskick_id),
        "tavla": bool(params["tavla"]),
        "kind": data["kind"],
        "text": data["text"],
        "path": tyck_till.mail_path(data.get("path")),
        "pekat": tyck_till.pointed(data.get("pekat")),
        "version": tyck_till.clean_version(data.get("version")),
        "device": data.get("device"),
        "user_id": data.get("user_id"),
        "name": " ".join(name.split()) if name else None,
        "email": email,
        "reply_to": email,
        "images": len(data["images"]),
        "attachments": [(Path(f).name, "image/jpeg", (folder / Path(f).name).read_bytes()) for f in data["images"]],
    }
