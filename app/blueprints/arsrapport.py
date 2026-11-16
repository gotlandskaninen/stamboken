"""
Arsrapport (yearly report) endpoints.

Thin route handlers — business logic belongs in utils/arsrapport.py.
See ADR-0007 for blueprint conventions.
"""

import os
import uuid
from dataclasses import asdict
from datetime import date, datetime
from functools import wraps

import utils.arsrapport as arsrapport
import utils.inbox as inbox
from flask import Blueprint, current_app, g, jsonify, request, send_file
from flask_login import current_user
from utils.arsrapport import ArsrapportError
from utils.database import DATABASE, OUTSIDE_GENEBANK_HERDS, Genebank, Herd, ReportAccessCode, YearlyReportRound
from utils.report_code import CodeActor

from .common import check_genebank_access, json_login_required, manager_required, problem
from .rapport_link import session_codes, touch

arsrapport_bp = Blueprint("arsrapport", __name__, url_prefix="/api")


@arsrapport_bp.errorhandler(ArsrapportError)
def refused(exc):
    return problem(exc.status, exc.title, exc.detail, **exc.extra)


@arsrapport_bp.errorhandler(inbox.InboxError)
def queue_refused(exc):
    """The paper path's item checks under its lock (inbox.lock_item, require_handler)."""
    return problem(exc.status, exc.title, exc.detail)


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


def _codes_in_session(herd, round_):
    """The session's codes for the herd and round, newest first, valid or not: who a retry or a refusal is about."""
    ids = session_codes(arsrapport.now())
    if not ids:
        return []
    query = ReportAccessCode.select().where(
        ReportAccessCode.id.in_(ids), ReportAccessCode.herd == herd.id, ReportAccessCode.round == round_.id
    )
    return list(query.order_by(ReportAccessCode.id.desc()))


def _audit_as(actor):
    """The audit triggers' session variables, as before_request sets them for an account."""
    try:
        DATABASE.execute_sql("SELECT set_config('audit.user', %s, false)", (actor.username,))
        DATABASE.execute_sql("SELECT set_config('audit.ip', %s, false)", (request.remote_addr or "",))
    except Exception:  # pylint: disable=broad-except  # as before_request: the write goes on without it
        current_app.logger.warning("Failed to set audit context", exc_info=True)


def _actor(access):
    """The account, or the link for a code access: what the service writes as the actor."""
    return CodeActor(access.code) if access.code else current_user


def _retry_actors(herd, round_):
    """
    Who a retry of Skicka may be looked up for, before the access is read: the account, and the session's codes for
    the herd, valid or not. A submission made with a code gets its receipt only while that code is valid (E4); the
    retry of a paper item's account submission keeps its exception (Codex 5).
    """
    user = current_user if current_user.is_authenticated else None
    codes = [CodeActor(code) for code in _codes_in_session(herd, round_)]
    return ([user] if user is not None else []) + codes


