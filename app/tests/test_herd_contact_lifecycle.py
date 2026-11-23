"""The herd's contact follows the persons' lifecycle, and audit undo leaves the contact alone (#117, spec: Livscykel
and Granskningsloggen)."""

import json
import threading
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

import utils.data_access as da
import utils.database as db
import utils.matrikel as matrikel

from tests.database_test import _USE_POSTGRES
from tests.test_herd_contact_write import FARM, HOME, HerdContactWriteTest

FARM_EMAIL = "gard@example.invalid"
FARM_MOBILE = "070-999 99 99"
FARM_WIRE = "0498-00 00 00"


class LifecycleTest(HerdContactWriteTest):
    """G1 is compared, the contact is Anna (main member); Ida is a family member (see HerdContactWriteTest)."""

    def _herd(self):
        return db.Herd.get_by_id(self.herd.id)


class TestLifecycle(LifecycleTest):
    def test_contact_person_ended_falls_back_to_main_member(self):
        self._set(
            contact_member=self.family.id,
            email=FARM_EMAIL,  # the farm's own e-mail
            **{f"{f}_privacy": "authenticated" for f in ("name", "email", "mobile_phone", "physical_address")},
        )
        other = self._user("other")
        self.assertEqual(self._read(other)["mobile_phone"], "073-222 22 22")

        matrikel.soft_delete_person(self.family, self.admin)

        state = self._state()
        self.assertEqual(state["contact_member_id"], self.main.id)
        # another person is shown: her name and mobile start hidden; the household's address is the same one
        self.assertEqual(
            (state["name_privacy"], state["mobile_phone_privacy"], state["physical_address_privacy"]),
            ("private", "private", "authenticated"),
        )
        self.assertEqual((state["email"], state["email_privacy"]), (FARM_EMAIL, "authenticated"))
        seen = self._read(other)
        self.assertEqual((seen.get("email"), seen.get("physical_address")), (FARM_EMAIL, HOME))
        self.assertNotIn("mobile_phone", seen)
        self.assertNotIn("name", seen)

    def test_swap_main_member_keeps_contact(self):
        self._set(email_privacy="authenticated")
        other = self._user("other")
        matrikel.swap_main_member(self.membership, self.family, self.admin)
        state = self._state()
        self.assertEqual((state["contact_member_id"], state["email_privacy"]), (self.main.id, "authenticated"))
        self.assertEqual(self._read(other)["email"], "anna@example.invalid")

    def test_retire_membership_empties_derived_keeps_own(self):
        self._set(
            email_privacy="authenticated",
            physical_address_privacy="authenticated",
            mobile_phone=FARM_MOBILE,  # own, "authenticated"
            wire_phone=FARM_WIRE,
            wire_phone_privacy="authenticated",
        )
        other = self._user("other")
        self.assertEqual(self._read(other)["email"], "anna@example.invalid")

        matrikel.retire_membership(self.membership, self.admin)

        herd = self._herd()
        self.assertIsNone(herd.contact_member_id)
        # what was fetched is gone, the address too, and it starts hidden if anyone comes back
        self.assertEqual(
            (herd.name_privacy, herd.email_privacy, herd.physical_address_privacy), ("private", "private", "private")
        )
        self.assertEqual(
            (herd.mobile_phone, herd.mobile_phone_privacy, herd.wire_phone, herd.wire_phone_privacy),
            (FARM_MOBILE, "authenticated", FARM_WIRE, "authenticated"),
        )
        seen = self._read(other)
        for field in ("name", "email", "physical_address"):
            self.assertIsNone(seen.get(field), field)
        self.assertEqual((seen.get("mobile_phone"), seen.get("wire_phone")), (FARM_MOBILE, FARM_WIRE))

    def test_anonymize_clears_own_rows_equal_to_person(self):
        self._set(
            email="IDA@example.invalid ",
            email_privacy="authenticated",
            wire_phone="+46 73 222 22 22",  # Ida's mobile, kept as the fixed phone
            wire_phone_privacy="authenticated",
            mobile_phone=FARM_MOBILE,
            contact_pending=["email"],
        )
        other = self._user("other")
        self.assertEqual(self._read(other)["wire_phone"], "+46 73 222 22 22")

        matrikel.anonymize_person(self.family, self.admin)

        herd = self._herd()
        self.assertEqual(
            (herd.email, herd.email_privacy, herd.wire_phone, herd.wire_phone_privacy),
            (None, "private", None, "private"),
        )
        self.assertEqual(herd.contact_pending, [])
        self.assertEqual((herd.mobile_phone, herd.contact_member_id), (FARM_MOBILE, self.main.id))
        seen = self._read(other)
        self.assertIsNone(seen.get("email"))  # fetched from Anna now, hidden
        self.assertIsNone(seen.get("wire_phone"))

    def test_anonymize_keeps_shared_value(self):
        ola = self._person("Ola", "Exempel", "familjemedlem", "Ida@example.invalid")
        db.Member.update(end_date=date.today()).where(db.Member.id == ola.id).execute()  # ended, not erased
        self._person("Per", "Exempel", "familjemedlem", None, "073-222 22 22")  # active
        self._set(
            email="ida@example.invalid",
            email_privacy="authenticated",
            wire_phone="073-222 22 22",
            wire_phone_privacy="authenticated",
        )
        other = self._user("other")

        matrikel.anonymize_person(self.family, self.admin)

        herd = self._herd()
        self.assertEqual(
            (herd.email, herd.email_privacy, herd.wire_phone, herd.wire_phone_privacy),
            ("ida@example.invalid", "authenticated", "073-222 22 22", "authenticated"),
        )
        self.assertEqual(self._read(other)["email"], "ida@example.invalid")
        # once Ola is erased too, nobody left has the e-mail
        matrikel.anonymize_person(ola, self.admin)
        herd = self._herd()
        self.assertEqual((herd.email, herd.email_privacy, herd.wire_phone), (None, "private", "073-222 22 22"))

    def test_household_erased_only_after_all_anonymized(self):
        own = {
            "email": FARM_EMAIL,
            "mobile_phone": FARM_MOBILE,
            "wire_phone": FARM_WIRE,
            "www": "exempelgarden.invalid",
            "physical_address": FARM,
        }
        self._set(**own, **{f"{c}_privacy": "authenticated" for c in db.HERD_CONTACT_COLUMNS})
        other = self._user("other")
        matrikel.retire_membership(self.membership, self.admin)

        matrikel.anonymize_person(db.Member.get_by_id(self.main.id), self.admin)

        herd = self._herd()
        self.assertEqual({c: getattr(herd, c) for c in own}, own)  # one person is not erased yet
        self.assertEqual(self._read(other)["www"], "exempelgarden.invalid")

        matrikel.anonymize_person(db.Member.get_by_id(self.family.id), self.admin)

        herd = self._herd()
        for column in db.HERD_CONTACT_COLUMNS:
            self.assertEqual((getattr(herd, column), getattr(herd, f"{column}_privacy")), (None, "private"), column)
        self.assertEqual(herd.contact_pending, [])
        seen = self._read(other)
        for column in db.HERD_CONTACT_COLUMNS:
            self.assertIsNone(seen.get(column), column)

    def test_restore_refuses_contact_fields(self):
        """Codex T1 F1: the history keeps no contact values, so an old privacy written back would apply to a newer
        value. Restore and revert never write the contact's privacy, membership, contact person or pending rows,
        not for admin either."""
        self._set(physical_address=FARM, physical_address_privacy="authenticated")
        self._set(physical_address_privacy="private")  # the breeder hides the farm's address
        hidden = (
            db.AuditLog.select()
            .where(db.AuditLog.table_name == "herd", db.AuditLog.record_id == str(self.herd.id))
            .order_by(db.AuditLog.id.desc())
            .get()
        )
        self.assertEqual(hidden.old_data["physical_address_privacy"], "authenticated")
        self._set(physical_address="Nyvägen 2|62300|Roma")  # and then moves: the value is not in the history
        other = self._user("other")
        for is_admin in (False, True):
            with self.subTest(is_admin=is_admin):
                self.assertEqual(da.revert_audit_entry(hidden.id, is_admin=is_admin)[1], 409)
                self.assertEqual(da.restore_record("herd", self.herd.id, hidden.id, is_admin=is_admin)[1], 200)
                self.assertEqual(self._herd().physical_address_privacy, "private")
                self.assertIsNone(self._read(other).get("physical_address"))

        stored = da._stored_row("herd", "herd_id", self.herd.id)
        protected = {
            "membership_id": None,
            "contact_member_id": self.family.id,
            "contact_pending": ["email"],
            **{f"{c}_privacy": "public" for c in db.HERD_CONTACT_COLUMNS},
        }
        entry = db.AuditLog.create(
            table_name="herd",
            record_id=str(self.herd.id),
            operation="UPDATE",
            old_data={**stored, **protected, "herd_name": "Gammalt namn"},
            new_data=stored,
            changed_fields=[*protected, "herd_name"],
        )
        for is_admin in (False, True):
            with self.subTest(is_admin=is_admin, entry="protected"):
                body, status = da.revert_audit_entry(entry.id, is_admin=is_admin)
                self.assertEqual(status, 409, body)
                body, status = da.restore_record("herd", self.herd.id, entry.id, is_admin=is_admin)
                self.assertEqual(status, 200, body)
                row = da._stored_row("herd", "herd_id", self.herd.id)
                self.assertEqual({c: row[c] for c in protected}, {c: stored[c] for c in protected})
                self.assertEqual(row["herd_name"], "Gammalt namn")  # the rest of the snapshot is restored

    def test_revert_names_the_contact_fields_it_cannot_write(self):
        """O6: the history keeps no contact values, so a revert of an entry that changed one says which it left."""
        self._set(herd_name="Gammalt namn")
        self._set(herd_name="Nytt namn", www="ny.example.invalid", email=FARM_EMAIL)
        entry = (
            db.AuditLog.select()
            .where(db.AuditLog.table_name == "herd", db.AuditLog.record_id == str(self.herd.id))
            .order_by(db.AuditLog.id.desc())
            .get()
        )
        self.assertEqual(set(entry.changed_fields), {"herd_name", "www", "email"})

        body, status = da.revert_audit_entry(entry.id)

        self.assertEqual(status, 200, body)
        self.assertEqual(body["message"], "Ändring ångrad utom email, www: historiken sparar inte de värdena.")
        herd = self._herd()
        self.assertEqual((herd.herd_name, herd.www, herd.email), ("Gammalt namn", "ny.example.invalid", FARM_EMAIL))

    def test_sequence_fritext_then_anonymize(self):
        self._set(
            contact_member=None,
            name="Gårdens Kontakt",
            email="ida@example.invalid",  # a contact outside the register, with Ida's e-mail
            email_privacy="authenticated",
            contact_pending=["name"],
        )
        other = self._user("other")
        self.assertEqual(self._read(other)["email"], "ida@example.invalid")

        matrikel.anonymize_person(self.family, self.admin)

        state = self._state()
        self.assertEqual(
            (state["name"], state["email"], state["email_privacy"], state["contact_pending"]),
            ("Gårdens Kontakt", None, "private", ["name"]),
        )
        self.assertIsNone(self._read(other).get("email"))
        history = db.AuditLog.select().where(
            db.AuditLog.table_name == "herd", db.AuditLog.record_id == str(self.herd.id)
        )
        self.assertGreater(history.count(), 0)
        for entry in history:
            self.assertNotIn("ida@example.invalid", json.dumps([entry.old_data, entry.new_data]).lower())

    def test_anonymize_chosen_family_member_same_and_other_number(self):
        other = self._user("other")
        for anna_phone, privacy in (("+46 73 222 22 22", "authenticated"), ("070-111 11 11", "private")):
            with self.subTest(anna_phone=anna_phone):
                ida = self._person("Ida", "Exempel", "familjemedlem", "ida@example.invalid", "073-222 22 22")
                db.Member.update(phone=anna_phone).where(db.Member.id == self.main.id).execute()
                self._set(contact_member=ida.id, mobile_phone_privacy="authenticated")
                self.assertEqual(self._read(other)["mobile_phone"], "073-222 22 22")

                matrikel.anonymize_person(ida, self.admin)

                state = self._state()
                self.assertEqual((state["contact_member_id"], state["mobile_phone_privacy"]), (self.main.id, privacy))
                shown = anna_phone if privacy == "authenticated" else None
                self.assertEqual(self._read(other).get("mobile_phone"), shown)

    def test_paused_membership_contact_ended_hides_the_next_persons_values(self):
        """Nothing is fetched while the membership is paused, but the contact still changes person: Anna's mobile
        must not show with the choice made for Ida's once the membership is active again."""
        self._set(contact_member=self.family.id, mobile_phone_privacy="authenticated")
        other = self._user("other")
        self._set_status("inactive")

        matrikel.soft_delete_person(self.family, self.admin)

        self._set_status("active")
        state = self._state()
        self.assertEqual((state["contact_member_id"], state["mobile_phone_privacy"]), (self.main.id, "private"))
        self.assertIsNone(self._read(other).get("mobile_phone"))

    def test_nightly_job_erases_the_household_rows(self):
        """The nightly job (anonymize_ended_persons) reaches the hooks under its own locks: an ended household
        with an inactive herd is erased, and so are the herd's own contact rows."""
        self._set(
            email=FARM_EMAIL,
            wire_phone=FARM_WIRE,
            www="exempelgarden.invalid",
            physical_address=FARM,
            is_active=False,
            **{f"{c}_privacy": "authenticated" for c in db.HERD_CONTACT_COLUMNS},
        )
        matrikel.retire_membership(self.membership, self.admin)
        ended = date.today() - timedelta(days=500)
        db.Member.update(end_date=ended).where(db.Member.membership == self.membership).execute()

        self.assertEqual(matrikel.anonymize_ended_persons(datetime.now()), (2, 0, []))

        herd = self._herd()
        for column in db.HERD_CONTACT_COLUMNS:
            self.assertEqual((getattr(herd, column), getattr(herd, f"{column}_privacy")), (None, "private"), column)
        self.assertIsNone(herd.contact_member_id)

    def test_contact_change_with_empty_mobile_starts_hidden(self):
        """Codex T7 F1: Ida had emptied her visible mobile and Anna has none. An empty row keeps no choice across a
        change of contact, or Anna's first number would be shown to others when she fills it in."""
        db.Member.update(phone=None).where(db.Member.id.in_([self.main.id, self.family.id])).execute()
        self._set(contact_member=self.family.id, mobile_phone_privacy="authenticated")
        other = self._user("other")

        matrikel.soft_delete_person(self.family, self.admin)

        self.assertEqual(self._state()["mobile_phone_privacy"], "private")
        db.Member.update(phone="070-123 45 67").where(db.Member.id == self.main.id).execute()
        self.assertIsNone(self._read(other).get("mobile_phone"))

    def test_repeated_anonymization_does_not_erase_again(self):
        """Codex T7 F2: the household's rows go once, when the last person becomes erased. Erasing an erased person
        again keeps a website added since (its value is not in the history to restore it from)."""
        matrikel.retire_membership(self.membership, self.admin)
        matrikel.anonymize_person(db.Member.get_by_id(self.main.id), self.admin)
        matrikel.anonymize_person(db.Member.get_by_id(self.family.id), self.admin)
        self._set(www="ny.exempelgarden.invalid", www_privacy="authenticated")

        matrikel.anonymize_person(db.Member.get_by_id(self.family.id), self.admin)

        herd = self._herd()
        self.assertEqual((herd.www, herd.www_privacy), ("ny.exempelgarden.invalid", "authenticated"))


