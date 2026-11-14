"""
The intake queue's mail round trip (docs/inkorg.md): "Fråga uppfödaren", and the Gmail reader's status for
those working the queue. The rules live in utils/inbox_gmail.py (ADR-0007).
"""

import utils.inbox_gmail as inbox_gmail
from flask import Blueprint, jsonify
from flask_login import current_user

from .common import json_login_required
from .inbox import _body, _locked, _queue_worker, _then_item

inbox_gmail_bp = Blueprint("inbox_gmail", __name__, url_prefix="/api/v2")


# [Next.js] "Fråga uppfödaren": the handler mails a question to the herd's holder; the item waits for the answer.
@inbox_gmail_bp.route("/inkorg/<int:item_id>/fraga", methods=["POST"])
@json_login_required
@_queue_worker
def ask_breeder(item_id):
    body = _body()

    def ask(item):
        inbox_gmail.ask_breeder(item, current_user, body.get("text"), body.get("document"), body.get("crop"))

    return _locked(item_id, _then_item(ask))


# [Next.js] The alarm at the top of the queue: the Gmail reader's last run and error.
@inbox_gmail_bp.route("/inkorg/status", methods=["GET"])
@json_login_required
@_queue_worker
def status():
    return jsonify({"gmail": inbox_gmail.status()})
