"""
The intake queue (inläsningskön): uploads, the queue, its notices and the paper certificate on a rabbit.
docs/inkorg.md is the API; the rules live in utils/inbox.py (ADR-0007).
"""

import os
import threading
from functools import wraps

import pillow_heif
import pypdfium2
import utils.inbox as inbox
from extensions import limiter
from flask import Blueprint, jsonify, request
from flask_login import current_user
from peewee import fn
from PIL import Image, ImageOps
from utils.database import DB_PROXY, Herd, InboxItem, User

from .common import json_login_required, problem
from .uploads import MAX_FILE_SIZE, MAX_PIXELS, _too_many_pixels, _validate_magic_bytes, _webp_pixels

pillow_heif.register_heif_opener()

inbox_bp = Blueprint("inbox", __name__, url_prefix="/api/v2")

MAX_FILES = 10  # files per upload, and images once each PDF is split into pages
MAX_MESSAGE = 2000
PDF_DPI = 200
PDF_MAX_SIDE = 3000  # pixels; bounds the memory a page takes, whatever size the PDF says it is
_HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs", b"mif1", b"msf1"}
_PDFIUM = threading.Lock()  # pdfium is not thread-safe, and gunicorn runs threads


class _Refused(Exception):
    def __init__(self, response):
        super().__init__()
        self.response = response


def _kind(file):
    """jpeg, png, webp, heic or pdf, from the magic bytes; None for anything else."""
    kind = _validate_magic_bytes(file)
    if kind:
        return kind
    head = file.read(12)
    file.seek(0)
    if head[4:8] == b"ftyp" and head[8:12] in _HEIC_BRANDS:
        return "heic"
    if head[:5] == b"%PDF-":
        return "pdf"
    return None


def _pdf_pages(data, room):
    """Each page as an RGB image, at PDF_DPI but at most PDF_MAX_SIDE pixels a side."""
    with _PDFIUM:
        pdf = pypdfium2.PdfDocument(data)
        try:
            if len(pdf) > room:
                raise _Refused(_too_many_images())
            pages = []
            for page in pdf:
                width, height = page.get_size()
                scale = min(PDF_DPI / 72, PDF_MAX_SIDE / max(width, height, 1))
                pages.append(page.render(scale=scale).to_pil().convert("RGB"))
                page.close()
            return pages
        finally:
            pdf.close()


def _too_many_images():
    return problem(400, "Bad Request", f"Högst {MAX_FILES} bilder per inskick. En PDF räknas sida för sida.")


def _images(file, room):
    """The file's images, RGB and turned upright as the phone saw them; a PDF page by page."""
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        raise _Refused(problem(413, "Payload Too Large", "Filen är för stor. Max 10 MB."))
    kind = _kind(file)
    if kind is None:
        raise _Refused(problem(415, "Unsupported Media Type", "Otillåten filtyp. Bara JPEG, PNG, WebP, HEIC och PDF."))
    try:
        if kind == "pdf":
            return _pdf_pages(file.read(), room)
        if room < 1:
            raise _Refused(_too_many_images())
        if kind == "webp" and _webp_pixels(file.read(30)) > MAX_PIXELS:
            raise _Refused(_too_many_pixels())
        file.seek(0)
        with Image.open(file) as image:
            if image.width * image.height > MAX_PIXELS:  # Image.open reads only the header
                raise _Refused(_too_many_pixels())
            image.load()
            return [ImageOps.exif_transpose(image).convert("RGB")]
    except _Refused:
        raise
    except Image.DecompressionBombError:
        raise _Refused(_too_many_pixels()) from None
    except Exception:
        raise _Refused(problem(422, "Unprocessable Content", "Filen kunde inte läsas. Den kan vara skadad.")) from None


