"""A session with a user is valid only with its sign-in method and the account's current mark, its generation, in the
sessions' Redis. Changing the account's credentials replaces the mark, a missing mark validates nothing, and only
production changes one."""

import base64
import os
import threading
import time
from unittest import mock

import herdbook
import redis
import utils.data_access as da
import utils.database as db
import utils.settings as settings
from herdbook import APP, limiter

from tests.database_test import DatabaseTest
from tests.google_login import ID_TOKEN, redirect_login, token_login

limiter.enabled = False

# This database only: under xdist, other workers' databases share the server.
WAITING_FOR_A_LOCK = (
    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'"
)


def as_demo(on=True):
    return mock.patch.object(settings.service, "demo_instance", on)


def google_link(client, sub, email):
    """GET /api/link/google as Google's OAuth redirect lands, with Google (a token of the domain) mocked out."""
    with (
        mock.patch("utils.external_auth.available_methods", return_value=["google"]),
        mock.patch("utils.external_auth.authorized", return_value=True),
        mock.patch("utils.external_auth.get_persistent", return_value=sub),
        mock.patch("utils.external_auth.google_verified_email", return_value=email),
        mock.patch("utils.external_auth.google_idtoken", return_value={"sub": sub, "hd": ID_TOKEN["hd"]}),
    ):
        return client.get("/api/link/google").get_data(as_text=True)


