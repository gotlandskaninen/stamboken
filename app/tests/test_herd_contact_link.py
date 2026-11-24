"""link_herd: the first link of a herd to a membership compares its contact with the register (#117, Överflyttning)."""

import threading
import unittest
from collections import Counter
from datetime import date
from unittest.mock import patch

import utils.database as db
import utils.matrikel as matrikel
from cli.members import _link_flag_herds
from utils.herd_contact import herd_contact, link_herd

from tests.database_test import _USE_POSTGRES
from tests.test_herd_contact import ADDRESS, HerdContactTest, _row

STATE = (
    "membership_id",
    "contact_member_id",
    "contact_pending",
    "name",
    "email",
    "mobile_phone",
    "physical_address",
    "name_privacy",
    "email_privacy",
    "mobile_phone_privacy",
    "physical_address_privacy",
)


class LinkTest(HerdContactTest):
    """Anna Exempel (main member, anna@example.invalid, 070-111 11 11) and Ida Exempel (family member) on membership 7,
    address Byvägen 1|62300|Roma. G1 is not linked yet."""

    def _herd(self, herd=None, **columns):
        """Set the herd's contact columns (the others NULL) before the link."""
        herd = herd or self.herd
        values = dict.fromkeys(("name", "email", "mobile_phone", "physical_address"))
        values.update(columns)
        db.Herd.update(**values).where(db.Herd.id == herd.id).execute()
        return herd

    def _state(self, herd=None):
        row = db.Herd.get_by_id((herd or self.herd).id)
        return {column: getattr(row, column) for column in STATE}


