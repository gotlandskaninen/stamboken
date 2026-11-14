#!/usr/bin/env python3
"""
This file contains the main webserver of 'the herdbook'.

The server uses Flask to serve a React frontend, and connect to a postgres
database.
"""

import base64
import binascii
import contextlib
import datetime
import fcntl
import hashlib
import logging
import os
import random
import sys
import threading
import time
import uuid
from logging.handlers import TimedRotatingFileHandler
from urllib.parse import urlparse

import apscheduler.schedulers.background
import click
import redis
import requests
from flask import (
    Flask,
    Response,
    abort,
    g,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)
from flask.cli import AppGroup
from flask_caching import Cache
from flask_limiter.util import get_remote_address
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_session import Session
from flask_talisman import Talisman
from limits import parse as parse_limit
from peewee import fn
from utils.cert_acess import (
    check_certificate_s3,
    create_pdf_response,
    download_certificate_s3,
    get_certificate,
    get_certificate_data,
    sign_data,
    upload_certificate,
    verify_certificate_checksum,
    verify_signature,
)
from utils.cert_service_v2 import (
    certificate_form,
    certificate_update,
    update_breeding_if_changed,
)
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

import utils.external_auth  # isort:skip
import utils.data_access as da  # isort:skip
import utils.database as db  # isort:skip
import utils.settings as settings  # isort:skip
import utils.genebank_logging as gblogging  # isort:skip
import utils.genetics_service as genetics  # isort:skip
from utils import number_assets  # isort:skip
from utils.individual_commands import purge_command_free_text  # isort:skip
from utils.mail import purge_old_mail, send_pending  # isort:skip
from utils.inbox import queue_digests  # isort:skip
from utils import inbox_gmail  # isort:skip
from utils import inbox_purge  # isort:skip
from utils.inbox_interpreter import interpret_next  # isort:skip
from utils.members import try_auto_link_member  # isort:skip
from utils.legacy_compat import is_legacy_host, legacy_classroom_url  # isort:skip
from utils.redis_retry import reconnect_on_drop  # isort:skip

APP = Flask(__name__, static_folder="/static")


def _resolve_secret_key() -> str:
    # Fail-hard SECRET_KEY gate: production must never fall back
    # to a per-process random secret. Note: api and api-test read the same
    # Redis session store (db 2), so a production login also works on the
    # demo; a login made on api-test is marked and production refuses it
    # (_session_revoked). The sid cookie is unsigned in Flask-Session 0.8, so
    # SECRET_KEY does not gate session validity and rotating it does NOT
    # invalidate sessions (flush Redis db 2 for that). A stable shared secret
    # is still required for everything else Flask signs (e.g. flask-dance
    # OAuth state).
    key = os.getenv("SECRET_KEY")
    if key:
        return key
    if os.getenv("FLASK_ENV") == "production":
        raise RuntimeError(
            "SECRET_KEY is required when FLASK_ENV=production "
            "(api/api-test must share one stable secret; see "
            ".docker/api-variables.env.default)."
        )
    return "dev-secret-do-not-use-in-prod"


APP.secret_key = _resolve_secret_key()

# Configure app to work behind reverse proxy (Nginx)
APP.wsgi_app = ProxyFix(APP.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
# cookie options at https://flask.palletsprojects.com/en/1.1.x/security/
# Configurable directories (for CI/testing compatibility)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
SESSION_REDIS_URL = os.getenv("SESSION_REDIS_URL", "redis://redis:6379/2")
UPLOAD_DIR = os.getenv("UPLOAD_FOLDER", "/app/uppladdningar")

# Expected audience for Google ID tokens from the Next.js sign-in (the GIS
# client — same value as next-app's NEXT_PUBLIC_GOOGLE_CLIENT_ID, NOT the
# Flask OAuth client in auth.ini). Unset skips the audience check, so any
# Google app's tokens would verify — warn loudly in production. An empty
# string (e.g. a bare "GOOGLE_CLIENT_ID=" env line) must normalize to None:
settings.refuse_committed_signing_key()
settings.refuse_auto_validate_outside_demo()
settings.refuse_unsafe_mail_settings()
settings.refuse_unsafe_gmail_settings()
settings.refuse_private_folder_under_uploads()

# verify_oauth2_token would otherwise enforce audience "" and fail every login.
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID") or None
if not GOOGLE_CLIENT_ID and os.getenv("FLASK_ENV") == "production":
    APP.logger.warning("GOOGLE_CLIENT_ID is not set — Google ID token audience is not pinned")

# Create directories if they don't exist (will fail silently if no permissions)
for d in [UPLOAD_DIR]:
    try:
        os.makedirs(d, exist_ok=True)
    except PermissionError:
        pass  # Will fail later if actually needed

APP.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.getenv("FLASK_ENV") == "production",
    # Lax: every frontend is same-site, and it keeps cross-site form posts from carrying the session.
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_TYPE="redis",
    # Timeouts so a hung (not down) Redis fails requests instead of
    # deadlocking every gunicorn worker — session I/O is on every request.
    SESSION_REDIS=redis.Redis.from_url(
        SESSION_REDIS_URL,
        socket_connect_timeout=2,
        socket_timeout=2,
        health_check_interval=30,
        **reconnect_on_drop(),
    ),
    SESSION_PERMANENT=True,
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=31),
    SESSION_REFRESH_EACH_REQUEST=True,
    DEBUG=os.getenv("FLASK_DEBUG", "0") == "1",
    CACHE_TYPE="RedisCache",
    CACHE_REDIS_URL=REDIS_URL,
    CACHE_DEFAULT_TIMEOUT=300,
    UPLOAD_FOLDER=UPLOAD_DIR,
    PROFILE_UPLOAD_FOLDER=os.path.join(UPLOAD_DIR, "profiler"),
    MAX_CONTENT_LENGTH=11 * 1024 * 1024,  # 11MB — upload endpoint validates 10MB max
)


def _should_auto_validate_users() -> bool:
    # Decouples auto-validation from FLASK_ENV via the AUTO_VALIDATE_USERS
    # override. Production api-test sets it to true for the legacy test site;
    # that is safe only because production refuses api-test logins
    # (_session_revoked). Defaults to the legacy FLASK_ENV check when the
    # override is unset, so dev/test envs are unaffected.
    override = os.getenv("AUTO_VALIDATE_USERS")
    if override is not None:
        return override.lower() == "true"
    return os.getenv("FLASK_ENV") != "production"


def _not_validated_response():
    """
    What a non-validated user gets after a successful Google login.

    Old production redirected them to the Google Classroom course, and the
    legacy frontend has no onboarding of its own — so on a legacy host we keep
    doing that. Other hosts get a text answer; the token login used by v2
    returns its own JSON error with the course address.
    """
    if is_legacy_host():
        # nosemgrep: python.flask.security.open-redirect.open-redirect
        return redirect(legacy_classroom_url())
    return "Du behöver gå en kurs och bli validerad först kontakta admin@gotlandskaninen.se"


# CLI commands for genetics management
genetics_cli = AppGroup("genetics", help="Genetics management commands.")
APP.cli.add_command(genetics_cli)

from cli.seed import seed_cli  # noqa: E402

APP.cli.add_command(seed_cli)

from cli.members import members_cli  # noqa: E402

APP.cli.add_command(members_cli)

from cli.breeding import breeding_cli  # noqa: E402

APP.cli.add_command(breeding_cli)

from cli.gmail import gmail_cli  # noqa: E402

APP.cli.add_command(gmail_cli)


@genetics_cli.command("recompute-history")
@click.argument("genebank_id", type=int)
def recompute_history(genebank_id):
    """Reconcile the genetics history for a genebank (seconds)."""
    click.echo(genetics.reconcile_history(genebank_id))


@genetics_cli.command("rotate-epoch")
def rotate_epoch():
    """New genetics epoch for this database; run after a restore or demo sync replaced it."""
    click.echo(db.rotate_genetics_epoch())


@genetics_cli.command("backfill-history")
@click.argument("genebank_id", type=int)
@click.option("--start-year", type=int, default=None, hidden=True)
@click.option("--end-year", type=int, default=None, hidden=True)
def backfill_history(genebank_id, start_year, end_year):
    """Alias for recompute-history (the year range is ignored)."""
    click.echo(genetics.reconcile_history(genebank_id))


def _reconcile_all_history():
    """Nightly leader job; runs on a scheduler thread, so it closes that thread's connection itself."""
    try:
        for gb in da.get_all_genebanks():
            try:
                genetics.reconcile_history(gb.id)
            except Exception:
                APP.logger.exception("Nightly history reconcile failed for genebank %s", gb.id)
                genetics.ps._close_db_connection()  # pylint: disable=protected-access  # next genebank reconnects
    finally:
        genetics.ps._close_db_connection()  # pylint: disable=protected-access


def _purge_command_free_text():
    """Nightly leader job (ADR-0017), built as _reconcile_all_history: it closes its thread's connection itself.

    It purges the mail queue first, on its own, so neither purge failing skips the other."""
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        try:
            APP.logger.info("Purged %s mail queue rows", purge_old_mail(now))
        except Exception:  # pylint: disable=broad-except
            APP.logger.exception("Purging the mail queue failed")
        count = purge_command_free_text(now)
        APP.logger.info("Purged free text from %s command log rows", count)
    finally:
        genetics.ps._close_db_connection()  # pylint: disable=protected-access


def _purge_inbox():
    """Nightly leader job (docs/inkorg.md, "Gallring"), built as _send_mail: it closes its thread's connection.

    Each rule runs on its own inside inbox_purge.run, so one failing does not skip the others."""
    try:
        inbox_purge.run(datetime.datetime.now(datetime.timezone.utc))
    except Exception:  # pylint: disable=broad-except
        APP.logger.exception("The inbox purge failed")
    finally:
        genetics.ps._close_db_connection()  # pylint: disable=protected-access


def _send_mail():
    """Leader job every 30 s (docs/mejl.md), built as _reconcile_all_history: it closes its thread's connection."""
    try:
        send_pending()
    except Exception:  # pylint: disable=broad-except
        APP.logger.exception("Mail sender run failed")
    finally:
        genetics.ps._close_db_connection()  # pylint: disable=protected-access


def _queue_notice_digests():
    """Leader job at 07:00 (docs/inkorg.md), built as _send_mail: it closes its thread's connection."""
    try:
        APP.logger.info("Queued %s notice digests", queue_digests())
    except Exception:  # pylint: disable=broad-except
        APP.logger.exception("Queueing the notice digests failed")
    finally:
        genetics.ps._close_db_connection()  # pylint: disable=protected-access


def _read_gmail():
    """Leader job every 5 minutes (docs/inkorg-gmail.md), built as _send_mail: it closes its thread's connection.

    The app context is for the upload's image checks, which answer with Flask responses."""
    try:
        with APP.app_context():
            inbox_gmail.run()
    except Exception:  # pylint: disable=broad-except
        APP.logger.exception("Reading the Gmail mailbox failed")
    finally:
        genetics.ps._close_db_connection()  # pylint: disable=protected-access


def _interpret_document():
    """Leader job every minute (docs/inkorg.md, "Tolkning"), built as _send_mail: it closes its thread's connection."""
    try:
        interpret_next()
    except Exception:  # pylint: disable=broad-except
        APP.logger.exception("Interpreting an inbox document failed")
    finally:
        genetics.ps._close_db_connection()  # pylint: disable=protected-access


# Initialize security packages
# Flask-Talisman: Add security headers
Talisman(
    APP,
    force_https=False,  # nginx handles HTTPS termination; internal health checks need plain HTTP
    strict_transport_security=True,
    strict_transport_security_max_age=31536000,
    content_security_policy={
        "default-src": "'self'",
        "script-src": "'self' 'unsafe-inline' 'unsafe-eval'",
        "style-src": "'self' 'unsafe-inline'",
        "img-src": "'self' data: https:",
        "font-src": "'self'",
        "connect-src": "'self'",
        "frame-ancestors": "'none'",
    },
    content_security_policy_nonce_in=["script-src", "style-src"],
    referrer_policy="strict-origin-when-cross-origin",
)

# Flask-Limiter: Rate limiting
# Set RATELIMIT_ENABLED=false to disable (e.g. local-production, testing).
# The instance lives in app/extensions.py (ADR-0007 — blueprints must not
# import herdbook.py); storage is memory:// for dev/pytest and shared Redis
# db 3 in prod, fail-open on Redis blips (swallow_errors). Imported
# here (and thereby re-exported) so the @limiter.limit decorations below and
# the existing `from herdbook import APP, limiter` test boilerplate keep
# working unchanged.
from extensions import limiter  # noqa: E402

limiter.init_app(APP)

# /api/login and Basic auth's failed password checks share one bucket.
LOGIN_RATE_LIMIT = "5 per minute"
LOGIN_RATE_SCOPE = "login"

