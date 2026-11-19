"""
The intake queue (inläsningskön, docs/inkorg.md): items of photos sent in for a human to register, their states
and handlers, the notices about them, and the masked copy of a certificate shown on the rabbit.

The files live under PRIVATE_UPLOAD_FOLDER, never under UPLOAD_FOLDER, which nginx serves without login.
"""

import hashlib
import io
import math
import os
import uuid
from datetime import datetime, timedelta, timezone

from peewee import fn
from PIL import Image, ImageDraw, ImageFilter, ImageStat

import utils.inbox_interpreter as interpreter
import utils.settings as settings
from utils.database import (
    DB_PROXY,
    OUTSIDE_GENEBANK_HERDS,
    Herd,
    HerdTracking,
    InboxDocument,
    InboxEvent,
    InboxItem,
    InboxOperation,
    Individual,
    MailMessage,
    Member,
    Notice,
    NoticeSetting,
    SaleProposal,
    User,
    YearlyHerdReport,
    YearlyReportRound,
)
from utils.inbox_proposal import build_proposal
from utils.individual_number_v2 import parse_number
from utils.individual_policy import Role
from utils.log_masking import mask_tokens
from utils.mail import enqueue_mail, forget_recipient, mail_kind

OPEN_STATES = ("ny", "tagen", "vantar_uppfodare", "vantar_foralder", "hos_genbanksansvarig", "ofullstandig")
CLOSED_STATES = ("klar", "dubblett", "skrap")
HELD_STATES = ("tagen", "vantar_uppfodare", "vantar_foralder", "ofullstandig")  # the item has a handler
# POST …/lage: the target state and the states the item's handler may move it from. A closed item is reopened
# ("tagen") by a manager of its genebank or an admin, who becomes its handler. The other states are reached
# otherwise: "ny" when the item comes in, "tagen" also by taking or assigning, "klar" when its last document is
# done or dismissed, "vantar_uppfodare" by the question to the breeder (utils/inbox_gmail.py, back with the answer).
# A message, or any item without documents (a mail whose attachments were all skipped), has nothing to save: its
# handler closes it as "klar" once it is answered (MESSAGE_DONE_FROM).
TRANSITIONS = {
    "tagen": ("vantar_foralder", "ofullstandig", *CLOSED_STATES),
    "vantar_foralder": ("tagen",),
    "hos_genbanksansvarig": ("tagen",),
    "ofullstandig": ("tagen",),
    "dubblett": HELD_STATES,
    "skrap": HELD_STATES,
}
MESSAGE_DONE_FROM = HELD_STATES
# What "Mina inskick" shows the uploader instead of the queue's state.
PLAIN_STATES = {
    "ny": "mottaget",
    "tagen": "under_arbete",
    "vantar_foralder": "under_arbete",
    "hos_genbanksansvarig": "under_arbete",
    "vantar_uppfodare": "fragat",
    "ofullstandig": "fragat",
    "klar": "klart",
    "dubblett": "avslutat",
    "skrap": "avslutat",
}
NOTICE_TEXTS = {
    "ny_post": "Ny post i inläsningskön",
    "tilldelad": "En post har tilldelats dig",
    "overtagen": "Någon har tagit över din post",
    "lamnad": "En post har lämnats till genbanksansvarig",
    "foralder_inlagd": "Föräldern är inlagd, och posten väntar inte längre",
    "klar": "Ditt inskick är klart",
    "svar": "Uppfödaren har svarat",
    "star_still": "En post har stått still i 14 dagar",
}
DOC_TYPES = ("intyg", "bevis", "arsblankett", "annat")
CERT_FORMATS = ("handskrivet", "datorskrivet", "v1_pdf", "intyg_b", "digitalt_v2")
OPENED_EVERY = timedelta(hours=1)
PURPOSE = "syfte"  # ref_data's key on a report photo held for a purchase: "kop" (a notice's) or "inskick" (S7, to send)
PURPOSES = ("kop", "inskick")
HELD_RABBIT = "kanin"  # PURPOSE of a photo for "Lägg till kanin", held until Spara registers the rabbit (not sent)
# An item left "ofullstandig" is deleted this long after its retention_start (utils/inbox_purge.py),
# and its sender is reminded after REMIND_MONTHS.
INCOMPLETE_MONTHS = 12
REMIND_MONTHS = 11
MAX_NOTE = 2000
MAX_RECTS = 20
# The masking a handwritten certificate (format 1) is offered: its lower third, where seller and buyer write.
HANDWRITTEN_MASK = [{"x": 0.0, "y": 0.6667, "w": 1.0, "h": 0.3333}]


class InboxError(Exception):
    """
    A refusal with its HTTP status, turned into a problem response by the blueprint. It rolls back the request's
    transaction, unless `keep`: what was done before it (a correction the refusal reports) is committed.
    """

    TITLES = {400: "Ogiltig begäran", 403: "Åtkomst nekad", 404: "Hittades inte", 409: "Konflikt"}

    def __init__(self, status, detail, *, keep=False):
        super().__init__(detail)
        self.status, self.title, self.detail, self.keep = status, self.TITLES[status], detail, keep


JPEG_QUALITY = 90
# The quality of a photo, measured when it comes in. First guesses, to be tuned against real photos of
# certificates: the ones no model could read should get a warning, the others not.
MIN_SHORT_SIDE = 1000  # pixels
SHARPNESS_SIDE = 1000  # the sharpness is measured on a grey copy at most this many pixels a side
MIN_SHARPNESS = 25.0  # variance of the Laplacian on that copy
MIN_BRIGHTNESS = 50.0  # mean grey level, 0-255
MAX_BRIGHTNESS = 235.0
_LAPLACIAN = ImageFilter.Kernel((3, 3), (0, 1, 0, 1, -4, 1, 0, 1, 0), scale=1, offset=128)


def now():
    return datetime.now(timezone.utc)


def months(count):
    """`count` months as days, rounded up as the command log's 13 months (396 days): the retention's one measure."""
    return timedelta(days=math.ceil(count * 365.25 / 12))


def _iso(value):
    return value.isoformat() if value else None


def works_in_queue(user):
    """Admins, genebank managers and helpers see and work the whole queue."""
    return bool(user.is_admin or user.is_manager or user.is_helper)


def measure(image):
    """Resolution, sharpness and light of an RGB image."""
    grey = image.convert("L")
    grey.thumbnail((SHARPNESS_SIDE, SHARPNESS_SIDE))
    edges = grey.filter(_LAPLACIAN)
    if min(edges.size) > 2:  # the filter leaves the border unfiltered; an image of a pixel or two has only border
        edges = edges.crop((1, 1, edges.width - 1, edges.height - 1))
    return {
        "short_side": min(image.size),
        "sharpness": round(ImageStat.Stat(edges).var[0], 1),
        "brightness": round(ImageStat.Stat(grey).mean[0], 1),
    }


