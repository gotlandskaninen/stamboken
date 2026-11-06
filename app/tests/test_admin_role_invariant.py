"""Backend last-admin invariant, ordered locking.

Must run against real PostgreSQL — SELECT ... FOR UPDATE row-locking
semantics do not reproduce on SQLite.
"""

import os
import threading

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402

# Disable rate limiting — multiple login() calls in quick succession
# would hit the 5/minute limit on /api/login and cause 429s.
limiter.enabled = False


class TestLastAdminInvariant(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        # Logout first — /api/login no-ops for an authenticated client.
        self.client.get("/api/logout")
        self.client.post("/api/login", json={"username": username, "password": password})

    def _make_admin(self, username, password="pass"):  # nosemgrep: hardcoded-password-default-argument
        # Convention: create via register_user + add_role, never hand-rolled
        # _privileges JSON.
        user = da.register_user(f"{username}@example.com", password, username=username)
        user.add_role("admin", None)
        return user

    def _remove_admin_via_legacy(self, target_id):
        """POST the UNTOUCHED legacy endpoint. The 409 comes from the shared
        data-access helper raising ValidationError (an HTTPException) — the
        route handler itself is byte-for-byte unchanged."""
        return self.client.post(
            "/api/manage/role",
            json={"action": "remove", "role": "admin", "user": target_id},
        )

    def test_last_admin_cannot_remove_own_admin_via_direct_api(self):
        # DatabaseTest seeds exactly one admin (self.admin).
        self.login("admin", "pass")
        resp = self._remove_admin_via_legacy(self.admin.id)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.headers["Content-Type"], "application/problem+json")
        body = resp.get_json()
        self.assertEqual(body["type"], "last-admin")
        self.assertEqual(body["title"], "Den sista administratörsrollen kan inte tas bort")
        # _privileges unchanged.
        admin = db.User.get_by_id(self.admin.id)
        self.assertTrue(any(p.get("level") == "admin" for p in admin.privileges))

    def test_admin_cannot_remove_last_remaining_admin_of_someone_else(self):
        """The invariant is GLOBAL (count-based), not actor-scoped. A distinct
        ACTIVE admin actor always keeps the count >= 1 (this explicitly allows
        A-removes-B while others remain), so the cross-user 409 is reached via
        the only legal history: A self-demotes while B exists (allowed), then
        the removal of B — now the last admin — is refused regardless of the
        request's prior legitimacy."""
        second = self._make_admin("second")
        self.login("admin", "pass")
        # Step 1 — allowed: another admin (second) still exists.
        resp = self._remove_admin_via_legacy(self.admin.id)
        self.assertEqual(resp.status_code, 200)
        # Step 2 — second is now the last admin; removing them must 409.
        self.login("second", "pass")
        resp = self._remove_admin_via_legacy(second.id)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["type"], "last-admin")

    def test_admin_can_remove_own_admin_when_others_exist(self):
        self._make_admin("other")
        self.login("admin", "pass")
        resp = self._remove_admin_via_legacy(self.admin.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "updated")
        # Audit row from the hbuser trigger. NOTE: the trigger records the
        # real DB column name "privileges" (hbuser.privileges), not the
        # Python attribute name "_privileges".
        row = (
            db.AuditLog.select()
            .where(
                (db.AuditLog.table_name == "hbuser")
                & (db.AuditLog.record_id == str(self.admin.id))
                & (db.AuditLog.changed_fields.contains("privileges"))
            )
            .order_by(db.AuditLog.id.desc())
            .first()
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.changed_by, "admin")

    def test_admin_can_remove_another_admin_when_third_admin_exists(self):
        target = self._make_admin("target")
        self._make_admin("third")
        self.login("admin", "pass")
        resp = self._remove_admin_via_legacy(target.id)
        self.assertEqual(resp.status_code, 200)
        privs = db.User.get_by_id(target.id).privileges
        self.assertFalse(any(p.get("level") == "admin" for p in privs))

    def test_last_admin_concurrent_self_demotions_no_deadlock(self):
        """TWO OS threads, each with its OWN DB
        connection (peewee connection state is thread-local), run the
        PRODUCTION update_role() simultaneously — admin A demotes A while
        admin B demotes B, and they are the last two admins.

        The ordered _lock_role_rows query must serialise them: exactly one
        succeeds, exactly one gets ValidationError('last-admin'), SQLSTATE
        40P01 never escapes, and exactly one admin remains.

        The test performs NO locking of its own — a test that pre-locks
        rows from its own transaction exercises nothing and is banned.
        """
        second = self._make_admin("second")
        barrier = threading.Barrier(2, timeout=10)
        outcomes = {}

        def demote(admin_user, key):
            try:
                barrier.wait()  # maximise overlap — both enter update_role together
                outcomes[key] = da.update_role(
                    {"action": "remove", "role": "admin", "user": admin_user.id},
                    admin_user.uuid,
                )
            except da.ValidationError as exc:
                outcomes[key] = exc
            except Exception as exc:  # a 40P01 escape lands here and FAILS below
                outcomes[key] = exc
            finally:
                db.DATABASE.close()  # release this thread's own connection

        t_a = threading.Thread(target=demote, args=(self.admin, "a"))
        t_b = threading.Thread(target=demote, args=(second, "b"))
        t_a.start()
        t_b.start()
        t_a.join(timeout=15)
        t_b.join(timeout=15)
        self.assertFalse(t_a.is_alive() or t_b.is_alive(), "hung/deadlocked threads")

        values = list(outcomes.values())
        self.assertEqual(len(values), 2)
        unexpected = [v for v in values if not isinstance(v, (dict, da.ValidationError))]
        self.assertEqual(unexpected, [], f"deadlock or other error escaped: {unexpected!r}")
        successes = [v for v in values if isinstance(v, dict) and v.get("status") == "updated"]
        conflicts = [v for v in values if isinstance(v, da.ValidationError)]
        self.assertEqual(len(successes), 1, f"expected exactly one success, got {values!r}")
        self.assertEqual(len(conflicts), 1, f"expected exactly one 409, got {values!r}")
        self.assertEqual(conflicts[0].problem_type, "last-admin")
        remaining = [u for u in db.User.select() if u.is_admin]
        self.assertEqual(len(remaining), 1, "exactly one admin must remain")
