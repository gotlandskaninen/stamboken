"""api and api-test share the session store: a session minted by the demo API is
marked, and production refuses it. Production sessions keep working on the demo."""

import os
import unittest
from unittest import mock

import redis
import utils.database as db
import utils.settings as settings
from herdbook import APP, limiter

from tests.database_test import DatabaseTest
from tests.google_login import redirect_login, token_login

limiter.enabled = False


def as_demo(on=True):
    return mock.patch.object(settings.service, "demo_instance", on)


class TestDemoSessions(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        super().setUp()
        self.session_redis = redis.Redis.from_url(
            os.getenv("SESSION_REDIS_URL", "redis://redis:6379/2"),
            socket_connect_timeout=2,
        )

    def tearDown(self):
        self.session_redis.delete("logout-epoch")
        super().tearDown()

    def login(self, client, username="spec"):
        return client.post("/api/login", json={"username": username, "password": "pass"})

    def demo_client(self):
        """A client holding a fresh session minted on the demo."""
        client = APP.test_client(use_cookies=True)
        with as_demo():
            self.assertEqual(self.login(client).status_code, 200)
        return client

    def test_demo_session_refused_by_production(self):
        # /api/user reads session["user_id"] directly; /api/active_users is @login_required.
        # Each gets its own session: the first refusal deletes the session it refused.
        for path in ("/api/user", "/api/active_users"):
            with self.subTest(path):
                client = self.demo_client()
                key = "session:" + client.get_cookie(APP.config["SESSION_COOKIE_NAME"]).value
                self.assertEqual(client.get(path).status_code, 401)
                self.assertFalse(self.session_redis.exists(key), "refused session left in the store")

    def test_relogin_on_demo_marks_a_production_session(self):
        client = APP.test_client(use_cookies=True)
        self.login(client)
        with as_demo():
            client.get("/api/logout")
            self.assertEqual(self.login(client).status_code, 200)
            self.assertEqual(client.get("/api/user").status_code, 200)
        self.assertEqual(client.get("/api/user").status_code, 401)

    def test_half_login_demo_session_refused_by_production(self):
        """A session with user_id but no _user_id never reaches load_user."""
        client = APP.test_client(use_cookies=True)
        with as_demo():
            self.login(client)
            with client.session_transaction() as sess:
                sess.pop("_user_id")
        self.assertEqual(client.get("/api/user").status_code, 401)

    def test_production_session_works_on_demo(self):
        client = APP.test_client(use_cookies=True)
        self.login(client)
        with as_demo():
            self.assertEqual(client.get("/api/user").status_code, 200)
            self.assertEqual(client.get("/api/active_users").status_code, 200)
        self.assertEqual(client.get("/api/user").status_code, 200)

    def test_demo_session_works_on_demo(self):
        client = APP.test_client(use_cookies=True)
        with as_demo():
            self.login(client)
            self.assertEqual(client.get("/api/user").status_code, 200)
            self.assertEqual(client.get("/api/active_users").status_code, 200)

    def test_every_demo_login_path_marks_the_session(self):
        db.User.update(validated=True).where(db.User.id == self.viewer.id).execute()

        def viewer(method, ident):
            return db.User.get_by_id(self.viewer.id)

        new_account = {"email": "ny@gotlandskaninen.se", "username": "ny"}
        logins = {
            "password": self.login,
            "google-token": lambda c: token_login(c, viewer),
            "google-redirect": lambda c: redirect_login(c, viewer),
            "google-autocreate": lambda c: redirect_login(
                c, lambda method, ident: None, auto_validate=True, account=new_account
            ),
        }
        for name, login in logins.items():
            with self.subTest(name):
                client = APP.test_client(use_cookies=True)
                with as_demo():
                    login(client)
                    self.assertEqual(client.get("/api/user").status_code, 200, name)
                self.assertEqual(client.get("/api/user").status_code, 401, f"{name} login was not marked")

    def test_mass_logout_refused_on_demo(self):
        """The demo shares the session store, so its mass logout would log out production."""
        prod = APP.test_client(use_cookies=True)
        self.login(prod)
        admin = APP.test_client(use_cookies=True)
        with as_demo():
            self.login(admin, "admin")
            resp = admin.post("/api/v2/admin/sessions/mass-logout")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.mimetype, "application/problem+json")
        self.assertEqual(resp.get_json()["type"], "demo-instance")
        self.assertIsNone(self.session_redis.get("logout-epoch"))
        self.assertEqual(prod.get("/api/user").status_code, 200)

    def test_failed_demo_login_never_saves_an_unmarked_user(self):
        """A store error mid-login still saves the session, so the marker is written first."""
        client = APP.test_client(use_cookies=True)
        with (
            as_demo(),
            mock.patch.dict(APP.config, {"PROPAGATE_EXCEPTIONS": False}),
            mock.patch("herdbook._logout_epoch", side_effect=redis.ConnectionError),
        ):
            self.assertEqual(self.login(client).status_code, 500)
        with client.session_transaction() as sess:
            self.assertTrue("user_id" not in sess or sess.get("demo_login"), dict(sess))


class TestAutoValidateGuard(unittest.TestCase):
    """Auto-validation is safe only where production refuses the sessions it leads to."""

    def _run(self, demo, **env):
        with mock.patch.dict(os.environ, env), as_demo(demo):
            try:
                settings.refuse_auto_validate_outside_demo()
                return "started"
            except RuntimeError:
                return "refused"

    def test_production_refuses_auto_validate_without_demo(self):
        self.assertEqual(self._run(False, FLASK_ENV="production", AUTO_VALIDATE_USERS="true"), "refused")

    def test_allowed_combinations(self):
        self.assertEqual(self._run(True, FLASK_ENV="production", AUTO_VALIDATE_USERS="true"), "started")
        self.assertEqual(self._run(False, FLASK_ENV="production", AUTO_VALIDATE_USERS="false"), "started")
        self.assertEqual(self._run(False, FLASK_ENV="development", AUTO_VALIDATE_USERS="true"), "started")
