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
    InboxDocument,
    InboxEvent,
    InboxItem,
    InboxOperation,
    Individual,
    MailMessage,
    Notice,
    NoticeSetting,
    User,
)
from utils.individual_number_v2 import parse_number
from utils.individual_policy import Role
from utils.mail import enqueue_mail, forget_recipient, mail_kind

OPEN_STATES = ("ny", "tagen", "vantar_uppfodare", "vantar_foralder", "hos_genbanksansvarig", "ofullstandig")
CLOSED_STATES = ("klar", "dubblett", "skrap")
HELD_STATES = ("tagen", "vantar_uppfodare", "vantar_foralder", "ofullstandig")  # the item has a handler
# POST …/lage: the target state and the states the item's handler may move it from. A closed item is reopened
# ("tagen") by a manager of its genebank or an admin, who becomes its handler. The other states are reached
# otherwise: "ny" when the item comes in, "tagen" also by taking or assigning, "klar" when its last document is
# done or dismissed, "vantar_uppfodare" by the question to the breeder (utils/inbox_gmail.py, back with the answer).
TRANSITIONS = {
    "tagen": ("vantar_foralder", "ofullstandig", *CLOSED_STATES),
    "vantar_foralder": ("tagen",),
    "hos_genbanksansvarig": ("tagen",),
    "ofullstandig": ("tagen",),
    "dubblett": HELD_STATES,
    "skrap": HELD_STATES,
}
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
}
DOC_TYPES = ("intyg", "bevis", "arsblankett", "annat")
CERT_FORMATS = ("handskrivet", "datorskrivet", "v1_pdf", "intyg_b", "digitalt_v2")
OPENED_EVERY = timedelta(hours=1)
INCOMPLETE_MONTHS = 12  # an item left "ofullstandig" is deleted this long after it came in (utils/inbox_purge.py)
MAX_NOTE = 2000
MAX_RECTS = 20
# The masking a handwritten certificate (format 1) is offered: its lower third, where seller and buyer write.
HANDWRITTEN_MASK = [{"x": 0.0, "y": 0.6667, "w": 1.0, "h": 0.3333}]


class InboxError(Exception):
    """A refusal with its HTTP status, turned into a problem response by the blueprint."""

    TITLES = {400: "Ogiltig begäran", 403: "Åtkomst nekad", 404: "Hittades inte", 409: "Konflikt"}

    def __init__(self, status, detail):
        super().__init__(detail)
        self.status, self.title, self.detail = status, self.TITLES[status], detail


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
    edges = edges.crop((1, 1, edges.width - 1, edges.height - 1))  # the filter leaves the border unfiltered
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


def store_jpeg(image, folder, name=None):
    """
    Saves `image` as a JPEG without metadata (EXIF, GPS, XMP) as inkorg/<folder>/<name>.jpg under
    PRIVATE_UPLOAD_FOLDER; returns (relative path, sha256). A new name is random; a given one is replaced.
    """
    image.info = {}  # nothing of the uploaded file's metadata may reach the saved one
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=JPEG_QUALITY)
    data = buffer.getvalue()
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
    InboxEvent.create(item=item, user=user, kind=kind, detail=detail or None)


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


def create_upload(user, herd, message, stored):
    """The item of an upload: one document per stored image ((path, sha256, quality)), and its notices."""
    item = InboxItem.create(kind="upload", genebank=herd.genebank_id, herd=herd, sender_user=user, message=message)
    documents = [
        InboxDocument.create(item=item, original_path=path, mime="image/jpeg", sha256=sha256, quality=quality)
        for path, sha256, quality in stored
    ]
    log_event(item, user, "inkommen", documents=len(documents))
    for worker in queue_workers(item.genebank_id):
        if worker.id != user.id:
            notify(worker, "ny_post", item)
    return item, documents


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


