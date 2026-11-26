"""
Arsrapport (yearly report) endpoints.

Thin route handlers — business logic belongs in utils/arsrapport.py.
See ADR-0007 for blueprint conventions.
"""

import io
import math
import os
import uuid
from dataclasses import asdict
from datetime import date, datetime
from functools import wraps

import utils.arsrapport as arsrapport
import utils.arsrapport_invite as invite
import utils.arsrapport_pdf as arsrapport_pdf
import utils.arsrapport_remind as remind
import utils.inbox as inbox
import utils.purchase_notice as purchase_notice
import utils.sale_proposal as sale_proposal
from extensions import limiter
from flask import Blueprint, current_app, g, jsonify, request, send_file, session
from flask_login import current_user
from limits import parse as parse_limit
from utils.arsrapport import ArsrapportError
from utils.database import (
    DATABASE,
    OUTSIDE_GENEBANK_HERDS,
    Genebank,
    Herd,
    ReportAccessCode,
    SaleProposal,
    YearlyReportRound,
)
from utils.legacy_compat import report_link_only
from utils.matrikel import resolve_own_membership
from utils.report_code import CodeActor, actor_key

from .common import check_genebank_access, json_login_required, manager_required, problem
from .inbox import REGISTRATION_FIELDS, _each_image, _Refused, certificate_upload_refusal
from .individual_v2_create import may_register_in, number_suggestion, paper_number_check, register_individual_as
from .rapport_link import _environment, session_codes, touch
from .uploads import MAX_FILE_REQUEST

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
    return jsonify(arsrapport.round_json(arsrapport.get_round(year)))


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


def _report_user():
    return current_user if not report_link_only() and current_user.is_authenticated else None


def _retry_actors(herd, round_):
    """
    Who a retry of Skicka may be looked up for, before the access is read: the account, and the session's codes for
    the herd, valid or not. A submission made with a code gets its receipt only while that code is valid (E4); the
    retry of a paper item's account submission keeps its exception (Codex 5).
    """
    user = _report_user()
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
        if _report_user() or session_codes(arsrapport.now()):
            return f(*args, **kwargs)
        if g.get("rapport_expired"):
            return problem(401, "Sessionen har gått ut", "Öppna länken i mejlet igen.", code="session_ute")
        return problem(401, "Autentisering krävs", "Du måste vara inloggad.")

    decorated.accepts_report_code = True
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
    user = _report_user()
    if user:
        access = arsrapport.report_access(user, herd, int(post) if post is not None else None)
    round_ = arsrapport.get_round(year)
    if access is None and post is None and round_ is not None:
        ids = session_codes(arsrapport.now())
        access = arsrapport.code_access(herd, round_, ids) if ids else None
        if access is not None:
            touch(arsrapport.now())
    if access is None:
        if user:
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


# [Next.js] The sale dialog's buyer herds for the personal link, which has no genebank picker of its own (4a).
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/besattningar", methods=["GET"])
@report_actor_required
def buyer_herds(herd, year):
    herd, _, _ = _report_target(herd, year)
    return jsonify({"herds": arsrapport.buyer_herds(herd)})


# [Next.js] "Anmäl köpet": body {number, from_herd, date, document_id?, doc_type?}; a purchase notice in the genebank's
# queue (4a Task 5), with the photo of its proof or certificate that this session uploaded through …/foto.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/kop", methods=["POST"])
@report_actor_required
def report_purchase(herd, year):
    herd, round_, access = _report_target(herd, year)  # a link writes only its own herd and year
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ArsrapportError(400, "Skicka köpet som JSON.")
    when = _dates("date").get("date")
    photo = body.get("document_id")
    if photo is not None and type(photo) is not int:  # True is an int too
        raise ArsrapportError(400, arsrapport.PHOTO_GONE, field="photo")
    item = purchase_notice.report_purchase(
        herd,
        round_,
        access,
        _actor(access),
        number=body.get("number"),
        from_herd=body.get("from_herd"),
        date=when,
        photo_document_id=photo,
        doc_type=body.get("doc_type"),
        photos=_session_photos(access),
    )
    return jsonify(purchase_notice.notice_json(item))


