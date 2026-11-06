"""
Herd-tracking v2 endpoints.

Thin route handlers; all rules live in utils/herd_tracking.py (ADR-0007).
Errors are RFC 9457 Problem Details; 409 responses carry the offending `rows`.
"""

import logging

from flask import Blueprint, jsonify, request
from flask_login import current_user
from utils import herd_tracking as ht
from utils.database import HerdTracking, Individual, User, not_voided

from .common import check_genebank_access, json_login_required, manager_required, problem

logger = logging.getLogger(__name__)
herd_tracking_bp = Blueprint("herd_tracking", __name__, url_prefix="/api")


def _actor():
    """The real User row (FK writes need a model instance, not the LocalProxy)."""
    return User.get_by_id(current_user.id)


def _accessible_individual(number):
    """
    The single access gate for herd-tracking routes (M23). Same read rule as data_access.get_individual:
    the genebank of the CURRENT herd must be accessible. Write routes must call this BEFORE
    any service call: the void service's idempotent returns precede its permission check.
    """
    individual = Individual.select().where(Individual.number == number).where(not_voided()).first()
    return _readable(individual)


def _readable(individual, allow_voided=False):
    """The same gate for an already loaded Individual (None passes through): not voided + genebank accessible."""
    if (
        individual is None
        or (individual.voided and not allow_voided)
        or individual.current_herd.genebank_id not in current_user.accessible_genebanks
    ):
        return None
    return individual


def _error(exc):
    extra = {"rows": exc.rows} if exc.rows else {}
    return problem(exc.status, exc.title, exc.detail, **extra)


def _flag(name):
    value = request.args.get(name)
    return None if value is None else value.lower() in ("1", "true", "yes")


# [Next.js] Herd-tracking history: rows in server order + periods.
@herd_tracking_bp.route("/v2/individual/<number>/herd-tracking", methods=["GET"])
@json_login_required
def get_herd_tracking(number):
    individual = _accessible_individual(number)
    if individual is None:
        return _not_found()
    return jsonify(ht.herd_tracking_history(individual, _actor(), include_voided=_flag("include_voided")))


def _not_found():
    return problem(404, "Hittades inte", "Individen finns inte eller är inte tillgänglig.")


def _json_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


def _invalidate_genebank(genebank_id):
    """Best-effort Next.js cache invalidation — never fails the request after the write."""
    try:
        from utils.cache_invalidation import trigger_invalidation

        trigger_invalidation(genebank_id)
    except Exception:  # pylint: disable=broad-except
        logger.warning("Cache invalidation failed for genebank %s", genebank_id, exc_info=True)


def _invalidate(individual):
    _invalidate_genebank(individual.origin_herd.genebank_id)


# [Next.js] Void one herd-tracking row — also "Ångra försäljning".
@herd_tracking_bp.route("/v2/herd-tracking/<int:ht_id>/void", methods=["POST"])
@json_login_required
def void_herd_tracking_row(ht_id):
    body = _json_body()
    if body is None:
        return problem(400, "Ogiltig begäran", "Skicka ett JSON-objekt med reason och operation_id.")
    row = HerdTracking.get_or_none(HerdTracking.id == ht_id)
    # Gate BEFORE the service: its idempotent returns precede its permission check (M23).
    individual = _readable(Individual.get_or_none(Individual.id == row.individual_id)) if row else None
    if individual is None:
        return problem(404, "Hittades inte", "Raden finns inte.")
    actor = _actor()
    try:
        ht.void_herd_tracking(ht_id, actor, body.get("reason"), body.get("operation_id"))
    except ht.HerdTrackingError as exc:
        return _error(exc)
    _invalidate(individual)
    return jsonify(ht.herd_tracking_history(Individual.get_by_id(individual.id), actor, include_voided=True)), 200


# [Next.js] Manager correction command.
@herd_tracking_bp.route("/v2/individual/<number>/herd-tracking/corrections", methods=["POST"])
@json_login_required
@manager_required
def post_herd_tracking_correction(number):
    individual = _accessible_individual(number)
    if individual is None:
        return _not_found()
    denied = check_genebank_access(individual.origin_herd.genebank_id)
    if denied:
        return denied
    body = _json_body()
    events = (body or {}).get("events", [])
    void_ids = (body or {}).get("void_ids", [])
    if (
        body is None
        or not isinstance(events, list)
        or not all(isinstance(e, dict) for e in events)
        or not isinstance(void_ids, list)
        or not all(isinstance(v, int) and not isinstance(v, bool) for v in void_ids)
    ):
        return problem(
            400, "Ogiltig begäran", "events ska vara en lista med händelser och void_ids en lista med rad-id:n."
        )
    actor = _actor()
    try:
        ht.correct_herd_tracking(
            individual, actor, body.get("operation_id"), void_ids, events, reason=body.get("reason")
        )
    except ht.HerdTrackingError as exc:
        return _error(exc)
    _invalidate(individual)
    return jsonify(ht.herd_tracking_history(Individual.get_by_id(individual.id), actor, include_voided=True)), 201


# [Next.js] Undo a whole herd-tracking operation.
@herd_tracking_bp.route("/v2/herd-tracking/operations/<operation_id>/undo", methods=["POST"])
@json_login_required
@manager_required
def undo_herd_tracking_operation_route(operation_id):
    body = _json_body() or {}
    actor = _actor()
    try:
        op = ht.new_operation_id(operation_id)
    except ht.HerdTrackingError as exc:
        return _error(exc)
    individuals = list(
        Individual.select().where(Individual.id.in_(ht.operation_individual_ids(op))).order_by(Individual.id)
    )
    # Gate every affected individual BEFORE the service (M23): any inaccessible one => 404.
    if any(_readable(i, allow_voided=True) is None for i in individuals):
        return problem(404, "Hittades inte", "Åtgärden finns inte.")
    try:
        result = ht.undo_herd_tracking_operation(op, actor, body.get("reason"), body.get("operation_id"))
    except ht.HerdTrackingError as exc:
        return _error(exc)
    undone = list(Individual.select().where(Individual.id.in_(result["individual_ids"])).order_by(Individual.id))
    for genebank_id in {i.origin_herd.genebank_id for i in undone}:
        _invalidate_genebank(genebank_id)
    return (
        jsonify(
            {
                "undo_operation_id": result["undo_operation_id"],
                "individuals": [
                    {"number": i.number, "history": ht.herd_tracking_history(i, actor, include_voided=True)}
                    for i in undone
                ],
            }
        ),
        200,
    )
