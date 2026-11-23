"""Gunicorn configuration for herdbook API."""

import logging
import os
import re
from urllib.parse import quote

from gunicorn.glogging import Logger

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


class QuotingLogger(Logger):
    """%(U)s is the decoded path; quote it so a %0A cannot forge a log line."""

    def atoms(self, resp, req, environ, request_time):
        atoms = super().atoms(resp, req, environ, request_time)
        atoms["U"] = quote(atoms["U"] or "", encoding="latin-1")  # PATH_INFO is latin-1 text
        return atoms


logger_class = QuotingLogger
accesslog = "-"
# %(U)s is the path without the query string (%(r)s would include it).
access_log_format = '%(h)s %(t)s "%(m)s %(U)s" %(s)s %(B)s %(M)s'
errorlog = "-"

# Scheduler lock file — initialize_app() flocks it so only one worker starts the
# APScheduler background job; the lock dies with that worker.
SCHEDULER_LOCK = "/tmp/herdbook_scheduler.lock"


# Must match _TOKEN in utils/log_masking.py; repeated because this file is loaded before the app is importable.
_LINK_TOKEN = re.compile(r"((?<![A-Za-z0-9_-])\d{1,19}\.|/auth/kod#)[A-Za-z0-9_-]{22}(?![A-Za-z0-9_-])")


class _TokenMaskFilter(logging.Filter):
    """Keeps link tokens in the request line out of the access log, and out of the error log's tracebacks."""

    def filter(self, record):
        record.msg, record.args = _LINK_TOKEN.sub(r"\1***", record.getMessage()), None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = _LINK_TOKEN.sub(r"\1***", record.exc_text)
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