# [Next.js] Upload photos of certificates from the phone (docs/inkorg.md).
@inbox_bp.route("/inkorg/upload", methods=["POST"])
@json_login_required
@limiter.limit("20 per hour", key_func=lambda: str(current_user.id))
def upload():
    # Up to MAX_FILES files of MAX_FILE_SIZE each, not the app-wide MAX_CONTENT_LENGTH; set before the body is read.
    request.max_content_length = MAX_FILES * MAX_FILE_SIZE + 1024 * 1024
    herd = Herd.get_or_none(Herd.herd == request.form.get("herd"))
    if herd is None:
        return problem(400, "Bad Request", "Välj besättning.")
    if not (inbox.works_in_queue(current_user) or herd.id in current_user.effective_herd_ids()):
        return problem(403, "Forbidden", "Du kan bara skicka in för dina egna besättningar.")
    message = (request.form.get("message") or "").strip() or None
    if message and len(message) > MAX_MESSAGE:
        return problem(400, "Bad Request", f"Meddelandet får vara högst {MAX_MESSAGE} tecken.")
    files = [f for f in request.files.getlist("files") if f and f.filename]
    if not files:
        return problem(400, "Bad Request", "Ingen fil bifogad.")
    if len(files) > MAX_FILES:
        return _too_many_images()
    dry_run = request.form.get("dry_run") in ("1", "true")

    results, stored = [], []
    try:
        for index, file in enumerate(files):
            images = _images(file, MAX_FILES - len(results))
            for page, image in enumerate(images, 1):
                quality = inbox.measure(image)
                results.append(
                    {
                        "file": index,
                        "page": page if len(images) > 1 else None,
                        "quality": quality,
                        "warnings": inbox.warnings(quality),
                    }
                )
                if not dry_run:
                    stored.append((*inbox.store_jpeg(image, "original"), quality))
        if dry_run:
            return jsonify({"documents": results}), 200
        with DB_PROXY.atomic():
            item, documents = inbox.create_upload(current_user, herd, message, stored)
    except _Refused as refused:
        inbox.remove_files(path for path, _, _ in stored)
        return refused.response
    except BaseException:
        inbox.remove_files(path for path, _, _ in stored)
        raise
    for result, document in zip(results, documents, strict=True):
        result["id"] = document.id
    return jsonify({"item": inbox.items_json([item])[0], "documents": results}), 201


def _queue_worker(f):
    """After json_login_required: the queue is for admins, genebank managers and helpers, the whole of it."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if not inbox.works_in_queue(current_user):
            return problem(403, "Åtkomst nekad", "Bara admin, genbanksansvarig och genbankshjälpare arbetar i kön.")
        return f(*args, **kwargs)

    return decorated


def _locked(item_id, action):
    """action(item) on the item locked in one transaction; a refusal rolls it back and becomes a problem."""
    try:
        with DB_PROXY.atomic():
            return action(inbox.lock_item(item_id))
    except inbox.InboxError as exc:
        return problem(exc.status, exc.title, exc.detail)


def _then_item(change):
    """An action that runs change(item) and answers with the item's list form."""

    def action(item):
        change(item)
        return jsonify(inbox.items_json([item])[0])

    return action


def _body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _user_in_body():
    user_id = _body().get("user_id")
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        return None
    return User.get_or_none(User.id == user_id)


# [Next.js] The queue: filters, sorted oldest first, with the count per state.
@inbox_bp.route("/inkorg", methods=["GET"])
@json_login_required
@_queue_worker
def queue():
    args = request.args
    query = InboxItem.select()
    if args.get("mine") in ("1", "true"):
        query = query.where(InboxItem.assigned_to == current_user.id)
    if args.get("untaken") in ("1", "true"):
        query = query.where(InboxItem.assigned_to.is_null(True))
    for name, column in (("assigned_to", InboxItem.assigned_to), ("genebank_id", InboxItem.genebank)):
        if name in args:
            value = args.get(name, type=int)
            if value is None:
                return problem(400, "Bad Request", f"{name} ska vara ett heltal.")
            query = query.where(column == value)
    if args.get("herd"):
        query = query.where(InboxItem.herd.in_(Herd.select(Herd.id).where(Herd.herd == args["herd"])))
    if args.get("kind"):
        query = query.where(InboxItem.kind == args["kind"])
    counts = dict(query.select(InboxItem.state, fn.COUNT(InboxItem.id)).group_by(InboxItem.state).tuples())
    if args.get("state") != "alla":
        states = args["state"].split(",") if args.get("state") else list(inbox.OPEN_STATES)
        if set(states) - set(inbox.OPEN_STATES + inbox.CLOSED_STATES):
            return problem(400, "Bad Request", "Okänt läge.")
        query = query.where(InboxItem.state.in_(states))
    limit = min(max(args.get("limit", 50, type=int) or 50, 1), 200)
    offset = max(args.get("offset", 0, type=int) or 0, 0)
    items = list(query.order_by(InboxItem.received_at, InboxItem.id).limit(limit).offset(offset))
    return jsonify({"items": inbox.items_json(items), "total": query.count(), "counts": counts})


# [Next.js] One item with its documents and history; opening it is logged and reads its notices.
@inbox_bp.route("/inkorg/<int:item_id>", methods=["GET"])
@json_login_required
@_queue_worker
def item_detail(item_id):
    item = InboxItem.get_or_none(InboxItem.id == item_id)
    if item is None:
        return problem(404, "Hittades inte", "Posten finns inte.")
    with DB_PROXY.atomic():
        inbox.open_item(item, current_user)
    return jsonify(inbox.item_detail(item))


