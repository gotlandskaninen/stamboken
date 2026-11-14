"""
Mail queue status (mejlkön): per-case status, the admin list with the sender's alarms, retry and cancel.

Admin sees every row; a genebank manager only rows of the genebanks they manage. Rows without a genebank
(for example the membership application mails) are admin-only. A recipient is shown as a name, looked up
now, never as an address.
"""

from datetime import date, datetime, time, timedelta, timezone

import utils.mail as mail
from extensions import limiter
from flask import Blueprint, jsonify, request
from flask_login import current_user
from utils.database import MailMessage

from blueprints.common import json_login_required, manager_required, problem

mail_bp = Blueprint("mail", __name__, url_prefix="/api/v2/mail")


def _visible():
    """The rows the current user may see."""
    if current_user.is_admin:
        return MailMessage.select()
    return MailMessage.select().where(MailMessage.genebank.in_(current_user.is_manager or []))


def _int_arg(name):
    value = request.args.get(name)
    return int(value) if value is not None and value.isdigit() else None


@mail_bp.route("/status", methods=["GET"])
@json_login_required
@manager_required
def mail_status():
    """The latest row per kind for one case (ref_type, ref_id)."""
    ref_type, ref_id = request.args.get("ref_type"), _int_arg("ref_id")
    if not ref_type or ref_id is None:
        return problem(400, "Ogiltigt anrop", "ref_type och ref_id (heltal) krävs.")
    rows = _visible().where((MailMessage.ref_type == ref_type) & (MailMessage.ref_id == ref_id))
    latest = {}
    for row in rows.order_by(MailMessage.id.desc()):
        latest.setdefault(row.kind, row)
    return jsonify({"items": [mail.message_view(row) for row in latest.values()]})


def _day(name):
    try:
        return date.fromisoformat(request.args[name]) if request.args.get(name) else None
    except ValueError:
        return False


@mail_bp.route("/messages", methods=["GET"])
@json_login_required
@manager_required
def list_messages():
    """The queue, newest first, filtered on status, kind, genebank, herd and creation date, with the alarms."""
    rows = _visible()
    for arg, field in (("status", MailMessage.status), ("kind", MailMessage.kind)):
        if request.args.get(arg):
            rows = rows.where(field == request.args[arg])
    for arg, field in (("genebank_id", MailMessage.genebank), ("herd_id", MailMessage.herd)):
        if _int_arg(arg) is not None:
            rows = rows.where(field == _int_arg(arg))
    since, until = _day("from"), _day("to")
    if since is False or until is False:
        return problem(400, "Ogiltigt datum", "from och to anges som ÅÅÅÅ-MM-DD.")
    if since:
        rows = rows.where(MailMessage.created_at >= datetime.combine(since, time(), timezone.utc))
    if until:
        rows = rows.where(MailMessage.created_at < datetime.combine(until + timedelta(days=1), time(), timezone.utc))
    limit = min(_int_arg("limit") or 100, 500)
    offset = _int_arg("offset") or 0
    page = rows.order_by(MailMessage.id.desc()).limit(limit).offset(offset)
    return jsonify({**mail.sender_alarms(), "items": [mail.message_view(row) for row in page]})


def _transition(message_id, from_statuses, fields, refused):
    """Moves a visible row on, only from `from_statuses`; a concurrent change gets 409, never a lost update."""
    if not _visible().where(MailMessage.id == message_id).exists():
        return problem(404, "Hittades inte", f"Utskick {message_id} finns inte.")
    changed = (
        MailMessage.update(**fields)
        .where((MailMessage.id == message_id) & MailMessage.status.in_(from_statuses))
        .execute()
    )
    if not changed:
        return problem(409, "Fel status", refused)
    return jsonify(mail.message_view(MailMessage.get_by_id(message_id)))


@mail_bp.route("/messages/<int:message_id>/retry", methods=["POST"])
@json_login_required
@manager_required
@limiter.limit("30 per minute", key_func=lambda: str(current_user.id))
def retry_message(message_id):
    """ "Försök igen": failed or bounced back to the queue, with a fresh retry ladder."""
    fields = {"status": "queued", "attempts": 0, "next_attempt_at": datetime.now(timezone.utc)}
    return _transition(
        message_id, ("failed", "bounced"), fields, "Bara misslyckade eller studsade utskick kan skickas igen."
    )


@mail_bp.route("/messages/<int:message_id>/cancel", methods=["POST"])
@json_login_required
@manager_required
@limiter.limit("30 per minute", key_func=lambda: str(current_user.id))
def cancel_message(message_id):
    """ "Stoppa": a queued mail is never sent."""
    fields = {"status": "cancelled", "last_error": "stoppat i statusvyn"}
    return _transition(message_id, ("queued",), fields, "Bara köade utskick kan stoppas.")
