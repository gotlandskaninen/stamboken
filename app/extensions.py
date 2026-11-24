# app/extensions.py — Flask extension singletons (ADR-0007: blueprints must
# not import herdbook.py; they import shared extensions from here instead).
import os

import redis
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from utils.redis_retry import reconnect_on_drop

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["1000 per hour", "100 per minute"],
    storage_uri=os.getenv("RATELIMIT_STORAGE_URL", "memory://"),
    swallow_errors=True,
    enabled=os.environ.get("RATELIMIT_ENABLED", "true").lower() != "false",
)

# The session store (Flask-Session), and each account's mark beside the sessions (data_access.login_generation).
# Timeouts so a hung (not down) Redis fails requests instead of deadlocking every gunicorn worker: session I/O is on
# every request.
session_redis = redis.Redis.from_url(
    os.getenv("SESSION_REDIS_URL", "redis://redis:6379/2"),
    socket_connect_timeout=2,
    socket_timeout=2,
    health_check_interval=30,
    **reconnect_on_drop(),
)
