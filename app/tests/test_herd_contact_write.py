"""The write rules of a herd's contact: apply_contact_patch behind PATCH /api/v2/herd and the admin route (#117)."""

import threading
import unittest
from datetime import date
from unittest.mock import patch

import herdbook  # noqa: E402
import utils.database as db  # noqa: E402
from herdbook import APP  # noqa: E402

from tests.database_test import _USE_POSTGRES  # noqa: E402
from tests.test_herd_contact_read import HerdContactReadTest  # noqa: E402

HOME = "Byvägen 1|62300|Roma"  # the membership's address
FARM = "Gårdsvägen 5|62300|Roma"
STATE = (
    "contact_member_id",
    "contact_pending",
    "membership_id",
    "name",
    "email",
    "mobile_phone",
    "physical_address",
    "name_privacy",
    "email_privacy",
    "mobile_phone_privacy",
    "physical_address_privacy",
    "wire_phone",
    "www",
)


class HerdContactWriteTest(HerdContactReadTest):
    """G1 is compared, the contact is Anna (main member): name, e-mail and mobile from her, address from the
    membership; e-mail "private", mobile "authenticated", name "private", address NULL (private)."""

    def _client(self, user):
        client = APP.test_client(use_cookies=True)
        response = client.post("/api/login", json={"username": user.email, "password": "pass"})
        self.assertEqual(response.status_code, 200)
        return client

    def _patch(self, user, body, admin=False):
        url = f"/api/manage/herd/{self.herd.herd}" if admin else f"/api/v2/herd/{self.herd.herd}"
        return self._client(user).patch(url, json=body)

    def _read(self, user):
        return self._get(user, f"/api/herd/{self.herd.herd}")

    def _form(self, user):
        """What the user's form shows, built from the user's own read: the top-level shown and each row's."""
        data = self._read(user)
        contact = data["contact"]
        shown = {
            "mode": contact["mode"],
            "contact_member": (contact["contact_member"] or {}).get("id"),
            "name": data.get("name") if contact["rows"]["name"]["source"] == "egen" else None,
        }
        rows = {
            field: {
                "source": r["source"],
                "value": data.get(field),
                "alternative": r["alternative"],
                "privacy": r["privacy"],
            }
            for field, r in contact["rows"].items()
        }
        return shown, rows

    def _state(self):
        herd = db.Herd.get_by_id(self.herd.id)
        return {column: getattr(herd, column) for column in STATE}

    def _set(self, **columns):
        db.Herd.update(**columns).where(db.Herd.id == self.herd.id).execute()

    def _assert_problem(self, response, status, problem_type):
        self.assertEqual(response.status_code, status, response.data)
        self.assertEqual(response.get_json()["type"], problem_type, response.data)

    def _main_user(self):
        return self._user("mainuser", self.main)


