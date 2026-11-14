"""
Keeps link tokens (utils.mail.link_token) out of the logs: a token in a URL is a credential, and both the
request log and gunicorn's access log write the URL.
"""

import logging
import re

# `<row id>.<22 base64url characters>`: the row id is no secret, the mac is.
_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])(\d{1,19})\.[A-Za-z0-9_-]{22}(?![A-Za-z0-9_-])")


def mask_tokens(text):
    return _TOKEN.sub(r"\1.***", text) if text else text


class TokenMaskFilter(logging.Filter):
    """Masks tokens in the finished message, so arguments (gunicorn's request line) are covered too."""

    def filter(self, record):
        record.msg, record.args = mask_tokens(record.getMessage()), None
        return True
