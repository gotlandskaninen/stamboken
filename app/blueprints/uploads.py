"""
Photo upload endpoint for rabbit individuals (v2).

Thin route handler — image processing logic is kept inline since it's
specific to this endpoint. See ADR-0007 for blueprint conventions.
RFC 9457 Problem Details for all error responses per ADR-0008.
"""

import os
import uuid

from flask import Blueprint, jsonify, request
from flask_login import current_user
from PIL import Image
from utils.number_assets import PHOTO_SUFFIXES, kaniner_path, lock_number

from blueprints.common import json_login_required, problem

uploads_bp = Blueprint("uploads", __name__, url_prefix="/api")

# Magic byte signatures for allowed image types
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG"
_WEBP_RIFF = b"RIFF"
_WEBP_SIG = b"WEBP"

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_PIXELS = 40_000_000  # decoded size, not bytes: a 20 KB PNG can decode to hundreds of MB


def _validate_magic_bytes(file_stream):
    """Validate file type by checking magic bytes, not extension.

    Returns detected type ('jpeg', 'png', 'webp') or None if invalid.
    """
    header = file_stream.read(12)
    file_stream.seek(0)
    if header[:3] == _JPEG_MAGIC:
        return "jpeg"
    if header[:4] == _PNG_MAGIC:
        return "png"
    if header[:4] == _WEBP_RIFF and header[8:12] == _WEBP_SIG:
        return "webp"
    return None


def _webp_pixels(header):
    """Canvas size from the first 30 bytes of a WebP file (0 if the chunk is unknown).

    Pillow's WebP plugin builds the decoder, which allocates the canvas, inside Image.open.
    """
    chunk = header[12:16]
    if chunk == b"VP8X":
        return (1 + int.from_bytes(header[24:27], "little")) * (1 + int.from_bytes(header[27:30], "little"))
    if chunk == b"VP8L":
        bits = int.from_bytes(header[21:25], "little")
        return (1 + (bits & 0x3FFF)) * (1 + ((bits >> 14) & 0x3FFF))
    if chunk == b"VP8 ":
        return (int.from_bytes(header[26:28], "little") & 0x3FFF) * (int.from_bytes(header[28:30], "little") & 0x3FFF)
    return 0


def _too_many_pixels():
    return problem(413, "Payload Too Large", "Bilden har för många pixlar. Max 40 megapixlar.")


# [Next.js] Photo upload for individual rabbits (v2)
@uploads_bp.route("/v2/upload/photo/<individual_number>", methods=["POST"])
@json_login_required
def upload_photo(individual_number):
    """Upload a photo for an individual rabbit.

    Validates ownership, magic bytes, and file size. Converts PNG/WebP to JPEG
    and generates a 200px thumbnail. Returns RFC 9457 errors on failure.
    """
    # Import here to avoid circular imports (database models import from herdbook)
    from utils.database import DB_PROXY, Individual, lock_individuals

    # Validate ownership
    if not current_user.can_edit(individual_number):
        return problem(403, "Forbidden", "Du har inte behörighet att ladda upp foto för denna individ.")

    # Check file present
    if "file" not in request.files:
        return problem(400, "Bad Request", "Ingen fil bifogad.")

    file = request.files["file"]
    if not file or not file.filename:
        return problem(400, "Bad Request", "Ingen fil bifogad.")

    # Validate file size
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        return problem(413, "Payload Too Large", "Filen är för stor. Max 10 MB.")

    # Validate magic bytes (NFR-S7)
    file_type = _validate_magic_bytes(file)
    if file_type is None:
        return problem(415, "Unsupported Media Type", "Otillåten filtyp. Bara JPEG, PNG och WebP.")

    # Resolve individual
    try:
        individual = Individual.get(Individual.number == individual_number)
    except Individual.DoesNotExist:
        return problem(404, "Not Found", "Individen hittades inte.")

    # Ensure upload directory exists
    upload_dir = kaniner_path()
    os.makedirs(upload_dir, exist_ok=True)

    # Save and convert to JPEG, under a temporary name: the rabbit may be renumbered meanwhile.
    tmp = os.path.join(upload_dir, f"~upload-{uuid.uuid4().hex}")
    try:
        try:
            if file_type == "webp" and _webp_pixels(file.read(30)) > MAX_PIXELS:
                return _too_many_pixels()
            file.seek(0)
            with Image.open(file) as img:
                if img.width * img.height > MAX_PIXELS:  # for JPEG/PNG, Image.open reads only the header
                    return _too_many_pixels()
                img.load()  # Force full decode — catches truncated/malformed files
                # Convert to RGB (PNG may have alpha channel)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(tmp + ".jpg", "JPEG", quality=85)

                # Generate 200px thumbnail
                img.thumbnail((200, 200))
                img.save(tmp + "_thumb.jpg", "JPEG", quality=85)
        except Image.DecompressionBombError:  # Pillow's own limit (~179 MP) trips inside Image.open
            return _too_many_pixels()
        except Exception:
            return problem(422, "Unprocessable Content", "Bildfilen kunde inte bearbetas. Filen kan vara skadad.")

        # Store under the rabbit's number as of now, while no renumber can commit (row lock) or be
        # moving its files (number lock).
        with DB_PROXY.atomic():
            lock_individuals([individual.id])
            # Authorized again under the lock: a sale may have completed while the image was processed.
            if not current_user.can_edit(individual.id):
                return problem(403, "Forbidden", "Du har inte behörighet att ladda upp foto för denna individ.")
            number = Individual.get_by_id(individual.id).number
            lock_number(number, xact=True)
            for suffix in PHOTO_SUFFIXES:
                os.replace(tmp + suffix, os.path.join(upload_dir, number + suffix))
            # Only this column: a full save would write back whatever changed while the image was processed.
            individual.has_photo = True
            individual.save(only=[Individual.has_photo, Individual.updated_at])
    finally:
        for suffix in PHOTO_SUFFIXES:
            if os.path.exists(tmp + suffix):
                os.remove(tmp + suffix)

    return jsonify({"filename": f"{number}.jpg"}), 201
