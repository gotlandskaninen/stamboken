"""
Audit log API endpoints (ADR-0007).

Provides read access to audit history and revert/restore capabilities
for managers. Per-genebank authorization enforced. hbuser audit is
admin-only; hbuser revert/restore is blocked (privilege escalation risk).
"""

import logging

import utils.data_access as da
from flask import Blueprint, jsonify, request
from flask_login import current_user
from utils.database import AUDITED_TABLES

from blueprints.common import check_genebank_access, json_login_required, manager_required, problem

audit_bp = Blueprint("audit", __name__, url_prefix="/api")

# Tables where revert/restore is blocked: hbuser (privilege-bearing fields) and
# herd_tracking (every change is an operation with locks + invariants;
# undo goes through /api/v2/herd-tracking/operations/<id>/undo).
_REVERT_BLOCKED_TABLES = {"hbuser", "herd_tracking"}


def _check_audit_access(table_name, record_id):
    """Per-record genebank authorization. Returns error response or None."""
    if table_name == "hbuser":
        if not current_user.is_admin:
            return problem(403, "Åtkomst nekad", "Admin krävs för användarhistorik")
        return None

    genebank_id = da.get_audit_genebank_id(table_name, record_id)
    if genebank_id is None:
        return problem(404, "Hittades inte", "Posten finns inte")
    return check_genebank_access(genebank_id)


def _invalidate_cache(table_name, record_id):
    """Best-effort cache invalidation after audit revert/restore writes."""
    try:
        from utils.cache_invalidation import trigger_invalidation

        genebank_id = da.get_audit_genebank_id(table_name, record_id)
        if genebank_id:
            trigger_invalidation(genebank_id)
    except Exception:
        logging.warning("Cache invalidation failed for %s/%s", table_name, record_id, exc_info=True)


def _revert_fields():
    """
    The `fields` a revert request names (None: every changed field). An empty body names none:
    fetchApi sends Content-Type: application/json even when it has nothing to send.
    Raises ValueError for a body that is not an object with a list of field names, so a
    malformed request is refused instead of reverting every field.
    """
    if not request.is_json or not request.get_data(cache=True).strip():
        return None
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValueError("Förväntade ett JSON-objekt")
    fields = body.get("fields")
    if fields is not None and not (isinstance(fields, list) and all(isinstance(f, str) for f in fields)):
        raise ValueError("fields måste vara en lista med fältnamn")
    return fields


@audit_bp.route("/audit-log/<table_name>/<record_id>")
@json_login_required
@manager_required
def get_audit_log(table_name, record_id):
    """Returns paginated change history for a specific record."""
    if table_name not in AUDITED_TABLES:
        return problem(400, "Okänd tabell", f"Tabellen '{table_name}' är inte spårad")

    access_error = _check_audit_access(table_name, record_id)
    if access_error:
        return access_error

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 25, type=int)
    changed_by = request.args.get("changed_by")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")

    result = da.get_audit_history(
        table_name,
        record_id,
        page=page,
        per_page=per_page,
        changed_by=changed_by,
        from_date=from_date,
        to_date=to_date,
    )
    return jsonify(result)


@audit_bp.route("/audit-log/<int:audit_id>/revert", methods=["POST"])
@json_login_required
@manager_required
def revert_audit_entry_route(audit_id):
    """Revert specific fields from an audit entry."""
    from utils.database import AuditLog

    try:
        entry = AuditLog.get_by_id(audit_id)
    except AuditLog.DoesNotExist:
        return problem(404, "Hittades inte", "Granskningsposten finns inte")

    if entry.table_name in _REVERT_BLOCKED_TABLES:
        return problem(403, "Ej tillåtet", "Ångra ej tillåtet för denna tabell")

    access_error = _check_audit_access(entry.table_name, entry.record_id)
    if access_error:
        return access_error

    try:
        fields = _revert_fields()
    except ValueError as exc:
        return problem(400, "Ogiltig förfrågan", str(exc))

    result, status = da.revert_audit_entry(audit_id, fields=fields, is_admin=current_user.is_admin)

    # Best-effort cache invalidation after successful write
    if status == 200:
        _invalidate_cache(entry.table_name, entry.record_id)

    return jsonify(result), status


@audit_bp.route(
    "/audit-log/<table_name>/<record_id>/restore/<int:audit_id>",
    methods=["POST"],
)
@json_login_required
@manager_required
def restore_record_route(table_name, record_id, audit_id):
    """Restore a record to its state before a specific audit entry."""
    if table_name not in AUDITED_TABLES:
        return problem(400, "Okänd tabell", f"Tabellen '{table_name}' är inte spårad")

    if table_name in _REVERT_BLOCKED_TABLES:
        return problem(403, "Ej tillåtet", "Återställ ej tillåtet för denna tabell")

    access_error = _check_audit_access(table_name, record_id)
    if access_error:
        return access_error

    result, status = da.restore_record(table_name, record_id, audit_id, is_admin=current_user.is_admin)

    # Best-effort cache invalidation after successful write
    if status == 200:
        _invalidate_cache(table_name, record_id)

    return jsonify(result), status
