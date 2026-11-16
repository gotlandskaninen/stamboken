"""Gunicorn configuration for herdbook API."""

import logging
import os
import re

# Server socket
bind = "0.0.0.0:9090"

# Worker processes
workers = int(os.getenv("GUNICORN_WORKERS", "4"))
threads = int(os.getenv("GUNICORN_THREADS", "2"))
timeout = 120
# Keep idle connections open longer so Node.js undici (Next.js server-side
# fetch) can reuse them for parallel RSC data fetches without hitting
# UND_ERR_SOCKET "other side closed" on the default 2s keepalive.
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "75"))

# Logging
accesslog = "-"
errorlog = "-"

# Scheduler lock file — initialize_app() flocks it so only one worker starts the
# APScheduler background job; the lock dies with that worker.
SCHEDULER_LOCK = "/tmp/herdbook_scheduler.lock"


# Must match _TOKEN, _PREFIX and mask_tokens in utils/log_masking.py; repeated because this file is loaded before
# the app is importable.
_LINK_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])(\d{1,19})\.[A-Za-z0-9_-]{22}(?![A-Za-z0-9_-])")


def _tolerant(text):
    return "".join(f"(?:{re.escape(char)}|%{ord(char):02x})" for char in text)


_LINK_PREFIX = re.compile(
    rf"(?i)((?<!/v2){_tolerant('/rapport/')}|{_tolerant('/api')}(?:-test)?{_tolerant('/v2/rapport/oppna/')})"
    r"(?:[^\s?\"']|%3f)*"
)


def _mask(text):
    return _LINK_TOKEN.sub(r"\1.***", _LINK_PREFIX.sub(r"\1***", text))


class _TokenMaskFilter(logging.Filter):
    """Keeps link tokens in the request line out of the access log."""

    def filter(self, record):
        record.msg, record.args = _mask(record.getMessage()), None
        return True


def on_starting(server):
    """Clean up stale scheduler lock from previous runs."""
    # Before the workers fork, so every worker's access log is masked.
    for name in ("gunicorn.access", "gunicorn.error"):
        logging.getLogger(name).addFilter(_TokenMaskFilter())
    try:
        os.unlink(SCHEDULER_LOCK)
    except FileNotFoundError:
        pass
