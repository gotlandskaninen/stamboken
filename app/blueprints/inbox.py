"""
The intake queue (inläsningskön): uploads, the queue, its notices and the paper certificate on a rabbit.
docs/inkorg.md is the API; the rules live in utils/inbox.py (ADR-0007).
"""

import datetime
import logging
import os
import re
import threading
import uuid
from functools import wraps

import pillow_heif
import pypdfium2
import utils.data_access as da
import utils.inbox as inbox
import utils.inbox_interpreter as interpreter
import utils.inbox_purge as inbox_purge
from extensions import limiter
from flask import Blueprint, jsonify, request, send_file
from flask_login import current_user
from peewee import fn
from PIL import Image, ImageOps
from utils.database import (
    DB_PROXY,
    Herd,
    HerdTracking,
    InboxItem,
    Individual,
    User,
    coerce_date,
    current_holder_row,
    not_voided,
)
from utils.herd_tracking import HerdTrackingError, correct_herd_tracking, is_manager_of
from utils.individual_commands import (
    AssignPaperCertificate,
    IndividualRefused,
    TransferIndividual,
    execute,
    lock_individual_for_edit,
)
from utils.individual_number_v2 import PAPER_NUMBER_REQUIRED, parse_number

from .common import json_login_required, problem
from .individual_v2_create import register_individual
from .individuals import _validate_sale
from .uploads import MAX_FILE_SIZE, MAX_PIXELS, _too_many_pixels, _validate_magic_bytes, _webp_pixels

logger = logging.getLogger(__name__)

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


@inbox_bp.errorhandler(429)
def rate_limited(exc):
    """The limiter's 429 as problem+json, as in admin.py."""
    return problem(429, "För många anrop", f"För många inskick: högst {exc.description}.", type="rate-limit-exceeded")


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
    mine = sorted(set(current_user.is_manager or []) | set(current_user.is_helper or []))
    scope = args.get("scope") or ("alla" if current_user.is_admin else "mina")
    if scope not in ("mina", "alla"):
        return problem(400, "Bad Request", "scope är mina eller alla.")
    query = InboxItem.select()
    if scope == "mina":  # a narrower view only: anyone in the queue may still open any item
        query = query.where(InboxItem.genebank.in_(mine) | InboxItem.genebank.is_null(True))
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
    return jsonify(
        {
            "items": inbox.items_json(items),
            "total": query.count(),
            "counts": counts,
            "interpretation": interpreter.status(),
            "scope": scope,
            "my_genebanks": mine,
        }
    )


# [Next.js] Who the person pickers offer: every active admin, manager and helper, by name only.
@inbox_bp.route("/inkorg/handlaggare", methods=["GET"])
@json_login_required
@_queue_worker
def handlers():
    return jsonify({"people": inbox.handlers()})


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


# [Next.js] "Tolka igen": the certificate waits for the image reading again, after a turn.
@inbox_bp.route("/inkorg/<int:item_id>/dokument/<int:document_id>/tolka-igen", methods=["POST"])
@json_login_required
@_queue_worker
def reinterpret(item_id, document_id):
    def action(item):
        document = inbox.document_of(item, document_id)
        inbox.reinterpret(item, document, current_user)
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


# What a certificate shows, as POST /v2/individual takes it (docs/inkorg.md lists which field is which).
REGISTRATION_FIELDS = (
    "breeding_id",
    "mother",
    "father",
    "birth_date",
    "breed_date",
    "litter_size",
    "litter_size6w",
    "position",
    "paper_number",
    "paper_certificate",
    "resolution",
    "sex",
    "color",
    "name",
    "color_note",
    "eye_color",
    "claw_color",
    "belly_color",
    "hair_notes",
)
_REFUSED_AS_FORBIDDEN = {"Forbidden", AssignPaperCertificate(None).denied().envelope["message"]}