def require_handler(item, user):
    """Only the item's handler changes it or writes through it: anyone else takes it over first."""
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
    """POST …/lage, by TRANSITIONS."""
    if state not in TRANSITIONS:
        raise InboxError(400, f"state är en av {', '.join(TRANSITIONS)}.")
    if item.state not in TRANSITIONS[state]:
        raise InboxError(409, f"Posten kan inte gå från {item.state} till {state}.")
    reopened = item.state in CLOSED_STATES
    if reopened and not manages(user, item.genebank_id):
        raise InboxError(403, "Bara genbanksansvarig och admin kan öppna en stängd post.")
    if not reopened:
        require_handler(item, user)
    if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE):
        raise InboxError(400, f"Anteckningen ska vara text, högst {MAX_NOTE} tecken.")
    detail = {"from": item.state, "to": state, **({"note": note.strip()} if note and note.strip() else {})}
    if state == "ofullstandig" and "note" not in detail:
        raise InboxError(400, "Skriv vad som saknas.")
    if state == "vantar_foralder" and not item.documents.where(InboxDocument.waiting_for.is_null(False)).exists():
        raise InboxError(400, "Ange på dokumentet vilken förälder posten väntar på.")
    item.duplicate_of = None
    if state == "dubblett":
        other = InboxItem.get_or_none(InboxItem.id == duplicate_of) if isinstance(duplicate_of, int) else None
        if other is None or other.id == item.id:
            raise InboxError(400, "Ange den post som den här är en dubblett av.")
        item.duplicate_of, detail["duplicate_of"] = other, other.id
    _set_state(item, state)
    if reopened:
        item.assigned_to, item.assigned_at = user, now()
    if state == "hos_genbanksansvarig":
        item.assigned_to, item.assigned_at = None, None
    item.save()
    log_event(item, user, "lage", **detail)
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
    if item.sender_user_id is not None:
        notify(item.sender_user_id, "klar", item, mailed=True)
        enqueue_mail(
            "inlasning.klar",
            "user",
            item.sender_user_id,
            {"item_id": item.id},
            ref=("inbox_item", item.id),
            herd=item.herd_id,
            genebank=item.genebank_id,
        )
    elif item.sender_address:  # a mailed item's sender gets the same news, at the address it came from
        enqueue_mail(
            "inlasning.klar",
            "inbox_sender",
            item.id,
            {"item_id": item.id},
            ref=("inbox_item", item.id),
            herd=item.herd_id,
            genebank=item.genebank_id,
        )
    release_sender(item)


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


def update_document(item, document, user, changes):
    """PATCH …/dokument/<id>: what the handler says about one image."""
    require_handler(item, user)
    if not changes or set(changes) - set(DOCUMENT_FIELDS):
        raise InboxError(400, f"Ändra något av {', '.join(DOCUMENT_FIELDS)}.")
    if "doc_type" in changes and changes["doc_type"] not in DOC_TYPES:
        raise InboxError(400, f"doc_type är en av {', '.join(DOC_TYPES)}.")
    if "cert_format" in changes and changes["cert_format"] not in (None, *CERT_FORMATS):
        raise InboxError(400, f"cert_format är null eller en av {', '.join(CERT_FORMATS)}.")
    if "rotation" in changes and changes["rotation"] not in (0, 90, 180, 270):
        raise InboxError(400, "rotation är 0, 90, 180 eller 270 grader medurs.")
    if "dismissed" in changes and not isinstance(changes["dismissed"], bool):
        raise InboxError(400, "dismissed är true eller false.")
    if changes.get("doc_type", document.doc_type) != document.doc_type:  # only certificates are read
        document.interpretation_status = interpreter.initial_status() if changes["doc_type"] == "intyg" else "av"
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
    if document.public_path and {"rotation", "mask_rects"} & set(changes):
        make_copy(document)
    document.save()
    log_event(item, user, "dokument", document=document.id, fields=sorted(changes))
    close_if_done(item, user)


def reinterpret(item, document, user):
    """ "Tolka igen", after a turn: the certificate waits for the image reading again, its old proposal gone."""
    require_handler(item, user)
    if not interpreter.enabled():
        raise InboxError(409, "Bildtolkningen är avstängd.")
    if document.doc_type != "intyg" or document.done_at is not None or document.individual_id is not None:
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
    Made again whenever the rectangles or the rotation change, which needs the original.
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


