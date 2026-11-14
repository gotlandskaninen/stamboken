"""
The intake queue (inläsningskön): uploads, the queue, its notices and the paper certificate on a rabbit.
docs/inkorg.md is the API; the rules live in utils/inbox.py (ADR-0007).
"""

import os
import threading

import pillow_heif
import pypdfium2
import utils.inbox as inbox
from extensions import limiter
from flask import Blueprint, jsonify, request
from flask_login import current_user
from PIL import Image, ImageOps
from utils.database import DB_PROXY, Herd

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
