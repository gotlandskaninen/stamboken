"""Gunicorn configuration for herdbook API."""

import os
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
        atoms["U"] = quote(atoms["U"] or "")
        return atoms


logger_class = QuotingLogger
accesslog = "-"
# %(U)s is the path without the query string (%(r)s would include it).
access_log_format = '%(h)s %(t)s "%(m)s %(U)s" %(s)s %(B)s %(M)s'
errorlog = "-"

# Scheduler lock file — used by initialize_app() to ensure only one worker
# starts the APScheduler background job.
SCHEDULER_LOCK = "/tmp/herdbook_scheduler.lock"


def on_starting(server):
    """Clean up stale scheduler lock from previous runs."""
    try:
        os.unlink(SCHEDULER_LOCK)
    except FileNotFoundError:
        pass
