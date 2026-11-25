#!/usr/bin/env python3
"""
"Radera kontots uppgifter" (#250): POST /api/v2/admin/users/<id>/erase empties an account that belongs to no person.

Only runs on PostgreSQL (audit_log rules and JSONB). Names and addresses are made up; e-mail uses example.invalid.
"""

import os
import tempfile
import unittest
from datetime import date
from unittest import mock

import peewee
import utils.data_access as da
import utils.database as db
import utils.mail as mail
from herdbook import APP, limiter

from tests.database_test import DatabaseTest

_USE_POSTGRES = bool(os.getenv("POSTGRES_HOST")) and bool(os.getenv("POSTGRES_DB"))


def _audit_mentions(value):
    """audit_log rows that carry `value` anywhere in their text."""
    return db.DB_PROXY.execute_sql(
        """
        SELECT count(*) FROM audit_log
        WHERE strpos(coalesce(old_data::text, '') || coalesce(new_data::text, '') || coalesce(changed_by, ''), %s) > 0
        """,
        (value,),
    ).fetchone()[0]


@unittest.skipUnless(_USE_POSTGRES, "audit_log rules require PostgreSQL")
class TestAdminEraseAccount(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.uploads = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(self.uploads.cleanup)
        os.makedirs(os.path.join(self.uploads.name, "profiler"))
        env = mock.patch.dict(os.environ, {"UPLOAD_FOLDER": self.uploads.name})
        env.start()
        self.addCleanup(env.stop)
        limit = mock.patch.object(limiter, "enabled", False)
        limit.start()
        self.addCleanup(limit.stop)
        self.client = APP.test_client(use_cookies=True)

    def _login(self, username="admin"):
        self.client.get("/api/logout")
        self.client.post("/api/login", json={"username": username, "password": "pass"})

    def _erase(self, user_id):
        return self.client.post(f"/api/v2/admin/users/{user_id}/erase")

    def _account(self, tag):
        """An account with no role and no person: every personal field, a password, Google and a picture."""
        user = da.register_user(
            f"konto{tag}@example.invalid", "losen", username=f"anvandare{tag}", fullname=f"Namn{tag}"
        )
        db.User.update(
            google_email=f"google{tag}@example.invalid",
            google_name=f"Googlenamn{tag}",
            google_picture=f"https://example.invalid/bild{tag}.jpg",
            profile_picture=f"profil{tag}.jpg",
            name_on_check_page=True,
        ).where(db.User.id == user.id).execute()
        db.Authenticators.create(user=user, auth="google", auth_data=f"sub-{tag}")
        with open(self._picture(tag), "wb") as picture:
            picture.write(b"jpeg")
        db.DB_PROXY.execute_sql(
            """
            INSERT INTO audit_log (table_name, record_id, operation, old_data, new_data, changed_by, ip_address)
            VALUES ('herd', '1', 'UPDATE', '{}'::jsonb, '{}'::jsonb, %s, '10.0.0.1')
            """,
            (f"anvandare{tag}",),
        )
        return db.User.get_by_id(user.id)

    def _picture(self, tag):
        return os.path.join(self.uploads.name, "profiler", f"profil{tag}.jpg")

    def _assert_untouched(self, user, tag):
        row = db.User.get_by_id(user.id)
        self.assertEqual((row.username, row.email), (f"anvandare{tag}", f"konto{tag}@example.invalid"))
        self.assertTrue(os.path.exists(self._picture(tag)))
        self.assertGreater(_audit_mentions(f"anvandare{tag}"), 0)

    def test_the_admin_empties_an_account_without_a_person(self):
        user = self._account("a")
        queued = mail.enqueue_mail("notis.sammandrag", "user", user.id, {})
        self._login()

        response = self._erase(user.id)

        self.assertEqual(response.status_code, 204, response.get_data(as_text=True))
        row = db.User.get_by_id(user.id)
        self.assertEqual(
            (row.username, row.fullname, row.email, row.google_email, row.google_name, row.google_picture),
            (None, None, f"raderad-{user.id}", None, None, None),
        )
        self.assertEqual((row.profile_picture, row.is_active, row.privileges), (None, False, []))
        self.assertFalse(row.name_on_check_page)
        self.assertNotEqual(row.uuid, user.uuid)
        self.assertFalse(db.Authenticators.select().where(db.Authenticators.user == user.id).exists())
        self.assertFalse(os.path.exists(self._picture("a")))
        self.assertEqual(db.MailMessage.get_by_id(queued).status, "cancelled")
        # the audit log keeps the rows, masked: the author is the pseudonym, without an IP
        authored = db.DB_PROXY.execute_sql(
            "SELECT count(*), count(ip_address) FROM audit_log WHERE changed_by = %s", (f"raderad-{user.id}",)
        ).fetchone()
        self.assertEqual((authored[0] > 0, authored[1]), (True, 0))
        for value in (
            "anvandarea",
            "kontoa@example.invalid",
            "Namna",
            "googlea@example.invalid",
            "Googlenamna",
            "bilda.jpg",
            "profila.jpg",
        ):
            self.assertEqual(_audit_mentions(value), 0, value)
        self.assertEqual(da.authenticate_user("anvandarea", "losen"), (None, None))
        self.assertIsNone(da.authenticate_with_credentials("google", "sub-a"))

        # the account page shows it as erased, and a second erasure is refused
        detail = self.client.get(f"/api/v2/admin/users/{user.id}").get_json()
        self.assertEqual((detail["email"], detail["is_active"]), (f"raderad-{user.id}", False))
        again = self._erase(user.id)
        self.assertEqual((again.status_code, again.get_json()["type"]), (409, "erased"))
        activate = self.client.patch(f"/api/v2/admin/users/{user.id}/active", json={"active": True})
        self.assertEqual(
            (activate.status_code, activate.get_json()["detail"]),
            (409, "Kontots uppgifter är raderade, så kontot kan inte aktiveras."),
        )

    def test_an_account_with_only_lasratt_is_erased(self):
        # Every account gets Läsrätt on both genebanks when it is made, so Läsrätt is no role here.
        user = self._account("v")
        db.User.update(_privileges='[{"level": "viewer", "genebank": 1}, {"level": "viewer", "genebank": 2}]').where(
            db.User.id == user.id
        ).execute()
        self._login()
        self.assertEqual(self._erase(user.id).status_code, 204)
        row = db.User.get_by_id(user.id)
        self.assertEqual((row.email, row.privileges), (f"raderad-{user.id}", []))

    def test_an_account_with_a_role_is_refused(self):
        for level in ("helper", "owner", "manager", "matrikel_admin", "admin"):
            with self.subTest(level=level):
                tag = f"r{level}"
                user = self._account(tag)
                user.add_role("viewer", self.genebanks[1].id)  # beside the role, as every account has it
                target = {"owner": self.herds[0].id, "admin": None, "matrikel_admin": None}.get(
                    level, self.genebanks[0].id
                )
                user.add_role(level, target)
                self._login()
                response = self._erase(user.id)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.mimetype, "application/problem+json")
                self.assertEqual(response.get_json()["type"], "has-role")
                self._assert_untouched(user, tag)

    def test_an_account_a_person_points_to_is_refused_even_when_the_person_has_ended(self):
        for number, ended in enumerate((None, date(2025, 1, 31)), start=500):
            with self.subTest(ended=str(ended)):  # xdist cannot send a date
                tag = f"p{number}"
                user = self._account(tag)
                membership = db.Membership.create(member_number=number)
                db.Member.create(
                    membership=membership,
                    first_name="Test",
                    last_name="Person",
                    role="huvudmedlem",
                    end_date=ended,
                    user=user,
                )
                self._login()
                response = self._erase(user.id)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.get_json()["type"], "has-person")
                self._assert_untouched(user, tag)

    def test_the_admin_cannot_erase_her_own_account(self):
        self._login()
        response = self._erase(self.admin.id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["type"], "self")
        self.assertEqual(db.User.get_by_id(self.admin.id).email, self.admin.email)

    def test_an_unknown_account_is_404(self):
        self._login()
        response = self._erase(999999)
        self.assertEqual((response.status_code, response.get_json()["type"]), (404, "user-not-found"))

    def test_only_an_admin_may_erase(self):
        user = self._account("x")
        self.client.get("/api/logout")
        self.assertEqual(self._erase(user.id).status_code, 401)
        for username in ("spec", "man", "owner"):
            with self.subTest(username=username):
                self._login(username)
                self.assertEqual(self._erase(user.id).status_code, 403)
        self._assert_untouched(user, "x")

    def test_a_locked_audit_log_answers_503_and_rolls_everything_back(self):
        user = self._account("l")

        class LockNotAvailable(Exception):
            pgcode = "55P03"

        def locked(*_args, **_kwargs):
            raise peewee.OperationalError("lock timeout") from LockNotAvailable()

        self._login()
        with mock.patch.object(da, "purge_command_free_text", side_effect=locked):
            response = self._erase(user.id)
        self.assertEqual(response.status_code, 503, response.get_json())
        self._assert_untouched(user, "l")
        self.assertTrue(db.User.get_by_id(user.id).is_active)
