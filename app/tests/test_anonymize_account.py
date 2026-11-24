#!/usr/bin/env python3
"""
Anonymization empties the person's account (#190): no personal data on the hbuser row or in audit_log, no way in.

Only runs on PostgreSQL (audit_log rules and JSONB). Names and addresses are made up; e-mail uses example.invalid.
"""

import inspect
import io
import os
import tempfile
import threading
import time
import unittest
import uuid
from datetime import date, datetime, timezone
from unittest import mock

import peewee
import utils.data_access as da
import utils.database as db
import utils.mail as mail
import utils.matrikel as matrikel
from herdbook import APP, limiter

from tests.database_test import DatabaseTest

_USE_POSTGRES = bool(os.getenv("POSTGRES_HOST")) and bool(os.getenv("POSTGRES_DB"))

NOW = datetime(2026, 11, 16, 3, 55, tzinfo=timezone.utc)
OLD = date(2025, 11, 1)  # more than 12 calendar months before NOW


def _audit_mentions(value):
    """audit_log rows that carry `value` anywhere in their text."""
    return db.DB_PROXY.execute_sql(
        """
        SELECT count(*) FROM audit_log
        WHERE strpos(coalesce(old_data::text, '') || coalesce(new_data::text, '') || coalesce(changed_by, ''), %s) > 0
        """,
        (value,),
    ).fetchone()[0]


def _written_by(changed_by):
    """An audited herd edit by `changed_by` (INSERT passes the append-only rule)."""
    db.DB_PROXY.execute_sql(
        """
        INSERT INTO audit_log (table_name, record_id, operation, old_data, new_data, changed_by, ip_address)
        VALUES ('herd', '1', 'UPDATE', '{}'::jsonb, '{}'::jsonb, %s, '10.0.0.1')
        """,
        (changed_by,),
    )