# pylint: disable=no-member
APP.logger.setLevel(logging.INFO)
file_handler = TimedRotatingFileHandler(f"{settings.service.logfolder}/APP.log", when="W6")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(
    gblogging.RequestFormatter(
        "[%(asctime)s] %(module)s.%(levelname)s: %(message)s, URL: %(url)s ",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)
APP.logger.addHandler(file_handler)
utils.external_auth.setup(APP)

Session(APP)

CACHE = Cache(APP)
LOGIN = LoginManager(APP)
LOGIN.login_view = "/api/login/google"

# Register domain-based Blueprints (ADR-0007)
from blueprints import register_blueprints  # noqa: E402
from blueprints.common import check_genebank_manager_access, problem  # noqa: E402

register_blueprints(APP)

# Rate-limit the public member-application endpoint (anonymous DB write).
# Attached here because `limiter` lives in this module — blueprints can't
# import it without a circular import (ADR-0007).
APP.view_functions["member_applications.create_application"] = limiter.limit("10 per hour")(
    APP.view_functions["member_applications.create_application"]
)


def _safe_redirect_url(url, default="/"):
    """Only allow same-site paths or same-host http(s) URLs to prevent open redirect.

    Browsers resolve 'http:host', '//host', '////host' and slash-backslash-host (also with a tab
    after the first slash) to another host. So a relative URL must start with exactly one '/',
    and backslashes and control characters are refused.
    """
    if not url or "\\" in url or any(ord(c) < 32 for c in url):
        return default
    parsed = urlparse(url)
    if parsed.scheme or parsed.netloc:
        same_host = parsed.scheme in ("http", "https") and parsed.netloc == request.host
        return url if same_host else default
    return url if url.startswith("/") and not url.startswith("//") else default


@LOGIN.unauthorized_handler
def unauthorized():
    """
    Custom unauthorized handler that returns 401 JSON for API requests
    instead of redirecting to login page. This is needed for compatibility
    with frontend applications that expect JSON responses.
    """
    # All /api/ paths return 401 JSON (frontends expect JSON, not redirects)
    if request.path.startswith("/api/"):
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    # For non-API browser requests, redirect to login
    return redirect(f"/api/login/google?next={request.url}")


@APP.errorhandler(429)
def rate_limit_exceeded(error):  # pylint: disable=unused-argument
    """
    Answer a rate-limited request with JSON instead of Flask-Limiter's HTML page.

    The legacy frontend's fetch helpers call resp.json() unconditionally, so an
    HTML 429 body makes the whole call throw instead of showing a message. The
    admin blueprint registers its own problem+json 429 handler, and a blueprint
    handler wins for its own routes, so this only covers the app-level routes.
    """
    return (
        jsonify({"status": "error", "message": "För många förfrågningar, försök igen om en stund"}),
        429,
    )


KINSHIP_LIFETIME = 300
DASHBOARD_LIFETIME = 3600  # Dashboard aggregates change rarely (hourly refresh)


# Before_request
# function that will update users last_active field in the database
# this will be called before every request
@APP.before_request
def before_request():
    """
    Callback that triggers before each request.
    - Updates users last active field
    - Sets PostgreSQL session variables for audit triggers
    """
    # load_user checks sessions that carry flask-login's _user_id; one with only
    # user_id never reaches it, but the legacy routes read user_id directly.
    if "_user_id" not in session and "user_id" in session and _session_revoked():
        session.clear()
    if current_user.is_authenticated:
        current_user.update_last_active()
        # Set audit context for PostgreSQL triggers (session-level)
        try:
            db.DATABASE.execute_sql(
                "SELECT set_config('audit.user', %s, false)",
                (current_user.username or current_user.email or "",),
            )
            db.DATABASE.execute_sql(
                "SELECT set_config('audit.ip', %s, false)",
                (request.remote_addr or "",),
            )
        except Exception:
            APP.logger.warning("Failed to set audit context", exc_info=True)


@APP.teardown_request
def teardown_request(exc=None):
    """Clear audit session variables after each request."""
    try:
        # Always attempt rollback — a handled DB error (caught by app code,
        # not passed via exc) can also leave the connection in aborted state.
        # Rollback is a no-op on clean connections.
        try:
            db.DATABASE.rollback()
        except Exception:
            pass
        # A number change made inside a route's own transaction moves its certificate/photo now.
        number_assets.finish()
        db.DATABASE.execute_sql("SELECT set_config('audit.user', '', false)")
        db.DATABASE.execute_sql("SELECT set_config('audit.ip', '', false)")
    except Exception:
        APP.logger.debug("Failed to clear audit context", exc_info=True)


def cors_origin_allowed(origin):
    """Only localhost dev servers, and only in development."""
    return os.getenv("FLASK_ENV") == "development" and urlparse(origin).hostname in ("localhost", "127.0.0.1")


@APP.after_request
def after_request(response):
    """
    Callback that triggers after each request. Currently this is used to set
    CORS headers to allow a different origin when using the development server.

    Every frontend reaches the API through its own host's /api/ proxy, so
    production sends no CORS headers: echoing any Origin with credentials
    would let every website read the API as the logged-in user.
    """

    origin = request.headers.get("Origin")
    if not origin or not cors_origin_allowed(origin):
        return response

    response.headers.add("Access-Control-Allow-Origin", origin)
    response.headers.add("Vary", "Origin")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type")
    response.headers.add("Access-Control-Allow-Methods", "GET,POST,PATCH")
    response.headers.add("Access-Control-Allow-Credentials", "true")

    return response


def _login_rate_limit(method):
    """
    Run the limiter's "test" or "hit" against /api/login's bucket. Fails open,
    like the limiter's swallow_errors, when it is disabled or storage is down.
    """
    if not (limiter.enabled and limiter.initialized):
        return True
    try:
        check = getattr(limiter.limiter, method)
        return check(parse_limit(LOGIN_RATE_LIMIT), get_remote_address(), LOGIN_RATE_SCOPE)
    except Exception:  # pylint: disable=broad-except
        APP.logger.exception("Login rate limit check failed, letting the request through")
        return True


@LOGIN.request_loader
def load_user_from_request(request):
    # Try to login using Basic Auth
    api_key = request.headers.get("Authorization")
    if api_key:
        api_key = api_key.replace("Basic ", "", 1)
        try:
            api_key = base64.b64decode(api_key)
        except (TypeError, binascii.Error):
            return None

        username = api_key[: api_key.find(b":")].decode()
        password = api_key[api_key.find(b":") + 1 :].decode()  # noqa: E203
        # The header checks a password on any route, so it draws on the
        # login budget; once spent, even the right password gets 429.
        if not _login_rate_limit("test"):
            abort(429)
        try:
            user = da.authenticate_user(username, password)
        except da.InactiveAccountError:
            # Lager 1 — deaktiverat konto får inte logga in via
            # Basic Auth heller; None ⇒ 401 nedströms.
            _login_rate_limit("hit")
            return None

        if user:
            APP.logger.info("User %s logged in from request header", user.username)

            session["user_id"] = user.uuid
            session.modified = True
            login_user(user)
            # Header auth is per-request: endpoints read session["user_id"]
            # during handling, but persisting it would mint a fresh 31-day
            # Redis key on every request (these clients ignore Set-Cookie).
            # The after_request hook below clears it before save_session,
            # so nothing is stored. No regenerate(): there is no
            # attacker-supplied sid to rotate away on a header-minted session.
            g._header_auth_session = True

            return user

        APP.logger.info("Failed login from header for %s", username)
        _login_rate_limit("hit")

    # we are not logged in.
    return None


@APP.after_request
def _drop_header_auth_session(response):
    # Runs before Flask calls save_session: clearing the session means no
    # session key is stored in Redis for a header-authenticated request
    # (a delete-cookie header may still be emitted, which cookie-less
    # machine clients ignore) — keeping Basic-auth effectively stateless.
    if g.get("_header_auth_session"):
        session.clear()
    return response


def _logout_epoch():
    return int(APP.config["SESSION_REDIS"].get(da.LOGOUT_EPOCH_KEY) or 0)


def _session_revoked():
    """
    Every login stamps the logout epoch into the session, and a mass
    logout increments it, so a session from before the last mass logout is
    dead even if an in-flight request wrote its key back after the sweep. A
    session without the stamp predates this check and dies at the first mass
    logout; until then it lives on, so deploying logs nobody out.

    A session minted by the demo API counts as revoked in production: the
    stores are shared, but demo account state (passwords, Google links,
    roles) is a stale or altered copy and must not grant production access.
    """
    if session.get("demo_login") and not settings.service.demo_instance:
        APP.logger.warning("Refused a session minted by the demo API")
        return True
    return session.get("logout_epoch", 0) < _logout_epoch()


def _stamp_login():
    # Called before user_id is set, marker before the Redis read: a session
    # saved after a failure here must never carry a demo user unmarked.
    if settings.service.demo_instance:
        session["demo_login"] = True
    session["logout_epoch"] = _logout_epoch()


# pylint: disable=unused-argument
@LOGIN.user_loader
def load_user(u_id):
    """
    Loads user information for flask-login.

    Currently u_id is not required, since user is loaded from the session.
    Returns None for deactivated accounts (layer 3 — belt on top of
    the fetch_user_info gate) so existing sessions die on the next request.
    """
    # Clearing (not just returning None) also logs out the legacy routes that
    # read session["user_id"] directly.
    if _session_revoked():
        session.clear()
        return None
    user = da.fetch_user_info(session.get("user_id", None))
    if user is not None and not user.is_active:
        return None
    return user


# Ensure upload directories exist
try:
    os.makedirs(APP.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(APP.config["PROFILE_UPLOAD_FOLDER"], exist_ok=True)
except OSError:  # EACCES, or EROFS on the demo API's read-only uploads mount
    APP.logger.warning("Could not create upload folders, assuming they exist")

# Allowed file extensions for different upload types
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_DOCUMENT_EXTENSIONS = {"pdf", "doc", "docx", "txt"}


def allowed_file(filename, file_type="image"):
    """Check if file has allowed extension for the specified type"""
    if not filename or "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()

    if file_type == "image":
        return extension in ALLOWED_IMAGE_EXTENSIONS
    elif file_type == "document":
        return extension in ALLOWED_DOCUMENT_EXTENSIONS
    else:
        return extension in ALLOWED_IMAGE_EXTENSIONS.union(ALLOWED_DOCUMENT_EXTENSIONS)


def get_upload_path(upload_type="profiler"):
    """Get the appropriate upload path for different content types"""
    paths = {
        "profiler": APP.config["PROFILE_UPLOAD_FOLDER"],
        "kaniner": os.path.join(APP.config["UPLOAD_FOLDER"], "kaniner"),
        "besattningar": os.path.join(APP.config["UPLOAD_FOLDER"], "besattningar"),
        "certifikat": os.path.join(APP.config["UPLOAD_FOLDER"], "certifikat"),
        "dokument": os.path.join(APP.config["UPLOAD_FOLDER"], "dokument"),
    }
    return paths.get(upload_type, APP.config["PROFILE_UPLOAD_FOLDER"])


# [Next.js] Profilhantering med bilduppladdning
@APP.route("/api/profile", methods=["GET", "PATCH"])
@login_required
def user_profile():
    """
    Handle user's own profile - GET to retrieve, PATCH to update profile settings
    """
    if request.method == "GET":
        user = da.fetch_user_info(session.get("user_id", None))
        if user:
            return jsonify(user.frontend_data())
        return jsonify({"status": "error", "message": "User not found"}), 404

    elif request.method == "PATCH":
        # Handle profile updates (profile picture and settings)
        profile_picture_url = None

        # Handle file upload for profile pictures
        if "profile_picture" in request.files:
            file = request.files["profile_picture"]
            if file and file.filename and allowed_file(file.filename, "image"):
                # Create unique filename for profile picture
                filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4().hex}_{filename}"
                file_path = os.path.join(get_upload_path("profiler"), unique_filename)

                try:
                    file.save(file_path)
                    profile_picture_url = unique_filename
                    APP.logger.info(f"Profile picture uploaded: {unique_filename}")
                except Exception as e:
                    APP.logger.error(f"Error uploading file: {e}")
                    return jsonify({"status": "error", "message": "Failed to upload image"})

        # Get settings from JSON or form data
        if request.content_type and "multipart/form-data" in request.content_type:
            settings = request.form.to_dict()
        else:
            settings = request.json or {}

        # Update profile
        user = da.fetch_user_info(session.get("user_id", None))
        if not user:
            return jsonify({"status": "error", "message": "User not found"}), 404

        try:
            # Update profile picture if uploaded
            if profile_picture_url:
                user.profile_picture = profile_picture_url

            # Update Google picture setting
            if "use_google_picture" in settings:
                user.use_google_picture = bool(settings["use_google_picture"])

            # Only the profile columns: a full-row save of this unlocked read
            # would write back a stale is_active/_privileges.
            user.save(only=[db.User.profile_picture, db.User.use_google_picture])
            return jsonify({"status": "updated", "message": "Profile updated successfully"})

        except Exception as e:
            APP.logger.error(f"Error updating profile: {e}")
            return jsonify({"status": "error", "message": "Failed to update profile"})


@APP.route("/api/user")
def get_user():
    """
    Returns information on the current logged in user, or 401 if not logged in.
    """
    user = da.fetch_user_info(session.get("user_id", None))
    if user is None:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    return jsonify(user.frontend_data())


@APP.route("/api/active_users", methods=["GET"])
@login_required
def get_active_users():
    minutes = request.args.get("minutes", default=15, type=int)
    active_users = da.get_active_users(minutes, session.get("user_id", None))
    return jsonify(active_users)


@APP.route("/api/manage/users")
def get_users():
    """
    Returns all users that the logged in user has access to. This is all users
    for admin, all users except admin users for managers, and None for regular
    users.
    """
    users = da.get_users(session.get("user_id", None))
    return jsonify(users=users)


@APP.route(
    "/api/manage/user/",
    defaults={"u_id": False},
    methods=["GET", "UPDATE", "PATCH", "POST"],
)
@APP.route("/api/manage/user/<u_id>", methods=["GET", "UPDATE", "PATCH", "POST"])
@login_required
def manage_user(u_id):
    """
    Returns user information and a list of all roles for the requested `u_id`.

    The return value from this function should be:
        JSON: {
            status: 'unchanged' | 'updated' | 'created' | 'success' | 'error',
            message?: string,
            data?: any
        }
    """

    # Handle file upload for profile pictures
    profile_picture_url = None
    if "profile_picture" in request.files:
        file = request.files["profile_picture"]
        if file and file.filename and allowed_file(file.filename):
            # Create unique filename
            filename = secure_filename(file.filename)
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            file_path = os.path.join(APP.config["UPLOAD_FOLDER"], unique_filename)

            try:
                file.save(file_path)
                profile_picture_url = unique_filename  # Only filename, not full URL
                APP.logger.info(f"Profile picture uploaded: {unique_filename}")
            except Exception as e:
                APP.logger.error(f"Error uploading file: {e}")
                return jsonify({"status": "error", "message": "Failed to upload image"})

    # Get form data (could be JSON or form data depending on upload)
    if request.content_type and "multipart/form-data" in request.content_type:
        form = request.form.to_dict()
    else:
        form = request.json if request.method != "GET" else {}

    # Add profile picture URL to form if uploaded
    if profile_picture_url:
        form["profile_picture"] = profile_picture_url

    if not u_id:
        # If not provided, default to current user.
        u_id = current_user.id
        if form:
            form["id"] = u_id

    if request.method == "GET":
        retval = da.get_user(u_id, session.get("user_id", None))
    if request.method in ("UPDATE", "PATCH"):
        retval = da.update_user(form, session.get("user_id", None))
    if request.method == "POST":
        retval = da.add_user(form, session.get("user_id", None))
    return jsonify(retval)


@APP.route("/api/manage/setpassword/", defaults={"u_id": False}, methods=["POST"])
@APP.route("/api/manage/setpassword/<u_id>", methods=["POST"])
def change_userpassword(u_id):
    """
    Set password for user u_id. Administrators can set password for any user.
    Non-administrators need to present the old password or a token.
    """

    if request.method != "POST":
        return abort(400)  # Makes the linter happy

    form = request.json

    if not current_user.is_authenticated:
        return abort(403)  # Makes the linter happy

    if not u_id:
        u_id = current_user.id
    retval = da.change_password(current_user, u_id, form)
    return jsonify(retval)


@APP.route("/api/manage/role", methods=["POST", "PATCH", "UPDATE"])
@login_required
def manage_roles():
    """
    Changes or adds roles for the user identified by `u_id`, and returns a
    status a json status message.
    The input data should be formatted like:
        {action: add | remove,
         role: owner | manager | viewer,
         user: <id>,
         herd | genebank: <id>
        }

    The return value will be formatted like:
        JSON: {
            status: 'unchanged' | 'updated' | 'created' | 'success' | 'error',
            message?: string,
            data?: any
        }
    """
    form = request.json
    status = da.update_role(form, session.get("user_id", None))
    return jsonify(status)


@APP.route("/api/manage/herd", methods=["POST", "PATCH"])
@login_required
def manage_herd():
    """
    Used to insert and update herd information in the database.
    Returns a message formatted like:
        JSON: {
            status: 'unchanged' | 'updated' | 'created' | 'success' | 'error',
            message?: string,
            data?: any
        }
    """
    form = request.json
    status = {"status": "error", "message": "Unknown request"}

    old_genebank_ids = set()
    if request.method == "PATCH" and "id" in form:
        try:
            from utils.cache_invalidation import get_genebank_id_for_herd_id

            old_genebank_ids = get_genebank_id_for_herd_id(form["id"])
        except Exception as e:
            APP.logger.warning(f"Could not resolve old genebank for herd ID {form.get('id')}: {e}")

    if request.method == "POST":
        status = da.add_herd(form, session.get("user_id", None))
    elif request.method == "PATCH":
        status = da.update_herd(form, session.get("user_id", None))

    # Invalidate after successful mutation
    try:
        if status.get("status") in ("success", "updated", "created"):
            from utils.cache_invalidation import get_genebank_id_for_herd_id, trigger_invalidation

            new_genebank_ids = set()
            if "id" in form:
                new_genebank_ids = get_genebank_id_for_herd_id(form["id"])
            elif "data" in status and isinstance(status["data"], dict) and "id" in status["data"]:
                new_genebank_ids = get_genebank_id_for_herd_id(status["data"]["id"])

            for gid in old_genebank_ids | new_genebank_ids:
                trigger_invalidation(gid)
    except Exception as e:
        APP.logger.warning(f"Cache invalidation failed after manage_herd: {e}")

    return jsonify(status)


# [Next.js] Phase 17 — genebank metadata edit
@APP.route("/api/manage/genebank/<int:gb_id>", methods=["PATCH"])
@login_required
def edit_genebank(gb_id):
    """
    Edit genebank metadata. Body: {"name"?: str}.

    Auth: admin OR manager(gb) of this genebank.
    Audit: genebank UPDATE captured by the audit trigger;
    changed_by is set per request in before_request().
    """
    user = current_user
    body = request.get_json(silent=True) or {}

    gb = db.Genebank.get_or_none(db.Genebank.id == gb_id)
    if gb is None:
        return problem(404, "Genbank saknas", f"Ingen genbank med id {gb_id}.", type="genebank-not-found")

    if not user.is_admin:
        err = check_genebank_manager_access(user, gb_id)
        if err is not None:
            return err

    allowed = {"name"}
    unknown = set(body.keys()) - allowed
    if unknown:
        return problem(400, "Okända fält", f"Okända fält: {sorted(unknown)}", type="unknown-fields")

    try:
        updated = da.edit_genebank(gb, body, actor=user)
    except ValueError as err:
        return problem(400, "Ogiltig indata", str(err), type="invalid-field-value")
    return jsonify(updated), 200


# [Next.js] Phase 17 — scoped herd management endpoints.
# The legacy body-h_id POST/PATCH /api/manage/herd above stays intact
# for legacy manage.tsx; the v2 panel uses these numeric-id URLs.


def _opt_bool_arg(name):
    """Optional ?name=true|false query arg → True/False/None."""
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw == "true"


@APP.route("/api/manage/herd", methods=["GET"])
@login_required
def list_all_herds():
    """
    List every herd for the adminpanel list page.

    Query params: genebank_id (int), active (bool), has_owner (bool),
    q (free text — herd code/name/contact), page, page_size.

    Auth: admin only. Manager(gb) lists their gb's herds via the
    existing GET /api/genebank/<gb_id>.
    """
    user = current_user
    if not user.is_admin:
        return problem(
            403, "Admin-behörighet krävs", "Endast admin får lista alla besättningar.", type="admin-required"
        )
    return jsonify(
        da.list_all_herds(
            user,
            genebank_id=request.args.get("genebank_id", type=int),
            active=_opt_bool_arg("active"),
            has_owner=_opt_bool_arg("has_owner"),
            search=request.args.get("q"),
            page=request.args.get("page", 1, type=int),
            page_size=request.args.get("page_size", 50, type=int),
        )
    ), 200


def _resolve_admin_herd(h_ref):
    """
    Herd by herd code (G1274) OR numeric Herd.id. The v2 adminpanel
    uses the CODE in user-facing URLs (URL:er ska vara begripliga —
    same principle as /stamboken/individ/<code>); numeric ids stay
    accepted for backward compatibility. The CODE lookup runs FIRST:
    nothing enforces letter-prefixed codes, so an all-numeric legacy
    code must resolve as itself — never as another herd's primary key.
    """
    herd = db.Herd.get_or_none(db.Herd.herd == h_ref)
    if herd is None and h_ref.isdigit():
        herd = db.Herd.get_or_none(db.Herd.id == int(h_ref))
    return herd


@APP.route("/api/manage/herd/<h_ref>", methods=["GET"])
@login_required
def get_herd_for_admin(h_ref):
    """
    Fetch one herd by numeric Herd.id or herd code — the shape the
    adminpanel uses everywhere else.

    Auth: admin OR manager(gb) of the herd's genebank.
    """
    user = current_user
    herd = _resolve_admin_herd(h_ref)
    if herd is None:
        return problem(404, "Besättning saknas", f"Ingen besättning med id {h_ref}.", type="herd-not-found")
    if not user.is_admin:
        err = check_genebank_manager_access(user, herd.genebank_id)
        if err is not None:
            return err
    return jsonify(da.get_herd_for_admin(user, herd)), 200


@APP.route("/api/manage/herd/<h_ref>", methods=["PATCH"])
@login_required
def edit_herd(h_ref):
    """
    Edit herd metadata via id/code path. Body ⊆
    HERD_EDITABLE_FIELDS. Auth: admin OR manager(gb) of the herd's
    genebank.
    """
    user = current_user
    herd = _resolve_admin_herd(h_ref)
    if herd is None:
        return problem(404, "Besättning saknas", f"Ingen besättning med id {h_ref}.", type="herd-not-found")
    if not user.is_admin:
        err = check_genebank_manager_access(user, herd.genebank_id)
        if err is not None:
            return err
    body = request.get_json(silent=True) or {}
    unknown = set(body.keys()) - da.HERD_EDITABLE_FIELDS
    if unknown:
        return problem(400, "Okända fält", f"Okända fält: {sorted(unknown)}", type="unknown-fields")
    try:
        updated = da.edit_herd(herd, body, actor=user)
    except ValueError as err:
        return problem(400, "Ogiltig indata", str(err), type="invalid-field-value")
    # Parity with legacy manage_herd (herdbook.py:679–693): herd edits
    # (esp. is_active) feed cached genebank views — best-effort invalidate.
    # (Added for cache-correctness parity.)
    try:
        from utils.cache_invalidation import trigger_invalidation

        trigger_invalidation(herd.genebank_id)
    except Exception as e:
        APP.logger.warning(f"Cache invalidation failed after edit_herd: {e}")
    return jsonify(updated), 200


@APP.route("/api/breeding/date/<birth_date>")
@login_required
def breedings_from_date(birth_date):
    breedings = da.get_breeding_events_by_date(birth_date, session.get("user_id", None))
    return jsonify(breedings=breedings)


@APP.route("/api/breeding/id/<breeding_id>")
@login_required
def breeding(breeding_id):
    breeding = da.get_breeding_event(breeding_id, session.get("user_id", None))
    return jsonify(breeding=breeding)


@APP.route("/api/breeding/<h_id>", methods=["GET", "POST"])
@login_required
def herd_breeding_list(h_id):
    """
    Returns a list of all breeding events connected to a given herd.
    If post search for a matching breeding given the birth date
    calculate breed date from birth date to find a match or take the
    exact birth date if it exists.
    """
    breedings = da.get_breeding_events_with_ind(h_id, session.get("user_id", None))

    if request.method == "POST":
        form = request.json
        birth_date = da.validate_date(form.get("birth_date", None))
        end = birth_date - datetime.timedelta(days=26)
        start = birth_date - datetime.timedelta(days=38)
        breedings = next(
            (
                item
                for item in breedings
                if item["father"] == form["father"]
                and item["mother"] == form["mother"]
                and (
                    start
                    <= (
                        da.validate_date(item.get("birth_date")) - datetime.timedelta(days=30)
                        if item.get("breed_date") is None
                        else da.validate_date(item.get("breed_date"))
                    )
                    <= end
                    or (
                        da.validate_date(item.get("birth_date")) == birth_date
                        if item.get("birth_date") is not None
                        else None
                    )
                )
            ),
            None,
        )

    return jsonify(breedings=breedings)


@APP.route("/api/breeding/nextind/", methods=["POST"])
@login_required
def breeding_next_indidivual_number():
    """
    Returns the next correct individual number for a breeding ID event
    """

    if request.method == "POST":
        form = request.json
        breeding_id = form.get("id", None)

        return jsonify(
            da.next_individual_number(
                herd=form["breeding_herd"],
                birth_date=form["birth_date"],
                breeding_event=breeding_id,
            )
        )


@APP.route("/api/breeding", methods=["POST", "PATCH"])
@login_required
def register_breeding():
    """
    Used to insert and update breeding events in the database.
    Returns a message formatted like:
        JSON: {
            status: 'success' | 'error',
            message?: string
        }
    """
    form = request.json
    status = {"status": "error", "message": "Unknown request"}

    # Capture old genebank for PATCH (update_breeding can change breeding_herd)
    old_genebank_ids = set()
    if request.method == "PATCH" and "id" in form:
        try:
            from utils.cache_invalidation import get_genebank_ids_for_breeding

            old_genebank_ids = get_genebank_ids_for_breeding(form["id"])
        except Exception as e:
            APP.logger.warning(f"Could not resolve old genebank for breeding {form.get('id')}: {e}")

    if request.method == "POST":
        status = da.register_breeding(form, session.get("user_id", None))
    if request.method == "PATCH":
        status = da.update_breeding(form, session.get("user_id", None))

    # Invalidate after successful mutation
    try:
        if status.get("status") == "success":
            from utils.cache_invalidation import get_genebank_ids_for_breeding, trigger_invalidation

            new_genebank_ids = set()
            if "breeding_id" in status:
                new_genebank_ids = get_genebank_ids_for_breeding(status["breeding_id"])
            elif "id" in form:
                new_genebank_ids = get_genebank_ids_for_breeding(form["id"])
            for gid in old_genebank_ids | new_genebank_ids:
                trigger_invalidation(gid)
    except Exception as e:
        APP.logger.warning(f"Cache invalidation failed after register_breeding: {e}")

    return jsonify(status)


@APP.route("/api/breeding/delete", methods=["POST"])
@login_required
def delete_breeding():
    """
    Used to delete breeding events in the database.
    Returns a message formatted like:
        JSON: {
            status: 'success' | 'error',
            message?: string
        }
    """
    breeding_id = request.json
    status = {"status": "error", "message": "Unknown request"}

    # Capture genebank before deletion
    genebank_ids = set()
    if breeding_id:
        try:
            from utils.cache_invalidation import get_genebank_ids_for_breeding

            genebank_ids = get_genebank_ids_for_breeding(breeding_id)
        except Exception as e:
            APP.logger.warning(f"Could not resolve genebank for breeding {breeding_id}: {e}")

    if request.method == "POST":
        status = da.delete_breeding(breeding_id, session.get("user_id", None))

    if status.get("status") == "success":
        try:
            from utils.cache_invalidation import trigger_invalidation

            for gid in genebank_ids:
                trigger_invalidation(gid)
        except Exception as e:
            APP.logger.warning(f"Cache invalidation failed after delete_breeding: {e}")

    return jsonify(status)


@APP.route("/api/birth", methods=["POST"])
@login_required
def register_birth():
    """
    Used to update breeding events in the database with birth information.
    Returns a message formatted like:
        JSON: {
            status: 'success' | 'error',
            message?: string
        }
    """
    form = request.json
    status = {"status": "error", "message": "Unknown request"}
    if request.method == "POST":
        status = da.register_birth(form, session.get("user_id", None))

    # Invalidate after successful birth registration
    if status.get("status") == "success" and form.get("id"):
        try:
            from utils.cache_invalidation import get_genebank_ids_for_breeding, trigger_invalidation

            for gid in get_genebank_ids_for_breeding(form["id"]):
                trigger_invalidation(gid)
        except Exception as e:
            APP.logger.warning(f"Cache invalidation failed after register_birth: {e}")

    return jsonify(status)


@APP.route("/api/colors")
@login_required
def colors():
    """
    Returns all the legal colors for all genebanks.
    """
    return jsonify(da.get_colors())


@APP.route("/api/login", methods=["POST"])
@limiter.shared_limit(LOGIN_RATE_LIMIT, scope=LOGIN_RATE_SCOPE)  # Limit login attempts
def login_handler():
    """
    Parses a login form and sets session variables when logged in.
    If login fails the system will return `None`.
    The login form should be in json-format like:

        {'username': '<user>', 'password': '<pass>'}
    """
    if current_user.is_authenticated:
        return get_user()
    form = request.json
    # Authenticate the user and return a user object
    try:
        user = da.authenticate_user(form.get("username"), form.get("password"))
    except da.InactiveAccountError:
        # Layer 1 — deactivated account; same shape as the existing
        # 401 failure path, Swedish message per spec.
        if is_legacy_host():
            # Old contract, same as any other failed login: legacy's handleLogin
            # treats a truthy JSON body as the user, so the 401 error object
            # reads as a successful login. The account stays refused either way.
            return jsonify(None)
        return (
            jsonify({"status": "error", "message": "Kontot är inaktiverat. Kontakta styrelsen."}),
            401,
        )
    if user:
        _stamp_login()
        session["user_id"] = user.uuid
        session.modified = True
        login_user(user)
        # regenerate() rotates the sid to prevent session fixation.
        # Known benign race, accepted: a concurrent request still carrying the
        # pre-login sid can re-upsert that (anonymous) key under SESSION_REFRESH_
        # EACH_REQUEST; the authenticated session is unaffected and the orphan
        # expires via TTL. Inherent to sid rotation (cf. Django cycle_key).
        APP.session_interface.regenerate(session)
        APP.logger.info(f"Logging in user: {user.username} via the admin password interface")
    else:
        APP.logger.warning(f"User name {form.get('username')} is not able to login using admin interface ")
        if is_legacy_host():
            # Old contract: a failed login answered 200 with a null body.
            # Legacy's handleLogin treats any JSON body as a user, so the 401
            # error object get_user() returns reads as a successful login.
            return jsonify(None)
    return get_user()


# The Google profile columns the login routes refresh. They save only these: the
# user row was read without a lock, so a full-row save would write back a stale
# is_active/_privileges and undo a concurrent deactivation or role change.
_GOOGLE_PROFILE_COLUMNS = [db.User.google_picture, db.User.google_name, db.User.google_email]


def _link_member_if_any(user, verified_email) -> None:
    """
    Auto-link a Member to this freshly-authenticated User by matching the
    address the identity provider just verified against
    Member.workspace_email (the provisioned login, NOT the contact email).
    Never User.email: any user can rewrite that through
    PATCH /api/manage/user/. No verified address, no link.
    Case-insensitive — the unique index is on LOWER(workspace_email) and
    Google may deliver different casing.

    Takes NO locks and opens NO transaction: the write goes through
    link_member_user(), which owns membership → user → person FOR UPDATE
    itself and re-checks everything under them, so this
    unlocked probe only picks a candidate. The domain guard
    (@gotlandskaninen.se only) lives inside try_auto_link_member.
    """
    if not verified_email:
        return
    unlinked = (
        db.Member.select()
        .where((fn.LOWER(db.Member.workspace_email) == verified_email.lower()) & (db.Member.user.is_null(True)))
        .first()
    )
    if unlinked:
        try_auto_link_member(unlinked, user)  # owns its own transaction + locks


# [Next.js] Google OAuth token-verifiering
@APP.route("/api/auth/google", methods=["POST"])
@limiter.limit("10 per minute")  # Limit OAuth attempts
def google_token_login():
    """
    Verify Google ID token from Next.js frontend and authenticate user.
    Expects JSON: {'credential': '<google_id_token>'}
    """
    if current_user.is_authenticated:
        return get_user()

    form = request.json
    if form is None:
        return jsonify({"error": "Request must be JSON with Content-Type: application/json"}), 400

    credential = form.get("credential")

    if not credential:
        return jsonify({"error": "Missing Google credential"}), 400

    try:
        # Verify the Google ID token
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        # Verify and decode the token. Pinning the audience rejects Google ID
        # tokens minted for any other OAuth app (401 via ValueError below).
        idinfo = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )

        # Extract user info from token
        google_user_id = idinfo.get("sub")
        email = idinfo.get("email")
        name = idinfo.get("name")
        picture = idinfo.get("picture")
        email_verified = idinfo.get("email_verified", False)
        hosted_domain = idinfo.get("hd")

        if not email_verified:
            APP.logger.warning(f"Google login attempt with unverified email: {email}")
            return jsonify({"error": "Email not verified"}), 400

        # Check if user belongs to the required domain
        if hosted_domain != "gotlandskaninen.se":
            APP.logger.warning(f"Google login attempt from unauthorized domain: {hosted_domain} ({email})")
            return jsonify({"error": "Access restricted to gotlandskaninen.se domain"}), 403

        if not email or not email.endswith("@gotlandskaninen.se"):
            APP.logger.warning(f"Google login attempt from unauthorized email domain: {email}")
            return jsonify({"error": "Access restricted to gotlandskaninen.se domain"}), 403

        # Try to authenticate user with Google ID
        user = da.authenticate_with_credentials("google", google_user_id)

        if user and not user.is_active:
            # Layer 2 — deactivated account may not log in via Google.
            APP.logger.warning(f"Google login attempt for inactive account: {user.username or user.email}")
            return jsonify({"error": "Kontot är inaktiverat. Kontakta styrelsen."}), 403

        if user and not user.validated:
            if _should_auto_validate_users():
                user.validated = True
                user.save(only=[db.User.validated])  # see _GOOGLE_PROFILE_COLUMNS
            else:
                # 401, not 403: the Next.js caller maps 403 to the domain-restriction text.
                msg = (
                    f"Du behöver gå webbkursen och bli validerad först: {legacy_classroom_url()} "
                    "Frågor: admin@gotlandskaninen.se"
                )
                return jsonify({"error": msg}), 401

        if user:
            # Update user with Google profile data in database
            user.google_picture = picture
            user.google_name = name
            user.google_email = email
            user.save(only=_GOOGLE_PROFILE_COLUMNS)

            # After the save: a save that raises must not leave a session that
            # carries user_id without flask-login's _user_id.
            _stamp_login()
            session["user_id"] = user.uuid
            session.modified = True
            login_user(user)
            APP.session_interface.regenerate(session)
            APP.logger.info(f"Google login successful for user: {user.username} ({email})")
            # Phase 8: link a pre-provisioned Member to this OAuth-verified
            # user. get_user() re-fetches from the DB, so a newly granted
            # owner role is visible in this same response.
            _link_member_if_any(user, email)
            return get_user()
        else:
            # User doesn't exist with this Google ID
            APP.logger.warning(f"Google login failed - no user found for Google ID: {google_user_id} ({email})")
            return jsonify({"error": "User not found or not authorized"}), 401

    except ValueError as e:
        # Invalid token
        APP.logger.error(f"Invalid Google token: {str(e)}")
        return jsonify({"error": "Invalid Google token"}), 401
    except Exception as e:
        APP.logger.error(f"Google login error: {str(e)}")
        return jsonify({"error": "Authentication failed"}), 500


