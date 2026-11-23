"""
"Tyck till" (docs/tyck-till.md): the text of the issue and the mail. Everything the browser sends is untrusted, and
nothing but what is built here goes into an issue, which is public or stays in the project's history.
"""

import hashlib
import hmac
import os
import re
import shutil
import uuid
from pathlib import Path

import utils.settings as settings
from utils.database import MailMessage
from utils.log_masking import mask_tokens

REPOS = {"publik": "gotlandskaninen/stamboken", "privat": "gotlandskaninen/stamboken-drift"}
UNKNOWN_PAGE = "okänd sida"
UNKNOWN_VERSION = "okänd"
_MAX_PATH = 200
_TITLE_LENGTH = 70
_PRIVATE_TITLES = {"fel": "Tyck till: något fungerar inte", "onskemal": "Tyck till: önskemål"}
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_GENERIC_SEGMENT = re.compile(r"[a-z-]+")
_VERSION = re.compile(r"[0-9A-Za-z.+-]{1,40}")


def root():
    return Path(settings.service.private_upload_folder) / "tyck-till"


def folder(inskick_id):
    """The submission's files: inskick.json, the images, svar.json. `inskick_id` is a uuid.UUID, so no path escapes."""
    return root() / str(inskick_id)


def reference(inskick_id):
    """`tt-` and eight hex digits of an HMAC of the submission's id: the same at every attempt, nothing else to keep."""
    secret = os.environ.get("SECRET_KEY") or "dev-secret-do-not-use-in-prod"  # as herdbook._resolve_secret_key
    mac = hmac.new(secret.encode(), f"tyck-till:{inskick_id}".encode(), hashlib.sha256)
    return f"tt-{mac.hexdigest()[:8]}"


def _is_path(path):
    return isinstance(path, str) and path.startswith("/") and len(path) <= _MAX_PATH


def generic_path(path):
    """The page's form for an issue: every segment that is not only lower case letters and hyphens becomes [id]."""
    if not _is_path(path):
        return UNKNOWN_PAGE
    segments = [s for s in path.split("/") if s]
    return "/" + "/".join(s if _GENERIC_SEGMENT.fullmatch(s) else "[id]" for s in segments)


def mask_codes(text):
    """Link codes and every UUID (a verification page's is enough to open a certificate) out of a text."""
    return mask_tokens(_UUID.sub("[uuid]", text or ""))


def mail_path(path):
    """The page's path for the mail: as it was, without codes and UUIDs, and on one line."""
    return mask_codes(" ".join(path.split())) if _is_path(path) else UNKNOWN_PAGE


def clean_version(value):
    return value if isinstance(value, str) and _VERSION.fullmatch(value) else UNKNOWN_VERSION


def issue_title(kind, visibility, text):
    if visibility == "privat":
        return _PRIVATE_TITLES[kind]
    line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if len(line) > _TITLE_LENGTH:
        line = line[:_TITLE_LENGTH].rstrip() + "…"
    return f"Tyck till: {line}" if line else "Tyck till"


def issue_body(kind, visibility, text, path, version, device, images, ref):
    # The fence is one backtick longer than the longest run in the text, so the text cannot end it.
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    lines = [
        f"{fence}\n{text.strip()}\n{fence}",
        "",
        f"Sida: {generic_path(path)}",
        f"Version: {clean_version(version)}",
        f"Enhet: {device if device in ('mobil', 'dator') else UNKNOWN_VERSION}",
    ]
    if visibility == "privat" and images:
        lines.append(f"Bilder: {images}, skickas med mejl till föreningen")
    lines += ["", f"Referens: {ref}"]
    return "\n".join(lines)


def labels(kind):
    found = ["tyck till", "bug" if kind == "fel" else "enhancement"]
    return found + ["testmiljö"] if settings.service.demo_instance else found


KEEP_SECONDS = 30 * 24 * 3600  # a submission's files, after it went into the queue
ABANDONED_SECONDS = 24 * 3600  # a folder that never got a queue row: the request died


def purge(now):
    """
    Removes the submissions' folders (a uuid directly under tyck-till/, never a link): 30 days old, or a day old
    when the mail was never queued. A folder's age is its modification time, as the last file is written at the
    end of the submission. Returns the number of folders removed.
    """
    if not root().is_dir():
        return 0
    removed = 0
    for entry in root().iterdir():
        try:
            if entry.is_symlink() or not entry.is_dir() or str(uuid.UUID(entry.name)) != entry.name:
                continue
        except ValueError:
            continue
        queued = MailMessage.select().where(MailMessage.dedupe_key == f"tyck-till:{entry.name}").exists()
        if now.timestamp() - entry.stat().st_mtime > (KEEP_SECONDS if queued else ABANDONED_SECONDS):
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed
