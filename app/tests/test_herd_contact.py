"""herd_contact: the herd's contact rows as they are shown, and who may see the register's values (#117)."""

from datetime import date, timedelta

import utils.data_access as da
import utils.database as db
import utils.matrikel as matrikel
from utils.herd_contact import Row, herd_contact, herd_contacts, is_matrikel_reader, normalize

from tests.database_test import DatabaseTest
from tests.ht_helpers import count_queries

ADDRESS = "Byvägen 1|62300|Roma"


def _row(value, source, pending=False, alternative=None):
    return Row(value, source, pending, alternative)


class HerdContactTest(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.membership = db.Membership.create(member_number=7, address="Byvägen 1", postal_code="62300", city="Roma")
        self.main = self._person("Anna", "Exempel", "huvudmedlem", "anna@example.invalid", "070-111 11 11")
        self.family = self._person("Ida", "Exempel", "familjemedlem", "ida@example.invalid", "073-222 22 22")
        self.herd = self.herds[0]  # G1, Gotland

    def _person(self, first, last, role, email=None, phone=None, user=None):
        return db.Member.create(
            membership=self.membership,
            first_name=first,
            last_name=last,
            role=role,
            email=email,
            phone=phone,
            user=user,
        )

    def _compare(self, herd, contact=None, pending=(), **columns):
        """Link `herd` to the membership as compared, with the contact columns given (others NULL)."""
        values = dict.fromkeys(("name", "email", "mobile_phone", "physical_address"))
        values.update(columns)
        db.Herd.update(
            membership=self.membership, contact_member=contact, contact_pending=list(pending), **values
        ).where(db.Herd.id == herd.id).execute()
        return db.Herd.get_by_id(herd.id)

    def _set_status(self, status):
        db.Membership.update(membership_status=status).where(db.Membership.id == self.membership.id).execute()


class TestHerdContact(HerdContactTest):
    def test_unlinked_or_uncompared_herd_reads_own_columns(self):
        unlinked = db.Herd.get_by_id(self.herds[1].id)
        db.Herd.update(membership=self.membership, mobile_phone="").where(db.Herd.id == self.herd.id).execute()
        uncompared = db.Herd.get_by_id(self.herd.id)  # linked, contact_pending NULL
        for herd in (unlinked, uncompared):
            contact = herd_contact(herd)
            self.assertEqual(contact.mode, "ej_jamford")
            self.assertIsNone(contact.contact_member_id)
            for field, row in contact.rows.items():
                self.assertEqual(
                    (row.value, row.source, row.pending, row.alternative), (getattr(herd, field), "egen", False, None)
                )
        self.assertEqual(herd_contact(uncompared).rows["email"].value, "o@h1")
        self.assertEqual(
            herd_contact(uncompared).rows["mobile_phone"].value, ""
        )  # untouched, as the legacy reply has it

    def test_person_mode_derives_name_email_phone(self):
        contact = herd_contact(self._compare(self.herd, contact=self.main))
        self.assertEqual((contact.mode, contact.contact_member_id), ("person", self.main.id))
        self.assertEqual(contact.rows["name"], _row("Anna Exempel", "person"))
        self.assertEqual(contact.rows["email"], _row("anna@example.invalid", "person"))
        self.assertEqual(contact.rows["mobile_phone"], _row("070-111 11 11", "person"))
        # a chosen family member is the contact while she is active, whoever the main member is
        contact = herd_contact(self._compare(self.herd, contact=self.family))
        self.assertEqual(contact.contact_member_id, self.family.id)
        self.assertEqual(contact.rows["email"].value, "ida@example.invalid")
        # an active person on another membership is never the contact
        other = db.Membership.create(member_number=8)
        stranger = db.Member.create(
            membership=other, first_name="Per", last_name="Prov", role="huvudmedlem", email="per@example.invalid"
        )
        contact = herd_contact(self._compare(self.herd, contact=stranger))
        self.assertEqual((contact.mode, contact.contact_member_id), ("ingen", None))
        self.assertEqual((contact.rows["name"].value, contact.rows["email"].value), (None, None))

    def test_address_derived_as_pipe_string(self):
        contact = herd_contact(self._compare(self.herd, contact=self.main))
        self.assertEqual(contact.rows["physical_address"], _row(ADDRESS, "medlemskap"))
        self.membership.postal_code = None
        self.membership.save()
        self.assertEqual(
            herd_contact(db.Herd.get_by_id(self.herd.id)).rows["physical_address"].value, "Byvägen 1||Roma"
        )

    def test_own_row_alternative_and_pending(self):
        herd = self._compare(
            self.herd,
            contact=self.main,
            pending=["mobile_phone", "email"],
            mobile_phone="070-000 00 00",
            email="ANNA@example.invalid ",
            physical_address="Gården 2|62300|Roma",
        )
        rows = herd_contact(herd).rows
        self.assertEqual(rows["mobile_phone"], _row("070-000 00 00", "egen", pending=True, alternative="070-111 11 11"))
        # the same value after normalising: no alternative to offer
        self.assertEqual(rows["email"], _row("ANNA@example.invalid ", "egen", pending=True))
        self.assertEqual(rows["physical_address"], _row("Gården 2|62300|Roma", "egen", alternative=ADDRESS))
        self.assertFalse(rows["name"].pending)  # only own rows wait for an answer

    def test_fritext_does_not_derive_email_or_phone(self):
        herd = self._compare(self.herd, name="Gårdens Kontakt", mobile_phone="070-999 99 99", pending=["name"])
        contact = herd_contact(herd)
        self.assertEqual((contact.mode, contact.contact_member_id), ("fritext", None))
        # "Använd medlemskapets" makes the main member the contact, so her name is the alternative
        self.assertEqual(
            contact.rows["name"], _row("Gårdens Kontakt", "egen", pending=True, alternative="Anna Exempel")
        )
        self.assertEqual(contact.rows["email"], _row(None, "egen"))
        self.assertEqual(contact.rows["mobile_phone"], _row("070-999 99 99", "egen"))
        self.assertEqual(contact.rows["physical_address"], _row(ADDRESS, "medlemskap"))
        # no active main member: nothing to offer, while the family member keeps the address fetched
        db.Member.update(end_date=date.today()).where(db.Member.id == self.main.id).execute()
        contact = herd_contact(herd)
        self.assertEqual(contact.rows["name"], _row("Gårdens Kontakt", "egen", pending=True))
        self.assertEqual(contact.rows["physical_address"].value, ADDRESS)

    def test_no_active_person_empties_derived_rows(self):
        herd = self._compare(self.herd, contact=self.main, email="gard@example.invalid")
        derived_empty = {
            "name": _row(None, "person"),
            "email": _row("gard@example.invalid", "egen"),  # the own row stays
            "mobile_phone": _row(None, "person"),
            "physical_address": _row(None, "medlemskap"),
        }

        # a paused membership: nobody ended, still nothing derived
        self._set_status("inactive")
        self.assertEqual(herd_contact(herd).rows, derived_empty)
        self._set_status("active")

        # the contact person ended while another person is active: the address still comes from the membership
        db.Member.update(end_date=date.today()).where(db.Member.id == self.main.id).execute()
        contact = herd_contact(herd)
        self.assertEqual((contact.mode, contact.contact_member_id), ("ingen", None))
        self.assertIsNone(contact.rows["name"].value)
        self.assertIsNone(contact.rows["mobile_phone"].value)
        self.assertEqual(contact.rows["physical_address"].value, ADDRESS)

        matrikel.retire_membership(self.membership, self.admin)
        contact = herd_contact(herd)
        self.assertEqual((contact.mode, contact.contact_member_id), ("ingen", None))
        self.assertEqual(contact.rows, derived_empty)

    def test_matrikel_reader_rules(self):
        users = {
            name: da.register_user(f"{name}@example.invalid", "pass", username=name)
            for name in ("main", "family", "caretaker", "no_grant", "expired", "ended")
        }
        db.Member.update(user=users["main"]).where(db.Member.id == self.main.id).execute()
        db.Member.update(user=users["family"]).where(db.Member.id == self.family.id).execute()
        caretaker = self._person("Kim", "Exempel", "skotare", user=users["caretaker"])
        self._person("Lo", "Exempel", "skotare", user=users["no_grant"])
        expired = self._person("Mo", "Exempel", "skotare", user=users["expired"])
        ended = self._person("No", "Exempel", "familjemedlem", user=users["ended"])
        db.Member.update(end_date=date.today()).where(db.Member.id == ended.id).execute()
        db.HerdAccessGrant.create(member=caretaker, herd=self.herd, granted_by=self.admin)
        db.HerdAccessGrant.create(
            member=expired, herd=self.herd, granted_by=self.admin, valid_until=date.today() - timedelta(days=1)
        )
        herd = self._compare(self.herd, contact=self.main)
        mellerud = db.Herd.get_by_id(self.herds[2].id)

        self.assertTrue(is_matrikel_reader(self.admin, herd))
        self.assertTrue(is_matrikel_reader(self.manager, herd))
        self.assertFalse(is_matrikel_reader(self.manager, mellerud))  # manager of Gotland only
        for name in ("main", "family", "caretaker"):
            self.assertTrue(is_matrikel_reader(users[name], herd), name)
        for name in ("no_grant", "expired", "ended"):
            self.assertFalse(is_matrikel_reader(users[name], herd), name)
        self.assertFalse(is_matrikel_reader(self.owner, herd))  # only the old owner role on G1
        self.assertFalse(is_matrikel_reader(None, herd))

        self._set_status("inactive")
        for name in ("main", "family", "caretaker"):
            self.assertFalse(is_matrikel_reader(users[name], herd), name)
        self.assertTrue(is_matrikel_reader(self.admin, herd))
        self.assertTrue(is_matrikel_reader(self.manager, herd))

    def test_herd_contacts_batches_queries(self):
        other = db.Membership.create(member_number=8, address="Annanväg 2", postal_code="62200", city="Visby")
        other_main = db.Member.create(
            membership=other, first_name="Per", last_name="Prov", role="huvudmedlem", email="per@example.invalid"
        )
        ids = []
        for i in range(30):
            membership, person = (self.membership, self.main) if i % 2 else (other, other_main)
            ids.append(
                db.Herd.create(
                    genebank=self.genebanks[0],
                    herd=f"G{100 + i}",
                    membership=membership,
                    contact_member=person,
                    contact_pending=[],
                ).id
            )
        herds = list(db.Herd.select().where(db.Herd.id.in_(ids)))  # fresh rows: no cached related objects

        with count_queries() as counter:
            contacts = herd_contacts(herds)
            emails = {herd_id: c.rows["email"].value for herd_id, c in contacts.items()}
        self.assertTrue(1 <= counter["n"] <= 4, counter)  # at least one: the counter sees these queries
        self.assertEqual(set(contacts), set(ids))
        self.assertEqual(emails[ids[0]], "per@example.invalid")
        self.assertEqual(emails[ids[1]], "anna@example.invalid")
        self.assertEqual(contacts[ids[0]].rows["physical_address"].value, "Annanväg 2|62200|Visby")

    def test_normalize(self):
        self.assertEqual(normalize("email", " Anna@Exempel.SE "), "anna@exempel.se")
        self.assertEqual(normalize("mobile_phone", "+46 70-000 00 00"), "0700000000")
        for field in ("mobile_phone", "wire_phone"):
            local = normalize(field, "070-000 00 00")
            self.assertEqual(normalize(field, "+46 70-000 00 00"), local, field)
            self.assertEqual(normalize(field, "0046 70-000 00 00"), local, field)
            self.assertNotEqual(normalize(field, "4670-000 00 00"), local, field)  # no marked country code
            self.assertEqual(normalize(field, "(+46) 70-000 00 00"), local, field)
            # text in the number is not settled by the normalisation, so it compares as different
            self.assertNotEqual(normalize(field, "0046 8-123 456 ank 78"), normalize(field, "08-123 456 78"), field)
            self.assertNotEqual(normalize(field, "(+46) 8-12 34 56 / 78"), normalize(field, "08-123 456 78"), field)
            self.assertNotEqual(normalize(field, "070 SMS-kod AbC"), normalize(field, "070 SMS-kod aBc"), field)
            for dash in ("\u2011", "\u2010"):  # non-breaking hyphen, hyphen
                self.assertEqual(normalize(field, f"070{dash}000 00 00"), local, field)
        self.assertNotEqual(
            normalize("physical_address", "Testvägen 1–3"), normalize("physical_address", "Testvägen 13")
        )
        self.assertEqual(
            normalize("physical_address", "Byvägen  1|623 00|ROMA"),
            normalize("physical_address", "Byvägen 1|62300|Roma"),
        )
        self.assertNotEqual(normalize("physical_address", "Byvägen 1"), normalize("physical_address", ADDRESS))
        self.assertNotEqual(
            normalize("physical_address", "Byvägen 1|623 00, lgh A|Roma"), normalize("physical_address", ADDRESS)
        )
        self.assertEqual(normalize("name", "Per Anna Exempel"), normalize("name", "Anna Per Exempel"))
        for field in ("email", "mobile_phone", "physical_address", "name"):
            self.assertIsNone(normalize(field, None))
            self.assertIsNone(normalize(field, ""))
        self.assertIsNone(normalize("physical_address", "||"))
