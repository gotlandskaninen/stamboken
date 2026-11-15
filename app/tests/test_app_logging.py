"""Appens loggar: standard ut, utan frågesträng, inloggning under herdbook.auth, inga loggfiler."""

import datetime
import importlib.util
import io
import logging
import os
from types import SimpleNamespace
from unittest import mock

from gunicorn.config import Config
from herdbook import APP
from utils import app_logging

from tests.database_test import DatabaseTest

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestAppLogging(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        super().setUp()
        self.client = APP.test_client()
        self.out = io.StringIO()
        patcher = mock.patch.object(app_logging.HANDLER, "stream", self.out)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_failed_login_is_a_herdbook_auth_line_without_the_query_string(self):
        self.client.post("/api/login?code=HEMLIG", json={"username": "admin", "password": "wrong"})
        lines = self.out.getvalue().splitlines()
        auth = [line for line in lines if line.startswith("herdbook.auth ")]
        self.assertTrue(auth, lines)
        self.assertRegex(auth[0], r"ip=\S+")
        self.assertNotIn("ip=-", auth[0])
        self.assertIn("user id=", auth[0])  # admin exists: the line says which account
        self.assertIn("path=/api/login", auth[0])
        self.assertNotIn("HEMLIG", self.out.getvalue())

    def test_failed_login_does_not_log_the_username_tried(self):
        self.client.post("/api/login", json={"username": "HEMLIG", "password": "wrong"})
        self.assertNotIn("HEMLIG", self.out.getvalue())

    def test_no_log_files(self):
        file_handlers = [
            h
            for name in ["", *logging.root.manager.loggerDict]
            for h in getattr(logging.getLogger(name), "handlers", [])
            if isinstance(h, logging.FileHandler) and h.baseFilename != os.devnull
        ]
        self.assertEqual(file_handlers, [])

    def test_gunicorn_access_log_has_no_query_string(self):
        spec = importlib.util.spec_from_file_location("gunicorn_conf", os.path.join(_APP_DIR, "gunicorn.conf.py"))
        conf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(conf)
        cfg = Config()
        cfg.set("access_log_format", conf.access_log_format)
        req = SimpleNamespace(
            method="GET",
            uri="/api/health?code=HEMLIG",
            query="code=HEMLIG",
            version=(1, 1),
            headers=[],
        )
        environ = {
            "REMOTE_ADDR": "192.0.2.1",
            "REQUEST_METHOD": "GET",
            "RAW_URI": "/api/health?code=HEMLIG",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "PATH_INFO": "/api/health",
            "QUERY_STRING": "code=HEMLIG",
        }
        resp = SimpleNamespace(status="200 OK", status_code=200, sent=2, headers=[], response_length=2)
        environ["PATH_INFO"] = "/api/health\nherdbook.auth INFO forged"
        atoms = conf.QuotingLogger(cfg).atoms(resp, req, environ, datetime.timedelta(seconds=1))
        line = cfg.access_log_format % atoms
        self.assertIn("/api/health", line)
        self.assertNotIn("HEMLIG", line)
        self.assertNotIn("\n", line)

    def test_decoded_newline_in_path_cannot_forge_a_log_line(self):
        with APP.test_request_context("/a%0Aherdbook.auth%20INFO%20forged"):
            logging.getLogger("herdbook.test").info("hello")
        self.assertEqual(len(self.out.getvalue().splitlines()), 1)

    def test_log_lines_are_written_once(self):
        # Flask's own stderr handler on `herdbook` would repeat each line without ip/path.
        self.assertEqual(
            [h for h in logging.getLogger().handlers if type(h) is logging.StreamHandler], [app_logging.HANDLER]
        )
        self.assertEqual(logging.getLogger("herdbook").handlers, [])

    def test_newline_in_a_message_cannot_forge_a_log_line(self):
        logging.getLogger("herdbook.test").info("Unknown level: %s", "x\nherdbook.auth INFO Login ok")
        self.assertEqual(len(self.out.getvalue().splitlines()), 1)

    def test_gunicorn_config_uses_the_quoting_logger(self):
        spec = importlib.util.spec_from_file_location("gunicorn_conf2", os.path.join(_APP_DIR, "gunicorn.conf.py"))
        conf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(conf)
        self.assertIs(conf.logger_class, conf.QuotingLogger)
        self.assertEqual(conf.accesslog, "-")

    def test_denied_request_is_logged_with_the_user_id_only(self):
        self.client.post("/api/login", json={"username": "man", "password": "pass"})
        self.out.truncate(0)
        self.out.seek(0)
        resp = self.client.get("/api/v2/admin/users?code=HEMLIG")
        self.assertEqual(resp.status_code, 403)
        denied = [line for line in self.out.getvalue().splitlines() if line.startswith("herdbook.auth INFO Denied 403")]
        self.assertEqual(len(denied), 1, self.out.getvalue())
        self.assertNotIn("HEMLIG", self.out.getvalue())

    def test_invalid_google_token_text_is_not_logged(self):
        with mock.patch("google.oauth2.id_token.verify_oauth2_token", side_effect=ValueError("token HEMLIG-TOKEN")):
            resp = self.client.post("/api/auth/google", json={"credential": "x"})
        self.assertEqual(resp.status_code, 401, resp.get_data(as_text=True))
        self.assertIn("herdbook.auth ERROR Invalid Google token: ValueError", self.out.getvalue())
        self.assertNotIn("HEMLIG", self.out.getvalue())

    def test_failed_login_is_one_auth_line(self):
        self.client.post("/api/login", json={"username": "admin", "password": "wrong"})
        failed = [line for line in self.out.getvalue().splitlines() if "Login failed" in line]
        self.assertEqual(len(failed), 1, self.out.getvalue())
