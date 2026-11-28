"""
"Tyck till": a member's or a visitor's feedback becomes a GitHub issue and a mail to the association.
docs/tyck-till.md is the flow; utils/tyck_till.py has the text, utils/github_app.py the GitHub calls (ADR-0007).
"""

import fcntl
import json
import logging
import os
import shutil
import threading
import time
import uuid

import utils.github_app as github
import utils.inbox as inbox
import utils.tyck_till as tt
from extensions import limiter
from flask import Blueprint, request
from flask_login import current_user
from limits import parse as parse_limit
from utils.database import DB_PROXY, MailMessage
from utils.mail import enqueue_mail

from .common import EMAIL_RE, problem
from .inbox import _each_image, _kind, _Refused

logger = logging.getLogger(__name__)

tyck_till_bp = Blueprint("tyck_till", __name__, url_prefix="/api/v2")

MAX_REQUEST = 9 * 1024 * 1024  # a public form whose body is read before its IP limit; nginx takes 10 MB on its pages
IMAGE_SIDE = 2000  # pixels, as shrink() in the dialog (pointing.ts); bounds the size of the mail
MAX_TEXT = 5000
MAX_POINTED = 200
MAX_IMAGES = 4
GITHUB_SECONDS = 10
IMAGE_KINDS = ("jpeg", "png", "webp", "heic")
LOGGED_IN_LIMIT = "5 per hour"
LOGGED_OUT_LIMIT = "3 per hour"
ALL_LOGGED_OUT_LIMIT = "30 per hour"
REACHED_LIMIT = "20 per hour"  # every call that gets past the lock, so rejected images cannot be decoded without end
_ONE_AT_A_TIME = threading.BoundedSemaphore(1)  # per gunicorn process: the others keep their threads for the rest


@tyck_till_bp.errorhandler(413)
def too_large(_exc):
    return problem(413, "Payload Too Large", "Bilderna är för stora tillsammans. Ta bort en bild och försök igen.")


def _unavailable():
    return problem(
        503,
        "Service Unavailable",
        "Det gick inte att skicka just nu. Texten finns kvar, så du kan försöka igen om en stund.",
    )


def _invalid(detail, field):
    return problem(400, "Bad Request", detail, field=field)


def _hit(limit, *identifiers):
    return limiter.limiter.hit(parse_limit(limit), *identifiers, "tyck-till")


def _limits(user_id):
    """The (limit, identifier) pairs a successful submission is counted against."""
    if user_id:
        return [(LOGGED_IN_LIMIT, f"user:{user_id}")]
    return [(LOGGED_OUT_LIMIT, f"ip:{request.remote_addr}"), (ALL_LOGGED_OUT_LIMIT, "logged-out")]


def _under_limits(user_id):
    """True, or False when over; raises when the counter does not answer (the caller closes: 503)."""
    return all(limiter.limiter.test(parse_limit(limit), ident, "tyck-till") for limit, ident in _limits(user_id))


def _count(user_id):
    """Counts one finished submission. It is done, so a counter that fails now only costs the count."""
    try:
        for limit, ident in _limits(user_id):
            _hit(limit, ident)
    except Exception:  # pylint: disable=broad-except
        logger.exception("The Tyck till limit could not be counted")


def _too_many():
    return problem(
        429,
        "För många anrop",
        "Du har skickat för många synpunkter. Försök igen om en stund.",
        type="rate-limit-exceeded",
    )


def _answer(visibility, issue_url, images, reply_to):
    return {
        "issue_url": issue_url if visibility == "publik" else None,
        "visibility": visibility,
        "images": images,
        "reply_to": reply_to,
    }


