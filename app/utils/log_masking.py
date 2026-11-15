"""
Keeps link tokens (utils.mail.link_token) out of the logs: a token in a URL is a credential, and both the
app's log (utils.app_logging) and gunicorn's access log write the request path.
"""

import logging
import re

# `<row id>.<22 base64url characters>`: the row id is no secret, the mac is.
_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])(\d{1,19})\.[A-Za-z0-9_-]{22}(?![A-Za-z0-9_-])")


def mask_tokens(text):
    return _TOKEN.sub(r"\1.***", text) if text else text


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
        if hasattr(record, "path"):  # app_logging's request path, set by its filter before this one
            record.path = mask_tokens(record.path)
        return True