@APP.route("/api/login/<string:service>", methods=["GET", "POST"])
def external_login_handler(service):
    """
    Do an external authentication. The special service
    available responds with a list of the enabled services.
    """

    if service == "available":
        return jsonify(utils.external_auth.available_methods())

    if service not in utils.external_auth.available_methods():
        return "null"  # bad method

    if not session.get("link_account") and current_user.is_authenticated:
        # nosemgrep: python.flask.security.open-redirect.open-redirect
        return redirect(_safe_redirect_url(request.referrer))

    if not utils.external_auth.authorized(APP, service):
        APP.logger.debug(f"Need to do external auth for service {service}")
        # Save the return_to URL in session for after OAuth
        return_to = request.args.get("return_to")
        if return_to:
            session["return_to_after_oauth"] = return_to
        return redirect(url_for(f"{service}.login"))

    # Hack to reuse the same external handler for both linking and login
    if session.get("link_account"):
        return redirect(f"/api/link/{service}")

    persistent_id = utils.external_auth.get_persistent(service)

    user = da.authenticate_with_credentials(service, persistent_id)

    if user and not user.validated:
        if _should_auto_validate_users():
            # Auto-validate user since this environment opted in via env var
            user.validated = True
            user.save(only=[db.User.validated])  # see _GOOGLE_PROFILE_COLUMNS
        else:
            return _not_validated_response()

    if user and user.validated:
        APP.logger.info(
            "Logging in user %s (%s - #%d) by persistent id %s for service %s, refferrer is %s",
            user.username,
            user.email,
            user.id,
            persistent_id,
            service,
            request.referrer,
        )
        _stamp_login()
        session["user_id"] = user.uuid
        session.modified = True
        login_user(user)
        APP.session_interface.regenerate(session)
        # Phase 8: auto-link Member on OAuth completion, then reload so the
        # profile save below writes fresh privileges — saving this stale
        # in-memory instance would clobber the just-granted owner role.
        verified_email = utils.external_auth.google_verified_email() if service == "google" else None
        _link_member_if_any(user, verified_email)
        # Reload unfiltered: fetch_user_info hides an account deactivated mid-login (the
        # provider calls above can take long), and the profile save below writes only
        # _GOOGLE_PROFILE_COLUMNS, so it cannot undo that deactivation.
        user = db.User.get_by_id(user.id)

        # Save Google profile data (picture, name, email)
        # The id_token may not contain picture/name — fetch from userinfo endpoint instead
        # google_email is the CMS identity: only ever a verified address.
        if service == "google":
            userinfo = utils.external_auth.google_userinfo()
            if userinfo:
                user.google_picture = userinfo.get("picture") or user.google_picture
                user.google_name = userinfo.get("name") or user.google_name
                user.google_email = verified_email or user.google_email
                user.save(only=_GOOGLE_PROFILE_COLUMNS)
            else:
                # Fallback to id_token if userinfo fails
                idtoken = utils.external_auth.google_idtoken()
                if idtoken:
                    if idtoken.get("picture"):
                        user.google_picture = idtoken["picture"]
                    if idtoken.get("name"):
                        user.google_name = idtoken["name"]
                    if verified_email:
                        user.google_email = verified_email
                    user.save(only=_GOOGLE_PROFILE_COLUMNS)

        # Check for saved return_to URL from before OAuth
        return_to = session.pop("return_to_after_oauth", None)
        if return_to:
            return redirect(_safe_redirect_url(return_to))

        if "accounts.google" in request.referrer:
            return redirect("/")
        # nosemgrep: python.flask.security.open-redirect.open-redirect
        return redirect(_safe_redirect_url(request.referrer))

    if not utils.external_auth.get_autocreate(service):
        # No user - give up
        return None

    accountdetails = utils.external_auth.get_account_details(service)
    APP.logger.debug(f"Got accountdetails {repr(accountdetails)}")

    # Auto-validate users in environments that opt in (e.g. api-test).
    auto_validate = _should_auto_validate_users()

    user = da.register_user(
        accountdetails["email"],
        None,
        username=accountdetails["username"],
        validated=auto_validate,
        fullname=accountdetails["fullname"] if "fullname" in accountdetails else None,
        privileges=[
            {"level": "viewer", "genebank": 1},
            {"level": "viewer", "genebank": 2},
        ],
    )

    if not user:
        APP.logger.error(
            "Automatic registering of user with e-mail %s (persistent id %s) for service %s FAILED",
            accountdetails["email"],
            persistent_id,
            service,
        )
        return None

    # register_user() adopts an existing account with this address. Never hand
    # this Google identity to one that someone can already sign in to while no
    # admin has validated it: anyone can set their own User.email to the address
    # of a member who has not signed in yet (update_user then clears validated)
    # and capture that login. Decided on the account register_user
    # returned, so a concurrent email change cannot slip in between. A
    # brand-new account has no authenticator yet and is linked as before.
    if not user.validated and db.Authenticators.select().where(db.Authenticators.user == user.id).exists():
        APP.logger.warning("Refusing to link %s to unvalidated existing user #%d", service, user.id)
        return _not_validated_response()

    linked = da.link_account(user, service, persistent_id)

    if not linked:
        APP.logger.error(
            "Linked of of user with e-mail %s (persistent id %s) for service %s FAILED",
            accountdetails["email"],
            persistent_id,
            service,
        )
        return None

    # google_email is the CMS identity; google_details() verified this address.
    db.User.update(google_email=accountdetails["email"]).where(db.User.id == user.id).execute()

    APP.logger.info(
        "Automatically registered user with e-mail %s (persistent id %s) for service %s",
        persistent_id,
        accountdetails["email"],
        service,
    )

    # If we got a herd from external, setup ownership
    if "herd" in accountdetails:
        for h in ["G", "M"]:
            h = h + accountdetails["herd"]
            herd = da.herd_to_herdid(h.strip())
            if herd:
                form = {
                    "action": "add",
                    "role": "owner",
                    "user": user.id,
                    "herd": herd,
                }
                da.update_role(form, user.uuid, skip_role_check=True)
            else:
                APP.logger.warning(f"Could not find herd id for herd {h.strip()}")

    # FIXME: this is how we "really" log in the user
    if user.validated:
        _stamp_login()
        session["user_id"] = user.uuid
        login_user(user)
        APP.session_interface.regenerate(session)
        # Phase 8: auto-link Member on first OAuth login of an auto-
        # registered user (domain guard lives in try_auto_link_member).
        # google_details() returns only an email_verified address.
        _link_member_if_any(user, accountdetails.get("email"))
        return_to = session.pop("return_to_after_oauth", None)  # Get the return_to url and remove it from the session
        if return_to:
            return redirect(_safe_redirect_url(return_to))
        return redirect("/start")
    else:
        return _not_validated_response()


