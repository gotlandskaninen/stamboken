"""
Shared decorators and helpers for Flask Blueprints.

Blueprints import from here instead of herdbook.py to avoid circular imports.
See ADR-0007 for details.
"""

import re
from functools import wraps

from flask import jsonify
from flask_login import current_user, login_required  # noqa: F401 — re-exported for blueprints

# Shared email-shape check for member_applications.py and members.py.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def json_login_required(f):
    """Decorator: returns JSON 401 for unauthenticated requests.

    Unlike Flask-Login's @login_required which redirects to a login page,
    this always returns an RFC 9457 problem+json error — suitable for
    Next.js/API clients that send Accept: */* and expect JSON responses.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return problem(401, "Autentisering krävs", "Du måste vara inloggad.")
        return f(*args, **kwargs)

    return decorated


def manager_required(f):
    """Decorator: coarse gate requiring the user to hold any manager or admin role.

    This is a pre-filter only. Endpoints that operate on a specific genebank
    MUST also call ``check_genebank_access(genebank_id)`` to enforce per-genebank
    authorization — the decorator alone does NOT scope access to a single genebank.

    Must be used after @login_required so that current_user is available.
    Returns RFC 9457 problem+json 403 if the user has no manager/admin role at all.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_admin and not current_user.is_manager:
            return problem(403, "Åtkomst nekad", "Du saknar behörighet för denna åtgärd.")
        return f(*args, **kwargs)

    return decorated


def check_genebank_access(genebank_id):
    """Check if the current user has manager access to a specific genebank.

    Mirrors the inline pattern used in herdbook.py::

        if not (current_user.is_admin or genebank_id in current_user.is_manager):
            return jsonify({...}), 403

    Returns an RFC 9457 problem+json response tuple on failure, or None on success.
    """
    if current_user.is_admin:
        return None
    manager_genebanks = current_user.is_manager or []
    if genebank_id not in manager_genebanks:
        return problem(403, "Åtkomst nekad", "Du saknar behörighet för denna genbank.")
    return None


def matrikel_admin_required(f):
    """Decorator: requires admin or matrikel_admin (Member Model v2).

    Full matrikel CRUD gate — registry writes, import/export, member-number
    edits. Grants NO studbook rights. Must be used after @json_login_required.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_admin and not current_user.is_matrikel_admin:
            return problem(403, "Åtkomst nekad", "Du saknar behörighet för denna åtgärd.")
        return f(*args, **kwargs)

    return decorated


def matrikel_read_required(f):
    """Decorator: requires admin, matrikel_admin, or any manager role.

    Matrikel read gate + reviewer gate for member applications: gene-bank
    managers get read access to the whole matrikel.
    Must be used after @json_login_required.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        if not (current_user.is_admin or current_user.is_matrikel_admin or current_user.is_manager):
            return problem(403, "Åtkomst nekad", "Du saknar behörighet för denna åtgärd.")
        return f(*args, **kwargs)

    return decorated


def json_error(message, status=400):
    """Return a JSON error response matching the project's standard format."""
    return jsonify({"status": "error", "message": message}), status


def problem(status, title, detail, **extra):
    """Return RFC 9457 Problem Details response."""
    body = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        **extra,
    }
    return jsonify(body), status, {"Content-Type": "application/problem+json"}


def admin_required(f):
    """Route decorator for admin-only API endpoints.

    Enforces auth AND admin role in ONE gate. Returns RFC 9457 Problem
    Details for both failure modes, always Content-Type:
    application/problem+json, never an HTML redirect.

    Do NOT compose with the redirecting Flask-Login ``login_required`` —
    the redirect would fire before this gate sees the request.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return problem(
                401,
                "Autentisering krävs",
                "Denna endpoint kräver en inloggad session.",
                type="authentication-required",
            )
        if not current_user.is_admin:
            return problem(
                403,
                "Admin-behörighet krävs",
                "Endast admin får anropa denna endpoint.",
                type="admin-required",
            )
        return f(*args, **kwargs)

    return decorated


def check_genebank_manager_access(user, gb_id):
    """Return None if ``user`` is admin or manager(gb=gb_id); otherwise an
    RFC 9457 Problem Details 403 tuple.

    Mirrors ``check_genebank_access`` but requires MANAGER tier (not merely
    viewer) and takes the user explicitly so herdbook.py routes can pass
    flask_login's current_user (used by the scoped adminpanel endpoints:
    reassign owner, genebank edit, scoped herd endpoints).
    """
    if user.is_admin:
        return None
    managed = user.is_manager or []
    if gb_id in managed:
        return None
    return problem(
        403,
        "Genbanksansvarig krävs",
        f"Kräver manager(gb={gb_id}) eller admin.",
        type="manager-of-genebank-required",
    )