def warnings(quality):
    """What makes a photo look unreadable, from its measures (computed on read, so new thresholds apply)."""
    if not quality:
        return []
    checks = (
        ("lag_upplosning", quality["short_side"] < MIN_SHORT_SIDE),
        ("suddig", quality["sharpness"] < MIN_SHARPNESS),
        ("for_mork", quality["brightness"] < MIN_BRIGHTNESS),
        ("for_ljus", quality["brightness"] > MAX_BRIGHTNESS),
    )
    return [name for name, bad in checks if bad]


def private_path(relative):
    return os.path.join(settings.service.private_upload_folder, relative)


def jpeg_bytes(image):
    """`image` as a JPEG without metadata (EXIF, GPS, XMP)."""
    image.info = {}  # nothing of the uploaded file's metadata may reach the saved one
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()


def store_jpeg(image, folder, name=None):
    """write_jpeg of `image` as a JPEG without metadata."""
    return write_jpeg(jpeg_bytes(image), folder, name)


def write_jpeg(data, folder, name=None):
    """
    Saves the JPEG `data` as inkorg/<folder>/<name>.jpg under PRIVATE_UPLOAD_FOLDER; returns (relative path,
    sha256). A new name is random; a given one is replaced.
    """
    relative = f"inkorg/{folder}/{name or uuid.uuid4().hex}.jpg"
    path = private_path(relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.{uuid.uuid4().hex}.tmp"
    with open(temporary, "xb") as out:
        out.write(data)
    os.replace(temporary, path)
    return relative, hashlib.sha256(data).hexdigest()


def remove_files(relatives):
    for relative in relatives:
        try:
            os.remove(private_path(relative))
        except FileNotFoundError:
            pass


def log_event(item, user, kind, **detail):
    return InboxEvent.create(item=item, user=user, kind=kind, detail=detail or None)


def notify(user, kind, item, *, mailed=False):
    """A notice in Stamboken; `mailed` keeps it out of the daily digest (it has a mail of its own)."""
    Notice.create(user=user, kind=kind, item=item, mailed_at=now() if mailed else None)


def queue_workers(genebank_id, *, managers_only=False):
    """
    The active users the queue's notices about a genebank go to: its managers, and its helpers unless
    `managers_only`. With no genebank: every manager (and helper) and the admins. The JSON column is only a
    prefilter (ADR-0014), as for the matrikel admins' mail.
    """
    levels = ["manager", "admin"] if managers_only else ["manager", "helper", "admin"]
    prefilter = User._privileges.contains(f'"{levels[0]}"')
    for level in levels[1:]:
        prefilter |= User._privileges.contains(f'"{level}"')

    def wanted(user):
        managed = user.is_manager or []
        helped = [] if managers_only else user.is_helper or []
        if genebank_id is None:
            return bool(user.is_admin or managed or helped)
        return genebank_id in managed + helped

    return [user for user in User.select().where(User.is_active & prefilter).order_by(User.id) if wanted(user)]


def handlers():
    """Who the queue's person pickers offer: id and name of every active admin, manager and helper."""
    workers = queue_workers(None)
    names = person_names([w.id for w in workers])
    return sorted((_person(w.id, names) for w in workers), key=lambda p: p["name"].casefold())


def create_upload(user, herd, message, stored, *, kind="upload", ref_type=None, held=None, member=None, **detail):
    """
    The item of an upload: one document per stored image ((path, sha256, quality)), and its notices; `member` is the
    person who sent it, recorded as it comes in (the report's Ärenden lists the herd's main member's). The report's
    photo (4b) is a `kontroll` item with `ref_type`; its `user` is None for the report link, which `detail` names
    (access_code_id), as an account would be named. Its notices wait for its rabbit (bind_report_photo). A photo
    `held` for a purchase (PURPOSES) or for a rabbit (HELD_RABBIT), kept in `ref_data`, is not read while it is held
    (unread) nor listed as the queue's work: its documents are off from the start, so no reading claims them.
    """
    item = InboxItem.create(
        kind=kind,
        genebank=herd.genebank_id,
        herd=herd,
        sender_user=user,
        member=member,
        message=mask_tokens(message),
        ref_type=ref_type,
        ref_data={PURPOSE: held} if held else None,
    )
    off = {"interpretation_status": "av"} if held else {}
    documents = [
        InboxDocument.create(item=item, original_path=path, mime="image/jpeg", sha256=sha256, quality=quality, **off)
        for path, sha256, quality in stored
    ]
    log_event(item, user, "inkommen", documents=len(documents), **detail)
    if not report_photo(item):
        _notify_workers(item, user)
    return item, documents


def _notify_workers(item, user):
    for worker in queue_workers(item.genebank_id):
        if user is None or worker.id != user.id:
            notify(worker, "ny_post", item)


def person_names(ids):
    """{user id: what the queue shows for the user}: the name, never the username (an e-mail address)."""
    ids = {i for i in ids if i is not None}
    users = User.select(User.id, User.fullname).where(User.id.in_(ids)) if ids else []
    return {u.id: u.fullname or f"Konto {u.id}" for u in users}


def _person(user_id, names):
    return {"id": user_id, "name": names[user_id]} if user_id is not None else None


def items_json(items):
    """The list form of items, with what each needs from other tables read in bulk."""
    ids = [item.id for item in items]
    names = person_names([i.assigned_to_id for i in items] + [i.sender_user_id for i in items])
    herd_ids = {i.herd_id for i in items if i.herd_id}
    herds = {h.id: h.herd for h in Herd.select(Herd.id, Herd.herd).where(Herd.id.in_(herd_ids))} if herd_ids else {}
    counts = {item_id: (0, 0) for item_id in ids}
    blurry = set()
    if ids:
        flagged = InboxDocument.select(InboxDocument.item, InboxDocument.quality).where(InboxDocument.item.in_(ids))
        blurry = {item_id for item_id, quality in flagged.tuples() if "suddig" in warnings(quality)}
        done = fn.COUNT(InboxDocument.done_at)
        query = (
            InboxDocument.select(InboxDocument.item, fn.COUNT(InboxDocument.id), done)
            .where(InboxDocument.item.in_(ids))
            .group_by(InboxDocument.item)
        )
        counts.update({item_id: (total, finished) for item_id, total, finished in query.tuples()})
    return [
        {
            "id": item.id,
            "kind": item.kind,
            "state": item.state,
            "genebank_id": item.genebank_id,
            "herd": herds.get(item.herd_id),
            "received_at": _iso(item.received_at),
            "state_changed_at": _iso(item.state_changed_at),
            "closed_at": _iso(item.closed_at),
            "sender": _person(item.sender_user_id, names),
            "assigned_to": _person(item.assigned_to_id, names),
            "assigned_at": _iso(item.assigned_at),
            "duplicate_of": item.duplicate_of_id,
            "stalled": item.stalled,
            "missing_proof": item.missing_proof,
            "ref_type": item.ref_type,
            "ref_id": item.ref_id,
            "sender_authenticated": item.sender_authenticated,
            "has_message": bool(item.message),
            "maybe_blurry": item.id in blurry,
            "documents": counts[item.id][0],
            "documents_done": counts[item.id][1],
        }
        for item in items
    ]


def manages(user, genebank_id):
    """A manager of the genebank, or an admin; with no genebank, any manager."""
    managed = user.is_manager or []
    return bool(user.is_admin or (genebank_id in managed if genebank_id is not None else managed))


def can_handle(user, genebank_id):
    """Who an item may be assigned to: an admin, or a manager or helper of the item's genebank."""
    if not user.is_active:
        return False
    if genebank_id is None:
        return works_in_queue(user)
    return bool(user.is_admin or genebank_id in (user.is_manager or []) + (user.is_helper or []))


def lock_item(item_id):
    """The item, locked FOR UPDATE: every change to an item, and every write through it, locks it first."""
    item = InboxItem.select().where(InboxItem.id == item_id).for_update().first()
    if item is None:
        raise InboxError(404, "Posten finns inte.")
    return item


def document_of(item, document_id):
    document = InboxDocument.get_or_none((InboxDocument.id == document_id) & (InboxDocument.item == item.id))
    if document is None:
        raise InboxError(404, "Dokumentet finns inte i posten.")
    return document


def require_worker_of(item, user):
    """Everyone in the queue sees all of it, but works only the items of their own genebanks (and those without)."""
    if not can_handle(user, item.genebank_id):
        raise InboxError(403, "Du arbetar inte i postens genbank, så du kan se den men inte arbeta med den.")


def require_handler(item, user):
    """Only the item's handler changes it or writes through it: anyone else takes it over first."""
    require_worker_of(item, user)
    if item.state in HELD_STATES and item.assigned_to_id == user.id:
        return
    if item.state in CLOSED_STATES:
        raise InboxError(409, "Posten är stängd.")
    if item.assigned_to_id is None:
        raise InboxError(409, "Ta posten först.")
    if item.assigned_to_id != user.id:
        name = person_names([item.assigned_to_id])[item.assigned_to_id]
        raise InboxError(409, f"{name} har posten. Ta över den för att arbeta med den.")
    raise InboxError(409, "Posten ligger hos genbanksansvarig.")


def _set_state(item, state):
    item.state, item.state_changed_at = state, now()
    item.closed_at = item.state_changed_at if state in CLOSED_STATES else None


def take(item, user, *, over):
    """ "Jag tar den", or with `over` "Ta över": the item becomes the user's, in "tagen"."""
    require_worker_of(item, user)
    if item.state in CLOSED_STATES:
        raise InboxError(409, "Posten är stängd.")
    previous = item.assigned_to_id
    if previous == user.id and item.state == "tagen":
        return
    if previous not in (None, user.id) and not over:
        name = person_names([previous])[previous]
        raise InboxError(409, f"{name} har posten. Ta över den för att arbeta med den.")
    item.assigned_to, item.assigned_at = user, now()
    _set_state(item, "tagen")
    item.save()
    if previous not in (None, user.id):
        log_event(item, user, "overtagen", from_user=previous)
        notify(previous, "overtagen", item)
    else:
        log_event(item, user, "tagen")


def assign(item, by, to):
    """A manager or admin gives the item to `to`; an item waiting for something keeps waiting."""
    if not manages(by, item.genebank_id):
        raise InboxError(403, "Bara genbanksansvarig och admin kan tilldela poster.")
    if item.state in CLOSED_STATES:
        raise InboxError(409, "Posten är stängd.")
    if not can_handle(to, item.genebank_id):
        raise InboxError(400, "Posten kan bara tilldelas någon som arbetar i kön för postens genbank.")
    previous = item.assigned_to_id
    item.assigned_to, item.assigned_at = to, now()
    if item.state in ("ny", "hos_genbanksansvarig"):
        _set_state(item, "tagen")
    item.save()
    log_event(item, by, "tilldelad", to_user=to.id, from_user=previous)
    if to.id != by.id:
        notify(to, "tilldelad", item)


def change_state(item, user, state, *, note=None, duplicate_of=None):
    """POST …/lage, by TRANSITIONS, and "klar" for a message or an item without documents (MESSAGE_DONE_FROM)."""
    answered = item.kind == "meddelande" or not item.documents.exists()
    if not isinstance(state, str):
        raise InboxError(400, f"state är en av {', '.join(TRANSITIONS)}.")
    allowed = MESSAGE_DONE_FROM if state == "klar" and answered else TRANSITIONS.get(state)
    if allowed is None:
        raise InboxError(400, f"state är en av {', '.join(TRANSITIONS)}.")
    if item.state not in allowed:
        raise InboxError(409, f"Posten kan inte gå från {item.state} till {state}.")
    reopened = item.state in CLOSED_STATES
    if reopened and not manages(user, item.genebank_id):
        raise InboxError(403, "Bara genbanksansvarig och admin kan öppna en stängd post.")
    if not reopened:
        require_handler(item, user)
    if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE):
        raise InboxError(400, f"Anteckningen ska vara text, högst {MAX_NOTE} tecken.")
    detail = {"from": item.state, "to": state, **({"note": mask_tokens(note.strip())} if note and note.strip() else {})}
    if state == "ofullstandig" and "note" not in detail:
        raise InboxError(400, "Skriv vad som saknas.")
    if state == "vantar_foralder":
        waited = {n for d in item.documents.where(InboxDocument.waiting_for.is_null(False)) for n in d.waiting_for}
        if not waited:
            raise InboxError(400, "Ange på dokumentet vilken förälder posten väntar på.")
        registered = _registered(waited)
        _clear_waiting(item, registered)  # a parent registered meanwhile is waited for no more
        if registered == waited:
            names = ", ".join(sorted(registered))
            raise InboxError(409, f"{names} finns redan i Stamboken. Posten väntar inte på någon förälder.", keep=True)
    if state == "klar" and item.documents.where(InboxDocument.done_at.is_null(True)).exists():
        raise InboxError(409, "Gör klart eller avfärda dokumenten först.")
    item.duplicate_of = None
    if state == "dubblett":
        other = InboxItem.get_or_none(InboxItem.id == duplicate_of) if isinstance(duplicate_of, int) else None
        if other is None or other.id == item.id:
            raise InboxError(400, "Ange den post som den här är en dubblett av.")
        item.duplicate_of, detail["duplicate_of"] = other, other.id
    _set_state(item, state)
    if reopened:
        item.assigned_to, item.assigned_at = user, now()
    if reopened and report_photo(item):  # "Öppna igen": the photo is checked again, so nothing else closes it
        InboxDocument.update(done_at=None).where(
            (InboxDocument.item == item.id) & InboxDocument.individual.is_null(False)
        ).execute()
    if state == "hos_genbanksansvarig":
        item.assigned_to, item.assigned_at = None, None
    item.save()
    event = log_event(item, user, "lage", **detail)
    if state == "ofullstandig":  # the builder reads the note from the event: no free text in the mail queue
        mail_sender(item, "inlasning.ofullstandig", {"item_id": item.id, "event_id": event.id}, created_by=user.id)
    if state == "hos_genbanksansvarig":
        for manager in queue_workers(item.genebank_id, managers_only=True):
            if manager.id != user.id:
                notify(manager, "lamnad", item)
    release_sender(item)


