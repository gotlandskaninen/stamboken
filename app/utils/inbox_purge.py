"""
The intake queue's retention (docs/inkorg.md, "Gallring"): the rules of the nightly job inbox_purge.

A row lets go of a file before the file goes: the rows change in a transaction with their items locked (every
write through the queue locks its item first, so none can save a stale document over ours), and the files are
removed after the commit. A crash in between leaves a file that no row names, never a row naming a missing file.
Only originals are removed, and only inside PRIVATE_UPLOAD_FOLDER/inkorg/original: the masked copy on the rabbit
and the inbox_operation trace stay. Every rule takes `now` and is idempotent.
"""

import logging
import os
from datetime import timedelta

from peewee import SQL, Case

import utils.inbox as inbox
import utils.inbox_gmail as inbox_gmail
import utils.settings as settings
from utils.database import DB_PROXY, GmailProcessed, HerdTracking, InboxDocument, InboxEvent, InboxItem
from utils.mail import forget_recipient

logger = logging.getLogger("herdbook.inbox_purge")

ORIGINAL_TYPES = ("intyg", "bevis")  # certificates and proofs; other photos are kept until decided
FREE_TEXT = ["text", "note", "not_saved"]  # in inbox_event.detail: questions, answers, notes, attachment names
OPENED_MONTHS = 13
MESSAGE_MONTHS = 13
JUNK_AFTER = timedelta(days=30)
GMAIL_PROCESSED_AFTER = timedelta(days=60)
STALLED_AFTER = timedelta(days=14)
VIEWS = ("oppnad", "original_visat")  # looking at an item is not something happening to it


def _lock(items):
    """The items (a query of ids) locked in the queue's order; returns their ids."""
    query = InboxItem.select(InboxItem.id).where(InboxItem.id.in_(items)).order_by(InboxItem.id).for_update()
    return [item_id for (item_id,) in query.tuples()]


def _null_originals(where):
    """In the caller's transaction: the documents matching `where` let go of their originals; returns the paths."""
    _lock(InboxDocument.select(InboxDocument.item).where(where))
    rows = InboxDocument.select(InboxDocument.id, InboxDocument.original_path)
    rows = list(rows.where(where & InboxDocument.original_path.is_null(False)).tuples())
    if rows:
        waiting = Case(
            None, [(InboxDocument.interpretation_status == "vantar", "av")], InboxDocument.interpretation_status
        )
        query = InboxDocument.update(original_path=None, interpretation_status=waiting)
        query.where(InboxDocument.id.in_([document_id for document_id, _ in rows])).execute()
    return [path for _, path in rows]


def _clear_text(items):
    """The items' text: the message, and the free text in their events (the events, kinds, times and users stay)."""
    cleared = InboxItem.update(message=None).where(InboxItem.id.in_(items) & InboxItem.message.is_null(False))
    events = InboxEvent.update(detail=SQL("detail - %s::text[]", [FREE_TEXT]))
    events = events.where(InboxEvent.item.in_(items) & SQL("detail ?| %s::text[]", [FREE_TEXT]))
    return cleared.execute() + events.execute()


def remove_originals(paths):
    """
    After the commit: removes the originals the rows let go of, but only files directly in the originals folder
    (a path naming anything else, also a copy, is kept). Logs counts, never names. Returns how many went.
    """
    folder = os.path.realpath(inbox.private_path("inkorg/original"))
    removed = kept = failed = 0
    for relative in paths:
        path = os.path.realpath(inbox.private_path(relative))
        if os.path.dirname(path) != folder:
            kept += 1
            continue
        try:
            os.remove(path)
            removed += 1
        except FileNotFoundError:
            pass
        except OSError:
            failed += 1
    if kept:
        logger.warning("Kept %s inbox files named outside the originals folder", kept)
    if failed:
        logger.error("Could not remove %s inbox originals; no row names them any more", failed)
    return removed


