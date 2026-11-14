"""
The intake queue's Gmail reader (docs/inkorg-gmail.md). The scheduler's job inbox_gmail reads the association's
mailbox and turns each message in INBOX into an item of the queue.

Each Gmail message is handled once: its row in gmail_processed is written in the transaction of its effects
(and of the mails they queue). Only after the commit is the message labelled "Inläst" and moved to the trash,
so a message read again after a crash in between is only labelled. A message that cannot be read is labelled
"Fel vid inläsning" and left in the inbox.
"""

import email
import hmac
import logging
import re
from datetime import datetime, timezone
from email import policy
from email.parser import HeaderParser
from email.utils import parseaddr

import utils.inbox as inbox
import utils.mail as mail
from utils.database import (
    DB_PROXY,
    GmailProcessed,
    GmailSync,
    Herd,
    InboxEvent,
    InboxItem,
    MailMessage,
    Member,
    User,
)
from utils.gmail import Gmail, HistoryTooOld
from utils.mail import _hostname, _normalize, _scrub

logger = logging.getLogger("herdbook.inbox_gmail")

READ, FAILED, DEMO = "Inläst", "Fel vid inläsning", "Demo"
MAX_TEXT = 10_000  # characters of a mail's text kept on the item; shortcut: cut, raise it if handlers miss text
# One of our Message-IDs (utils.mail.message_id), of any environment: <mail-<row>.<16 hex>@<its hostname>>.
_OUR_ID = re.compile(r"<mail-(\d{1,18})\.[0-9a-f]{16}@([A-Za-z0-9.-]+)>")
_CASE = re.compile(r"\(ärende (\d{1,9})\)$")
# Authentication-Results (RFC 8601) as Gmail writes it: "spf=pass (comment) smtp.mailfrom=<envelope sender>",
# "dkim=pass header.i=@<signing domain> header.s=… header.b=…".
_QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')
_COMMENT = re.compile(r"\([^()]*\)")
_SPF = re.compile(r"spf=pass\s.*\bsmtp\.mailfrom=(\S+)", re.I | re.S)
_DKIM = re.compile(r"dkim=pass\s+header\.[id]=@?([a-z0-9.-]+)(?:\s|$)", re.I)


def run(gmail=None):
    """
    One run of the job: the messages added to INBOX since the stored historyId, or the whole inbox when Gmail
    no longer has that history (or on the first run). The historyId moves on only when every message is
    labelled, so a run that fails half way is read again.
    """
    GmailSync.insert(id=1).on_conflict_ignore().execute()
    sync = GmailSync.get_by_id(1)
    gmail = gmail or Gmail.from_settings()
    try:
        ids, newest = _new_messages(gmail, sync.history_id)
        errors = [error for message_id in ids if (error := _handle(gmail, message_id))]
    except Exception as exc:
        GmailSync.update(last_error=_scrub(f"{type(exc).__name__}: {exc}")).where(GmailSync.id == 1).execute()
        raise
    GmailSync.update(history_id=newest, last_run_at=inbox.now(), last_error="; ".join(errors) or None).where(
        GmailSync.id == 1
    ).execute()


def _new_messages(gmail, history_id):
    if history_id:
        try:
            return gmail.added_since(history_id)
        except HistoryTooOld:
            logger.warning("Gmail has no history since %s: reading the whole inbox", history_id)
    newest = gmail.history_id()  # before the listing, so that nothing arriving during it is missed
    return gmail.inbox(), newest


def _handle(gmail, message_id):
    """Reads and labels one message; returns the error when it could not be read."""
    found = gmail.message(message_id)
    if found is None or "INBOX" not in found["labelIds"] or gmail.label(READ) in found["labelIds"]:
        return None  # gone, not in the inbox (never SPAM), or read before
    if not GmailProcessed.select().where(GmailProcessed.gmail_message_id == message_id).exists():
        received = datetime.fromtimestamp(int(found["internalDate"]) / 1000, timezone.utc)
        try:
            outcome = read_message(message_id, found["raw"], received)
        except Exception as exc:  # pylint: disable=broad-except  # one bad message must not stop the others
            logger.exception("Reading Gmail message %s failed", message_id)
            gmail.modify(message_id, add=[gmail.label(FAILED)])
            return _scrub(f"{message_id}: {type(exc).__name__}: {exc}")
        if outcome == DEMO:
            gmail.modify(message_id, add=[gmail.label(DEMO)])
            return None
    gmail.modify(message_id, add=[gmail.label(READ)], remove=[gmail.label(FAILED)])
    gmail.trash(message_id)
    return None


