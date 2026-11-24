"""First sign-in through the public code and account creation routes, with a synthetic member and a stub CMS."""

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
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
RULE_TEXT = "Kontoregler\n\nAnvänd bara ditt eget testkonto."
RULES = {"accepted": True, "rules_version": "23", "rules_sha256": sha256(RULE_TEXT.encode()).hexdigest()}


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
        self.cms.return_value.json.return_value = {"version": "23", "text": RULE_TEXT}
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

    def test_created_account_and_login_are_recorded_in_the_auth_log(self):
        self.pending()
        with self.assertLogs("herdbook.auth", level="INFO") as logged:
            self.assertEqual(self.create().status_code, 200)
        user_id = db.Member.get_by_id(self.member.id).user_id
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            [f"Account created: kod, user id={user_id}", f"Login ok: kod, user id={user_id}"],
        )

    def test_republished_text_shares_its_first_snapshot_and_changed_text_gets_a_new_one(self):
        def accept(version, text):
            self.member = _mk_person(_mk_membership(), "Test", "Member", f"member-{version}@example.org")
            self.cms.return_value.json.return_value = {"version": version, "text": text}
            client = self.pending(APP.test_client())
            digest = sha256(text.encode()).hexdigest()
            response = self.create({**RULES, "rules_version": version, "rules_sha256": digest}, client)
            self.assertEqual(response.status_code, 200, response.data)
            user = db.Member.get_by_id(self.member.id).user
            self.assertEqual((user.rules_version, user.rules_sha256, user.rules_snapshot.text), (version, digest, text))
            return user

        first = accept("23", RULE_TEXT)
        second = accept("24", RULE_TEXT)
        self.assertEqual(db.AccountRulesSnapshot.select().count(), 1)
        self.assertEqual(second.rules_snapshot.first_accepted_at, first.rules_accepted_at)
        self.assertEqual(second.rules_snapshot.cms_version, "23")

        third = accept("25", RULE_TEXT + " Nya regler.")
        self.assertEqual(db.AccountRulesSnapshot.select().count(), 2)
        self.assertEqual(third.rules_snapshot.first_accepted_at, third.rules_accepted_at)
        self.assertEqual(third.rules_snapshot.cms_version, "25")

    def test_account_still_has_the_exact_text_after_the_cms_page_is_deleted(self):
        self.pending()
        self.assertEqual(self.create().status_code, 200)
        self.cms.return_value.status_code = 404
        self.assertIsNone(login_account.published_rules())
        self.assertEqual(db.AccountRulesSnapshot.update(text="Ersatt").execute(), 0)
        self.assertEqual(db.AccountRulesSnapshot.delete().execute(), 0)
        user = db.Member.get_by_id(self.member.id).user
        self.assertEqual(user.rules_snapshot.text, RULE_TEXT)

    def test_changed_text_with_the_same_revision_requires_a_new_acceptance(self):
        self.pending()
        self.cms.return_value.json.return_value = {"version": "23", "text": RULE_TEXT + " Ny regel."}
        self.assertEqual(self.create().status_code, 412)
        self.assert_no_account()
        self.assertFalse(db.AccountRulesSnapshot.select().exists())

    def test_the_same_text_under_a_new_revision_is_still_accepted(self):
        self.pending()
        self.cms.return_value.json.return_value = {"version": "24", "text": RULE_TEXT}
        self.assertEqual(self.create().status_code, 200)
        user = db.Member.get_by_id(self.member.id).user
        self.assertEqual((user.rules_version, user.rules_snapshot.text), ("24", RULE_TEXT))

    def test_failed_account_link_rolls_back_the_snapshot(self):
        self.pending()
        with mock.patch.object(matrikel, "link_member_user", side_effect=matrikel.LinkError("test", "test")):
            self.assertEqual(self.create().status_code, 401)
        self.assert_no_account()
        self.assertFalse(db.AccountRulesSnapshot.select().exists())

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

    def test_previous_address_can_verify_but_cannot_create_an_account_without_a_current_address(self):
        matrikel.set_member_email(self.member, None, self.viewer, by="other")
        self.pending()
        self.assertEqual(self.create().status_code, 401)
        self.assert_no_account()

    def test_previous_address_can_verify_but_the_account_gets_the_current_address(self):
        matrikel.set_member_email(self.member, "current@example.org", self.viewer, by="other")
        self.pending()
        self.assertEqual(self.create().status_code, 200)
        self.assertEqual(db.Member.get_by_id(self.member.id).user.email, "current@example.org")

    def test_contact_used_by_another_linked_account_refuses_creation(self):
        _mk_person(_mk_membership(), "Test", "Other", "other@example.org", user=self.viewer)
        db.User.update(email=f" {self.member.email.upper()} ").where(db.User.id == self.viewer.id).execute()
        self.pending()
        self.assertEqual(self.create().status_code, 409)
        self.assert_no_account()

    def test_contact_previously_set_by_an_owner_refuses_creation(self):
        _mk_person(_mk_membership(), "Test", "Owner", "owner@example.org", user=self.owner)
        result = data_access.update_user(
            {"id": self.owner.id, "email": self.member.email, "validated": False}, self.owner.uuid
        )
        self.assertEqual(result["status"], "updated")
        self.pending()
        self.assertEqual(self.create().status_code, 409)
        self.assert_no_account()

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

    def test_code_login_closing_after_verification_prevents_account_creation(self):
        self.pending()
        db.LoginCode.update(failed=login_code.WRONG_AN_HOUR).where(db.LoginCode.member == self.member.id).execute()
        self.assertEqual(self.create().status_code, 503)
        self.assert_no_account()

    def test_mass_logout_while_fetching_rules_invalidates_pending_proof(self):
        self.pending()
        with self.client.session_transaction() as proof:
            self.assertEqual(proof["logout_epoch"], data_access.logout_epoch())

        def rotate(*args, **kwargs):
            data_access.session_redis.incr(data_access.LOGOUT_EPOCH_KEY)
            self.addCleanup(data_access.session_redis.decr, data_access.LOGOUT_EPOCH_KEY)
            return self.cms.return_value

        self.cms.side_effect = rotate
        self.assertEqual(self.create().status_code, 401)
        self.assert_no_account()

    def test_mass_logout_after_creation_cannot_refresh_the_verified_epoch(self):
        self.pending()
        establish = APP.extensions["establish_session"]

        def rotate(*args, **kwargs):
            data_access.session_redis.incr(data_access.LOGOUT_EPOCH_KEY)
            self.addCleanup(data_access.session_redis.decr, data_access.LOGOUT_EPOCH_KEY)
            return establish(*args, **kwargs)

        with mock.patch.dict(APP.extensions, establish_session=rotate):
            self.assertEqual(self.create().status_code, 200)
        self.assertEqual(self.client.get("/api/user").status_code, 401)

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

    def test_an_erased_account_cannot_be_created_again_by_code(self):
        self.pending()
        other_browser = self.pending(APP.test_client())
        self.assertEqual(self.create().status_code, 200)
        user = db.Member.get_by_id(self.member.id).user

        matrikel.anonymize_person(self.member, self.admin)

        self.assertEqual(self.create(client=other_browser).status_code, 401)
        response = other_browser.post(BASE + "/kod", json={"email": self.member.email})
        self.assertEqual(response.status_code, 200)
        response.close()  # issuing the code runs after the response
        self.assertFalse(db.LoginCode.select().where(db.LoginCode.member == self.member.id).exists())
        self.assertIsNone(db.Member.get_by_id(self.member.id).user_id)
        self.assertEqual(db.User.select().count(), self.initial_count + 1)
        erased = db.User.get_by_id(user.id)
        self.assertEqual((erased.is_active, erased.email), (False, f"raderad-{user.id}"))
        self.assertEqual(
            (erased.rules_accepted_at, erased.rules_version, erased.rules_sha256),
            (user.rules_accepted_at, RULES["rules_version"], RULES["rules_sha256"]),
        )

    def test_explicit_acceptance_and_matching_published_rules_are_required(self):
        self.pending()
        for body in ({}, {**RULES, "accepted": 1}, {"accepted": True}, {"accepted": True, "rules_version": "23"}):
            self.assertEqual(self.create(body).status_code, 400)
        self.cms.assert_not_called()
        self.assertEqual(self.create({**RULES, "rules_sha256": "0" * 64}).status_code, 412)
        for bad in (
            {},
            {"version": None},
            [],
            {"version": "", "text": RULE_TEXT},
            {"version": "23"},
            {"version": "23", "text": " "},
        ):
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

    def test_registrations_and_account_edits_wait_for_the_same_address(self):
        def register(path):
            address = f" {self.member.email.upper()} "
            if path == "manual":
                result = data_access.add_user({"email": address, "password": "test"}, self.admin.uuid)
                return result["status"] == "created"
            if path == "edit":
                result = data_access.update_user(
                    {"id": self.viewer.id, "email": address, "validated": False}, self.viewer.uuid
                )
                self.assertEqual(result, {"status": "error", "message": "email already in use"})
                return False
            try:
                if path == "google":
                    data_access.register_user(address.strip(), None, adopt_existing=False)
                elif path == "admin-edit":
                    data_access.edit_admin_user(self.viewer.id, {"email": address})
                else:
                    login_account.create_pending_account("23", RULES["rules_sha256"])
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

        for first, second in [*permutations(("code", "manual", "google"), 2), ("code", "edit"), ("code", "admin-edit")]:
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