# The request field a refusal is about, from its wording (the registration's own messages) and title; the
# UI places an error by `field` first.
_FIELD_BY_DETAIL = (
    (re.compile(r"^Välj mor och far|^Modern "), "mother"),
    (re.compile(r"^Fadern "), "father"),
    (re.compile(r"levande vid 6 veckor|litter_size6w", re.I), "litter_size6w"),
    (re.compile(r"antal födda", re.I), "litter_size"),
    (re.compile(r"^Födelsedatum"), "birth_date"),
    (re.compile(r"^name must"), "name"),
    (
        re.compile(r"intygsnumret|Intygsnummer krävs|paper_certificate|certificate already exists", re.I),
        "paper_certificate",
    ),
    (re.compile(r"som det står på pappersintyget|^Individnumret ska skrivas"), "paper_number"),
    (re.compile(r"färg|color", re.I), "color"),
    (re.compile(r"^Kaninen finns inte"), "individual"),
)
_FIELD_BY_TITLE = {"number_conflict": "paper_number", "too_young": "birth_date", "litter_order_conflict": "birth_date"}


def _field_of(title, detail):
    if title in _FIELD_BY_TITLE:
        return _FIELD_BY_TITLE[title]
    if title == "Ogiltig försäljning":
        return "date" if re.search("datum", detail, re.I) else "herd"
    if title == "Conflict":
        return "paper_certificate" if re.search("certificate number", detail, re.I) else None
    return next((field for pattern, field in _FIELD_BY_DETAIL if pattern.search(detail)), None)


def _placed(response):
    """A problem response with `field` added where the request field it concerns is known."""
    body, status, headers = response
    problem_body = body.get_json()
    if field := _field_of(problem_body["title"], problem_body["detail"]):
        problem_body["field"] = field
    return jsonify(problem_body), status, headers


def _command_problem(exc):
    """A refusal from the write commands or herd-tracking, as v2's PATCH answers it."""
    if isinstance(exc, HerdTrackingError):
        return problem(exc.status, exc.title, exc.detail, rows=exc.rows)
    if not isinstance(exc, IndividualRefused):
        return problem(400, "Ogiltig begäran", str(exc))
    envelope, message = exc.envelope, exc.envelope.get("message")
    if "problem_status" in envelope:
        extra = {k: v for k, v in envelope.items() if k not in ("status", "message", "problem_status", "title")}
        return problem(envelope["problem_status"], envelope["title"], message, **extra)
    if message == "Individual not found":
        return problem(404, "Hittades inte", message)
    if message in _REFUSED_AS_FORBIDDEN:
        return problem(403, "Åtkomst nekad", message)
    return problem(400, "Ogiltig begäran", message, **{k: v for k, v in envelope.items() if k == "must_mark_dead"})


def _live_individual(number):
    individual = (
        Individual.get_or_none((Individual.number == number) & not_voided()) if isinstance(number, str) else None
    )
    if individual is None:
        raise inbox.InboxError(404, "Kaninen finns inte i Stamboken.")
    return individual


def _register_new(body, user, grant):
    """A new rabbit from the certificate, as POST /v2/individual registers it, with a paper certificate."""
    form = {key: body[key] for key in REGISTRATION_FIELDS if key in body}
    form["certificate_type"] = "paper"
    created = []
    response = register_individual(form, lambda herd: grant.allows(user, herd), created.append)
    if not created:
        raise _Refused(response)
    individual = created[0]
    birth = HerdTracking.get((HerdTracking.individual == individual.id) & (HerdTracking.kind == "BIRTH"))
    grant.trace(birth.operation_id)
    return response[0].get_json(), individual


def _assign_certificate(body, user, grant, document):
    """The paper certificate on a rabbit already in Stamboken (AssignPaperCertificate)."""
    individual = _live_individual(body.get("individual"))
    inbox.require_same_rabbit(document, individual)
    certificate, paper_number = body.get("paper_certificate"), body.get("paper_number")
    if not isinstance(certificate, str) or not certificate.strip() or len(certificate) > 20:
        raise inbox.InboxError(400, "Ange intygsnumret (paper_certificate), högst 20 tecken.")
    if parse_number(paper_number) is None:
        raise inbox.InboxError(400, PAPER_NUMBER_REQUIRED)
    try:
        execute(
            user, individual.id, lambda ctx: [AssignPaperCertificate(certificate.strip(), paper_number)], grant=grant
        )
    except (IndividualRefused, HerdTrackingError, ValueError) as exc:
        raise _Refused(_command_problem(exc)) from None
    individual = Individual.get_by_id(individual.id)
    return {"individual": individual.as_dict()}, individual


def _with_item(body_and_individual, item, document):
    body, _ = body_and_individual
    return {**body, "item": inbox.items_json([item])[0], "document": inbox.documents_json([document])[0]}


