"""Appens loggar: standard ut, utan frågesträng, inloggning under herdbook.auth, inga loggfiler."""

import datetime
import importlib.util
import io
import logging
import os
from types import SimpleNamespace
from unittest import mock

from gunicorn.config import Config
from gunicorn.glogging import Logger as GunicornLogger
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
        self.assertIn("ip=", auth[0])
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
        atoms = GunicornLogger(cfg).atoms(resp, req, environ, datetime.timedelta(seconds=1))
        line = cfg.access_log_format % atoms
        self.assertIn("/api/health", line)
        self.assertNotIn("HEMLIG", line)