def confirm_mask(item, document, user, rects=None):
    """The handler confirms what covers the seller and the buyer: the copy goes on the rabbit, the document is done."""
    require_handler(item, user)
    if document.doc_type != "intyg" or document.individual_id is None:
        raise InboxError(409, "Spara kaninen från intyget först.")
    if rects is not None:
        document.mask_rects = _rects(rects)
    if document.mask_rects is None:
        raise InboxError(400, "Ange mask_rects, eller en tom lista om intyget inte visar någon säljare eller köpare.")
    document.done_at = document.done_at or now()
    make_copy(document)
    document.save()
    log_event(item, user, "kopia", document=document.id, rects=len(document.mask_rects))
    close_if_done(item, user)


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


def _document_status(document):
    if document.done_at:
        return "klar" if document.public_path or document.herd_tracking_id else "avfardad"
    if document.individual_id:
        return "sparad"
    return "vantar_foralder" if document.waiting_for else "ny"


def documents_json(documents):
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
            "status": _document_status(d),
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


def item_detail(item):
    """GET …/<id>: the list form plus the message, the documents and the history."""
    documents = list(item.documents.order_by(InboxDocument.id))
    events = list(item.events.order_by(InboxEvent.at, InboxEvent.id))
    names = person_names([e.user_id for e in events])
    return {
        **items_json([item])[0],
        "message": item.message,
        "sender_address": item.sender_address,
        "documents": documents_json(documents),
        "events": [
            {"id": e.id, "at": _iso(e.at), "kind": e.kind, "user": _person(e.user_id, names), "detail": e.detail}
            for e in events
        ],
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
    items = list(InboxItem.select().where(InboxItem.sender_user == user.id).order_by(InboxItem.received_at.desc()))
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

    def roles(self, user, individual):
        return frozenset({Role.HANDLAGGARE}) if self.allows(user, individual.current_herd) else frozenset()

    def trace(self, operation_id):
        """ "Inlagd från foto av": the write's operation id, its handler and the document."""
        InboxOperation.create(operation_id=operation_id, user=self.user_id, document=self.document_id)

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


def saved(item, document, user, individual, action):
    """The rabbit a certificate document registered or certified."""
    document.individual = individual
    document.save()
    log_event(item, user, "sparad", document=document.id, action=action, individual=individual.number)


def transferred(item, document, user, individual, row):
    """A sale registered from a document: a proof (bevis) is done with it; anything else leaves the proof missing."""
    proof = document.doc_type == "bevis"
    if proof:
        document.individual, document.herd_tracking_id, document.done_at = individual, row.id, now()
        document.save()
    else:
        item.missing_proof = True
        item.save()
    detail = {"document": document.id, "individual": individual.number, "herd": row.herd.herd}
    log_event(item, user, "sparad", action="overlatelse", missing_proof=not proof, **detail)
    close_if_done(item, user)


def parent_registered(number):
    """
    A rabbit was created (Individual.save, in its transaction, wherever it was created): its number leaves the
    waiting_for of the items waiting for it, and an item no longer waiting for anything goes back to its
    handler ("tagen"). Only items in "vantar_foralder" are locked here, after the rabbit's own locks: no save
    holds such an item (a save needs "tagen"), so the reversed lock order cannot deadlock with one.
    """
    waiting = InboxDocument.select(InboxDocument.item).where(InboxDocument.waiting_for.contains([number]))
    items = list(
        InboxItem.select()
        .where((InboxItem.state == "vantar_foralder") & InboxItem.id.in_(waiting))
        .order_by(InboxItem.id)
        .for_update()
    )
    for item in items:
        for document in item.documents.where(InboxDocument.waiting_for.contains([number])):
            document.waiting_for = [n for n in document.waiting_for if n != number] or None
            document.save()
        if item.documents.where(InboxDocument.waiting_for.is_null(False)).exists():
            continue
        _set_state(item, "tagen")
        item.save()
        log_event(item, None, "foralder_inlagd", individual=number)
        handlers = [item.assigned_to_id] if item.assigned_to_id else queue_workers(item.genebank_id, managers_only=True)
        for handler in handlers:
            notify(handler, "foralder_inlagd", item)


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