def read_message(gmail_id, raw, received_at=None):
    """
    Sorts one message and writes its effects with its gmail_processed row in one transaction: a delivery report
    marks our mail bounced, an automatic answer is ignored, a reply goes on the item it answers when its sender
    may answer there, and anything else becomes an item. Returns DEMO for another environment's mail, which
    nothing here touches (no row either: it has no effects to guard).
    """
    msg = email.message_from_bytes(raw, policy=policy.default)
    sender = _normalize(parseaddr(str(msg.get("From", "")))[1])
    here = _hostname().lower()
    report = _delivery_report(msg)
    if report is not None:
        original, diagnostic, text = report
        if _hosts(original) - {here}:
            return DEMO
        with DB_PROXY.atomic():
            if mail.record_bounce(original, diagnostic):
                _processed(gmail_id, "bounce")
            else:  # a report on no mail of ours: a human has a look
                _processed(gmail_id, "item", _new_item(gmail_id, sender, text, received_at))
        return None
    if _auto_reply(msg):
        with DB_PROXY.atomic():
            _processed(gmail_id, "ignored")
        return None
    replied_to = _hosts(msg.get("In-Reply-To"), msg.get("References"))
    if replied_to and here not in replied_to:
        return DEMO
    text = _text(msg)
    with DB_PROXY.atomic():
        replied = _replied_item(msg)
        if replied is not None and _may_answer(msg, sender, replied):
            _attach_reply(replied, text)
            _processed(gmail_id, "reply", replied)
        else:
            maybe = replied.id if replied is not None else None
            _processed(gmail_id, "item", _new_item(gmail_id, sender, text, received_at, maybe_item=maybe))
    return None


def _processed(gmail_id, kind, item=None):
    GmailProcessed.create(gmail_message_id=gmail_id, kind=kind, item=item)


def _hosts(*headers):
    """The hostnames of our Message-IDs in the headers, of whichever environment sent them."""
    return {match.group(2).lower() for header in headers for match in _OUR_ID.finditer(str(header or ""))}


def _content(part):
    try:
        return part.get_content()
    except (LookupError, UnicodeError):  # an unknown or lying charset
        return part.get_payload(decode=True).decode("utf-8", "replace")


def _text(msg):
    """The mail's own text, plain if it has it."""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return None
    return _content(part).strip()[:MAX_TEXT] or None


def _delivery_report(msg):
    """(the bounced mail's Message-ID, the diagnostic, the readable text) of a delivery report, else None."""
    if (
        msg.get_content_type() != "multipart/report"
        or (msg.get_param("report-type") or "").lower() != "delivery-status"
    ):
        return None
    original = diagnostic = text = None
    for part in msg.walk():
        kind = part.get_content_type()
        if kind == "text/plain" and text is None:
            text = _content(part).strip()[:MAX_TEXT] or None
        elif kind == "message/delivery-status":
            for fields in part.get_payload():
                diagnostic = diagnostic or fields.get("Diagnostic-Code") or fields.get("Status")
        elif kind in ("message/rfc822", "text/rfc822-headers") and original is None:
            headers = (
                part.get_payload()[0]
                if kind == "message/rfc822"
                else HeaderParser(policy=policy.default).parsestr(_content(part))
            )
            original = headers.get("Message-ID")
    return (str(original).strip() if original else None), (str(diagnostic) if diagnostic else None), text


def _auto_reply(msg):
    """An out-of-office or other automatic answer (RFC 3834 and the common variants)."""
    submitted = str(msg.get("Auto-Submitted", "no")).split(";")[0].strip().lower()
    precedence = str(msg.get("Precedence", "")).strip().lower()
    return submitted != "no" or msg.get("X-Autoreply") is not None or precedence == "auto_reply"


