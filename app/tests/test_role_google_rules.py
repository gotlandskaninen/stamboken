"""An account with a role keeps a Google login on the association's domain. ALLOW_ROLE_PASSWORD_LOGIN lifts these rules
for development and tests, and production refuses to start with it."""

import os
import threading
import time
import unittest
from unittest import mock

import utils.data_access as da
import utils.database as db
import utils.settings as settings
from herdbook import APP, limiter

from tests.database_test import DatabaseTest
from tests.google_login import ID_TOKEN

limiter.enabled = False

DOMAIN_ADDRESS = "ansvarig@gotlandskaninen.se"
OUTSIDE_ADDRESS = "ansvarig@example.org"


def google_link(client, sub, email):
    """GET /api/link/google as Google's OAuth redirect lands, with Google mocked out."""
    with (
        mock.patch("utils.external_auth.available_methods", return_value=["google"]),
        mock.patch("utils.external_auth.authorized", return_value=True),
        mock.patch("utils.external_auth.get_persistent", return_value=sub),
        mock.patch("utils.external_auth.google_verified_email", return_value=email),
    ):
        return client.get("/api/link/google").get_data(as_text=True)


class RoleRulesTest(DatabaseTest):
    """The rules on, as in production; the account `member` signs in with "pass" and has no Google login yet."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        super().setUp()
        rules_on = mock.patch.object(settings.service, "allow_role_password_login", False)
        rules_on.start()
        self.addCleanup(rules_on.stop)
        self.member = da.register_user("medlem@example.org", "pass", validated=True)

    def give_google(self, user, sub="sub-medlem", email=DOMAIN_ADDRESS):
        db.Authenticators.create(user=user.id, auth="google", auth_data=sub)
        db.User.update(google_email=email).where(db.User.id == user.id).execute()

    def identities(self, user):
        rows = db.Authenticators.select().where(
            (db.Authenticators.user == user.id) & (db.Authenticators.auth == "google")
        )
        return [row.auth_data for row in rows]

    def login(self, username="medlem@example.org"):
        client = APP.test_client(use_cookies=True)
        client.post("/api/login", json={"username": username, "password": "pass"})
        return client

    def google_login(self, sub="sub-medlem", email=DOMAIN_ADDRESS):
        client = APP.test_client(use_cookies=True)
        token = {**ID_TOKEN, "sub": sub, "email": email}
        with mock.patch("google.oauth2.id_token.verify_oauth2_token", return_value=token):
            self.assertEqual(client.post("/api/auth/google", json={"credential": "t"}).status_code, 200)
        return client

    def grant(self, user, level="manager"):
        role = {"level": level} if level in ("admin", "matrikel_admin") else {"level": level, "genebank": 1}
        return self.login("admin").post(
            "/api/v2/admin/role", json={"operation": "add", "user_id": user.id, "role": role}
        )

    def has_level(self, user, level="manager"):
        return any(p["level"] == level for p in db.User.get_by_id(user.id).privileges)


class TestRoleNeedsGoogle(RoleRulesTest):
    def test_a_role_is_only_given_to_an_account_with_google_on_the_domain(self):
        for name, setup in (
            ("password only", lambda: None),
            ("Google outside the domain", lambda: self.give_google(self.member, email=OUTSIDE_ADDRESS)),
        ):
            with self.subTest(name):
                setup()
                for level in da.ROLE_LEVELS:
                    resp = self.grant(self.member, level)
                    self.assertEqual((resp.status_code, resp.get_json()["type"]), (409, "google-required"), level)
                legacy = self.login("admin").post(
                    "/api/manage/role", json={"action": "add", "role": "manager", "user": self.member.id, "genebank": 1}
                )
                self.assertEqual(legacy.status_code, 409)
                self.assertFalse(self.has_level(self.member))
        self.assertEqual(self.grant(self.member, "viewer").status_code, 200)  # not a role in ROLE_LEVELS
        db.User.update(google_email=DOMAIN_ADDRESS).where(db.User.id == self.member.id).execute()
        self.assertEqual(self.grant(self.member).status_code, 200)
        self.assertTrue(self.has_level(self.member))

    def test_the_setting_lifts_the_rule(self):
        with mock.patch.object(settings.service, "allow_role_password_login", True):
            self.assertEqual(self.grant(self.member).status_code, 200)

    def test_a_role_account_cannot_unlink_its_google_login(self):
        self.give_google(self.member)
        self.member.add_role("manager", 1)
        client = self.google_login()
        self.assertEqual(client.post("/api/unlink/google").get_data(as_text=True), "null")
        self.assertEqual(self.identities(self.member), ["sub-medlem"])

    def test_a_grant_and_an_unlink_never_leave_a_role_account_without_google(self):
        def grant():
            try:
                return (
                    da.update_role(
                        {"action": "add", "role": "manager", "user": self.member.id, "genebank": 1}, self.admin.uuid
                    )["status"]
                    == "updated"
                )
            except da.ValidationError:
                return False

        def unlink():
            return bool(da.unlink_account(self.member, "google"))

        def at_once():
            barrier = threading.Barrier(2, timeout=10)
            done = []

            def run(call):
                try:
                    barrier.wait()
                    done.append(call())
                finally:
                    db.DATABASE.close()

            threads = [threading.Thread(target=run, args=(call,)) for call in (grant, unlink)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(15)
            return done

        for name, run in (
            ("grant first", lambda: [grant(), unlink()]),
            ("unlink first", lambda: [unlink(), grant()]),
            ("at once", at_once),
        ):
            with self.subTest(name):
                db.Authenticators.delete().where(db.Authenticators.user == self.member.id).execute()
                db.User.update(_privileges="[]").where(db.User.id == self.member.id).execute()
                db.Authenticators.create(user=self.member.id, auth="password", auth_data="x")
                self.give_google(self.member)
                outcomes = run()
                self.assertEqual(sorted(outcomes), [False, True], name)
                self.assertFalse(self.has_level(self.member) and not self.identities(self.member), name)


class TestGoogleIdentity(RoleRulesTest):
    def test_a_password_session_cannot_remove_or_switch_the_identity(self):
        self.give_google(self.member)
        password = self.login()
        self.assertEqual(password.post("/api/unlink/google").get_data(as_text=True), "null")
        self.assertEqual(google_link(password, "sub-ny", DOMAIN_ADDRESS), "null")
        self.assertEqual(self.identities(self.member), ["sub-medlem"])
        # From a session from Google, both work.
        self.assertEqual(google_link(self.google_login(), "sub-ny", DOMAIN_ADDRESS), str(self.member.id))
        self.assertEqual(self.identities(self.member), ["sub-ny"])
        self.assertEqual(self.google_login("sub-ny").post("/api/unlink/google").get_data(as_text=True), "1")
        self.assertEqual(self.identities(self.member), [])
        self.assertIsNone(db.User.get_by_id(self.member.id).google_email)

    def test_a_switch_to_a_taken_identity_keeps_the_old_one(self):
        self.give_google(self.member)
        other = da.register_user("annan@example.org", None)
        self.give_google(other, sub="sub-annan", email="annan@gotlandskaninen.se")
        self.assertEqual(google_link(self.google_login(), "sub-annan", DOMAIN_ADDRESS), "null")
        self.assertEqual(self.identities(self.member), ["sub-medlem"])
        self.assertEqual(db.User.get_by_id(self.member.id).google_email, DOMAIN_ADDRESS)

    def test_a_clash_on_the_unique_index_keeps_the_old_identity(self):
        """Another account takes the identity in a transaction still open when this switch checks it is free."""
        self.give_google(self.member)
        other = da.register_user("annan@example.org", None)
        inserted, commit, linked = threading.Event(), threading.Event(), []

        def take():
            try:
                with db.DATABASE.atomic():
                    db.Authenticators.create(user=other.id, auth="google", auth_data="sub-krock")
                    inserted.set()
                    commit.wait(10)
            finally:
                db.DATABASE.close()

        def switch():
            try:
                linked.append(da.link_account(self.member, "google", "sub-krock", from_google_session=True))
            finally:
                db.DATABASE.close()

        taker = threading.Thread(target=take)
        taker.start()
        self.assertTrue(inserted.wait(10))
        switcher = threading.Thread(target=switch)
        switcher.start()
        try:
            self.assertTrue(self._wait_for_lock_waiter(), "the switch never waited on the unique index")
        finally:
            commit.set()
            taker.join(10)
            switcher.join(10)
        self.assertEqual(linked, [None])
        self.assertEqual(self.identities(self.member), ["sub-medlem"])
        self.assertEqual(self.identities(other), ["sub-krock"])

    def _wait_for_lock_waiter(self, timeout=10):
        """Poll pg_locks until a session waits for a lock, as test_database's migration-lock test does."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if db.DATABASE.execute_sql("SELECT count(*) FROM pg_locks WHERE NOT granted").fetchone()[0]:
                return True
            time.sleep(0.05)
        return False

    def test_a_role_account_with_only_a_password_adds_its_first_google_identity(self):
        self.member.add_role("manager", 1)
        client = self.login()
        self.assertEqual(google_link(client, "sub-medlem", DOMAIN_ADDRESS), str(self.member.id))
        self.assertEqual(self.identities(self.member), ["sub-medlem"])
        self.assertEqual(db.User.get_by_id(self.member.id).google_email, DOMAIN_ADDRESS)
        self.assertEqual(client.get("/api/user").status_code, 200)  # adding is no occasion to revoke

    def test_a_role_account_takes_no_identity_outside_the_domain(self):
        self.member.add_role("manager", 1)
        password = self.login()
        self.assertEqual(google_link(password, "sub-utanfor", OUTSIDE_ADDRESS), "null")
        self.assertEqual(google_link(password, "sub-utanfor", None), "null")  # no verified address
        self.assertEqual(self.identities(self.member), [])
        self.assertEqual(google_link(password, "sub-medlem", DOMAIN_ADDRESS), str(self.member.id))
        google = self.google_login()
        self.assertEqual(google_link(google, "sub-utanfor", OUTSIDE_ADDRESS), "null")
        self.assertEqual(self.identities(self.member), ["sub-medlem"])
        self.assertEqual(google_link(google, "sub-ny", DOMAIN_ADDRESS), str(self.member.id))
        self.assertEqual(self.identities(self.member), ["sub-ny"])


