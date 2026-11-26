"""
The colour atlas (stamboken #37): the colours with the atlas's texts and photos, for logged-in users only. The
package lies under PRIVATE_UPLOAD_FOLDER (utils/fargatlas.py), which nginx does not serve.
"""

import logging

from extensions import limiter
from flask import Blueprint, jsonify, request, send_file
from utils import fargatlas

from .common import json_login_required, problem

logger = logging.getLogger(__name__)

fargatlas_v2_bp = Blueprint("fargatlas_v2", __name__, url_prefix="/api/v2")


# [Next.js] The colour page and the card behind "Visa färgen".
@fargatlas_v2_bp.route("/fargatlas", methods=["GET"])
@json_login_required
def atlas():
    return jsonify(fargatlas.fargatlas_data())


# [Next.js] One atlas photo, ?storlek=480 or 1600 (the default). Exempt from the per-address limit: one page is
# some 35 photos, Skriv ut loads them all at once, and members behind one address (a course, a phone network) share it.
@fargatlas_v2_bp.route("/fargatlas/foto/<foto_id>", methods=["GET"])
@limiter.exempt
@json_login_required
def foto(foto_id):
    path = fargatlas.foto_sokvag(foto_id, request.args.get("storlek", "1600"))
    if path is None:
        return problem(404, "Hittades inte", "Fotot finns inte.")
    try:
        response = send_file(path, mimetype="image/jpeg", max_age=0)
    except OSError as error:  # removed or unreadable since the check, for instance after a package copy
        logger.warning("Colour atlas photo %s cannot be opened: %s", foto_id, type(error).__name__)
        return problem(404, "Hittades inte", "Fotot finns inte.")
    # Never kept by a shared cache, and checked again on each use: a photo taken out of the package, or a session
    # that is no longer valid, stops at once. The ETag keeps that check to a 304 while the photo stays.
    response.headers["Cache-Control"] = "private, no-cache"
    return response