def release_sender(item, *, force=False):
    """
    A closed item keeps a mail sender's address only while a mail to it is on its way (inlasning.klar needs
    it); `force`: the sweep, 30 days after closing, drops it anyway. Conditional, so a reopened item keeps it.
    """
    if item.state not in CLOSED_STATES or item.sender_address is None:
        return
    query = InboxItem.update(sender_address=None).where(
        (InboxItem.id == item.id) & InboxItem.state.in_(CLOSED_STATES) & InboxItem.sender_address.is_null(False)
    )
    if not force:
        on_its_way = MailMessage.select().where(
            (MailMessage.recipient_kind == "inbox_sender")
            & (MailMessage.recipient_id == item.id)
            & MailMessage.status.in_(("queued", "sending"))
        )
        query = query.where(~fn.EXISTS(on_its_way))
    if query.execute():
        item.sender_address = None
        forget_recipient("inbox_sender", item.id)


def close_if_done(item, user):
    """The last document done or dismissed closes the item ("klar") and tells the uploader, or the mail's sender."""
    if item.state in CLOSED_STATES or item.documents.where(InboxDocument.done_at.is_null(True)).exists():
        return
    if not item.documents.exists():
        return
    previous = item.state
    _set_state(item, "klar")
    item.save()
    log_event(item, user, "lage", **{"from": previous, "to": "klar"})
    # Once per item: a reopened and closed item does not tell its sender again (a cancelled mail did not tell).
    told = MailMessage.select().where(
        (MailMessage.kind == "inlasning.klar")
        & (MailMessage.ref_type == "inbox_item")
        & (MailMessage.ref_id == item.id)
        & (MailMessage.status != "cancelled")
    )
    if not told.exists():
        if (
            item.sender_user_id is not None
            and not Notice.select().where((Notice.item == item.id) & (Notice.kind == "klar")).exists()
        ):
            notify(item.sender_user_id, "klar", item, mailed=True)
        mail_sender(item, "inlasning.klar", {"item_id": item.id})
    release_sender(item)