class TestRows(HerdContactWriteTest):
    def test_missing_row_is_unchanged(self):
        main = self._main_user()
        before = self._state()
        response = self._patch(main, {"www": "ny.example.invalid"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._state(), {**before, "www": "ny.example.invalid"})
        # a contact patch with one row leaves the others as they were
        shown, rows = self._form(main)
        response = self._patch(
            main,
            {
                "contact": {
                    "shown": shown,
                    "rows": {"email": {"source": "medlemskap", "privacy": "authenticated", "shown": rows["email"]}},
                }
            },
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._state(), {**before, "www": "ny.example.invalid", "email_privacy": "authenticated"})

    def test_echo_of_derived_row_changes_nothing(self):
        main = self._main_user()
        shown, rows = self._form(main)
        before = self._state()
        body = {
            "contact": {
                "shown": shown,
                "rows": {
                    "email": {"source": "medlemskap", "privacy": "private", "shown": rows["email"]},
                    # the register's values, written differently: the same after the normalisation
                    "mobile_phone": {
                        "source": "egen",
                        "value": "+46 70-111 11 11",
                        "privacy": "authenticated",
                        "shown": rows["mobile_phone"],
                    },
                    "physical_address": {
                        "source": "egen",
                        "value": "Byvägen  1|623 00|ROMA",
                        "privacy": "private",
                        "shown": rows["physical_address"],
                    },
                },
            }
        }
        response = self._patch(main, body)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._state(), before)

    def test_own_equal_to_derived_becomes_derived_for_matrikel_reader(self):
        self._set(email="gard@example.invalid")
        main = self._main_user()
        shown, rows = self._form(main)
        response = self._patch(
            main,
            {
                "contact": {
                    "shown": shown,
                    "rows": {
                        "email": {
                            "source": "egen",
                            "value": " Anna@Example.invalid",
                            "privacy": "private",
                            "shown": rows["email"],
                        }
                    },
                }
            },
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(self._state()["email"])
        self.assertEqual(self._read(main)["contact"]["rows"]["email"]["source"], "person")

    def test_own_equal_to_derived_stays_own_for_legacy_owner_only(self):
        self._set(email="gard@example.invalid", email_privacy="authenticated")
        legacy = self._legacy_owner()
        for value in ("anna@example.invalid", "ny@example.invalid"):  # equal to the contact person's, and not
            with self.subTest(value=value):
                row = self._read(legacy)["contact"]["rows"]["email"]
                body = {
                    "contact": {
                        "rows": {"email": {"source": "egen", "value": value, "privacy": row["privacy"], "shown": row}}
                    }
                }
                response = self._patch(legacy, body)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(self._state()["email"], value)
                self.assertEqual(
                    self._read(legacy)["contact"]["rows"]["email"],
                    {"source": "egen", "value": value, "privacy": "authenticated"},
                )

    def test_privacy_reset_when_shown_value_changes(self):
        main = self._main_user()
        # "Använd medlemskapets" with another value than the own one: "private", whatever the form sent
        self._set(email="gard@example.invalid", email_privacy="authenticated")
        shown, rows = self._form(main)
        self.assertEqual(rows["email"]["alternative"], "anna@example.invalid")
        row = {"source": "medlemskap", "privacy": "authenticated", "shown": rows["email"]}
        response = self._patch(main, {"contact": {"shown": shown, "rows": {"email": row}}})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((self._state()["email"], self._state()["email_privacy"]), (None, "private"))
        # the same value (an own copy kept by an account without register access): the choice is kept
        self._set(email="anna@example.invalid", email_privacy="authenticated")
        shown, rows = self._form(main)
        self.assertIsNone(rows["email"]["alternative"])
        response = self._patch(
            main, {"contact": {"shown": shown, "rows": {"email": {"source": "medlemskap", "shown": rows["email"]}}}}
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((self._state()["email"], self._state()["email_privacy"]), (None, "authenticated"))

    def test_widen_requires_matrikel_reader(self):
        legacy = self._legacy_owner()
        row = self._read(legacy)["contact"]["rows"]["email"]
        self.assertEqual(row, {"source": "hamtad"})
        guessed = {"source": "person", "value": "anna@example.invalid", "alternative": None, "privacy": "private"}
        for shown in (row, guessed):
            with self.subTest(shown=shown):
                body = {
                    "contact": {"rows": {"email": {"source": "medlemskap", "privacy": "authenticated", "shown": shown}}}
                }
                self._assert_problem(self._patch(legacy, body), 403, "contact-forbidden")
                self.assertEqual(self._state()["email_privacy"], "private")
        # the main member reads the register: she may
        main = self._main_user()
        shown, rows = self._form(main)
        body = {
            "shown": shown,
            "rows": {"email": {"source": "medlemskap", "privacy": "authenticated", "shown": rows["email"]}},
        }
        self.assertEqual(self._patch(main, {"contact": body}).status_code, 200)
        self.assertEqual(self._state()["email_privacy"], "authenticated")

    def test_use_membership_value_requires_matrikel_reader(self):
        self._set(mobile_phone="0498-00 00 00", contact_pending=["mobile_phone"])
        legacy = self._legacy_owner()
        row = self._read(legacy)["contact"]["rows"]["mobile_phone"]
        self.assertEqual(row, {"source": "egen", "value": "0498-00 00 00", "privacy": "authenticated"})
        before = self._state()
        for alternative in ("070-111 11 11", "070-999 99 99"):  # the register's number, and a wrong guess
            for change in ({"source": "medlemskap"}, {"source": "medlemskap", "answer": "anvand"}):
                with self.subTest(alternative=alternative, change=change):
                    body = {
                        "contact": {"rows": {"mobile_phone": {**change, "shown": {**row, "alternative": alternative}}}}
                    }
                    self._assert_problem(self._patch(legacy, body), 403, "contact-forbidden")
                    self.assertEqual(self._state(), before)

    def test_stale_form_conflicts(self):
        self._set(email="gard@example.invalid", contact_pending=["email"])
        main = self._main_user()
        shown, rows = self._form(main)
        answer = {"source": "egen", "value": "gard@example.invalid", "privacy": "private", "answer": "behall"}
        before = self._state()
        cases = (
            ("mode", {**shown, "mode": "fritext"}, rows["email"]),
            ("contact_member", {**shown, "contact_member": self.family.id}, rows["email"]),
            ("name", {**shown, "name": "Gårdens Kontakt"}, rows["email"]),
            ("source", shown, {**rows["email"], "source": "person"}),
            ("value", shown, {**rows["email"], "value": "annan@example.invalid"}),
            ("alternative", shown, {**rows["email"], "alternative": "ida@example.invalid"}),
            ("privacy", shown, {**rows["email"], "privacy": "authenticated"}),
        )
        for label, top, row_shown in cases:
            with self.subTest(label):
                body = {"www": "ny-www", "contact": {"shown": top, "rows": {"email": {**answer, "shown": row_shown}}}}
                self._assert_problem(self._patch(main, body), 409, "contact-changed")
                self.assertEqual(self._state(), before)
        # the row no longer waits for an answer
        self._set(contact_pending=[])
        body = {"www": "ny-www", "contact": {"shown": shown, "rows": {"email": {**answer, "shown": rows["email"]}}}}
        self._assert_problem(self._patch(main, body), 409, "contact-changed")
        self.assertEqual(self._state(), {**before, "contact_pending": []})
        # the same answer to a form that still holds: saved
        self._set(contact_pending=["email"])
        self.assertEqual(self._patch(main, body).status_code, 200)
        self.assertEqual(self._state(), {**before, "contact_pending": [], "www": "ny-www"})

    def test_legacy_owner_edits_own_row_from_own_get(self):
        self._set(email="gard@example.invalid", email_privacy="private")
        legacy = self._legacy_owner()

        def from_read(value):  # a PATCH built from nothing but the account's own GET
            row = self._read(legacy)["contact"]["rows"]["email"]
            return {
                "contact": {
                    "rows": {"email": {"source": "egen", "value": value, "privacy": row["privacy"], "shown": row}}
                }
            }

        response = self._patch(legacy, from_read("gard2@example.invalid"))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._state()["email"], "gard2@example.invalid")
        # changed by someone else since the read
        body = from_read("gard3@example.invalid")
        self._set(email="annan@example.invalid")
        self._assert_problem(self._patch(legacy, body), 409, "contact-changed")
        self.assertEqual(self._state()["email"], "annan@example.invalid")
        # fetched from the register since the read
        body = from_read("gard3@example.invalid")
        self._set(email=None)
        self._assert_problem(self._patch(legacy, body), 409, "contact-changed")
        self.assertIsNone(self._state()["email"])

    def test_emptied_own_row_is_a_switch_to_the_register(self):
        """An own value removed lets the register's show: as "Använd medlemskapets", only for those who read the
        register, and only to the value the form showed as the alternative."""
        self._set(email="gard@example.invalid", email_privacy="authenticated")
        legacy = self._legacy_owner()
        row = self._read(legacy)["contact"]["rows"]["email"]
        body = {"contact": {"rows": {"email": {"source": "egen", "value": "", "shown": row}}}}
        self._assert_problem(self._patch(legacy, body), 403, "contact-forbidden")
        self.assertEqual(self._state()["email"], "gard@example.invalid")
        # the form showed no alternative (Anna had no e-mail then); hers would appear now
        main = self._main_user()
        db.Member.update(email=None).where(db.Member.id == self.main.id).execute()
        shown, rows = self._form(main)
        db.Member.update(email="anna@example.invalid").where(db.Member.id == self.main.id).execute()
        body = {"contact": {"shown": shown, "rows": {"email": {"source": "egen", "value": "", "shown": rows["email"]}}}}
        self._assert_problem(self._patch(main, body), 409, "contact-changed")
        self.assertEqual(self._state()["email"], "gard@example.invalid")
        # the form showed hers: the row is fetched, and hidden until someone chooses to show it
        shown, rows = self._form(main)
        body = {"contact": {"shown": shown, "rows": {"email": {"source": "egen", "value": "", "shown": rows["email"]}}}}
        self.assertEqual(self._patch(main, body).status_code, 200)
        self.assertEqual((self._state()["email"], self._state()["email_privacy"]), (None, "private"))

    def test_cleared_own_row_equal_to_the_register_is_fetched(self):
        """O2: an own mobile equal to the contact person's has no alternative. A reader clears it: the row is
        fetched, shows the same value and keeps its privacy."""
        self._set(mobile_phone="070-111 11 11", mobile_phone_privacy="authenticated")
        main = self._main_user()
        shown, rows = self._form(main)
        self.assertEqual((rows["mobile_phone"]["source"], rows["mobile_phone"]["alternative"]), ("egen", None))
        row = {"source": "egen", "value": None, "shown": rows["mobile_phone"]}
        response = self._patch(main, {"contact": {"shown": shown, "rows": {"mobile_phone": row}}})
        self.assertEqual(response.status_code, 200, response.data)
        state = self._state()
        self.assertEqual((state["mobile_phone"], state["mobile_phone_privacy"]), (None, "authenticated"))
        data = self._read(main)
        source = data["contact"]["rows"]["mobile_phone"]["source"]
        self.assertEqual((source, data["mobile_phone"]), ("person", "070-111 11 11"))


class TestContactPerson(HerdContactWriteTest):
    def _to_person(self, shown, person_id):
        return {"contact": {"contact_member": person_id, "name": None, "shown": shown, "rows": {}}}

    def _to_fritext(self, shown, name="Gårdens Kontakt"):
        return {"contact": {"contact_member": None, "name": name, "shown": shown, "rows": {}}}

    def test_person_change_after_fritext_rename_conflicts(self):
        self.herd = self._compare(self.herd, name="Gårdens Kontakt", pending=["name"])
        main = self._main_user()
        shown, _ = self._form(main)
        self.assertEqual(shown, {"mode": "fritext", "contact_member": None, "name": "Gårdens Kontakt"})
        response = self._patch(main, self._to_fritext(shown, "Gårdens Kontakt AB"))  # the first form
        self.assertEqual(response.status_code, 200, response.data)
        self._assert_problem(self._patch(main, self._to_person(shown, self.main.id)), 409, "contact-changed")
        state = self._state()
        self.assertEqual((state["contact_member_id"], state["name"]), (None, "Gårdens Kontakt AB"))

    def test_guessed_main_member_id_gets_the_same_refusal(self):
        """A non-chooser who guesses the main member's id next to "Använd medlemskapets" on a fritext name gets the
        same 403 for a right and a wrong guess."""
        self.herd = self._compare(self.herd, name="Gårdens Kontakt", pending=["name"])
        caretaker_user = self._user("caretaker")
        caretaker = self._person("Kim", "Exempel", "skotare", user=caretaker_user)
        db.HerdAccessGrant.create(member=caretaker, herd=self.herd, granted_by=self.admin)
        for user in (self._legacy_owner(), caretaker_user):
            data = self._read(user)
            shown = {"mode": "fritext", "contact_member": None, "name": "Gårdens Kontakt"}
            row = {**data["contact"]["rows"]["name"], "value": data.get("name"), "alternative": None}
            for guess in (self.main.id, self.family.id):
                with self.subTest(user=user.username, guess=guess):
                    body = {"contact_member": guess, "name": None, "shown": shown}
                    body["rows"] = {"name": {"source": "medlemskap", "shown": row}}
                    self._assert_problem(self._patch(user, {"contact": body}), 403, "contact-forbidden")
                    self.assertEqual(self._state()["name"], "Gårdens Kontakt")

    def test_stale_privacy_conflicts(self):
        main = self._main_user()
        shown, rows = self._form(main)
        self.assertEqual(rows["mobile_phone"]["privacy"], "authenticated")
        self._set(mobile_phone_privacy="private")  # someone hides the number
        body = {
            "shown": shown,
            "rows": {"mobile_phone": {"source": "medlemskap", "privacy": "public", "shown": rows["mobile_phone"]}},
        }
        self._assert_problem(self._patch(main, {"contact": body}), 409, "contact-changed")
        self.assertEqual(self._state()["mobile_phone_privacy"], "private")

    def test_contact_member_must_be_active_person_on_membership(self):
        main = self._main_user()
        stranger = db.Member.create(
            membership=db.Membership.create(member_number=8), first_name="Per", last_name="Prov", role="huvudmedlem"
        )
        ended = self._person("Ola", "Exempel", "familjemedlem")
        db.Member.update(end_date=date.today()).where(db.Member.id == ended.id).execute()
        shown, _ = self._form(main)
        for target in (stranger.id, ended.id, 999999):
            with self.subTest(target=target):
                response = self._patch(main, self._to_person(shown, target))
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(self._state()["contact_member_id"], self.main.id)
        response = self._patch(self.admin, self._to_person(shown, stranger.id), admin=True)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self._state()["contact_member_id"], self.main.id)

    def test_change_contact_requires_main_member_manager_or_admin(self):
        family_user = self._user("familyuser", self.family)
        db.HerdAccessGrant.create(member=self.family, herd=self.herd, granted_by=self.admin)
        caretaker_user = self._user("caretaker")
        caretaker = self._person("Kim", "Exempel", "skotare", user=caretaker_user)
        db.HerdAccessGrant.create(member=caretaker, herd=self.herd, granted_by=self.admin)
        for user in (family_user, caretaker_user):
            shown, _ = self._form(user)
            for body in (self._to_person(shown, self.family.id), self._to_fritext(shown)):
                with self.subTest(user=user.username, body=body):
                    self._assert_problem(self._patch(user, body), 403, "contact-forbidden")
                    self.assertEqual(self._state()["contact_member_id"], self.main.id)
        # from fritext to a person, also with "Använd medlemskapets" on the name
        self.herd = self._compare(self.herd, name="Gårdens Kontakt", pending=["name"])
        for user in (family_user, caretaker_user):
            shown, rows = self._form(user)
            use = {
                "shown": shown,
                "rows": {"name": {"source": "medlemskap", "answer": "anvand", "shown": rows["name"]}},
            }
            for body in (self._to_person(shown, self.family.id), {"contact": use}):
                with self.subTest(user=user.username, body=body):
                    self._assert_problem(self._patch(user, body), 403, "contact-forbidden")
                    state = self._state()
                    self.assertEqual((state["contact_member_id"], state["name"]), (None, "Gårdens Kontakt"))
        # renaming the fritext contact edits the herd's own row: anyone who may edit the herd
        shown, _ = self._form(caretaker_user)
        response = self._patch(caretaker_user, self._to_fritext(shown, "Gårdens Kontakt AB"))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._state()["name"], "Gårdens Kontakt AB")
        # the main member, the genebank's manager (admin route) and admin choose
        main_user = self._main_user()
        shown, rows = self._form(main_user)
        # the rename above answered the question; "Använd medlemskapets" is the row's own choice now
        use = {"shown": shown, "rows": {"name": {"source": "medlemskap", "shown": rows["name"]}}}
        response = self._patch(main_user, {"contact": use})
        self.assertEqual(response.status_code, 200, response.data)
        state = self._state()
        self.assertEqual(
            (state["contact_member_id"], state["name"], state["contact_pending"]), (self.main.id, None, [])
        )
        shown, _ = self._form(self.manager)
        response = self._patch(self.manager, self._to_person(shown, self.family.id), admin=True)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._state()["contact_member_id"], self.family.id)
        shown, _ = self._form(self.admin)
        response = self._patch(self.admin, self._to_fritext(shown, "Annan Kontakt"))
        self.assertEqual(response.status_code, 200, response.data)
        state = self._state()
        self.assertEqual((state["contact_member_id"], state["name"]), (None, "Annan Kontakt"))

    def test_person_change_with_empty_rows(self):
        # e-mail fetched from Anna on "authenticated"; an own mobile equal to Ida's number
        self._set(email_privacy="authenticated", mobile_phone="073-222 22 22", mobile_phone_privacy="authenticated")
        main = self._main_user()
        other = self._user("other")
        shown, _ = self._form(main)
        response = self._patch(main, self._to_person(shown, self.family.id))
        self.assertEqual(response.status_code, 200, response.data)
        state = self._state()
        self.assertEqual(state["contact_member_id"], self.family.id)
        self.assertEqual(state["email_privacy"], "private")  # another e-mail is shown now
        self.assertIsNone(state["mobile_phone"])  # the own row equal to Ida's number is fetched now
        self.assertEqual(state["mobile_phone_privacy"], "authenticated")  # the same number is shown
        seen = self._read(other)
        self.assertNotIn("email", seen)
        self.assertEqual(seen["mobile_phone"], "073-222 22 22")
        # back to Anna, who has the same e-mail as Ida now: the choice is kept
        db.Member.update(email="ida@example.invalid").where(db.Member.id == self.main.id).execute()
        self._set(email_privacy="authenticated")
        shown, _ = self._form(main)
        response = self._patch(main, self._to_person(shown, self.main.id))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._state()["email_privacy"], "authenticated")
        self.assertEqual(self._read(other)["email"], "ida@example.invalid")

    def test_person_change_between_empty_mobiles_starts_hidden(self):
        """An empty person row keeps no choice across a change of contact person (the rule of the lifecycle's
        on_person_leaving): else the new contact's first number would show with the choice made for the earlier
        one's."""
        db.Member.update(phone=None).where(db.Member.id.in_([self.main.id, self.family.id])).execute()
        main = self._main_user()
        other = self._user("other")
        shown, rows = self._form(main)
        self.assertEqual((rows["mobile_phone"]["value"], rows["mobile_phone"]["privacy"]), (None, "authenticated"))
        response = self._patch(main, self._to_person(shown, self.family.id))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._state()["mobile_phone_privacy"], "private")
        db.Member.update(phone="073-123 45 67").where(db.Member.id == self.family.id).execute()
        self.assertIsNone(self._read(other).get("mobile_phone"))

    def test_switch_to_fritext_hides_the_empty_rows(self):
        """The rows of a fritext contact are own: an empty mobile keeps no choice from the person before, or the
        number the breeder types later would show to others without anyone choosing that."""
        db.Member.update(phone=None).where(db.Member.id == self.main.id).execute()
        main = self._main_user()
        other = self._user("other")
        shown, rows = self._form(main)
        self.assertEqual((rows["mobile_phone"]["value"], rows["mobile_phone"]["privacy"]), (None, "authenticated"))
        response = self._patch(main, self._to_fritext(shown))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._state()["mobile_phone_privacy"], "private")
        shown, rows = self._form(main)
        typed = {"source": "egen", "value": "070-555 55 55", "shown": rows["mobile_phone"]}
        response = self._patch(main, {"contact": {"rows": {"mobile_phone": typed}}})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._state()["mobile_phone"], "070-555 55 55")
        self.assertIsNone(self._read(other).get("mobile_phone"))


