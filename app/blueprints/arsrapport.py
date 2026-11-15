"""
Arsrapport (yearly report) endpoints.

Thin route handlers — business logic belongs in utils/arsrapport.py.
See ADR-0007 for blueprint conventions.
"""

import uuid
from dataclasses import asdict
from datetime import date, datetime

import utils.arsrapport as arsrapport
import utils.inbox as inbox
from flask import Blueprint, jsonify, request
from flask_login import current_user
from utils.arsrapport import ArsrapportError
from utils.database import OUTSIDE_GENEBANK_HERDS, Genebank, Herd, YearlyReportRound

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


def _report_target(code, year):
    """
    The herd, the year's round and the caller's access, for every route under besattning/<herd>/<year>. `?post=` is
    the taken paper item that report_access reads (Task 9); a missing access is a 403.
    """
    herd = Herd.get_or_none(Herd.herd == code)
    if herd is None or herd.herd in OUTSIDE_GENEBANK_HERDS:
        raise ArsrapportError(404, "Besättningen finns inte.")
    post = request.args.get("post")
    if post is not None and not post.isdecimal():
        raise ArsrapportError(400, "Ange posten som ett nummer.")
    access = arsrapport.report_access(current_user, herd, int(post) if post is not None else None)
    if access is None:
        raise ArsrapportError(403, "Du har inte tillgång till årsrapporten för besättningen.")
    round_ = arsrapport.get_round(year)
    if round_ is None:
        raise ArsrapportError(404, f"Det finns ingen runda för {year}.")
    return herd, round_, access


# [Next.js] The logged-in user's reports: the herd's rounds the genebank has activated.
@arsrapport_bp.route("/v2/arsrapport/mina", methods=["GET"])
@json_login_required
def my_reports():
    return jsonify({"reports": arsrapport.my_reports(current_user)})


# [Next.js] The report page: the list, the year's litters and sales, the report and the draft (ReportView).
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>", methods=["GET"])
@json_login_required
def report_view(herd, year):
    herd, round_, access = _report_target(herd, year)
    return jsonify(arsrapport.report_view(herd, round_, access, current_user))


# [Next.js] Autosave of the server draft; a stale version is a 409 with the current draft.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/utkast", methods=["PUT"])
@json_login_required
def save_draft(herd, year):
    herd, round_, access = _report_target(herd, year)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ArsrapportError(400, "Skicka utkastet som JSON.")
    revision = body.get("revision")
    if revision is not None and type(revision) is not int:  # True is an int too
        raise ArsrapportError(400, "Ange revisionen som ett heltal.")
    try:
        updated_at = datetime.fromisoformat(body["updated_at"]) if body.get("updated_at") is not None else None
        key = uuid.UUID(body["submission_key"]) if body.get("submission_key") is not None else None
    except (AttributeError, TypeError, ValueError) as exc:
        raise ArsrapportError(400, "Ange updated_at som en tidpunkt och submission_key som ett UUID.") from exc
    draft = arsrapport.save_draft(herd, round_, access, current_user, body.get("data"), updated_at, key, revision)
    return jsonify({"updated_at": draft.updated_at.isoformat(), "submission_key": str(key) if key else None})


# [Next.js] The dry run before Skicka: every refusal per rabbit, and the warnings; nothing is written.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/torrkorning", methods=["POST"])
@json_login_required
def dry_run(herd, year):
    herd, round_, access = _report_target(herd, year)
    sub = arsrapport.parse_submission(request.get_json(silent=True), paper=access.source == "paper")
    report = arsrapport.current_report(herd, round_)
    refusals, warnings = arsrapport.check(herd, round_, access, report, sub, on=arsrapport.today())
    return jsonify(
        {"ok": not refusals, "refusals": [asdict(r) for r in refusals], "warnings": [asdict(w) for w in warnings]}
    )


# [Next.js] Skicka: the submission in one transaction and its Receipt; the same request again gets the same one.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/skicka", methods=["POST"])
@json_login_required
def submit(herd, year):
    body = request.get_json(silent=True)
    sub = arsrapport.parse_submission(body, paper=request.args.get("post") is not None)  # a 400 before any lookup
    target, round_ = Herd.get_or_none(Herd.herd == herd), arsrapport.get_round(year)
    if target is not None and round_ is not None:  # before report_access: a retry after the item closed (Fable 5)
        saved = arsrapport.find_submission(sub.key, target, round_, current_user, arsrapport.request_hash(sub))
        if saved is not None:
            return jsonify(arsrapport.receipt(saved))
    target, round_, access = _report_target(herd, year)
    return jsonify(arsrapport.submit(target, round_, access, current_user, sub, body))