@unittest.skipUnless(_USE_POSTGRES, "FOR UPDATE serialisation needs PostgreSQL")
class TestConcurrentLifecycle(LifecycleTest):
    def _race(self, first, pause, second):
        """Run `first` until it calls `pause` (target, name) with its locks held, start `second`, check that it
        waits for them, then let both finish. Returns their results or exceptions."""
        entered, release, second_done = threading.Event(), threading.Event(), threading.Event()
        target, name = pause
        original = getattr(target, name)
        results = {}

        def paused(*args, **kwargs):
            if not entered.is_set():
                entered.set()
                assert release.wait(timeout=10), "the test never released the paused call"
            return original(*args, **kwargs)

        def run(key, call):
            try:
                results[key] = call()
            except Exception as exc:  # pylint: disable=broad-except
                results[key] = exc
            finally:
                if key == "second":
                    second_done.set()
                db.DB_PROXY.close()

        with patch.object(target, name, paused):
            one = threading.Thread(target=run, args=("first", first))
            one.start()
            self.assertTrue(entered.wait(timeout=10), "the first call never reached its pause")
            two = threading.Thread(target=run, args=("second", second))
            two.start()
            self.assertFalse(second_done.wait(1.5), "the second call finished while the first held the locks")
            release.set()
            one.join(timeout=15)
            two.join(timeout=15)
        for thread in (one, two):
            self.assertFalse(thread.is_alive(), "worker still blocked after the join timeout — a lock never released")
        return results["first"], results["second"]

    def test_concurrent_contact_change_and_person_end(self):
        """The main member chooses Ida as contact while Ida is ended: whichever goes first, the contact is never
        an ended person afterwards."""
        main = self._main_user()
        admin_id, url = self.admin.id, f"/api/v2/herd/{self.herd.herd}"
        for order in (("change", "end"), ("end", "change")):
            with self.subTest(order=order):
                ida = self._person("Ida", "Exempel", "familjemedlem", "ida@example.invalid", "073-222 22 22")
                self._set(contact_member=self.main.id)
                shown, _ = self._form(main)
                client = self._client(main)
                body = {"contact": {"contact_member": ida.id, "name": None, "shown": shown, "rows": {}}}
                calls = {
                    "change": (lambda b=body, c=client: c.patch(url, json=b), (db.Herd, "save")),
                    "end": (
                        lambda i=ida.id: matrikel.soft_delete_person(
                            db.Member.get_by_id(i), db.User.get_by_id(admin_id)
                        ),
                        (matrikel, "write_matrikel_audit"),
                    ),
                }
                first, second = self._race(calls[order[0]][0], calls[order[0]][1], calls[order[1]][0])
                outcome = dict(zip(order, (first, second), strict=True))
                self.assertIsNone(outcome["end"])
                # the change either went first or found Ida ended (400)
                self.assertEqual(outcome["change"].status_code, 200 if order[0] == "change" else 400)
                contact = self._herd().contact_member_id
                self.assertEqual(contact, self.main.id)
                self.assertIsNone(db.Member.get_by_id(contact).end_date)


if __name__ == "__main__":
    unittest.main()
