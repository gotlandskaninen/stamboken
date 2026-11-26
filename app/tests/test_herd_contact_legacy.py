"""The old app's write path, PATCH /api/manage/herd, on a herd linked to a membership (#117, spec: Gamla appen).

The old app sends back the whole herd it read, also fields that were hidden from the reader. Every body here is
built like that: from the same user's GET /api/herd/<h_id>."""

import utils.database as db  # noqa: E402
from utils.herd_contact import LEGACY_EMPTY_ADDRESSES  # noqa: E402

from tests.test_herd_contact_write import STATE, HerdContactWriteTest  # noqa: E402

REFUSED = {
    "status": "error",
    "message": "Kontaktuppgifterna ändras i nya Stamboken. Har du inte tillgång där, kontakta genbanksansvarig.",
}
COLUMNS = (*STATE, "herd_name")


class HerdContactLegacyTest(HerdContactWriteTest):
    def _legacy_save(self, user, herd=None, **changes):
        """What the old app sends: the user's own read of the herd, with `changes`, back to its route."""
        client = self._client(user)
        body = client.get(f"/api/herd/{(herd or self.herd).herd}").get_json()
        body.pop("individuals")
        body.update(changes)
        response = client.patch("/api/manage/herd", json=body)
        self.assertEqual(response.status_code, 200, response.data)
        return response.get_json()

    def _columns(self, herd=None):
        """The herd's columns, and its membership's account, which the old app still sends as the herd's."""
        row = db.Herd.get_by_id((herd or self.herd).id)
        account = db.Membership.get_by_id(row.membership_id).bank_account_number if row.membership_id else None
        return {**{column: getattr(row, column) for column in COLUMNS}, "bank_account_number": account}


