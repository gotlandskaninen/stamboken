"""admin_bp registration + auth contract.

The two contract tests enumerate every /api/v2/admin rule from the live
url_map, so endpoints added by later tasks are covered automatically.
"""

import json
import os
import threading
from datetime import datetime, timedelta
from unittest import mock

import redis

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402
from tests.google_login import redirect_login, token_login  # noqa: E402

# Disable rate limiting — multiple login() calls in quick succession
# would hit the 5/minute limit on /api/login and cause 429s.
limiter.enabled = False


def _admin_rules():
    """Every admin_bp rule as (path, method), int params filled with 1."""
    rules = []
    for rule in APP.url_map.iter_rules():
        if not rule.rule.startswith("/api/v2/admin"):
            continue
        method = next(m for m in ("GET", "POST", "PATCH", "DELETE") if m in rule.methods)
        path = rule.rule
        for arg in rule.arguments:
            path = path.replace(f"<int:{arg}>", "1").replace(f"<{arg}>", "1")
        rules.append((path, method))
    return rules


class TestAdminBlueprintRegistration(DatabaseTest):
    def test_admin_blueprint_registered(self):
        bp_names = [bp.name for bp in APP.iter_blueprints()]
        self.assertIn("admin", bp_names)


class TestAdminBlueprintAuthContract(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.get("/api/logout")
        self.client.post("/api/login", json={"username": username, "password": password})

    def test_admin_required_403_for_manager(self):
        self.login("man", "pass")
        rules = _admin_rules()
        self.assertTrue(rules, "no admin_bp routes registered")
        for path, method in rules:
            with self.subTest(path=path, method=method):
                resp = self.client.open(path, method=method)
                self.assertEqual(resp.status_code, 403)
                self.assertEqual(resp.headers["Content-Type"], "application/problem+json")
                self.assertEqual(resp.get_json()["type"], "admin-required")

    def test_admin_required_403_for_unauth(self):
        """Skeleton test name; the contract for NO session is 401."""
        rules = _admin_rules()
        self.assertTrue(rules, "no admin_bp routes registered")
        for path, method in rules:
            with self.subTest(path=path, method=method):
                resp = self.client.open(path, method=method)
                self.assertEqual(resp.status_code, 401)
                self.assertEqual(resp.headers["Content-Type"], "application/problem+json")
                self.assertEqual(resp.get_json()["type"], "authentication-required")
                self.assertIsNone(resp.headers.get("Location"))


class TestAuditLogReader(DatabaseTest):
    """GET /api/v2/admin/audit-log."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.post("/api/login", json={"username": username, "password": password})

    def _seed_audit_row(self, table, record_id, changed_by, old_data, new_data, changed_fields, seconds_in_future=0):
        # Direct INSERT — the audit_log_no_update rule blocks UPDATE, not
        # INSERT. psycopg2 adapts the Python list to a PG text[].
        db.DATABASE.execute_sql(
            "INSERT INTO audit_log (table_name, record_id, operation, "
            "old_data, new_data, changed_fields, changed_by, changed_at) "
            "VALUES (%s, %s, 'UPDATE', %s::jsonb, %s::jsonb, %s, %s, "
            "NOW() + (%s || ' seconds')::interval)",
            (
                table,
                record_id,
                json.dumps(old_data),
                json.dumps(new_data),
                changed_fields,
                changed_by,
                seconds_in_future,
            ),
        )

    def test_audit_log_pagination(self):
        # Future timestamps make the 100 seeded rows strictly newer than
        # the fixture's own hbuser trigger rows → deterministic offsets
        # under the changed_at DESC default sort.
        for i in range(100):
            self._seed_audit_row(
                "herd", f"row-{i:03d}", "seeder", {}, {"name": f"N{i}"}, ["name"], seconds_in_future=200 - i
            )
        self.login("admin", "pass")
        resp = self.client.get("/api/v2/admin/audit-log?page=2&per_page=25")
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json()
        self.assertEqual(len(body["rows"]), 25)
        self.assertGreaterEqual(body["total"], 100)
        self.assertEqual(body["page"], 2)
        self.assertEqual(body["per_page"], 25)
        self.assertEqual(body["rows"][0]["record_id"], "row-025")
        self.assertEqual(body["rows"][-1]["record_id"], "row-049")

    def test_audit_log_filter_by_table(self):
        self._seed_audit_row("herd", "h-1", "seeder", {}, {"x": 1}, ["x"])
        self._seed_audit_row("genebank", "g-1", "seeder", {}, {"x": 1}, ["x"])
        self.login("admin", "pass")
        resp = self.client.get("/api/v2/admin/audit-log?table=herd")
        self.assertEqual(resp.status_code, 200, resp.data)
        rows = resp.get_json()["rows"]
        self.assertGreaterEqual(len(rows), 1)
        for row in rows:
            self.assertEqual(row["table_name"], "herd")

    def test_auth_data_stripped_by_viewer(self):
        # Simulates a future migration accident or a restored
        # pre-migration dump — the viewer strips at render time
        # regardless of row age. Covers the full
        # SENSITIVE_AUDIT_KEYS set.
        # Distinctive sentinel VALUES so the raw-body assertions below prove
        # value-absence, not merely key-absence.
        self._seed_audit_row(
            "authenticators",
            "auth-leak",
            "attacker",
            old_data={"auth_data": "SENTINEL-AUTHDATA-LEAK", "auth": "password"},
            new_data={"auth_data": "SENTINEL-AUTHDATA-LEAK", "auth": "password"},
            changed_fields=["auth_data"],
        )
        self._seed_audit_row(
            "hbuser",
            "hbuser-leak",
            "attacker",
            old_data={
                "password_hash": "SENTINEL-PWHASH-LEAK",
                "password": "SENTINEL-PW-LEAK",
                "salt": "SENTINEL-SALT-LEAK",
            },
            new_data={
                "password_hash": "SENTINEL-PWHASH-LEAK",
                "password": "SENTINEL-PW-LEAK",
                "salt": "SENTINEL-SALT-LEAK",
            },
            changed_fields=["password_hash"],
        )
        self.login("admin", "pass")

        resp = self.client.get("/api/v2/admin/audit-log?record_id=auth-leak")
        row = resp.get_json()["rows"][0]
        self.assertNotIn("auth_data", row["old_data"] or {})
        self.assertNotIn("auth_data", row["new_data"] or {})
        self.assertIn("auth", row["old_data"])  # non-sensitive keys survive
        self.assertIn("auth_data", row["changed_fields"])  # field NAME stays
        # Shape-robust: the sensitive VALUE must not appear anywhere in the
        # raw response bytes, regardless of row shape.
        self.assertNotIn(b"SENTINEL-AUTHDATA-LEAK", resp.data)

        resp = self.client.get("/api/v2/admin/audit-log?record_id=hbuser-leak")
        row = resp.get_json()["rows"][0]
        for key in ("password_hash", "password", "salt"):
            self.assertNotIn(key, row["old_data"] or {})
            self.assertNotIn(key, row["new_data"] or {})
        for sentinel in (b"SENTINEL-PWHASH-LEAK", b"SENTINEL-PW-LEAK", b"SENTINEL-SALT-LEAK"):
            self.assertNotIn(sentinel, resp.data)


class TestOnlineUsers(DatabaseTest):
    """GET /api/v2/admin/online-users."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.post("/api/login", json={"username": username, "password": password})

    def test_online_users_returns_recent(self):
        recent = da.register_user("recent@example.com", "pass", username="recent")
        stale = da.register_user("stale@example.com", "pass", username="stale")
        recent.last_active = datetime.now() - timedelta(minutes=2)
        recent.save()
        stale.last_active = datetime.now() - timedelta(minutes=60)
        stale.save()
        self.login("admin", "pass")
        resp = self.client.get("/api/v2/admin/online-users?minutes=5")
        self.assertEqual(resp.status_code, 200, resp.data)
        rows = resp.get_json()
        self.assertIsInstance(rows, list)
        names = [r["username"] for r in rows]
        self.assertIn("recent", names)
        self.assertNotIn("stale", names)
        row = next(r for r in rows if r["username"] == "recent")
        for key in ("username", "fullname", "last_active"):
            self.assertIn(key, row, f"missing key {key}")
        # Sorted last_active DESC
        stamps = [r["last_active"] for r in rows if r["last_active"]]
        self.assertEqual(stamps, sorted(stamps, reverse=True))


class TestAdminUsersList(DatabaseTest):
    """GET /api/v2/admin/users."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.post("/api/login", json={"username": username, "password": password})

    def test_admin_users_list_returns_full_field_set(self):
        self.login("admin", "pass")
        resp = self.client.get("/api/v2/admin/users")
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json()
        # Fixture seeds admin/spec/man/owner
        self.assertGreaterEqual(body["total"], 4)
        row = body["users"][0]
        # Exact-set equality pins the PII closure: a future accidental field
        # addition (e.g. an auth column) fails this test.
        self.assertEqual(
            set(row.keys()),
            {
                "id",
                "username",
                "email",
                "fullname",
                "validated",
                "v2_prod_access",
                "is_active",
                "last_active",
                "role_summary",
                "google_linked",
            },
        )
        self.assertNotIn("_privileges", row)  # ballast — detail-only

    def test_admin_users_list_manager_gets_403(self):
        self.login("man", "pass")
        resp = self.client.get("/api/v2/admin/users")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("application/problem+json", resp.content_type)

    def test_admin_users_list_filters(self):
        self.login("admin", "pass")
        # active=false — deactivate one fixture user (is_active).
        self.viewer.is_active = False
        self.viewer.save()
        # v2_prod_access=true — promote one fixture user (Phase 999.2 flag).
        self.owner.v2_prod_access = True
        self.owner.save()
        cases = [
            ("role=admin", lambda r: r["role_summary"] == "admin"),
            ("validated=false", lambda r: r["validated"] is False),
            ("active=false", lambda r: r["is_active"] is False),
            ("v2_prod_access=true", lambda r: r["v2_prod_access"] is True),
            (
                "search=man",
                lambda r: "man" in ((r["username"] or "") + (r["email"] or "") + (r["fullname"] or "")).lower(),
            ),
        ]
        for query, predicate in cases:
            with self.subTest(query=query):
                resp = self.client.get(f"/api/v2/admin/users?{query}")
                self.assertEqual(resp.status_code, 200, resp.data)
                rows = resp.get_json()["users"]
                self.assertGreaterEqual(len(rows), 1)
                for row in rows:
                    self.assertTrue(predicate(row), row)
        # active_since — push one user into the future; everyone else
        # (incl. the admin, whose last_active updates per request) is out.
        self.owner.last_active = datetime.now() + timedelta(hours=1)
        self.owner.save()
        cutoff = (datetime.now() + timedelta(minutes=30)).isoformat()
        resp = self.client.get(f"/api/v2/admin/users?active_since={cutoff}")
        rows = resp.get_json()["users"]
        self.assertEqual([r["id"] for r in rows], [self.owner.id])

    def test_admin_users_list_shows_and_filters_matrikel_admin(self):
        """matrikel_admin is shown alone and next to a studbook role
        (never hidden by the admin > manager > ... precedence) and filterable."""
        alone = da.register_user("matr_alone", "pass")
        alone.add_role("matrikel_admin", None)
        self.manager.add_role("matrikel_admin", None)
        self.admin.add_role("matrikel_admin", None)
        self.login("admin", "pass")
        resp = self.client.get("/api/v2/admin/users?role=matrikel_admin")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(
            {r["id"]: r["role_summary"] for r in resp.get_json()["users"]},
            {
                alone.id: "matrikel_admin",
                self.manager.id: "manager(G) + matrikel_admin",
                self.admin.id: "admin + matrikel_admin",
            },
        )
        resp = self.client.get("/api/v2/admin/users?role=none")
        self.assertNotIn(alone.id, [r["id"] for r in resp.get_json()["users"]])

    def test_admin_users_list_pagination(self):
        for i in range(100):
            da.register_user(f"page{i:03d}@example.com", "pass", username=f"page{i:03d}")
        self.login("admin", "pass")
        resp = self.client.get("/api/v2/admin/users?sort=username&dir=asc&page=2&per_page=25")
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json()
        self.assertEqual(len(body["users"]), 25)
        self.assertGreaterEqual(body["total"], 100)
        # username asc: page000..page099 sort before the fixture users'
        # NULL usernames (PG puts NULLs last) → offset 25 is page025.
        self.assertEqual(body["users"][0]["username"], "page025")
        self.assertEqual(body["users"][-1]["username"], "page049")

    def test_admin_users_list_sort(self):
        self.login("admin", "pass")
        for sort, direction in (
            ("username", "asc"),
            ("username", "desc"),
            ("last_active", "asc"),
            ("last_active", "desc"),
        ):
            with self.subTest(sort=sort, direction=direction):
                resp = self.client.get(f"/api/v2/admin/users?sort={sort}&dir={direction}")
                self.assertEqual(resp.status_code, 200, resp.data)
                values = [r[sort] for r in resp.get_json()["users"] if r[sort] is not None]
                self.assertEqual(values, sorted(values, reverse=(direction == "desc")))


class TestAdminUsersDetail(DatabaseTest):
    """GET /api/v2/admin/users/<u_id> + legacy-compat guard."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.post("/api/login", json={"username": username, "password": password})

    def test_admin_users_detail_full_shape(self):
        self.login("admin", "pass")
        resp = self.client.get(f"/api/v2/admin/users/{self.manager.id}")
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json()
        # Exact-set equality pins the PII closure: the detail view exposes only
        # the curated field set (no credential/auth material) — a future
        # accidental field addition fails this test.
        self.assertEqual(
            set(body.keys()),
            {
                "id",
                "username",
                "email",
                "fullname",
                "uuid",
                "validated",
                "v2_prod_access",
                "is_active",
                "_privileges",
                "last_active",
                "role_summary",
                "google_linked",
                "profile_picture",
                "google_picture",
                "google_name",
                "google_email",
                "use_google_picture",
            },
        )
        self.assertEqual(
            body["_privileges"],
            [{"level": "manager", "genebank": self.genebanks[0].id}],
        )
        # Genebank-letter label: fixture gb names are
        # "Gotland"/"Mellerud" → letters G/M.
        self.assertEqual(body["role_summary"], "manager(G)")

    def test_admin_users_detail_unknown_user_gets_404(self):
        self.login("admin", "pass")
        resp = self.client.get("/api/v2/admin/users/999999")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.headers["Content-Type"], "application/problem+json")

    def test_admin_users_detail_manager_gets_403(self):
        self.login("man", "pass")
        resp = self.client.get(f"/api/v2/admin/users/{self.admin.id}")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.headers["Content-Type"], "application/problem+json")

    def test_legacy_manage_users_still_works_for_manager(self):
        # Regression guard: an earlier hardening of the legacy endpoint was
        # reversed — manage.tsx still relies on it.
        self.login("man", "pass")
        resp = self.client.get("/api/manage/users")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIsInstance(body["users"], list)
        self.assertGreaterEqual(len(body["users"]), 1)
        # Legacy shape untouched: only email/name/id/fullname.
        self.assertEqual(set(body["users"][0].keys()), {"email", "name", "id", "fullname"})