def retention_start(item):
    """
    What the retention months of an item count from: when it came in, or when the sender last answered on it, or
    when it was last marked "ofullstandig", whichever is latest (a reply adds photos and text to an old item).
    """
    events = item.events.select(fn.MAX(InboxEvent.at))
    answered = events.where(InboxEvent.kind == "svar").scalar()
    marked = events.where((InboxEvent.kind == "lage") & InboxEvent.detail.contains({"to": "ofullstandig"})).scalar()
    return max(when for when in (item.received_at, answered, marked) if when)


def mail_sender(item, kind, params, **options):
    """
    Queues `kind` to the item's uploader, or else to the address a mailed item came from, but only when Gmail
    authenticated it: a forged From must never make us mail its victim. An upload with no account (a link's, S7) goes
    to its `member`; a mail's `member` is matched from its From, so never that. None without any.
    """
    if item.sender_user_id is not None:
        recipient = ("user", item.sender_user_id)
    elif item.sender_address and item.sender_authenticated:
        recipient = ("inbox_sender", item.id)
    elif item.kind == "upload" and item.member_id is not None:
        recipient = ("member", item.member_id)
    else:
        return None
    options.update(ref=("inbox_item", item.id), herd=item.herd_id, genebank=item.genebank_id)
    return enqueue_mail(kind, *recipient, params, **options)