def report_actor_required(f):
    """
    A route that takes a login or a code session instead of json_login_required: 401 for neither (`session_ute` when
    a code session timed out). `_report_target` decides which of the two applies to the herd in the URL: the
    account's own right when it has one, otherwise the session's valid code for that herd, never both (section 6).
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.is_authenticated or session_codes(arsrapport.now()):
            return f(*args, **kwargs)
        if g.get("rapport_expired"):
            return problem(401, "Sessionen har gått ut", "Öppna länken i mejlet igen.", code="session_ute")
        return problem(401, "Autentisering krävs", "Du måste vara inloggad.")

    return decorated


def _report_target(code, year):
    """
    The herd, the year's round, the caller's access and the actor, for every route under besattning/<herd>/<year>.
    `?post=` is the taken paper item that report_access reads (Task 9). A login with a right to the herd goes
    first, the session's valid code for the herd second; a login without either is a 403, a code session for other
    herds a 404, and a code session that timed out a 401 `session_ute`.
    """
    herd = Herd.get_or_none(Herd.herd == code)
    if herd is None or herd.herd in OUTSIDE_GENEBANK_HERDS:
        raise ArsrapportError(404, "Besättningen finns inte.")
    post = request.args.get("post")
    if post is not None and not post.isdecimal():
        raise ArsrapportError(400, "Ange posten som ett nummer.")
    access = None
    if current_user.is_authenticated:
        access = arsrapport.report_access(current_user, herd, int(post) if post is not None else None)
    round_ = arsrapport.get_round(year)
    if access is None and post is None and round_ is not None:
        ids = session_codes(arsrapport.now())
        access = arsrapport.code_access(herd, round_, ids) if ids else None
        if access is not None:
            touch(arsrapport.now())
    if access is None:
        if current_user.is_authenticated:
            raise ArsrapportError(403, "Du har inte tillgång till årsrapporten för besättningen.")
        raise ArsrapportError(404, "Besättningen finns inte.")  # a code session, but not for this herd
    if round_ is None:
        raise ArsrapportError(404, f"Det finns ingen runda för {year}.")
    if access.code is not None:  # the audit log names the link, also for a logged-in user who writes through it
        _audit_as(CodeActor(access.code))
    return herd, round_, access


def _submission_body():
    """The dry run's and Skicka's JSON body, at most as large as a draft may be."""
    if len(request.get_data()) > arsrapport.DRAFT_MAX_BYTES:
        raise ArsrapportError(400, "Rapporten är för stor.")
    return request.get_json(silent=True)


# [Next.js] The logged-in user's reports: the herd's rounds the genebank has activated.
@arsrapport_bp.route("/v2/arsrapport/mina", methods=["GET"])
@json_login_required
def my_reports():
    return jsonify({"reports": arsrapport.my_reports(current_user)})


# [Next.js] The report page: the list, the year's litters and sales, the report and the draft (ReportView).
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>", methods=["GET"])
@report_actor_required
def report_view(herd, year):
    herd, round_, access = _report_target(herd, year)
    return jsonify(arsrapport.report_view(herd, round_, access, _actor(access)))


# [Next.js] Autosave of the server draft; a stale version is a 409 with the current draft.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/utkast", methods=["PUT"])
@report_actor_required
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
    draft = arsrapport.save_draft(herd, round_, access, _actor(access), body.get("data"), updated_at, key, revision)
    return jsonify({"updated_at": draft.updated_at.isoformat(), "submission_key": str(key) if key else None})


# [Next.js] The dry run before Skicka: every refusal per rabbit, and the warnings; nothing is written.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/torrkorning", methods=["POST"])
@report_actor_required
def dry_run(herd, year):
    herd, round_, access = _report_target(herd, year)
    sub = arsrapport.parse_submission(_submission_body(), paper=access.source == "paper")
    on = arsrapport.today()
    if access.item is not None:
        arsrapport.check_paper(sub, access, on)
    report = arsrapport.current_report(herd, round_)
    refusals, warnings = arsrapport.check(herd, round_, access, report, sub, on=on)
    return jsonify(
        {"ok": not refusals, "refusals": [asdict(r) for r in refusals], "warnings": [asdict(w) for w in warnings]}
    )


# [Next.js] Skicka: the submission in one transaction and its Receipt; the same request again gets the same one.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/skicka", methods=["POST"])
@report_actor_required
def submit(herd, year):
    sub = arsrapport.parse_submission(_submission_body(), paper=request.args.get("post") is not None)  # before lookups
    target, round_ = Herd.get_or_none(Herd.herd == herd), arsrapport.get_round(year)
    if target is not None and round_ is not None:  # before report_access: a retry after the item closed (Fable 5)
        actors = _retry_actors(target, round_)

        def digest(by_link):  # as the original submission's actor was treated
            return arsrapport.request_hash(arsrapport.without_reason(sub) if by_link else sub)

        try:
            saved = arsrapport.find_submission(sub.key, target, round_, actors, digest) if actors else None
        except ArsrapportError as exc:
            if exc.status == 409 and any(isinstance(actor, CodeActor) for actor in actors):
                arsrapport.stale_link_retry(sub.key, target, round_)  # a reissued link: 403 lank_ogiltig
            raise
        if saved is not None:
            if saved.access_code_id is not None:  # E4 on every use, also for a receipt
                arsrapport.require_valid_code(saved.access_code_id, target)
            return jsonify(arsrapport.receipt(saved))
    target, round_, access = _report_target(herd, year)
    return jsonify(arsrapport.submit(target, round_, access, _actor(access), sub))


# [Next.js] Dra tillbaka: the whole report backed out; body {revision, reason}, the reason required of an editor.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/dra-tillbaka", methods=["POST"])
@report_actor_required
def withdraw(herd, year):
    herd, round_, access = _report_target(herd, year)
    body = _submission_body()
    if not isinstance(body, dict):
        raise ArsrapportError(400, "Skicka revision och orsak som JSON.")
    revision = body.get("revision")
    if type(revision) is not int:  # True is an int too
        raise ArsrapportError(400, "Ange revisionen som ett heltal.", field="revision")
    view = arsrapport.withdraw(herd, round_, access, _actor(access), revision=revision, reason=body.get("reason"))
    return jsonify(view)


# [Next.js] "I tid" for a submitted report: body {on_time: true | false | null}; the genebank's manager or admin.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/i-tid", methods=["POST"])
@json_login_required
def on_time(herd, year):
    target = Herd.get_or_none(Herd.herd == herd)
    if target is None or target.herd in OUTSIDE_GENEBANK_HERDS:
        raise ArsrapportError(404, "Besättningen finns inte.")
    denied = check_genebank_access(target.genebank_id)
    if denied:
        return denied
    round_ = arsrapport.get_round(year)
    report = arsrapport.current_report(target, round_) if round_ else None
    if report is None:
        raise ArsrapportError(404, "Besättningen har ingen inskickad rapport för året.")
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("on_time", ""), bool | None):
        raise ArsrapportError(400, "Ange on_time som true, false eller null.", field="on_time")
    report = arsrapport.set_on_time(report, current_user, body["on_time"])
    return jsonify({"on_time_override": report.on_time_override})


# [Next.js] The status view of one genebank: admin, its manager or its helper (inbox.can_handle).
@arsrapport_bp.route("/v2/arsrapport/<int:year>/status", methods=["GET"])
@json_login_required
def status(year):
    genebank_id = request.args.get("genebank_id", type=int)
    if genebank_id is None:
        raise ArsrapportError(400, "Ange genebank_id som ett nummer.", field="genebank_id")
    if not inbox.can_handle(current_user, genebank_id):
        return problem(403, "Åtkomst nekad", "Du saknar behörighet för denna genbank.")
    round_ = arsrapport.get_round(year)
    if round_ is None or Genebank.get_or_none(Genebank.id == genebank_id) is None:
        raise ArsrapportError(404, f"Rundan för {year} eller genbanken finns inte.")
    # The phone is for calling; helpers do not get it.
    with_phone = check_genebank_access(genebank_id) is None
    return jsonify(arsrapport.status_view(round_, genebank_id, with_phone=with_phone))


# [Next.js] The blank årsblankett as a PDF, put on the private volume by ops (docs/arsrapport.md).
@arsrapport_bp.route("/v2/arsrapport/blankett.pdf", methods=["GET"])
@json_login_required
def blank_form():
    path = inbox.private_path(arsrapport.BLANK_FORM)
    if not os.path.isfile(path):
        return problem(404, "Hittades inte", "Blanketten finns inte på servern än.")
    return send_file(path, mimetype="application/pdf", max_age=0)
