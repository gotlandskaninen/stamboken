"""
The intake queue's Gmail reader (docs/inkorg-gmail.md). The scheduler's job inbox_gmail reads the association's
mailbox and turns each message in INBOX into an item of the queue.

Each Gmail message is handled once: its row in gmail_processed is written in the transaction of its effects
(and of the mails they queue). Only after the commit is the message labelled "Inläst" and moved to the trash,
so a message read again after a crash in between is only labelled. A message that cannot be read is labelled
"Fel vid inläsning" and left in the inbox.
"""

import email
import logging
from datetime import datetime, timezone
from email import policy
from email.utils import parseaddr

import utils.inbox as inbox
from utils.database import DB_PROXY, GmailProcessed, GmailSync, InboxEvent, InboxItem
from utils.gmail import Gmail, HistoryTooOld
from utils.mail import _normalize, _scrub

logger = logging.getLogger("herdbook.inbox_gmail")

READ, FAILED = "Inläst", "Fel vid inläsning"
MAX_TEXT = 10_000  # characters of a mail's text kept on the item; shortcut: cut, raise it if handlers miss text


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
            read_message(message_id, found["raw"], received)
        except Exception as exc:  # pylint: disable=broad-except  # one bad message must not stop the others
            logger.exception("Reading Gmail message %s failed", message_id)
            gmail.modify(message_id, add=[gmail.label(FAILED)])
            return _scrub(f"{message_id}: {type(exc).__name__}: {exc}")
    gmail.modify(message_id, add=[gmail.label(READ)], remove=[gmail.label(FAILED)])
    gmail.trash(message_id)
    return None


def read_message(gmail_id, raw, received_at=None):
    """Turns one message into its effects, written with its gmail_processed row in one transaction."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    sender = _normalize(parseaddr(str(msg.get("From", "")))[1])
    with DB_PROXY.atomic():
        item = _new_item(gmail_id, sender, _text(msg), received_at)
        GmailProcessed.create(gmail_message_id=gmail_id, kind="item", item=item)


def _text(msg):
    """The mail's own text, plain if it has it."""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return None
    try:
        text = part.get_content()
    except (LookupError, UnicodeError):  # an unknown or lying charset
        text = part.get_payload(decode=True).decode("utf-8", "replace")
    return text.strip()[:MAX_TEXT] or None


def _new_item(gmail_id, sender, text, received_at):
    item = InboxItem.create(
        kind="meddelande",
        sender_address=sender,
        message=text,
        gmail_message_id=gmail_id,
        received_at=received_at or inbox.now(),
    )
    InboxEvent.create(item=item, kind="inkommen", detail={"documents": 0})
    for worker in inbox.queue_workers(item.genebank_id):
        inbox.notify(worker, "ny_post", item)
    return item
