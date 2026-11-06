"""Tests for Member↔User auto-linking helper."""

import json
from unittest import mock

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from utils.members import try_auto_link_member  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402
from tests.test_endpoints import FlaskTest  # noqa: E402


class TestAutoLinkMember(DatabaseTest):
    def setUp(self):
        super().setUp()
        # Reuse seeded genebank 0 and its herd 0
        self.genebank = self.genebanks[0]
        self.herd = self.herds[0]

    def _user(self, email):
        # Use the real registration path so uuid is a proper UUID hex and
        # any side effects (authenticator, privileges list) happen correctly.
        return da.register_user(email, "pass", username=email)

    def test_link_matches_by_workspace_email_writes_no_privileges(self):
        user = self._user("alfa@gotlandskaninen.se")
        member = db.Member.create(
            first_name="A",
            last_name="A",
            email="alfa-personal@example.com",  # contact email
            workspace_email="alfa@gotlandskaninen.se",  # provisioned login
            membership=db.Membership.create(),
        )
        linked = try_auto_link_member(member, user)
        self.assertTrue(linked)
        member = db.Member.get_by_id(member.id)
        self.assertEqual(member.user_id, user.id)
        # v2: herd rights are derived at check time (effective_herd_ids) —
        # auto-link must not write owner entries to the privileges JSON.
        user_reloaded = db.User.get_by_id(user.id)
        self.assertEqual(json.loads(user_reloaded._privileges), [])
        self.assertTrue(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_user_linked").exists())

    def test_link_leaves_existing_privileges_untouched(self):
        user = self._user("delta@gotlandskaninen.se")
        user._privileges = json.dumps([{"level": "owner", "herd": self.herds[0].id}])
        user.save()
        member = db.Member.create(
            first_name="D",
            last_name="D",
            email="delta-personal@example.com",
            workspace_email="delta@gotlandskaninen.se",
            membership=db.Membership.create(),
        )
        try_auto_link_member(member, user)
        privs = json.loads(db.User.get_by_id(user.id)._privileges)
        self.assertEqual(privs, [{"level": "owner", "herd": self.herds[0].id}])

    def test_link_ignores_contact_email_match(self):
        """Auto-link must NOT fire when only contact email matches."""
        user = self._user("contact-only@example.com")
        member = db.Member.create(
            first_name="X",
            last_name="Y",
            email="contact-only@example.com",  # same as user.email — irrelevant
            workspace_email=None,
            membership=db.Membership.create(),
        )
        linked = try_auto_link_member(member, user)
        self.assertFalse(linked)
        self.assertIsNone(db.Member.get_by_id(member.id).user_id)

    def test_auto_link_skips_when_user_already_linked_elsewhere(self):
        """idx_member_user_unique: a second workspace_email match is skipped, never an IntegrityError."""
        user = self._user("dup@gotlandskaninen.se")
        first = db.Member.create(first_name="A", last_name="A", membership=db.Membership.create(), user=user)
        member = db.Member.create(
            first_name="B", last_name="B", workspace_email="dup@gotlandskaninen.se", membership=db.Membership.create()
        )
        self.assertFalse(try_auto_link_member(member, user))
        self.assertEqual(db.Member.get_by_id(first.id).user_id, user.id)
        self.assertIsNone(db.Member.get_by_id(member.id).user_id)

    def test_already_linked_skip_logs_ids_not_names(self):
        """Log policy: the refusal line carries ids only — never the holder's
        name or membership number, which LinkError.detail spells out for the admin UI."""
        user = self._user("holder@gotlandskaninen.se")
        holder = db.Member.create(
            first_name="Hemlig",
            last_name="Holmberg",
            membership=db.Membership.create(member_number=6),
            user=user,
        )
        member = db.Member.create(
            first_name="B",
            last_name="B",
            workspace_email="holder@gotlandskaninen.se",
            membership=db.Membership.create(),
        )
        with self.assertLogs("utils.members", level="INFO") as logs:
            self.assertFalse(try_auto_link_member(member, user))
        output = "\n".join(logs.output)
        self.assertIn(f"member={member.id}", output)
        self.assertIn(f"holder_person_id={holder.id}", output)
        self.assertNotIn("Hemlig", output)
        self.assertNotIn("Holmberg", output)
        self.assertNotIn("nr 6", output)

    def test_link_refuses_non_domain_workspace_email(self):
        """Defense in depth: the flask-dance login path has no domain check,
        so the helper itself must refuse non-@gotlandskaninen.se addresses
        even if such a value ever ends up in workspace_email. The refusal
        line names the member id and the required domain — never the private
        address it refused (log policy)."""
        user = self._user("foxtrot@gmail.com")
        member = db.Member.create(
            first_name="F",
            last_name="F",
            workspace_email="foxtrot@gmail.com",
            membership=db.Membership.create(),
        )
        with self.assertLogs("utils.members", level="WARNING") as logs:
            self.assertFalse(try_auto_link_member(member, user))
        self.assertIsNone(db.Member.get_by_id(member.id).user_id)
        output = "\n".join(logs.output)
        self.assertIn(f"member={member.id}", output)
        self.assertIn("@gotlandskaninen.se", output)
        self.assertNotIn("foxtrot", output)
        self.assertNotIn("gmail.com", output)

    def test_auto_link_refuses_when_link_would_convey_herds(self):
        """The OAuth path never conveys access — it logs and leaves the row for the admin flow."""
        user = self._user("main@gotlandskaninen.se")
        ms = db.Membership.create(membership_status="active")
        self.herd.membership = ms
        self.herd.save()
        member = db.Member.create(
            first_name="M", last_name="M", role="huvudmedlem", workspace_email="main@gotlandskaninen.se", membership=ms
        )
        with self.assertLogs("utils.members", level="WARNING") as logs:
            self.assertFalse(try_auto_link_member(member, user))
        self.assertIn("would convey herds", logs.output[0])
        self.assertIn(self.herd.herd, logs.output[0])
        self.assertIsNone(db.Member.get_by_id(member.id).user_id)
        self.assertFalse(db.MatrikelAudit.select().exists())

    def test_auto_link_links_empty_delta_and_audits_with_self_as_actor(self):
        user = self._user("fam@gotlandskaninen.se")
        member = db.Member.create(
            first_name="F",
            last_name="F",
            role="familjemedlem",
            workspace_email="fam@gotlandskaninen.se",
            membership=db.Membership.create(membership_status="active"),
        )
        self.assertTrue(try_auto_link_member(member, user))
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "person_user_linked")
        self.assertEqual((audit.actor_id, audit.payload["source"]), (user.id, "oauth"))


