"""
Shared decorators and helpers for Flask Blueprints.

Blueprints import from here instead of herdbook.py to avoid circular imports.
See ADR-0007 for details.
"""

import re
from datetime import datetime, timezone
from functools import wraps

from flask import jsonify
from flask_login import current_user, login_required  # noqa: F401 — re-exported for blueprints
from utils.database import AuditLog

# Shared email-shape check for member_applications.py and members.py.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# The demo is a nightly copy of production: an export there would carry real data
# while its audit row is gone at the next sync.
DEMO_EXPORT_REFUSED = "Exporten går bara att göra i den riktiga Stamboken, där varje uttag loggas."


def log_export(model, action, **details):
    """One audit_log row per download of an export: who, when and which rows, by identifier; never a value."""
    AuditLog.create(
        table_name=model._meta.table_name,
        record_id=f"export-{action}-{datetime.now(timezone.utc).isoformat()}",
        operation="READ",
        new_data={"action": action, **details},
        changed_by=current_user.username or current_user.email,
    )


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


def membership_organization_fields(membership, *, account_details: bool) -> dict:
    fields = {"organization_name": membership.organization_name}
    if account_details and (current_user.is_admin or current_user.is_matrikel_admin):
        fields["organization_number"] = membership.organization_number
    return fields


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


# Member's column widths: a longer value is a 400 here, never a DataError (500) at the write (R029, #294).
PERSON_FIELD_LIMITS = {"first_name": 100, "last_name": 100, "email": 255, "phone": 50}


def field_too_long(body, limits=PERSON_FIELD_LIMITS):
    """The 400 for the first text field in `body` longer than its column, otherwise None. Untrimmed: some routes
    store the value as sent (PATCH /v2/persons keeps the phone's spaces)."""
    for key, limit in limits.items():
        value = body.get(key)
        if isinstance(value, str) and len(value) > limit:
            return problem(400, "Fält för långt", f"Fältet '{key}' överskrider maxlängden {limit} tecken", field=key)
    return None


def contact_problem(err):
    """A refused contact patch (#117, utils.herd_contact): 409 contact-changed or 403 contact-forbidden."""
    from utils.herd_contact import ContactConflict  # pylint: disable=import-outside-toplevel

    if isinstance(err, ContactConflict):
        return problem(409, "Kontaktuppgifterna har ändrats", str(err), type="contact-changed")
    return problem(403, "Åtkomst nekad", str(err), type="contact-forbidden")


REX_MUST_BE_BOOLEAN = "rex must be true or false"


def rex_problem(body):
    """A 400 when the body carries rex that is not a real boolean (null, 0, 1 and "false" included), else None."""
    if "rex" in body and not isinstance(body["rex"], bool):
        return problem(400, "Bad Request", REX_MUST_BE_BOOLEAN)
    return None


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
