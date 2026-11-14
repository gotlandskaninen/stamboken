"""Link tokens must never reach a log line."""

import importlib.util
import logging
import os
import unittest

from utils.log_masking import _TOKEN, TokenMaskFilter, mask_tokens

TOKEN = "4711." + "a" * 22  # shaped like utils.mail.link_token; built, so no scanner takes it for a secret


class TestLogMasking(unittest.TestCase):
    def test_token_in_url_is_masked_and_the_row_id_kept(self):
        self.assertEqual(
            mask_tokens(f"https://example.org/rapport/{TOKEN}?x=1"), "https://example.org/rapport/4711.***?x=1"
        )

    def test_ordinary_text_is_untouched(self):
        for text in ("GET /api/v2/individual/G9001-2512 200", "version 2.8.0", "12.5 kg", None, ""):
            self.assertEqual(mask_tokens(text), text)

    def test_filter_masks_tokens_passed_as_arguments(self):
        record = logging.LogRecord(
            "gunicorn.access", logging.INFO, "", 0, "%(r)s", ({"r": f"GET /x/{TOKEN} HTTP/1.1"},), None
        )
        TokenMaskFilter().filter(record)
        self.assertEqual(record.getMessage(), "GET /x/4711.*** HTTP/1.1")

    def test_gunicorn_config_repeats_the_same_pattern(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gunicorn.conf.py")
        spec = importlib.util.spec_from_file_location("gunicorn_conf", path)
        conf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(conf)
        self.assertEqual(conf._LINK_TOKEN.pattern, _TOKEN.pattern)  # pylint: disable=protected-access
