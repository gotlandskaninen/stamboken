"""
Individual listing endpoints.

Thin route handlers — business logic belongs in data_access.py.
See ADR-0007 for blueprint conventions.
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import utils.data_access as da
import utils.genetics_service as genetics_service
from flask import Blueprint, jsonify, request, session
from utils.database import DB_PROXY, OUTSIDE_GENEBANK_HERDS, Herd, IndividualCommand
from utils.herd_tracking import HerdTrackingError
from utils.individual_commands import IndividualRefused, Undo, execute, own_recent_commands
from utils.individual_number_v2 import PAPER_NUMBER_REQUIRED, parse_number

from .common import json_login_required, problem

individuals_bp = Blueprint("individuals", __name__, url_prefix="/api")

logger = logging.getLogger(__name__)


# [Next.js] Paginated individual list for Rabbit Explorer
@individuals_bp.route("/individuals")
@json_login_required
def paginated_individuals():
    """
    Returns paginated, filterable, sortable list of individuals
    the current user has access to.
    """
    user_id = session.get("user_id", None)
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    sort = request.args.get("sort", "name")
    order = request.args.get("order", "asc")
    genebank_id = request.args.get("genebank_id", None, type=int)
    search = request.args.get("search", None)
    status = request.args.get("status", None)
    sex = request.args.get("sex", None)
    herd_id = request.args.get("herd_id", None)
    include_historical = request.args.get("include_historical", "false").lower() == "true"

    result = da.get_paginated_individuals(
        user_id,
        page=page,
        per_page=per_page,
        sort=sort,
        order=order,
        genebank_id=genebank_id,
        search=search,
        status=status,
        sex=sex,
        herd_id=herd_id,
        include_historical=include_historical,
    )
    if result is None:
        return jsonify({"status": "error", "message": "Not authenticated"}), 401
    return jsonify(result)


# [Next.js] Get individual by number — proper 404, no legacy 200+null quirk.
# Uses a separate /v2/ path so legacy GET /api/individual/<n> stays untouched (ADR-0006).
@individuals_bp.route("/v2/individual/<number>", methods=["GET"])
@json_login_required
def get_individual_v2(number):
    """Get individual by number with RFC 9457 errors."""
    user_uuid = session.get("user_id")
    individual = da.get_individual(number, user_uuid)
    if individual is None:
        return problem(404, "Not Found", f"No accessible individual with number {number}")
    # Include updated_at for cache-busting photo URLs (stripped by as_dict for legacy compat)
    from utils.database import Individual as IndividualModel

    try:
        ind = IndividualModel.get(IndividualModel.number == number)
        if ind.updated_at:
            individual["updated_at"] = ind.updated_at.isoformat()
    except IndividualModel.DoesNotExist:
        pass
    return jsonify(_with_can_transfer(individual, user_uuid)), 200


_warned_missing = set()  # (genebank, number) already warned about in this process


def _warn_missing_once(genebank_id, number):
    """Should be unreachable: warn once per animal and process, then stay quiet."""
    if (genebank_id, number) in _warned_missing:
        logger.debug("Fresh genetics snapshot of genebank %s still lacks %s", genebank_id, number)
        return
    _warned_missing.add((genebank_id, number))
    logger.warning("Fresh genetics snapshot of genebank %s lacks accessible individual %s", genebank_id, number)


def _retry_later(detail):
    """503 Problem Details with Retry-After: the animal is accessible, only its genetics are not ready."""
    body, status, headers = problem(503, "Service Unavailable", detail)
    return body, status, {**headers, "Retry-After": "5"}


def _genetics_snapshot_status(genebank_id):
    """genetics_service.snapshot_status, or (None, False) when it fails (a cold start whose key read failed)."""
    try:
        return genetics_service.snapshot_status(genebank_id)
    except Exception:  # pylint: disable=broad-except
        logger.warning("Reading the genetics snapshot for genebank %s failed", genebank_id, exc_info=True)
        return None, False


# [Next.js] Per-individual genetics for the v2 individual page.
@individuals_bp.route("/v2/individual/<number>/genetics", methods=["GET"])
@json_login_required
def get_individual_genetics_v2(number):
    """Inbreeding, mean kinship and MK band of one accessible individual; same 404 as /v2/individual/<number>."""
    user_uuid = session.get("user_id")
    individual = da.get_individual(number, user_uuid)
    if individual is None:
        return problem(404, "Not Found", f"No accessible individual with number {number}")
    # Snapshots hold animals by origin genebank; the current herd may belong to another one.
    gb = Herd.get_by_id(individual["origin_herd"]["id"]).genebank_id
    snap, stale = _genetics_snapshot_status(gb)
    if snap is not None and stale and number not in snap.index:
        # Renumbered or newly registered: the snapshot that knows it is being built.
        try:
            genetics_service.ps.wait_for_builds(gb, timeout=genetics_service.REFRESH_WAIT_SECONDS)
        except Exception:  # pylint: disable=broad-except
            logger.info("Genetics rebuild for genebank %s not ready for %s", gb, number, exc_info=True)
        snap, stale = _genetics_snapshot_status(gb)
    if snap is None:
        return _retry_later("Genetiken kan inte beräknas just nu")
    outside = (individual.get("herd") or {}).get("herd") in OUTSIDE_GENEBANK_HERDS
    data = genetics_service.individual_genetics(
        snap, number, alive=bool(individual.get("alive")), outside=outside, stale=stale
    )
    if data is None:
        # Stale: the rebuild that knows this animal did not finish in time (or failed).
        # Fresh: should not happen for an accessible animal; never answer 404 for it.
        if not stale:
            _warn_missing_once(gb, number)
        return _retry_later("Genetiken uppdateras, försök igen om en stund")
    return jsonify(data), 200


def _with_can_transfer(individual, user_uuid):
    """Add `can_transfer` (sell/move permission, see User.can_transfer) to an individual dict."""
    user = da.fetch_user_info(user_uuid)
    individual["can_transfer"] = bool(user and user.can_transfer(individual["id"]))
    return individual


MIN_SALE_AGE_DAYS = 43


def _herd_code(value):
    """Herd code from either a herd dict or a plain string."""
    if isinstance(value, dict):
        value = value.get("herd", "")
    return value if isinstance(value, str) else ""


def _min_sale_date(individual):
    """
    Earliest allowed sale date (mirrors legacy): birth + 43 days when the latest
    herd-tracking row is the birth row (or there is none), otherwise the day
    after the latest herd-tracking date. None if nothing constrains the date.
    """
    birth = individual.get("birth_date")
    tracking = individual.get("herd_tracking") or []
    latest = max((t["date"] for t in tracking if t.get("date")), default=None)
    if latest and latest != birth:
        return datetime.strptime(latest, "%Y-%m-%d").date() + timedelta(days=1)
    if birth:
        return datetime.strptime(birth, "%Y-%m-%d").date() + timedelta(days=MIN_SALE_AGE_DAYS)
    return None


def _validate_sale(individual, form, user, buyer=None):
    """
    Server-side rules for a sale/move (a PATCH carrying `selling_date`). With a `buyer`, GX1 to GX1 (MX1 to MX1)
    is a sale too: one buyer outside the association selling to another (ADR-0016).
    Returns a Swedish error message, or None if the sale is valid.
    Kept out of data_access.update_individual so legacy behaviour is untouched (ADR-0006).
    """
    try:
        sale_date = datetime.strptime(str(form["selling_date"])[:10], "%Y-%m-%d").date()
    except ValueError:
        return "Ogiltigt datum. Ange datumet som ÅÅÅÅ-MM-DD."

    today = datetime.now(ZoneInfo("Europe/Stockholm")).date()
    if sale_date > today:
        return "Försäljningsdatumet får inte ligga i framtiden."

    min_date = _min_sale_date(individual)
    if min_date and sale_date < min_date:
        return (
            f"Försäljningsdatumet får inte vara tidigare än {min_date.isoformat()} "
            "(tidigast 43 dagar efter födseln, och efter senaste besättningsbytet)."
        )

    target_code = _herd_code(form.get("herd"))
    resale = buyer is not None and target_code in OUTSIDE_GENEBANK_HERDS
    if target_code == _herd_code(individual.get("herd")) and not resale:
        return "Individen finns redan i den besättningen."
    target = Herd.get_or_none(Herd.herd == target_code)
    if target is None:
        return f"Okänd besättning: {target_code}."
    # An admin may correct a misregistration; update_individual then requires the body's `reason`.
    if target.genebank_id != individual.get("genebank_id") and not user.is_admin:
        return "Individen kan bara flyttas till en besättning inom samma genbank."
    if not individual.get("is_registered") and target_code not in OUTSIDE_GENEBANK_HERDS:
        return (
            "En individ utan intyg kan bara säljas utanför genbanken "
            f"({' eller '.join(OUTSIDE_GENEBANK_HERDS)}), inte till en annan besättning."
        )
    return None


def _check_transfer(individual, form, user_uuid, buyer=None):
    """
    Guard for PATCHes that move an individual to another herd. A move is any
    request whose `herd` differs from the current herd, whether or not it carries
    `selling_date` — data_access.update_individual writes a HerdTracking row for
    `herd` + `yearly_report_date` too, so that payload must not bypass the rules.
    Returns a problem response, or None if the request is not a move or is valid.
    """
    selling = bool(form.get("selling_date"))
    moving = "herd" in form and _herd_code(form["herd"]) != _herd_code(individual.get("herd"))
    if not (selling or moving):
        return None

    user = da.fetch_user_info(user_uuid)
    if user is None or not user.can_transfer(individual["id"]):
        return problem(
            403,
            "Forbidden",
            "Endast huvudmedlem, genbanksansvarig eller administratör kan sälja eller flytta individen.",
        )
    if not selling:
        return problem(400, "Bad Request", "Ange försäljningsdatum för att flytta individen.")
    if "herd" not in form:
        return problem(400, "Bad Request", "Ange vilken besättning individen ska flyttas till.")
    error = _validate_sale(individual, form, user, buyer)
    if error:
        return problem(400, "Ogiltig försäljning", error)
    return None


def _check_origin_herd_change(individual, form, user_uuid):
    """
    data_access.update_individual rewrites the birth herd-tracking row when `origin_herd`
    changes, which silently changes the current herd of a never-moved individual. Only admins
    and managers of the individual's genebank may change the origin herd; the v2 UI never
    sends it. Returns a problem response, or None if the PATCH leaves origin_herd alone.
    """
    if "origin_herd" not in form:
        return None
    if _herd_code(form["origin_herd"]) == _herd_code(individual.get("origin_herd")):
        return None
    user = da.fetch_user_info(user_uuid)
    if user is not None and (user.is_admin or individual.get("genebank_id") in (user.is_manager or [])):
        return None
    return problem(403, "Forbidden", "Endast genbanksansvarig eller administratör kan ändra ursprungsbesättning.")


class _UpdateRejected(Exception):
    """Raised inside the update transaction so everything written so far is rolled back."""

    def __init__(self, response):
        super().__init__()
        self.response = response


# [Next.js] Herds in a genebank (code, name, active) for the sell/move picker.
# Owners must see other herds' codes and names to pick a buyer; no contact data.
@individuals_bp.route("/v2/genebank/<int:genebank_id>/herds", methods=["GET"])
@json_login_required
def genebank_herds_v2(genebank_id):
    """List the herds of a genebank the user has access to (minimal fields)."""
    user = da.fetch_user_info(session.get("user_id"))
    if user is None or genebank_id not in user.accessible_genebanks:
        return problem(404, "Not Found", "Genbanken finns inte eller är inte tillgänglig")
    herds = Herd.select().where(Herd.genebank == genebank_id).order_by(Herd.herd)
    return jsonify(
        {"herds": [{"herd": h.herd, "herd_name": h.herd_name, "is_active": bool(h.is_active)} for h in herds]}
    )


# [Next.js] Update individual and return full updated entity.
# Uses /<number> in URL (RESTful) — no conflict with legacy PATCH /api/individual (no number).
@individuals_bp.route("/individual/<number>", methods=["PATCH"])
@json_login_required
def update_individual_v2(number):
    """Update individual by number, return full entity."""
    user_uuid = session.get("user_id")

    individual = da.get_individual(number, user_uuid)
    if individual is None:
        return problem(404, "Individual not found", f"No accessible individual with number {number}")

    form = request.get_json(silent=True)
    if not form or not isinstance(form, dict):
        return problem(400, "Bad Request", "Request body must be a JSON object")
    # `selling_date` is not a column — it only dates the TRANSFER row a sale
    # writes. A null value means "no sale", so drop it instead of trying to
    # clear a field that does not exist.
    if "selling_date" in form and form["selling_date"] is None:
        del form["selling_date"]
    # The buyer outside the association, on a sale to GX1/MX1 (ADR-0016); kept out of the legacy form.
    buyer = form.pop("buyer", None)
    if buyer is not None and not form.get("selling_date"):
        return problem(400, "Bad Request", "Köparens uppgifter registreras bara vid en försäljning.")
    # A first paper certificate comes with the individual number the paper says: the number
    # is pinned to the URL here, so it is the paper's claim that is checked against the litter.
    uncertified = not (individual.get("certificate") or individual.get("digital_certificate"))
    if form.get("certificate") and uncertified and parse_number(form.get("paper_number")) is None:
        return problem(400, "Bad Request", PAPER_NUMBER_REQUIRED)

    try:
        # Lock first (its Breeding, then the individual): the checks below
        # read herd-tracking history and permissions, so two concurrent sales must queue instead
        # of both passing validation. FOR NO KEY UPDATE (not plain FOR UPDATE): still
        # self-conflicting, but it does not conflict with the FOR KEY SHARE lock that a concurrent
        # weight/bodyfat insert takes on Individual through its FK.
        with DB_PROXY.atomic():
            if not da.lock_individual_for_edit(individual["id"], form.get("breeding")):
                return problem(404, "Individual not found", f"No accessible individual with number {number}")
            # Reload under the lock — the first read was an unlocked snapshot.
            individual = da.get_individual(number, user_uuid)
            if individual is None:
                return problem(404, "Individual not found", f"No accessible individual with number {number}")

            # Permission first: the sale and origin checks below would answer a non-editor otherwise.
            user = da.fetch_user_info(user_uuid)
            if user is None or not user.can_edit(individual["id"]):
                return problem(403, "Forbidden", "Forbidden")

            error_response = _check_transfer(individual, form, user_uuid, buyer) or _check_origin_herd_change(
                individual, form, user_uuid
            )
            if error_response is not None:
                return error_response

            form["id"] = individual["id"]
            form["number"] = number
            # Ensure herd is present — data_access.update_individual requires it
            if "herd" not in form:
                form["herd"] = _herd_code(individual.get("herd"))

            # clear_nulls: the death and castration fields sent as null are cleared (undo death, IR-51).
            result = da.update_individual(
                form, user_uuid, genebank_change_reason=form.pop("reason", None), clear_nulls=True, buyer=buyer
            )
            if result is None or result.get("status") == "error":
                msg = (result or {}).get("message", "Unknown error")
                # data_access returns "Forbidden" string for permission failures
                code = 403 if msg == "Forbidden" else 400
                if "problem_status" in (result or {}):
                    # number_conflict also carries the dry-run fields.
                    extra = {
                        k: v for k, v in result.items() if k not in ("status", "message", "problem_status", "title")
                    }
                    raise _UpdateRejected(
                        problem(result["problem_status"], result["title"], msg, **{"rows": [], **extra})
                    )
                # roster_alive_exceeds_6w also says how many kits the breeder must mark dead.
                extra = {key: value for key, value in (result or {}).items() if key == "must_mark_dead"}
                # Roll back anything written in this transaction.
                raise _UpdateRejected(problem(code, "Forbidden" if code == 403 else "Update failed", msg, **extra))
    except _UpdateRejected as rejected:
        return rejected.response
    except da.HerdTrackingError as exc:  # e.g. 409 from the lock helper: the rabbit changed concurrently
        return problem(exc.status, exc.title, exc.detail, rows=exc.rows)
    except ValueError as exc:
        return problem(400, "Update failed", str(exc))
    except Exception:
        logging.exception("Failed to update individual %s", number)
        return problem(500, "Internal error", "Kunde inte uppdatera individen")

    # Cache invalidation + reload are best-effort after successful write.
    # Never return 500 for post-write failures — the mutation already applied.
    from utils.cache_invalidation import get_genebank_id_for_herd, trigger_invalidation

    try:
        herd_val = form.get("herd", "")
        herd_code = herd_val if isinstance(herd_val, str) else herd_val.get("herd", "")
        if herd_code:
            for gid in get_genebank_id_for_herd(herd_code):
                trigger_invalidation(gid)
    except Exception:
        logging.warning("Cache invalidation failed for herd %s", form.get("herd", ""))

    updated = da.get_individual(number, user_uuid)
    return jsonify(_with_can_transfer(updated or individual, user_uuid)), 200


# [Next.js] The caller's own changes on an individual within the undo window (ADR-0017).
@individuals_bp.route("/v2/individual/<number>/commands", methods=["GET"])
@json_login_required
def individual_commands_v2(number):
    user_uuid = session.get("user_id")
    individual = da.get_individual(number, user_uuid)
    if individual is None:
        return problem(404, "Not Found", f"No accessible individual with number {number}")
    return jsonify({"commands": own_recent_commands(da.fetch_user_info(user_uuid), individual["id"])}), 200


# [Next.js] Undo one's own change, or correct anyone's as an editor with a reason (ADR-0017).
@individuals_bp.route("/v2/individual-commands/<uuid:operation_id>/undo", methods=["POST"])
@json_login_required
def undo_individual_command_v2(operation_id):
    user_uuid = session.get("user_id")
    entry = IndividualCommand.get_or_none(IndividualCommand.operation_id == operation_id)
    # As update_individual_v2: an individual the user may not read is not found, before execute.
    if entry is None or da.get_individual(entry.individual.number, user_uuid) is None:
        return problem(404, "Hittades inte", "Ändringen finns inte.")
    body = request.get_json(silent=True)
    reason = body.get("reason") if isinstance(body, dict) else None
    try:
        execute(da.fetch_user_info(user_uuid), entry.individual_id, lambda ctx: [Undo(operation_id, reason)])
    except HerdTrackingError as exc:
        return problem(exc.status, exc.title, exc.detail, rows=exc.rows)
    except IndividualRefused as exc:
        message = exc.envelope.get("message")
        if message == "Individual not found":
            return problem(404, "Hittades inte", message)
        return problem(403, "Åtkomst nekad", message)
    return jsonify({"operation_id": str(operation_id)}), 200