@inbox_bp.route("/inkorg/<int:item_id>/ta", methods=["POST"])
@json_login_required
@_queue_worker
def take(item_id):
    return _locked(item_id, _then_item(lambda item: inbox.take(item, current_user, over=False)))


@inbox_bp.route("/inkorg/<int:item_id>/ta-over", methods=["POST"])
@json_login_required
@_queue_worker
def take_over(item_id):
    return _locked(item_id, _then_item(lambda item: inbox.take(item, current_user, over=True)))


@inbox_bp.route("/inkorg/<int:item_id>/tilldela", methods=["POST"])
@json_login_required
@_queue_worker
def assign(item_id):
    to = _user_in_body()
    if to is None:
        return problem(400, "Bad Request", "Ange user_id för den som ska få posten.")
    return _locked(item_id, _then_item(lambda item: inbox.assign(item, current_user, to)))


# [Next.js] Every open item of a herd to one handler.
@inbox_bp.route("/inkorg/tilldela", methods=["POST"])
@json_login_required
@_queue_worker
def assign_herd():
    to, herd = _user_in_body(), Herd.get_or_none(Herd.herd == _body().get("herd"))
    if to is None or herd is None:
        return problem(400, "Bad Request", "Ange herd (besättningsnummer) och user_id.")
    try:
        with DB_PROXY.atomic():
            items = list(
                InboxItem.select()
                .where((InboxItem.herd == herd.id) & InboxItem.state.in_(inbox.OPEN_STATES))
                .order_by(InboxItem.id)
                .for_update()
            )
            for item in items:
                inbox.assign(item, current_user, to)
    except inbox.InboxError as exc:
        return problem(exc.status, exc.title, exc.detail)
    return jsonify({"assigned": [item.id for item in items]})


@inbox_bp.route("/inkorg/<int:item_id>/lage", methods=["POST"])
@json_login_required
@_queue_worker
def change_state(item_id):
    body = _body()

    def change(item):
        inbox.change_state(
            item, current_user, body.get("state"), note=body.get("note"), duplicate_of=body.get("duplicate_of")
        )

    return _locked(item_id, _then_item(change))


@inbox_bp.route("/inkorg/<int:item_id>/dokument/<int:document_id>", methods=["PATCH"])
@json_login_required
@_queue_worker
def update_document(item_id, document_id):
    body = _body()

    def action(item):
        document = inbox.document_of(item, document_id)
        inbox.update_document(item, document, current_user, body)
        return jsonify({"item": inbox.items_json([item])[0], "document": inbox.documents_json([document])[0]})

    return _locked(item_id, action)


# [Next.js] "Mina inskick": the user's own uploads, in plain words.
@inbox_bp.route("/inkorg/mina-inskick", methods=["GET"])
@json_login_required
def my_uploads():
    with DB_PROXY.atomic():
        return jsonify({"items": inbox.my_uploads(current_user)})


@inbox_bp.route("/inkorg/notiser", methods=["GET"])
@json_login_required
def notices():
    limit = min(max(request.args.get("limit", 50, type=int) or 50, 1), 200)
    offset = max(request.args.get("offset", 0, type=int) or 0, 0)
    unread_only = request.args.get("unread") in ("1", "true")
    rows = inbox.notices_json(current_user, unread_only=unread_only, limit=limit, offset=offset)
    return jsonify({"notices": rows, "unread": inbox.unread_count(current_user)})


# [Next.js] The menu's counter, and whether to show the queue at all.
@inbox_bp.route("/inkorg/notiser/antal", methods=["GET"])
@json_login_required
def notice_count():
    return jsonify({"unread": inbox.unread_count(current_user), "works_in_queue": inbox.works_in_queue(current_user)})


@inbox_bp.route("/inkorg/notiser/las", methods=["POST"])
@json_login_required
def read_notices():
    body = _body()
    ids = body.get("ids")
    if body.get("all") is True:
        ids = None
    elif not (isinstance(ids, list) and all(isinstance(i, int) and not isinstance(i, bool) for i in ids)):
        return problem(400, "Bad Request", 'Ange "ids": [id, …] eller "all": true.')
    return jsonify({"read": inbox.mark_read(current_user, ids), "unread": inbox.unread_count(current_user)})


@inbox_bp.route("/inkorg/notiser/installning", methods=["GET", "PUT"])
@json_login_required
def notice_setting():
    if request.method == "PUT":
        enabled = _body().get("mail_enabled")
        if not isinstance(enabled, bool):
            return problem(400, "Bad Request", "mail_enabled är true eller false.")
        inbox.set_mail_enabled(current_user, enabled)
    return jsonify({"mail_enabled": inbox.mail_enabled(current_user)})