class TestOAuthAutoLinkHook(DatabaseTest):
    """
    The OAuth hook must link an unlinked Member to the newly-authenticated
    User. The hook lives in app/herdbook.py (not external_auth.py).

    Helper coverage here; TestOAuthAutoLinkRoutes drives the three OAuth
    routes with mocked Google responses.
    """

    def test_hook_links_unlinked_member_with_matching_workspace_email(self):
        from herdbook import _link_member_if_any  # noqa: E402

        db.Member.create(
            first_name="Pre",
            last_name="Existing",
            email="pre-personal@example.com",  # contact
            workspace_email="pre.existing@gotlandskaninen.se",  # login
            membership=db.Membership.create(),
        )
        user = da.register_user(
            "pre.existing@gotlandskaninen.se",
            "pass",
            username="pre-existing",
        )

        _link_member_if_any(user, "pre.existing@gotlandskaninen.se")

        m = db.Member.get(db.Member.workspace_email == "pre.existing@gotlandskaninen.se")
        self.assertEqual(m.user_id, user.id)

    def test_hook_matches_verified_email_case_insensitively(self):
        """Phase 9 or Google may deliver different casing than stored —
        the DB index is on LOWER(workspace_email), match the same way."""
        from herdbook import _link_member_if_any  # noqa: E402

        user = da.register_user("echo@gotlandskaninen.se", "pass", username="echo")
        member = db.Member.create(
            first_name="E", last_name="E", workspace_email="Echo@Gotlandskaninen.se", membership=db.Membership.create()
        )
        _link_member_if_any(user, "ECHO@gotlandskaninen.se")
        self.assertEqual(db.Member.get_by_id(member.id).user_id, user.id)

    def test_hook_never_falls_back_to_user_email(self):
        """Without a provider-verified address there is no link, even
        when the self-editable User.email equals the workspace address."""
        from herdbook import _link_member_if_any  # noqa: E402

        user = da.register_user("golf@gotlandskaninen.se", "pass", username="golf")
        member = db.Member.create(
            first_name="G", last_name="G", workspace_email="golf@gotlandskaninen.se", membership=db.Membership.create()
        )
        _link_member_if_any(user, None)
        self.assertIsNone(db.Member.get_by_id(member.id).user_id)

    def test_hook_is_noop_when_no_matching_member(self):
        from herdbook import _link_member_if_any  # noqa: E402

        user = da.register_user(
            "lonely@gotlandskaninen.se",
            "pass",
            username="lonely",
        )
        # Should not raise
        _link_member_if_any(user, "lonely@gotlandskaninen.se")
        self.assertEqual(
            db.Member.select().where(db.Member.user == user).count(),
            0,
        )


