"""
The erase link in kopare.information (ADR-0016, docs/mejl.md): public, no login. The token comes in the body,
never in a URL, so neither the request log nor an access log ever holds it.
"""

from extensions import limiter
from flask import Blueprint, jsonify, request
from utils.buyer_mail import erase_by_link
from utils.herd_tracking import HerdTrackingConflict

from .common import problem

buyer_link_bp = Blueprint("buyer_link", __name__, url_prefix="/api")

GONE = "Länken gäller inte längre. Skriv till dataskydd@gotlandskaninen.se."


@buyer_link_bp.after_request
def _no_store(response):
    """No answer is cached, the 429 included. Referrer-Policy is set in herdbook.py, after Talisman's."""
    response.headers["Cache-Control"] = "no-store"
    return response


# [Next.js] The button on /kopare/ta-bort. POST only: a link preview in a mail program must never erase anyone.
@buyer_link_bp.route("/v2/kopare/ta-bort", methods=["POST"])
@limiter.limit("10 per hour")
def erase_buyer():
    body = request.get_json(silent=True)
    try:
        result = erase_by_link(body.get("token") if isinstance(body, dict) else None)
    except HerdTrackingConflict as busy:  # a correction or the queue got in between: nothing was erased
        return problem(409, "Försök igen", str(busy))
    if result is None:  # forged, malformed or for another purpose: one answer, whatever id it names
        return problem(404, "Hittades inte", GONE)
    return jsonify({"result": result})