@APP.route("/api/link/<string:service>", methods=["GET", "POST"])
def external_link_handler(service):
    """
    Link user to selected account. Will be logged in to that service if not.
    """
    # Something odd

    if service == "reset":
        if session.get("link_account"):
            del session["link_account"]
        return "reset"

    if service not in utils.external_auth.available_methods():
        return "null"  # bad method

    if not current_user.is_authenticated:
        return "null"  # FIXME: error code instead?

    if not utils.external_auth.authorized(APP, service):
        # Not authorized? Go back to login
        session["link_account"] = True
        return redirect(f"/api/login/{service}")

    persistent = utils.external_auth.get_persistent(service)
    linked = da.link_account(current_user, service, persistent)

    if not linked:
        # Not linked
        return "null"  # FIXME: error code instead?

    return str(current_user.id)


@APP.route("/api/linked", methods=["GET", "POST"])
def external_linked_accounts_handler():
    """
    Return linked services for logged in user.
    """
    # Something odd

    if not current_user.is_authenticated:
        return "null"  # FIXME: Return error code instead?

    linked = da.linked_accounts(current_user)

    if not linked:
        return "null"  # FIXME: error code instead?

    return jsonify(linked)


@APP.route("/api/unlink/<string:service>", methods=["POST"])
def external_unlink_handler(service):
    """
    Link user to selected account. Should be logged in to that service.
    """
    # Something odd

    if not current_user.is_authenticated:
        return "null"  # FIXME: 403 instead?

    unlinked = da.unlink_account(current_user, service)
    if not unlinked:
        return "null"  # FIXME: Error code instead?
    return "1"


