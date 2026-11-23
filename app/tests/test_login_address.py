"""
One address, one person: every write that can make an address a login address reserves it under a lock on the
address (utils.login_code.reserve_login_address). The matrikel admin and the approver of an application get 409 on an
address another person holds, also as a previous address that still counts; the member herself never sees it.
Synthetic data only.

isort:skip_file
"""

import json
import threading
from datetime import datetime, timedelta, timezone

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.login_code as lc  # noqa: E402
from cli.members import members_cli  # noqa: E402
from click.testing import CliRunner
from flask.cli import ScriptInfo
from herdbook import APP  # noqa: E402

from tests.test_member_api import MatrikelApiTest, _mk_membership, _mk_person  # noqa: E402

TAKEN = "upptagen@example.org"


class LoginAddressTest(MatrikelApiTest):
    def setUp(self):
        super().setUp()
        self.holder = _mk_person(_mk_membership(number=10), "Hanna", "Holder", "Upptagen@Example.org ")

    def reserve(self, address, person_id):
        with db.DB_PROXY.atomic():
            lc.reserve_login_address(address, person_id)

    def post(self, url, body=None):
        return self.client.post(url, data=json.dumps(body or {}), content_type="application/json")


class TestReserve(LoginAddressTest):
    def test_a_main_members_address_is_hers_in_any_case(self):
        other = _mk_person(_mk_membership(number=11), "Bo", "Other", None)
        with self.assertRaises(lc.AddressTaken):
            self.reserve(f" {TAKEN.upper()}", other.id)
        self.reserve(TAKEN, self.holder.id)  # her own

    def test_a_person_with_an_account_holds_her_address(self):
        user = da.register_user("kontot@example.org", "pass", username="kontot")
        _mk_person(self.holder.membership, "Kim", "Holder", "familj@example.org", role="familjemedlem", user=user)
        with self.assertRaises(lc.AddressTaken):
            self.reserve("familj@example.org", self.holder.id)

    def test_a_family_member_without_account_or_an_ended_person_holds_nothing(self):
        _mk_person(self.holder.membership, "Kim", "Holder", "familj@example.org", role="familjemedlem")
        _mk_person(_mk_membership(number=12), "Eva", "Ended", "slutad@example.org", end_date=datetime.now().date())
        self.reserve("familj@example.org", self.holder.id)
        self.reserve("slutad@example.org", self.holder.id)

    def test_a_previous_address_counts_while_it_counts_for_login(self):
        now = datetime.now(timezone.utc)
        previous = db.MemberPreviousAddress.create(
            member=self.holder, address="Tidigare@example.org", login_until=now + timedelta(days=7), purge_at=now
        )
        other = _mk_person(_mk_membership(number=11), "Bo", "Other", None)
        with self.assertRaises(lc.AddressTaken):
            self.reserve("tidigare@example.org", other.id)
        for login_until in (None, now - timedelta(seconds=1)):
            previous.login_until = login_until
            previous.save()
            self.reserve("tidigare@example.org", other.id)

    def test_two_reservations_at_once_give_the_address_to_one(self):
        first = _mk_person(_mk_membership(number=11), "Bo", "First", None)
        second = _mk_person(_mk_membership(number=12), "Cid", "Second", None)
        holding, release, results = threading.Event(), threading.Event(), {}

        def take(person, wait):
            try:
                with db.DB_PROXY.atomic():
                    lc.reserve_login_address("ny@example.org", person.id)
                    db.Member.update(email="ny@example.org").where(db.Member.id == person.id).execute()
                    if wait:
                        holding.set()
                        release.wait(timeout=10)
                results[person.id] = "ok"
            except lc.AddressTaken:
                results[person.id] = "taken"
            finally:
                db.DATABASE.close()

        one = threading.Thread(target=take, args=(first, True))
        one.start()
        self.assertTrue(holding.wait(timeout=10))
        two = threading.Thread(target=take, args=(second, False))
        two.start()
        two.join(timeout=1)
        self.assertTrue(two.is_alive(), "the second reservation did not wait for the lock on the address")
        release.set()
        one.join(timeout=10)
        two.join(timeout=10)
        self.assertEqual(results, {first.id: "ok", second.id: "taken"})


