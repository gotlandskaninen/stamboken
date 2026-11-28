"""First sign-in through the public code and account creation routes, with a synthetic member and a stub CMS."""

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
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


def test_sqlite_skips_the_postgres_rules_for_snapshots():
    with db.SqliteDatabase(":memory:") as sqlite, mock.patch.object(db, "DATABASE", sqlite):
        db._lock_account_rules_snapshots()


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

    def pending(self, client=None, person=None):
        client, person = client or self.client, person or self.member
        response = client.post(BASE + "/kod", json={"email": person.email})
        response.get_data()
        response.close()
        row = db.LoginCode.select().where(db.LoginCode.member == person.id).order_by(db.LoginCode.id.desc()).get()
        response = client.post(BASE + "/kod/verifiera", json={"code": login_code.code(row)})
        self.assertEqual(response.status_code, 200, response.data)
        with client.session_transaction() as session:
            self.assertEqual(session["pending_member_id"], person.id)
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

    def test_link_invalidates_the_genebank_only_after_the_account_commits(self):
        self.pending()
        calls = []

        def invalidate(genebank_ids):
            calls.append((list(genebank_ids), db.DB_PROXY.in_transaction()))

        with mock.patch.object(matrikel, "_invalidate_genebanks", side_effect=invalidate):
            with mock.patch.object(data_access, "login_generation", side_effect=RuntimeError("generation unavailable")):
                with self.assertRaisesRegex(RuntimeError, "generation unavailable"):
                    self.create()
            self.assert_no_account()
            self.assertEqual(calls, [])
            self.assertEqual(self.create().status_code, 200)
        self.assertEqual(calls, [([self.herds[1].genebank_id], False)])

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

    def test_pending_membership_allows_its_main_member_to_create_an_account(self):
        db.Membership.update(membership_status="pending").where(db.Membership.id == self.member.membership_id).execute()
        self.pending()
        self.assertEqual(self.create().status_code, 200)

    def test_an_inactive_membership_refuses_every_person_an_account(self):
        family = _mk_person(self.member.membership, "Test", "Family", role="familjemedlem")
        inactive = db.Membership.update(membership_status="inactive")
        inactive.where(db.Membership.id == self.member.membership_id).execute()
        with self.assertRaises(matrikel.LinkError) as refused:
            matrikel.link_member_user(family.id, self.viewer.id, actor=self.viewer, mode="matrikel_epost")
        self.assertEqual(
            refused.exception.detail, "Bara en person i ett aktivt eller väntande medlemskap kan skapa ett konto."
        )

    def test_family_member_or_keeper_creates_an_account_with_her_grants(self):
        """#269: the main member put her in with an address and a grant; the main member's account does not stop it."""
        main_user = data_access.register_user("main@example.org", "pass", username="main")
        matrikel.link_member_user(self.member.id, main_user.id, actor=self.admin, mode="admin",
                                  confirmed_herd_ids=[self.herds[1].id])  # fmt: skip
        # an older owner role on the herd, as legacy stored it: the linked account is not hers
        db.User.update(_privileges=f'[{{"level": "owner", "herd": {self.herds[1].id}}}]').where(
            db.User.id == main_user.id
        ).execute()
        for role in ("familjemedlem", "skotare"):
            with self.subTest(role=role):
                person = _mk_person(self.member.membership, "Test", role.title(), f"{role}@example.org", role=role)
                matrikel.create_grant(person, self.herds[1], None, self.admin)
                client = APP.test_client(use_cookies=True)
                self.pending(client, person)
                self.assertEqual(self.create(client=client).status_code, 200)
                user = db.Member.get_by_id(person.id).user
                self.assertEqual((user.email, user.effective_herd_ids()), (person.email, {self.herds[1].id}))

    def test_a_grant_outside_the_membership_refuses_a_family_member_an_account_by_code(self):
        """The main member vouches for the address; a grant on another membership's herd needs matrikelansvarig."""
        keeper = _mk_person(self.member.membership, "Test", "Keeper", "keeper@example.org", role="skotare")
        matrikel.create_grant(keeper, self.herds[0], None, self.admin)  # a herd outside the membership
        self.pending(person=keeper)
        self.assertEqual(self.create().status_code, 409)
        self.assertIsNone(db.Member.get_by_id(keeper.id).user_id)

    def test_only_an_unlinked_owner_of_a_granted_herd_elsewhere_may_be_the_main_member(self):
        other_membership = _mk_membership()
        herd = db.Herd.create(genebank=self.genebanks[0], herd="G9901", membership=other_membership, is_active=True)
        matrikel.create_grant(self.member, herd, None, self.admin)
        owner_role = f'[{{"level": "owner", "herd": "{herd.id}"}}]'
        linked = data_access.register_user("linked-owner@example.org", "pass", username="linked-owner")
        db.User.update(_privileges=owner_role).where(db.User.id == linked.id).execute()
        other = _mk_person(other_membership, "Other", "Owner", "other@example.org")
        matrikel.link_member_user(other.id, linked.id, actor=self.admin, mode="admin", confirmed_herd_ids=[herd.id])
        self.assertFalse(login_account._existing_account(self.member, self.member.email))
        unlinked = data_access.register_user("old-owner@example.org", "pass", username="old-owner")
        db.User.update(_privileges=owner_role).where(db.User.id == unlinked.id).execute()
        self.assertTrue(login_account._existing_account(self.member, self.member.email))

    def test_a_holder_taking_the_address_after_the_code_refuses_the_family_members_account(self):
        family = _mk_person(self.member.membership, "Test", "Family", "family@example.org", role="familjemedlem")
        self.pending(person=family)
        matrikel.set_member_email(self.member, "family@example.org", self.admin, by="self")
        self.assertEqual(self.create().status_code, 401)
        self.assertIsNone(db.Member.get_by_id(family.id).user_id)

    def test_another_persons_workspace_address_gives_the_family_member_no_code(self):
        family = _mk_person(_mk_membership(), "Test", "Family", "board@gotlandskaninen.se", role="familjemedlem")
        self.assertEqual(login_code.login_holder("board@gotlandskaninen.se").id, family.id)
        db.Member.update(workspace_email="Board@Gotlandskaninen.se").where(db.Member.id == self.member.id).execute()
        self.assertIsNone(login_code.login_holder("board@gotlandskaninen.se"))

    def test_an_accounts_address_gives_the_family_member_no_code(self):
        family = _mk_person(_mk_membership(), "Test", "Family", "anna@gotlandskaninen.se", role="familjemedlem")
        self.assertEqual(login_code.login_holder("anna@gotlandskaninen.se").id, family.id)
        other = data_access.register_user("anna-private@example.org", "pass", username="anna")
        db.User.update(google_email="Anna@Gotlandskaninen.se").where(db.User.id == other.id).execute()
        self.assertIsNone(login_code.login_holder("anna@gotlandskaninen.se"))

    def test_her_own_workspace_account_refuses_a_second_account(self):
        family = _mk_person(self.member.membership, "Test", "Family", "family@example.org", role="familjemedlem")
        self.assertFalse(login_account._existing_account(family, family.email))
        older = data_access.register_user("old@example.org", "pass", username="old")
        db.User.update(google_email="family@gotlandskaninen.se").where(db.User.id == older.id).execute()
        db.Member.update(workspace_email="family@gotlandskaninen.se").where(db.Member.id == family.id).execute()
        self.assertTrue(login_account._existing_account(db.Member.get_by_id(family.id), family.email))

    def test_an_ended_persons_previous_address_does_not_stop_the_family_member(self):
        matrikel.set_member_email(self.member, "ny@example.org", self.admin, by="self")  # the old one counts a week
        family = _mk_person(_mk_membership(), "Test", "Family", "member@example.org", role="familjemedlem")
        self.assertEqual(login_code.login_holder("member@example.org").id, self.member.id)
        db.Member.update(end_date=date.today()).where(db.Member.id == self.member.id).execute()
        self.assertEqual(login_code.login_holder("member@example.org").id, family.id)

    def test_a_shared_address_stays_the_holders_and_gives_the_family_member_no_code(self):
        family = _mk_person(self.member.membership, "Test", "Family", self.member.email.upper(), role="familjemedlem")
        self.assertEqual(login_code.login_holder(self.member.email).id, self.member.id)
        self.pending()
        self.assertEqual(self.create().status_code, 200)
        self.assertFalse(db.LoginCode.select().where(db.LoginCode.member == family.id).exists())

    def test_a_holder_takes_a_family_members_address_and_keeps_a_previous_one(self):
        """The family member holds her address only while nobody else has it, now or as a previous address."""
        family = _mk_person(_mk_membership(), "Test", "Family", "shared@example.org", role="familjemedlem")
        self.assertEqual(login_code.login_holder("shared@example.org").id, family.id)
        _mk_person(_mk_membership(), "Test", "Ended", "ended@example.org", role="familjemedlem", end_date=date.today())
        self.assertIsNone(login_code.login_holder("ended@example.org"))
        matrikel.set_member_email(self.member, "shared@example.org", self.admin, by="self")  # no AddressTaken
        self.assertEqual(login_code.login_holder("shared@example.org").id, self.member.id)
        # The main member's old address still counts for her a while, so it is not the family member's either.
        later = _mk_person(_mk_membership(), "Test", "Later", "member@example.org", role="familjemedlem")
        self.assertEqual(login_code.login_holder("member@example.org").id, self.member.id)
        self.assertNotEqual(login_code.login_holder("member@example.org").id, later.id)

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

    def test_cms_fetch_happens_outside_the_account_transaction(self):
        self.pending()

        def read_rules(*args, **kwargs):
            self.assertFalse(db.DB_PROXY.in_transaction())
            return self.cms.return_value

        self.cms.side_effect = read_rules
        self.assertEqual(self.create().status_code, 200)

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

    def test_changed_contact_or_membership_refuses_the_pending_proof(self):
        self.pending()
        for model, column, value, original, target in (
            (db.Member, db.Member.email, "changed@example.org", self.member.email, self.member.id),
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