@APP.route("/api/logout")
def logout():
    """
    Logs out the current user from the system.
    """
    logout_user()
    # Full clear (not just a user_id pop) so save_session deletes the Redis
    # record outright instead of leaving an anonymous shell with up to 31
    # days of TTL.
    session.clear()
    return jsonify({"status": "success", "message": "Logged out successfully"})


@APP.route("/api/genebanks")
@APP.route("/api/genebank/<int:g_id>")
@login_required
def genebank(g_id=None):
    """
    Returns information on the genebank given by `g_id`, or a list of all
    genebanks if no `g_id` is given.
    """
    user_id = session.get("user_id", None)
    if g_id:
        return jsonify(da.get_genebank(g_id, user_id))
    return jsonify(genebanks=da.get_genebanks(user_id))


@APP.route("/api/genebank/<int:g_id>/individuals")
@login_required
def genebank_individuals(g_id):
    """
    Returns individuals for the genebank given by `g_id`, if allowed for the
    currently logged in user.
    """
    user_id = session.get("user_id", None)
    return jsonify(individuals=da.get_individuals(g_id, user_id))


@APP.route("/api/herd/<h_id>")
@login_required
def herd(h_id):
    """
    Returns information on the herd given by `h_id`.
    """
    data = da.get_herd(h_id, session.get("user_id", None))
    return jsonify(data)


@APP.route("/api/individual/<i_number>")
@login_required
def individual(i_number):
    """
    Returns information on the individual given by `i_number`.
    """
    user_id = session.get("user_id", None)
    ind = da.get_individual(i_number, user_id)

    if ind:
        try:
            # Snapshots hold animals by origin genebank; ind["genebank_id"] is the current herd's.
            gb = db.Herd.get_by_id(ind["origin_herd"]["id"]).genebank_id
            # One snapshot for both values: a rebuild published in between must not mix versions.
            with _pinned_snapshot(gb):
                ind["inbreeding"] = "%.2f" % (get_ind_inbreeding(i_number, gb) * 100)
                ind["MK"] = "%.2f" % (get_ind_mean_kinship(i_number, gb) * 100)
        except requests.exceptions.ConnectionError as error:
            APP.logger.error("%s", error)
            ind["inbreeding"] = ind["inbreeding"] if "inbreeding" in ind else None
            ind["MK"] = None
    return jsonify(ind)


@APP.route("/api/individual", methods=["PATCH", "POST"])
@login_required
# Legacy's yearly-report batch (BatchRabbitUpdateForm.tsx) sends one PATCH per
# rabbit, and 18 regular herds have more than 50 living rabbits — a 50/min
# window 429'd the batch mid-way. Raised so a 100-rabbit herd finishes inside
# one window; the route is authenticated-only.
@limiter.limit("300 per minute; 2000 per hour")  # Limit individual edits
def edit_individual():
    """
    Updates an individual on `PATCH`, or creates a new individual on `POST`.

    The return value from this function should be:
        JSON: {
            status: 'success' | 'error',
            message?: string,
        }
    """
    form = request.json
    retval = None
    try:
        if request.method == "PATCH":
            retval = da.update_individual(
                form, session.get("user_id", None), genebank_change_reason=da.LEGACY_GENEBANK_CHANGE_NOTE
            )
        if request.method == "POST":
            retval = da.add_individual(form, session.get("user_id", None))
    except Exception as error:
        APP.logger.error("Unexpected error when edit individual: " + str(error))
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Be Admin kolla server loggarna ange {datetime.datetime.now()}",
                }
            ),
            500,
        )

    # Invalidate caches — separate try/except so mutation success isn't masked
    try:
        if retval and retval.get("status") == "success":
            from utils.cache_invalidation import get_genebank_id_for_herd, trigger_invalidation

            if form.get("herd"):
                herd_code = form["herd"] if isinstance(form["herd"], str) else form["herd"].get("herd", "")
                for gid in get_genebank_id_for_herd(herd_code):
                    trigger_invalidation(gid)
    except Exception as e:
        APP.logger.warning(f"Cache invalidation failed after edit_individual: {e}")

    return jsonify(retval)


@APP.route("/api/checkindnumber", methods=["POST"])
@login_required
def check_ind_number():
    """
    Check if indivdual number exists.

    The return value from this function should be:
        JSON: {
            status: 'success' | 'error',
            message?: string,
        }
    """
    form = request.json
    try:
        if db.Individual.select().where(db.Individual.number == form["number"]).exists():
            return jsonify(
                {
                    "status": "error",
                    "message": "Individual number already exists",
                }
            )
    except Exception as error:
        APP.logger.error("Unexpected error when checking number: " + str(error))
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Be Admin kolla server loggarna ange {datetime.datetime.now()}",
                }
            ),
            500,
        )
    return jsonify(
        {
            "status": "success",
            "message": "No duplicates",
        }
    )


@APP.route("/api/checkintyg", methods=["POST"])
@login_required
def check_ind_intyg():
    """
    Check  if certificate/intyg  exists.

    The return value from this function should be:
        JSON: {
            status: 'success' | 'error',
            message?: string,
        }
    """
    form = request.json
    try:
        if form.get("certificate", None) is not None:
            if db.Individual.select().where(db.Individual.certificate == form["certificate"]).exists():
                return jsonify(
                    {
                        "status": "error",
                        "message": "Individual certificate already exists",
                    }
                )
    except Exception as error:
        APP.logger.error("Unexpected error when checking number: " + str(error))
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Be Admin kolla server loggarna ange {datetime.datetime.now()}",
                }
            ),
            500,
        )
    return jsonify(
        {
            "status": "success",
            "message": "No duplicates",
        }
    )


def _memo_key(snap):
    version, day, definition, algorithm, epoch = snap.key
    # The epoch identifies the database: a restored one can repeat a version already memoized.
    return f"{epoch}:{version}:{day.isoformat()}:{definition}:{algorithm}"


def _pinned_snapshot(g_id):
    """Pin the genebank's current snapshot for the block; no pin when there is none or reading it fails."""
    try:
        snap = genetics.snapshot(int(g_id))
    except Exception:  # pylint: disable=broad-except
        snap = None  # the readers inside fail (or return empty) exactly as before
    return genetics.ps.pinned(snap) if snap is not None else contextlib.nullcontext()


def _on_snapshot(g_id, cached, *params):
    """Run a memoized genetics body on one pinned snapshot, cached under that snapshot's key.

    A result computed on snapshot v is stored under v even if v+1 is published
    meanwhile, so it can never be served as v+1. Without a snapshot (a failed
    cold build) the body runs uncached and returns the service's empty result;
    when reading the snapshot fails, the uncached body fails as it always did.
    The memoized `_<name>_cached` bodies take `snap_key` only as part of the cache key.
    """
    g_id = int(g_id)
    try:
        snap = genetics.snapshot(g_id)
    except Exception:  # pylint: disable=broad-except
        snap = None
    if snap is None:
        return cached.uncached(g_id, None, *params)
    with genetics.ps.pinned(snap):
        return cached(g_id, _memo_key(snap), *params)


def get_ind_inbreeding(i_number, g_id):
    """
    Returns  the inbreeding coefficient of the individual given by `i_number`.
    """
    coefficients = get_inbreeding(g_id)
    if i_number in coefficients:
        return coefficients[i_number]
    return 0


def _genetics_access_denied(g_id):
    """403 response unless the logged-in user may see genebank `g_id`, else None."""
    if g_id not in current_user.accessible_genebanks:
        return jsonify({"status": "error", "message": "Åtkomst nekad"}), 403
    return None


@APP.route("/api/<int:g_id>/inbreeding/")
@login_required
def inbreeding(g_id):
    """
    Returns all inbreeding coefficient of the genebank given by `g_id`.

    Requires authentication.
    """
    if (denied := _genetics_access_denied(g_id)) is not None:
        return denied
    inb_coeffcient = get_inbreeding(int(g_id))
    return jsonify(inb_coeffcient)


def get_inbreeding(g_id):
    """
    Get inbreeding coefficients for all individuals in the genebank given by `g_id`.
    Uses Python genetics module (replaced R-API).
    """
    return _on_snapshot(g_id, _get_inbreeding_cached)


