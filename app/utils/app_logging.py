"""Appens loggar går till standard ut (journald via Docker), utan frågesträng."""

import logging
import sys
from urllib.parse import quote

from flask import has_request_context, request

FORMAT = "%(name)s %(levelname)s %(message)s ip=%(ip)s path=%(path)s"


class _RequestFilter(logging.Filter):
    def filter(self, record):
        # remote_addr är klientadressen efter ProxyFix; path saknar frågesträng.
        record.ip = request.remote_addr if has_request_context() else "-"
        # quoted: a decoded %0A in the path would otherwise forge a log line
        record.path = quote(request.path) if has_request_context() else "-"
        return True


HANDLER = logging.StreamHandler(sys.stdout)
HANDLER.setFormatter(logging.Formatter(FORMAT))
HANDLER.addFilter(_RequestFilter())


def setup():
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if HANDLER not in root.handlers:
        root.addHandler(HANDLER)