class TestAdminUserMutations(DatabaseTest):
    """Profile PATCH + v2-prod-access + validated toggles."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        # /api/login no-ops for an already-authenticated session
        # (herdbook.py:909) — log out first so role switches work.
        self.client.get("/api/logout")
        return self.client.post("/api/login", json={"username": username, "password": password})

    def _clear_audit_log(self):
        db.DATABASE.execute_sql("TRUNCATE audit_log RESTART IDENTITY")

    def _hbuser_audit_rows(self, record_id):
        return list(
            db.AuditLog.select().where((db.AuditLog.table_name == "hbuser") & (db.AuditLog.record_id == str(record_id)))
        )

    def test_admin_users_patch_fullname_email(self):
        self.login("admin")
        resp = self.client.patch(
            f"/api/v2/admin/users/{self.viewer.id}",
            json={"fullname": "Ny Full", "email": "ny@example.com"},
        )
        self.assertEqual(resp.status_code, 200)
        u = db.User.get_by_id(self.viewer.id)
        self.assertEqual(u.fullname, "Ny Full")
        self.assertEqual(u.email, "ny@example.com")
        # returns the full detail shape
        body = resp.get_json()
        for key in ("id", "username", "email", "fullname", "_privileges"):
            self.assertIn(key, body)

    def test_admin_users_patch_manager_gets_403(self):
        self.login("man")
        resp = self.client.patch(f"/api/v2/admin/users/{self.viewer.id}", json={"fullname": "x"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.mimetype, "application/problem+json")

    def test_admin_users_patch_rejects_privileges(self):
        self.login("admin")
        resp = self.client.patch(
            f"/api/v2/admin/users/{self.viewer.id}",
            json={"_privileges": [{"level": "admin"}]},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.mimetype, "application/problem+json")
        self.assertEqual(resp.get_json()["type"], "unknown-fields")
        # role write did NOT land
        self.assertFalse(db.User.get_by_id(self.viewer.id).has_role("admin"))

    def test_admin_users_patch_rejects_v2_prod_access(self):
        self.login("admin")
        resp = self.client.patch(f"/api/v2/admin/users/{self.viewer.id}", json={"v2_prod_access": True})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["type"], "unknown-fields")
        self.assertFalse(bool(db.User.get_by_id(self.viewer.id).v2_prod_access))

    def test_v2_prod_access_toggle_audits_hbuser(self):
        self.login("admin")
        self._clear_audit_log()
        resp = self.client.patch(
            f"/api/v2/admin/users/{self.viewer.id}/v2-prod-access",
            json={"enabled": True},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(bool(db.User.get_by_id(self.viewer.id).v2_prod_access))
        rows = self._hbuser_audit_rows(self.viewer.id)
        self.assertEqual(len(rows), 1)
        self.assertIn("v2_prod_access", rows[0].changed_fields)
        # changed_by = username-or-email convention (herdbook.py:302);
        # insert_default's admin has username None, email "admin".
        self.assertEqual(rows[0].changed_by, "admin")
        # non-bool body → 400
        resp = self.client.patch(
            f"/api/v2/admin/users/{self.viewer.id}/v2-prod-access",
            json={"enabled": "yes"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_validated_toggle_via_dedicated_endpoint_audits(self):
        self.login("admin")
        self._clear_audit_log()
        resp = self.client.patch(
            f"/api/v2/admin/users/{self.viewer.id}/validated",
            json={"validated": True},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(bool(db.User.get_by_id(self.viewer.id).validated))
        rows = self._hbuser_audit_rows(self.viewer.id)
        self.assertEqual(len(rows), 1)
        self.assertIn("validated", rows[0].changed_fields)
        # non-bool body → 400
        resp = self.client.patch(
            f"/api/v2/admin/users/{self.viewer.id}/validated",
            json={"validated": "ja"},
        )
        self.assertEqual(resp.status_code, 400)


class TestAdminPasswordReset(DatabaseTest):
    """Dedicated admin password reset."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.get("/api/logout")
        return self.client.post("/api/login", json={"username": username, "password": password})

    def _clear_audit_log(self):
        db.DATABASE.execute_sql("TRUNCATE audit_log RESTART IDENTITY")

    def test_password_reset_audits_authenticators_not_hbuser(self):
        self.login("admin")
        self._clear_audit_log()
        resp = self.client.post(
            f"/api/v2/admin/users/{self.viewer.id}/password-reset",
            json={"password": "Nytt-Lösen-123"},
        )
        self.assertEqual(resp.status_code, 204)

        auth_rows = list(db.AuditLog.select().where(db.AuditLog.table_name == "authenticators"))
        self.assertEqual(len(auth_rows), 1)
        row = auth_rows[0]
        self.assertEqual(row.changed_fields, ["auth_data"])
        self.assertEqual(row.changed_by, "admin")
        for payload in (row.old_data, row.new_data):
            if payload is not None:
                self.assertNotIn("auth_data", payload)
        # zero hbuser rows for this action (password is NOT on hbuser —
        # password_hash was removed in schema v6)
        self.assertEqual(list(db.AuditLog.select().where(db.AuditLog.table_name == "hbuser")), [])
        # target can log in with the new password
        fresh = APP.test_client(use_cookies=True)
        r = fresh.post("/api/login", json={"username": "spec", "password": "Nytt-Lösen-123"})
        self.assertEqual(r.status_code, 200)

    def test_first_password_reset_google_only_user(self):
        # Google-only user: registered WITHOUT a password → no password
        # authenticator row exists → change_password takes the INSERT branch.
        google_user = da.register_user("googleonly@example.com", None, username="googleonly")
        self.login("admin")
        self._clear_audit_log()
        resp = self.client.post(
            f"/api/v2/admin/users/{google_user.id}/password-reset",
            json={"password": "Först-Lösen-1"},
        )
        self.assertEqual(resp.status_code, 204)

        auth = db.Authenticators.get_or_none(
            (db.Authenticators.user == google_user.id) & (db.Authenticators.auth == "password")
        )
        self.assertIsNotNone(auth)
        row = db.AuditLog.select().where(db.AuditLog.table_name == "authenticators").get()
        self.assertEqual(row.operation, "INSERT")
        self.assertIn("auth_data", row.changed_fields)
        self.assertNotIn("auth_data", row.new_data or {})
        self.assertEqual(row.changed_by, "admin")
        fresh = APP.test_client(use_cookies=True)
        r = fresh.post("/api/login", json={"username": "googleonly", "password": "Först-Lösen-1"})
        self.assertEqual(r.status_code, 200)

    def test_password_update_existing_authenticator_still_audits_uniformly(self):
        # UPDATE branch — same snapshot-stripping invariants as INSERT.
        self.login("admin")
        self._clear_audit_log()
        resp = self.client.post(
            f"/api/v2/admin/users/{self.owner.id}/password-reset",
            json={"password": "Uppdaterat-Lösen-2"},
        )
        self.assertEqual(resp.status_code, 204)
        row = db.AuditLog.select().where(db.AuditLog.table_name == "authenticators").get()
        self.assertEqual(row.operation, "UPDATE")
        self.assertEqual(row.changed_fields, ["auth_data"])
        for payload in (row.old_data, row.new_data):
            if payload is not None:
                self.assertNotIn("auth_data", payload)

    def test_legacy_selfservice_setpassword_untouched(self):
        # Regression guard against re-introducing the hardening that
        # would have broken legacy settings.tsx: a NON-admin POSTs the
        # no-ID legacy alias with old+new password → still works. NOTE:
        # live change_password() reads form["oldpassword"] for non-admins
        # (data_access.py:420) — that is the payload contract that works
        # today and MUST keep working (an earlier spec wrote `password` for the
        # old value, which raises KeyError in live code — pre-existing
        # legacy-UI mismatch, out of scope).
        self.login("spec")
        r = self.client.post(
            "/api/manage/setpassword/",
            json={"oldpassword": "pass", "newpassword": "Själv-Bytt-1"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json())
        # new password works, old does not
        fresh = APP.test_client(use_cookies=True)
        self.assertEqual(
            fresh.post("/api/login", json={"username": "spec", "password": "Själv-Bytt-1"}).status_code,
            200,
        )
        fresh2 = APP.test_client(use_cookies=True)
        self.assertEqual(
            fresh2.post("/api/login", json={"username": "spec", "password": "pass"}).status_code,
            401,
        )


class TestAdminPasswordResetRateLimit(DatabaseTest):
    """10/hour per acting admin. Enables the limiter,
    opposite of every other test class (salvaged from an older test)."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        limiter.reset()  # clear memory:// counters from earlier runs
        limiter.enabled = True

    def tearDown(self):
        limiter.enabled = False
        super().tearDown()

    def test_admin_password_reset_rate_limit_returns_429(self):
        self.client.post("/api/login", json={"username": "admin", "password": "pass"})
        url = f"/api/v2/admin/users/{self.viewer.id}/password-reset"
        for i in range(10):
            r = self.client.post(url, json={"password": f"Nytt-Lösen-{i:02d}"})
            self.assertEqual(r.status_code, 204, f"iteration {i}: {r.data}")
        r = self.client.post(url, json={"password": "Blockerad-11"})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.mimetype, "application/problem+json")
        body = r.get_json()
        self.assertEqual(body["status"], 429)
        self.assertEqual(body["type"], "rate-limit-exceeded")


class TestMassLogout(DatabaseTest):
    """Session mass logout.

    Uses the REAL session store (pytest stack: redis service, db 2 —
    docker-compose.pytest.yml SESSION_REDIS_URL). Precedent for touching
    db 2 in tests: test_session_redis_sharing.py."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.session_redis = redis.Redis.from_url(
            os.getenv("SESSION_REDIS_URL", "redis://redis:6379/2"),
            socket_connect_timeout=2,
        )

    def tearDown(self):
        # The logout epoch outlives the sessions; later tests in this worker start without one.
        self.session_redis.delete("logout-epoch")
        super().tearDown()

    def login(self, username, password="pass", client=None):  # nosemgrep: hardcoded-password-default-argument
        client = client or self.client
        client.get("/api/logout")
        return client.post("/api/login", json={"username": username, "password": password})

    def test_mass_logout_clears_sessions_and_writes_marker(self):
        # ≥2 real sessions via /api/login on separate test clients
        client_a = APP.test_client(use_cookies=True)
        client_b = APP.test_client(use_cookies=True)
        self.login("spec", client=client_a)
        self.login("owner", client=client_b)
        self.assertEqual(client_a.get("/api/user").status_code, 200)
        self.assertEqual(client_b.get("/api/user").status_code, 200)

        # sentinel in the SAME db proves SCAN+DEL, not FLUSHDB
        self.session_redis.set("phase17-mass-logout-sentinel", "1")
        try:
            self.login("admin")  # third session — the acting admin
            resp = self.client.post("/api/v2/admin/sessions/mass-logout")
            self.assertEqual(resp.status_code, 200)
            cleared = resp.get_json()["sessions_cleared"]
            self.assertGreaterEqual(cleared, 2)

            # every session:* key is gone; the sentinel survives
            self.assertEqual(list(self.session_redis.scan_iter(match="session:*")), [])
            self.assertTrue(self.session_redis.exists("phase17-mass-logout-sentinel"))

            # both seeded sessions are dead — and so is the acting admin's
            self.assertEqual(client_a.get("/api/user").status_code, 401)
            self.assertEqual(client_b.get("/api/user").status_code, 401)
            self.assertEqual(self.client.get("/api/user").status_code, 401)

            # explicit audit marker row (trigger can't record this)
            marker = db.AuditLog.select().where(db.AuditLog.operation == "SYSTEM").order_by(db.AuditLog.id.desc()).get()
            self.assertEqual(marker.table_name, "hbuser")
            self.assertTrue(marker.record_id.startswith("mass-logout-"))
            self.assertEqual(marker.changed_by, "admin")
            self.assertEqual(marker.new_data["sessions_cleared"], cleared)
        finally:
            self.session_redis.delete("phase17-mass-logout-sentinel")

    def mass_logout(self):
        self.login("admin")
        resp = self.client.post("/api/v2/admin/sessions/mass-logout")
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        return resp.get_json()["sessions_cleared"]

    def test_inflight_request_does_not_resurrect_session(self):
        """Flask-Session writes back every session at the end of its request, so a request
        that opened its session before the sweep recreates the key after it."""
        victim = APP.test_client(use_cookies=True)
        self.login("spec", client=victim)
        self.assertEqual(victim.get("/api/user").status_code, 200)

        entered, release = threading.Event(), threading.Event()
        real_fetch = da.fetch_user_info
        victim_uuid = str(self.viewer.uuid).replace("-", "")

        def gated_fetch(user_id):
            # Park the victim's request after open_session, before save_session.
            if str(user_id).replace("-", "") == victim_uuid and not entered.is_set():
                entered.set()
                release.wait(10)
            return real_fetch(user_id)

        with mock.patch.object(da, "fetch_user_info", gated_fetch):
            t = threading.Thread(target=lambda: victim.get("/api/user"))
            t.start()
            self.assertTrue(entered.wait(10), "victim request never reached load_user")
            cleared = self.mass_logout()
            release.set()
            t.join(10)

        keys = [k.decode() for k in self.session_redis.scan_iter(match="session:*")]
        after = victim.get("/api/user").status_code
        self.assertEqual(
            after,
            401,
            f"victim session survived mass logout: /api/user -> {after}; "
            f"sessions_cleared={cleared}, session keys after sweep={keys}",
        )

    def test_session_written_back_after_sweep_is_refused(self):
        """The same race without threads: the victim's session key, as it was before the
        sweep, is written back after it. A session from before this fix has no logout_epoch;
        one with user_id but no _user_id never reaches load_user, yet /api/user reads user_id."""
        variants = {"current": (), "pre-upgrade": ("logout_epoch",), "half-login": ("_user_id",)}
        for name, dropped in variants.items():
            with self.subTest(name):
                self.session_redis.delete("logout-epoch")
                victim = APP.test_client(use_cookies=True)
                self.login("spec", client=victim)
                with victim.session_transaction() as sess:
                    for k in dropped:
                        sess.pop(k, None)
                # Until a mass logout, unstamped sessions keep working (no logout on deploy).
                self.assertEqual(victim.get("/api/user").status_code, 200)
                key = "session:" + victim.get_cookie(APP.config["SESSION_COOKIE_NAME"]).value
                before_sweep = self.session_redis.get(key)
                self.assertIsNotNone(before_sweep, f"no {key} in the session store")

                self.mass_logout()
                self.session_redis.set(key, before_sweep)  # what the in-flight save_session does

                self.assertEqual(victim.get("/api/user").status_code, 401)
                self.assertFalse(self.session_redis.exists(key), "refused session left in the store")

    def test_every_login_path_works_after_mass_logout(self):
        """Every login path stamps the logout epoch, so a login after a mass logout is not refused."""
        self.mass_logout()
        epoch = int(self.session_redis.get("logout-epoch") or 0)
        db.User.update(validated=True).where(db.User.id == self.viewer.id).execute()

        def viewer(method, ident):
            return db.User.get_by_id(self.viewer.id)

        new_account = {"email": "ny@gotlandskaninen.se", "username": "ny"}
        logins = {
            "password": lambda c: c.post("/api/login", json={"username": "spec", "password": "pass"}),
            "google-token": lambda c: token_login(c, viewer),
            "google-redirect": lambda c: redirect_login(c, viewer),
            "google-autocreate": lambda c: redirect_login(
                c, lambda method, ident: None, auto_validate=True, account=new_account
            ),
        }
        for name, login in logins.items():
            with self.subTest(name):
                client = APP.test_client(use_cookies=True)
                login(client)
                with client.session_transaction() as sess:
                    self.assertEqual(sess.get("logout_epoch"), epoch, f"{name} login did not stamp the epoch")
                self.assertEqual(client.get("/api/user").status_code, 200)