class TestGeneralCalls(HerdContactWriteTest):
    def test_flat_contact_fields_rejected(self):
        main = self._main_user()
        before = self._state()
        bodies = (
            {"email": "ny@example.invalid", "www": "ny-www"},
            {"email_privacy": "public", "www": "ny-www"},
            {"name": "Ny Kontakt"},
            {"physical_address_privacy": "public"},
        )
        for body in bodies:
            with self.subTest(body=body):
                self.assertEqual(self._patch(main, body).status_code, 400)
                self.assertEqual(self._state(), before)
                self.assertEqual(self._patch(self.admin, body, admin=True).status_code, 400)
                self.assertEqual(self._state(), before)
        # the plumbing columns in a general call are not written; the call's other fields are
        other = db.Membership.create(member_number=8)
        plumbing = {"contact_member": self.family.id, "contact_pending": ["email"], "membership": other.id}
        for user in (main, self.admin):
            with self.subTest(user=user.username):
                response = self._patch(user, {"www": f"www-{user.id}", **plumbing})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(self._state(), {**before, "www": f"www-{user.id}"})
        self.assertEqual(self._patch(self.admin, plumbing, admin=True).status_code, 400)  # not in the allow-list
        self.assertEqual(self._state(), {**before, "www": f"www-{self.admin.id}"})
        # a herd not compared with the register takes flat fields as today
        response = self._client(self.admin).patch(
            f"/api/v2/herd/{self.herds[1].herd}", json={"email": "ny@example.invalid"}
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(db.Herd.get_by_id(self.herds[1].id).email, "ny@example.invalid")


class TestReviewRound1(HerdContactWriteTest):
    """Codex review of Task 4, round 1."""

    def test_typed_register_value_becomes_fetched_and_hidden(self):
        """F1: an own row a reader sets equal to the register's value is fetched, and the household's value is
        hidden like any other row that goes from own to fetched, whatever privacy the form sent."""
        self._set(physical_address=FARM, physical_address_privacy="authenticated")
        self._set(email="gard@example.invalid", email_privacy="authenticated")
        main = self._main_user()
        other = self._user("other")
        shown, rows = self._form(main)
        address = {"source": "egen", "value": HOME, "privacy": "authenticated", "shown": rows["physical_address"]}
        email = {"source": "egen", "value": "anna@example.invalid", "shown": rows["email"]}  # no privacy sent
        response = self._patch(
            main, {"contact": {"shown": shown, "rows": {"physical_address": address, "email": email}}}
        )
        self.assertEqual(response.status_code, 200, response.data)
        state = self._state()
        self.assertEqual((state["physical_address"], state["physical_address_privacy"]), (None, "private"))
        self.assertEqual((state["email"], state["email_privacy"]), (None, "private"))
        seen = self._read(other)
        self.assertNotIn("physical_address", seen)
        self.assertNotIn("email", seen)

    def test_omitted_value_keeps_the_own_row(self):
        """F2: "Ja, behåll" or a privacy change without `value` keeps the own value; an explicit empty value
        next to "Ja, behåll" contradicts it."""
        self._set(email="gard@example.invalid", email_privacy="private", contact_pending=["email"])
        main = self._main_user()
        shown, rows = self._form(main)
        keep = {"source": "egen", "answer": "behall", "shown": rows["email"]}
        response = self._patch(main, {"contact": {"shown": shown, "rows": {"email": keep}}})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((self._state()["email"], self._state()["contact_pending"]), ("gard@example.invalid", []))
        # a privacy change only, from the main member and from an account with only the old owner role
        shown, rows = self._form(main)
        body = {
            "shown": shown,
            "rows": {"email": {"source": "egen", "privacy": "authenticated", "shown": rows["email"]}},
        }
        self.assertEqual(self._patch(main, {"contact": body}).status_code, 200)
        self.assertEqual(
            (self._state()["email"], self._state()["email_privacy"]), ("gard@example.invalid", "authenticated")
        )
        legacy = self._legacy_owner()
        row = self._read(legacy)["contact"]["rows"]["email"]
        body = {"rows": {"email": {"source": "egen", "privacy": "private", "shown": row}}}
        self.assertEqual(self._patch(legacy, {"contact": body}).status_code, 200)
        self.assertEqual((self._state()["email"], self._state()["email_privacy"]), ("gard@example.invalid", "private"))
        # contradictory instructions are refused before anything is written
        self._set(contact_pending=["email"])
        before = self._state()
        shown, rows = self._form(main)
        for row in (
            {"source": "egen", "value": "", "answer": "behall", "shown": rows["email"]},
            {"source": "medlemskap", "value": "annan@example.invalid", "shown": rows["email"]},  # an own row
        ):
            with self.subTest(row=row):
                self.assertEqual(
                    self._patch(main, {"contact": {"shown": shown, "rows": {"email": row}}}).status_code, 400
                )
                self.assertEqual(self._state(), before)

    def test_echo_of_person_name_changes_nothing(self):
        """F3: the contact person's name sent back as an own value is an echo, not a change to fritext."""
        main = self._main_user()
        legacy = self._legacy_owner()
        before, seen = self._state(), self._read(legacy)
        shown, rows = self._form(main)
        echo = {"source": "egen", "value": "anna  exempel", "privacy": "private", "shown": rows["name"]}
        for top in ({}, {"contact_member": self.main.id, "name": None}):
            with self.subTest(top=top):
                response = self._patch(main, {"contact": {**top, "shown": shown, "rows": {"name": echo}}})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(self._state(), before)
                self.assertEqual(self._read(legacy), seen)

    def test_manager_moved_out_of_the_genebank_meanwhile(self):
        """F4: the admin route decides the manager's right on the locked herd, and answers from it."""
        self._set(email_privacy="authenticated")
        before = self._state()
        resolve = herdbook._resolve_admin_herd

        def resolve_then_move(h_ref):
            herd = resolve(h_ref)  # the route checks this copy; an admin moves the herd before the lock
            db.Herd.update(genebank=self.genebanks[1]).where(db.Herd.id == herd.id).execute()
            return herd

        with patch.object(herdbook, "_resolve_admin_herd", resolve_then_move):
            response = self._patch(self.manager, {"www": "ny-www"}, admin=True)
        self._assert_problem(response, 403, "manager-of-genebank-required")
        self.assertEqual(self._state(), before)
        self.assertNotIn("anna@example.invalid", response.get_data(as_text=True))

    def test_reader_corrects_own_row_with_short_shown(self):
        """F5: the short shown (source, value, privacy) works for a reader too while the row stays own."""
        self._set(email="gard@example.invalid", email_privacy="private")
        main = self._main_user()
        self.assertEqual(self._form(main)[1]["email"]["alternative"], "anna@example.invalid")
        short = {"source": "egen", "value": "gard@example.invalid", "privacy": "private"}
        body = {"rows": {"email": {"source": "egen", "value": "gard2@example.invalid", "shown": short}}}
        response = self._patch(main, {"contact": body})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._state()["email"], "gard2@example.invalid")


