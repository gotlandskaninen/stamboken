"""
Breeding CRUD v2 endpoints.

Thin route handlers — business logic in data_access.py.
See ADR-0007 for conventions, ADR-0008 for Server-First architecture.
"""

import logging

import utils.data_access as da
from flask import Blueprint, jsonify, request, session
from utils.database import Bunny

from .common import json_login_required, problem

breeding_bp = Blueprint("breeding", __name__, url_prefix="/api")


@breeding_bp.route("/v2/breeding", methods=["POST"])
@json_login_required
def create_breeding():
    """Register a new mating event. Returns 201 + full breeding entity."""
    form = request.get_json(silent=True)
    if not form or not isinstance(form, dict):
        return problem(400, "Bad Request", "Request body must be a JSON object")

    user_uuid = session.get("user_id")
    result = da.register_breeding(form, user_uuid)

    if result.get("status") == "error":
        msg = result.get("message", "Unknown error")
        if msg == "Forbidden":
            code = 403
        elif "already registered" in msg.lower():
            code = 409
        else:
            code = 400
        return problem(code, "Registration failed", msg)

    # Cache invalidation (best-effort)
    _invalidate_breeding(result.get("breeding_id"))

    # Return full entity
    breeding = da.get_breeding_event(result["breeding_id"], user_uuid)
    if result.get("warnings"):
        breeding["warnings"] = result["warnings"]
    return jsonify(breeding), 201


@breeding_bp.route("/v2/breeding/<int:breeding_id>", methods=["PATCH"])
@json_login_required
def update_breeding_v2(breeding_id):
    """Update a breeding event. Returns 200 + full updated entity."""
    form = request.get_json(silent=True)
    if not form or not isinstance(form, dict):
        return problem(400, "Bad Request", "Request body must be a JSON object")

    user_uuid = session.get("user_id")

    # Verify breeding exists
    existing = da.get_breeding_event(breeding_id, user_uuid)
    if not existing:
        return problem(404, "Not Found", f"Breeding {breeding_id} not found")

    # Capture old genebank IDs before update (breeding can span genebanks)
    from utils.cache_invalidation import get_genebank_ids_for_breeding

    old_genebank_ids = set()
    try:
        old_genebank_ids = get_genebank_ids_for_breeding(breeding_id)
    except Exception:
        logging.warning("Could not resolve old genebank for breeding %s", breeding_id)

    form["id"] = breeding_id
    try:
        result = da.update_breeding(form, user_uuid)
    except Exception:
        logging.exception("Unexpected error updating breeding %s", breeding_id)
        return problem(500, "Internal Server Error", "An unexpected error occurred during the update.")

    if result.get("status") == "error":
        msg = result.get("message", "Unknown error")
        if "problem_status" in result:
            return problem(result["problem_status"], result["title"], msg, rows=result.get("rows", []))
        code = 403 if msg == "Forbidden" else 400
        return problem(code, "Update failed", msg)

    # Cache invalidation: old + new genebanks
    try:
        new_genebank_ids = get_genebank_ids_for_breeding(breeding_id)
        from utils.cache_invalidation import trigger_invalidation

        for gid in old_genebank_ids | new_genebank_ids:
            trigger_invalidation(gid)
    except Exception:
        logging.warning("Cache invalidation failed for breeding %s", breeding_id)

    updated = da.get_breeding_event(breeding_id, user_uuid)
    if result.get("warnings"):
        updated["warnings"] = result["warnings"]
    return jsonify(updated), 200