def _rects(value):
    """Rectangles as fractions of the image after rotation: [{x, y, w, h}], each inside the image."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > MAX_RECTS:
        raise InboxError(400, f"mask_rects ska vara en lista med högst {MAX_RECTS} rektanglar.")
    rects = []
    for rect in value:
        numbers = [rect.get(k) for k in "xywh"] if isinstance(rect, dict) else []
        if len(numbers) != 4 or any(isinstance(n, bool) or not isinstance(n, (int, float)) for n in numbers):
            raise InboxError(400, "En rektangel är {x, y, w, h}, bråkdelar av bilden mellan 0 och 1.")
        x, y, w, h = (float(n) for n in numbers)
        if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1.0001 or y + h > 1.0001:
            raise InboxError(400, "En rektangel måste ligga inom bilden (bråkdelar mellan 0 och 1).")
        rects.append({"x": x, "y": y, "w": w, "h": h})
    return rects


def _waiting_for(value):
    """The numbers of the parents a document waits for: not in Stamboken yet."""
    if not value:
        return None
    if not isinstance(value, list) or len(value) > 2 or any(parse_number(n) is None for n in value):
        raise InboxError(400, "Ange förälderns nummer, till exempel G1274-2512 (högst två).")
    found = [i.number for i in Individual.select(Individual.number).where(Individual.number.in_(value))]
    if found:
        raise InboxError(400, f"{', '.join(sorted(found))} finns redan i Stamboken.")
    return sorted(set(value))


DOCUMENT_FIELDS = ("doc_type", "cert_format", "rotation", "mask_rects", "waiting_for", "dismissed")
COPY_FIELDS = {"rotation", "mask_rects", "doc_type"}  # fixed once the copy is made: only …/maskning remakes it


def _rotation(value):
    if isinstance(value, bool) or value not in (0, 90, 180, 270):
        raise InboxError(400, "rotation är 0, 90, 180 eller 270 grader medurs.")
    return value


def update_document(item, document, user, changes):
    """PATCH …/dokument/<id>: what the handler says about one image."""
    require_handler(item, user)
    if not changes or set(changes) - set(DOCUMENT_FIELDS):
        raise InboxError(400, f"Ändra något av {', '.join(DOCUMENT_FIELDS)}.")
    if document.public_path and COPY_FIELDS & set(changes):
        raise InboxError(409, "Kopian är gjord. Vridning och maskning ändras med …/maskning, och typen inte alls.")
    if changes.get("doc_type", document.doc_type) != document.doc_type and (
        document.individual_id or document.herd_tracking_id
    ):
        raise InboxError(409, "Något är redan sparat från dokumentet, så typen kan inte ändras.")
    if "doc_type" in changes and changes["doc_type"] not in DOC_TYPES:
        raise InboxError(400, f"doc_type är en av {', '.join(DOC_TYPES)}.")
    if "cert_format" in changes and changes["cert_format"] not in (None, *CERT_FORMATS):
        raise InboxError(400, f"cert_format är null eller en av {', '.join(CERT_FORMATS)}.")
    if "rotation" in changes:
        _rotation(changes["rotation"])
    if "dismissed" in changes and not isinstance(changes["dismissed"], bool):
        raise InboxError(400, "dismissed är true eller false.")
    if changes.get("doc_type", document.doc_type) != document.doc_type:  # only certificates are read, never a notice's
        read = changes["doc_type"] == "intyg" and not unread(item)
        document.interpretation_status = interpreter.initial_status() if read else "av"
        document.attempts = 0
    for key in ("doc_type", "cert_format", "rotation"):
        if key in changes:
            setattr(document, key, changes[key])
    if "mask_rects" in changes:
        document.mask_rects = _rects(changes["mask_rects"])
    if "waiting_for" in changes:
        document.waiting_for = _waiting_for(changes["waiting_for"])
    if changes.get("dismissed"):
        document.done_at = document.done_at or now()
    elif changes.get("dismissed") is False and document.public_path is None and document.herd_tracking_id is None:
        document.done_at = None
    document.save()
    log_event(item, user, "dokument", document=document.id, fields=sorted(changes))
    close_if_done(item, user)


NOTICE_UNREAD = "Fotot till ett anmält köp tolkas inte."


def not_held():
    """The items that are not a held report photo (`ref_data` PURPOSE): the queue's work and a sender's own list."""
    return InboxItem.ref_data.is_null() | ~InboxItem.ref_data.has_key(PURPOSE)


def unread(item):
    """
    The model never reads the item's photos: a purchase notice's, and a report photo held (`ref_data` PURPOSE) for a
    purchase or a rabbit until the notice takes it, its sending makes it an ordinary upload (S7), or a rabbit is
    registered from it.
    """
    return item.ref_type == "kopanmalan" or bool(item.ref_data and item.ref_data.get(PURPOSE))


def reinterpret(item, document, user):
    """ "Tolka igen", after a turn: the certificate waits for the image reading again, its old proposal gone."""
    require_handler(item, user)
    if not interpreter.enabled():
        raise InboxError(409, "Bildtolkningen är avstängd.")
    if unread(item):
        raise InboxError(409, NOTICE_UNREAD)
    saved_elsewhere = document.individual_id is not None and not report_photo(item)
    if document.doc_type != "intyg" or document.done_at is not None or saved_elsewhere:
        raise InboxError(409, "Bara ett intyg som inte är sparat kan tolkas.")
    if document.original_path is None:
        raise InboxError(409, "Originalet är raderat.")
    document.interpretation_status, document.attempts = "vantar", 0
    document.interpretation = document.proposal = document.interpreter = document.interpreted_at = None
    document.save()
    log_event(item, user, "tolka_igen", document=document.id)


def make_copy(document):
    """
    The copy shown on the rabbit, made from the original: turned `rotation` degrees clockwise, its mask_rects
    (fractions of the turned image) painted black, saved as inkorg/kopia/<document id>.jpg without metadata.
    Only confirm_mask makes it, from the pair it was given, which needs the original.
    """
    if document.original_path is None:
        raise InboxError(409, "Originalet är raderat, så kopian kan inte göras om.")
    with Image.open(private_path(document.original_path)) as original:
        image = original.convert("RGB").rotate(-document.rotation, expand=True)
    width, height = image.size
    draw = ImageDraw.Draw(image)
    for r in document.mask_rects or []:
        box = (r["x"] * width, r["y"] * height, (r["x"] + r["w"]) * width, (r["y"] + r["h"]) * height)
        draw.rectangle(
            [math.floor(box[0]), math.floor(box[1]), math.ceil(box[2]) - 1, math.ceil(box[3]) - 1], fill="black"
        )
    document.public_path, _ = store_jpeg(image, "kopia", name=str(document.id))


def confirm_mask(item, document, user, rotation, rects, no_personal_data=None):
    """
    POST …/maskning: the rotation and the rectangles covering the seller and the buyer, stored together, and the copy
    made from exactly that pair goes on the rabbit; the document is done. The item's handler, while the item is open;
    a copy already made can be made again by a manager of the item's genebank or an admin at any time.
    """
    if not (document.public_path and manages(user, item.genebank_id)):
        require_handler(item, user)
    if document.doc_type != "intyg" or document.individual_id is None:
        raise InboxError(409, "Spara kaninen från intyget först.")
    rotation, rects = _rotation(rotation), _rects(rects)
    if rects is None:
        raise InboxError(400, "Ange mask_rects: rektanglarna som täcker säljaren och köparen.")
    if not rects and no_personal_data is not True:
        raise InboxError(400, 'En tom mask_rects kräver "no_personal_data": true: intyget visar ingen säljare.')
    document.rotation, document.mask_rects = rotation, rects
    document.done_at = document.done_at or now()
    make_copy(document)
    document.save()
    log_event(item, user, "kopia", document=document.id, rects=len(rects), rotation=rotation)
    close_if_done(item, user)


def remove_copy(item, document, user):
    """
    DELETE …/kopia: the masked copy comes off the rabbit (a badly masked one, with the original gone, cannot be
    made again). The caller holds the item's lock, and removes the returned file after the commit.
    """
    if not manages(user, item.genebank_id):
        raise InboxError(403, "Bara genbanksansvarig och admin kan ta bort en kopia.")
    if document.public_path is None:
        raise InboxError(409, "Dokumentet har ingen kopia.")
    path, document.public_path = document.public_path, None
    document.save()
    log_event(item, user, "kopia_borttagen", document=document.id)
    return path


def paper_certificate(individual):
    """The rabbit's paper certificate: the newest copy made from an "intyg" document for it, or None."""
    return (
        InboxDocument.select()
        .where(
            (InboxDocument.individual == individual.id)
            & (InboxDocument.doc_type == "intyg")
            & InboxDocument.public_path.is_null(False)
        )
        .order_by(InboxDocument.done_at.desc(), InboxDocument.id.desc())
        .first()
    )


def _document_status(document, report=False):
    if document.done_at:  # a report photo is done when it is checked against its rabbit (check_report_photo)
        return "klar" if document.public_path or document.herd_tracking_id or report else "avfardad"
    if document.individual_id:
        return "sparad"
    return "vantar_foralder" if document.waiting_for else "ny"


def documents_json(documents, report=False):
    numbers = {}
    individual_ids = {d.individual_id for d in documents if d.individual_id}
    if individual_ids:
        query = Individual.select(Individual.id, Individual.number).where(Individual.id.in_(individual_ids))
        numbers = dict(query.tuples())
    same = {}  # the same image (sha256) anywhere in the queue: a duplicate warning
    shas = {d.sha256 for d in documents}
    if shas:
        query = InboxDocument.select(InboxDocument.id, InboxDocument.item, InboxDocument.sha256)
        for other in query.where(InboxDocument.sha256.in_(shas)).order_by(InboxDocument.id):
            same.setdefault(other.sha256, []).append({"item_id": other.item_id, "document_id": other.id})
    return [
        {
            "id": d.id,
            "status": _document_status(d, report),
            "mime": d.mime,
            "quality": d.quality,
            "warnings": warnings(d.quality),
            "duplicates": [o for o in same.get(d.sha256, []) if o["document_id"] != d.id],
            "doc_type": d.doc_type,
            "cert_format": d.cert_format,
            "rotation": d.rotation,
            "mask_rects": d.mask_rects,
            "mask_suggestion": HANDWRITTEN_MASK if d.cert_format == "handskrivet" and not d.mask_rects else None,
            "waiting_for": d.waiting_for,
            "interpretation_status": d.interpretation_status,
            "proposal": d.proposal,
            "individual": numbers.get(d.individual_id),
            "herd_tracking_id": d.herd_tracking_id,
            "has_original": d.original_path is not None,
            "has_copy": d.public_path is not None,
            "done_at": _iso(d.done_at),
        }
        for d in documents
    ]


