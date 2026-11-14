"""
The intake queue (inläsningskön, docs/inkorg.md): items of photos sent in for a human to register, their states
and handlers, the notices about them, and the masked copy of a certificate shown on the rabbit.

The files live under PRIVATE_UPLOAD_FOLDER, never under UPLOAD_FOLDER, which nginx serves without login.
"""

import hashlib
import io
import os
import uuid
from datetime import datetime, timezone

from peewee import fn
from PIL import ImageFilter, ImageStat

import utils.settings as settings
from utils.database import Herd, InboxDocument, InboxEvent, InboxItem, Notice, User

OPEN_STATES = ("ny", "tagen", "vantar_uppfodare", "vantar_foralder", "hos_genbanksansvarig", "ofullstandig")
CLOSED_STATES = ("klar", "dubblett", "skrap")

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
    if ids:
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
            "documents": counts[item.id][0],
            "documents_done": counts[item.id][1],
        }
        for item in items
    ]
