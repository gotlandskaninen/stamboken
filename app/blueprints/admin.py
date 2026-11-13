"""
Admin blueprint — v2 Adminpanel endpoints.

Panel-specific reads and mutations that don't belong in the generic
/api/manage/* space. Admin-only across the whole blueprint.

`admin_required` folds the auth check into the
role check — no separate `@login_required` on any admin_bp route.
Unauthenticated requests get 401 application/problem+json; authenticated
non-admin requests get 403 application/problem+json. Never a redirect.

ADR-0007: this module must never import herdbook.py — the shared rate
limiter comes from app/extensions.py.
"""

import os
from datetime import datetime

import redis
import utils.data_access as da
import utils.database as db
import utils.settings as settings
from extensions import limiter
from flask import Blueprint, current_app, jsonify, request, session
from flask_login import current_user
from peewee import OperationalError

from blueprints.common import admin_required, problem

admin_bp = Blueprint("admin", __name__, url_prefix="/api/v2/admin")


@admin_bp.route("/role", methods=["POST"])
@admin_required
@limiter.limit("30 per minute", key_func=lambda: str(current_user.id))
def admin_grant_role():
    """
    Admin-only role grant/revoke for the v2 panel.

    Body:
      {"operation": "add" | "remove",
       "user_id": <int>,
       "role": {"level": "admin"} | {"level": "matrikel_admin"}
             | {"level": "manager" | "helper" | "viewer", "genebank": <int>}
             | {"level": "owner", "herd": <int>}}   # numeric Herd.id

    Legacy POST /api/manage/role is UNTOUCHED — the
    v2 panel routes ALL role writes here. Delegates to
    data_access.update_role(), so the last-admin invariant fires
    (ValidationError → 409 application/problem+json) and the hbuser
    audit trigger records the write.
    """
    body = request.get_json(silent=True) or {}
    operation = body.get("operation")
    user_id = body.get("user_id")
    role = body.get("role")

    if operation not in ("add", "remove"):
        return problem(
            400,
            "Ogiltig operation",
            "operation måste vara 'add' eller 'remove'.",
            type="invalid-operation",
        )
    if not isinstance(user_id, int) or isinstance(user_id, bool):
        return problem(
            400,
            "Ogiltigt user_id",
            "user_id måste vara heltal.",
            type="invalid-user-id",
        )
    try:
        entry = da.validate_privileges([role])[0]
    except ValueError as exc:
        return problem(400, "Ogiltig roll", str(exc), type="invalid-role")

    op = {"action": operation, "role": entry["level"], "user": user_id}
    if "genebank" in entry:
        op["genebank"] = entry["genebank"]
    if "herd" in entry:
        op["herd"] = entry["herd"]

    # ValidationError("last-admin") propagates from update_role as a 409
    # problem+json HTTPException — no try/except needed here.
    result = da.update_role(op, current_user.uuid)
    if result.get("status") == "error":
        status = 404 if result.get("message") == "unknown user" else 400
        return problem(
            status,
            "Rolländring misslyckades",
            result.get("message", "okänt fel"),
            type="role-update-failed",
        )
    return jsonify(result), 200


def _parse_iso_arg(name):
    """Optional ISO 8601 query param → (datetime | None, error | None)."""
    raw = request.args.get(name)
    if not raw:
        return None, None
    try:
        return datetime.fromisoformat(raw), None
    except ValueError:
        return None, problem(
            400,
            "Ogiltigt datum",
            f"Parametern '{name}' är inte giltig ISO 8601: {raw}",
            type="invalid-query-param",
        )


@admin_bp.route("/audit-log", methods=["GET"])
@admin_required
def get_audit_log():
    """Paginated audit_log reader. Filters via query params:
    table, record_id, changed_by, from, to, op, page, per_page."""
    date_from, err = _parse_iso_arg("from")
    if err:
        return err
    date_to, err = _parse_iso_arg("to")
    if err:
        return err
    try:
        result = da.query_audit_log(
            table_name=request.args.get("table"),
            record_id=request.args.get("record_id"),
            changed_by=request.args.get("changed_by"),
            date_from=date_from,
            date_to=date_to,
            operation=request.args.get("op"),
            page=request.args.get("page", 1, type=int),
            per_page=request.args.get("per_page", 50, type=int),
        )
    except OperationalError:
        # statement_timeout tripped; the RSC side shows its own copy.
        return problem(
            503,
            "Aktivitetsloggen är inte tillgänglig",
            "Frågan tog för lång tid (över 5 sekunder). Förfina filtren och försök igen.",
            type="audit-log-timeout",
        )
    return jsonify(result), 200