class TestRateLimitStatus(DatabaseTest):
    """rate-limit status endpoint."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.get("/api/logout")
        return self.client.post("/api/login", json={"username": username, "password": password})

    def test_rate_limit_status_shape(self):
        self.login("admin")
        resp = self.client.get("/api/v2/admin/rate-limit-status")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()

        # memory:// branch — the pytest stack pins RATELIMIT_STORAGE_URL=
        # memory:// (docker-compose.pytest.yml) → active_counter_keys null,
        # no crash.
        self.assertEqual(body["storage"], "memory")
        self.assertIsNone(body["active_counter_keys"])
        self.assertTrue(body["storage_healthy"])
        # test modules set limiter.enabled = False at module load — the
        # endpoint reports the LIVE limiter object, so this reads False here
        # (and True in a default prod process).
        self.assertFalse(body["enabled"])

        limits = body["registered_limits"]
        self.assertTrue(
            any("admin_reset_password" in e["endpoint"] and e["limit"] == "10 per hour" for e in limits),
            f"password-reset limit missing from {limits}",
        )
        self.assertTrue(any(e["limit"] == "5 per minute" for e in limits))  # /api/login
        self.assertTrue(any(e["endpoint"] == "default" for e in limits))

        # redis branch of the counter helper — exercise it against whatever
        # redis this environment exposes (REDIS_URL: redis://redis:6379/... in
        # the pytest compose stack, redis://localhost:6379/1 under the GH
        # Actions --network host job). DBSIZE returns an int regardless of db,
        # and _active_counter_keys returns None only when unreachable — so a
        # reachable redis proves the branch parses and returns an int, no crash.
        from blueprints.admin import _active_counter_keys

        n = _active_counter_keys(os.getenv("REDIS_URL", "redis://redis:6379/3"))
        self.assertIsInstance(n, int)
