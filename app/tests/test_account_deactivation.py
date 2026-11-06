"""Account deactivation, three enforcement layers."""

import inspect
from unittest import mock

import utils.data_access as da
import utils.database as db
from herdbook import APP, limiter

from tests.database_test import DatabaseTest
from tests.google_login import ID_TOKEN, redirect_login, token_login

limiter.enabled = False


class TestAccountDeactivation(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username="admin", password="pass", client=None):  # nosemgrep: hardcoded-password-default-argument
        # /api/login no-ops for an already-authenticated session
        # (herdbook.py:909) — log out first so role switches work.
        client = client or self.client
        client.get("/api/logout")
        return client.post("/api/login", json={"username": username, "password": password})

    def _make_admin(self, email, username, active=True):
        user = da.register_user(email, "pass", username=username)
        user.add_role("admin", None)
        if not active:
            db.User.update(is_active=False).where(db.User.id == user.id).execute()
        return user

    def test_deactivate_self_returns_409(self):
        # A second ACTIVE admin exists, so the last-admin check passes and
        # the self-guard is what fires.
        self._make_admin("admin2@example.com", "admin2")
        self.login("admin")
        resp = self.client.patch(f"/api/v2/admin/users/{self.admin.id}/active", json={"active": False})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.mimetype, "application/problem+json")
        self.assertEqual(resp.get_json()["type"], "self-deactivation")
        self.assertTrue(db.User.get_by_id(self.admin.id).is_active)

    def test_deactivate_last_active_admin_returns_409(self):
        # Two admins, one already inactive. The
        # remaining ACTIVE admin (the actor) deactivates themselves —
        # the ordered-lock last-admin check fires FIRST (guard-order note).
        self._make_admin("admin2@example.com", "admin2", active=False)
        self.login("admin")
        resp = self.client.patch(f"/api/v2/admin/users/{self.admin.id}/active", json={"active": False})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.mimetype, "application/problem+json")
        self.assertEqual(resp.get_json()["type"], "last-admin")
        self.assertTrue(db.User.get_by_id(self.admin.id).is_active)

    def test_inactive_user_password_login_rejected(self):
        self.login("admin")
        resp = self.client.patch(f"/api/v2/admin/users/{self.viewer.id}/active", json={"active": False})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(db.User.get_by_id(self.viewer.id).is_active)

        fresh = APP.test_client(use_cookies=True)
        r = fresh.post("/api/login", json={"username": "spec", "password": "pass"})
        self.assertEqual(r.status_code, 401)
        self.assertIn("Kontot är inaktiverat", r.get_json()["message"])

    def test_inactive_user_basic_auth_rejected(self):
        self.login("admin")
        resp = self.client.patch(f"/api/v2/admin/users/{self.viewer.id}/active", json={"active": False})
        self.assertEqual(resp.status_code, 200)

        # Basic Auth går genom @LOGIN.request_loader — en ofångad
        # InactiveAccountError skulle 500:a varje sådan request
        # Kontraktet är None → ej autentiserad → 401.
        import base64

        creds = base64.b64encode(b"spec:pass").decode()
        fresh = APP.test_client()
        r = fresh.get("/api/user", headers={"Authorization": f"Basic {creds}"})
        self.assertEqual(r.status_code, 401)

    def test_inactive_user_existing_session_dies(self):
        user_client = APP.test_client(use_cookies=True)
        self.login("spec", client=user_client)
        self.assertEqual(user_client.get("/api/user").status_code, 200)

        self.login("admin")
        resp = self.client.patch(f"/api/v2/admin/users/{self.viewer.id}/active", json={"active": False})
        self.assertEqual(resp.status_code, 200)

        # Next request with the OLD session cookie is unauthenticated —
        # fetch_user_info/user_loader return None (layer 3).
        self.assertEqual(user_client.get("/api/user").status_code, 401)

    def test_deactivate_writes_audit_row(self):
        self.login("admin")
        db.DATABASE.execute_sql("TRUNCATE audit_log RESTART IDENTITY")
        resp = self.client.patch(f"/api/v2/admin/users/{self.viewer.id}/active", json={"active": False})
        self.assertEqual(resp.status_code, 200)
        rows = list(
            db.AuditLog.select().where(
                (db.AuditLog.table_name == "hbuser") & (db.AuditLog.record_id == str(self.viewer.id))
            )
        )
        self.assertEqual(len(rows), 1)
        self.assertIn("is_active", rows[0].changed_fields)
        self.assertEqual(rows[0].changed_by, "admin")
        # reactivation works and is audited too
        resp = self.client.patch(f"/api/v2/admin/users/{self.viewer.id}/active", json={"active": True})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(db.User.get_by_id(self.viewer.id).is_active)