class TestOAuthAutoLinkRoutes(FlaskTest):
    """
    Every OAuth route links a provisioned Member by the address Google
    verified in this login, to the account that signed in. The self-editable
    User.email (PATCH /api/manage/user/) must play no part.
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
    ):
        """GET /api/login/google after flask-dance's callback: an existing account
        (`user`), or a first login that auto-registers from `account_details`."""
        idtoken = {"sub": sub, "email": verified_email, "email_verified": email_verified}
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

    def test_token_login_links_the_signed_in_account_not_an_email_twin(self):
        # Eve's older row holds Anna's address in another casing; the old hook
        # re-resolved the User by LOWER(User.email).first() and got Eve.
        eve = da.register_user("Anna@gotlandskaninen.se", "pass", username="eve")
        anna = da.register_user("anna@gotlandskaninen.se", "pass", username="anna")
        db.Authenticators.create(user=anna.id, auth="google", auth_data="sub-anna")

        with self.app as client:
            resp = self._token_login(client, "anna@gotlandskaninen.se", "sub-anna")

        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(self._linked_to(), anna.id, f"anna={anna.id} eve={eve.id}")

    def test_dance_login_does_not_link_member_matching_self_set_email(self):
        # Eve's User.email is self-set to Anna's address; Google verified eve@.
        eve = da.register_user("anna@gotlandskaninen.se", "pass", username="eve")

        resp = self._dance_login(eve, "eve@gotlandskaninen.se")

        self.assertEqual(resp.status_code, 302)
        self.assertIsNone(self._linked_to(), f"Anna's member row linked to eve (user {eve.id})")

    def test_dance_login_links_by_verified_email(self):
        # Anna changed her contact address; Google still verifies anna@.
        anna = da.register_user("anna.privat@example.se", "pass", username="anna")

        resp = self._dance_login(anna, "anna@gotlandskaninen.se")

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self._linked_to(), anna.id)

    def test_dance_first_login_links_the_new_account_not_an_email_twin(self):
        eve = da.register_user("Anna@gotlandskaninen.se", "pass", username="eve")

        resp = self._dance_login(
            None, "anna@gotlandskaninen.se", account_details={"email": "anna@gotlandskaninen.se", "username": "anna"}
        )

        self.assertEqual(resp.status_code, 302)
        anna = db.User.get(db.User.username == "anna")
        self.assertEqual(self._linked_to(), anna.id, f"anna={anna.id} eve={eve.id}")
        self.assertEqual(anna.google_email, "anna@gotlandskaninen.se")  # CMS identity from the first login

    def test_dance_first_login_adopts_only_a_validated_account_by_email(self):
        """register_user() adopts an existing account by exact User.email. Eve
        self-sets the address of a member who has not signed in yet; Anna's first
        Google login must not attach her Google identity to Eve's account."""
        eve = da.register_user("eve@gotlandskaninen.se", "pass", username="eve", validated=True)
        with self.app as client:
            client.post("/api/login", json={"username": "eve", "password": "pass"})
            patch = client.patch("/api/manage/user/", json={"email": "anna@gotlandskaninen.se", "validated": False})
            client.get("/api/logout")
        self.assertEqual(patch.get_json(), {"status": "updated"})
        eve_now = db.User.get_by_id(eve.id)
        self.assertEqual((eve_now.email, eve_now.validated), ("anna@gotlandskaninen.se", False))

        anna_details = {"email": "anna@gotlandskaninen.se", "username": "anna"}
        resp = self._dance_login(None, "anna@gotlandskaninen.se", account_details=anna_details, auto_validate=False)

        eve_google = db.Authenticators.select().where(
            (db.Authenticators.user == eve.id) & (db.Authenticators.auth == "google")
        )
        self.assertFalse(eve_google.exists(), f"Anna's Google identity linked to eve: PATCH -> {patch.get_json()}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("validerad", resp.data.decode())
        self.assertIsNone(db.User.get_by_id(eve.id).google_email)

        # An address an admin validated is still adopted on the first Google login.
        bo = da.register_user("bo@gotlandskaninen.se", "pass", username="bo", validated=True)
        resp = self._dance_login(
            None, "bo@gotlandskaninen.se", account_details={"email": "bo@gotlandskaninen.se", "username": "bo"}
        )
        self.assertEqual(resp.status_code, 302)
        bo_google = db.Authenticators.get((db.Authenticators.user == bo.id) & (db.Authenticators.auth == "google"))
        self.assertEqual(bo_google.auth_data, "sub-dance")

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
