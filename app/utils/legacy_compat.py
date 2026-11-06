"""
Compatibility helpers for the legacy React frontend (Phase 20).

The legacy app and the v2 (Next.js) app share one Flask backend, so a few
endpoints must answer differently depending on which frontend asked. The only
reliable discriminator is the request host: the legacy frontend is served from
its own vhosts, v2 from the main site.

Both the host list and the Classroom URL are environment-overridable so a
misjudged host can be corrected without a code change.
"""

import os

from flask import request

DEFAULT_LEGACY_HOSTS = "stamboken.gotlandskaninen.se,test.gotlandskaninen.se,stamboken.sb.gotlandskaninen.se"

# Old production redirected non-validated Google logins here.
DEFAULT_CLASSROOM_URL = "https://classroom.google.com/c/NjE3MDI1MzY2OTAz?cjc=27x3zpg"


def legacy_hosts():
    """The hosts served by the legacy frontend, from $LEGACY_HOSTS."""
    raw = os.getenv("LEGACY_HOSTS") or DEFAULT_LEGACY_HOSTS
    return {host.strip().lower() for host in raw.split(",") if host.strip()}


def legacy_classroom_url():
    """Where a non-validated legacy user is sent, from $LEGACY_CLASSROOM_URL."""
    return os.getenv("LEGACY_CLASSROOM_URL") or DEFAULT_CLASSROOM_URL


def is_legacy_host():
    """True when the current request arrived on a host served by the legacy frontend.

    Requires nginx to forward the original Host header (proxy_set_header Host $host).
    """
    host = (request.host or "").split(":")[0].strip().lower()
    return host in legacy_hosts()
