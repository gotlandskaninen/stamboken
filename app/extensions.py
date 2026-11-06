# app/extensions.py — Flask extension singletons (ADR-0007: blueprints must
# not import herdbook.py; they import shared extensions from here instead).
import os

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["1000 per hour", "100 per minute"],
    storage_uri=os.getenv("RATELIMIT_STORAGE_URL", "memory://"),
    swallow_errors=True,
    enabled=os.environ.get("RATELIMIT_ENABLED", "true").lower() != "false",
)