@admin_bp.route("/online-users", methods=["GET"])
@admin_required
def get_online_users():
    """?minutes=1|5|15 (default 5) → [{username, fullname, last_active}]."""
    minutes = request.args.get("minutes", 5, type=int)
    minutes = max(1, min(minutes, 1440))  # clamp: 1 min .. 24 h
    return jsonify(da.get_online_users(minutes=minutes)), 200


# Demo-sync status, read-only (the trigger stays cut).


@admin_bp.route("/sync-status", methods=["GET"])
@admin_required
def get_sync_status():
    """Latest demo_sync_status row + stale flag (>26 h since last
    finished run). Read-only — the in-app sync trigger stays cut."""
    return jsonify(da.get_demo_sync_status())


_USER_SORT_FIELDS = {"username", "email", "fullname", "last_active"}
_USER_ROLE_FILTERS = {"admin", "matrikel_admin", "manager", "helper", "viewer", "owner", "none"}


@admin_bp.route("/users", methods=["GET"])
@admin_required
def list_users_admin():
    """
    Paginated admin user list with filters.

    Query params:
      role=admin|matrikel_admin|manager|helper|viewer|owner|none
      validated=true|false
      active=true|false       (hbuser.is_active — the Aktiv/Inaktiv filter)
      v2_prod_access=true|false  (hbuser.v2_prod_access — the yes/no filter)
      active_since=<ISO8601>  (last_active >= this)
      search=<str>            (matches username | email | fullname)
      page=<int>              (default 1)
      per_page=<int>          (default 25, cap 200)
      sort=username|email|fullname|last_active   (default: last_active)
      dir=asc|desc                                (default: desc)

    Returns each row with the full admin field set (same shape as the
    detail endpoint below, excluding _privileges — that's ballast for a
    list). Includes `role_summary` — a short computed label
    ("admin" | "manager(G,M)" | "viewer(G)" | "owner(2 besättningar)" |
    "ingen roll", plus " + matrikel_admin" when held) — computed
    server-side so the client can render without re-deriving from
    _privileges.
    """
    role = request.args.get("role")
    if role and role not in _USER_ROLE_FILTERS:
        return problem(
            400, "Ogiltig roll", f"role måste vara en av {sorted(_USER_ROLE_FILTERS)}.", type="invalid-query-param"
        )
    validated_param = request.args.get("validated")
    validated = None if validated_param is None else validated_param == "true"
    active_param = request.args.get("active")
    active = None if active_param is None else active_param == "true"
    v2_param = request.args.get("v2_prod_access")
    v2_prod_access = None if v2_param is None else v2_param == "true"
    active_since, err = _parse_iso_arg("active_since")
    if err:
        return err
    sort = request.args.get("sort", "last_active")
    if sort not in _USER_SORT_FIELDS:
        sort = "last_active"
    direction = "asc" if request.args.get("dir", "desc") == "asc" else "desc"
    return jsonify(
        da.list_admin_users(
            role=role,
            validated=validated,
            active=active,
            v2_prod_access=v2_prod_access,
            active_since=active_since,
            search=request.args.get("search"),
            page=request.args.get("page", 1, type=int),
            per_page=request.args.get("per_page", 25, type=int),
            sort=sort,
            direction=direction,
        )
    ), 200


@admin_bp.route("/users/<int:u_id>", methods=["GET"])
@admin_required
def get_user_admin(u_id):
    """
    Full admin user detail. Returns:
      id, username, email, fullname, uuid,
      validated, v2_prod_access, is_active,
      _privileges (full JSON array),
      last_active,
      profile_picture, google_picture, google_name, google_email,
      use_google_picture.
    (created_at only if the column exists — it does not today.)
    """
    detail = da.get_admin_user_detail(u_id)
    if detail is None:
        return problem(404, "Användare saknas", f"Ingen användare med id {u_id}.", type="user-not-found")
    return jsonify(detail), 200