class TestReviewRound2(HerdContactWriteTest):
    """Codex review of Task 4, round 2."""

    def test_kept_own_value_equal_to_the_register_stays_own(self):
        """R2-1: an own value kept by a privacy change or "Ja, behåll" is not one the user sent: it is not turned
        into the register's row even when it equals the contact person's."""
        self._set(email="anna@example.invalid", email_privacy="private", contact_pending=["email"])
        main = self._main_user()
        for label, change in (("privacy", {"privacy": "authenticated"}), ("behall", {"answer": "behall"})):
            with self.subTest(label):
                shown, rows = self._form(main)
                row = {"source": "egen", **change, "shown": rows["email"]}
                response = self._patch(main, {"contact": {"shown": shown, "rows": {"email": row}}})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(self._state()["email"], "anna@example.invalid")
                self.assertEqual(self._read(main)["contact"]["rows"]["email"]["source"], "egen")
        self.assertEqual(self._state()["email_privacy"], "authenticated")
        self.assertEqual(self._state()["contact_pending"], [])

    def test_echo_of_fetched_row_with_its_value(self):
        """R2-4: a fetched row sent back with the value it shows changes nothing, and the call's other fields are
        saved; another value on a "medlemskap" row is refused."""
        main = self._main_user()
        shown, rows = self._form(main)
        before = self._state()
        echo = {"source": "medlemskap", "value": " ANNA@example.invalid", "privacy": "private", "shown": rows["email"]}
        response = self._patch(main, {"www": "ny-www", "contact": {"shown": shown, "rows": {"email": echo}}})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._state(), {**before, "www": "ny-www"})
        other = {**echo, "value": "annan@example.invalid"}
        response = self._patch(main, {"www": "annan-www", "contact": {"shown": shown, "rows": {"email": other}}})
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self._state(), {**before, "www": "ny-www"})


