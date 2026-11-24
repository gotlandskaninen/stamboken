"""
One address, one person, and the seven days' wait (utils.matrikel.set_member_email). Every write that can make an
address a login address reserves it under a lock on the address (utils.login_code.reserve_login_address). The
matrikel admin and the approver of an application get 409 on an address another person holds, also as a previous
address that still counts; the member herself never sees it. Synthetic data only.

isort:skip_file
"""

import json
import threading
from datetime import datetime, timedelta, timezone
from unittest import mock

import herdbook  # noqa: E402
import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.login_code as lc  # noqa: E402
import utils.mail as mail  # noqa: E402
import utils.matrikel as matrikel  # noqa: E402
import utils.settings as settings  # noqa: E402
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

    def test_friexemplar_holds_neither_its_current_nor_its_previous_address(self):
        person = _mk_person(_mk_membership(status="friexemplar"), "Fia", "Friblad", "friblad@example.invalid")
        until = datetime.now(timezone.utc) + timedelta(days=7)
        old = "gammalt-friblad@example.invalid"
        db.MemberPreviousAddress.create(member=person, address=old, login_until=until, purge_at=until)
        self.reserve(person.email, self.holder.id)
        self.reserve(old, self.holder.id)

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

    def test_friexemplar_can_use_a_members_address_until_it_changes_status(self):
        address = "kontakt@example.invalid"
        _mk_person(_mk_membership(number=12), "Maj", "Gullblad", address)
        self.login("matrikel")
        resp = self.post(
            "/api/v2/memberships",
            {"first_name": "Liv", "last_name": "Friblad", "membership_status": "friexemplar", "email": address},
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        ms_id = resp.get_json()["id"]
        for route in ("members", "memberships"):
            self.assert_taken(self.client.patch(f"/api/v2/{route}/{ms_id}", json={"membership_status": "active"}))
        self.assertEqual(db.Membership.get_by_id(ms_id).membership_status, "friexemplar")
        self.assertEqual(lc.address_collisions(), 0)

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


WEEK = timedelta(days=7)


class SevenDaysTest(LoginAddressTest):
    """A member with an account and an address, and the helpers to change it."""

    def setUp(self):
        super().setUp()
        self.user = da.register_user("a@example.org", "pass", username="medlemmen")
        self.person = _mk_person(_mk_membership(number=11), "Maja", "Medlem", "a@example.org", user=self.user)
        self.started = datetime.now(timezone.utc)

    def change(self, address, by):
        return matrikel.set_member_email(self.person, address, self.user if by == "self" else self.matrikel_user, by=by)

    def previous(self):
        return {
            r.address: r.login_until
            for r in db.MemberPreviousAddress.select().where(db.MemberPreviousAddress.member == self.person.id)
        }

    def assert_about(self, moment, expected):
        self.assertIsNotNone(moment)
        self.assertLess(abs(moment - (datetime.now(timezone.utc) + expected)), timedelta(minutes=1))

    def besked(self):
        """(previous address, by_self, by_matrikel) of each besked queued, in order."""
        rows = db.MailMessage.select().where(db.MailMessage.kind == "kontakt.epost_besked").order_by(db.MailMessage.id)
        out = []
        for row in rows:
            previous = db.MemberPreviousAddress.get_by_id(row.recipient_id)
            out.append((previous.address, row.params["by_self"], row.params["by_matrikel"]))
        return out


class TestSevenDays(SevenDaysTest):
    """The three rows of the table, the chain A to B to C, back to A, and what goes with every change."""

    def test_the_member_herself(self):
        person = self.change("b@example.org", "self")
        self.assertEqual((person.email, person.email_login_from), ("b@example.org", None))
        (until,) = self.previous().values()
        self.assert_about(until, WEEK)
        self.assertEqual(self.besked(), [("a@example.org", True, False)])

    def test_someone_else(self):
        person = self.change("b@example.org", "other")
        self.assert_about(person.email_login_from, WEEK)
        self.assert_about(self.previous()["a@example.org"], WEEK)
        self.assertEqual(self.besked(), [("a@example.org", False, False)])

    def test_the_matrikel_admin(self):
        person = self.change("b@example.org", "matrikel")
        self.assertEqual((person.email, person.email_login_from), ("b@example.org", None))
        self.assertEqual(self.previous(), {"a@example.org": None})
        self.assertEqual(self.besked(), [("a@example.org", False, True)])

    def test_reactivation_leaves_the_previous_address_with_its_new_holder(self):
        old = self.person.email
        self.change("b@example.org", "self")
        self.assert_about(self.previous()[old], WEEK)
        self.login("matrikel")
        url = f"/api/v2/memberships/{self.person.membership_id}"
        resp = self.client.patch(url, json={"membership_status": "friexemplar"})
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assert_about(self.previous()[old], timedelta(0))

        matrikel.set_member_email(self.holder, old, self.matrikel_user, by="matrikel")
        resp = self.client.patch(url, json={"membership_status": "active"})
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.get_json()["membership_status"], "active")
        self.reserve(old, self.holder.id)  # only the new holder may use it

    def test_reactivating_an_older_friexemplar_drops_its_leftover_previous_address(self):
        old = self.person.email
        self.change("b@example.org", "self")
        # A friexemplar from before this change, with a wait still left on its previous address.
        ms_id = self.person.membership_id
        db.Membership.update(membership_status="friexemplar").where(db.Membership.id == ms_id).execute()
        matrikel.set_member_email(self.holder, old, self.matrikel_user, by="matrikel")
        self.login("matrikel")
        resp = self.client.patch(f"/api/v2/memberships/{ms_id}", json={"membership_status": "active"})
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assert_about(self.previous()[old], timedelta(0))
        self.reserve(old, self.holder.id)  # only the other member holds it

    def test_editing_a_friexemplars_email_expires_a_still_valid_previous_address(self):
        self.change("b@example.org", "self")
        # An existing friexemplar with a wait left over from its active membership.
        ms_id = self.person.membership_id
        db.Membership.update(membership_status="friexemplar").where(db.Membership.id == ms_id).execute()
        self.change("c@example.org", "matrikel")
        self.assert_about(self.previous()["a@example.org"], timedelta(0))

    def test_a_to_b_to_c_never_makes_b_count_and_tells_a_and_b(self):
        """B was the member's own new address; whoever changes it within the wait, A and B both hear of it."""
        self.change("b@example.org", "self")
        self.change("c@example.org", "self")
        previous = self.previous()
        self.assertEqual(sorted(previous), ["a@example.org", "b@example.org"])
        self.assert_about(previous["a@example.org"], WEEK)
        self.assertIsNone(previous["b@example.org"])
        self.assertEqual([b[0] for b in self.besked()], ["a@example.org", "a@example.org", "b@example.org"])
        other = _mk_person(_mk_membership(number=12), "Bo", "Other", None)
        self.reserve("b@example.org", other.id)  # nobody holds b
        with self.assertRaises(lc.AddressTaken):
            self.reserve("a@example.org", other.id)

    def test_back_to_a_ends_the_wait(self):
        self.change("b@example.org", "other")
        person = self.change("A@example.org", "self")
        self.assertEqual((person.email, person.email_login_from), ("A@example.org", None))
        self.assertEqual(self.previous(), {"a@example.org": None, "b@example.org": None})
        self.assertEqual([b[0] for b in self.besked()], ["a@example.org", "b@example.org"])

    def test_after_the_matrikel_admin_an_own_change_does_not_bring_the_old_address_back(self):
        self.change("b@example.org", "matrikel")
        self.change("c@example.org", "self")
        previous = self.previous()
        self.assertIsNone(previous["a@example.org"])
        self.assert_about(previous["b@example.org"], WEEK)
        self.assertEqual([b[0] for b in self.besked()], ["a@example.org", "b@example.org"])

    def test_every_change_ends_the_sessions_and_voids_the_codes(self):
        marks = [da.account_generation(self.user.uuid)]
        with mock.patch.object(settings.mail, "link_secret", "test-link-secret"), db.DB_PROXY.atomic():
            code = lc.issue(self.person, "ny_adress", "webblasare", "b@example.org")
        for address in ("b@example.org", "a@example.org"):  # the intruder's change, and the member's way back
            self.change(address, "self")
            marks.append(da.account_generation(self.user.uuid))
        self.assertEqual(len(set(marks)), 3)
        self.assertIsNotNone(db.LoginCode.get_by_id(code.id).used_at)

    def test_another_persons_address_is_refused_and_nothing_changes(self):
        with self.assertRaises(lc.AddressTaken):
            self.change(TAKEN, "self")
        person = db.Member.get_by_id(self.person.id)
        self.assertEqual(person.email, "a@example.org")
        self.assertEqual((self.previous(), self.besked()), ({}, []))

    def test_a_person_without_a_login_address_just_gets_the_new_one(self):
        family = _mk_person(self.person.membership, "Kim", "Medlem", "kim@example.org", role="familjemedlem")
        person = matrikel.set_member_email(family, TAKEN, self.matrikel_user, by="matrikel")
        self.assertEqual(person.email, TAKEN)
        self.assertFalse(db.MemberPreviousAddress.select().exists())
        self.assertEqual(self.besked(), [])

    def test_erasure_takes_the_previous_addresses(self):
        self.change("b@example.org", "self")
        (mail_id,) = [r.id for r in db.MailMessage.select()]
        matrikel.anonymize_person(db.Member.get_by_id(self.person.id), self.matrikel_user)
        self.assertFalse(db.MemberPreviousAddress.select().exists())
        self.assertEqual(db.MailMessage.get_by_id(mail_id).status, "cancelled")

    def test_erasure_takes_the_codes_and_the_queue_forgets_where_they_went(self):
        with mock.patch.object(settings.mail, "link_secret", "test-link-secret"), db.DB_PROXY.atomic():
            used = lc.issue(self.person, "ny_adress", "w1", "b@example.org")
            live = lc.issue(self.person, "ny_adress", "w2", "c@example.org")
        db.LoginCode.update(used_at=datetime.now(timezone.utc)).where(db.LoginCode.id == used.id).execute()
        sent = mail.enqueue_mail("konto.kod", "login_code", used.id, {"code_id": used.id})
        db.MailMessage.update(status="sent", address_hash="hash").where(db.MailMessage.id == sent).execute()
        queued = mail.enqueue_mail("konto.kod", "login_code", live.id, {"code_id": live.id})

        matrikel.anonymize_person(db.Member.get_by_id(self.person.id), self.matrikel_user)

        self.assertFalse(db.LoginCode.select().where(db.LoginCode.member == self.person.id).exists())
        self.assertIsNone(db.MailMessage.get_by_id(sent).address_hash)
        self.assertEqual(db.MailMessage.get_by_id(queued).status, "cancelled")

    def test_the_matrikel_admins_edit_goes_through_it(self):
        self.login("matrikel")
        resp = self.client.patch(
            f"/api/v2/persons/{self.person.id}",
            data=json.dumps({"email": "b@example.org", "phone": "0701"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self.previous(), {"a@example.org": None})
        self.assertEqual(db.Member.get_by_id(self.person.id).phone, "0701")
        resp = self.client.patch(
            f"/api/v2/persons/{self.person.id}", data=json.dumps({"email": TAKEN}), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.get_json()["title"], lc.AddressTaken.title)
        self.assertEqual(db.Member.get_by_id(self.person.id).email, "b@example.org")

    def test_previous_addresses_go_at_their_purge_time(self):
        self.change("b@example.org", "matrikel")
        (row,) = db.MemberPreviousAddress.select()
        (mail_id,) = [r.id for r in db.MailMessage.select()]
        db.MailMessage.update(status="sent", address_hash="hash").where(db.MailMessage.id == mail_id).execute()
        self.assertEqual(matrikel.purge_previous_addresses(row.purge_at), 0)
        self.assertEqual(matrikel.purge_previous_addresses(row.purge_at + timedelta(seconds=1)), 1)
        self.assertFalse(db.MemberPreviousAddress.select().exists())
        self.assertIsNone(db.MailMessage.get_by_id(mail_id).address_hash)

    def test_an_interrupted_purge_of_previous_addresses_leaves_nothing_half_done(self):
        self.change("b@example.org", "matrikel")
        (row,) = db.MemberPreviousAddress.select()
        later = row.purge_at + timedelta(seconds=1)
        with mock.patch.object(matrikel, "forget_recipient", side_effect=RuntimeError("database gone")):
            with self.assertRaises(RuntimeError):
                matrikel.purge_previous_addresses(later)
        self.assertTrue(db.MemberPreviousAddress.select().exists())
        self.assertEqual(matrikel.purge_previous_addresses(later), 1)


class TestHolderAgain(SevenDaysTest):
    """A person who holds addresses again holds every one that still counts, the previous ones too."""

    def setUp(self):
        super().setUp()
        self.change("b@example.org", "self")  # a@example.org counts for seven more days
        ms = self.person.membership
        self.other_main = _mk_person(ms, "Ny", "Huvudmedlem", "ny-huvud@example.org", role="familjemedlem")
        matrikel.swap_main_member(ms, self.other_main, self.matrikel_user)
        matrikel.unlink_member_user(self.person.id, actor=self.matrikel_user)
        self.taker = _mk_person(_mk_membership(number=12), "Bo", "Tar", None)
        self.reserve("a@example.org", self.taker.id)  # free while she holds nothing
        db.Member.update(email="a@example.org").where(db.Member.id == self.taker.id).execute()

    def test_linking_her_account_again(self):
        with self.assertRaises(matrikel.LinkError) as refused:
            matrikel.link_member_user(self.person.id, self.user.id, actor=self.matrikel_user, mode="admin")
        self.assertEqual(refused.exception.title, lc.AddressTaken.title)
        self.assertIsNone(db.Member.get_by_id(self.person.id).user_id)
        self.assertEqual(lc.address_collisions(), 0)

    def test_making_her_main_member_again(self):
        with self.assertRaises(lc.AddressTaken):
            matrikel.swap_main_member(self.person.membership, self.person, self.matrikel_user)
        self.assertEqual(db.Member.get_by_id(self.person.id).role, "familjemedlem")
        self.assertEqual(lc.address_collisions(), 0)


class TestWaitLocks(SevenDaysTest):
    def test_the_restarted_clock_holds_the_lock_on_the_old_address(self):
        """The old address is about to stop counting. The change that restarts its clock reads it in time; another
        person reserves it as it stops. Without the lock on the old address both end up holding it."""
        self.change("b@example.org", "self")
        db.MemberPreviousAddress.update(login_until=datetime.now(timezone.utc) + timedelta(seconds=1)).execute()
        taker = _mk_person(_mk_membership(number=12), "Bo", "Tar", None)
        paused, release, outcome = threading.Event(), threading.Event(), {}
        original = db.MemberPreviousAddress.save

        def paused_save(row, *args, **kwargs):
            if threading.current_thread().name == "change" and not paused.is_set():
                paused.set()
                assert release.wait(timeout=10), "the test never released the change"
            return original(row, *args, **kwargs)

        def change():
            try:
                self.change("c@example.org", "self")
            finally:
                db.DATABASE.close()

        def take():
            try:
                with db.DB_PROXY.atomic():
                    lc.reserve_login_address("a@example.org", taker.id)
                    db.Member.update(email="a@example.org").where(db.Member.id == taker.id).execute()
                outcome["taker"] = "ok"
            except lc.AddressTaken:
                outcome["taker"] = "taken"
            finally:
                db.DATABASE.close()

        with mock.patch.object(db.MemberPreviousAddress, "save", paused_save):
            changing = threading.Thread(target=change, name="change")
            changing.start()
            self.assertTrue(paused.wait(timeout=10), "the change never reached the restart of the clock")
            while datetime.now(timezone.utc) <= db.MemberPreviousAddress.get().login_until:
                threading.Event().wait(0.1)
            taking = threading.Thread(target=take)
            taking.start()
            taking.join(timeout=2)
            release.set()
            changing.join(timeout=10)
            taking.join(timeout=10)
        self.assertEqual(outcome, {"taker": "taken"})
        self.assertEqual(lc.address_collisions(), 0)


class TestCollisions(LoginAddressTest):
    """A write that missed the reservation: counted at night and in the status view, never named."""

    def test_two_holders_of_one_address_are_counted_and_alarmed(self):
        self.assertEqual(lc.address_collisions(), 0)
        _mk_person(self.holder.membership, "Kim", "Holder", TAKEN, role="familjemedlem")  # no account: no holder
        self.assertEqual(lc.address_collisions(), 0)
        _mk_person(_mk_membership(number=11), "Bo", "Other", f" {TAKEN.upper()}")
        now = datetime.now(timezone.utc)
        db.MemberPreviousAddress.create(
            member=self.holder, address="b@example.org", login_until=now + timedelta(days=1), purge_at=now
        )
        _mk_person(_mk_membership(number=12), "Cid", "Third", "b@example.org")
        self.assertEqual(lc.address_collisions(), 2)
        alarm = [a for a in mail.sender_alarms()["alarms"] if a["code"] == "adresskrock"]
        self.assertEqual(
            alarm, [{"code": "adresskrock", "message": "2 inloggningsadresser hör till fler än en person"}]
        )

    def test_an_empty_string_is_no_address(self):
        _mk_person(_mk_membership(number=11), "Bo", "Tom", "")
        _mk_person(_mk_membership(number=12), "Cid", "Tom", "  ")
        now = datetime.now(timezone.utc)
        later = now + timedelta(days=1)
        db.MemberPreviousAddress.create(member=self.holder, address="", login_until=later, purge_at=now)
        self.assertEqual(lc.address_collisions(), 0)

    def test_the_nightly_job_logs_the_count_only(self):
        _mk_person(_mk_membership(number=11), "Bo", "Other", TAKEN)
        with (
            mock.patch.object(herdbook, "purge_command_free_text", return_value=0),
            mock.patch.object(herdbook.genetics.ps, "_close_db_connection"),
            self.assertLogs(herdbook.APP.logger, "WARNING") as logs,
        ):
            herdbook._purge_command_free_text()
        self.assertIn("1 login addresses are held by more than one person", "\n".join(logs.output))
        self.assertNotIn("example.org", "\n".join(logs.output))
