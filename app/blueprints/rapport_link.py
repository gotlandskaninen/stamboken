"""
The yearly report's personal link (step 3): the exchange of a link token for a short code session, and the
session's reads. The link is `/rapport#<token>`: a browser never sends the fragment, so the token reaches no
server log. The page reads it, clears it from the address bar and posts it to the exchange.

Thin route handlers. The code and its validity are in utils/report_code.py.
"""

import re
from datetime import datetime, timedelta

import utils.arsrapport as arsrapport
import utils.report_code as report_code
import utils.settings as settings
from extensions import limiter
from flask import Blueprint, current_app, g, jsonify, make_response, request, session
from utils.database import Herd, ReportAccessCode

from .common import problem

rapport_link_bp = Blueprint("rapport_link", __name__, url_prefix="/api")

MAX_CODES = 4  # E2: the session holds at most four codes, the oldest dropped
IDLE = timedelta(hours=2)  # E3
_CANONICAL = re.compile(r"[1-9][0-9]{0,18}\.[A-Za-z0-9_-]{22}")  # nothing else goes near the database


def _environment():
    """FA2: production and the demo share the session store, so an entry says where it was made."""
    return "demo" if settings.service.demo_instance else "prod"


def _invalid():
    return problem(403, "Åtkomst nekad", arsrapport.LINK_INVALID, code="lank_ogiltig")


def _answer(response):
    # nosemgrep: make-response-with-unknown-content -- `response` is this module's own jsonify or problem() reply
    response = make_response(response)
    response.headers["Cache-Control"] = "no-store"
    return response


def session_codes(now: datetime) -> list[int]:
    """
    The code ids of a live code session (E3). A session idle for two hours loses its codes (the user part is
    untouched) and `g.rapport_expired` says so, for the 401 `session_ute`. None in the demo (FA2).
    """
    entries = session.get("rapport") or []
    if settings.service.demo_instance or not entries:
        return []
    try:
        seen = datetime.fromisoformat(session["rapport_seen"])
    except (KeyError, TypeError, ValueError):
        seen = None
    if seen is None or now - seen > IDLE:
        session.pop("rapport", None)
        session.pop("rapport_seen", None)
        g.rapport_expired = True
        return []
    return [entry[0] for entry in entries if entry[1] == _environment()]


def touch(now: datetime) -> None:
    """Each accepted code request starts the two hours again."""
    session["rapport_seen"] = now.isoformat()


@rapport_link_bp.errorhandler(429)
def rate_limited(_exc):
    return problem(
        429,
        "För många anrop",
        "Du har öppnat länken för många gånger på kort tid. Vänta en minut och försök igen.",
        type="rate-limit-exceeded",
    )


# [Next.js] The exchange: the page reads the token after # in the link and posts it here. A valid link starts a code
# session. JSON only: a cross-site page cannot send it without a CORS preflight, so no login CSRF.
@rapport_link_bp.route("/v2/rapport/oppna", methods=["POST"])
@limiter.limit("20 per minute")
def open_link():
    if request.mimetype != "application/json":  # not is_json: that accepts application/*+json too
        return _answer(problem(415, "Fel innehållstyp", "Skicka JSON."))
    now = arsrapport.now()
    body = request.get_json(silent=True)
    token = body.get("token") if isinstance(body, dict) else None
    # Canonical form first, before anything is looked up; the same answer as for a forged token.
    if settings.service.demo_instance or not isinstance(token, str) or not _CANONICAL.fullmatch(token):
        return _answer(_invalid())
    try:
        code = report_code.resolve(token)
        herd = code.herd if code is not None else None
        if code is None or report_code.refusal(code, herd, today=arsrapport.today()) is not None:
            return _answer(_invalid())
        ReportAccessCode.update(last_opened_at=now).where(ReportAccessCode.id == code.id).execute()
    except Exception as exc:  # pylint: disable=broad-except  # the answer is the same, and the log never names the token
        current_app.logger.error("Report link exchange failed: %s", type(exc).__name__)
        return _answer(_invalid())
    # As login: a new session id, so a sid planted before the exchange gets nothing. user_id stays. The rotation comes
    # first: if it fails, the grant is never made, so it cannot be saved under the old id.
    had_codes = "rapport" in session
    session.setdefault("rapport", [])  # regenerate() skips an empty session, e.g. one the revocation check just cleared
    try:
        current_app.session_interface.regenerate(session)
    except Exception as exc:  # pylint: disable=broad-except
        if not had_codes:
            session.pop("rapport", None)
        current_app.logger.error("Report link session rotation failed: %s", type(exc).__name__)
        return _answer(problem(500, "Serverfel", "Det gick inte att öppna länken. Försök igen."))
    session_codes(now)  # E3: an idle session loses its codes before this one joins, so they are not revived
    others = [entry for entry in session.get("rapport") or [] if entry[0] != code.id]
    session["rapport"] = (others + [[code.id, _environment()]])[-MAX_CODES:]
    touch(now)
    return _answer(jsonify({"herd": herd.herd, "year": code.round.report_year}))


# [Next.js] The session's valid codes, for the page and its list of herds.
@rapport_link_bp.route("/v2/rapport/mina", methods=["GET"])
def mine():
    now = arsrapport.now()
    ids = session_codes(now)
    if g.get("rapport_expired"):
        return problem(401, "Sessionen har gått ut", "Öppna länken i mejlet igen.", code="session_ute")
    rows = []
    for code in ReportAccessCode.select().where(ReportAccessCode.id.in_(ids)):
        herd = Herd.get_by_id(code.herd_id)
        if report_code.refusal(code, herd, today=arsrapport.today()) is None:
            rows.append(
                {"code_id": code.id, "herd": herd.herd, "herd_name": herd.herd_name, "year": code.round.report_year}
            )
    if rows:
        touch(now)
    return jsonify(sorted(rows, key=lambda row: ids.index(row["code_id"])))


# [Next.js] Who to call, for the page of a link that no longer works (E6). Public: no code is known there.
@rapport_link_bp.route("/v2/rapport/kontakt", methods=["GET"])
def contacts():
    return jsonify(settings.arsrapport.kontakt)