class TestLinkHerd(LinkTest):
    def test_link_same_value_becomes_derived_keeps_privacy(self):
        self._herd(
            name="anna  exempel",
            email=" ANNA@example.invalid",
            email_privacy="authenticated",
            mobile_phone="+46 70-111 11 11",
            mobile_phone_privacy="public",
            physical_address="Byvägen 1|623 00|roma",
            physical_address_privacy="authenticated",
        )

        cases = link_herd(self.herd.id, self.membership.id)

        self.assertEqual(cases, {"name": "person", "email": "lika", "mobile_phone": "lika", "physical_address": "lika"})
        state = self._state()
        self.assertEqual((state["membership_id"], state["contact_member_id"]), (self.membership.id, self.main.id))
        self.assertEqual(state["contact_pending"], [])
        # no copies left: every row is read from the register, with the privacy chosen for it
        self.assertEqual([state[f] for f in ("name", "email", "mobile_phone", "physical_address")], [None] * 4)
        self.assertEqual(
            [state[f"{f}_privacy"] for f in ("name", "email", "mobile_phone", "physical_address")],
            ["private", "authenticated", "public", "authenticated"],
        )
        rows = herd_contact(db.Herd.get_by_id(self.herd.id)).rows
        self.assertEqual(rows["email"], _row("anna@example.invalid", "person"))
        self.assertEqual(rows["physical_address"], _row(ADDRESS, "medlemskap"))

    def test_link_different_value_becomes_pending(self):
        self._herd(
            name="Anna Exempel",
            email="gard@example.invalid",
            email_privacy="authenticated",
            mobile_phone="070-999 99 99",
            physical_address="Gårdsvägen 5|62300|Roma",
        )

        cases = link_herd(self.herd.id, self.membership.id)

        self.assertEqual(
            cases, {"name": "person", "email": "olika", "mobile_phone": "olika", "physical_address": "olika"}
        )
        state = self._state()
        self.assertEqual(state["contact_pending"], ["email", "mobile_phone", "physical_address"])
        self.assertEqual(
            (state["email"], state["mobile_phone"], state["physical_address"]),
            ("gard@example.invalid", "070-999 99 99", "Gårdsvägen 5|62300|Roma"),
        )
        self.assertEqual(state["email_privacy"], "authenticated")  # nothing else is shown: the choice stands
        rows = herd_contact(db.Herd.get_by_id(self.herd.id)).rows
        self.assertEqual(rows["email"], _row("gard@example.invalid", "egen", True, "anna@example.invalid"))
        self.assertEqual(rows["physical_address"], _row("Gårdsvägen 5|62300|Roma", "egen", True, ADDRESS))

    def test_link_herd_value_matrikel_empty_stays_own(self):
        """Granskningsfokus 5: a person without e-mail or phone in the register gives an empty fetched row, and the
        herd's value stays an own row without a question. A fritext contact never fetches them either."""
        db.Member.update(email=None, phone="").where(db.Member.id == self.main.id).execute()
        self._herd(name="Anna Exempel", email="gard@example.invalid", mobile_phone="070-999 99 99")

        cases = link_herd(self.herd.id, self.membership.id)

        self.assertEqual((cases["email"], cases["mobile_phone"]), ("bara_besattningen", "bara_besattningen"))
        state = self._state()
        self.assertEqual(state["contact_pending"], [])
        self.assertEqual((state["email"], state["mobile_phone"]), ("gard@example.invalid", "070-999 99 99"))
        self.assertEqual(state["email_privacy"], "authenticated")  # G1's fixture choice

        fritext = self._herd(db.Herd.get_by_id(self.herds[1].id), name="Gårdens Kontakt", email="anna@example.invalid")
        cases = link_herd(fritext.id, self.membership.id)
        self.assertEqual((cases["name"], cases["email"]), ("fritext", "bara_besattningen"))
        self.assertEqual(self._state(fritext)["contact_pending"], ["name"])
        self.assertEqual(self._state(fritext)["email"], "anna@example.invalid")

    def test_link_empty_herd_gets_derived_private(self):
        self._herd(
            name=" ",
            name_privacy="public",
            email="",
            email_privacy="public",
            mobile_phone=None,
            mobile_phone_privacy="authenticated",
            physical_address="  ",
            physical_address_privacy="authenticated",
        )

        cases = link_herd(self.herd.id, self.membership.id)

        self.assertEqual(set(cases.values()), {"bara_matrikeln"})
        state = self._state()
        self.assertEqual(state["contact_member_id"], self.main.id)  # an empty name: the main member
        self.assertEqual(state["contact_pending"], [])
        self.assertEqual((state["name"], state["physical_address"]), (None, None))  # blank is empty
        # decision 4: a value nobody chose to show starts hidden
        self.assertEqual(
            [state[f"{f}_privacy"] for f in ("name", "email", "mobile_phone", "physical_address")], ["private"] * 4
        )
        rows = herd_contact(db.Herd.get_by_id(self.herd.id)).rows
        self.assertEqual(rows["name"], _row("Anna Exempel", "person"))
        self.assertEqual(rows["mobile_phone"], _row("070-111 11 11", "person"))

    def test_link_both_empty_resets_privacy(self):
        db.Member.update(email=None, phone=None).where(db.Member.id == self.main.id).execute()
        db.Membership.update(address=None, postal_code=None, city=None).where(
            db.Membership.id == self.membership.id
        ).execute()
        self._herd(name="Anna Exempel", email_privacy="public", mobile_phone_privacy="authenticated")

        cases = link_herd(self.herd.id, self.membership.id)

        self.assertEqual(
            cases,
            {"name": "person", "email": "bada_tomma", "mobile_phone": "bada_tomma", "physical_address": "bada_tomma"},
        )
        state = self._state()
        self.assertEqual((state["email_privacy"], state["mobile_phone_privacy"]), ("private", "private"))

        # no main member and an empty name: no contact, the name row resets too
        household = db.Membership.create(member_number=9)
        db.Member.create(membership=household, first_name="Ola", last_name="Prov", role="familjemedlem")
        other = self._herd(db.Herd.get_by_id(self.herds[1].id))
        cases = link_herd(other.id, household.id)
        self.assertEqual(cases["name"], "bada_tomma")
        state = self._state(other)
        self.assertEqual((state["contact_member_id"], state["name_privacy"]), (None, "private"))

    def test_link_name_matches_one_person(self):
        self._herd(name="Exempel Ida", email="ida@example.invalid", mobile_phone="070-000 00 00")

        cases = link_herd(self.herd.id, self.membership.id)

        self.assertEqual((cases["name"], cases["email"], cases["mobile_phone"]), ("person", "lika", "olika"))
        state = self._state()
        self.assertEqual((state["contact_member_id"], state["name"]), (self.family.id, None))
        self.assertEqual(state["name_privacy"], "private")  # G1's fixture choice, kept
        self.assertEqual(state["contact_pending"], ["mobile_phone"])

        # also when the membership has no active main member
        db.Member.update(end_date=date.today()).where(db.Member.id == self.main.id).execute()
        other = self._herd(db.Herd.get_by_id(self.herds[1].id), name="Ida Exempel")
        self.assertEqual(link_herd(other.id, self.membership.id)["name"], "person")
        self.assertEqual((self._state(other)["contact_member_id"], self._state(other)["name"]), (self.family.id, None))

    def test_link_ambiguous_name_is_fritext_pending(self):
        for herd, name in ((self.herd, "Anna och Per Exempel"), (db.Herd.get_by_id(self.herds[1].id), "Exempel")):
            with self.subTest(name=name):
                self._herd(herd, name=name, mobile_phone="070-999 99 99")

                cases = link_herd(herd.id, self.membership.id)

                self.assertEqual((cases["name"], cases["mobile_phone"]), ("fritext", "bara_besattningen"))
                state = self._state(herd)
                self.assertEqual((state["contact_member_id"], state["name"]), (None, name))
                self.assertEqual(state["contact_pending"], ["name"])
                contact = herd_contact(db.Herd.get_by_id(herd.id))
                self.assertEqual(contact.mode, "fritext")
                self.assertEqual(contact.rows["name"], _row(name, "egen", True, "Anna Exempel"))

    def test_link_relink_same_membership_is_noop(self):
        self._herd(name="Anna Exempel", mobile_phone="070-999 99 99")
        link_herd(self.herd.id, self.membership.id)
        # the breeder answers "Ja, behåll"
        db.Herd.update(contact_pending=[]).where(db.Herd.id == self.herd.id).execute()
        before = self._state()

        self.assertIsNone(link_herd(self.herd.id, self.membership.id))

        self.assertEqual(self._state(), before)

    def test_link_already_linked_to_other_membership_untouched(self):
        other = db.Membership.create(member_number=8)
        self._herd(name="Anna Exempel", email="anna@example.invalid")
        db.Herd.update(membership=other).where(db.Herd.id == self.herd.id).execute()
        before = self._state()

        self.assertIsNone(link_herd(self.herd.id, self.membership.id))
        self.assertEqual(self._state(), before)

        # the import skips it as today, with a warning (G1 is the herd of number 1)
        report = {"herd_warnings": [], "herd_links": 0, "contact_cases": Counter()}
        _link_flag_herds(1, [{"g": True, "m": False}], self.membership, False, report)
        self.assertEqual(report["herd_warnings"], [f"herd G1 already linked to membership {other.id}"])
        self.assertEqual((report["herd_links"], report["contact_cases"]), (0, Counter()))
        self.assertEqual(self._state(), before)

    def test_link_refuses_a_herd_renumbered_since_the_lookup(self):
        """The import finds the herd by its G/M code before the locks. A herd an admin renumbered meanwhile is not
        linked to the old number's membership: link_herd checks the code on the locked row."""
        self._herd(name="Anna Exempel")
        self.assertIsNone(link_herd(self.herd.id, self.membership.id, herd_code="G7"))  # G1 is not G7
        self.assertIsNone(self._state()["membership_id"])

        real_lookup = db.Herd.get_or_none

        def lookup_then_renumber(*args, **kwargs):
            herd = real_lookup(*args, **kwargs)
            db.Herd.update(herd="G1001").where(db.Herd.id == herd.id).execute()  # the admin, before the lock
            return herd

        report = {"herd_warnings": [], "herd_links": 0, "contact_cases": Counter()}
        with patch.object(db.Herd, "get_or_none", lookup_then_renumber):
            _link_flag_herds(1, [{"g": True, "m": False}], self.membership, False, report)
        self.assertIsNone(self._state()["membership_id"])
        self.assertEqual((report["herd_links"], report["contact_cases"]), (0, Counter()))
        self.assertEqual(report["herd_warnings"], ["herd G1 changed or linked meanwhile — not linked"])

    def test_link_to_a_membership_not_active_leaves_it_uncompared(self):
        """O4: the reads show nothing of a membership that is not active, so the link compares nothing: the herd is
        linked, contact_pending stays NULL and it reads its own columns as before the link."""
        own = {"name": "Anna Exempel", "email": "anna@example.invalid", "mobile_phone": "070-999 99 99"}
        for status in ("inactive", "pending", "friexemplar"):
            with self.subTest(status=status):
                db.Herd.update(membership=None, contact_member=None, contact_pending=None).where(
                    db.Herd.id == self.herd.id
                ).execute()
                self._herd(**own, email_privacy="authenticated")
                self._set_status(status)

                self.assertEqual(link_herd(self.herd.id, self.membership.id), {})

                state = self._state()
                self.assertEqual(
                    (state["membership_id"], state["contact_member_id"], state["contact_pending"]),
                    (self.membership.id, None, None),
                )
                self.assertEqual({f: state[f] for f in own}, own)
                self.assertEqual(state["email_privacy"], "authenticated")
                contact = herd_contact(db.Herd.get_by_id(self.herd.id))
                self.assertEqual(contact.mode, "ej_jamford")
                self.assertEqual(contact.rows["email"], _row("anna@example.invalid", "egen"))

    def test_membership_becoming_active_compares_its_herds(self):
        """O4: set_membership_status to active compares the herds linked while it was not, in its transaction: the
        main member is the contact, equal rows are fetched, a different one waits for an answer. A herd already
        compared is left as it is."""
        self._set_status("inactive")
        self._herd(name="Anna Exempel", email="anna@example.invalid", mobile_phone="070-999 99 99")
        link_herd(self.herd.id, self.membership.id)
        compared = self._herd(self.herds[1], email="anna@example.invalid")
        db.Herd.update(membership=self.membership, contact_member=self.main, contact_pending=[]).where(
            db.Herd.id == compared.id
        ).execute()

        with db.DATABASE.atomic():
            locked = db.Membership.select().where(db.Membership.id == self.membership.id).for_update().get()
            matrikel.set_membership_status(locked, "active", self.admin)
            locked.save(only=[db.Membership.membership_status, db.Membership.updated_at])

        state = self._state()
        self.assertEqual((state["contact_member_id"], state["contact_pending"]), (self.main.id, ["mobile_phone"]))
        self.assertEqual((state["name"], state["email"], state["mobile_phone"]), (None, None, "070-999 99 99"))
        rows = herd_contact(db.Herd.get_by_id(self.herd.id)).rows
        self.assertEqual(rows["name"], _row("Anna Exempel", "person"))
        self.assertEqual(rows["email"], _row("anna@example.invalid", "person"))
        self.assertEqual(rows["mobile_phone"], _row("070-999 99 99", "egen", True, "070-111 11 11"))
        self.assertEqual(self._state(compared)["email"], "anna@example.invalid")