class TestAdminRemovesGoogle(RoleRulesTest):
    def remove(self, user):
        return self.login("admin").delete(f"/api/v2/admin/users/{user.id}/google")

    def test_only_on_an_account_without_a_role(self):
        self.give_google(self.member)
        before = da.login_generation(self.member.uuid)
        self.assertEqual(self.remove(self.member).status_code, 204)
        self.assertEqual(self.identities(self.member), [])
        self.assertIsNone(db.User.get_by_id(self.member.id).google_email)
        self.assertNotEqual(da.account_generation(self.member.uuid), before)

        manager = da.register_user("ansvarig@example.org", "pass", validated=True)
        self.give_google(manager, sub="sub-ansvarig")
        manager.add_role("manager", 1)
        resp = self.remove(manager)
        self.assertEqual((resp.status_code, resp.get_json()["type"]), (409, "google-unlink-refused"))
        self.assertEqual(self.identities(manager), ["sub-ansvarig"])

    def test_never_the_last_way_to_sign_in(self):
        only_google = da.register_user("bara-google@example.org", None, validated=True)
        self.give_google(only_google, sub="sub-bara")
        self.assertEqual(self.remove(only_google).status_code, 409)
        self.assertEqual(self.identities(only_google), ["sub-bara"])


class TestAddRoleCommand(RoleRulesTest):
    def add_role(self, konto="medlem@example.org", roll="admin"):
        return APP.test_cli_runner().invoke(args=["users", "add-role", konto, roll])

    def test_refuses_an_account_without_google_or_without_the_course(self):
        result = self.add_role()
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("Google", result.output)
        self.give_google(self.member)
        db.User.update(validated=False).where(db.User.id == self.member.id).execute()
        result = self.add_role()
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("validerat", result.output)
        self.assertFalse(self.has_level(self.member, "admin"))

    def test_gives_the_role_to_an_account_that_can_sign_in(self):
        self.give_google(self.member)
        result = self.add_role()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(self.has_level(self.member, "admin"))
        self.assertNotEqual(self.add_role(roll="manager").exit_code, 0)  # needs a genebank: the panel gives it


class TestAllowRolePasswordLoginGuard(unittest.TestCase):
    def _run(self, **env):
        with mock.patch.dict(os.environ, env):
            try:
                settings.refuse_role_password_login_in_production()
                return "started"
            except RuntimeError:
                return "refused"

    def test_production_refuses_the_setting(self):
        self.assertEqual(self._run(FLASK_ENV="production", ALLOW_ROLE_PASSWORD_LOGIN="true"), "refused")
        self.assertEqual(self._run(FLASK_ENV="production", ALLOW_ROLE_PASSWORD_LOGIN="TRUE"), "refused")

    def test_allowed_combinations(self):
        self.assertEqual(self._run(FLASK_ENV="production", ALLOW_ROLE_PASSWORD_LOGIN="false"), "started")
        self.assertEqual(self._run(FLASK_ENV="development", ALLOW_ROLE_PASSWORD_LOGIN="true"), "started")
        self.assertEqual(self._run(FLASK_ENV="testing", ALLOW_ROLE_PASSWORD_LOGIN="true"), "started")