class TestStaleUserWriters(DatabaseTest):
    """A User write outside the role lock must not write back a stale is_active or _privileges.

    Each test lets the writer read the row, commits an admin deactivation or
    role revocation, and then lets the writer save.
    """

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.fired = []

    def _after_read(self, real, target, admin_write):
        """Wrap the writer's own read of `target` so that `admin_write` commits right after it."""

        def read(*args, **kwargs):
            row = real(*args, **kwargs)
            if not self.fired and getattr(row, "id", None) == target.id:
                self.fired.append(admin_write())
            return row

        return read

    def _deactivate(self, target):
        return lambda: da.set_account_active(target.id, False, actor_user_id=self.admin.id)

    def _validate(self, user):
        db.User.update(validated=True).where(db.User.id == user.id).execute()

    def assertStillDeactivated(self, target):
        self.assertEqual(
            self.fired, [{"id": target.id, "is_active": False}], "precondition: admin deactivated mid-write"
        )
        active = db.User.get_by_id(target.id).is_active
        self.assertFalse(active, f"is_active after the write = {active!r} (deactivation undone)")

    def test_last_active_keeps_deactivation(self):
        stale = da.fetch_user_info(self.manager.uuid)  # what load_user returned
        da.set_account_active(self.manager.id, False, actor_user_id=self.admin.id)
        stale.update_last_active()  # what before_request does next
        fresh = db.User.get_by_id(self.manager.id)
        self.assertFalse(fresh.is_active, f"is_active after stale save = {fresh.is_active!r} (deactivation undone)")

    def test_last_active_keeps_role_revocation(self):
        stale = da.fetch_user_info(self.manager.uuid)
        res = da.update_role(
            {"action": "remove", "role": "manager", "user": self.manager.id, "genebank": self.genebanks[0].id},
            self.admin.uuid,
        )
        self.assertEqual(res["status"], "updated", res)
        stale.update_last_active()
        fresh = db.User.get_by_id(self.manager.id)
        self.assertFalse(
            fresh.has_role("manager", self.genebanks[0].id),
            f"privileges after stale save = {fresh._privileges} (revoked manager role restored)",
        )

    def test_profile_patch_keeps_deactivation(self):
        real_fetch = da.fetch_user_info
        target = self.owner

        def fetch_then_deactivate(uid):
            row = real_fetch(uid)
            # Only the view's own read (load_user/before_request already ran): the admin commits now.
            if any(f.function == "user_profile" for f in inspect.stack(0)):
                self.fired.append(da.set_account_active(target.id, False, actor_user_id=self.admin.id))
            return row

        self.client.post("/api/login", json={"username": target.email, "password": "pass"})
        with mock.patch.object(da, "fetch_user_info", side_effect=fetch_then_deactivate):
            resp = self.client.patch("/api/profile", json={"use_google_picture": False})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertStillDeactivated(target)
        self.assertFalse(db.User.get_by_id(target.id).use_google_picture)
        self.assertEqual(self.client.get("/api/user").status_code, 401)

    def test_v2_prod_access_keeps_deactivation(self):
        read = self._after_read(db.User.get_or_none, self.viewer, self._deactivate(self.viewer))
        with mock.patch.object(da.User, "get_or_none", side_effect=read):
            da.set_v2_prod_access(self.viewer.id, True)
        self.assertStillDeactivated(self.viewer)
        self.assertTrue(db.User.get_by_id(self.viewer.id).v2_prod_access)

    def test_set_validated_keeps_deactivation(self):
        read = self._after_read(db.User.get_or_none, self.viewer, self._deactivate(self.viewer))
        with mock.patch.object(da.User, "get_or_none", side_effect=read):
            da.set_validated(self.viewer.id, True)
        self.assertStillDeactivated(self.viewer)
        self.assertTrue(db.User.get_by_id(self.viewer.id).validated)

    def test_edit_admin_user_keeps_deactivation(self):
        read = self._after_read(db.User.get_or_none, self.viewer, self._deactivate(self.viewer))
        with mock.patch.object(da.User, "get_or_none", side_effect=read):
            da.edit_admin_user(self.viewer.id, {"fullname": "Nytt Namn"})
        self.assertStillDeactivated(self.viewer)
        self.assertEqual(db.User.get_by_id(self.viewer.id).fullname, "Nytt Namn")

    def test_update_user_keeps_deactivation(self):
        read = self._after_read(db.User.get, self.manager, self._deactivate(self.manager))
        with mock.patch.object(da.User, "get", side_effect=read):
            res = da.update_user({"id": self.manager.id, "email": "ny@example.se", "validated": True}, self.admin.uuid)
        self.assertEqual(res, {"status": "updated"})
        self.assertStillDeactivated(self.manager)
        self.assertEqual(db.User.get_by_id(self.manager.id).email, "ny@example.se")

    def test_update_user_keeps_role_revocation(self):
        revoke = lambda: da.update_role(  # noqa: E731
            {"action": "remove", "role": "manager", "user": self.manager.id, "genebank": self.genebanks[0].id},
            self.admin.uuid,
        )
        read = self._after_read(db.User.get, self.manager, revoke)
        with mock.patch.object(da.User, "get", side_effect=read):
            res = da.update_user({"id": self.manager.id, "email": "ny@example.se", "validated": True}, self.admin.uuid)
        self.assertEqual(res, {"status": "updated"})
        self.assertEqual(self.fired, [{"status": "updated"}], "precondition: admin revoked the role mid-write")
        fresh = db.User.get_by_id(self.manager.id)
        self.assertFalse(
            fresh.has_role("manager", self.genebanks[0].id),
            f"privileges after update_user = {fresh._privileges} (revoked manager role restored)",
        )

    def test_google_token_login_keeps_deactivation(self):
        authenticate = self._after_read(
            lambda method, ident: db.User.get_by_id(self.viewer.id), self.viewer, self._deactivate(self.viewer)
        )
        token_login(self.client, authenticate)
        self.assertStillDeactivated(self.viewer)
        self.assertEqual(db.User.get_by_id(self.viewer.id).google_email, ID_TOKEN["email"])

    def test_google_auto_validation_keeps_deactivation(self):
        authenticate = self._after_read(
            lambda method, ident: db.User.get_by_id(self.viewer.id), self.viewer, self._deactivate(self.viewer)
        )
        redirect_login(self.client, authenticate, auto_validate=True)
        self.assertStillDeactivated(self.viewer)
        self.assertTrue(db.User.get_by_id(self.viewer.id).validated)

    def test_google_userinfo_save_keeps_deactivation(self):
        self._validate(self.viewer)

        def userinfo():  # the HTTP round-trip to Google sits between the read and the save
            self.fired.append(self._deactivate(self.viewer)())
            return {"picture": "https://example.com/ny.png"}

        redirect_login(self.client, lambda method, ident: db.User.get_by_id(self.viewer.id), userinfo=userinfo)
        self.assertStillDeactivated(self.viewer)
        self.assertEqual(db.User.get_by_id(self.viewer.id).google_picture, "https://example.com/ny.png")

    def test_google_idtoken_save_keeps_deactivation(self):
        self._validate(self.viewer)

        def idtoken():
            # The handler reads the id_token twice (verified email for auto-link, then the
            # profile fallback); the admin deactivates once, during the first read.
            if not self.fired:
                self.fired.append(self._deactivate(self.viewer)())
            return {"picture": "https://example.com/ny.png"}

        redirect_login(self.client, lambda method, ident: db.User.get_by_id(self.viewer.id), idtoken=idtoken)
        self.assertStillDeactivated(self.viewer)
        self.assertEqual(db.User.get_by_id(self.viewer.id).google_picture, "https://example.com/ny.png")