class TestWriters(LoginAddressTest):
    """Each path that makes an address a login address answers 409 for the matrikel admin or the approver."""

    def assert_taken(self, resp):
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.get_json()["title"], lc.AddressTaken.title)

    def test_create_membership(self):
        self.login("matrikel")
        before = db.Membership.select().count()
        self.assert_taken(self.post("/api/v2/memberships", {"first_name": "A", "last_name": "B", "email": TAKEN}))
        self.assertEqual(db.Membership.select().count(), before)

    def test_add_a_main_member(self):
        ms = _mk_membership(number=11)
        self.login("matrikel")
        self.assert_taken(
            self.post(
                f"/api/v2/memberships/{ms.id}/persons",
                {"first_name": "A", "last_name": "B", "email": TAKEN, "role": "huvudmedlem"},
            )
        )
        resp = self.post(f"/api/v2/memberships/{ms.id}/persons", {"first_name": "A", "last_name": "B", "email": TAKEN})
        self.assertEqual(resp.status_code, 201, resp.data)  # a family member without account holds no address

    def test_swap_the_main_member(self):
        ms = _mk_membership(number=11)
        _mk_person(ms, "Old", "Main", "gammal@example.org")
        new = _mk_person(ms, "New", "Main", TAKEN, role="familjemedlem")
        self.login("matrikel")
        self.assert_taken(self.post(f"/api/v2/memberships/{ms.id}/main-member", {"person_id": new.id}))
        self.assertEqual(db.Member.get_by_id(new.id).role, "familjemedlem")

    def test_link_an_account(self):
        person = _mk_person(self.holder.membership, "Kim", "Holder", TAKEN, role="familjemedlem")
        user = da.register_user("kim@example.org", "pass", username="kim")
        self.login("matrikel")
        self.assert_taken(self.post(f"/api/v2/persons/{person.id}/link-user", {"user_id": user.id}))
        self.assertIsNone(db.Member.get_by_id(person.id).user_id)

    def test_approve_an_application(self):
        db.MemberNumberCounter.delete().execute()
        db.MemberNumberCounter.create(value=0)
        application = db.MemberApplication.create(
            first_name="A", last_name="B", email=TAKEN, gdpr_consented_at=datetime.now(), status="pending"
        )
        self.login("man")  # a reviewer
        self.assert_taken(self.post(f"/api/v2/member-applications/{application.id}/approve"))
        self.assertEqual(db.MemberApplication.get_by_id(application.id).status, "pending")
        self.assertEqual(db.MemberNumberCounter.get().value, 0)  # the number went back with the rest

    def test_import(self):
        csv = (
            "G,M,Nr,Namn Efternamn,Adress,Postnummer,Postort,Telefonnr,e-postadress,Bet senast,Noteringar\n"
            f",,20,Anna Andersson,,,,,{TAKEN},,\n"
            ",,21,Bo Berg,,,,,fri@example.org,,\n"
        )
        runner = CliRunner()
        with runner.isolated_filesystem():
            with open("matrikel.csv", "w", encoding="utf-8") as f:
                f.write(csv)
            result = runner.invoke(members_cli, ["import", "matrikel.csv"], obj=ScriptInfo(create_app=lambda: APP))
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn(f"Nr 20: {lc.AddressTaken.title}", result.output)
        self.assertFalse(db.Membership.select().where(db.Membership.member_number == 20).exists())
        self.assertTrue(db.Membership.select().where(db.Membership.member_number == 21).exists())

    def test_a_main_member_adding_a_family_member_never_learns_of_it(self):
        user = da.register_user("main@example.org", "pass", username="mainmember")
        ms = _mk_membership(number=11)
        _mk_person(ms, "Main", "Member", "main@example.org", user=user)
        self.login("mainmember")
        resp = self.post("/api/v2/my-membership/persons", {"first_name": "A", "last_name": "B", "email": TAKEN})
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertFalse(resp.get_json()["duplicate_contact_email"])
