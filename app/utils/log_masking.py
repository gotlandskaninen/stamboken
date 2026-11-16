"""
Keeps link tokens (utils.mail.link_token) out of the logs: a token in a URL is a credential, and both the
request log and gunicorn's access log write the URL.
"""

import logging
import re
from urllib.parse import unquote

# `<row id>.<22 base64url characters>`: the row id is no secret, the mac is.
_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])(\d{1,19})\.[A-Za-z0-9_-]{22}(?![A-Za-z0-9_-])")


# R6: everything after the link's path prefixes goes, whatever shape it has (truncated, wrong, percent-encoded).
# `/api/v2/rapport/mina` and the other API routes are no links and stay readable.
_PREFIX = re.compile(r"(?i)((?<!/v2)/rapport/|/api/v2/rapport/oppna/)[^\s?\"']*")


def mask_tokens(text):
    if not text:
        return text
    decoded = text
    for _ in range(3):  # %72apport and %2572apport are the same path to nginx and to Flask
        decoded, previous = unquote(decoded), decoded
        if decoded == previous:
            break
    if _PREFIX.search(decoded):
        text = _PREFIX.sub(r"\1***", decoded)
    return _TOKEN.sub(r"\1.***", text)


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