class SessionTest(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        super().setUp()
        self.session_redis = redis.Redis.from_url(
            os.getenv("SESSION_REDIS_URL", "redis://redis:6379/2"), socket_connect_timeout=2
        )
        # "spec" (a viewer, no role) also signs in with Google as ID_TOKEN's identity.
        db.Authenticators.create(user=self.viewer.id, auth="google", auth_data=ID_TOKEN["sub"])
        db.User.update(google_email=ID_TOKEN["email"]).where(db.User.id == self.viewer.id).execute()

    def login(self, username="spec", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        client = APP.test_client(use_cookies=True)
        client.post("/api/login", json={"username": username, "password": password})
        return client

    def google_login(self):
        client = APP.test_client(use_cookies=True)
        token_login(client, da.authenticate_with_credentials)
        return client

    def signed_in(self, client):
        return client.get("/api/user").status_code == 200

    def mark(self):
        return da.account_generation(self.viewer.uuid)

    def drop_mark(self):
        self.session_redis.delete(da._generation_key(self.viewer.uuid))  # pylint: disable=protected-access

    def session_key(self, client):
        return "session:" + client.get_cookie(APP.config["SESSION_COOKIE_NAME"]).value


class TestSession(SessionTest):
    def test_every_login_stamps_its_method_and_the_mark(self):
        for name, login, method in (
            ("password", self.login, "losenord"),
            ("google", self.google_login, "google"),
        ):
            with self.subTest(name):
                client = login()
                with client.session_transaction() as sess:
                    self.assertEqual((sess["auth_method"], sess["generation"]), (method, self.mark()))
                self.assertEqual(client.get("/api/user").get_json()["auth_method"], method)

    def test_a_session_without_auth_method_is_emptied(self):
        """Every session from before the stamps lacks auth_method (and generation): deploying signs everybody out."""
        variants = {
            "no auth_method": ("auth_method",),
            "from before the stamps": ("auth_method", "generation"),
            "half login": ("auth_method", "_user_id"),
        }
        for name, dropped in variants.items():
            with self.subTest(name):
                client = self.login()
                with client.session_transaction() as sess:
                    for key in dropped:
                        sess.pop(key)
                key = self.session_key(client)
                self.assertEqual(client.get("/api/user").status_code, 401)
                self.assertEqual(client.get("/api/active_users").status_code, 401)
                self.assertFalse(self.session_redis.exists(key), "refused session left in the store")

    def test_a_session_without_a_user_keeps_the_google_login_state(self):
        client = APP.test_client(use_cookies=True)
        state = {"google_oauth_state": "tillstand", "return_to_after_oauth": "/stamboken", "link_account": True}
        with client.session_transaction() as sess:
            sess.update(state)
        self.assertEqual(client.get("/api/user").status_code, 401)
        with client.session_transaction() as sess:
            self.assertEqual({k: sess.get(k) for k in state}, state)

    def test_basic_auth_needs_no_stamps(self):
        """The one-request session Basic auth makes is not checked by _session_revoked, as before."""
        auth = {"Authorization": "Basic " + base64.b64encode(b"spec:pass").decode()}
        client = APP.test_client()
        self.assertEqual(client.get("/api/user", headers=auth).get_json()["auth_method"], None)
        self.assertEqual(client.get("/api/active_users", headers=auth).status_code, 200)

    def test_basic_auth_changes_no_password(self):
        """Its one-request session has no mark, so the re-check under the account's row lock refuses the change."""
        auth = {"Authorization": "Basic " + base64.b64encode(b"spec:pass").decode()}
        form = {"oldpassword": "pass", "newpassword": "ny", "password": "ny"}
        res = APP.test_client().post("/api/manage/setpassword/", headers=auth, json=form)
        self.assertIsNone(res.get_json())
        self.assertIsNotNone(da.authenticate_user("spec", "pass")[0])

    def test_a_login_flask_login_refuses_writes_no_session(self):
        """login_user refuses an inactive account; establish_session then writes nothing, not even the mark."""
        inactive = db.User.get_by_id(self.viewer.id)
        inactive.is_active = False
        with APP.test_request_context():
            herdbook.establish_session(inactive, "losenord", da.login_generation(inactive.uuid))
            written = {"user_id", "_user_id", "generation", "auth_method", "logout_epoch"} & set(herdbook.session)
            self.assertEqual(written, set())

    def test_a_demo_login_holds_on_the_demo_after_the_generation_changed(self):
        old = self.login()
        da.new_generation(self.viewer.uuid)
        with as_demo():
            demo = self.login()
            self.assertTrue(self.signed_in(demo))
            self.assertFalse(self.signed_in(old))


class TestRevocation(SessionTest):
    """Each occasion replaces the mark: older sessions end on production and on the demo, newer ones hold on both."""

    def admin_client(self):
        return self.login("admin")

    def test_only_an_admin_sets_another_accounts_password(self):
        """Otherwise a right guess of another account's old password changes it and signs its holder out."""
        holder = self.login()
        before = self.mark()
        form = {"oldpassword": "pass", "newpassword": "ny", "password": "ny"}
        answer = self.login("man").post(f"/api/manage/setpassword/{self.viewer.id}", json=form)
        self.assertEqual((answer.status_code, answer.get_json()), (200, None))
        self.assertIsNotNone(da.authenticate_user("spec", "pass")[0])
        self.assertEqual(self.mark(), before)
        self.assertTrue(self.signed_in(holder))

    def occasions(self):
        uid = self.viewer.id
        return {
            "deactivated and activated again": lambda: (
                [
                    self.admin_client().patch(f"/api/v2/admin/users/{uid}/active", json={"active": active}).status_code
                    for active in (False, True)
                ]
                == [200, 200]
            ),
            "Google identity switched": lambda: (
                google_link(self.google_login(), "sub-ny", ID_TOKEN["email"]) == str(uid)
            ),
            "Google identity removed by the holder": lambda: (
                self.google_login().post("/api/unlink/google").get_data(as_text=True) == "1"
            ),
            "Google login removed by an admin": lambda: (
                self.admin_client().delete(f"/api/v2/admin/users/{uid}/google").status_code == 204
            ),
            "password changed by the holder": lambda: (
                self.login()
                .post("/api/manage/setpassword/", json={"oldpassword": "pass", "newpassword": "pass"})
                .get_json()
                is True
            ),
            "password reset by an admin": lambda: (
                self.admin_client()
                .post(f"/api/v2/admin/users/{uid}/password-reset", json={"password": "pass"})
                .status_code
                == 204
            ),
            "Logga ut överallt": lambda: (
                self.admin_client().post(f"/api/v2/admin/users/{uid}/logga-ut").status_code == 204
            ),
        }

    def test_every_occasion_replaces_the_mark(self):
        for name, occasion in self.occasions().items():
            with self.subTest(name):
                self.setUp()  # the Google identity back, and a fresh account state
                old_production = self.login()
                with as_demo():
                    old_demo = self.login()  # a session the demo made
                    self.assertTrue(self.signed_in(old_demo))
                before = self.mark()
                self.assertTrue(occasion(), name)
                self.assertNotEqual(self.mark(), before)
                self.assertFalse(self.signed_in(old_production))
                with as_demo():
                    self.assertFalse(self.signed_in(old_demo))
                new_production = self.login()
                self.assertTrue(self.signed_in(new_production))
                with as_demo():
                    new_demo = self.login()
                    self.assertTrue(self.signed_in(new_demo))

    def test_logout_everywhere_needs_an_admin(self):
        before = self.mark() or da.login_generation(self.viewer.uuid)
        for client in (APP.test_client(), self.login("man"), self.login("spec")):
            self.assertIn(client.post(f"/api/v2/admin/users/{self.viewer.id}/logga-ut").status_code, (401, 403))
        self.assertEqual(self.mark(), before)

    def test_no_call_to_the_demo_changes_a_mark(self):
        production = self.login()
        before = self.mark()
        uid = self.viewer.id
        with as_demo():
            admin = self.admin_client()
            refused = admin.post(f"/api/v2/admin/users/{uid}/logga-ut")
            self.assertEqual((refused.status_code, refused.get_json()["type"]), (403, "demo-instance"))
            reset = admin.post(f"/api/v2/admin/users/{uid}/password-reset", json={"password": "pass"})
            self.assertEqual(reset.status_code, 204)
            for sub in ("sub-ny", ID_TOKEN["sub"]):  # two switches
                self.assertTrue(da.link_account(self.viewer, "google", sub, from_google_session=True))
            self.assertEqual(self.google_login().post("/api/unlink/google").get_data(as_text=True), "1")
            for active in (False, True):
                admin.patch(f"/api/v2/admin/users/{uid}/active", json={"active": active})
        self.assertEqual(self.mark(), before)
        self.assertTrue(self.signed_in(production))


class TestLostMarkAndRaces(SessionTest):
    def test_without_the_mark_no_session_of_the_account_holds(self):
        first, second, other = self.login(), self.google_login(), self.login("man")
        self.drop_mark()
        self.assertFalse(self.signed_in(first))
        self.assertFalse(self.signed_in(second))
        self.assertTrue(self.signed_in(other))

    def test_a_session_written_back_after_redis_was_emptied_is_refused(self):
        victim = self.login()
        key = self.session_key(victim)
        written = self.session_redis.get(key)
        # Redis emptied, as far as this account goes, while a request was in flight.
        self.session_redis.delete(key)
        self.drop_mark()
        self.session_redis.set(key, written)  # what the in-flight save_session does
        self.assertFalse(self.signed_in(victim))
        self.assertTrue(self.signed_in(self.login()))  # a new login gets a new mark
        self.session_redis.set(key, written)
        self.assertFalse(self.signed_in(victim))

    def pause_login(self, change):
        """
        Runs `change` after the first login checked the credential and read the mark, before its session is made.
        A login inside `change` passes straight through.
        """
        real = herdbook.establish_session
        calls = []

        def paused(user, method, generation, **stamps):
            calls.append(method)
            if len(calls) == 1:
                change()
            return real(user, method, generation, **stamps)

        return mock.patch.object(herdbook, "establish_session", paused)

    def test_a_password_login_paused_while_the_password_changes_is_refused(self):
        for had_mark in (True, False):
            with self.subTest(had_mark=had_mark):
                self.login()
                if not had_mark:
                    self.drop_mark()
                with self.pause_login(
                    lambda: da.change_password(self.admin, self.viewer.id, {"password": "ny", "newpassword": "ny"})
                ):
                    client = self.login()
                self.assertFalse(self.signed_in(client))
                self.assertTrue(self.signed_in(self.login(password="ny")))
                da.change_password(self.admin, self.viewer.id, {"password": "pass", "newpassword": "pass"})

    def test_a_google_login_while_the_identity_switches_is_refused(self):
        def switch():
            self.assertTrue(da.link_account(self.viewer, "google", "sub-ny", from_google_session=True))

        with self.pause_login(switch):
            client = self.google_login()
        self.assertFalse(self.signed_in(client))

        # A switch before the login takes the account's lock: the identity looked up again is gone.
        db.Authenticators.update(auth_data=ID_TOKEN["sub"]).where(db.Authenticators.user == self.viewer.id).execute()
        real = da.google_login_generation

        def switched_first(*args):
            switch()
            return real(*args)

        client = APP.test_client(use_cookies=True)
        with mock.patch.object(da, "google_login_generation", switched_first):
            self.assertEqual(token_login(client, da.authenticate_with_credentials).status_code, 401)
        self.assertFalse(self.signed_in(client))

    def test_two_first_logins_without_a_mark_both_hold(self):
        self.drop_mark()
        second = []
        with self.pause_login(lambda: second.append(self.google_login())):
            first = self.login()
        self.assertTrue(self.signed_in(first))
        self.assertTrue(self.signed_in(second[0]))

    def test_the_demo_never_overwrites_a_mark(self):
        mark = da.login_generation(self.viewer.uuid)
        with as_demo():
            self.assertEqual(da.login_generation(self.viewer.uuid), mark)
            self.assertTrue(self.signed_in(self.login()))
            da.new_generation(self.viewer.uuid)
        self.assertEqual(self.mark(), mark)
        # The demo may create a missing one, which production then reads.
        self.drop_mark()
        with as_demo():
            demo = self.login()
        created = self.mark()
        self.assertIsNotNone(created)
        self.assertTrue(self.signed_in(self.login()))
        self.assertEqual(self.mark(), created)
        with as_demo():
            self.assertTrue(self.signed_in(demo))

    def test_a_mark_that_cannot_be_replaced_leaves_the_password(self):
        with mock.patch.object(da, "new_generation", side_effect=redis.ConnectionError):
            with self.assertRaises(redis.ConnectionError):
                da.change_password(self.admin, self.viewer.id, {"password": "ny", "newpassword": "ny"})
            with self.assertRaises(redis.ConnectionError):
                da.set_account_active(self.viewer.id, False, actor_user_id=self.admin.id)
        self.assertEqual(da.authenticate_user("spec", "ny"), (None, None))
        self.assertIsNotNone(da.authenticate_user("spec", "pass")[0])
        self.assertTrue(db.User.get_by_id(self.viewer.id).is_active)

    def test_a_login_during_a_password_change_waits_and_does_not_take_the_old_password(self):
        """The change has replaced the mark but not committed: the login waits on the account's row."""
        swapped, release, done = threading.Event(), threading.Event(), threading.Event()
        real = da.new_generation
        results = {}

        def hold(user_uuid):
            real(user_uuid)
            swapped.set()
            release.wait(10)

        def change():
            try:
                with mock.patch.object(da, "new_generation", hold):
                    da.change_password(self.admin, self.viewer.id, {"password": "ny", "newpassword": "ny"})
            finally:
                db.DATABASE.close()

        def login():
            try:
                results["client"] = self.login()
            finally:
                done.set()
                db.DATABASE.close()

        changer = threading.Thread(target=change)
        changer.start()
        self.assertTrue(swapped.wait(10), "the change never replaced the mark")
        waiter = threading.Thread(target=login)
        waiter.start()
        try:
            self.assertTrue(self._wait_for_lock_waiter(), "the login never waited on the account's row")
            self.assertFalse(done.is_set())
        finally:
            release.set()
            changer.join(10)
            waiter.join(10)
        self.assertFalse(self.signed_in(results["client"]))
        self.assertTrue(self.signed_in(self.login(password="ny")))

    def identities(self):
        rows = db.Authenticators.select().where(
            (db.Authenticators.user == self.viewer.id) & (db.Authenticators.auth == "google")
        )
        return [row.auth_data for row in rows]

    def test_a_link_that_waited_for_the_account_while_its_sessions_ended_is_refused(self):
        """The admin removes the Google login while the holder's link waits for the account's row: without the
        session's mark the link would count as a first one, open to a password session."""
        real = da.link_account

        def after_the_removal(*args, **kwargs):
            self.assertTrue(da.unlink_account(self.viewer, "google"))  # the admin's removal takes the row first
            return real(*args, **kwargs)

        password = self.login()
        with mock.patch.object(da, "link_account", after_the_removal):
            self.assertEqual(google_link(password, "sub-ny", ID_TOKEN["email"]), "null")
        self.assertEqual(self.identities(), [])

    def test_an_unlink_that_waited_for_the_account_while_its_sessions_ended_is_refused(self):
        real = da.unlink_account

        def after_logout_everywhere(*args, **kwargs):
            da.new_generation(self.viewer.uuid)  # what Logga ut överallt does once it has the row
            return real(*args, **kwargs)

        google = self.google_login()
        with mock.patch.object(da, "unlink_account", after_logout_everywhere):
            self.assertEqual(google.post("/api/unlink/google").get_data(as_text=True), "null")
        self.assertEqual(self.identities(), [ID_TOKEN["sub"]])

    def test_a_google_login_never_writes_its_address_after_a_switch(self):
        """google_email is the domain proof for a role: a login that checked identity A must not write A's address
        once the holder has switched to an identity outside the domain."""
        idtoken = {"sub": ID_TOKEN["sub"], "email": ID_TOKEN["email"], "email_verified": True, "hd": ID_TOKEN["hd"]}
        logins = {
            "token": lambda: token_login(APP.test_client(), da.authenticate_with_credentials),
            "legacy": lambda: redirect_login(
                APP.test_client(), da.authenticate_with_credentials, idtoken=lambda: idtoken
            ),
        }
        real = da.google_login_generation

        def then_switch(*args, **kwargs):
            generation = real(*args, **kwargs)
            da.link_account(self.viewer, "google", "sub-utanfor", email="medlem@example.org", from_google_session=True)
            return generation

        for name, login in logins.items():
            with self.subTest(name):
                self.setUp()
                db.User.update(validated=True).where(db.User.id == self.viewer.id).execute()
                with mock.patch.object(da, "google_login_generation", then_switch):
                    login()
                self.assertEqual(self.identities(), ["sub-utanfor"])
                self.assertEqual(db.User.get_by_id(self.viewer.id).google_email, "medlem@example.org")

    @staticmethod
    def first(change, real):
        """`real`, after `change` has taken the account's row: what a request waiting for the lock meets."""

        def after(*args, **kwargs):
            change()
            return real(*args, **kwargs)

        return after

    def test_a_change_that_waited_through_a_mass_logout_is_refused(self):
        """The mass logout raises the logout epoch and leaves the marks alone; a change that waited for the account's
        row asks the same question as every request: is the session still valid."""
        self.addCleanup(self.session_redis.delete, da.LOGOUT_EPOCH_KEY)
        changes = {
            "link": ("link_account", lambda: google_link(self.google_login(), "sub-ny", ID_TOKEN["email"])),
            "unlink": ("unlink_account", lambda: self.google_login().post("/api/unlink/google").get_data(as_text=True)),
        }
        for name, (function, request) in changes.items():
            with self.subTest(name):
                self.setUp()
                mass_logout = self.first(
                    lambda: da.mass_logout_sessions(da.session_redis, "test"), getattr(da, function)
                )
                with mock.patch.object(da, function, mass_logout):
                    self.assertEqual(request(), "null")
                self.assertEqual(self.identities(), [ID_TOKEN["sub"]])

    def test_a_password_change_that_waited_while_its_session_ended_is_refused(self):
        """Admin A changes her own password (an admin is asked no old one) while admin B resets it, or while a mass
        logout runs: a revoked session must not decide the password once it gets the row."""
        self.addCleanup(self.session_redis.delete, da.LOGOUT_EPOCH_KEY)
        real = da.change_password
        other = da.register_user("admin2@example.org", "pass", username="admin2")
        other.add_role("admin", None)
        revocations = {
            "reset by another admin": lambda: real(other, self.admin.id, {"password": "satt", "newpassword": "satt"}),
            "mass logout": lambda: da.mass_logout_sessions(da.session_redis, "test"),
        }
        for name, revoke in revocations.items():
            with self.subTest(name):
                real(other, self.admin.id, {"password": "pass", "newpassword": "pass"})
                own = self.login("admin")
                with mock.patch.object(da, "change_password", self.first(revoke, real)):
                    answer = own.post("/api/manage/setpassword/", json={"password": "egen", "newpassword": "egen"})
                self.assertIsNone(answer.get_json())
                self.assertEqual(da.authenticate_user("admin", "egen"), (None, None))

    def test_logout_everywhere_waits_for_the_account(self):
        """It takes the account's row lock, as every change of credentials does."""
        before = da.login_generation(self.viewer.uuid)
        admin = self.admin_client()
        held, release, answers = threading.Event(), threading.Event(), []

        def hold():
            try:
                with db.DATABASE.atomic():
                    db.User.select().where(db.User.id == self.viewer.id).for_update().get()
                    held.set()
                    release.wait(10)
            finally:
                db.DATABASE.close()

        def logout_everywhere():
            try:
                answers.append(admin.post(f"/api/v2/admin/users/{self.viewer.id}/logga-ut").status_code)
            finally:
                db.DATABASE.close()

        holder = threading.Thread(target=hold)
        holder.start()
        self.assertTrue(held.wait(10))
        logout = threading.Thread(target=logout_everywhere)
        logout.start()
        try:
            self.assertTrue(self._wait_for_lock_waiter(), "Logga ut överallt never waited for the account's row")
            self.assertEqual(self.mark(), before)
        finally:
            release.set()
            holder.join(10)
            logout.join(10)
        self.assertEqual(answers, [204])
        self.assertNotEqual(self.mark(), before)

    def admin_client(self):
        return self.login("admin")

    def _wait_for_lock_waiter(self, timeout=10):
        """Poll until a session of this database waits for a lock, as test_database's migration-lock test does."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if db.DATABASE.execute_sql(WAITING_FOR_A_LOCK).fetchone()[0]:
                return True
            time.sleep(0.05)
        return False


class TestMassLogoutCommand(SessionTest):
    """flask users mass-logout: the admin's mass logout without a session, for when signing in does not work."""

    def mass_logout(self):
        return APP.test_cli_runner().invoke(args=["users", "mass-logout"])

    def test_signs_everybody_out(self):
        client = self.login()
        key = self.session_key(client)
        result = self.mass_logout()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(self.session_redis.exists(key))
        self.assertFalse(self.signed_in(client))
        self.assertTrue(db.AuditLog.select().where(db.AuditLog.record_id.startswith("mass-logout-")).exists())

    def test_not_on_the_demo(self):
        client = self.login()
        with as_demo():
            self.assertNotEqual(self.mass_logout().exit_code, 0)
        self.assertTrue(self.signed_in(client))