def _saved_answer(folder, inskick_id):
    """The answer a finished or half-finished earlier attempt gave, or None when none got as far as the queue."""
    try:
        return json.loads((folder / "svar.json").read_text())
    except (FileNotFoundError, ValueError):
        pass
    row = MailMessage.get_or_none(MailMessage.dedupe_key == f"tyck-till:{inskick_id}")
    if row is None:
        return None
    visibility = "privat" if row.params["repo"] else "publik"
    try:
        data = json.loads((folder / "inskick.json").read_text())
    except (FileNotFoundError, ValueError):
        data = {"images": [], "reply_to": None}
    url = f"https://github.com/{tt.REPOS[visibility]}/issues/{row.params['issue']}"
    return _answer(visibility, url, len(data["images"]), data.get("reply_to"))


def _fields():
    """The checked fields of the form, or a _Refused."""
    form = request.form
    kind, text = form.get("typ"), (form.get("text") or "").strip()
    if kind not in ("fel", "onskemal"):
        raise _Refused(_invalid("Välj fel eller önskemål.", "typ"))
    if not text:
        raise _Refused(_invalid("Skriv vad du vill säga.", "text"))
    if len(text) > MAX_TEXT:
        raise _Refused(_invalid(f"Texten får vara högst {MAX_TEXT} tecken.", "text"))
    email = (form.get("email") or "").strip().lower()
    logged_in = current_user.is_authenticated
    if (email or not logged_in) and not (
        len(email) <= 254 and EMAIL_RE.match(email) and not set(email) & set("<>,;\"'")
    ):
        raise _Refused(_invalid("Skriv en giltig e-postadress.", "email"))
    # Logged out is always private, whatever is sent: the public repo takes only what a logged-in member chose.
    visibility = "publik" if logged_in and form.get("vem") == "publik" else "privat"
    contact = logged_in and not email and form.get("kontakt") == "1"
    return {
        "kind": kind,
        "visibility": visibility,
        "text": text,
        "path": (form.get("sida") or "")[:500],
        "pekat": (form.get("pekat") or "").strip()[:MAX_POINTED],
        "version": (form.get("version") or "")[:100],
        "device": form.get("enhet"),
        "email": email,
        "user_id": current_user.id if logged_in else None,
        "contact": contact,
    }


def _images():
    """The images as JPEG bytes, re-encoded so that EXIF with a position is gone; or a _Refused."""
    files = [f for f in request.files.getlist("bilder") if f and f.filename]
    if len(files) > MAX_IMAGES:
        raise _Refused(_invalid(f"Högst {MAX_IMAGES} bilder.", "bilder"))
    encoded = []
    for file in files:
        if _kind(file) not in IMAGE_KINDS:  # a PDF is never rendered here
            raise _Refused(problem(415, "Unsupported Media Type", "Otillåten filtyp. Bara JPEG, PNG, WebP och HEIC."))
    for file in files:
        _each_image(file, MAX_IMAGES - len(encoded), lambda image: encoded.append(inbox.jpeg_bytes(_fit(image))))
    return encoded


def _fit(image):
    """At most IMAGE_SIDE on the longest side, as the dialog's shrink(): the mail carries every image."""
    image.thumbnail((IMAGE_SIDE, IMAGE_SIDE))
    return image


@tyck_till_bp.route("/tyck-till", methods=["POST"])
def send():
    # Set before the body is read: a larger one never half reaches the rest.
    request.max_content_length = MAX_REQUEST
    try:
        inskick_id = uuid.UUID(request.form.get("inskick_id") or "")
    except ValueError:
        return _invalid("Ogiltigt inskicks-id.", "inskick_id")
    try:
        fields = _fields()
    except _Refused as refusal:
        return refusal.response
    folder = tt.folder(inskick_id)

    # Reserve. None of this spends the limit: a retry or a double click is not a new submission.
    saved = _saved_answer(folder, inskick_id)
    if saved:
        return saved, 202
    created = False
    try:
        try:
            tt.root().mkdir(parents=True, exist_ok=True)
            folder.mkdir()
            created = True
        except FileExistsError:
            pass
        lock = os.open(folder / "lock", os.O_CREAT | os.O_RDWR)
    except FileNotFoundError:  # the other attempt removed its folder just now
        return problem(409, "Conflict", "Skickas redan.")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock)
        return problem(409, "Conflict", "Skickas redan.")
    try:  # the folder may have been removed and made again while this one waited: then the lock is on a dead file
        same = os.fstat(lock).st_ino == os.stat(folder / "lock").st_ino
    except FileNotFoundError:
        same = False
    if not same:
        os.close(lock)
        return problem(409, "Conflict", "Skickas redan.")
    try:
        saved = _saved_answer(folder, inskick_id)  # finished while this one waited to open the lock
        if saved:
            return saved, 202
        return _submit(inskick_id, folder, fields, created)
    finally:
        os.close(lock)  # releases the lock