def _delete_items(where):
    """
    Deletes the items matching `where`, with their documents, events, notices and originals. Never an item that
    put something on a rabbit (a copy, a registration or a sale's proof): the originals and text rules take those.
    """
    saved = InboxDocument.select(InboxDocument.item).where(
        InboxDocument.public_path.is_null(False)
        | InboxDocument.individual.is_null(False)
        | InboxDocument.herd_tracking_id.is_null(False)
    )
    with DB_PROXY.atomic():
        query = InboxItem.select(InboxItem.id).where(where & InboxItem.id.not_in(saved))
        ids = [item_id for (item_id,) in query.order_by(InboxItem.id).for_update().tuples()]
        documents = InboxDocument.select(InboxDocument.original_path).where(
            InboxDocument.item.in_(ids) & InboxDocument.original_path.is_null(False)
        )
        paths = [path for (path,) in documents.tuples()]
        InboxItem.delete().where(InboxItem.id.in_(ids)).execute()
        for item_id in ids:
            forget_recipient("inbox_sender", item_id)
    remove_originals(paths)
    return len(ids)


def purge_originals(now):
    """Originals of certificates and proofs some months after their item came in, and the item's text with them."""
    old = InboxItem.select(InboxItem.id).where(
        InboxItem.received_at < now - inbox.months(settings.inbox.original_months)
    )
    with DB_PROXY.atomic():
        paths = _null_originals(InboxDocument.item.in_(old) & InboxDocument.doc_type.in_(ORIGINAL_TYPES))
        _clear_text(old.where(InboxItem.id.in_(InboxDocument.select(InboxDocument.item))))  # a message keeps its own
    return remove_originals(paths)


def purge_sold_proofs(now):  # pylint: disable=unused-argument  # every rule takes the clock
    """A proof's original once its rabbit is sold on: a later active TRANSFER from the buyer's herd. The sale stays."""
    sale, later = HerdTracking, HerdTracking.alias()
    proofs = InboxDocument.select(InboxDocument.herd_tracking_id).where(
        (InboxDocument.doc_type == "bevis") & InboxDocument.original_path.is_null(False)
    )
    sold_on = (
        sale.select(sale.id)
        .join(later, on=(later.individual == sale.individual))
        .where(
            sale.id.in_(proofs)
            & sale.voided_at.is_null(True)
            & later.voided_at.is_null(True)
            & (later.kind == "TRANSFER")
            & (later.from_herd == sale.herd)
            & (
                (later.herd_tracking_date > sale.herd_tracking_date)
                | ((later.herd_tracking_date == sale.herd_tracking_date) & (later.id > sale.id))
            )
        )
    )
    with DB_PROXY.atomic():
        paths = _null_originals((InboxDocument.doc_type == "bevis") & InboxDocument.herd_tracking_id.in_(sold_on))
    return remove_originals(paths)


def remind_incomplete(now):
    """inlasning.paminnelse once to the sender of an item still "ofullstandig" 11 months after it came in."""
    old = now - inbox.months(inbox.REMIND_MONTHS)
    queued = 0
    with DB_PROXY.atomic():
        for item in InboxItem.select().where((InboxItem.state == "ofullstandig") & (InboxItem.received_at < old)):
            marked = item.events.where((InboxEvent.kind == "lage") & InboxEvent.detail.contains({"to": "ofullstandig"}))
            marked = marked.order_by(InboxEvent.id.desc()).first()
            params = {"item_id": item.id, "event_id": marked.id} if marked else None
            key = f"inlasning.paminnelse:{item.id}"
            if params and inbox.mail_sender(item, "inlasning.paminnelse", params, dedupe_key=key):
                queued += 1
    return queued


def purge_incomplete(now):
    """An item left "ofullstandig" a year after it came in."""
    old = now - inbox.months(inbox.INCOMPLETE_MONTHS)
    return _delete_items((InboxItem.state == "ofullstandig") & (InboxItem.received_at < old))


def purge_junk(now):
    """An item closed as junk ("skrap") 30 days after it closed."""
    return _delete_items((InboxItem.state == "skrap") & (InboxItem.closed_at < now - JUNK_AFTER))


