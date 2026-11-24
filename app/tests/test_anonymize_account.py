#!/usr/bin/env python3
"""
Anonymization empties the person's account (#190): no personal data on the hbuser row or in audit_log, no way in.

Only runs on PostgreSQL (audit_log rules and JSONB). Names and addresses are made up; e-mail uses example.invalid.
"""

import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from unittest import mock

import utils.data_access as da
import utils.database as db
import utils.matrikel as matrikel
from herdbook import APP

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
        self.addCleanup(self.uploads.cleanup)

    def _account(self, tag):
        """An account with every personal field set, a password, a Google identity and an uploaded picture."""
        user = da.register_user(f"konto{tag}@example.invalid", "losen", username=f"anvandare{tag}", fullname=f"Namn{tag}")
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
        person = self._person(db.Membership.create(member_number=302, membership_status="active"), user)

        matrikel.anonymize_person(person, self.admin)

        self.assertEqual(_audit_mentions("kontob@example.invalid"), 0)
        self.assertEqual(_audit_mentions("ny-b@example.invalid"), 0)
        by_other = db.DB_PROXY.execute_sql(
            "SELECT count(*) FROM audit_log WHERE changed_by = %s", ("upptagen@example.invalid",)
        ).fetchone()[0]
        self.assertEqual(by_other, 1)
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