# A failed computation returns {}; response_filter keeps it out of the cache.
@CACHE.memoize(timeout=KINSHIP_LIFETIME, response_filter=bool)
def _get_inbreeding_cached(g_id, snap_key):  # pylint: disable=unused-argument
    try:
        return genetics.get_inbreeding(g_id)
    except Exception as ex:
        APP.logger.error(f"Could not calculate inbreeding data: {ex}")
        return {}


@APP.route("/api/<int:g_id>/kinship/")
@login_required
def kinship(g_id):
    """
    Returns kinship matrix of the genebank given by `g_id`.

    Requires authentication.
    """
    if (denied := _genetics_access_denied(g_id)) is not None:
        return denied
    return jsonify(get_kinship(int(g_id)))


def get_kinship(g_id):
    """
    Get kinship matrix for active individuals in the genebank given by `g_id`.
    Uses Python genetics module (replaced R-API).
    """
    return _on_snapshot(g_id, _get_kinship_cached)


# A failed computation returns {}; response_filter keeps it out of the cache.
@CACHE.memoize(timeout=KINSHIP_LIFETIME, response_filter=bool)
def _get_kinship_cached(g_id, snap_key):  # pylint: disable=unused-argument
    try:
        return genetics.get_kinship_matrix(g_id)
    except Exception as ex:
        APP.logger.error(f"Could not calculate kinship data: {ex}")
        return {}


def get_ind_mean_kinship(i_number, g_id):
    """
    Returns the mean kinship coefficient of the individual given by `i_number`.
    belonging to the genebank given by `g_id`.
    In case the individual is not active, we return 0.
    """
    mk_values = get_mean_kinship(g_id)
    return mk_values[i_number] if i_number in mk_values else 0


@APP.route("/api/<int:g_id>/meankinship/")
@login_required
def mean_kinship(g_id):
    """
    Returns the mean kinship list for the Genebank given by `g_id`.

    Requires authentication.
    """
    if (denied := _genetics_access_denied(g_id)) is not None:
        return denied
    return jsonify(get_mean_kinship(int(g_id)))


def get_mean_kinship(g_id):
    """
    Get mean kinship for all active individuals in the genebank given by `g_id`.
    Uses Python genetics module (replaced R-API).
    """
    return _on_snapshot(g_id, _get_mean_kinship_cached)


# A failed computation returns {}; response_filter keeps it out of the cache.
@CACHE.memoize(timeout=KINSHIP_LIFETIME, response_filter=bool)
def _get_mean_kinship_cached(g_id, snap_key):  # pylint: disable=unused-argument
    try:
        return genetics.get_mean_kinship(g_id)
    except Exception as ex:
        APP.logger.error(f"Could not calculate mean kinship data: {ex}")
        return {}


def get_population_metrics(g_id):
    """Get population metrics for genebank, shared across workers via Redis."""
    return _on_snapshot(g_id, _get_population_metrics_cached)


@CACHE.memoize(timeout=DASHBOARD_LIFETIME)
def _get_population_metrics_cached(g_id, snap_key):  # pylint: disable=unused-argument
    return genetics.get_population_metrics(g_id)


def get_founder_statistics(g_id):
    """Get founder statistics for genebank, shared across workers via Redis."""
    return _on_snapshot(g_id, _get_founder_statistics_cached)


@CACHE.memoize(timeout=DASHBOARD_LIFETIME)
def _get_founder_statistics_cached(g_id, snap_key):  # pylint: disable=unused-argument
    return genetics.get_founder_statistics(g_id)


def get_founders_at_risk(g_id):
    """Get founders at risk for genebank, shared across workers via Redis."""
    return _on_snapshot(g_id, _get_founders_at_risk_cached)


@CACHE.memoize(timeout=DASHBOARD_LIFETIME)
def _get_founders_at_risk_cached(g_id, snap_key):  # pylint: disable=unused-argument
    return genetics.get_founders_at_risk(g_id)


def get_genetic_priorities(g_id):
    """Get genetic priorities for genebank, shared across workers via Redis."""
    return _on_snapshot(g_id, _get_genetic_priorities_cached)


@CACHE.memoize(timeout=DASHBOARD_LIFETIME)
def _get_genetic_priorities_cached(g_id, snap_key):  # pylint: disable=unused-argument
    return genetics.get_genetic_priorities(g_id)


def get_breeding_suggestions(g_id, max_pairs=20, max_inbreeding=0.0625, max_per_male=3, max_per_female=1):
    """Get breeding suggestions, shared across workers via Redis."""
    return _on_snapshot(g_id, _get_breeding_suggestions_cached, max_pairs, max_inbreeding, max_per_male, max_per_female)


@CACHE.memoize(timeout=DASHBOARD_LIFETIME)
def _get_breeding_suggestions_cached(g_id, snap_key, max_pairs, max_inbreeding, max_per_male, max_per_female):  # pylint: disable=unused-argument
    return genetics.get_breeding_suggestions(
        g_id,
        max_pairs=max_pairs,
        max_inbreeding=max_inbreeding,
        max_per_male=max_per_male,
        max_per_female=max_per_female,
    )


@APP.route("/api/testbreed", methods=["POST"])
@login_required
def testbreed():
    """
    Calculate the inbreeding coefficient for a potential offspring.
    Uses Python genetics module (replaced R-API).

    Requires authentication.
    """
    payload = request.json
    APP.logger.info(f"Testbreed calculation input {payload}")
    try:
        genebank_id = int(payload.get("genebankId"))
        # Unregistered parents fall through to the snapshot of `genebank_id`, so gate it here.
        if (denied := _genetics_access_denied(genebank_id)) is not None:
            return denied
        male_id = payload.get("male", "")
        female_id = payload.get("female", "")

        # Registered pair: computed through the pedigree snapshot
        user_id = session.get("user_id", None)
        father = da.get_individual(male_id, user_id)
        mother = da.get_individual(female_id, user_id)

        if mother and father:
            offspring_coi = genetics.calculate_testbreed(genebank_id, male_id, female_id)
        else:
            # One or both parents are not registered
            # Extract parent information from payload
            male_parents = None
            female_parents = None

            male_gf = payload.get("maleGF") or None
            male_gm = payload.get("maleGM") or None
            if male_gf or male_gm:
                male_parents = (male_gf, male_gm)

            female_gf = payload.get("femaleGF") or None
            female_gm = payload.get("femaleGM") or None
            if female_gf or female_gm:
                female_parents = (female_gf, female_gm)

            offspring_coi = genetics.calculate_testbreed(
                genebank_id,
                male_id,
                female_id,
                male_parents=male_parents,
                female_parents=female_parents,
            )

    # Also genetics.SnapshotNotReady: a supplied animal is missing from a stale snapshot whose
    # rebuild did not finish in time; answered like any other failure, never as 0.
    except Exception as ex:  # pylint: disable=broad-except
        APP.logger.error(f"Testbreed calculation error: {ex}")
        return jsonify({"error": "Error processing your request"}), 500

    formatted_offspring_coi = round(offspring_coi * 100, 2)
    APP.logger.info(f"Testbreed calculation result {formatted_offspring_coi}")
    return jsonify({"offspringCOI": formatted_offspring_coi})


# =============================================================================
# [Next.js] Population Metrics Endpoints (Phase 4)
# =============================================================================


@APP.route("/api/<int:g_id>/population-metrics/")
@login_required
def population_metrics(g_id):
    """
    Returns comprehensive population metrics for the genebank.

    Requires authentication and genebank manager/admin access.

    Includes:
    - population_size: Total individuals
    - n_active: Active individuals
    - n_founders: Founder count
    - founder_equivalents: FE value (Lacy 1989)
    - mean_inbreeding: Average inbreeding coefficient
    - max_inbreeding: Maximum inbreeding coefficient
    - mean_kinship: Average mean kinship
    - effective_population_size: Realised Ne from individual ΔF over the
      reference population (Gutiérrez et al. 2008); null when not estimable
    - delta_f: Mean individual ΔF behind that Ne; null when not estimable
    - ne_method, ne_se, ne_n: Ne method, standard error and animals used
    - expected_offspring_f: Expected offspring F under random mating (null without both sexes)
    - mean_equiv_gen: Average equivalent complete generations
    - mean_full_gen: Average full generations
    - mean_max_gen: Average maximum generations
    """
    try:
        genebank_id = int(g_id)
        user_id = session.get("user_id", None)
        user = da.fetch_user_info(user_id)

        if not user or not (user.is_admin or genebank_id in (user.is_manager or [])):
            return jsonify({"status": "error", "message": "Åtkomst nekad"}), 403

        metrics = get_population_metrics(genebank_id)
        return jsonify(metrics)
    except Exception as ex:
        APP.logger.error(f"Could not calculate population metrics: {ex}")
        return jsonify({"error": "Error calculating population metrics"}), 500


@APP.route("/api/<int:g_id>/founder-statistics/")
@login_required
def founder_statistics(g_id):
    """
    Returns founder statistics for the genebank.

    Requires authentication and genebank manager/admin access.

    Includes:
    - n_founders: Number of founders contributing to the reference population
    - n_founders_total: Number of founders in the whole pedigree
    - founder_equivalents: FE value
    - proportional_loss: Proportion of the founders' gene diversity lost (mean MK)
    - top_founders: Top 20 founders by contribution
    - population_size: Number of active individuals
    """
    try:
        genebank_id = int(g_id)
        user_id = session.get("user_id", None)
        user = da.fetch_user_info(user_id)

        if not user or not (user.is_admin or genebank_id in (user.is_manager or [])):
            return jsonify({"status": "error", "message": "Åtkomst nekad"}), 403

        stats = get_founder_statistics(genebank_id)
        return jsonify(stats)
    except Exception as ex:
        APP.logger.error(f"Could not calculate founder statistics: {ex}")
        return jsonify({"error": "Error calculating founder statistics"}), 500


@APP.route("/api/<int:g_id>/founders-at-risk/")
@login_required
def founders_at_risk(g_id):
    """
    Returns founders at risk of losing their genetic contribution.

    Requires authentication and genebank manager/admin access.
    # [Next.js]
    """
    try:
        genebank_id = int(g_id)
        user_id = session.get("user_id", None)
        user = da.fetch_user_info(user_id)

        if not user or not (user.is_admin or genebank_id in (user.is_manager or [])):
            return jsonify({"status": "error", "message": "Åtkomst nekad"}), 403

        at_risk = get_founders_at_risk(genebank_id)
        return jsonify({"status": "success", "data": at_risk})
    except Exception as ex:
        APP.logger.error(f"Could not calculate founders at risk: {ex}")
        return jsonify({"error": "Error calculating founders at risk"}), 500


@APP.route("/api/<int:g_id>/genetics-trends/")
@login_required
def genetics_trends(g_id):
    """Returns historical genetic metrics trends.
    # [Next.js]
    """
    try:
        genebank_id = int(g_id)
        user_id = session.get("user_id", None)
        user = da.fetch_user_info(user_id)

        if not user or not (user.is_admin or genebank_id in (user.is_manager or [])):
            return jsonify({"status": "error", "message": "Åtkomst nekad"}), 403

        start_year = request.args.get("start_year", type=int)
        end_year = request.args.get("end_year", type=int)

        trends = genetics.get_genetics_trends(genebank_id, start_year, end_year)
        return jsonify({"status": "success", "data": trends})
    except Exception as ex:
        APP.logger.error(f"Could not fetch genetics trends: {ex}")
        return jsonify({"error": "Error fetching genetics trends"}), 500


@APP.route("/api/<int:g_id>/generation-numbers/")
@login_required
def generation_numbers(g_id):
    """
    Returns generation numbers for all individuals in the genebank.

    Requires authentication and genebank manager/admin access.

    For each individual:
    - max_gen: Maximum generations to any founder
    - full_gen: Complete generations (all ancestors known)
    - equiv_gen: Equivalent complete generations
    """
    try:
        genebank_id = int(g_id)
        user_id = session.get("user_id", None)
        user = da.fetch_user_info(user_id)

        if not user or not (user.is_admin or genebank_id in (user.is_manager or [])):
            return jsonify({"status": "error", "message": "Åtkomst nekad"}), 403

        gen_numbers = genetics.get_generation_numbers(genebank_id)
        return jsonify(gen_numbers)
    except Exception as ex:
        APP.logger.error(f"Could not calculate generation numbers: {ex}")
        return jsonify({"error": "Error calculating generation numbers"}), 500


@APP.route("/api/<int:g_id>/pedigree-completeness/")
@login_required
def pedigree_completeness(g_id):
    """
    Returns pedigree completeness index for all individuals.

    Requires authentication and genebank manager/admin access.

    For each individual, returns completeness (0.0-1.0) at each generation level.
    """
    try:
        genebank_id = int(g_id)
        user_id = session.get("user_id", None)
        user = da.fetch_user_info(user_id)

        if not user or not (user.is_admin or genebank_id in (user.is_manager or [])):
            return jsonify({"status": "error", "message": "Åtkomst nekad"}), 403

        max_gen = max(1, min(request.args.get("max_generations", 5, type=int), 10))
        pci = genetics.get_pedigree_completeness(genebank_id, max_generations=max_gen)
        return jsonify(pci)
    except Exception as ex:
        APP.logger.error(f"Could not calculate pedigree completeness: {ex}")
        return jsonify({"error": "Error calculating pedigree completeness"}), 500


