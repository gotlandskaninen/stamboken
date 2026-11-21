"""An account with a role keeps a Google login on the association's domain. ALLOW_ROLE_PASSWORD_LOGIN lifts these rules
for development and tests, and production refuses to start with it."""

import base64
import configparser
import os
import threading
import time
import unittest
from unittest import mock

import utils.data_access as da
import utils.database as db
import utils.external_auth as external_auth
import utils.settings as settings
from extensions import session_redis
from herdbook import APP, limiter

from tests.database_test import DatabaseTest
from tests.google_login import ID_TOKEN, google_session, redirect_login

limiter.enabled = False

DOMAIN_ADDRESS = ID_TOKEN["email"]
OUTSIDE_ADDRESS = "medlem@example.org"
LEGACY = "https://stamboken.gotlandskaninen.se"
NEW = "https://gotlandskaninen.se"
# This database only: under xdist, other workers' databases share the server.
WAITING_FOR_A_LOCK = (
    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'"
)


def google_link(client, sub, email, hd=ID_TOKEN["hd"]):
    """GET /api/link/google as Google's OAuth redirect lands, with Google mocked out; `hd` is the token's Workspace."""
    with (
        mock.patch("utils.external_auth.available_methods", return_value=["google"]),
        mock.patch("utils.external_auth.authorized", return_value=True),
        mock.patch("utils.external_auth.get_persistent", return_value=sub),
        mock.patch("utils.external_auth.google_verified_email", return_value=email),
        mock.patch("utils.external_auth.google_idtoken", return_value={"sub": sub, "hd": hd} if hd else {"sub": sub}),
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
        return google_session(self.admin).post(
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
                legacy = google_session(self.admin).post(
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
        """Poll until a session of this database waits for a lock, as test_database's migration-lock test does."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if db.DATABASE.execute_sql(WAITING_FOR_A_LOCK).fetchone()[0]:
                return True
            time.sleep(0.05)
        return False

    def test_a_role_account_with_only_a_password_adds_its_first_google_identity(self):
        """From a session that is no Google session, as a password session was before the role rule refused it."""
        self.member.add_role("manager", 1)
        before = da.login_generation(self.member.uuid)
        self.assertTrue(da.link_account(self.member, "google", "sub-medlem", email=DOMAIN_ADDRESS))
        self.assertEqual(self.identities(self.member), ["sub-medlem"])
        self.assertEqual(db.User.get_by_id(self.member.id).google_email, DOMAIN_ADDRESS)
        self.assertEqual(da.account_generation(self.member.uuid), before)  # adding is no occasion to revoke

    def test_a_domain_address_without_the_domains_hd_is_no_proof(self):
        """Whatever auth.ini says, google_email holds an address on the domain only from a token of the domain."""
        no_hd = {"sub": "google-sub", "email": DOMAIN_ADDRESS, "email_verified": True}
        manager = da.register_user("ansvarig@example.org", "pass", validated=True)
        manager.add_role("manager", 1)
        self.assertEqual(google_link(google_session(manager), "sub-ansvarig", DOMAIN_ADDRESS, hd=None), "null")
        self.assertEqual(self.identities(manager), [])

        self.assertEqual(google_link(self.login(), "google-sub", DOMAIN_ADDRESS, hd=None), str(self.member.id))
        self.assertIsNone(db.User.get_by_id(self.member.id).google_email)
        self.assertEqual(self.grant(self.member).status_code, 409)

        redirect_login(APP.test_client(), da.authenticate_with_credentials, idtoken=lambda: no_hd)
        self.assertIsNone(db.User.get_by_id(self.member.id).google_email)
        redirect_login(APP.test_client(), da.authenticate_with_credentials, idtoken=lambda: {**no_hd, "hd": "x.org"})
        self.assertIsNone(db.User.get_by_id(self.member.id).google_email)
        redirect_login(APP.test_client(), da.authenticate_with_credentials, idtoken=lambda: {**no_hd, **ID_TOKEN})
        self.assertEqual(db.User.get_by_id(self.member.id).google_email, DOMAIN_ADDRESS)

        db.Authenticators.delete().where(db.Authenticators.user == self.member.id).execute()  # frees the identity
        account = {"email": DOMAIN_ADDRESS, "username": "ny"}
        redirect_login(APP.test_client(), lambda m, i: None, idtoken=lambda: no_hd, auto_validate=True, account=account)
        self.assertIsNone(db.User.get(db.User.username == "ny").google_email)

    def test_a_token_that_contradicts_the_domain_proof_clears_it(self):
        """A later token of the same identity with the domain address but another hd takes the proof away; one with no
        verified address leaves it."""
        self.give_google(self.member, sub="google-sub", email=None)

        def legacy_login(idtoken):
            redirect_login(APP.test_client(), da.authenticate_with_credentials, idtoken=lambda: idtoken)
            return db.User.get_by_id(self.member.id).google_email

        self.assertEqual(legacy_login(dict(ID_TOKEN)), DOMAIN_ADDRESS)
        self.assertEqual(legacy_login({"sub": "google-sub", "email_verified": False}), DOMAIN_ADDRESS)
        self.assertIsNone(legacy_login({**ID_TOKEN, "hd": "example.org"}))
        self.assertEqual(self.grant(self.member).status_code, 409)

        self.assertEqual(legacy_login(dict(ID_TOKEN)), DOMAIN_ADDRESS)
        self.assertEqual(google_link(self.login(), "google-sub", DOMAIN_ADDRESS, hd=None), str(self.member.id))
        self.assertIsNone(db.User.get_by_id(self.member.id).google_email)  # linked again, contradicted the same way

    def test_the_address_follows_the_identity(self):
        self.give_google(self.member)
        self.assertTrue(da.link_account(self.member, "google", "sub-medlem"))  # the same one, no verified address
        self.assertEqual(db.User.get_by_id(self.member.id).google_email, DOMAIN_ADDRESS)
        self.assertTrue(da.link_account(self.member, "google", "sub-ny", from_google_session=True))
        self.assertIsNone(db.User.get_by_id(self.member.id).google_email)  # never the old identity's

    def test_a_role_account_takes_no_identity_outside_the_domain(self):
        self.member.add_role("manager", 1)
        # The first identity, from a session that is no Google session (link_account).
        self.assertIsNone(da.link_account(self.member, "google", "sub-utanfor", email=OUTSIDE_ADDRESS))
        self.assertIsNone(da.link_account(self.member, "google", "sub-utanfor"))  # no verified address
        self.assertEqual(self.identities(self.member), [])
        self.assertTrue(da.link_account(self.member, "google", "sub-medlem", email=DOMAIN_ADDRESS))
        google = self.google_login()
        self.assertEqual(google_link(google, "sub-utanfor", OUTSIDE_ADDRESS), "null")
        self.assertEqual(self.identities(self.member), ["sub-medlem"])
        self.assertEqual(google_link(google, "sub-ny", DOMAIN_ADDRESS), str(self.member.id))
        self.assertEqual(self.identities(self.member), ["sub-ny"])


class TestAdminRemovesGoogle(RoleRulesTest):
    def remove(self, user):
        return google_session(self.admin).delete(f"/api/v2/admin/users/{user.id}/google")

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

    def test_an_admin_whose_session_ended_meanwhile_removes_nothing(self):
        self.give_google(self.member)
        before = da.login_generation(self.member.uuid)
        real = da.unlink_account

        def after_the_admins_logout(*args, **kwargs):
            da.revoke_sessions(self.admin.id)  # the admin's sessions end while the request waits for the row
            return real(*args, **kwargs)

        with mock.patch.object(da, "unlink_account", after_the_admins_logout):
            self.assertEqual(self.remove(self.member).status_code, 409)
        self.assertEqual(self.identities(self.member), ["sub-medlem"])
        self.assertEqual(da.account_generation(self.member.uuid), before)

    def test_never_the_last_way_to_sign_in(self):
        only_google = da.register_user("bara-google@example.org", None, validated=True)
        self.give_google(only_google, sub="sub-bara")
        self.assertEqual(self.remove(only_google).status_code, 409)
        self.assertEqual(self.identities(only_google), ["sub-bara"])

    def test_the_way_back_with_the_access_rules_enforced(self):
        """Neither validated nor promoted: given a password, its Google login removed, it signs in and links anew."""
        stray = da.register_user("tillbaka@example.org", None)
        self.give_google(stray, sub="sub-gammal")
        with mock.patch.object(settings.service, "access_rules", "enforce"):
            admin = google_session(self.admin)
            reset = admin.post(f"/api/v2/admin/users/{stray.id}/password-reset", json={"password": "nytt"})
            self.assertEqual(reset.status_code, 204)
            self.assertEqual(self.remove(stray).status_code, 204)
            client = APP.test_client(use_cookies=True)
            resp = client.post("/api/login", json={"username": "tillbaka@example.org", "password": "nytt"})
            self.assertEqual(resp.get_json()["id"], stray.id)
            self.assertEqual(google_link(client, "sub-ny", DOMAIN_ADDRESS), str(stray.id))
        self.assertEqual(self.identities(stray), ["sub-ny"])
        self.assertEqual(db.User.get_by_id(stray.id).google_email, DOMAIN_ADDRESS)


class TestAddRoleCommand(RoleRulesTest):
    def add_role(self, konto=DOMAIN_ADDRESS, roll="admin"):
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

    def test_finds_the_account_by_its_verified_google_address_only(self):
        """The contact address is the holder's to edit: an account that set it to another's Google address is not it."""
        self.give_google(self.member)
        impostor = da.register_user(DOMAIN_ADDRESS, "pass", username="annan", validated=True)
        self.give_google(impostor, sub="sub-annan", email="annan@gotlandskaninen.se")
        result = self.add_role()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(self.has_level(self.member, "admin"))
        self.assertFalse(self.has_level(impostor, "admin"))
        self.assertNotEqual(self.add_role("medlem@example.org").exit_code, 0)  # the contact address: no account

    def test_refuses_an_address_two_accounts_hold_and_a_deactivated_account(self):
        self.give_google(self.member)
        twin = da.register_user("tvilling@example.org", None, validated=True)
        self.give_google(twin, sub="sub-tvilling")  # the same verified address, as older rows can have
        result = self.add_role()
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertFalse(self.has_level(self.member, "admin") or self.has_level(twin, "admin"))

        db.User.update(google_email=None).where(db.User.id == self.member.id).execute()
        db.User.update(is_active=False).where(db.User.id == twin.id).execute()
        result = self.add_role()
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("inaktiverat", result.output)
        self.assertFalse(self.has_level(twin, "admin"))


class TestRoleRule(RoleRulesTest):
    """With the rules on, the only way into an account with a role is a session from Google."""

    def test_a_password_session_ends_at_the_next_request_once_the_account_has_a_role(self):
        self.give_google(self.member)
        manage_role = {"action": "add", "role": "viewer", "user": self.member.id, "genebank": 1}
        for path, call in (
            ("/api/user", lambda client: client.get("/api/user")),
            ("/api/manage/role", lambda client: client.post("/api/manage/role", json=manage_role)),
        ):
            with self.subTest(path):
                db.User.update(_privileges="[]").where(db.User.id == self.member.id).execute()
                client = self.login()
                self.assertEqual(client.get("/api/user").status_code, 200)
                self.assertEqual(self.grant(self.member).status_code, 200)
                key = "session:" + client.get_cookie(APP.config["SESSION_COOKIE_NAME"]).value
                self.assertEqual(call(client).status_code, 401)
                self.assertFalse(session_redis.exists(key), "refused session left in the store")
        self.assertEqual(self.google_login().get("/api/user").get_json()["id"], self.member.id)

    def test_a_password_is_refused_for_every_role_as_a_wrong_one_is(self):
        def login(password, base_url):
            client = APP.test_client(use_cookies=True)
            form = {"username": "medlem@example.org", "password": password}
            resp = client.post("/api/login", json=form, base_url=base_url)
            return resp.status_code, resp.get_json(), client.get("/api/user", base_url=base_url).status_code

        self.member.add_role("viewer", 1)
        self.member.add_role("owner", self.herds[0].id)
        self.assertEqual(login("pass", NEW)[0], 200)  # not roles that count
        for level in da.ROLE_LEVELS:
            with self.subTest(level):
                db.User.update(_privileges="[]").where(db.User.id == self.member.id).execute()
                self.member.add_role(level, None if level in ("admin", "matrikel_admin") else 1)
                self.assertEqual(login("pass", NEW), login("fel", NEW))
                self.assertEqual(login("pass", NEW)[0], 401)
                self.assertEqual(login("pass", LEGACY), (200, None, 401))  # legacy reads any JSON body as the user
                self.assertEqual(login("pass", LEGACY), login("fel", LEGACY))

    def test_basic_auth_is_refused_for_an_account_with_a_role(self):
        auth = {"Authorization": "Basic " + base64.b64encode(b"medlem@example.org:pass").decode()}
        client = APP.test_client()
        # Without a role it works, on an older address and under /api/v2/ (404: no membership, but signed in).
        self.assertEqual(client.get("/api/active_users", headers=auth).status_code, 200)
        self.assertEqual(client.get("/api/v2/my-membership", headers=auth).status_code, 404)
        self.member.add_role("manager", 1)
        for path in ("/api/active_users", "/api/v2/my-membership"):
            with self.subTest(path):
                self.assertEqual(client.get(path, headers=auth).status_code, 401)

    def test_a_google_login_outside_the_domain_is_refused_on_both_routes(self):
        self.give_google(self.member, sub="google-sub")
        self.member.add_role("manager", 1)

        def legacy_login(idtoken):
            client = APP.test_client(use_cookies=True)
            redirect_login(client, da.authenticate_with_credentials, idtoken=lambda: idtoken)
            return client.get("/api/user").status_code

        outside = {"sub": "google-sub", "email": OUTSIDE_ADDRESS, "email_verified": True}
        # The address is written as for any account before the refusal: google_email stays the identity's.
        for name, idtoken, google_email in (
            ("an address outside the domain", outside, OUTSIDE_ADDRESS),
            ("the domain's address from another Workspace", {**ID_TOKEN, "hd": "example.org"}, None),
            ("no verified address", {"sub": "google-sub", "email_verified": False}, DOMAIN_ADDRESS),
        ):
            with self.subTest(name):
                db.User.update(google_email=DOMAIN_ADDRESS).where(db.User.id == self.member.id).execute()
                self.assertEqual(legacy_login(idtoken), 401)
                self.assertEqual(db.User.get_by_id(self.member.id).google_email, google_email)
        self.assertEqual(legacy_login(dict(ID_TOKEN)), 200)

        # The Next.js route refuses every identity outside the domain before it looks for the account.
        token = {**ID_TOKEN, "email": OUTSIDE_ADDRESS, "hd": None}
        with mock.patch("google.oauth2.id_token.verify_oauth2_token", return_value=token):
            self.assertEqual(APP.test_client().post("/api/auth/google", json={"credential": "t"}).status_code, 403)
        self.assertIsNone(da.google_login_generation(self.member, "google", "google-sub", OUTSIDE_ADDRESS))
        self.assertTrue(da.google_login_generation(self.member, "google", "google-sub", DOMAIN_ADDRESS))

    def test_the_roles_of_an_account_without_a_session_still_count(self):
        """The rule is on sessions: is_admin and the other properties answer for an account that is not signed in."""
        form = {"id": self.admin.id, "email": "ny@example.org", "validated": True}
        resp = google_session(self.manager).patch(f"/api/manage/user/{self.admin.id}", json=form)
        self.assertEqual(resp.get_json(), {"status": "error", "message": "forbidden"})
        self.assertEqual(db.User.get_by_id(self.admin.id).email, "admin")

        self.member.add_role("matrikel_admin")
        application = {"first_name": "Test", "last_name": "Sökande", "email": "sokande@example.org"}
        resp = APP.test_client().post("/api/v2/member-applications", json={**application, "gdpr_consent": True})
        self.assertEqual(resp.status_code, 201)
        notices = db.MailMessage.select().where(db.MailMessage.kind == "ansokan.ny")
        self.assertEqual([notice.recipient_id for notice in notices], [self.member.id])


class TestLegacyGoogleScope(unittest.TestCase):
    def test_the_legacy_google_login_always_asks_for_the_verified_address(self):
        """Without the e-mail scope its token has no address: no google_email, and a role account's first link fails."""
        config = configparser.ConfigParser()
        config.read_dict({"google": {"key": "klient", "secret": "x"}})  # no autocreate
        with (
            mock.patch("flask_dance.contrib.google.make_google_blueprint") as make,
            mock.patch.object(external_auth, "_active", []),
        ):
            external_auth.setup_google(mock.Mock(), config)
        self.assertIn("https://www.googleapis.com/auth/userinfo.email", make.call_args.kwargs["scope"])


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
