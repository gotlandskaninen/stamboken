"""
Litter number management v2 endpoints.

Thin route handlers -- business logic in individual_number_v2.py.
See ADR-0007 for conventions.
"""

import logging

from flask import Blueprint, jsonify, request
from flask_login import current_user
from peewee import DoesNotExist, IntegrityError
from utils.database import Breeding, Herd
from utils.individual_number_v2 import (
    IndividualNumberConflict,
    IndividualRenumberNotAllowed,
    check_litter_order,
    renumber_litters,
    set_litter_number,
    suggest_litter_number,
)
from utils.number_assets import AssetMoveError

from .common import check_genebank_access, json_login_required, problem

breeding_v2_bp = Blueprint("breeding_v2", __name__, url_prefix="/api")

_RENUMBER_MANAGER_REQUIRED = "Omnumrering berör registrerade individer och kräver genbanksansvarig eller administratör"
_ASSETS_NOT_MOVED = "Intyg eller foto kunde inte flyttas till det nya numret, så ingenting numrerades om. Försök igen."


def _invalidate_genetics(genebank_id):
    """Best-effort genetics cache invalidation after individuals were renumbered.

    The renumbering uses bulk updates, which neither bump updated_at nor change
    any count, so the pedigree hash safety net would not notice it.
    """
    try:
        from utils.cache_invalidation import trigger_invalidation

        trigger_invalidation(genebank_id)
    except Exception:
        logging.warning("Cache invalidation failed for genebank %s", genebank_id)


@breeding_v2_bp.route("/v2/breeding/check-order", methods=["GET"])
@json_login_required
def check_order():
    """Check if litter numbers match chronological birth_date order for a herd/year."""
    herd_id = request.args.get("herd")
    year = request.args.get("year", type=int)

    if not herd_id or not year:
        return problem(400, "Bad Request", "Both 'herd' and 'year' query parameters are required")

    try:
        herd = Herd.get(Herd.herd == herd_id)
    except DoesNotExist:
        return problem(404, "Not Found", f"Herd {herd_id} not found")

    if not _can_manage_herd(current_user, herd):
        return problem(403, "Forbidden", "Åtkomst nekad")

    result = check_litter_order(herd_id, year)
    return jsonify(result), 200


@breeding_v2_bp.route("/v2/breeding/renumber", methods=["POST"])
@json_login_required
def renumber():
    """Renumber all litters for a herd/year to match chronological birth_date order."""
    form = request.get_json(silent=True)
    if not form or not isinstance(form, dict):
        return problem(400, "Bad Request", "Request body must be a JSON object")

    herd_id = form.get("herd_id")
    year = form.get("year")
    confirm = form.get("confirm", False)

    if not herd_id or not year:
        return problem(400, "Bad Request", "Both 'herd_id' and 'year' are required")

    if not isinstance(herd_id, str):
        return problem(400, "Bad Request", "herd_id must be a string")

    try:
        year = int(year)
    except (TypeError, ValueError):
        return problem(400, "Bad Request", "year must be an integer")

    try:
        herd = Herd.get(Herd.herd == herd_id)
    except DoesNotExist:
        return problem(404, "Not Found", f"Herd {herd_id} not found")

    if not _can_manage_herd(current_user, herd):
        return problem(403, "Forbidden", "Åtkomst nekad")

    # An owner may renumber only when no LIVE registered Individual is affected;
    # managers/admins for the genebank may always. check_genebank_access returns None
    # for manager/admin and a json_error tuple otherwise, so this is True for owners.
    owner_only = check_genebank_access(herd.genebank_id) is not None

    if not confirm:
        preview = renumber_litters(herd_id, year, confirm=False)
        if owner_only and preview["affected_individuals"]:
            return problem(403, "Forbidden", _RENUMBER_MANAGER_REQUIRED)
        return jsonify(preview), 200

    # The renumber decision must hold UNDER the lock. A promote could land a live
    # Individual into a renumbered litter between an unlocked preview and the locked
    # apply, so the owner flag is passed into the locked confirm; renumber_litters
    # aborts (rolls back) and raises if a live Individual would actually change.
    try:
        result = renumber_litters(herd_id, year, confirm=True, allow_individual_changes=not owner_only)
    except IndividualRenumberNotAllowed:
        return problem(403, "Forbidden", _RENUMBER_MANAGER_REQUIRED)
    except IndividualNumberConflict as exc:
        return problem(409, "Conflict", f"Individual number(s) already in use: {', '.join(exc.conflicts)}")
    except IntegrityError:
        return problem(409, "Conflict", "Renumbering conflicts with existing litter or individual numbers")
    except AssetMoveError:
        logging.exception("Renumber of %s/%s rolled back: a certificate/photo could not be staged", herd_id, year)
        return problem(503, "Service Unavailable", _ASSETS_NOT_MOVED)
    _invalidate_genetics(herd.genebank_id)
    return jsonify(result), 200