@APP.route("/api/<int:g_id>/effective-population-size/")
@login_required
def effective_population_size(g_id):
    """
    Returns effective population size (Ne) estimate.

    Requires authentication and genebank manager/admin access.

    Returns:
    - ne: Effective population size
    - delta_f: Rate of inbreeding used in calculation
    - r_squared: R² of the regression fit
    - method: Calculation method used
    """
    try:
        genebank_id = int(g_id)
        user_id = session.get("user_id", None)
        user = da.fetch_user_info(user_id)

        if not user or not (user.is_admin or genebank_id in (user.is_manager or [])):
            return jsonify({"status": "error", "message": "Åtkomst nekad"}), 403

        ne_data = genetics.get_effective_population_size(genebank_id)
        return jsonify(ne_data)
    except Exception as ex:
        APP.logger.error(f"Could not calculate effective population size: {ex}")
        return jsonify({"error": "Error calculating effective population size"}), 500


@APP.route("/api/<int:g_id>/gene-drop/")
@login_required
def gene_drop_statistics(g_id):
    """
    Returns gene drop simulation statistics.

    Requires authentication and genebank manager/admin access.

    This is computationally expensive. Use n_iterations parameter to control precision.

    Returns:
    - founder_genome_equivalents: FGE from simulation
    - gene_diversity: Expected heterozygosity
    - genome_contributions: Simulated founder contributions
    - allele_retention: Probability each founder's alleles survive
    """
    try:
        genebank_id = int(g_id)
        user_id = session.get("user_id", None)
        user = da.fetch_user_info(user_id)

        if not user or not (user.is_admin or genebank_id in (user.is_manager or [])):
            return jsonify({"status": "error", "message": "Åtkomst nekad"}), 403

        n_iterations = max(1, min(request.args.get("n_iterations", 1000, type=int), 10000))
        seed = request.args.get("seed", None, type=int)
        stats = genetics.get_gene_drop_statistics(genebank_id, n_iterations=n_iterations, seed=seed)
        return jsonify(stats)
    except Exception as ex:
        APP.logger.error(f"Could not run gene drop simulation: {ex}")
        return jsonify({"error": "Error running gene drop simulation"}), 500


@APP.route("/api/<int:g_id>/genetic-priorities/")
@login_required
def genetic_priorities(g_id):
    """
    Returns genetic conservation priorities for all active individuals.

    Requires authentication and genebank manager/admin access.
    # [Next.js]
    """
    try:
        genebank_id = int(g_id)
        user_id = session.get("user_id", None)
        user = da.fetch_user_info(user_id)

        if not user or not (user.is_admin or genebank_id in (user.is_manager or [])):
            return jsonify({"status": "error", "message": "Åtkomst nekad"}), 403

        priorities = get_genetic_priorities(genebank_id)
        return jsonify({"status": "success", "data": priorities})
    except Exception as ex:
        APP.logger.error(f"Could not calculate genetic priorities: {ex}")
        return jsonify({"error": "Error calculating genetic priorities"}), 500


@APP.route("/api/<int:g_id>/breeding-suggestions/")
@login_required
def breeding_suggestions(g_id):
    """
    Returns breeding pair suggestions using Dynamic MK Selection.

    Query parameters:
    - max_pairs: Maximum number of pairs (default 10)
    - max_inbreeding: Maximum offspring F (default 0.0625)
    - max_per_male: Max times a male can appear (default 3)
    - max_per_female: Max times a female can appear (default 1)

    Requires authentication and genebank manager/admin access.
    # [Next.js]
    """
    try:
        genebank_id = int(g_id)
        user_id = session.get("user_id", None)
        user = da.fetch_user_info(user_id)

        if not user or not (user.is_admin or genebank_id in (user.is_manager or [])):
            return jsonify({"status": "error", "message": "Åtkomst nekad"}), 403

        max_pairs = min(request.args.get("max_pairs", 20, type=int), 50)
        max_inbreeding = round(min(request.args.get("max_inbreeding", 0.0625, type=float), 0.25), 4)
        max_per_male = min(request.args.get("max_per_male", 3, type=int), 10)
        max_per_female = min(request.args.get("max_per_female", 1, type=int), 10)

        suggestions = get_breeding_suggestions(
            genebank_id,
            max_pairs=max(max_pairs, 1),
            max_inbreeding=max(max_inbreeding, 0.0),
            max_per_male=max(max_per_male, 1),
            max_per_female=max(max_per_female, 1),
        )
        return jsonify({"status": "success", "data": suggestions})
    except Exception as ex:
        APP.logger.error(f"Could not calculate breeding suggestions: {ex}")
        return jsonify({"error": "Error calculating breeding suggestions"}), 500


class _CertificateRefused(Exception):
    """A refused legacy certificate request, raised inside its transaction so nothing commits."""

    def __init__(self, message, result=None):
        super().__init__(message)
        # roster_alive_exceeds_6w: how many kits the breeder must mark dead (a new field, ADR-0006)
        self.extra = {key: result[key] for key in ("must_mark_dead",) if key in (result or {})}


def _sign_stored_certificate(ind_data, user_id, form, issue_digital=False):
    """
    Apply the certificate form, then sign and upload a PDF rendered from the re-read rabbit, all
    in one transaction: a refused breeding or individual update, a failed signing or a
    failed upload commits nothing, and the body never reaches the PDF or the S3 key.
    Returns (signed pdf, re-read individual dict). Raises _CertificateRefused.
    """
    with db.DATABASE.atomic():
        # Global lock order: Breeding, then the rabbit + the litter's parents (update_breeding locks them).
        da.lock_individual_for_edit(ind_data["id"], None, with_parents=True)
        # The route read the rabbit before the lock: a certificate issued by another route or a renumber
        # committed since must not be overwritten by that read. Re-read it and decide on that row;
        # update_individual re-checks the edit right and refuses a voided rabbit under this lock.
        locked = db.Individual.get_by_id(ind_data["id"])
        if issue_digital and (locked.certificate or locked.digital_certificate):
            raise _CertificateRefused("Certificate already exists")
        if not issue_digital and locked.digital_certificate is None:
            raise _CertificateRefused("Certificate was not updated")
        ind_data = locked.as_dict()
        result = update_breeding_if_changed(ind_data, form, user_id)
        if result and result.get("status") == "error":
            raise _CertificateRefused(result["message"])
        # update_individual also refuses a first certificate past the litter quota.
        result = da.update_individual(certificate_update(ind_data, form), user_id, issue_digital=issue_digital)
        if result.get("status") == "error":
            raise _CertificateRefused(result["message"], result)
        ind_data = da.get_individual(locked.number, user_id)
        pdf_bytes = get_certificate(get_certificate_data(dict(ind_data), user_id))
        signed_data = sign_data(pdf_bytes)
        # The S3 key is the number: wait for a renumber still moving its assets (as a photo upload does).
        number_assets.lock_number(ind_data["number"], xact=True)
        if not upload_certificate(pdf_bytes=signed_data.getvalue(), ind_number=ind_data["number"]):
            raise _CertificateRefused("Certificate could not be uploaded")
    return signed_data, ind_data


@APP.route("/api/certificates/update/<i_number>", methods=["PATCH"])
@login_required
def update_certificate(i_number):
    """
    Returns an updated pdf of the individual given by `i_number`.
    """
    user_id = session.get("user_id", None)
    ind_data = da.get_individual(i_number, user_id)
    # get_individual currently returns a dict, not an individual
    if ind_data is None:
        return jsonify({"response": "Individual not found"}), 404
    # Read access is not enough to sign; 404 is this route's refusal status.
    if not da.fetch_user_info(user_id).can_edit(ind_data["id"]):
        return jsonify({"response": "Forbidden"}), 404

    certificate_exists = ind_data.get("digital_certificate", None)
    uploaded = False

    try:
        present = check_certificate_s3(ind_number=ind_data["number"])
        if certificate_exists and present:
            signed_data, ind_data = _sign_stored_certificate(ind_data, user_id, certificate_form(request.json))
            uploaded = True
    except _CertificateRefused as exc:
        return jsonify({"response": str(exc), **exc.extra}), 404
    except da.HerdTrackingError as exc:  # e.g. the rabbit changed before the lock
        return jsonify({"response": exc.detail}), 404
    except HTTPException:
        raise
    except Exception as ex:  # pylint: disable=broad-except
        APP.logger.error("Unexpected error while updating certificate: " + str(ex))
        return jsonify({"response": "Error processing your request"}), 404

    # Invalidate caches after certificate update
    try:
        from utils.cache_invalidation import get_genebank_id_for_herd, trigger_invalidation

        origin_herd = ind_data.get("origin_herd", {})
        herd_code = origin_herd.get("herd", "") if isinstance(origin_herd, dict) else str(origin_herd)
        for gid in get_genebank_id_for_herd(herd_code):
            trigger_invalidation(gid)
    except Exception as e:
        APP.logger.warning(f"Cache invalidation failed after update_certificate: {e}")

    if uploaded:
        return create_pdf_response(
            pdf_bytes=signed_data.getvalue(),
            obj_name=f"{ind_data['certificate']}.pdf",
        )

    return jsonify({"response": "Certificate was not updated"}), 404


@APP.route("/api/certificates/issue/<i_number>", methods=["GET", "POST"])
@login_required
def issue_certificate(i_number):
    """
    Returns an issued pdf certificate of the individual given by `i_number`.
    """
    user_id = session.get("user_id", None)
    ind_data = da.get_individual(i_number, user_id)
    # get_individual currently returns a dict, not an individual
    if ind_data is None:
        return jsonify({"response": "Individual not found"}), 404

    certificate_exists = ind_data.get("digital_certificate", None)
    paper_certificate_exists = ind_data.get("certificate", None)

    if request.method == "GET":
        try:
            present = check_certificate_s3(ind_number=ind_data["number"])
            if certificate_exists and present:
                cert = download_certificate_s3(i_number)
                return create_pdf_response(pdf_bytes=cert, obj_name=f"{i_number}_certificate.pdf")
        except Exception as ex:  # pylint: disable=broad-except
            print(ex)
            return jsonify({"response": "Error processing your request"}), 400

    elif request.method == "POST":
        if certificate_exists or paper_certificate_exists:
            return jsonify({"response": "Certificate already exists"}), 400
        # Read access is not enough to sign; 400 is this route's refusal status.
        if not da.fetch_user_info(user_id).can_edit(ind_data["id"]):
            return jsonify({"response": "Forbidden"}), 400

        try:
            signed_data, ind_data = _sign_stored_certificate(
                ind_data, user_id, certificate_form(request.json), issue_digital=True
            )
        except _CertificateRefused as exc:
            return jsonify({"response": str(exc), **exc.extra}), 400
        except da.HerdTrackingError as exc:  # e.g. the rabbit changed before the lock
            return jsonify({"response": exc.detail}), 400
        except HTTPException:
            raise
        except Exception as ex:  # pylint: disable=broad-except
            print(ex)
            return jsonify({"response": "Error processing your request"}), 400

        # Invalidate caches after certificate issuance
        try:
            from utils.cache_invalidation import get_genebank_id_for_herd, trigger_invalidation

            origin_herd = ind_data.get("origin_herd", {})
            herd_code = origin_herd.get("herd", "") if isinstance(origin_herd, dict) else str(origin_herd)
            for gid in get_genebank_id_for_herd(herd_code):
                trigger_invalidation(gid)
        except Exception as e:
            APP.logger.warning(f"Cache invalidation failed after issue_certificate: {e}")

        cert_number = ind_data["digital_certificate"]
        APP.logger.info(f"Digital certificate for {ind_data['number']} was created with number {cert_number}")
        return create_pdf_response(pdf_bytes=signed_data.getvalue(), obj_name=f"{cert_number}.pdf")


@APP.route("/api/certificates/preview/<i_number>", methods=["POST", "GET"])
@login_required
def preview_certificate(i_number):
    """
    Returns a preview of a pdf certificate of the individual given by `i_number`.
    """
    user_id = session.get("user_id", None)
    ind = da.get_individual(i_number, user_id)
    if ind is None:
        return jsonify({"response": "Individual not found"}), 404

    if request.method == "POST":
        form = request.json
        ind.update(**form, certificate=ind["digital_certificate"])
        data = get_certificate_data(ind, user_id)
        pdf_bytes = get_certificate(data)
    elif request.method == "GET":
        data = get_certificate_data(ind, user_id)
        pdf_bytes = get_certificate(data)

    return create_pdf_response(pdf_bytes=pdf_bytes.getvalue(), obj_name="preview.pdf")