class TestReviewRound3(HerdContactWriteTest):
    def test_unchanged_own_value_is_not_fetched(self):
        """R3: only an own value the call changes is turned into the register's row when equal to it. "Ja, behåll"
        with or without the value, or a privacy change echoing it, keeps the farm's own e-mail, also after the
        person changes hers in the register."""
        self._set(email="anna@example.invalid", email_privacy="authenticated")
        main = self._main_user()
        other = self._user("other")
        cases = (
            ("behall with value", {"value": "anna@example.invalid", "answer": "behall"}),
            ("behall without value", {"answer": "behall"}),
            ("privacy echoing value", {"value": "Anna@example.invalid", "privacy": "authenticated"}),
        )
        for label, change in cases:
            with self.subTest(label):
                self._set(contact_pending=["email"])
                shown, rows = self._form(main)
                row = {"source": "egen", **change, "shown": rows["email"]}
                response = self._patch(main, {"contact": {"shown": shown, "rows": {"email": row}}})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertIsNotNone(self._state()["email"])
                self.assertEqual(self._read(main)["contact"]["rows"]["email"]["source"], "egen")
        db.Member.update(email="anna.ny@example.invalid").where(db.Member.id == self.main.id).execute()
        self.assertEqual(self._read(other)["email"].lower(), "anna@example.invalid")