@unittest.skipUnless(_USE_POSTGRES, "audit_log rules require PostgreSQL")
class TestAnonymizeEmptiesTheAccount(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.uploads = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        os.makedirs(os.path.join(self.uploads.name, "profiler"))
        env = mock.patch.dict(os.environ, {"UPLOAD_FOLDER": self.uploads.name})
        env.start()
        self.addCleanup(env.stop)
        folder = mock.patch.dict(APP.config, {"PROFILE_UPLOAD_FOLDER": os.path.join(self.uploads.name, "profiler")})
        folder.start()
        self.addCleanup(folder.stop)
        limit = mock.patch.object(limiter, "enabled", False)  # these tests log in more often than the login limit
        limit.start()
        self.addCleanup(limit.stop)
        self.addCleanup(self.uploads.cleanup)

    def _account(self, tag):
        """An account with every personal field set, a password, a Google identity and an uploaded picture."""
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
        user.add_role("viewer", self.genebanks[0].id)
        with open(self._picture(tag), "wb") as picture:
            picture.write(b"jpeg")
        _written_by(f"anvandare{tag}")
        return db.User.get_by_id(user.id)

    def _picture(self, tag):
        return os.path.join(self.uploads.name, "profiler", f"profil{tag}.jpg")

    def _person(self, membership, user, end_date=None, role="huvudmedlem"):
        return db.Member.create(
            membership=membership,
            first_name="Test",
            last_name=f"Person{db.Member.select().count()}",
            email="person@example.invalid",
            role=role,
            end_date=end_date,
            user=user,
        )

    def _assert_emptied(self, user, tag):
        row = db.User.get_by_id(user.id)
        self.assertEqual(
            (row.username, row.fullname, row.email, row.google_email, row.google_name, row.google_picture),
            (None, None, f"raderad-{user.id}", None, None, None),
        )
        self.assertEqual((row.profile_picture, row.is_active, row.privileges), (None, False, []))
        self.assertFalse(db.Authenticators.select().where(db.Authenticators.user == user.id).exists())
        self.assertNotEqual(row.uuid, user.uuid)
        authored = db.DB_PROXY.execute_sql(
            "SELECT count(*), count(ip_address) FROM audit_log WHERE changed_by = %s", (f"raderad-{user.id}",)
        ).fetchone()
        self.assertEqual((authored[0] > 0, authored[1]), (True, 0))  # _written_by's row, pseudonymised, no IP
        self.assertFalse(os.path.exists(self._picture(tag)))
        for value in (
            f"anvandare{tag}",
            f"konto{tag}@example.invalid",
            f"Namn{tag}",
            f"google{tag}@example.invalid",
            f"Googlenamn{tag}",
            f"bild{tag}.jpg",
            f"profil{tag}.jpg",
        ):
            self.assertEqual(_audit_mentions(value), 0, value)
        # no way in: password, Google, or a session the account already had
        self.assertEqual(da.authenticate_user(f"anvandare{tag}", "losen"), (None, None))
        self.assertEqual(da.authenticate_user(f"konto{tag}@example.invalid", "losen"), (None, None))
        self.assertIsNone(da.authenticate_with_credentials("google", f"sub-{tag}"))
        self.assertIsNone(da.fetch_user_info(row.uuid))

    def test_manual_anonymization_empties_the_account(self):
        user = self._account("a")
        membership = db.Membership.create(member_number=301, membership_status="active")
        person = self._person(membership, user)

        matrikel.anonymize_person(person, self.admin)

        self._assert_emptied(user, "a")
        self.assertIsNone(db.Member.get_by_id(person.id).user_id)

    def test_an_earlier_address_written_by_the_account_goes_too(self):
        user = self._account("b")
        db.User.update(email="ny-b@example.invalid").where(db.User.id == user.id).execute()  # audited, with the old one
        _written_by("kontob@example.invalid")  # written while the account had that address
        # an address the account had once and another account holds now: that account's rows keep their author
        other = da.register_user("upptagen@example.invalid", "losen")
        _written_by("upptagen@example.invalid")
        db.DB_PROXY.execute_sql(
            """
            INSERT INTO audit_log (table_name, record_id, operation, old_data, new_data)
            VALUES ('hbuser', %s, 'UPDATE', jsonb_build_object('email', 'upptagen@example.invalid'), '{}'::jsonb)
            """,
            (str(user.id),),
        )
        # an address the account had once and another account had before it: those rows may be the other's
        earlier = da.register_user("forre@example.invalid", "losen")
        db.User.update(email="annan@example.invalid").where(db.User.id == earlier.id).execute()  # audited
        _written_by("forre@example.invalid")
        db.DB_PROXY.execute_sql(
            """
            INSERT INTO audit_log (table_name, record_id, operation, old_data, new_data)
            VALUES ('hbuser', %s, 'UPDATE', jsonb_build_object('email', 'forre@example.invalid'), '{}'::jsonb)
            """,
            (str(user.id),),
        )
        person = self._person(db.Membership.create(member_number=302, membership_status="active"), user)

        matrikel.anonymize_person(person, self.admin)

        self.assertEqual(_audit_mentions("kontob@example.invalid"), 0)
        self.assertEqual(_audit_mentions("ny-b@example.invalid"), 0)
        for kept in ("upptagen@example.invalid", "forre@example.invalid"):
            by_other = db.DB_PROXY.execute_sql("SELECT count(*) FROM audit_log WHERE changed_by = %s", (kept,))
            self.assertEqual(by_other.fetchone()[0], 1, kept)
        self.assertTrue(db.User.get_by_id(other.id).is_active)

    def test_an_account_with_a_role_stops_the_anonymization(self):
        for number, level in enumerate(("admin", "matrikel_admin", "manager"), start=310):
            with self.subTest(level=level):
                tag = f"r{number}"
                user = self._account(tag)
                user.add_role(level, self.genebanks[0].id if level == "manager" else None)
                person = self._person(db.Membership.create(member_number=number, membership_status="active"), user)
                with self.assertRaises(matrikel.LinkError) as refused:
                    matrikel.anonymize_person(person, self.admin)
                self.assertEqual(refused.exception.status, 409)
                self.assertFalse(matrikel.is_anonymized(db.Member.get_by_id(person.id)))
                row = db.User.get_by_id(user.id)
                self.assertEqual((row.username, row.is_active), (f"anvandare{tag}", True))
                self.assertEqual(db.Member.get_by_id(person.id).user_id, user.id)
                self.assertTrue(os.path.exists(self._picture(tag)))
                self.assertGreater(_audit_mentions(f"anvandare{tag}"), 0)

    def test_the_endpoint_answers_409_for_an_account_with_a_role(self):
        user = self._account("e")
        user.add_role("matrikel_admin")
        person = self._person(db.Membership.create(member_number=320, membership_status="active"), user)
        client = APP.test_client(use_cookies=True)
        client.post("/api/login", json={"username": "admin", "password": "pass"})
        response = client.post(f"/api/v2/persons/{person.id}/anonymize")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["detail"], "Ta bort kontots roller innan personen anonymiseras")

    def test_a_helper_role_and_owner_entries_go_with_the_account(self):
        user = self._account("h")
        user.add_role("helper", self.genebanks[0].id)
        user.add_role("owner", self.herds[0].id)
        person = self._person(db.Membership.create(member_number=330, membership_status="active"), user)

        matrikel.anonymize_person(person, self.admin)

        self._assert_emptied(user, "h")

    def test_the_nightly_job_empties_every_account_of_the_household(self):
        main_account, family_account = self._account("n1"), self._account("n2")
        ended = db.Membership.create(member_number=340, membership_status="inactive")
        self._person(ended, main_account, OLD)
        self._person(ended, family_account, OLD, role="familjemedlem")

        def after_the_commit(name):
            self.assertFalse(db.DB_PROXY.in_transaction())
            da.remove_profile_picture(name)

        with mock.patch.object(matrikel, "remove_profile_picture", side_effect=after_the_commit) as remove:
            self.assertEqual(matrikel.anonymize_ended_persons(NOW), (2, 0, []))
        self.assertEqual(sorted(c.args[0] for c in remove.call_args_list), ["profiln1.jpg", "profiln2.jpg"])

        self._assert_emptied(main_account, "n1")
        self._assert_emptied(family_account, "n2")

    def test_a_failed_household_keeps_its_accounts_and_pictures(self):
        main_account, family_account = self._account("f1"), self._account("f2")
        ended = db.Membership.create(member_number=350, membership_status="inactive")
        first = self._person(ended, main_account, OLD)
        self._person(ended, family_account, OLD, role="familjemedlem")
        real = matrikel.anonymize_person

        def second_fails(person, actor, **deferred):
            if person.id != first.id:
                raise RuntimeError("lock timeout")
            return real(person, actor, **deferred)

        with mock.patch.object(matrikel, "anonymize_person", side_effect=second_fails):
            with self.assertLogs(matrikel.logger, "ERROR"):
                self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, 1, []))

        row = db.User.get_by_id(main_account.id)
        self.assertEqual((row.username, row.is_active), ("anvandaref1", True))
        self.assertTrue(os.path.exists(self._picture("f1")))
        self.assertGreater(_audit_mentions("anvandaref1"), 0)  # not purged

    def test_a_session_from_before_stays_ended_if_the_account_is_activated_again(self):
        user = self._account("s")
        client = APP.test_client(use_cookies=True)
        client.post("/api/login", json={"username": "anvandares", "password": "losen"})
        self.assertEqual(client.get("/api/user").status_code, 200)
        matrikel.anonymize_person(self._person(db.Membership.create(member_number=360), user), self.admin)
        db.User.update(is_active=True).where(db.User.id == user.id).execute()
        self.assertEqual(client.get("/api/user").status_code, 401)

    def test_a_profile_upload_racing_the_erasure_writes_nothing_back(self):
        user = self._account("p")
        person = self._person(db.Membership.create(member_number=370), user)
        client = APP.test_client(use_cookies=True)
        client.post("/api/login", json={"username": "anvandarep", "password": "losen"})
        real_fetch = da.fetch_user_info

        def fetch_then_erase(uid):
            row = real_fetch(uid)
            if any(f.function == "user_profile" for f in inspect.stack(0)):  # the view's own read, then the erasure
                matrikel.anonymize_person(person, self.admin)
            return row

        with mock.patch.object(da, "fetch_user_info", side_effect=fetch_then_erase):
            resp = client.patch(
                "/api/profile",
                data={"profile_picture": (io.BytesIO(b"jpeg"), "ny.jpg")},
                content_type="multipart/form-data",
            )
        self.assertEqual(resp.status_code, 404, resp.get_json())
        self.assertIsNone(db.User.get_by_id(user.id).profile_picture)
        self.assertEqual(os.listdir(os.path.join(self.uploads.name, "profiler")), [])
        self._assert_emptied(user, "p")

    def test_the_nightly_job_waits_for_an_undo_instead_of_deadlocking(self):
        """The second account's command row is purged before the first DROP RULE locks audit_log."""
        first, second = self._account("u1"), self._account("u2")
        ended = db.Membership.create(member_number=380, membership_status="inactive")
        self._person(ended, first, OLD)
        self._person(ended, second, OLD, role="familjemedlem")
        entry = db.IndividualCommand.create(
            operation_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
            command="EditDescription",
            individual=self.individuals[0],
            actor=second,
            reason="fritext",
        )
        locked, errors = threading.Event(), []

        def undo_shape():  # an Undo: holds the entry, then writes an audited table, then commits
            try:
                with db.DB_PROXY.atomic():
                    db.IndividualCommand.select().where(db.IndividualCommand.id == entry.id).for_update().get()
                    locked.set()
                    time.sleep(1)
                    db.Herd.update(herd_name="Ny").where(db.Herd.id == self.herds[1].id).execute()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                errors.append(repr(exc))
            finally:
                db.DB_PROXY.close()

        undoer = threading.Thread(target=undo_shape)
        undoer.start()
        self.assertTrue(locked.wait(10))
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (2, 0, []))
        undoer.join(15)
        self.assertEqual(errors, [])
        self.assertIsNone(db.IndividualCommand.get_by_id(entry.id).reason)

    def test_the_endpoint_answers_503_when_audit_log_stays_locked(self):
        user = self._account("l")
        person = self._person(db.Membership.create(member_number=390), user)

        class LockNotAvailable(Exception):
            pgcode = "55P03"

        def locked(*_args, **_kwargs):
            raise peewee.OperationalError("lock timeout") from LockNotAvailable()

        client = APP.test_client(use_cookies=True)
        client.post("/api/login", json={"username": "admin", "password": "pass"})
        with mock.patch.object(da, "purge_command_free_text", side_effect=locked):
            response = client.post(f"/api/v2/persons/{person.id}/anonymize")
        self.assertEqual(response.status_code, 503, response.get_json())
        self.assertFalse(matrikel.is_anonymized(db.Member.get_by_id(person.id)))  # all of it rolled back
        self.assertEqual(db.User.get_by_id(user.id).username, "anvandarel")

    def test_the_mail_queue_forgets_the_account(self):
        user = self._account("m")
        sent = mail.enqueue_mail("notis.sammandrag", "user", user.id, {})
        db.MailMessage.update(status="sent", address_hash="hash").where(db.MailMessage.id == sent).execute()
        queued = mail.enqueue_mail("notis.sammandrag", "user", user.id, {})
        matrikel.anonymize_person(self._person(db.Membership.create(member_number=440), user), self.admin)
        self.assertIsNone(db.MailMessage.get_by_id(sent).address_hash)
        self.assertEqual(db.MailMessage.get_by_id(queued).status, "cancelled")

    def test_an_open_edit_form_cannot_write_the_account_back(self):
        user = self._account("f")
        stale = db.User.get_by_id(user.id)  # what the admin's open form shows
        matrikel.anonymize_person(self._person(db.Membership.create(member_number=400), user), self.admin)
        result = da.update_user(
            {
                "id": user.id,
                "email": stale.email,
                "username": stale.username,
                "fullname": stale.fullname,
                "validated": True,
            },
            self.admin.uuid,
        )
        self.assertEqual(result, {"status": "error", "message": "unknown user"})
        with self.assertRaises(ValueError):
            da.edit_admin_user(user.id, {"fullname": stale.fullname, "email": stale.email})
        self._assert_emptied(user, "f")

    def test_a_stale_read_before_the_erasure_cannot_write_the_account_back(self):
        user = self._account("g")
        stale = db.User.get_by_id(user.id)
        person = self._person(db.Membership.create(member_number=410), user)
        real_get = db.User.get_by_id

        def get_then_erase(user_id):
            row = real_get(user_id)
            if user_id == user.id:
                matrikel.anonymize_person(person, self.admin)
            return row

        with mock.patch.object(da.User, "get_by_id", side_effect=get_then_erase):
            result = da.update_user(
                {"id": user.id, "email": "ny-g@example.invalid", "validated": True}, self.admin.uuid
            )
        self.assertEqual(result, {"status": "error", "message": "unknown user"})
        self.assertEqual(db.User.get_by_id(user.id).email, f"raderad-{user.id}")
        self.assertNotEqual(stale.email, f"raderad-{user.id}")

    def test_earlier_profile_pictures_go_too(self):
        user = self._account("o")
        earlier = os.path.join(self.uploads.name, "profiler", "tidigareo.jpg")
        with open(earlier, "wb") as picture:
            picture.write(b"jpeg")
        db.User.update(profile_picture="tidigareo.jpg").where(db.User.id == user.id).execute()  # audited
        db.User.update(profile_picture="profilo.jpg").where(db.User.id == user.id).execute()  # replaced, kept on disk
        matrikel.anonymize_person(self._person(db.Membership.create(member_number=420), user), self.admin)
        self.assertEqual(os.listdir(os.path.join(self.uploads.name, "profiler")), [])
        self._assert_emptied(user, "o")

    def test_an_upload_after_the_erasure_leaves_no_file(self):
        user = self._account("x")
        client = APP.test_client(use_cookies=True)
        client.post("/api/login", json={"username": "anvandarex", "password": "losen"})
        matrikel.anonymize_person(self._person(db.Membership.create(member_number=430), user), self.admin)
        client.patch(
            "/api/profile",
            data={"profile_picture": (io.BytesIO(b"jpeg"), "ny.jpg")},
            content_type="multipart/form-data",
        )
        self.assertEqual(os.listdir(os.path.join(self.uploads.name, "profiler")), [])

    def test_no_password_reset_and_no_activation_after_the_erasure(self):
        user = self._account("w")
        matrikel.anonymize_person(self._person(db.Membership.create(member_number=450), user), self.admin)
        self.assertFalse(da.change_password(self.admin, user.id, {"newpassword": "nytt-losen"}))
        with self.assertRaises(da.ValidationError):
            da.set_account_active(user.id, True, actor_user_id=self.admin.id)
        self._assert_emptied(user, "w")

    def test_a_reset_waiting_for_the_erasure_creates_no_password(self):
        user = self._account("v")
        person = self._person(db.Membership.create(member_number=460), user)
        locked, results = threading.Event(), []

        def reset_when_locked():
            try:
                self.assertTrue(locked.wait(10))
                results.append(da.change_password(self.admin, user.id, {"newpassword": "nytt-losen"}))
            finally:
                db.DB_PROXY.close()

        real_erase = matrikel.erase_account

        def erase_then_pause(account):  # the account's row is locked from here to the commit
            real_erase(account)
            locked.set()
            time.sleep(1)

        resetter = threading.Thread(target=reset_when_locked)
        resetter.start()
        with mock.patch.object(matrikel, "erase_account", side_effect=erase_then_pause):
            matrikel.anonymize_person(person, self.admin)
        resetter.join(15)
        self.assertEqual(results, [None])
        self._assert_emptied(user, "v")

    def test_a_current_address_another_account_had_keeps_that_accounts_rows(self):
        user = self._account("c")
        other = da.register_user("forst-c@example.invalid", "losen")
        _written_by("kontoc@example.invalid")  # written by the other account while it had the address
        db.DB_PROXY.execute_sql(
            """
            INSERT INTO audit_log (table_name, record_id, operation, old_data, new_data)
            VALUES ('hbuser', %s, 'UPDATE', jsonb_build_object('email', 'kontoc@example.invalid'), '{}'::jsonb)
            """,
            (str(other.id),),
        )
        with self.assertLogs(da.logger, "WARNING"):
            matrikel.anonymize_person(self._person(db.Membership.create(member_number=470), user), self.admin)
        kept = db.DB_PROXY.execute_sql(
            "SELECT count(*) FROM audit_log WHERE changed_by = %s", ("kontoc@example.invalid",)
        ).fetchone()[0]
        self.assertEqual(kept, 1)  # written under the address: it may be the other account's
        row = db.User.get_by_id(user.id)
        self.assertEqual((row.email, row.username), (f"raderad-{user.id}", None))

    def test_a_failed_upload_leaves_no_partial_file(self):
        self._account("y")
        client = APP.test_client(use_cookies=True)
        client.post("/api/login", json={"username": "anvandarey", "password": "losen"})

        def write_then_fail(self_, dst, *args, **kwargs):
            with open(dst, "wb") as partial:
                partial.write(b"jp")
            raise OSError("disk full")

        with mock.patch("werkzeug.datastructures.FileStorage.save", write_then_fail):
            client.patch(
                "/api/profile",
                data={"profile_picture": (io.BytesIO(b"jpeg"), "ny.jpg")},
                content_type="multipart/form-data",
            )
        self.assertEqual(sorted(os.listdir(os.path.join(self.uploads.name, "profiler"))), ["profily.jpg"])
