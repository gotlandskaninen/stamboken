"""First sign-in through the public code and account creation routes, with a synthetic member and a stub CMS."""

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from itertools import permutations
from threading import Barrier
from time import monotonic, sleep
from unittest import mock

import requests
from flask import session
from herdbook import APP
from utils import data_access, login_account, login_code, matrikel, settings
from utils import database as db

from tests.test_member_api import MatrikelApiTest, _mk_membership, _mk_person

BASE = "/api/v2/login"
RULES = {"accepted": True, "rules_version": "23"}


class TestLoginAccount(MatrikelApiTest):
    def setUp(self):
        super().setUp()
        for change in (
            mock.patch.dict(os.environ, KODINLOGGNING="true", NEXT_INTERNAL_ORIGIN="https://example.org"),
            mock.patch.multiple(settings.mail, mode="log", link_secret=secrets.token_hex(32)),
            mock.patch.object(settings.service, "demo_instance", False),
        ):
            change.start()
            self.addCleanup(change.stop)
        os.environ.pop("SJALVSKAPAT_KONTO_PROD", None)
        cms = mock.patch.object(login_account.requests, "get")
        self.cms = cms.start()
        self.addCleanup(cms.stop)
        self.cms.return_value.status_code = 200
        self.cms.return_value.json.return_value = {"version": "23"}
        self.member = _mk_person(_mk_membership(), "Test", "Member", "member@example.org")
        db.Herd.update(membership=self.member.membership_id).where(db.Herd.id == self.herds[1].id).execute()
        self.initial_count = db.User.select().count()

    def pending(self, client=None):
        client = client or self.client
        response = client.post(BASE + "/kod", json={"email": self.member.email})
        response.get_data()
        response.close()
        row = db.LoginCode.select().where(db.LoginCode.member == self.member.id).order_by(db.LoginCode.id.desc()).get()
        response = client.post(BASE + "/kod/verifiera", json={"code": login_code.code(row)})
        self.assertEqual(response.status_code, 200, response.data)
        with client.session_transaction() as session:
            self.assertEqual(session["pending_member_id"], self.member.id)
            self.assertNotIn("user_id", session)
        return client

    def create(self, body=RULES, client=None):
        return (client or self.client).post(BASE + "/skapa-konto", json=body)

    def assert_no_account(self):
        self.assertIsNone(db.Member.get_by_id(self.member.id).user_id)
        self.assertEqual(db.User.select().count(), self.initial_count)

    def test_member_gets_her_herd_and_a_fresh_session_after_accepting_the_rules(self):
        with self.client.session_transaction() as session:
            session["earlier"] = True
            old_sid = session.sid
        before = datetime.now(timezone.utc)
        self.pending()
        with self.client.session_transaction() as session:
            pending_sid = session.sid
            self.assertNotEqual(pending_sid, old_sid)
            self.assertNotIn("earlier", session)
            self.assertGreaterEqual(session["pending_until"], (before + timedelta(minutes=15)).timestamp())
            self.assertLessEqual(
                session["pending_until"], (datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()
            )
        self.assertEqual(self.client.get("/api/user").status_code, 401)
        response = self.create()
        self.assertEqual(response.get_json(), {"v2_prod_access": False}, response.data)
        user = db.Member.get_by_id(self.member.id).user
        self.assertEqual((user.fullname, user.email), ("Test Member", self.member.email))
        self.assertEqual(user.effective_herd_ids(), {self.herds[1].id})
        self.assertFalse(user.validated or user.v2_prod_access)
        self.assertEqual(user.privileges, [{"level": "viewer", "genebank": n} for n in (1, 2)])
        self.assertFalse(db.Authenticators.select().where(db.Authenticators.user == user).exists())
        self.assertEqual(user.rules_version, "23")
        self.assertLessEqual(before, user.rules_accepted_at)
        self.assertLessEqual(user.rules_accepted_at, datetime.now(timezone.utc))
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "person_user_linked")
        self.assertEqual(audit.payload["source"], "matrikel_epost")
        self.assertEqual(audit.payload["conveys_herd_ids"], [self.herds[1].id])
        with self.client.session_transaction() as session:
            self.assertNotEqual(session.sid, pending_sid)
            self.assertNotIn("pending_member_id", session)
            self.assertEqual(session["auth_method"], "kod")
            self.assertTrue(data_access.session_holds(session))

    def test_account_linked_after_issue_cannot_be_entered_by_either_credential(self):
        response = self.client.post(BASE + "/kod", json={"email": self.member.email})
        response.get_data()
        response.close()
        row = db.LoginCode.get(db.LoginCode.member == self.member.id)
        self.assertIsNone(row.user_id)
        db.Member.update(user=self.viewer).where(db.Member.id == self.member.id).execute()
        for path, body in (
            ("/lank/uppslag", {"token": login_code.login_link_token(row)}),
            ("/lank", {"token": login_code.login_link_token(row)}),
            ("/kod/verifiera", {"code": login_code.code(row)}),
        ):
            denied = self.client.post(BASE + path, json=body)
            self.assertEqual(denied.status_code, 400)
            self.assertNotIn("name", denied.get_json())
        self.assertIsNone(db.LoginCode.get_by_id(row.id).used_at)
        self.assertEqual(self.client.get("/api/user").status_code, 401)

    def test_production_access_when_enabled(self):
        self.pending()
        with mock.patch.dict(os.environ, SJALVSKAPAT_KONTO_PROD="true"):
            self.assertEqual(self.create().get_json(), {"v2_prod_access": True})
        self.assertTrue(db.Member.get_by_id(self.member.id).user.v2_prod_access)

    def test_previous_address_still_in_its_wait_when_contact_is_empty(self):
        matrikel.set_member_email(self.member, None, self.viewer, by="other")
        self.pending()
        self.assertEqual(self.create().status_code, 200)
        self.assertEqual(db.Member.get_by_id(self.member.id).user.email, self.member.email)

    def test_possible_owner_or_unlinked_email_account_refuses_creation(self):
        self.pending()
        db.Herd.update(membership=self.member.membership_id).where(db.Herd.id == self.herds[0].id).execute()
        self.assertEqual(self.create().status_code, 409)
        db.Herd.update(membership=None).where(db.Herd.id == self.herds[0].id).execute()
        for column in (db.User.email, db.User.google_email):
            with self.subTest(column=column.name):
                db.User.update({column: self.member.email.upper()}).where(db.User.id == self.viewer.id).execute()
                response = self.create()
                self.assertEqual(response.status_code, 409)
                self.assertIn("kontakta matrikelansvarig", response.get_json()["detail"])
                self.assert_no_account()
                db.User.update({column: getattr(self.viewer, column.name)}).where(
                    db.User.id == self.viewer.id
                ).execute()

    def test_pending_expires_after_fifteen_minutes_and_is_bound_to_production(self):
        self.pending()
        with self.client.session_transaction() as session:
            session["pending_demo"] = True
        self.assertEqual(self.create().status_code, 401)
        with self.client.session_transaction() as session:
            session["pending_demo"] = False
            session["pending_until"] = datetime.now(timezone.utc).timestamp()
        self.assertEqual(self.create().status_code, 401)
        self.cms.assert_not_called()
        self.assert_no_account()

    def test_changed_contact_role_or_membership_refuses_the_pending_proof(self):
        self.pending()
        for model, column, value, original, target in (
            (db.Member, db.Member.email, "changed@example.org", self.member.email, self.member.id),
            (db.Member, db.Member.role, "familjemedlem", "huvudmedlem", self.member.id),
            (db.Membership, db.Membership.membership_status, "inactive", "active", self.member.membership_id),
        ):
            with self.subTest(column=column.name):
                model.update({column: value}).where(model.id == target).execute()
                self.assertEqual(self.create().status_code, 401)
                self.assert_no_account()
                model.update({column: original}).where(model.id == target).execute()

    def test_explicit_acceptance_and_matching_published_rules_are_required(self):
        self.pending()
        for body in ({}, {"accepted": 1, "rules_version": "23"}, {"accepted": True}):
            self.assertEqual(self.create(body).status_code, 400)
        self.cms.assert_not_called()
        self.assertEqual(self.create({"accepted": True, "rules_version": "22"}).status_code, 412)
        for bad in ({}, {"version": None}, [], {"version": ""}):
            self.cms.return_value.json.return_value = bad
            self.assertEqual(self.create().status_code, 503)
        self.cms.side_effect = requests.Timeout
        self.assertEqual(self.create().status_code, 503)
        self.assert_no_account()

    def test_two_pending_browsers_create_one_account(self):
        clients = [self.pending(self.client), self.pending(APP.test_client())]
        start = Barrier(2)

        def submit(client):
            try:
                start.wait(timeout=10)
                return self.create(client=client).status_code
            finally:
                db.DB_PROXY.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(submit, clients)), [200, 409])
        self.assertEqual(db.User.select().count(), self.initial_count + 1)

    def test_registration_paths_wait_for_the_same_address_in_either_order(self):
        def register(path):
            address = f" {self.member.email.upper()} "
            if path == "manual":
                result = data_access.add_user({"email": address, "password": "test"}, self.admin.uuid)
                return result["status"] == "created"
            try:
                if path == "google":
                    data_access.register_user(address.strip(), None, adopt_existing=False)
                else:
                    login_account.create_pending_account("23")
                return True
            except (data_access.AddressInUseError, login_account.AccountConflict):
                return False

        def second_registration(path, proof):
            try:
                with APP.test_request_context():
                    session.update(proof)
                    return register(path)
            finally:
                db.DB_PROXY.close()

        for first, second in permutations(("code", "manual", "google"), 2):
            with self.subTest(first=first, second=second):
                address = f"{first}-{second}@example.org"
                self.member = _mk_person(_mk_membership(), "Test", "Member", address)
                self.pending()
                with self.client.session_transaction() as pending:
                    proof = dict(pending)
                with APP.test_request_context(), ThreadPoolExecutor(max_workers=1) as pool:
                    session.update(proof)
                    with db.DB_PROXY.atomic():
                        self.assertTrue(register(first))
                        result = pool.submit(second_registration, second, proof)
                        deadline = monotonic() + 10
                        while monotonic() < deadline:
                            waiting = db.DB_PROXY.execute_sql(
                                "SELECT locktype FROM pg_locks WHERE NOT granted "
                                "AND pg_backend_pid() = ANY(pg_blocking_pids(pid))"
                            ).fetchone()
                            if waiting:
                                self.assertEqual(waiting[0], "advisory")
                                break
                            self.assertFalse(result.done())
                            sleep(0.02)
                        else:
                            self.fail("The competing registration never waited for the address")
                    self.assertFalse(result.result(timeout=10))
                self.assertEqual(db.User.select().where(db.fn.LOWER(db.fn.BTRIM(db.User.email)) == address).count(), 1)

    def test_duplicate_check_waits_for_an_account_address_being_written(self):
        self.pending()

        def submit():
            try:
                return self.create().status_code
            finally:
                db.DB_PROXY.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with db.DB_PROXY.atomic():
                db.User.update(email=self.member.email).where(db.User.id == self.viewer.id).execute()
                result = pool.submit(submit)
                deadline = monotonic() + 10
                while monotonic() < deadline:
                    waiting = db.DB_PROXY.execute_sql(
                        "SELECT 1 FROM pg_locks WHERE relation = 'hbuser'::regclass AND NOT granted "
                        "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
                    ).fetchone()
                    if waiting:
                        break
                    self.assertFalse(result.done(), "Registration did not wait for the uncommitted address")
                    sleep(0.02)
                else:
                    self.fail("Registration never reached the lock")
            self.assertEqual(result.result(timeout=10), 409)
        self.assert_no_account()