def report_photo(item):
    """A certificate photo from the yearly report (4b, G5): its rabbit is registered, and the reading checks it."""
    return item.kind == "kontroll" and item.ref_type == "individual"


CHECK_OUTCOMES = ("stammer", "rattat")  # "Stämmer", or "Rättat": the handler corrected the rabbit to the photo


def check_report_photo(item, document, user, outcome):
    """
    A report photo compared with its rabbit by the item's handler (4b): the document is done, with the outcome in the
    item's history, and the item closes as "klar" the way an ordinary item does once its documents are done.
    """
    if not report_photo(item):
        raise InboxError(409, "Bara ett foto från årsrapporten kontrolleras så.")
    require_handler(item, user)
    if item.state != "tagen":
        raise InboxError(409, "Posten väntar. Gör den till tagen igen för att spara.")
    if outcome not in CHECK_OUTCOMES:
        raise InboxError(400, 'outcome är "stammer" eller "rattat".')
    if item.ref_id is None or document.individual_id != item.ref_id:  # a photo checks only the rabbit it registered
        raise InboxError(409, "Fotot är inte kopplat till någon registrerad kanin. Det kan inte kontrolleras.")
    if document.done_at is not None:
        raise InboxError(409, "Dokumentet är redan klart.")
    document.done_at = now()
    document.save()
    log_event(item, user, "kontrollerad", document=document.id, outcome=outcome)
    close_if_done(item, user)


def registered_rabbit(item):
    """
    A report photo's rabbit as the member registered it, keyed as the certificate form's fields, for the queue to
    set beside the reading; None for any other item, or before the rabbit is saved.
    """
    rabbit = Individual.get_or_none(Individual.id == item.ref_id) if report_photo(item) and item.ref_id else None
    if rabbit is None:
        return None
    litter = rabbit.breeding
    mother, father = (litter.mother, litter.father) if litter else (None, None)
    return {
        "paper_number": rabbit.number,
        "paper_certificate": rabbit.certificate,
        "name": rabbit.name,
        "sex": rabbit.sex,
        "birth_date": _iso(litter.birth_date) if litter else None,
        "color": rabbit.color.name if rabbit.color_id else None,
        "mother": mother.number if mother else None,
        "father": father.number if father else None,
        "litter_size": litter.litter_size if litter else None,
        "litter_size6w": litter.litter_size6w if litter else None,
    }


def _report_year(item):
    """
    The round year of a sale proposal's item, whose status view decides it (5.9), or of the proposal a purchase
    notice matches (4a Task 5); None for any other item.
    """
    if item.ref_type == "kopanmalan":
        from utils.purchase_notice import proposal_for  # pylint: disable=import-outside-toplevel  # it imports us

        proposal = proposal_for(item)
        return proposal.report.round.report_year if proposal is not None else None
    if item.ref_type != "sale_proposal":
        return None
    return (
        YearlyReportRound.select(YearlyReportRound.report_year)
        .join(YearlyHerdReport)
        .join(SaleProposal)
        .where(SaleProposal.id == item.ref_id)
        .scalar()
    )


def item_detail(item):
    """
    GET …/<id>: the list form plus the message, the documents, the history, a sale proposal's year, a kontroll
    item's or a sent upload's structured fields (ref_data), and a report photo's rabbit.
    """
    documents = list(item.documents.order_by(InboxDocument.id))
    events = list(item.events.order_by(InboxEvent.at, InboxEvent.id))
    names = person_names([e.user_id for e in events])
    return {
        **items_json([item])[0],
        "report_year": _report_year(item),
        "ref_data": item.ref_data,
        "message": item.message,
        "sender_address": item.sender_address,
        "documents": documents_json(documents, report_photo(item)),
        "events": [
            {"id": e.id, "at": _iso(e.at), "kind": e.kind, "user": _person(e.user_id, names), "detail": e.detail}
            for e in events
        ],
        "registered": registered_rabbit(item),
    }


def open_item(item, user):
    """
    Who opened which item is logged (it may show a buyer's details), at most once an hour per user and item so
    that reloading does not fill the history; its notices are read.
    """
    since = now() - OPENED_EVERY
    seen = item.events.where((InboxEvent.kind == "oppnad") & (InboxEvent.user == user.id) & (InboxEvent.at > since))
    if not seen.exists():
        log_event(item, user, "oppnad")
    Notice.update(read_at=now()).where(
        (Notice.user == user.id) & (Notice.item == item.id) & Notice.read_at.is_null(True)
    ).execute()


def my_uploads(user):
    """ "Mina inskick": the user's own items in plain words, and the rabbits registered from them."""
    items = list(
        InboxItem.select()
        .where(InboxItem.sender_user == user.id, not_held())  # a held photo is not sent yet
        .order_by(InboxItem.received_at.desc())
    )
    listed = {row["id"]: row for row in items_json(items)}
    rabbits = {}
    if items:
        query = (
            InboxDocument.select(InboxDocument.item, Individual.number)
            .join(Individual)
            .where(InboxDocument.item.in_(list(listed)))
            .order_by(InboxDocument.id)
        )
        for item_id, number in query.tuples():
            rabbits.setdefault(item_id, []).append(number)
    Notice.update(read_at=now()).where(
        (Notice.user == user.id) & (Notice.kind == "klar") & Notice.read_at.is_null(True)
    ).execute()
    return [
        {
            "id": item.id,
            "status": PLAIN_STATES[item.state],
            "received_at": listed[item.id]["received_at"],
            "herd": listed[item.id]["herd"],
            "documents": listed[item.id]["documents"],
            "individuals": rabbits.get(item.id, []),
        }
        for item in items
    ]


def notices_json(user, *, unread_only, limit, offset):
    query = Notice.select().where(Notice.user == user.id)
    if unread_only:
        query = query.where(Notice.read_at.is_null(True))
    rows = query.order_by(Notice.created_at.desc(), Notice.id.desc()).limit(limit).offset(offset)
    return [
        {
            "id": n.id,
            "kind": n.kind,
            "text": NOTICE_TEXTS.get(n.kind, n.kind),
            "item_id": n.item_id,
            "created_at": _iso(n.created_at),
            "read_at": _iso(n.read_at),
        }
        for n in rows
    ]