def purge_messages(now):
    """A closed message ("meddelande") without documents 13 months after it closed."""
    no_documents = InboxItem.id.not_in(InboxDocument.select(InboxDocument.item))
    closed = InboxItem.state.in_(inbox.CLOSED_STATES) & (InboxItem.closed_at < now - inbox.months(MESSAGE_MONTHS))
    return _delete_items((InboxItem.kind == "meddelande") & closed & no_documents)


def purge_opened(now):
    """The log of who opened an item, after 13 months."""
    old = now - inbox.months(OPENED_MONTHS)
    return InboxEvent.delete().where((InboxEvent.kind == "oppnad") & (InboxEvent.at < old)).execute()


def purge_gmail_processed(now):
    """The Gmail reader's rows after 60 days, when the mail is long gone from Gmail's trash."""
    return GmailProcessed.delete().where(GmailProcessed.at < now - GMAIL_PROCESSED_AFTER).execute()


def mark_stalled(now):
    """
    "Står still": an item "tagen" for 14 days with no event since (a view is none) gets the flag, and its genebank's
    managers a notice, once per stall; the flag goes when something has happened.
    """
    since = now - STALLED_AFTER
    recent = InboxEvent.select(InboxEvent.item).where((InboxEvent.at > since) & InboxEvent.kind.not_in(VIEWS))
    still = (InboxItem.state == "tagen") & (InboxItem.state_changed_at < since) & InboxItem.id.not_in(recent)
    with DB_PROXY.atomic():
        InboxItem.update(stalled=False).where(InboxItem.stalled & ~still).execute()
        stalled = InboxItem.update(stalled=True).where(~InboxItem.stalled & still)
        stalled = list(stalled.returning(InboxItem.id, InboxItem.genebank).tuples())
        for item_id, genebank_id in stalled:
            for manager in inbox.queue_workers(genebank_id, managers_only=True):
                inbox.notify(manager, "star_still", item_id)
    return len(stalled)


# The Gmail job sweeps sender addresses too, but it runs only with the reading on.
RULES = (
    inbox_gmail.release_senders,
    remind_incomplete,
    purge_originals,
    purge_sold_proofs,
    purge_incomplete,
    purge_junk,
    purge_messages,
    purge_opened,
    purge_gmail_processed,
    mark_stalled,
)


def run(now):
    """The nightly inbox_purge: every rule on its own, so one failing does not skip the others."""
    for rule in RULES:
        try:
            logger.info("Inbox purge %s: %s", rule.__name__, rule(now))
        except Exception:  # pylint: disable=broad-except
            logger.exception("Inbox purge %s failed", rule.__name__)


def erase_person_from_inbox(member):
    """
    Erasure of a member (anonymize_person): every document recorded as showing the member as seller or buyer
    loses its original, so that only the masked copy without the seller and buyer block is left where there is
    one, and its item loses its text. In the caller's transaction; the caller passes the returned paths to
    remove_originals after the commit.
    """
    shown = (InboxDocument.seller_member == member.id) | (InboxDocument.buyer_member == member.id)
    paths = _null_originals(shown)
    _clear_text(InboxDocument.select(InboxDocument.item).where(shown))
    return paths


def erase_document(item, document, user):
    """
    POST …/radera-original: the same for one document on request (a buyer outside the association has no member
    row), logged on the item. The caller holds the item's lock; returns the paths for remove_originals.
    """
    paths = _null_originals(InboxDocument.id == document.id)
    _clear_text([item.id])
    inbox.log_event(item, user, "original_raderat", document=document.id)
    return paths


def erase_buyer_from_inbox(herd_tracking_id):  # pylint: disable=unused-argument
    """
    Seam, a no-op for now: when a buyer outside the association is deleted (an erasure, a void of the sale or the
    five-year purge, utils.herd_tracking.delete_buyer_contacts), the original of the sale's proof (the bevis whose
    inbox_document.herd_tracking_id is this sale) is to go too, as erase_document does for one document. Called
    in the caller's transaction, before the buyer is deleted.
    """