@admin_bp.route("/users/<int:u_id>", methods=["PATCH"])
@admin_required
def update_user_admin(u_id):
    """
    Admin-only user profile update. Body accepts a subset of
    {fullname, email}. Does NOT accept _privileges (POST /api/v2/admin/role) or flag fields (dedicated endpoints below).
    Returns the updated user in the GET-detail shape.
    """
    body = request.get_json(silent=True) or {}
    allowed = {"fullname", "email"}
    unknown = sorted(set(body) - allowed)
    if unknown:
        return problem(
            400,
            "Okända fält",
            f"Okända fält: {unknown}. Roller ändras via POST /api/v2/admin/role; "
            "flaggor via sina egna endpoints (v2-prod-access, validated, active).",
            type="unknown-fields",
        )
    if not all(isinstance(body[k], str) for k in body):
        return problem(
            400,
            "Ogiltigt värde",
            "fullname och email måste vara strängar.",
            type="invalid-value",
        )
    try:
        return jsonify(da.edit_admin_user(u_id, body)), 200
    except ValueError as exc:
        if str(exc) == "user-not-found":
            return problem(
                404,
                "Användare saknas",
                f"Ingen användare med id {u_id}.",
                type="user-not-found",
            )
        raise


@admin_bp.route("/users/<int:u_id>/v2-prod-access", methods=["PATCH"])
@admin_required
def set_v2_prod_access(u_id):
    """Toggle hbuser.v2_prod_access. Body: {"enabled": bool}."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("enabled"), bool):
        return problem(
            400,
            "Ogiltigt värde",
            "'enabled' måste vara JSON-boolean.",
            type="invalid-enabled",
        )
    try:
        return jsonify(da.set_v2_prod_access(u_id, body["enabled"])), 200
    except ValueError as exc:
        if str(exc) == "user-not-found":
            return problem(
                404,
                "Användare saknas",
                f"Ingen användare med id {u_id}.",
                type="user-not-found",
            )
        raise


# Dedicated write path for the validated toggle.


@admin_bp.route("/users/<int:u_id>/validated", methods=["PATCH"])
@admin_required
def set_validated(u_id):
    """Toggle hbuser.validated (course completed; required for Google login).
    Body: {"validated": bool}. Audit row via hbuser trigger."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("validated"), bool):
        return problem(
            400,
            "Ogiltigt värde",
            "'validated' måste vara JSON-boolean.",
            type="invalid-validated",
        )
    try:
        return jsonify(da.set_validated(u_id, body["validated"])), 200
    except ValueError as exc:
        if str(exc) == "user-not-found":
            return problem(
                404,
                "Användare saknas",
                f"Ingen användare med id {u_id}.",
                type="user-not-found",
            )
        raise


_DEACTIVATION_PROBLEM_TITLES = {
    "last-admin": "Kan inte inaktivera sista aktiva admin",
    "self-deactivation": "Kan inte inaktivera ditt eget konto",
}


# Account deactivation.


@admin_bp.route("/users/<int:u_id>/active", methods=["PATCH"])
@admin_required
def set_active(u_id):
    """Activate/deactivate an account. Body: {"active": bool}.
    Guards: last-ACTIVE-admin → 409 (ordered-lock transaction);
    self-deactivation → 409. Audit row via hbuser trigger."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("active"), bool):
        return problem(
            400,
            "Ogiltigt värde",
            "'active' måste vara JSON-boolean.",
            type="invalid-active",
        )
    try:
        result = da.set_account_active(u_id, body["active"], actor_user_id=current_user.id)
    except da.ValidationError as exc:
        # ValidationError carries .problem_type / .detail;
        # its .args are empty, so read the attributes directly.
        code = exc.problem_type
        return problem(
            409,
            _DEACTIVATION_PROBLEM_TITLES.get(code, "Ogiltig åtgärd"),
            exc.detail,
            type=code,
        )
    except ValueError as exc:
        if str(exc) == "user-not-found":
            return problem(
                404,
                "Användare saknas",
                f"Ingen användare med id {u_id}.",
                type="user-not-found",
            )
        raise
    return jsonify(result), 200


@admin_bp.errorhandler(429)
def admin_rate_limited(exc):
    """Blueprint-scoped 429 → problem+json. Flask routes the limiter's
    before-request RateLimitExceeded to the matched blueprint's handler,
    so legacy endpoints' 429 shape is untouched."""
    return problem(
        429,
        "För många anrop",
        f"Rate limit: {exc.description}.",
        type="rate-limit-exceeded",
    )


# Dedicated admin password reset. The legacy
# /api/manage/setpassword/ aliases stay untouched (self-service path).