def unread_count(user):
    return Notice.select().where((Notice.user == user.id) & Notice.read_at.is_null(True)).count()


def mark_read(user, ids=None):
    """The user's notices `ids`, or all of them, read now; returns how many changed."""
    query = Notice.update(read_at=now()).where((Notice.user == user.id) & Notice.read_at.is_null(True))
    if ids is not None:
        query = query.where(Notice.id.in_(ids))
    return query.execute()


def mail_enabled(user):
    setting = NoticeSetting.get_or_none(NoticeSetting.user == user.id)
    return setting is None or setting.mail_enabled


def set_mail_enabled(user, enabled):
    NoticeSetting.insert(user=user.id, mail_enabled=enabled).on_conflict(
        conflict_target=[NoticeSetting.user], update={NoticeSetting.mail_enabled: enabled}
    ).execute()


class InboxGrant:
    """
    HANDLAGGARE on a rabbit through an inbox item (individual_commands.Grant), for a genebank helper who holds
    the item: never through an item in another state or someone else's, nor one that points at another
    feature's row (ref_type: decided there), nor for a rabbit outside the genebanks the user helps in or in
    GX1/MX1. Managers and admins write with their own roles; for them the grant only leaves the trace.
    The caller locks the item first (lock order: item, litters, rabbits); `allows` re-reads it under that lock.
    """

    def __init__(self, item, user, document=None):
        self.item_id, self.user_id = item.id, user.id
        self.document_id = document.id if document is not None else None
        self.traced = 0  # the writes traced: none means the save changed nothing

    def allows(self, user, herd):
        """May `user` write, as handler, to a rabbit in `herd` (also a newborn's herd)?"""
        item = lock_item(self.item_id)
        return (
            user.id == self.user_id
            and item.state == "tagen"
            and item.assigned_to_id == user.id
            and item.ref_type is None
            and herd.genebank_id in (user.is_helper or [])
            and herd.herd not in OUTSIDE_GENEBANK_HERDS
        )

    def roles_in(self, user, herd):
        return frozenset({Role.HANDLAGGARE}) if self.allows(user, herd) else frozenset()

    def roles(self, user, individual):
        return self.roles_in(user, individual.current_herd)

    def trace(self, operation_id):
        """ "Inlagd från foto av": the write's operation id, its handler and the document."""
        InboxOperation.create(operation_id=operation_id, user=self.user_id, document=self.document_id)
        self.traced += 1

    def record(self, ctx):
        for row in ctx.log_rows:
            self.trace(row["operation_id"])


def require_saving(item, document, user):
    """Writes on rabbits through the item: its handler, in "tagen", and never an item that points elsewhere."""
    if item.ref_type is not None:
        raise InboxError(409, f"Posten gäller {item.ref_type} {item.ref_id} och avgörs där, inte i kön.")
    require_handler(item, user)
    if item.state != "tagen":
        raise InboxError(409, "Posten väntar. Gör den till tagen igen för att spara.")
    if document.done_at is not None:
        raise InboxError(409, "Dokumentet är redan klart.")


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


def saved(item, document, user, individual, action):
    """The rabbit a certificate document registered or certified; its seller is the holder of the rabbit's herd."""
    document.individual = individual
    document.seller_member = herd_holder(individual.current_herd.id) or document.seller_member
    document.save()
    log_event(item, user, "sparad", document=document.id, action=action, individual=individual.number)


def bind_report_photo(item, document, user, individual):
    """
    A report photo bound to the rabbit registered from it (4b, G5), under the item's lock and in the registration's
    transaction: a reading already made is set beside the rabbit again from what was read (no new reading), and only
    now do the queue's workers hear of it; a photo never bound may be scrapped, which asks for a new upload.
    """
    InboxItem.update(ref_id=individual.id, ref_data=None).where(InboxItem.id == item.id).execute()
    item.ref_id, item.ref_data = individual.id, None  # held for a purchase no longer: a rabbit's photo is read
    saved(item, document, user, individual, "ny_kanin")
    if document.interpretation_status == "av":  # uploaded for a purchase notice (unread): a rabbit's photo is read (G5)
        document.interpretation_status = interpreter.initial_status()
        document.save()
    if document.interpretation_status == "klar" and document.interpretation is not None:
        document.proposal = build_proposal(document.interpretation, item.genebank_id, item.herd_id, individual)
        document.save()
    _notify_workers(item, user)


def bound_rabbit(document):
    """The rabbit a document is bound to by its first save: the one registered or certified from it, or sold."""
    if document.individual_id is not None:
        return document.individual_id
    if document.herd_tracking_id is not None:
        return HerdTracking.get_by_id(document.herd_tracking_id).individual_id
    return None


def require_same_rabbit(document, individual=None):
    """
    One document, one rabbit: whatever is saved through a document concerns the rabbit of its first save (a new
    rabbit, `individual` None, never one already bound), and a document carries at most one sale.
    """
    bound = bound_rabbit(document)
    if bound is not None and (individual is None or individual.id != bound):
        number = Individual.get_by_id(bound).number
        raise InboxError(409, f"Dokumentet gäller {number}. Det som sparas genom det måste gälla samma kanin.")


def proven_sale(item, document, individual, herd, date):  # pylint: disable=unused-argument  # the item: kept
    """
    The sale a proof (bevis) shows when it is already registered, from another document of the item or anywhere
    else (the sell dialog): an active move of the same rabbit to the same herd on the same date. The proof is then
    linked to it rather than registering it again, and asks for no buyer: one came with the sale.
    """
    if document.doc_type != "bevis":
        return None
    return (
        HerdTracking.select()
        .join(Herd, on=(HerdTracking.herd == Herd.id))
        .where(
            (HerdTracking.individual == individual.id)
            & HerdTracking.kind.in_(("TRANSFER", "CORRECTION"))
            & (Herd.herd == herd)
            & (HerdTracking.herd_tracking_date == date)
            & HerdTracking.voided_at.is_null(True)
        )
        .first()
    )


def transferred(item, document, user, individual, row, *, linked=False):
    """
    A sale registered from a document (or, `linked`, a proof of one registered before): the sale is the
    document's (herd_tracking_id) whatever its type, and a proof (bevis) is done with it. The item lacks a proof
    ("bevis saknas") while a sale from another type of document has no proof on the item. The document shows the
    sale's seller and, for a sale to a member, its buyer.
    """
    document.seller_member = herd_holder(row.from_herd_id or individual.origin_herd_id) or document.seller_member
    if row.herd.herd not in OUTSIDE_GENEBANK_HERDS:
        document.buyer_member = herd_holder(row.herd_id) or document.buyer_member
    proof = document.doc_type == "bevis"
    document.herd_tracking_id = row.id
    if proof:
        document.individual, document.done_at = individual, now()
    document.save()
    proven = item.documents.select(InboxDocument.herd_tracking_id).where(
        (InboxDocument.doc_type == "bevis") & InboxDocument.herd_tracking_id.is_null(False)
    )
    item.missing_proof = item.documents.where(
        (InboxDocument.doc_type != "bevis")
        & InboxDocument.herd_tracking_id.is_null(False)
        & InboxDocument.herd_tracking_id.not_in(proven)
    ).exists()
    item.save()
    detail = {"document": document.id, "individual": individual.number, "herd": row.herd.herd}
    log_event(item, user, "sparad", action="bevis" if linked else "overlatelse", missing_proof=not proof, **detail)
    close_if_done(item, user)


