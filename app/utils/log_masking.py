"""
Keeps link tokens (utils.mail.link_token) out of the logs: a token in a URL is a credential, and both the
request log and gunicorn's access log write the URL.
"""

import logging
import re

# `<row id>.<22 base64url characters>`: the row id is no secret, the mac is.
_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])(\d{1,19})\.[A-Za-z0-9_-]{22}(?![A-Za-z0-9_-])")


def _tolerant(text):
    """`text` as a case-insensitive pattern that also takes each character percent-encoded (%72 for r, %2F for /)."""
    return "".join(f"(?:{re.escape(char)}|%{ord(char):02x})" for char in text)


# R6: everything after the link's path prefixes goes, whatever shape it has (truncated, wrong, percent-encoded, an
# encoded ? or a new line inside the tail). The match is found in the text as written and masked there: decoded
# text is never returned, so an encoded new line cannot forge a log line. `/api/v2/rapport/mina` and the other API
# routes are no links and stay readable.
_PREFIX = re.compile(
    rf"(?i)((?<!/v2){_tolerant('/rapport/')}|{_tolerant('/api')}(?:-test)?{_tolerant('/v2/rapport/oppna/')})"
    r"(?:[^\s?\"']|%3f)*"
)


def mask_tokens(text):
    if not text:
        return text
    return _TOKEN.sub(r"\1.***", _PREFIX.sub(r"\1***", text))


class TokenMaskFilter(logging.Filter):
    """Masks tokens in the finished message and in the exception text, so arguments and tracebacks are covered."""

    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:  # pylint: disable=broad-except  # mismatched arguments must not raise out of a log call
            message = f"{record.msg} {record.args}"
        record.msg, record.args = mask_tokens(message), None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        record.exc_text = mask_tokens(record.exc_text)
        return True