@breeding_bp.route("/v2/breeding/<int:breeding_id>", methods=["DELETE"])
@json_login_required
def delete_breeding_v2(breeding_id):
    """Delete an empty breeding event. Returns 204 on success."""
    user_uuid = session.get("user_id")

    existing = da.get_breeding_event(breeding_id, user_uuid)
    if not existing:
        return problem(404, "Not Found", f"Breeding {breeding_id} not found")

    # v2 shows its delete button whenever the litter has no promoted individuals
    # and never confirms, so an unpromoted roster must block the delete here.
    # The shared da.delete_breeding cascades the roster for the legacy route,
    # whose UI cannot see roster rows.
    if Bunny.select().where(Bunny.breeding == breeding_id).exists():
        return problem(409, "has_bunnies", "Kullen har ungar i rostret — ta bort dem först.")

    # Capture genebank IDs before deletion
    from utils.cache_invalidation import get_genebank_ids_for_breeding

    genebank_ids = set()
    try:
        genebank_ids = get_genebank_ids_for_breeding(breeding_id)
    except Exception:
        logging.warning("Could not resolve genebank for breeding %s", breeding_id)

    result = da.delete_breeding(breeding_id, user_uuid)

    if result.get("status") == "error":
        msg = result.get("message", "Unknown error")
        if "behörighet" in msg.lower() or msg == "Forbidden":
            return problem(403, "Forbidden", msg)
        if "individer" in msg.lower():
            return problem(409, "Conflict", msg)
        return problem(400, "Delete failed", msg)

    # Cache invalidation
    try:
        from utils.cache_invalidation import trigger_invalidation

        for gid in genebank_ids:
            trigger_invalidation(gid)
    except Exception:
        logging.warning("Cache invalidation failed for breeding %s", breeding_id)

    return "", 204


@breeding_bp.route("/v2/breeding/<int:breeding_id>/birth", methods=["POST"])
@json_login_required
def register_birth_v2(breeding_id):
    """Register birth on an existing breeding. Returns 200 + full updated breeding."""
    form = request.get_json(silent=True)
    if not form or not isinstance(form, dict):
        return problem(400, "Bad Request", "Request body must be a JSON object")

    user_uuid = session.get("user_id")

    existing = da.get_breeding_event(breeding_id, user_uuid)
    if not existing:
        return problem(404, "Not Found", f"Breeding {breeding_id} not found")

    form["id"] = breeding_id
    result = da.register_birth(form, user_uuid)

    if result.get("status") == "error":
        msg = result.get("message", "Unknown error")
        if msg == "Forbidden":
            return problem(403, "Forbidden", msg)
        if "already registered" in msg.lower():
            return problem(409, "Conflict", msg)
        return problem(400, "Birth registration failed", msg)

    # Cache invalidation
    _invalidate_breeding(breeding_id)

    updated = da.get_breeding_event(breeding_id, user_uuid)
    if result.get("warnings"):
        updated["warnings"] = result["warnings"]
    # An out-of-order birth is appended at the end of the number series; pass
    # the conflicts through so the UI can offer renumbering immediately.
    if result.get("litter_number_conflicts"):
        updated["litter_number_conflicts"] = result["litter_number_conflicts"]
    return jsonify(updated), 200


@breeding_bp.route("/v2/herd/<herd_id>", methods=["PATCH"])
@json_login_required
def update_herd_v2(herd_id):
    """Update herd info. Returns 200 + full herd entity."""
    form = request.get_json(silent=True)
    if not form or not isinstance(form, dict):
        return problem(400, "Bad Request", "Request body must be a JSON object")

    user_uuid = session.get("user_id")

    # Resolve herd code to numeric ID via data access layer
    numeric_id = da.herd_to_herdid(herd_id)
    if numeric_id is None:
        return problem(404, "Not Found", f"Herd {herd_id} not found")

    form["id"] = numeric_id
    result = da.update_herd(form, user_uuid)

    if result.get("status") == "error":
        msg = result.get("message", "Unknown error")
        code = 403 if msg == "Forbidden" else 400
        return problem(code, "Forbidden" if code == 403 else "Update failed", msg)

    # Cache invalidation
    try:
        from utils.cache_invalidation import get_genebank_id_for_herd_id, trigger_invalidation

        for gid in get_genebank_id_for_herd_id(numeric_id):
            trigger_invalidation(gid)
    except Exception:
        logging.warning("Cache invalidation failed for herd %s", herd_id)

    # Return full herd entity
    herd_data = da.get_herd(herd_id, user_uuid)
    if herd_data:
        return jsonify(herd_data), 200
    return problem(500, "Internal error", "Could not reload herd after update")


def _invalidate_breeding(breeding_id):
    """Best-effort cache invalidation for a breeding event."""
    if not breeding_id:
        return
    try:
        from utils.cache_invalidation import get_genebank_ids_for_breeding, trigger_invalidation

        for gid in get_genebank_ids_for_breeding(breeding_id):
            trigger_invalidation(gid)
    except Exception:
        logging.warning("Cache invalidation failed for breeding %s", breeding_id)