# [Next.js] Save what a certificate shows: a new rabbit, or the paper certificate on one that exists.
@inbox_bp.route("/inkorg/<int:item_id>/dokument/<int:document_id>/spara", methods=["POST"])
@json_login_required
@_queue_worker
def save_document(item_id, document_id):
    body, user = _body(), User.get_by_id(current_user.id)
    action = body.get("action")
    try:
        with DB_PROXY.atomic():
            item = inbox.lock_item(item_id)
            document = inbox.document_of(item, document_id)
            inbox.require_saving(item, document, user)
            if document.doc_type != "intyg" or document.individual_id is not None:
                raise inbox.InboxError(409, "Bara ett intyg som inte är sparat än kan sparas.")
            grant = inbox.InboxGrant(item, user, document)
            if action == "ny_kanin":
                inbox.require_same_rabbit(document)  # a rabbit sold through the document is not a new one
                result = _register_new(body, user, grant)
            elif action == "pappersintyg":
                result = _assign_certificate(body, user, grant, document)
            else:
                raise inbox.InboxError(400, 'action är "ny_kanin" eller "pappersintyg".')
            inbox.saved(item, document, user, result[1], action)
            answer = _with_item(result, item, document)
    except _Refused as refused:
        return _placed(refused.response)
    except inbox.InboxError as exc:
        return _placed(problem(exc.status, exc.title, exc.detail))
    _invalidate(result[1])
    return jsonify(answer), 201 if action == "ny_kanin" else 200


# [Next.js] Register a sale shown by a document; without a proof (bevis) the item is marked "bevis saknas".
@inbox_bp.route("/inkorg/<int:item_id>/dokument/<int:document_id>/overlat", methods=["POST"])
@json_login_required
@_queue_worker
def transfer(item_id, document_id):
    body, user = _body(), User.get_by_id(current_user.id)
    herd, date = body.get("herd"), body.get("date")
    try:
        when = datetime.date.fromisoformat(date) if isinstance(date, str) else None
    except ValueError:
        when = None
    bad = "herd" if not isinstance(herd, str) or Herd.get_or_none(Herd.herd == herd) is None else None
    if bad or when is None:
        detail = "Ange köparens besättning (herd) och datum (date, ÅÅÅÅ-MM-DD)."
        return problem(400, "Ogiltig begäran", detail, field=bad or "date")
    try:
        with DB_PROXY.atomic():
            item = inbox.lock_item(item_id)
            document = inbox.document_of(item, document_id)
            inbox.require_saving(item, document, user)
            individual = _live_individual(body.get("individual"))
            inbox.require_same_rabbit(document, individual)
            if document.herd_tracking_id is not None:
                raise inbox.InboxError(409, "En försäljning är redan registrerad genom dokumentet.")
            grant = inbox.InboxGrant(item, user, document)
            lock_individual_for_edit(individual.id)
            latest = current_holder_row(individual.id)
            proven = inbox.proven_sale(item, document, individual, herd, when)
            if proven is not None:  # the proof of a sale registered from another document: nothing to write
                seller = proven.from_herd or individual.origin_herd
                if not (is_manager_of(user, seller.genebank_id) or grant.allows(user, seller)):
                    raise inbox.InboxError(403, "Du får inte koppla ett bevis till kaninens försäljning.")
                row = proven
            elif (
                latest
                and when < coerce_date(latest.herd_tracking_date)
                and is_manager_of(user, individual.current_herd.genebank_id)
            ):
                # A correction: before the rabbit's latest row, a manager's or an admin's (ADR-0017 level 2).
                operation = uuid.uuid4()
                (row,) = correct_herd_tracking(
                    individual, user, operation, [], [{"kind": "TRANSFER", "date": date, "herd": herd}]
                )
                grant.trace(operation)
            else:
                stored = da.get_individual(individual.number, user.uuid)
                if stored is None:
                    raise inbox.InboxError(404, "Kaninen finns inte i Stamboken.")
                if error := _validate_sale(stored, {"selling_date": date, "herd": herd}, user):
                    raise _Refused(problem(400, "Ogiltig försäljning", error))
                execute(user, individual.id, lambda ctx: [TransferIndividual(herd, date)], grant=grant)
                row = current_holder_row(individual.id)
            inbox.transferred(item, document, user, individual, row, linked=proven is not None)
            answer = {
                "individual": Individual.get_by_id(individual.id).as_dict(),
                "herd_tracking_id": row.id,
                "item": inbox.items_json([item])[0],
                "document": inbox.documents_json([document])[0],
            }
    except _Refused as refused:
        return _placed(refused.response)
    except inbox.InboxError as exc:
        return _placed(problem(exc.status, exc.title, exc.detail))
    except (IndividualRefused, HerdTrackingError) as exc:
        return _placed(_command_problem(exc))
    _invalidate(individual)
    return jsonify(answer), 200