class TestLegacyWrites(HerdContactLegacyTest):
    def test_legacy_echo_accepted(self):
        """An echo of what the user read, derived rows included, saves the bank account and makes no own copies.
        The account is the membership's: a legacy owner privilege does not change it (U2)."""
        for user in (self._main_user(), self.admin):
            with self.subTest(user=user.username):
                before = self._columns()
                account = f"1234-{user.id:07d}"
                self.assertEqual(self._legacy_save(user, bank_account_number=account), {"status": "updated"})
                self.assertEqual(self._columns(), {**before, "bank_account_number": account})
        before, legacy = self._columns(), self._legacy_owner()
        self.assertEqual(self._legacy_save(legacy, herd_name="Ny"), {"status": "updated"})
        forbidden = {"status": "error", "message": "Forbidden"}
        self.assertEqual(self._legacy_save(legacy, bank_account_number="1234-5678901"), forbidden)
        self.assertEqual(self._columns(), {**before, "herd_name": "Ny"})

    def test_legacy_hidden_address_echo_forms(self):
        """Granskningsfokus 4: the household's address is hidden from the old owner role; the old app sends it back
        as "||" (årsrapporten), "undefined||" (the herd form) or not at all. Each is an echo."""
        legacy = self._legacy_owner()
        read = self._read(legacy)
        self.assertNotIn("physical_address", read)
        self.assertNotIn("email", read)
        # absent, as the old app's JSON drops an undefined field; an empty hidden e-mail is an echo too
        forms = [("physical_address", "||"), ("physical_address", "undefined||"), (None, None)]
        forms += [("email", ""), ("email", None)]
        for i, (field, form) in enumerate(forms):
            with self.subTest(field=field, form=form):
                before = self._columns()
                sent = {} if field is None else {field: form}
                self.assertEqual(self._legacy_save(legacy, herd_name=f"Ny {i}", **sent), {"status": "updated"})
                self.assertEqual(self._columns(), {**before, "herd_name": f"Ny {i}"})

    def test_legacy_empty_forms_of_a_shown_empty_address_are_an_echo(self):
        """A visible empty address comes back as "||", or as "null||" from the herd view (null joined as text)."""
        self._set(physical_address_privacy="authenticated")
        db.Membership.update(address=None, postal_code=None, city=None).where(
            db.Membership.id == self.membership.id
        ).execute()
        main = self._main_user()
        self.assertIsNone(self._read(main)["physical_address"])
        for form in ("||", "undefined||", "null||", "", None):
            with self.subTest(form=form):
                before = self._columns()
                self.assertEqual(self._legacy_save(main, physical_address=form), {"status": "updated"})
                self.assertEqual(self._columns(), before)

    def test_legacy_echo_of_a_stored_empty_marker(self):
        """An own address saved as an empty marker before the link reads back as that text, and the old app sends
        it back as it is: an echo, so a bank-only save goes through and the column keeps its bytes."""
        main = self._main_user()
        for marker in LEGACY_EMPTY_ADDRESSES:
            with self.subTest(marker=marker):
                self._set(physical_address=marker)
                self.assertEqual(self._read(main)["physical_address"], marker)
                before = self._columns()
                account = f"1234-{len(marker):07d}"
                self.assertEqual(self._legacy_save(main, bank_account_number=account), {"status": "updated"})
                self.assertEqual(self._columns(), {**before, "bank_account_number": account})

    def test_legacy_changed_contact_field_rejected(self):
        """A new value, also an emptied one, for any of the six contact fields: the error, and nothing in the call
        is saved, the bank account, herd name and a narrower privacy included."""
        self._set(email="gard@example.invalid")  # an own row is not changed either
        main = self._main_user()
        changes = {
            "name": "Nils Nyman",
            "email": "ny@example.invalid",
            "mobile_phone": "070-999 99 99",
            "wire_phone": "0498-12 34 56",
            "physical_address": "Nyvägen 2|62300|Roma",
            "www": "ny.example.invalid",
        }
        emptied = {"name": "", "email": "", "mobile_phone": None, "physical_address": "||", "www": ""}
        before = self._columns()
        for field, value in [*changes.items(), *emptied.items(), ("email", 5)]:  # not text: changed, not a 500
            with self.subTest(field=field, value=value):
                response = self._legacy_save(
                    main,
                    herd_name="Ny",
                    bank_account_number="9999-1234567",
                    mobile_phone_privacy="private",
                    **{field: value},
                )
                self.assertEqual(response, REFUSED)
                self.assertEqual(self._columns(), before)

    def test_legacy_guess_gives_same_error(self):
        """A value for a field hidden from the user is refused the same way whether it is the register's or not."""
        legacy = self._legacy_owner()
        self.assertNotIn("email", self._read(legacy))
        before = self._columns()
        answers = [
            self._legacy_save(legacy, email=guess, herd_name="Ny")
            for guess in ("anna@example.invalid", " ANNA@example.invalid", "fel@example.invalid")
        ]
        self.assertEqual(answers, [REFUSED] * 3)
        self.assertEqual(self._columns(), before)

    def test_legacy_privacy_only_narrower(self):
        """Old årsrapporten sends all six privacy choices as "authenticated": only a narrower or equal one is
        saved, a wider one is ignored without an error, and NULL counts as private."""
        self._set(www_privacy="public", wire_phone_privacy=None)
        main = self._main_user()
        before = self._columns()
        six = ("name", "email", "mobile_phone", "wire_phone", "physical_address", "www")
        response = self._legacy_save(
            main, bank_account_number="1234-5678901", **{f"{f}_privacy": "authenticated" for f in six}
        )
        self.assertEqual(response, {"status": "updated"})
        self.assertEqual(
            self._columns(),
            {**before, "bank_account_number": "1234-5678901", "www_privacy": "authenticated"},
        )
        # narrower: saved
        self.assertEqual(self._legacy_save(main, mobile_phone_privacy="private"), {"status": "updated"})
        self.assertEqual(db.Herd.get_by_id(self.herd.id).mobile_phone_privacy, "private")
        # wider: ignored
        self.assertEqual(self._legacy_save(main, email_privacy="public"), {"status": "updated"})
        self.assertEqual(db.Herd.get_by_id(self.herd.id).email_privacy, "private")

    def test_legacy_unlinked_herd_as_today(self):
        """A herd without a membership saves every contact field and any privacy, as before #117."""
        unlinked = self.herds[1]  # G2
        changes = {
            "name": "Nils Nyman",
            "email": "ny@example.invalid",
            "mobile_phone": "070-999 99 99",
            "wire_phone": "0498-12 34 56",
            "physical_address": "Nyvägen 2|62300|Roma",
            "www": "ny.example.invalid",
            "www_privacy": "public",  # wider than the stored "private"
            "name_privacy": "public",
        }
        self.assertEqual(self._legacy_save(self.admin, herd=unlinked, **changes), {"status": "updated"})
        stored = db.Herd.get_by_id(unlinked.id)
        self.assertEqual({k: getattr(stored, k) for k in changes}, changes)

    def test_legacy_linked_uncompared_herd_keeps_contact(self):
        """The rule keys on the membership, not on the comparison: a linked herd not yet compared is closed too."""
        unlinked = self.herds[1]
        db.Herd.update(membership=self.membership).where(db.Herd.id == unlinked.id).execute()
        before = self._columns(unlinked)
        self.assertEqual(self._legacy_save(self.admin, herd=unlinked, email="ny@example.invalid"), REFUSED)
        self.assertEqual(self._columns(unlinked), before)
        self.assertEqual(self._legacy_save(self.admin, herd=unlinked, herd_name="Ny"), {"status": "updated"})
        self.assertEqual(self._columns(unlinked), {**before, "herd_name": "Ny"})
