"""
Genetics exports for Next.js.

The calculations and their cache stay in herdbook.py, which this module never imports
(ADR-0007): herdbook.py hands over the memoized priorities as APP.extensions["genetic_priorities"].
"""

from datetime import date

import utils.settings as settings
import utils.work_list as work_list
from flask import Blueprint, Response, current_app, request
from utils.database import Individual

from .common import DEMO_EXPORT_REFUSED, check_genebank_access, json_login_required, log_export, problem

genetics_bp = Blueprint("genetics", __name__, url_prefix="/api")


@genetics_bp.route("/v2/genetics/<int:genebank_id>/priorities.csv", methods=["GET"])
@json_login_required
def priorities_csv(genebank_id):
    """The Avelsprioritet list as a CSV file, with one audit row per download naming the rabbits that left.

    Query: `levels` (comma-separated critical, important, normal; default all) and `per_herd=1`.
    Admin or the genebank's manager (ADR-0014). Refused in the demo, whose audit rows go at the nightly sync.
    """
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
    rows = work_list.select(work_list.with_details(priorities), levels, per_herd)
    body = work_list.priorities_csv(rows)
    # Logged before the file is returned: no download without its row.
    log_export(
        Individual,
        "avelsprioritet",
        genebank=genebank_id,
        levels=levels,
        per_herd=per_herd,
        rows=len(rows),
        numbers=[r["individual_id"] for r in rows],
    )
    filename = f"avelsprioritet-genbank-{genebank_id}-{date.today().isoformat()}.csv"
    return Response(
        body,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",  # a cached copy would skip the audit row
        },
    )