@unittest.skipUnless(_USE_POSTGRES, "FOR UPDATE serialisation needs PostgreSQL")
class TestLinkHerdConcurrency(LinkTest):
    def test_link_waits_for_a_concurrent_admin_change(self):
        """The link re-reads the herd under its lock: an admin's change that commits meanwhile is compared, not
        overwritten (spec, Prov: Kopplingen)."""
        self._herd(name="Anna Exempel", email="gard@example.invalid")
        locked, release = threading.Event(), threading.Event()
        results, failures = [], []

        def admin():
            try:
                with db.DATABASE.atomic():
                    db.Herd.select(db.Herd.id).where(db.Herd.id == self.herd.id).for_update().get()
                    changed = db.Herd.update(email="anna@example.invalid", www="admin")
                    changed.where(db.Herd.id == self.herd.id).execute()
                    locked.set()
                    assert release.wait(timeout=10)
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(exc)
            finally:
                db.DATABASE.close()

        def link():
            try:
                results.append(link_herd(self.herd.id, self.membership.id))
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(exc)
            finally:
                db.DATABASE.close()

        one = threading.Thread(target=admin)
        one.start()
        self.assertTrue(locked.wait(timeout=10))
        two = threading.Thread(target=link)
        two.start()
        two.join(timeout=1.5)
        self.assertTrue(two.is_alive(), "the link did not wait for the herd's lock")
        release.set()
        one.join(timeout=15)
        two.join(timeout=15)

        self.assertEqual(failures, [])
        self.assertEqual(results[0]["email"], "lika")
        state = self._state()
        self.assertEqual((state["email"], state["contact_pending"]), (None, []))
        self.assertEqual(db.Herd.get_by_id(self.herd.id).www, "admin")