def _submit(inskick_id, folder, fields, created):
    def refuse(response):
        if created:  # an empty folder of this attempt's own; one left by an earlier attempt is kept
            shutil.rmtree(folder, ignore_errors=True)
        return response

    if not github.configured():
        return refuse(_unavailable())
    limited = limiter.enabled and limiter.initialized
    if limited:
        try:
            if not _hit(REACHED_LIMIT, f"reached:{request.remote_addr}"):
                return refuse(_too_many())
            if not _under_limits(fields["user_id"]):
                return refuse(_too_many())
        except Exception:  # pylint: disable=broad-except  # the limiter swallows errors and would let everything in
            logger.exception("The Tyck till limit could not be checked")
            return refuse(_unavailable())
    if request.form.get("webbplats"):  # the hidden field: only a bot fills it in, and gets the same answer
        if limited:
            _count(fields["user_id"])
        return refuse(_answer("privat", None, 0, None)), 202
    if not _ONE_AT_A_TIME.acquire(blocking=False):
        return refuse(_unavailable())
    try:
        response = _create(inskick_id, folder, fields)
        if limited:
            _count(fields["user_id"])
        return response
    except _Refused as refusal:
        shutil.rmtree(folder, ignore_errors=True)
        return refusal.response
    finally:
        _ONE_AT_A_TIME.release()


def _create(inskick_id, folder, fields):
    images = _images()
    for number, data in enumerate(images):
        (folder / f"bild-{number}.jpg").write_bytes(data)
    reply_to = fields["email"] or None
    if fields["contact"] and not reply_to:
        reply_to = (current_user.email or "").strip().lower() or None
    ref = tt.reference(inskick_id)
    saved = {**fields, "images": [f"bild-{n}.jpg" for n in range(len(images))], "reply_to": reply_to}
    (folder / "inskick.json").write_text(json.dumps(saved))
    deadline = time.monotonic() + GITHUB_SECONDS
    visibility = fields["visibility"]
    try:
        # An earlier attempt may have made the issue in the other repo: what exists wins over what this one chose.
        found = next(
            ((v, issue) for v in ("publik", "privat") if (issue := github.find_issue(tt.REPOS[v], ref, deadline))),
            None,
        )
        if found:
            visibility, issue = found
        else:
            issue = github.create_issue(
                tt.REPOS[visibility],
                tt.issue_title(fields["kind"], visibility, fields["text"]),
                tt.issue_body(
                    fields["kind"],
                    visibility,
                    fields["text"],
                    fields["path"],
                    fields["version"],
                    fields["device"],
                    len(images),
                    ref,
                    fields["pekat"],
                ),
                tt.labels(fields["kind"]),
                deadline,
            )
    except github.GitHubError:
        logger.warning("Tyck till: GitHub did not answer, the submission is refused")
        raise _Refused(_unavailable()) from None
    # A private issue is added to the board by the project's own workflow.
    on_board = github.add_to_project(issue.node_id, deadline) if visibility == "publik" else True
    params = {
        "inskick": inskick_id.int,
        "issue": issue.number,
        "repo": int(visibility == "privat"),
        "tavla": int(on_board),
    }
    with DB_PROXY.atomic():
        enqueue_mail("tyck_till.inskick", "tyck_till", 0, params, dedupe_key=f"tyck-till:{inskick_id}")
    answer = _answer(visibility, issue.url, len(images), reply_to)
    (folder / "svar.json").write_text(json.dumps(answer))
    return answer, 202