def _registered(numbers):
    """The numbers among `numbers` that are in Stamboken."""
    found = Individual.select(Individual.number).where(Individual.number.in_(list(numbers))) if numbers else []
    return {number for (number,) in found.tuples()} if numbers else set()


def _clear_waiting(item, numbers):
    """`numbers` leave the waiting_for of the item's documents; returns those that were waited for."""
    cleared = set()
    for document in item.documents.where(InboxDocument.waiting_for.is_null(False)):
        kept = [n for n in document.waiting_for if n not in numbers]
        if len(kept) < len(document.waiting_for):
            cleared |= set(document.waiting_for) - set(kept)
            document.waiting_for = kept or None
            document.save()
    return cleared


def _wake(item, numbers):
    """
    Parents registered: out of the open item's waiting_for, each logged; once it waits for no one its handler is
    told (or its genebank's managers when it has none), and an item that was waiting goes back to "tagen".
    """
    cleared = _clear_waiting(item, numbers)
    for number in sorted(cleared):
        log_event(item, None, "foralder_inlagd", individual=number)
    if not cleared or item.documents.where(InboxDocument.waiting_for.is_null(False)).exists():
        return bool(cleared)
    if item.state == "vantar_foralder":
        _set_state(item, "tagen")
        item.save()
    handlers = [item.assigned_to_id] if item.assigned_to_id else queue_workers(item.genebank_id, managers_only=True)
    for handler in handlers:
        notify(handler, "foralder_inlagd", item)
    return True


def parent_registered(number):
    """
    A rabbit was created (Individual.save, in its transaction, wherever it was created): every open item waiting
    for it is woken (_wake). The items are locked after the rabbit's own locks and after the item a save through
    the queue holds, the reverse of the queue's order, so they are locked SKIP LOCKED: this never waits, and an
    item someone else holds (assigning a herd's items, say) is left to wake_waiting.
    """
    waiting = InboxDocument.select(InboxDocument.item).where(InboxDocument.waiting_for.contains([number]))
    items = list(
        InboxItem.select()
        .where(InboxItem.state.in_(OPEN_STATES) & InboxItem.id.in_(waiting))
        .order_by(InboxItem.id)
        .for_update("FOR UPDATE SKIP LOCKED")
    )
    for item in items:
        _wake(item, {number})


def wake_waiting():
    """
    The hourly sweep: wakes the open items still waiting for a rabbit that is in Stamboken (one parent_registered
    skipped as locked, or missed). One short transaction per item, locked in the queue's order. Returns how many.
    """
    rows = (
        InboxDocument.select(InboxDocument.item, InboxDocument.waiting_for)
        .join(InboxItem)
        .where(InboxDocument.waiting_for.is_null(False) & InboxItem.state.in_(OPEN_STATES))
        .tuples()
    )
    waited = {}
    for item_id, numbers in rows:
        waited.setdefault(item_id, set()).update(numbers)
    registered = _registered(set().union(*waited.values()))
    woken = 0
    for item_id in sorted(i for i, numbers in waited.items() if numbers & registered):
        with DB_PROXY.atomic():
            item = InboxItem.select().where(InboxItem.id == item_id).for_update().first()
            if item is not None and item.state in OPEN_STATES and _wake(item, registered):
                woken += 1
    return woken


@mail_kind("inlasning.klar", priority=1, category="T")
def _item_done_mail(params):
    """To the uploader when the item is "klar"; stopped if it was reopened before the mail went."""
    item = InboxItem.get_or_none(InboxItem.id == params["item_id"])
    if item is None or item.state != "klar":
        return None
    query = (
        InboxDocument.select(Individual.number)
        .join(Individual)
        .where(InboxDocument.item == item.id)
        .order_by(InboxDocument.id)
    )
    numbers = list(dict.fromkeys(number for (number,) in query.tuples()))
    return {"item_id": item.id, "numbers": numbers, "account": item.sender_user_id is not None}


@mail_kind("inlasning.paminnelse", priority=1, category="T")
@mail_kind("inlasning.ofullstandig", priority=1, category="T")
def _incomplete_mail(params):
    """What is missing, in the handler's note read when the mail goes (none left once purged); none once moved on."""
    item = InboxItem.get_or_none(InboxItem.id == params["item_id"])
    if item is None or item.state != "ofullstandig":
        return None
    event = InboxEvent.get_or_none((InboxEvent.id == params["event_id"]) & (InboxEvent.item == item.id))
    note = (event.detail or {}).get("note") if event else None
    return {
        "item_id": item.id,
        "note": note,
        "deadline": f"{retention_start(item) + months(INCOMPLETE_MONTHS):%Y-%m-%d}",
        "account": item.sender_user_id is not None,
    }


@mail_kind("notis.sammandrag", priority=1, category="N")
def _digest_mail(params):
    """The user's unread notices when the mail goes; none left (all read since), no mail."""
    notices = (
        Notice.select()
        .where((Notice.user == params["user_id"]) & Notice.read_at.is_null(True) & (Notice.kind != "klar"))
        .order_by(Notice.created_at, Notice.id)
    )
    rows = [{"text": NOTICE_TEXTS.get(n.kind, n.kind), "item_id": n.item_id} for n in notices]
    return {"notices": rows} if rows else None


def queue_digests(at=None):
    """
    The daily notis.sammandrag (07:00): one mail to each active user with unread notices that no digest has
    covered, unless they turned the mail off. The notices are marked as mailed in the same transaction as the
    mail is queued. "Klar" notices never come here: they have inlasning.klar. Returns the number of mails.
    """
    at = at or now()
    with DB_PROXY.atomic():
        disabled = {s.user_id for s in NoticeSetting.select().where(~NoticeSetting.mail_enabled)}
        pending = (
            Notice.select(Notice.user)
            .join(User)
            .where(Notice.read_at.is_null(True) & Notice.mailed_at.is_null(True) & User.is_active)
            .distinct()
        )
        queued = 0
        for user_id in sorted({user_id for (user_id,) in pending.tuples()} - disabled):
            key = f"notis.sammandrag:{user_id}:{at:%Y-%m-%d}"
            if enqueue_mail("notis.sammandrag", "user", user_id, {"user_id": user_id}, dedupe_key=key) is None:
                continue  # one digest a day: the rest waits for tomorrow's
            Notice.update(mailed_at=at).where(
                (Notice.user == user_id) & Notice.read_at.is_null(True) & Notice.mailed_at.is_null(True)
            ).execute()
            queued += 1
    return queued