def _invalidate(individual):
    """Best-effort Next.js cache invalidation, after the commit: never fails the request."""
    try:
        from utils.cache_invalidation import trigger_invalidation

        trigger_invalidation(individual.origin_herd.genebank_id)
    except Exception:  # pylint: disable=broad-except
        logger.warning("Cache invalidation failed for %s", individual.number, exc_info=True)


def _private_jpeg(relative):
    """A file under PRIVATE_UPLOAD_FOLDER, never cached anywhere on the way."""
    response = send_file(inbox.private_path(relative), mimetype="image/jpeg", max_age=0)
    response.headers["Cache-Control"] = "no-store, private"
    return response


# [Next.js] Confirm the masking: the copy goes on the rabbit and the document is done.
@inbox_bp.route("/inkorg/<int:item_id>/dokument/<int:document_id>/maskning", methods=["POST"])
@json_login_required
@_queue_worker
def confirm_mask(item_id, document_id):
    body = _body()

    def action(item):
        document = inbox.document_of(item, document_id)
        inbox.confirm_mask(
            item, document, current_user, body.get("rotation"), body.get("mask_rects"), body.get("no_personal_data")
        )
        return jsonify({"item": inbox.items_json([item])[0], "document": inbox.documents_json([document])[0]})

    return _locked(item_id, action)


# [Next.js] Erase one document's original on request; only the masked copy, if made, is left. Managers and admins.
@inbox_bp.route("/inkorg/<int:item_id>/dokument/<int:document_id>/radera-original", methods=["POST"])
@json_login_required
@_queue_worker
def erase_original(item_id, document_id):
    try:
        with DB_PROXY.atomic():
            item = inbox.lock_item(item_id)
            if not inbox.manages(current_user, item.genebank_id):
                raise inbox.InboxError(403, "Bara genbanksansvarig och admin kan radera ett original.")
            paths = inbox_purge.erase_document(item, inbox.document_of(item, document_id), current_user)
            item = InboxItem.get_by_id(item_id)
            document = inbox.document_of(item, document_id)
            answer = {"item": inbox.items_json([item])[0], "document": inbox.documents_json([document])[0]}
    except inbox.InboxError as exc:
        return problem(exc.status, exc.title, exc.detail)
    inbox_purge.remove_originals(paths)
    return jsonify(answer)


# [Next.js] The original as it came in, for those working in the queue only; every view is logged.
@inbox_bp.route("/inkorg/<int:item_id>/dokument/<int:document_id>/original", methods=["GET"])
@json_login_required
@_queue_worker
def original(item_id, document_id):
    try:
        with DB_PROXY.atomic():
            item = InboxItem.get_or_none(InboxItem.id == item_id)
            if item is None:
                raise inbox.InboxError(404, "Posten finns inte.")
            document = inbox.document_of(item, document_id)
            if document.original_path is None:
                raise inbox.InboxError(404, "Originalet är raderat.")
            inbox.log_event(item, current_user.id, "original_visat", document=document.id)
    except inbox.InboxError as exc:
        return problem(exc.status, exc.title, exc.detail)
    return _private_jpeg(document.original_path)


# [Next.js] The paper certificate on the rabbit's page: the masked copy, for whoever may see its certificate.
@inbox_bp.route("/individual/<number>/paper-certificate", methods=["GET"])
@json_login_required
def paper_certificate(number):
    individual = Individual.get_or_none((Individual.number == number) & not_voided())
    user = User.get_by_id(current_user.id)
    if individual is None or da.get_individual(number, user.uuid) is None:
        return problem(404, "Not Found", f"Individual {number} not found")
    if not user.can_view_certificate(individual):
        return problem(403, "Forbidden", "Bara ägaren, uppfödaren och genbanksansvarig kan hämta intyget")
    document = inbox.paper_certificate(individual)
    if document is None:
        return problem(404, "Not Found", "Kaninen har inget inläst pappersintyg.")
    return _private_jpeg(document.public_path)
