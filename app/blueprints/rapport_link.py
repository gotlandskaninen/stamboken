"""
The yearly report's personal link (step 3): the exchange of a link token for a short code session, and the
session's reads. The token never reaches Next: nginx sends /rapport/<token> here, and the answer is a 303 to
/rapport?kod=<id>.

Thin route handlers. The code and its validity are in utils/report_code.py.
"""

import re
from datetime import datetime, timedelta

import utils.arsrapport as arsrapport
import utils.report_code as report_code
import utils.settings as settings
from extensions import limiter
from flask import Blueprint, current_app, g, jsonify, redirect, request, session
from utils.database import Herd, ReportAccessCode

from .common import problem

rapport_link_bp = Blueprint("rapport_link", __name__, url_prefix="/api")

MAX_CODES = 4  # E2: the session holds at most four codes, the oldest dropped
IDLE = timedelta(hours=2)  # E3
_CANONICAL = re.compile(r"[1-9][0-9]{0,18}\.[A-Za-z0-9_-]{22}")  # R6: nothing else goes near a log or the database
_INVALID = "/rapport/ogiltig"
_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _environment():
    """FA2: production and the demo share the session store, so an entry says where it was made."""
    return "demo" if settings.service.demo_instance else "prod"


def exchange_headers(response):
    """
    An after_request hook, registered in herdbook.py before Flask-Talisman: Flask runs these last-registered first,
    and Talisman sets one Referrer-Policy for every answer, so this one has to run after it.
    """
    if request.endpoint == "rapport_link.open_link":
        response.headers.update(_HEADERS)
    return response


def _answer(location):
    response = redirect(location, 303)
    response.headers.update(_HEADERS)
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
def rate_limited(exc):
    return problem(429, "För många anrop", f"Högst {exc.description}.", type="rate-limit-exceeded")


# [Next.js, nginx] The exchange: a valid link starts a code session and goes on to the page without the token.
@rapport_link_bp.route("/v2/rapport/oppna/<path:token>", methods=["GET"])
@limiter.limit("20 per minute")
def open_link(token):
    now = arsrapport.now()
    # Canonical form first, before anything is logged or looked up; the same answer as for a forged token.
    if settings.service.demo_instance or not _CANONICAL.fullmatch(token):
        return _answer(_INVALID)
    try:
        code = report_code.resolve(token)
        if code is None or report_code.refusal(code, code.herd, today=arsrapport.today()) is not None:
            return _answer(_INVALID)
        ReportAccessCode.update(last_opened_at=now).where(ReportAccessCode.id == code.id).execute()
    except Exception as exc:  # pylint: disable=broad-except  # the 303 is the same, and the log never names the token
        current_app.logger.error("Report link exchange failed: %s", type(exc).__name__)
        return _answer(_INVALID)
    session_codes(now)  # E3: an idle session loses its codes before this one joins, so they are not revived
    others = [entry for entry in session.get("rapport") or [] if entry[0] != code.id]
    session["rapport"] = (others + [[code.id, _environment()]])[-MAX_CODES:]
    touch(now)
    # As login: a new session id, so a sid planted before the exchange gets nothing. user_id stays.
    current_app.session_interface.regenerate(session)
    return _answer(f"/rapport?kod={code.id}")


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