@unittest.skipUnless(_USE_POSTGRES, "FOR UPDATE serialisation needs PostgreSQL")
class TestConcurrentWrites(HerdContactWriteTest):
    def _race(self, first, second):
        """Run `first` until it saves the herd (its locks held), start `second`, check that it waits for them,
        then let both finish. Returns their responses."""
        entered, release, second_done = threading.Event(), threading.Event(), threading.Event()
        original_save = db.Herd.save
        herd_id = self.herd.id
        responses, failures = {}, []

        def paused_save(row, *args, **kwargs):
            if row.id == herd_id and not entered.is_set():
                entered.set()
                assert release.wait(timeout=10), "the test never released the paused PATCH"
            return original_save(row, *args, **kwargs)

        def run(key, call):
            try:
                responses[key] = call()
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(exc)
            finally:
                if key == "second":
                    second_done.set()

        with patch.object(db.Herd, "save", paused_save):
            one = threading.Thread(target=run, args=("first", first))
            one.start()
            self.assertTrue(entered.wait(timeout=10), "the first PATCH never reached its save")
            two = threading.Thread(target=run, args=("second", second))
            two.start()
            self.assertFalse(second_done.wait(1.5), "the second PATCH finished while the first held the locks")
            release.set()
            one.join(timeout=15)
            two.join(timeout=15)
        for thread in (one, two):
            self.assertFalse(thread.is_alive(), "worker still blocked after the join timeout — a lock never released")
        self.assertEqual(failures, [])
        return responses["first"], responses["second"]

    def test_concurrent_widen_and_source_switch(self):
        main = self._main_user()
        other = self._user("other")
        url = f"/api/v2/herd/{self.herd.herd}"
        for order in (("switch", "widen"), ("widen", "switch")):
            with self.subTest(order=order):
                self._set(physical_address=FARM, physical_address_privacy="private", contact_pending=[])
                shown, rows = self._form(main)
                self.assertEqual(rows["physical_address"]["alternative"], HOME)
                bodies = {
                    # one form: the household's address
                    "switch": {"source": "medlemskap", "privacy": "private", "shown": rows["physical_address"]},
                    # the other: the farm's address for all logged-in members
                    "widen": {
                        "source": "egen",
                        "value": FARM,
                        "privacy": "authenticated",
                        "shown": rows["physical_address"],
                    },
                }
                requests = [
                    (self._client(main), {"contact": {"shown": shown, "rows": {"physical_address": bodies[key]}}})
                    for key in order
                ]
                first, second = self._race(*(lambda c=c, b=b: c.patch(url, json=b) for c, b in requests))
                self.assertEqual(first.status_code, 200, first.data)
                self._assert_problem(second, 409, "contact-changed")
                self.assertNotEqual(self._read(other).get("physical_address"), HOME)


if __name__ == "__main__":
    unittest.main()