@APP.route("/api/certificates/verify/<i_number>", methods=["POST"])
@login_required
def verify_certificate(i_number):
    """
    Returns whether an pdf certificate has been issued by us and matches our checksum.
    """
    user_id = session.get("user_id", None)
    ind = da.get_individual(i_number, user_id)
    if ind is None:
        return jsonify({"response": "Individual not found"}), 404

    uploaded_bytes = request.get_data()
    present, signed = False, False

    try:
        checksum = hashlib.sha256(uploaded_bytes).hexdigest()
        signed = verify_signature(uploaded_bytes)
        present = verify_certificate_checksum(i_number, checksum=checksum)
    except Exception as ex:  # pylint: disable=broad-except
        APP.logger.info("Unexpected error while verifying certificate " + str(ex))
        return (
            jsonify({"response": "Oväntat fel vid verifiering av intyget kontakta Admin."}),
            400,
        )

    if present and signed:
        return jsonify({"response": "Certificate is valid"}), 200
    elif not present and signed:
        return (
            jsonify({"response": "Certificate valid but file not present"}),
            202,
        )

    return (
        jsonify({"response": "The uploaded certificate is not valid"}),
        404,
    )


@APP.route("/api/herd/<h_id>/yearlyreport", methods=["GET", "POST"])
@login_required
def herd_yearly_report(h_id):
    """Get or create yearly report for a herd."""
    user_id = session.get("user_id", None)
    user = da.fetch_user_info(user_id)

    if not user:
        return jsonify({"status": "error", "message": "User not found"}), 404

    if not user.can_edit(h_id):
        return jsonify({"status": "error", "message": "Not authorized"}), 403

    # Fetch the herd data using the existing get_herd function
    herd_data = da.get_herd(h_id, user_id)
    if not herd_data:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Herd not found or access denied",
                }
            ),
            404,
        )

    # Get the herd_id from the herd_data
    herd_id = herd_data["id"]

    if request.method == "GET":
        # Get the round_id from query parameters
        round_id = request.args.get("round_id", type=int)
        if not round_id:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Report round ID is required",
                    }
                ),
                400,
            )

        # Get the report for the specific round
        report = da.get_yearly_report_by_round(herd_id, round_id)
        if report:
            return jsonify({"status": "success", "report": report})
        else:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "No report found for this round",
                    }
                ),
                404,
            )

    elif request.method == "POST":
        # Create or update the yearly report
        form = request.json
        result = da.save_yearly_report(herd_id, form, user)
        if result["status"] == "success":
            return jsonify(result)
        else:
            return jsonify(result), 400


@APP.route("/api/manage/yearly_report_rounds", methods=["GET"])
@login_required
def get_yearly_report_rounds():
    user_id = session.get("user_id", None)
    rounds = da.get_yearly_report_rounds_with_counts(user_id)
    if rounds is not None:
        return jsonify({"status": "success", "rounds": rounds})
    else:
        return jsonify({"status": "error", "message": "Unauthorized"})


@APP.route("/api/manage/yearly_report_round", methods=["POST"])
@login_required
def create_yearly_report_round():
    """
    Creates a new YearlyReportRound.
    Only accessible to admin or manager users.
    """
    user_id = session.get("user_id", None)
    form = request.json
    result = da.create_yearly_report_round(form, user_id)
    if result["status"] == "success":
        return jsonify(result), 201
    else:
        return jsonify(result), 403


@APP.route("/api/manage/yearly_report_round/<int:round_id>", methods=["PATCH"])
@login_required
def update_yearly_report_round(round_id):
    """
    Updates an existing YearlyReportRound.
    Only accessible to admin or manager users.
    """
    user_id = session.get("user_id", None)
    form = request.json
    form["id"] = round_id
    result = da.update_yearly_report_round(round_id, form, user_id)
    if result["status"] == "success":
        return jsonify(result)
    else:
        return jsonify(result), 403


@APP.route("/api/manage/yearly_report_round/<int:round_id>", methods=["DELETE"])
@login_required
def delete_yearly_report_round(round_id):
    """
    Deletes an existing YearlyReportRound.
    Only accessible to admin or manager users.
    """
    user_id = session.get("user_id", None)
    result = da.delete_yearly_report_round(round_id, user_id)
    if result["status"] == "success":
        return jsonify(result)
    else:
        return jsonify(result), 403


@APP.route("/", defaults={"path": ""})
@APP.route("/<path:path>")  # catch-all to allow react routing
def main(path):  # pylint: disable=unused-argument
    """
    Serves the single-page webapp.
    """
    return APP.send_static_file("index.html")


def reload_genetics_caches():
    """Warm all genetics caches used by the individual and dashboard endpoints.

    Runs on the scheduler leader only (once at startup, and after a debounced
    change): the memoized results are shared across workers through the cache,
    so one worker computing them is enough.
    """
    APP.logger.debug("Refreshing genetics caches")
    for p in da.get_all_genebanks():
        try:
            get_kinship(p.id)
            get_inbreeding(p.id)
            get_mean_kinship(p.id)
            get_population_metrics(p.id)
            get_founder_statistics(p.id)
            get_founders_at_risk(p.id)
            get_genetic_priorities(p.id)
            get_breeding_suggestions(p.id)
        except Exception:
            APP.logger.warning("Failed to refresh genetics caches for genebank %s", p.id, exc_info=True)


def _warm_genetics_in_background():
    """Build this worker's pedigree snapshots, one genebank at a time, without blocking startup.

    Only the snapshot and its reference kinship block: the shared memo (gene drop,
    priorities, suggestions) is warmed once, by the scheduler leader.
    """

    def run():
        time.sleep(random.uniform(0, 10))  # stagger the workers
        try:
            for p in da.get_all_genebanks():
                try:
                    snap = genetics.snapshot(p.id)
                    if snap is not None:
                        snap.reference_kinship()
                except Exception:  # pylint: disable=broad-except
                    APP.logger.warning("Failed to warm the genetics snapshot for genebank %s", p.id, exc_info=True)
        except Exception:  # pylint: disable=broad-except
            APP.logger.warning("Failed to list genebanks for the genetics warm-up", exc_info=True)
        finally:
            genetics.ps._close_db_connection()  # pylint: disable=protected-access

    threading.Thread(target=run, daemon=True, name="genetics-warmup").start()


# Must match SCHEDULER_LOCK in gunicorn.conf.py. The leader holds a flock on it for its lifetime.
SCHEDULER_LOCK_PATH = "/tmp/herdbook_scheduler.lock"
_SCHEDULER_LOCK_FD = None


def initialize_app():
    # Initialize Redis for cache invalidation
    from utils.cache_invalidation import (
        init_redis,
        poll_debounce_keys,
        poll_genetics_version,
        set_cache_and_functions,
        start_pubsub_listener,
    )

    redis_url = APP.config.get("CACHE_REDIS_URL", "redis://redis:6379/0")
    try:
        redis_client = init_redis(redis_url)
        redis_client.ping()
        APP.logger.info("Redis connected for cache invalidation")
    except Exception as e:
        APP.logger.warning(f"Redis not available: {e}. Cache invalidation disabled.")

    # Provide the memoized wrappers to cache_invalidation for the debounced warm-up
    set_cache_and_functions(
        memoized_funcs=[
            get_kinship,
            get_inbreeding,
            get_mean_kinship,
            get_population_metrics,
            get_founder_statistics,
            get_founders_at_risk,
            get_genetic_priorities,
        ],
        breeding_suggestions_func=get_breeding_suggestions,
    )

    # Start pub/sub listener on every worker
    start_pubsub_listener()

    # Every worker builds its own snapshots (initialize_app runs once per worker)
    _warm_genetics_in_background()

    # Only the scheduler leader runs debounce polling and the version poller.
    # The leader keeps a flock on the lock file; the kernel releases it if the leader dies.
    try:
        global _SCHEDULER_LOCK_FD  # pylint: disable=global-statement
        fd = os.open(SCHEDULER_LOCK_PATH, os.O_CREAT | os.O_WRONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise FileExistsError(SCHEDULER_LOCK_PATH) from None
        _SCHEDULER_LOCK_FD = fd
        scheduler = apscheduler.schedulers.background.BackgroundScheduler()

        # Poll debounce keys every 5s
        scheduler.add_job(
            poll_debounce_keys,
            trigger="interval",
            seconds=5,
            id="debounce_poll",
            max_instances=1,
            coalesce=True,
        )

        # Rebuild hint when the global genetics version moved (correctness rests on the snapshot key)
        scheduler.add_job(
            poll_genetics_version,
            trigger="interval",
            seconds=5,
            id="genetics_version_poll",
            max_instances=1,
            coalesce=True,
        )

        scheduler.add_job(
            _reconcile_all_history,
            "cron",
            hour=3,
            id="genetics_history_nightly",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,  # idempotent: a late leader still runs the day's reconcile
        )

        scheduler.add_job(
            _purge_command_free_text,
            "cron",
            hour=3,
            minute=30,
            id="command_free_text_purge",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

        # The intake queue's retention (docs/inkorg.md, "Gallring"); idempotent, so a late leader still runs it.
        scheduler.add_job(
            _purge_inbox,
            "cron",
            hour=3,
            minute=45,
            id="inbox_purge",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

        # Sends committed mail from the queue (docs/mejl.md); only the leader ever sends.
        scheduler.add_job(
            _send_mail,
            trigger="interval",
            seconds=30,
            id="mail_send",
            max_instances=1,
            coalesce=True,
        )

        # The intake queue's daily digest of unread notices (docs/inkorg.md), category N in the mail queue.
        scheduler.add_job(
            _queue_notice_digests,
            "cron",
            hour=7,
            id="notice_digest",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

        # Reads the association's mailbox into the intake queue (docs/inkorg-gmail.md); never on the demo.
        if settings.gmail.mode == "on":
            scheduler.add_job(
                _read_gmail, trigger="interval", minutes=5, id="inbox_gmail", max_instances=1, coalesce=True
            )
        # The image reading of photographed certificates, one document a run (docs/inkorg.md, "Tolkning").
        scheduler.add_job(
            _interpret_document,
            trigger="interval",
            minutes=1,
            id="inbox_interpret",
            max_instances=1,
            coalesce=True,
        )

        # Warm the shared genetics memo once at startup (workers only build their snapshots)
        scheduler.add_job(reload_genetics_caches, trigger="date", id="initial_warm", misfire_grace_time=None)

        scheduler.start()
        APP.logger.info("Scheduler leader — started debounce polling + genetics version poller + memo warm")
    except FileExistsError:
        APP.logger.info("Another worker is scheduler leader, skipping scheduler start")

    # Create loggers depending on Genbanks entry in database
    with db.DATABASE.atomic():
        for genebank in db.Genebank.select():
            gblogging.create_genebank_logs(settings.service.logfolder, genebank.name)


# Skip blocking startup code when running tests (pytest imports this module)
if "pytest" not in sys.modules and "unittest" not in sys.modules:
    # Connect to the database, or wait for database and then connect.
    while True:
        APP.logger.info("Connecting to database.")  # pylint: disable=no-member
        db.connect()
        if db.is_connected():
            break
        time.sleep(4)

    # verify the database before starting the server.
    if not db.verify():
        APP.logger.error("Database has errors.")  # pylint: disable=no-member
        sys.exit(1)

    initialize_app()


@APP.route("/api/manage/yearly-reports/<int:round_id>/<int:genebank_id>")
@login_required
def get_yearly_reports(round_id, genebank_id):
    """Get all yearly reports for a specific round and genebank."""
    try:
        # Check if user has permission for this genebank
        if not (current_user.is_admin or genebank_id in current_user.is_manager):
            return (
                jsonify({"status": "error", "message": "Åtkomst nekad"}),
                403,
            )

        # Get the report round to include the year
        report_round = da.YearlyReportRound.get_by_id(round_id)
        reports = da.get_yearly_reports(round_id, genebank_id)

        return jsonify(
            {
                "status": "success",
                "reports": reports,
                "report_year": report_round.report_year,
            }
        )
    except Exception as e:
        APP.logger.error(f"Failed to get yearly reports: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@APP.route("/api/manage/yearly-reports/<int:round_id>/<int:genebank_id>/export")
@login_required
def export_yearly_reports(round_id, genebank_id):
    """Export yearly reports as CSV for a specific round and genebank."""
    try:
        # Check if user has permission for this genebank
        if not (current_user.is_admin or genebank_id in current_user.is_manager):
            return (
                jsonify({"status": "error", "message": "Åtkomst nekad"}),
                403,
            )

        # Get the report round to include the year in the filename
        report_round = da.YearlyReportRound.get_by_id(round_id)
        csv_data = da.export_yearly_reports_csv(round_id, genebank_id)

        return Response(
            csv_data,
            mimetype="text/csv",
            headers={
                "Content-Disposition": f"attachment;filename=arsrapporter-{genebank_id}-{report_round.report_year}.csv"
            },
        )
    except Exception as e:
        APP.logger.error(f"Failed to export yearly reports: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@APP.route("/api/health")
def health_check():
    """Health check endpoint for monitoring and Docker health checks"""
    try:
        db.DATABASE.execute_sql("SELECT 1")

        return jsonify(
            {
                "status": "healthy",
                "timestamp": datetime.datetime.now().isoformat(),
                "version": os.environ.get("APP_VERSION", "dev"),
                "database": "connected",
            }
        ), 200
    except Exception as e:
        APP.logger.error(f"Health check failed: {str(e)}")
        return jsonify({"status": "unhealthy", "error": str(e), "timestamp": datetime.datetime.now().isoformat()}), 503