def _replied_item(msg):
    """
    The item a reply is about, locked: by one of our mails about it in In-Reply-To (its Message-ID checked like
    a bounce's, host and HMAC), failing that by "(ärende <id>)" at the end of the subject. This only says which
    item; whether the sender may answer there is _may_answer's.
    """
    item_id = None
    for match in _OUR_ID.finditer(str(msg.get("In-Reply-To", ""))):
        row_id = int(match.group(1))
        if hmac.compare_digest(mail.message_id(row_id), match.group(0)):
            row = MailMessage.get_or_none(MailMessage.id == row_id)
            if row is not None and row.ref_type == "inbox_item":
                item_id = row.ref_id
                break
    if item_id is None:
        case = _CASE.search(" ".join(str(msg.get("Subject", "")).split()))
        item_id = int(case.group(1)) if case else None
    return InboxItem.select().where(InboxItem.id == item_id).for_update().first() if item_id else None


def _may_answer(msg, sender, item):
    """An answer goes on an open item only from an authenticated sender who is related to it (Codex 5)."""
    return item.state not in inbox.CLOSED_STATES and authenticated(msg, sender) and sender in _related(item)


def _related(item):
    """Whom a question on the item went to, its sender, and its herd's holder per the member register."""
    asked = MailMessage.select(MailMessage.recipient_id).where(
        (MailMessage.kind == "inlasning.fraga")
        & (MailMessage.recipient_kind == "member")
        & (MailMessage.ref_type == "inbox_item")
        & (MailMessage.ref_id == item.id)
    )
    addresses = [m.email for m in Member.select(Member.email).where(Member.id.in_(asked))]
    holder = herd_holder(item.herd_id)
    uploader = User.get_or_none(User.id == item.sender_user_id) if item.sender_user_id else None
    addresses += [item.sender_address, holder and holder.email, uploader and uploader.email]
    return {_normalize(address) for address in addresses} - {None}


def herd_holder(herd_id):
    """The herd's holder per the member register: the active main member of the membership that owns it."""
    if herd_id is None:
        return None
    return (
        Member.select()
        .join(Herd, on=(Herd.membership == Member.membership))
        .where((Herd.id == herd_id) & (Member.role == "huvudmedlem") & Member.end_date.is_null(True))
        .order_by(Member.id)
        .first()
    )


def authenticated(msg, sender):
    """
    Did Gmail authenticate the sender's domain? Only the topmost Authentication-Results counts, the one the
    receiving Google server adds (anything below it may come from the sender), and only an SPF or DKIM pass for
    the From address's domain, a parent or a subdomain of it: a pass for another domain says nothing about
    From. Quoted strings and comments go first, as they can hold the envelope sender's own text.
    """
    headers = msg.get_all("Authentication-Results") or []
    if not headers or not sender:
        return False
    top = _COMMENT.sub(" ", _QUOTED.sub(" ", " ".join(str(headers[0]).split())))
    server, _, results = top.partition(";")
    if server.strip().lower() != "mx.google.com":
        return False
    domain = sender.rpartition("@")[2]
    for result in results.split(";"):
        found = _SPF.fullmatch(result.strip()) or _DKIM.match(result.strip())
        passing = found.group(1).rpartition("@")[2].lower().rstrip(".") if found else ""
        if "." in passing and (passing == domain or domain.endswith(f".{passing}") or passing.endswith(f".{domain}")):
            return True
    return False


def _attach_reply(item, text):
    """An answer on the item: an event with its text, back to the handler if it waited, and a notice."""
    InboxEvent.create(item=item, kind="svar", detail={"text": text})
    if item.state == "vantar_uppfodare":
        inbox._set_state(item, "tagen")  # pylint: disable=protected-access
        item.save()
    if item.assigned_to_id:
        handlers = [item.assigned_to_id]
    else:
        handlers = [user.id for user in inbox.queue_workers(item.genebank_id, managers_only=True)]
    for handler in handlers:
        inbox.notify(handler, "svar", item)


def _new_item(gmail_id, sender, text, received_at, maybe_item=None):
    item = InboxItem.create(
        kind="meddelande",
        sender_address=sender,
        message=text,
        gmail_message_id=gmail_id,
        received_at=received_at or inbox.now(),
    )
    detail = {"documents": 0, **({"maybe_item": maybe_item} if maybe_item else {})}
    InboxEvent.create(item=item, kind="inkommen", detail=detail)
    for worker in inbox.queue_workers(item.genebank_id):
        inbox.notify(worker, "ny_post", item)
    return item
