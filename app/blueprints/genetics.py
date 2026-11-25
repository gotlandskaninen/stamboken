"""
The genetics work list and its export, for Next.js. Every read is logged (log_export).

The calculations and their cache stay in herdbook.py, which this module never imports
(ADR-0007): herdbook.py hands over the memoized priorities as APP.extensions["genetic_priorities"].
"""

from datetime import date

import utils.settings as settings
import utils.work_list as work_list
from flask import Blueprint, Response, current_app, jsonify, request
from flask_login import current_user
from utils.database import Individual

from .common import DEMO_EXPORT_REFUSED, check_genebank_access, json_login_required, log_export, problem

genetics_bp = Blueprint("genetics", __name__, url_prefix="/api")


def _head_refused():
    """Flask sends HEAD to GET views; a HEAD must not log a read it never sends."""
    body, status, headers = problem(405, "Metoden stöds inte", "Hämta med GET.")
    return body, status, {**headers, "Allow": "GET"}


def _log_read(action, genebank_id, rows, **details):
    """One audit row per read: who, which genebank and which rabbits, by number, never a value."""
    log_export(
        Individual,
        action,
        genebank=genebank_id,
        **details,
        rows=len(rows),
        numbers=[r["individual_id"] for r in rows],
        reason_numbers=work_list.reason_numbers(rows),  # founderdjur named in Skäl
    )


@genetics_bp.route("/v2/genetics/<int:genebank_id>/work-list", methods=["GET"])
@json_login_required
def work_list_rows(genebank_id):
    """The Avelsprioritet list: the priorities with each rabbit's name, sex, birth date and current herd.

    Admin or the genebank's manager (ADR-0014). Every read is logged before the rows are returned
    (owner's decision 2026-11-25), in the demo too, where the rows go at the nightly sync.
    """
    if request.method == "HEAD":
        return _head_refused()
    refused = check_genebank_access(genebank_id)
    if refused:
        return refused
    priorities = current_app.extensions["genetic_priorities"](genebank_id)
    rows = work_list.with_details(priorities, current_user.accessible_genebanks)
    _log_read("avelsprioritet-lista", genebank_id, rows)
    response = jsonify(rows)
    response.headers["Cache-Control"] = "no-store"  # a cached copy would skip the audit row
    return response


@genetics_bp.route("/v2/genetics/<int:genebank_id>/priorities.csv", methods=["GET"])
@json_login_required
def priorities_csv(genebank_id):
    """The Avelsprioritet list as a CSV file, with one audit row per download naming the rabbits that left.

    Query: `levels` (comma-separated critical, important, normal; default all) and `per_herd=1`.
    Admin or the genebank's manager (ADR-0014). Refused in the demo, whose audit rows go at the nightly sync.
    """
    if request.method == "HEAD":
        return _head_refused()
    refused = check_genebank_access(genebank_id)
    if refused:
        return refused
    if settings.service.demo_instance:
        return problem(403, "Inte i testmiljön", DEMO_EXPORT_REFUSED)
    wanted = set(request.args.get("levels", ",".join(work_list.LEVELS)).split(","))
    if not wanted <= set(work_list.LEVELS):
        return problem(400, "Okänd nivå", f"levels tar {', '.join(work_list.LEVELS)}.")
    levels = [level for level in work_list.LEVELS if level in wanted]
    per_herd = request.args.get("per_herd") == "1"

    priorities = current_app.extensions["genetic_priorities"](genebank_id)
    rows = work_list.select(work_list.with_details(priorities, current_user.accessible_genebanks), levels, per_herd)
    body = work_list.priorities_csv(rows)
    # Logged before the file is returned: no download without its row.
    _log_read("avelsprioritet", genebank_id, rows, levels=levels, per_herd=per_herd)
    filename = f"avelsprioritet-genbank-{genebank_id}-{date.today().isoformat()}.csv"
    return Response(
        body,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",  # a cached copy would skip the audit row
        },
    )
