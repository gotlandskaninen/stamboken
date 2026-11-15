"""
Arsrapport (yearly report) endpoints.

Thin route handlers — business logic belongs in utils/arsrapport.py.
See ADR-0007 for blueprint conventions.
"""

from datetime import date

import utils.arsrapport as arsrapport
import utils.inbox as inbox
from flask import Blueprint, jsonify, request
from flask_login import current_user
from utils.arsrapport import ArsrapportError
from utils.database import Genebank, YearlyReportRound

from .common import check_genebank_access, json_login_required, manager_required, problem

arsrapport_bp = Blueprint("arsrapport", __name__, url_prefix="/api")


@arsrapport_bp.errorhandler(ArsrapportError)
def refused(exc):
    return problem(exc.status, exc.title, exc.detail, **exc.extra)


def _dates(*keys):
    """The body's dates among `keys`, from "YYYY-MM-DD"; a missing or null key is left out."""
    body = request.get_json(silent=True) or {}
    try:
        return {key: date.fromisoformat(body[key]) for key in keys if body.get(key) is not None}
    except (AttributeError, TypeError, ValueError) as exc:
        raise ArsrapportError(400, f"Ange {', '.join(keys)} som ÅÅÅÅ-MM-DD.") from exc


# [Next.js] The rounds, for the queue's link and the round panel.
@arsrapport_bp.route("/v2/arsrapport/rundor", methods=["GET"])
@json_login_required
def rounds():
    if not inbox.works_in_queue(current_user):
        return problem(403, "Åtkomst nekad", "Bara admin, genbanksansvarig och genbankshjälpare ser rundorna.")
    rows = YearlyReportRound.select().order_by(YearlyReportRound.report_year.desc())
    return jsonify({"rounds": [arsrapport.round_json(row) for row in rows]})


# [Next.js] Create the year's round, or move its dates: admin or any genebank manager (spec 8).
@arsrapport_bp.route("/v2/arsrapport/rundor/<int:year>", methods=["PUT"])
@json_login_required
@manager_required
def save_round(year):
    round_ = arsrapport.save_round(year, current_user, **_dates(*arsrapport.DATE_FIELDS))
    return jsonify(arsrapport.round_json(round_))


# [Next.js] "Aktivera och schemalägg" for one genebank: admin or that genebank's manager.
@arsrapport_bp.route("/v2/arsrapport/rundor/<int:year>/genbanker/<int:genebank_id>/aktivera", methods=["POST"])
@json_login_required
def activate(year, genebank_id):
    denied = check_genebank_access(genebank_id)
    if denied:
        return denied
    round_ = arsrapport.get_round(year)
    if round_ is None or Genebank.get_or_none(Genebank.id == genebank_id) is None:
        return problem(404, "Hittades inte", f"Rundan för {year} eller genbanken finns inte.")
    arsrapport.activate(round_, genebank_id, current_user, **_dates("send_at"))
    return jsonify(arsrapport.round_json(round_))