@admin_bp.route("/users/<int:u_id>/password-reset", methods=["POST"])
@admin_required
@limiter.limit("10 per hour", key_func=lambda: str(current_user.id))
def admin_reset_password(u_id):
    """Body: {"password": "<plaintext>"} → 204 No Content. Covers both
    authenticator branches (INSERT for Google-only users, UPDATE for
    existing password authenticators). Rate scoped by the ACTING admin's
    id — one admin cannot exhaust another admin's budget."""
    body = request.get_json(silent=True) or {}
    new_password = body.get("password")
    if not isinstance(new_password, str) or not new_password:
        return problem(
            400,
            "Ogiltigt värde",
            "'password' (icke-tom sträng) krävs.",
            type="invalid-password",
        )
    target = db.User.get_or_none(db.User.id == u_id)
    if target is None:
        return problem(
            404,
            "Användare saknas",
            f"Ingen användare med id {u_id}.",
            type="user-not-found",
        )
    # Live signature: change_password(active_user, changed_user, form).
    # BOTH keys required: the INSERT branch (Google-only
    # target) reads form["password"], the UPDATE branch reads
    # form["newpassword"]. current_user.is_admin skips the old-password
    # check on the admin path.
    ok = da.change_password(current_user, u_id, {"password": new_password, "newpassword": new_password})
    if not ok:
        return problem(
            500,
            "Lösenordsbyte misslyckades",
            "change_password returnerade fel.",
            type="password-reset-failed",
        )
    return "", 204


# Session mass logout.


@admin_bp.route("/sessions/mass-logout", methods=["POST"])
@admin_required
def mass_logout():
    """SCAN+DEL all 'session:*' keys in the Flask-Session Redis (db 2).
    Returns {"sessions_cleared": n}. Writes an explicit audit_log marker
    row. The acting admin's own session is cleared too — session.clear()
    stops SESSION_REFRESH_EACH_REQUEST from re-saving it after the sweep."""
    if settings.service.demo_instance:
        # The demo shares the session store: its sweep would log out production.
        return problem(
            403,
            "Inte på demon",
            "Massutloggning görs i produktion; demon delar sessioner med den.",
            type="demo-instance",
        )
    redis_client = current_app.config["SESSION_REDIS"]
    changed_by = current_user.username or current_user.email or ""
    cleared = da.mass_logout_sessions(redis_client, changed_by)
    session.clear()
    return jsonify({"sessions_cleared": cleared})


def _active_counter_keys(storage_url):
    """DBSIZE of the rate-limit Redis (prod: db 3). None when unreachable."""
    try:
        client = redis.Redis.from_url(storage_url, socket_connect_timeout=2, socket_timeout=2)
        return int(client.dbsize())
    except Exception:
        return None


def _registered_limits():
    """
    Enumerate the Flask-Limiter 4.x registry: decorated routes (raw limit
    strings preserved) + app defaults under endpoint "default".
    `_decorated_limits` is a private attr — acceptable because
    flask-limiter is pinned (==4.0.0, app/requirements.txt:58); a future
    bump is caught by test_rate_limit_status_shape.
    """
    entries = []
    for name, route_limits in limiter.limit_manager._decorated_limits.items():
        for route_limit in route_limits:
            provider = route_limit.limit_provider
            entries.append(
                {
                    "endpoint": name,
                    "limit": provider if isinstance(provider, str) else str(provider),
                }
            )
    for runtime_limit in limiter.limit_manager.default_limits:
        entries.append({"endpoint": "default", "limit": str(runtime_limit.limit)})
    return entries


# Rate-limit status, read-only.


@admin_bp.route("/rate-limit-status", methods=["GET"])
@admin_required
def rate_limit_status():
    """Returns {enabled, storage, storage_healthy, active_counter_keys,
    registered_limits}. Reads the live Flask-Limiter object (extensions.py)
    + Redis db 3 DBSIZE (null when storage is memory://)."""
    storage_url = os.getenv("RATELIMIT_STORAGE_URL", "memory://")
    is_redis = storage_url.startswith("redis")
    try:
        storage_healthy = bool(limiter.storage.check())
    except Exception:
        storage_healthy = False
    return jsonify(
        {
            "enabled": bool(limiter.enabled),
            "storage": "redis" if is_redis else "memory",
            "storage_healthy": storage_healthy,
            "active_counter_keys": _active_counter_keys(storage_url) if is_redis else None,
            "registered_limits": _registered_limits(),
        }
    )
