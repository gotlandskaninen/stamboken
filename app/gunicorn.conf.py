"""Gunicorn configuration for herdbook API."""

import os

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


def on_starting(server):
    """Clean up stale scheduler lock from previous runs."""
    try:
        os.unlink(SCHEDULER_LOCK)
    except FileNotFoundError:
        pass