# [Next.js] "Skicka till genbanksansvarig" (S7): body {number, from_herd, date, documents: [{id, doc_type}]}; a rabbit
# Stamboken lacks, its photos uploaded through …/foto?syfte=inskick sent to the queue as an ordinary upload.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/kop/inskick", methods=["POST"])
@report_actor_required
def send_purchase_photos(herd, year):
    if not report_link_only() and (refusal := certificate_upload_refusal()) is not None:
        return refusal
    herd, round_, access = _report_target(herd, year)  # a link writes only its own herd and year
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ArsrapportError(400, "Skicka köpet som JSON.")
    if (limited := _send_limit(access)) is not None:
        return limited
    item = purchase_notice.send_photos(
        herd,
        round_,
        access,
        _actor(access),
        number=body.get("number"),
        from_herd=body.get("from_herd"),
        date=_dates("date").get("date"),
        documents=body.get("documents"),
        photos=_session_photos(access),
    )
    try:
        limiter.limiter.hit(SEND_LIMIT, "arsrapport-inskick", _send_key(access))
    except Exception:  # pylint: disable=broad-except
        current_app.logger.exception("Send rate limit count failed")
    return jsonify(purchase_notice.notice_json(item))


# [Next.js] The herd's register extract on 31 December as a PDF, for the member to check against (section 9).
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/registerutdrag.pdf", methods=["GET"])
@report_actor_required
def register_extract(herd, year):
    herd, round_, _ = _report_target(herd, year)
    response = send_file(
        io.BytesIO(arsrapport_pdf.register_extract_pdf(herd, round_)),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"registerutdrag-{herd.herd}-{year}.pdf",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


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


def _saved_receipt(herd, year, key, digest):
    """
    A retry's receipt, looked up before report_access: a retry after the item closed (Fable 5). `digest(by_link)`
    hashes the request as the original submission's actor was treated. None for a new request.
    """
    target, round_ = Herd.get_or_none(Herd.herd == herd), arsrapport.get_round(year)
    if target is None or round_ is None:
        return None
    actors = _retry_actors(target, round_)
    try:
        saved = arsrapport.find_submission(key, target, round_, actors, digest) if actors else None
    except ArsrapportError as exc:
        if exc.status == 409 and any(isinstance(actor, CodeActor) for actor in actors):
            arsrapport.stale_link_retry(key, target, round_)  # a reissued link: 403 lank_ogiltig
        raise
    if saved is not None and saved.access_code_id is not None:  # E4 on every use, also for a receipt
        arsrapport.require_valid_code(saved.access_code_id, target)
    return arsrapport.receipt(saved) if saved is not None else None


# [Next.js] Skicka: the submission in one transaction and its Receipt; the same request again gets the same one.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/skicka", methods=["POST"])
@report_actor_required
def submit(herd, year):
    sub = arsrapport.parse_submission(_submission_body(), paper=request.args.get("post") is not None)  # before lookups

    def digest(by_link):
        return arsrapport.request_hash(arsrapport.without_reason(sub) if by_link else sub)

    if (saved := _saved_receipt(herd, year, sub.key, digest)) is not None:
        return jsonify(saved)
    target, round_, access = _report_target(herd, year)
    return jsonify(arsrapport.submit(target, round_, access, _actor(access), sub))


def _completion():
    """The partial answer's body (D9); never from paper, whose entry is "från blankett" (P8)."""
    if request.args.get("post") is not None:
        raise ArsrapportError(400, "Svaren för kaniner som saknas skickas inte från blankett.")
    body = _submission_body()
    if not isinstance(body, dict):
        raise ArsrapportError(400, "Skicka svaren som JSON.")
    return arsrapport.parse_completion(body)


# [Next.js] The dry run of a partial answer: body {submission_key, revision, rabbits}; nothing is written.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/komplettera/torrkorning", methods=["POST"])
@report_actor_required
def completion_dry_run(herd, year):
    patch = _completion()
    herd, round_, access = _report_target(herd, year)
    report = arsrapport.current_report(herd, round_)
    sub = arsrapport.merge_completion(report, patch)
    on = arsrapport.today()
    refusals, warnings = arsrapport.check(herd, round_, access, report, sub, on=on, completion=True)
    return jsonify(
        {"ok": not refusals, "refusals": [asdict(r) for r in refusals], "warnings": [asdict(w) for w in warnings]}
    )


# [Next.js] Skicka svar: the rabbits a paper form left out, answered on their own (Å22, D9), as a new submission of
# the report; its arrival date and the rest of it stay. The same request again gets the same Receipt.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/komplettera", methods=["POST"])
@report_actor_required
def complete(herd, year):
    patch = _completion()
    saved = _saved_receipt(herd, year, patch.key, lambda _: arsrapport.request_hash(patch, completion=True))
    if saved is not None:
        return jsonify(saved)
    target, round_, access = _report_target(herd, year)
    return jsonify(arsrapport.submit(target, round_, access, _actor(access), patch, completion=True))


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


# [Next.js] "Kullar under Y": a litter without a certificate, registered at once (it stays if the report is withdrawn).
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/kull", methods=["POST"])
@report_actor_required
def add_litter(herd, year):
    herd, round_, access = _report_target(herd, year)
    litter = arsrapport.add_litter(herd, round_, access, _actor(access), _submission_body(), account=current_user)
    return jsonify(litter), 201


# [Next.js] A litter's counts, confirmed (the 6-week count) or changed; the dialog's "Ja, ändra den" after samma_kull.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/kull/<int:breeding_id>", methods=["PATCH"])
@report_actor_required
def change_litter(herd, year, breeding_id):
    herd, round_, access = _report_target(herd, year)
    return jsonify(arsrapport.change_litter(herd, round_, access, _actor(access), breeding_id, _submission_body()))


# [Next.js] The mother picker of the litter dialog: the herd's does in the year, with a login or a link alike.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/honor", methods=["GET"])
@report_actor_required
def litter_mothers(herd, year):
    herd, _, _ = _report_target(herd, year)
    return jsonify({"honor": arsrapport.report_mothers(herd, year)})


# [Next.js] The father picker of the litter dialog: the genebank's males, with a login or a link alike.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/hanar", methods=["GET"])
@report_actor_required
def litter_fathers(herd, year):
    herd, _, _ = _report_target(herd, year)
    return jsonify({"hanar": arsrapport.report_fathers(herd, year)})


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


def _genebank_round(year, genebank_id):
    round_ = arsrapport.get_round(year)
    if round_ is None or Genebank.get_or_none(Genebank.id == genebank_id) is None:
        raise ArsrapportError(404, f"Rundan för {year} eller genbanken finns inte.")
    return round_


# [Next.js] "Skicka provmejl till mig": the invitation to the manager's own address, with no link.
@arsrapport_bp.route("/v2/arsrapport/rundor/<int:year>/genbanker/<int:genebank_id>/provmejl", methods=["POST"])
@json_login_required
def test_mail(year, genebank_id):
    denied = check_genebank_access(genebank_id)
    if denied:
        return denied
    invite.test_mail(_genebank_round(year, genebank_id), genebank_id, current_user)
    return jsonify({"queued": True})


# [Next.js] How many herds the invitation reaches by e-mail, counts only.
@arsrapport_bp.route("/v2/arsrapport/rundor/<int:year>/genbanker/<int:genebank_id>/mottagare", methods=["GET"])
@json_login_required
def recipients(year, genebank_id):
    if not inbox.can_handle(current_user, genebank_id):
        return problem(403, "Åtkomst nekad", "Du saknar behörighet för denna genbank.")
    return jsonify(invite.recipients(_genebank_round(year, genebank_id), genebank_id))


# [Next.js] "Ny länk": revokes the herd's link and mails a new one to the main member.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/ny-lank", methods=["POST"])
@json_login_required
def new_link(herd, year):
    target = Herd.get_or_none(Herd.herd == herd)
    if target is None or target.herd in OUTSIDE_GENEBANK_HERDS:
        raise ArsrapportError(404, "Besättningen finns inte.")
    denied = check_genebank_access(target.genebank_id)
    if denied:
        return denied
    invite.new_link(target, _genebank_round(year, target.genebank_id), current_user, now=arsrapport.now())
    return jsonify({"sent": True})


# [Next.js] "Skicka påminnelse": a reminder to the herd's main member now; admin or the herd's genebank manager.
# `queued` is false when one already waits in the mail queue or went today.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/paminnelse", methods=["POST"])
@json_login_required
def send_reminder(herd, year):
    target = Herd.get_or_none(Herd.herd == herd)
    if target is None or target.herd in OUTSIDE_GENEBANK_HERDS:
        raise ArsrapportError(404, "Besättningen finns inte.")
    denied = check_genebank_access(target.genebank_id)
    if denied:
        return denied
    round_ = _genebank_round(year, target.genebank_id)
    queued = remind.send_reminder(target, round_, current_user, now=arsrapport.now())
    return jsonify({"queued": queued is not None})


# "Lägg till kanin från intyget" (4b Task 4, spec 5.8): the certificate's photo first, a `kontroll` item held from the
# queue (G5, inbox.HELD_RABBIT), then the rabbit, registered at once with the report actor's own right and bound to
# that photo, which only then becomes the queue's work.

PHOTO_LIMIT = parse_limit("60 per hour")  # per code or per user, every request with access, refused or not (mitt val)
PHOTO_LIMITED = (
    f"Du har laddat upp {PHOTO_LIMIT.amount} foton den senaste timmen. Det är gränsen, ett skydd mot missbruk. "
    "Du kan fortsätta efter kl. {at}. Det du skrivit är sparat."
)
SEND_LIMIT = parse_limit("20 per hour")  # per actor, as the queue's upload; sends only
SEND_LIMITED = (
    f"Du har skickat {SEND_LIMIT.amount} köpanmälningar den senaste timmen. Det är gränsen, ett skydd mot missbruk. "
    "Du kan fortsätta efter kl. {at}. Det du skrivit är sparat."
)
PHOTOS_KEPT = 60  # the session's own uploads a registration may bind (FC1): an hour's worth
PHOTO_FIRST = "Ladda upp ett foto av intyget först."
ONE_PAGE = "Ladda upp ett intyg i taget. PDF:en har fler än en sida."
PAPER_IN_QUEUE = "Intyg på papper läggs in i kön."
NO_RIGHT_TO_ADD = "Du har inte rätt att lägga till kaniner i besättningen."


@arsrapport_bp.errorhandler(413)
def too_large(_exc):
    """A photo over MAX_FILE_REQUEST (werkzeug's 413 is HTML) as problem+json, as the queue's upload."""
    return problem(413, "Payload Too Large", "Filen är för stor. Max 25 MB.")


def _photo_key(access):
    """Who a photo is the session's for (FC1): the actor (a code or an account) and the environment (FA2)."""
    return [*actor_key(_actor(access)), _environment()]


def _session_photos(access):
    """The items of the photos this session's actor uploaded here (FC1): the only ones a request may bind."""
    key = _photo_key(access)
    return {entry[0] for entry in session.get("rapport_foton") or [] if entry[1:] == key}


def _photo_limit(access):
    """
    The 429 once the actor has sent PHOTO_LIMIT this hour, else None. Counted after the access check, so nobody
    spends a herd's photos without its code, and fail-open like the login's bucket when the limiter is off.
    """
    if not (limiter.enabled and limiter.initialized):
        return None
    key = "/".join(map(str, actor_key(_actor(access))))
    try:
        if limiter.limiter.hit(PHOTO_LIMIT, "arsrapport-foto", key):
            return None
        reset = limiter.limiter.get_window_stats(PHOTO_LIMIT, "arsrapport-foto", key).reset_time
    except Exception:  # pylint: disable=broad-except  # as the limiter's swallow_errors
        current_app.logger.exception("Photo rate limit check failed, letting the request through")
        return None
    at = datetime.fromtimestamp(math.ceil(reset / 60) * 60, arsrapport.STOCKHOLM)  # "efter" a whole minute
    return problem(429, "För många foton", PHOTO_LIMITED.format(at=f"{at:%H.%M}"), type="rate-limit-exceeded")


def _send_key(access):
    return "/".join(map(str, actor_key(_actor(access))))


def _send_limit(access):
    """The 429 once the actor has made SEND_LIMIT successful sends this hour, else None; fail-open as _photo_limit."""
    if not (limiter.enabled and limiter.initialized):
        return None
    key = _send_key(access)
    try:
        if limiter.limiter.test(SEND_LIMIT, "arsrapport-inskick", key):
            return None
        reset = limiter.limiter.get_window_stats(SEND_LIMIT, "arsrapport-inskick", key).reset_time
    except Exception:  # pylint: disable=broad-except  # as the limiter's swallow_errors
        current_app.logger.exception("Send rate limit check failed, letting the request through")
        return None
    at = datetime.fromtimestamp(math.ceil(reset / 60) * 60, arsrapport.STOCKHOLM)
    return problem(429, "För många inskick", SEND_LIMITED.format(at=f"{at:%H.%M}"), type="rate-limit-exceeded")


# [Next.js] The certificate's photo: the queue's checks, a `kontroll` item with an `intyg` document (G5).
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/foto", methods=["POST"])
@report_actor_required
def upload_photo(herd, year):
    if not report_link_only() and (refusal := certificate_upload_refusal()) is not None:
        return refusal
    request.max_content_length = MAX_FILE_REQUEST  # before the body is read: one photo, as the queue's upload
    herd, round_, access = _report_target(herd, year)
    if access.item is not None:
        raise ArsrapportError(403, PAPER_IN_QUEUE)
    arsrapport.require_round_open(herd, round_, access)
    if not may_register_in(_actor(access), herd)(herd):  # the right to the rabbit the photo is for (Opus L4)
        raise ArsrapportError(403, NO_RIGHT_TO_ADD)
    if (limited := _photo_limit(access)) is not None:
        return limited
    file = request.files.get("file")
    if file is None or not file.filename:
        raise ArsrapportError(400, "Ingen fil bifogad.")
    # held for a purchase notice, never read by the model, or for sending a bought rabbit's photos, read once sent (S7);
    # else for "Lägg till kanin": read and the queue's once Spara registers the rabbit, purged a day later if not
    held = request.args.get("syfte") if request.args.get("syfte") in inbox.PURPOSES else inbox.HELD_RABBIT
    encoded, stored = [], []

    def keep(image):
        encoded.append((inbox.jpeg_bytes(image), inbox.measure(image)))

    try:
        # shortcut: one certificate per photo, a PDF of one page; several pages wait for a flow of several documents
        _each_image(file, 1, keep, lambda: problem(400, "Ogiltig begäran", ONE_PAGE))  # refused before page 2
        for data, quality in encoded:
            stored.append((*inbox.write_jpeg(data, "original"), quality))
        # a link has no account: the item names its code, as an account would be named
        sender, named = (None, {"access_code_id": access.code.id}) if access.code else (_actor(access), {})
        with DATABASE.atomic():
            # the round row under its lock: a round closed while the photo was read is seen here
            arsrapport.require_round_open(herd, arsrapport._lock_round(round_), access)  # pylint: disable=protected-access
            item, documents = inbox.create_upload(
                sender,
                herd,
                None,
                stored,
                kind="kontroll",
                ref_type="individual",
                held=held,
                # the person, so an erasure finds a held photo at once
                member=access.code.member_id if access.code else resolve_own_membership(sender),
                **named,
            )
    except _Refused as refused:
        inbox.remove_files(path for path, _, _ in stored)
        return refused.response
    except BaseException:
        inbox.remove_files(path for path, _, _ in stored)
        raise
    # A new list, not an append: the session saves on assignment (as open_link's)
    session["rapport_foton"] = ((session.get("rapport_foton") or []) + [[item.id, *_photo_key(access)]])[-PHOTOS_KEPT:]
    return jsonify({"item_id": item.id, "document_id": documents[0].id}), 201


# [Next.js] The rabbit from its paper certificate, bound to the session's own photo (FC1); it stays if the report is
# withdrawn (spec 5.8).
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/kanin", methods=["POST"])
@report_actor_required
def add_rabbit(herd, year):
    herd, round_, access = _report_target(herd, year)
    if access.item is not None:
        raise ArsrapportError(403, PAPER_IN_QUEUE)
    body = _submission_body()
    if not isinstance(body, dict):
        raise ArsrapportError(400, "Skicka kaninen som JSON.")
    item_id = body.get("item_id")
    if type(item_id) is not int:  # True is an int too
        raise ArsrapportError(400, PHOTO_FIRST, field="photo")
    if item_id not in _session_photos(access):
        raise ArsrapportError(403, arsrapport.PHOTO_NOT_OURS, field="photo")
    actor = _actor(access)
    form = {key: body[key] for key in REGISTRATION_FIELDS if key in body}
    form["certificate_type"] = "paper"  # from the paper certificate only, a link above all (FC1)
    created = []

    def write(_grant):
        try:
            item = inbox.lock_item(item_id)  # after the report's lock and the code's recheck, as a sale proposal's
        except inbox.InboxError as exc:  # a held photo left a day is purged (purge_held)
            raise ArsrapportError(409, arsrapport.PHOTO_GONE, field="photo") from exc
        document = arsrapport.report_photo_document(item, herd)

        def bind(individual):  # in the registration's transaction: the photo, the rabbit and its receipt together
            inbox.bind_report_photo(item, document, None if access.code else actor, individual)
            arsrapport.mail_added(herd, access, current_user, "individual", individual.id)
            created.append(individual)

        return register_individual_as(actor, herd, form, bind)

    response = arsrapport._litter_write(herd, round_, access, actor, write)  # pylint: disable=protected-access
    if not created:
        return response  # the registration's refusal; nothing was written
    individual = created[0]
    listed = any(row["id"] == individual.id for row in arsrapport.report_list(herd, round_.report_year))
    return jsonify({"id": individual.id, "number": individual.number, "item_id": item_id, "listed": listed}), 201


# [Next.js] What the form needs on opening: the genebank's colours (/api/colors needs a login) and who the actor is,
# a code or an account, which a draft saved in the browser is kept under.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/kanin-formular", methods=["GET"])
@report_actor_required
def rabbit_form(herd, year):
    herd, _, access = _report_target(herd, year)
    actor = "-".join(map(str, actor_key(_actor(access))))
    return jsonify({"farger": arsrapport.genebank_colors(herd), "aktor": actor})


# [Next.js] The form's parent lookup by number, for a code session too (L10): 404 only when there is no such rabbit.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/kanin-sok", methods=["GET"])
@report_actor_required
def find_rabbit(herd, year):
    herd, _, _ = _report_target(herd, year)
    found = arsrapport.report_parent(herd, (request.args.get("nummer") or "").strip().upper())
    if found is None:
        raise ArsrapportError(404, "Kaninen finns inte i Stamboken.", code="saknas")  # not a 404 for the herd
    return jsonify(found)


# [Next.js] The number a certificate of a litter would get (suggest-number), for a code session too (FC1).
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/nummerforslag", methods=["GET"])
@report_actor_required
def number_proposal(herd, year):
    herd, _, access = _report_target(herd, year)
    return number_suggestion(request.args, may_register_in(_actor(access), herd), herd.genebank_id)


# [Next.js] The paper's number against Stamboken's before a save (number-check), for a code session too (FC1).
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/nummerkontroll", methods=["POST"])
@report_actor_required
def number_control(herd, year):
    herd, _, access = _report_target(herd, year)
    body = _submission_body()
    if not isinstance(body, dict):
        raise ArsrapportError(400, "Skicka numret som JSON.")
    actor = _actor(access)
    # no lookup by certificate number for the report (it reaches every genebank): registration answers instead
    body = {key: value for key, value in body.items() if key != "paper_certificate"}
    return paper_number_check(body, actor, may_register_in(actor, herd), herd.genebank_id)


# [Next.js] The status view's sale dialog: the herd's pending sale proposals; the genebank's manager or admin.
@arsrapport_bp.route("/v2/arsrapport/besattning/<herd>/<int:year>/forslag", methods=["GET"])
@json_login_required
def sale_proposals(herd, year):
    target = Herd.get_or_none(Herd.herd == herd)
    if target is None or target.herd in OUTSIDE_GENEBANK_HERDS:
        raise ArsrapportError(404, "Besättningen finns inte.")
    denied = check_genebank_access(target.genebank_id)
    if denied:
        return denied
    round_ = arsrapport.get_round(year)
    report = arsrapport.current_report(target, round_) if round_ else None
    return jsonify({"forslag": sale_proposal.decisions(report) if report else []})


def _deciding(proposal_id):
    """The proposal and None, or None and the 403 for anyone but its genebank's manager or admin (section 6)."""
    proposal = SaleProposal.get_or_none(SaleProposal.id == proposal_id)
    if proposal is None:
        raise ArsrapportError(404, "Försäljningen finns inte.")
    return proposal, check_genebank_access(proposal.report.herd.genebank_id)


# [Next.js] Godkänn: the proposed sale is registered (5.9).
@arsrapport_bp.route("/v2/arsrapport/forslag/<int:proposal_id>/godkann", methods=["POST"])
@json_login_required
def approve_sale(proposal_id):
    proposal, denied = _deciding(proposal_id)
    if denied:
        return denied
    sale_proposal.approve(proposal, current_user, now=arsrapport.now())
    return jsonify({"id": proposal.id, "state": "godkand"})


# [Next.js] Avvisa: body {reason, then: "kvar" | "valj_igen"}; the member is mailed the reason (F4).
@arsrapport_bp.route("/v2/arsrapport/forslag/<int:proposal_id>/avvisa", methods=["POST"])
@json_login_required
def reject_sale(proposal_id):
    proposal, denied = _deciding(proposal_id)
    if denied:
        return denied
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ArsrapportError(400, "Skicka orsak och val som JSON.")
    sale_proposal.reject(proposal, current_user, reason=body.get("reason"), then=body.get("then"), now=arsrapport.now())
    return jsonify({"id": proposal.id, "state": "avvisad"})


# [API] A pending sale's buyer erased on request or objection (ADR-0016), by proposal: a buyer only a proposal names
# has no BuyerContact yet, so DELETE /v2/buyer-contacts cannot reach it. The sale can then only be rejected.
@arsrapport_bp.route("/v2/arsrapport/forslag/<int:proposal_id>/kopare", methods=["DELETE"])
@json_login_required
def erase_sale_buyer(proposal_id):
    proposal, denied = _deciding(proposal_id)
    if denied:
        return denied
    sale_proposal.clear_buyer(proposal, "radering", current_user)
    return "", 204
