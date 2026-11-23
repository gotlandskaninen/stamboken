"""Email code sign-in. Both credentials redeem the same browser-bound row."""

import hmac
import logging
import secrets

from extensions import limiter
from flask import Blueprint, current_app, jsonify, request, session
from flask_limiter.util import get_remote_address
from flask_login import current_user
from limits import parse
from utils import login_code as lc
from utils import settings
from utils.data_access import fetch_user_info, login_generation
from utils.database import DB_PROXY
from utils.login_account import start_pending
from utils.mail import _normalize, address_hash, enqueue_mail
from utils.matrikel import LinkError, _lock_for_detach

from blueprints.common import problem

code_login_bp = Blueprint("code_login", __name__, url_prefix="/api/v2/login")
IP_LIMIT = parse("10 per hour")
logger = logging.getLogger("herdbook.code_login")


def _wrong():
    return problem(400, "Ogiltig kod eller länk", "Använd webbläsaren där du bad om koden eller be om en ny kod.")


@code_login_bp.before_request
def require_enabled():
    if request.endpoint == "code_login.status":
        return None
    if not lc.enabled():
        return problem(404, "Kodinloggningen är avstängd", "Använd ett annat inloggningssätt.")
    try:
        lc.refuse_unsafe()
    except lc.CodeRefused:
        return problem(503, "Kodinloggningen är otillgänglig", "Försök igen senare.")
    return None


@code_login_bp.get("/status")
def status():
    return jsonify(enabled=lc.enabled())


def _queue_request(address, browser, replaces, source):
    # WSGI calls this after handing off the body. Database and limiter latency cannot disclose the recipient.
    try:
        allowed = not limiter.enabled or limiter.limiter.hit(IP_LIMIT, "code-login", source)
        with DB_PROXY.atomic():
            person = lc.login_holder(address) if address and allowed else None
            if person:
                person, _ = _lock_for_detach(person.id)
                if lc.login_address(person, address_hash(address)):
                    row = lc.issue(person, "login", browser, address, replaces=replaces)
                    if row:
                        enqueue_mail(
                            "konto.kod",
                            "login_code",
                            row.id,
                            {"code_id": row.id},
                            ref=("membership", person.membership_id),
                        )
                    return
            lc.cancel(replaces, purpose="login")
    except LinkError:
        pass  # The member disappeared before the lock.
    except Exception:  # The HTTP response has already been sent. Never log the address or the credential.
        logger.error("Could not queue a code login request")


@code_login_bp.post("/kod")
@limiter.exempt
def request_code():
    body = request.get_json(silent=True)
    email = body.get("email") if isinstance(body, dict) else None
    address = _normalize(email) if isinstance(email, str) and len(email) <= 255 else None
    browser = secrets.token_urlsafe(32)
    replaces = request.cookies.get("login_request")
    source = hmac.digest(
        settings.mail.link_secret.encode(), ("code-ip:" + get_remote_address()).encode(), "sha256"
    ).hex()
    response = jsonify(message="Finns adressen i matrikeln har vi skickat en kod dit.")
    response.set_cookie(
        "login_request",
        browser,
        max_age=int(lc.VALID_FOR.total_seconds()),
        httponly=True,
        secure=current_app.config["SESSION_COOKIE_SECURE"],
        samesite="Lax",
    )
    response.cache_control.no_store = True
    response.call_on_close(lambda: _queue_request(address, browser, replaces, source))
    return response


def _redeem(*, link, preview=False):
    body = request.get_json(silent=True)
    browser = request.cookies.get("login_request")
    if not browser or not isinstance(body, dict):
        return _wrong()
    entered = body.get("token" if link else "code")
    # Unknown browsers and wrong credentials go through the same check without locking a person.
    # Commit wrong tries. A valid credential is checked again under the normal membership-first locks.
    with DB_PROXY.atomic() as probe:
        try:
            candidate = lc.check("login", browser, entered, link=link)
        except lc.CodeLoginClosed:
            return _wrong()
        if candidate is None:
            return _wrong()
        probe.rollback()  # The probe must not spend a correct numeric try.
    with DB_PROXY.atomic() as transaction:
        # Same lock order as address changes, account linking and role updates.
        try:
            person, user = _lock_for_detach(candidate.member_id)
        except LinkError:
            return _wrong()
        try:
            row = lc.check("login", browser, entered, person.id, link=link)
        except lc.CodeLoginClosed:
            return _wrong()
        if row is None:
            return _wrong()  # A wrong numeric try commits here.
        if row.id != candidate.id or row.user_id != person.user_id or not lc.login_address(person, row.address_hash):
            transaction.rollback()
            return _wrong()
        signed_in = current_user
        if not signed_in.is_authenticated and session.get("user_id"):
            signed_in = fetch_user_info(session["user_id"])
        other = signed_in.id if signed_in and signed_in.is_authenticated and signed_in.id != row.user_id else None
        if preview:
            response = jsonify(name=f"{person.first_name} {person.last_name}".strip(), switch_from=other)
            response.cache_control.no_store = True
            return response
        if other is not None and (type(body.get("confirm_user_id")) is not int or body["confirm_user_id"] != other):
            transaction.rollback()  # A right code requesting confirmation does not spend a try.
            return problem(409, "Bekräfta byte av konto", "Ett annat konto är inloggat.", switch_from=other)
        if not lc.consume(row, link=link):
            transaction.rollback()
            return _wrong()
        generation = login_generation(user.uuid) if user else None
    if user is None:
        start_pending(person, row)
        return jsonify(pending=True)
    session.clear()
    current_app.extensions["establish_session"](user, "kod", generation)
    return jsonify(v2_prod_access=user.v2_promoted)


@code_login_bp.post("/kod/verifiera")
def verify_code():
    return _redeem(link=False)


@code_login_bp.post("/lank/uppslag")
def preview_link():
    return _redeem(link=True, preview=True)


@code_login_bp.post("/lank")
def redeem_link():
    return _redeem(link=True)
