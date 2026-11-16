"""Link tokens must never reach a log line."""

import importlib.util
import logging
import os
import subprocess
import sys
import textwrap
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

    def test_filter_masks_exception_text(self):
        try:
            raise ValueError(f"bad link /x/{TOKEN}")
        except ValueError:
            record = logging.LogRecord("x", logging.ERROR, "", 0, "failed", None, sys.exc_info())
        TokenMaskFilter().filter(record)
        text = logging.Formatter().format(record)
        self.assertIn("bad link /x/4711.***", text)
        self.assertNotIn(TOKEN, text)

    def test_filter_does_not_raise_on_mismatched_arguments(self):
        record = logging.LogRecord("x", logging.INFO, "", 0, "two %s and %s", ("one",), None)
        self.assertTrue(TokenMaskFilter().filter(record))
        self.assertIn("two %s and %s", record.getMessage())

    def test_gunicorn_config_filters_the_error_log_too(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gunicorn.conf.py")
        spec = importlib.util.spec_from_file_location("gunicorn_conf", path)
        conf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(conf)
        names = ("gunicorn.access", "gunicorn.error")
        loggers = [logging.getLogger(n) for n in names]
        try:
            conf.on_starting(None)
            for logger in loggers:
                self.assertTrue(any(type(f).__name__ == "_TokenMaskFilter" for f in logger.filters), logger.name)
            try:
                raise ValueError(f"bad link /x/{TOKEN}")
            except ValueError:
                record = logging.LogRecord(
                    "gunicorn.error", logging.ERROR, "", 0, "GET /x/%s", (TOKEN,), sys.exc_info()
                )
            loggers[1].filter(record)
            text = logging.Formatter().format(record)
            self.assertIn("bad link /x/4711.***", text)  # the traceback, not only the message
            self.assertNotIn(TOKEN, text)
        finally:
            for logger in loggers:
                logger.filters.clear()

    def test_gunicorn_config_repeats_the_same_pattern(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gunicorn.conf.py")
        spec = importlib.util.spec_from_file_location("gunicorn_conf", path)
        conf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(conf)
        self.assertEqual(conf._LINK_TOKEN.pattern, _TOKEN.pattern)  # pylint: disable=protected-access

    def test_app_log_handlers_mask_exception_paths_and_mail_lines(self):
        """
        A fresh process, so the handler is the one the app runs with (under pytest the root logger holds
        pytest's): utils.app_logging's, on standard out, with the request path as a field of its own.
        """
        probe = textwrap.dedent(
            """
            import logging, sys
            import pytest  # no blocking startup
            from herdbook import APP

            token = "4711." + "a" * 22
            APP.config["PROPAGATE_EXCEPTIONS"] = False  # log the exception as in production, not re-raise it
            rule = next(r for r in APP.url_map.iter_rules() if r.rule == "/api/v2/certificates/<i_number>")

            def boom(**kwargs):
                raise RuntimeError("boom")

            APP.view_functions[rule.endpoint] = boom
            print("status", APP.test_client().get(f"/api/v2/certificates/{token}").status_code, file=sys.stderr)
            logging.getLogger("herdbook.mail").info("Mail 1: https://example.org/rapport/%s", token)
            """
        )
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        p = subprocess.run(
            [sys.executable, "-c", probe], cwd=app_dir, env=os.environ, capture_output=True, text=True, timeout=120
        )
        self.assertIn("status 500", p.stderr)
        self.assertIn("Exception on /api/v2/certificates/4711.***", p.stdout)
        self.assertIn("path=/api/v2/certificates/4711.***", p.stdout)
        self.assertIn("Mail 1: https://example.org/rapport/4711.***", p.stdout)
        self.assertNotIn(TOKEN, p.stdout + p.stderr)
