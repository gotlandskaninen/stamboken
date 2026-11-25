"""Google sign-in never links an account to a Member by its workspace_email."""

from unittest import mock

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402

from tests.test_endpoints import FlaskTest  # noqa: E402


class TestOAuthNeverLinksRoutes(FlaskTest):
    """
    No OAuth route links a Member to the account that signed in, whatever
    address Google verified (administrators link in the matrikel).
    """

    def setUp(self):
        super().setUp()
        self.anna_member = db.Member.create(
            membership=db.Membership.create(membership_status="active"),
            first_name="Anna",
            last_name="A",
            role="familjemedlem",
            workspace_email="anna@gotlandskaninen.se",
        )

    def _linked_to(self):
        return db.Member.get_by_id(self.anna_member.id).user_id

    def _token_login(self, client, email, sub):
        token = {"sub": sub, "email": email, "email_verified": True, "hd": "gotlandskaninen.se", "name": email}
        with mock.patch("google.oauth2.id_token.verify_oauth2_token", return_value=token):
            return client.post("/api/auth/google", json={"credential": "tok"})

    def _dance_login(
        self,
        user,
        verified_email,
        account_details=None,
        email_verified=True,
        userinfo=None,
        auto_validate=True,
        sub="sub-dance",
        hd="gotlandskaninen.se",
    ):
        """GET /api/login/google after flask-dance's callback: an existing account
        (`user`), or a first login that auto-registers from `account_details`."""
        # A Workspace token of the domain by default: only one carries its hd, which a domain address needs.
        idtoken = {"sub": sub, "email": verified_email, "email_verified": email_verified, "hd": hd}
        with (
            mock.patch("herdbook._should_auto_validate_users", return_value=auto_validate),
            mock.patch("utils.external_auth.authorized", return_value=True),
            mock.patch("utils.external_auth.get_persistent", return_value=sub),
            mock.patch("utils.data_access.authenticate_with_credentials", return_value=user),
            mock.patch("utils.external_auth.google_idtoken", return_value=idtoken),
            mock.patch("utils.external_auth.google_userinfo", return_value=userinfo),
            mock.patch("utils.external_auth.get_autocreate", return_value=account_details is not None),
            mock.patch("utils.external_auth.get_account_details", return_value=account_details),
        ):
            return self.app.get("/api/login/google", headers={"Referer": "https://accounts.google.com/"})

    def test_google_login_with_verified_workspace_email_does_not_link_the_person(self):
        anna = da.register_user("anna@gotlandskaninen.se", "pass", username="anna")
        db.Authenticators.create(user=anna.id, auth="google", auth_data="sub-anna")

        with self.app as client:
            resp = self._token_login(client, "anna@gotlandskaninen.se", "sub-anna")

        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertIsNone(self._linked_to())
        self.assertFalse(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_user_linked").exists())

    def test_token_login_does_not_link_member_matching_self_set_email(self):
        eve = da.register_user("eve@gotlandskaninen.se", "pass", username="eve")
        db.Authenticators.create(user=eve.id, auth="google", auth_data="sub-eve")

        with self.app as client:
            first = self._token_login(client, "eve@gotlandskaninen.se", "sub-eve")
            self.assertEqual(first.status_code, 200, first.get_json())
            self.assertIsNone(self._linked_to())  # sanity: no link yet
            patch = client.patch("/api/manage/user/", json={"email": "anna@gotlandskaninen.se", "validated": False})
            client.get("/api/logout")
            second = self._token_login(client, "eve@gotlandskaninen.se", "sub-eve")

        self.assertIsNone(
            self._linked_to(),
            f"Anna's member row linked to eve (user {eve.id}) whose Google-verified email is "
            f"eve@gotlandskaninen.se: PATCH -> {patch.get_json()}, 2nd /api/auth/google -> {second.status_code}",
        )

    def test_token_login_does_not_link_even_the_account_verified_as_the_workspace_address(self):
        # Eve's older row holds Anna's address in another casing; the old hook
        # re-resolved the User by LOWER(User.email).first() and got Eve.
        eve = da.register_user("Anna@gotlandskaninen.se", "pass", username="eve")
        anna = da.register_user("anna@gotlandskaninen.se", "pass", username="anna")
        db.Authenticators.create(user=anna.id, auth="google", auth_data="sub-anna")

        with self.app as client:
            resp = self._token_login(client, "anna@gotlandskaninen.se", "sub-anna")

        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertIsNone(self._linked_to(), f"anna={anna.id} eve={eve.id}")

    def test_dance_login_does_not_link_member_matching_self_set_email(self):
        # Eve's User.email is self-set to Anna's address; Google verified eve@.
        eve = da.register_user("anna@gotlandskaninen.se", "pass", username="eve")

        resp = self._dance_login(eve, "eve@gotlandskaninen.se")

        self.assertEqual(resp.status_code, 302)
        self.assertIsNone(self._linked_to(), f"Anna's member row linked to eve (user {eve.id})")

    def test_dance_login_does_not_link_by_verified_workspace_email(self):
        # Anna changed her contact address; Google still verifies anna@.
        anna = da.register_user("anna.privat@example.se", "pass", username="anna")

        resp = self._dance_login(anna, "anna@gotlandskaninen.se")

        self.assertEqual(resp.status_code, 302)
        self.assertIsNone(self._linked_to())

    def _first_login_with_herd(self, address, username):
        """A first Google sign-in whose account details carry the herd attribute (herd G1)."""
        details = {"email": address, "username": username, "herd": "1"}
        resp = self._dance_login(None, address, account_details=details, sub=f"sub-{username}")
        self.assertEqual(resp.status_code, 302)
        return db.User.get(db.User.username == username)

    def test_first_login_with_herd_attribute_makes_the_main_member_owner_without_linking(self):
        """The owner guard is for manual grants: the sign-in's own grant comes before the member link."""
        membership = db.Membership.create(membership_status="active")
        eva = db.Member.create(
            membership=membership,
            first_name="Eva",
            last_name="E",
            role="huvudmedlem",
            workspace_email="eva@gotlandskaninen.se",
        )
        db.Herd.update(membership=membership).where(db.Herd.id == self.herds[0].id).execute()

        user = self._first_login_with_herd("eva@gotlandskaninen.se", "eva")

        self.assertTrue(user.has_role("owner", self.herds[0].id))
        self.assertIsNone(db.Member.get_by_id(eva.id).user_id)

    def test_first_login_with_herd_attribute_makes_a_family_member_owner_without_linking(self):
        db.Herd.update(membership=self.anna_member.membership).where(db.Herd.id == self.herds[0].id).execute()

        user = self._first_login_with_herd("anna@gotlandskaninen.se", "anna")

        self.assertTrue(user.has_role("owner", self.herds[0].id))
        self.assertIsNone(self._linked_to())

    def test_dance_login_links_no_member_without_the_domains_hd(self):
        """auth.ini may name no domain, so nothing upstream checks the token's hd: the member link does."""
        anna = da.register_user("anna.privat@example.se", "pass", username="anna")
        for hd in (None, "example.org"):
            self.assertEqual(self._dance_login(anna, "anna@gotlandskaninen.se", hd=hd).status_code, 302)
            self.assertIsNone(self._linked_to(), f"linked with hd={hd}")
            self.app.get("/api/logout")

        first = {"email": "anna@gotlandskaninen.se", "username": "anna2"}
        self._dance_login(None, "anna@gotlandskaninen.se", account_details=first, sub="sub-anna2", hd=None)
        self.assertTrue(db.User.select().where(db.User.username == "anna2").exists())  # registered all the same
        self.assertIsNone(self._linked_to())

    def test_dance_first_login_refuses_an_email_twin_in_another_casing(self):
        eve = da.register_user("Anna@gotlandskaninen.se", "pass", username="eve")

        resp = self._dance_login(
            None, "anna@gotlandskaninen.se", account_details={"email": "anna@gotlandskaninen.se", "username": "anna"}
        )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Det finns redan ett konto", resp.data.decode())
        self.assertFalse(db.User.select().where(db.User.username == "anna").exists())
        self.assertFalse(db.Authenticators.select().where(db.Authenticators.auth == "google").exists())
        self.assertIsNone(self._linked_to(), f"Anna's member row linked to eve (user {eve.id})")

    def test_dance_first_login_never_adopts_an_existing_account(self):
        """Eve self-sets the address of a member who has not signed in yet; Anna's
        first Google login must not attach her Google identity to Eve's account."""
        eve = da.register_user("eve@gotlandskaninen.se", "pass", username="eve", validated=True)
        with self.app as client:
            client.post("/api/login", json={"username": "eve", "password": "pass"})
            patch = client.patch("/api/manage/user/", json={"email": "anna@gotlandskaninen.se", "validated": False})
            client.get("/api/logout")
        self.assertEqual(patch.get_json(), {"status": "updated"})
        eve_now = db.User.get_by_id(eve.id)
        self.assertEqual((eve_now.email, eve_now.validated), ("anna@gotlandskaninen.se", True))

        anna_details = {"email": "anna@gotlandskaninen.se", "username": "anna"}
        resp = self._dance_login(None, "anna@gotlandskaninen.se", account_details=anna_details, auto_validate=False)

        eve_google = db.Authenticators.select().where(
            (db.Authenticators.user == eve.id) & (db.Authenticators.auth == "google")
        )
        self.assertFalse(eve_google.exists(), f"Anna's Google identity linked to eve: PATCH -> {patch.get_json()}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Det finns redan ett konto", resp.data.decode())
        self.assertIsNone(db.User.get_by_id(eve.id).google_email)

        # Not even an account an admin validated: its holder links Google from it.
        da.register_user("bo@gotlandskaninen.se", "pass", username="bo", validated=True)
        resp = self._dance_login(
            None, "bo@gotlandskaninen.se", account_details={"email": "bo@gotlandskaninen.se", "username": "bo"}
        )
        self.assertIn("Det finns redan ett konto", resp.data.decode())
        self.assertFalse(db.Authenticators.select().where(db.Authenticators.auth == "google").exists())

        # A brand-new account is still registered and linked while it awaits validation.
        self.app.get("/api/logout")
        resp = self._dance_login(
            None,
            "cleo@gotlandskaninen.se",
            account_details={"email": "cleo@gotlandskaninen.se", "username": "cleo"},
            auto_validate=False,
            sub="sub-cleo",
        )
        self.assertIn("validerad", resp.data.decode())
        cleo = db.User.get(db.User.email == "cleo@gotlandskaninen.se")
        self.assertFalse(cleo.validated)
        self.assertEqual(db.Authenticators.get(db.Authenticators.user == cleo.id).auth_data, "sub-cleo")

    def test_dance_login_stores_only_a_verified_google_email(self):
        """google_email is the CMS identity, so the Flask-Dance profile
        save writes only an address Google marks verified."""
        eve = da.register_user("eve@gotlandskaninen.se", "pass", username="eve")
        claimed = "cms-admin@gotlandskaninen.se"

        self._dance_login(eve, claimed, email_verified=False, userinfo={"email": claimed, "name": "Eve"})
        self.assertIsNone(db.User.get_by_id(eve.id).google_email, "unverified Google address stored")

        self.app.get("/api/logout")
        self._dance_login(eve, "eve@gotlandskaninen.se", userinfo={"email": "eve@gotlandskaninen.se"})
        self.assertEqual(db.User.get_by_id(eve.id).google_email, "eve@gotlandskaninen.se")