@breeding_v2_bp.route("/v2/breeding/<int:breeding_id>/litter-number", methods=["PATCH"])
@json_login_required
def update_litter_number(breeding_id):
    """Update litter number for a single breeding record."""
    try:
        breeding = Breeding.get_by_id(breeding_id)
    except DoesNotExist:
        return problem(404, "Not Found", f"Breeding {breeding_id} not found")

    herd = breeding.breeding_herd_id
    if not _can_manage_herd(current_user, herd):
        return problem(403, "Forbidden", "Åtkomst nekad")

    form = request.get_json(silent=True)
    if not form or not isinstance(form, dict):
        return problem(400, "Bad Request", "Request body must be a JSON object")

    new_litter_number = form.get("litter_number")
    if (
        new_litter_number is None
        or isinstance(new_litter_number, bool)
        or not isinstance(new_litter_number, int)
        or new_litter_number < 1
    ):
        return problem(400, "Bad Request", "litter_number must be a positive integer (>= 1)")

    # Mirror of /v2/breeding/renumber: an owner may only change the litter
    # number when no LIVE registered Individual belongs to the breeding; the
    # decision is enforced under the lock inside set_litter_number.
    owner_only = check_genebank_access(herd.genebank_id) is not None

    try:
        result = set_litter_number(breeding_id, new_litter_number, allow_individual_changes=not owner_only)
    except DoesNotExist:
        return problem(404, "Not Found", f"Breeding {breeding_id} not found")
    except IndividualRenumberNotAllowed:
        return problem(403, "Forbidden", _RENUMBER_MANAGER_REQUIRED)
    except IndividualNumberConflict as exc:
        return problem(409, "Conflict", f"Individual number(s) already in use: {', '.join(exc.conflicts)}")
    except IntegrityError:
        return problem(409, "Conflict", "Could not update litter number — possible duplicate")
    except AssetMoveError:
        logging.exception(
            "Litter number of breeding %s rolled back: a certificate/photo could not be staged", breeding_id
        )
        return problem(503, "Service Unavailable", _ASSETS_NOT_MOVED)

    _invalidate_genetics(herd.genebank_id)
    return jsonify(
        {"breeding_id": breeding_id, "litter_number": new_litter_number, "individuals": result["individuals"]}
    ), 200


@breeding_v2_bp.route("/v2/breeding/suggest-number", methods=["GET"])
@json_login_required
def suggest_number():
    """Suggest a litter number for a new litter."""
    herd_id = request.args.get("herd")
    birth_date_str = request.args.get("birth_date")

    if not herd_id or not birth_date_str:
        return problem(400, "Bad Request", "Both 'herd' and 'birth_date' query parameters are required")

    try:
        herd = Herd.get(Herd.herd == herd_id)
    except DoesNotExist:
        return problem(404, "Not Found", f"Herd {herd_id} not found")

    if not _can_manage_herd(current_user, herd):
        return problem(403, "Forbidden", "Åtkomst nekad")

    from datetime import date

    try:
        birth_date = date.fromisoformat(birth_date_str)
    except ValueError:
        return problem(400, "Bad Request", "birth_date must be ISO format (YYYY-MM-DD)")

    result = suggest_litter_number(herd_id, birth_date)
    return jsonify(result), 200


def _can_manage_herd(user, herd):
    """Check if user can manage litter numbers for this herd."""
    if user.is_admin:
        return True
    if user.is_manager and herd.genebank_id in (user.is_manager or []):
        return True
    if user.is_owner and herd.herd in (user.is_owner or []):
        return True
    return False
