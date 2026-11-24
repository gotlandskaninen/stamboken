"""The read paths of a herd's contact: values resolved from the member register, `contact` for those entitled (#117)."""

import json
import os

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from herdbook import APP, limiter  # noqa: E402
from utils.herd_contact import matrikel_reader_herd_ids  # noqa: E402

from tests.ht_helpers import count_queries  # noqa: E402
from tests.test_herd_contact import HerdContactTest  # noqa: E402

ADDRESS = "Byvägen 1|62300|Roma"


class HerdContactReadTest(HerdContactTest):
    def setUp(self):
        APP.config["TESTING"] = True  # nosemgrep
        APP.config["SESSION_COOKIE_NAME"] = "test_session"
        limiter.enabled = False
        self.app = APP.test_client(use_cookies=True)
        super().setUp()
        # a derived e-mail on "private", a derived mobile on "authenticated"; the own name stays private
        db.Herd.update(email_privacy="private", mobile_phone_privacy="authenticated", name_privacy="private").where(
            db.Herd.id == self.herd.id
        ).execute()
        self.herd = self._compare(self.herd, contact=self.main)

    def _user(self, name, person=None, herd_roles=True):
        user = da.register_user(f"{name}@example.invalid", "pass", username=name)
        if herd_roles:
            user.add_role("viewer", self.genebanks[0].id)
        if person is not None:
            db.Member.update(user=user).where(db.Member.id == person.id).execute()
        return user

    def _get(self, user, url):
        with APP.test_client(use_cookies=True) as ctx:  # a client of its own: the session cookie is per user
            ctx.post("/api/login", json={"username": user.email, "password": "pass"})
            response = ctx.get(url)
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def _legacy_owner(self):
        user = self._user("legacy")
        user.add_role("owner", self.herd.id)
        return user


class TestLegacyHerdRead(HerdContactReadTest):
    def test_legacy_herd_read_keeps_fields_and_format(self):
        main_user = self._user("mainuser", self.main)
        other = self._user("other")
        owner_data = self._get(main_user, f"/api/herd/{self.herd.herd}")
        other_data = self._get(other, f"/api/herd/{self.herd.herd}")
        for data in (owner_data, other_data):
            self.assertNotIn("contact_member_id", data)
            self.assertNotIn("contact_member", data)
            self.assertNotIn("contact_pending", data)
            self.assertNotIn("membership", data)
        self.assertEqual(owner_data["physical_address"], ADDRESS)
        self.assertEqual(owner_data["email"], "anna@example.invalid")
        self.assertIn("contact", owner_data)
        self.assertNotIn("contact", other_data)
        # a hidden field is absent, the others as before
        self.assertNotIn("email", other_data)  # derived, "private"
        self.assertEqual(other_data["mobile_phone"], "070-111 11 11")
        self.assertNotIn("name", other_data)
        self.assertEqual(set(other_data) - {"individuals"}, set(other_data) - {"individuals", "contact"})
        self.assertEqual(
            owner_data["contact"]["rows"]["email"],
            {"source": "person", "privacy": "private", "pending": False, "alternative": None},
        )
        self.assertEqual(owner_data["contact"]["mode"], "person")
        self.assertEqual(
            owner_data["contact"]["contact_member"], {"id": self.main.id, "name": "Anna Exempel", "role": "huvudmedlem"}
        )
        self.assertEqual(
            owner_data["contact"]["persons"],
            [
                {"id": self.main.id, "name": "Anna Exempel", "role": "huvudmedlem"},
                {"id": self.family.id, "name": "Ida Exempel", "role": "familjemedlem"},
            ],
        )

    def test_derived_row_hidden_for_legacy_owner_only(self):
        main_user = self._user("mainuser", self.main)
        legacy = self._legacy_owner()
        self.assertEqual(self._get(main_user, f"/api/herd/{self.herd.herd}")["email"], "anna@example.invalid")
        data = self._get(legacy, f"/api/herd/{self.herd.herd}")
        self.assertNotIn("email", data)
        self.assertEqual(data["mobile_phone"], "070-111 11 11")
        self.assertEqual(data["www"], "www1")  # the account's own rows read as today
        self.assertEqual(set(data["contact"]), {"rows"})
        self.assertEqual(data["contact"]["rows"]["email"], {"source": "hamtad"})
        self.assertEqual(data["contact"]["rows"]["name"], {"source": "hamtad"})
        text = json.dumps(data, ensure_ascii=False)
        for secret in ("Anna", "Exempel", "anna@example.invalid", "contact_member"):
            self.assertNotIn(secret, text)

    def test_legacy_owner_sees_own_rows_in_small_contact(self):
        legacy = self._legacy_owner()
        db.Herd.update(email="gard@example.invalid").where(db.Herd.id == self.herd.id).execute()
        rows = self._get(legacy, f"/api/herd/{self.herd.herd}")["contact"]["rows"]
        self.assertEqual(rows["email"], {"source": "egen", "value": "gard@example.invalid", "privacy": "private"})

    def test_family_member_reads_derived_rows(self):
        family_user = self._user("familyuser", self.family)
        self.assertNotIn(self.herd.id, family_user.effective_herd_ids())
        data = self._get(family_user, f"/api/herd/{self.herd.herd}")
        self.assertEqual(data["email"], "anna@example.invalid")  # derived, "private"
        self.assertEqual(data["contact"]["mode"], "person")
        self.assertNotIn("persons", data["contact"])  # a family member does not choose the contact

    def test_unlinked_herd_gets_contact_with_own_rows(self):
        user = self._legacy_owner()
        user.add_role("owner", self.herds[1].id)
        data = self._get(user, f"/api/herd/{self.herds[1].herd}")
        self.assertEqual(set(data["contact"]), {"rows"})
        self.assertEqual(data["contact"]["rows"]["email"]["source"], "egen")
        data = self._get(self.admin, f"/api/herd/{self.herds[1].herd}")
        self.assertEqual(data["contact"]["mode"], "ej_jamford")
        self.assertEqual(data["contact"]["rows"]["email"]["source"], "egen")
        self.assertEqual(data["contact"]["rows"]["email"]["privacy"], "public")

    def test_persons_only_for_those_who_choose(self):
        main_user = self._user("mainuser", self.main)
        self.assertEqual(len(self._get(main_user, f"/api/herd/{self.herd.herd}")["contact"]["persons"]), 2)
        self.assertEqual(len(self._get(self.manager, f"/api/herd/{self.herd.herd}")["contact"]["persons"]), 2)
        self.assertEqual(len(self._get(self.admin, f"/api/herd/{self.herd.herd}")["contact"]["persons"]), 2)


class TestGenebankList(HerdContactReadTest):
    def test_genebank_list_has_no_contact_for_legacy_owner(self):
        db.Herd.update(email_privacy="authenticated", mobile_phone_privacy="private").where(
            db.Herd.id == self.herd.id
        ).execute()
        legacy = self._legacy_owner()
        herds = {h["id"]: h for h in self.genebanks[0].get_herds(legacy)}
        data = herds[self.herd.id]
        self.assertEqual(data["email"], "anna@example.invalid")
        self.assertNotIn("mobile_phone", data)
        self.assertNotIn("contact", data)

    def test_get_herds_uses_resolved_values(self):
        herds = {h["id"]: h for h in self.genebanks[0].get_herds(self.admin)}
        self.assertEqual(herds[self.herd.id]["email"], "anna@example.invalid")
        self.assertEqual(herds[self.herd.id]["name"], "Anna Exempel")
        self.assertEqual(herds[self.herd.id]["physical_address"], ADDRESS)

    def test_get_herds_batches_queries(self):
        for i in range(20):
            db.Herd.create(
                genebank=self.genebanks[0],
                herd=f"G{100 + i}",
                membership=self.membership,
                contact_member=self.main,
                contact_pending=[],
            )
        with count_queries() as counter:
            herds = self.genebanks[0].get_herds(self.admin)
        self.assertEqual(len(herds), 22)
        self.assertLessEqual(counter["n"], 8, counter)  # not a few per herd
        self.assertEqual(next(h for h in herds if h["herd"] == "G100")["email"], "anna@example.invalid")
        # the batched reader set agrees with the single one for a family member
        family_user = self._user("familyuser", self.family)
        rows = list(db.Herd.select().where(db.Herd.genebank == self.genebanks[0]))
        with count_queries() as counter:
            ids = matrikel_reader_herd_ids(family_user, rows)
        self.assertLessEqual(counter["n"], 3, counter)
        self.assertEqual(ids, {h.id for h in rows if h.membership_id == self.membership.id})


class TestAdminReads(HerdContactReadTest):
    def test_admin_search_finds_contact_person_name(self):
        result = da.list_all_herds(self.admin, search="Exempel")
        self.assertEqual([h["id"] for h in result["herds"]], [self.herd.id])
        self.assertEqual(result["herds"][0]["name"], "Anna Exempel")

    def test_get_herd_for_admin_resolves_and_has_contact(self):
        data = da.get_herd_for_admin(self.admin, db.Herd.get_by_id(self.herd.id))
        self.assertEqual(data["name"], "Anna Exempel")
        self.assertEqual(data["email"], "anna@example.invalid")
        self.assertEqual(data["physical_address"], ADDRESS)
        self.assertEqual(data["contact"]["mode"], "person")
        self.assertEqual(len(data["contact"]["persons"]), 2)


class TestCaretakerScope(HerdContactReadTest):
    def _caretaker(self):
        user = self._user("caretaker")
        other = db.Membership.create(member_number=9, address="Annanväg 2", postal_code="62200", city="Visby")
        db.Member.create(membership=other, first_name="Per", last_name="Prov", role="huvudmedlem")
        mine = db.Member.create(membership=other, first_name="Kim", last_name="Prov", role="skotare", user=user)
        own_herd = db.Herd.create(genebank=self.genebanks[0], herd="G200", membership=other, contact_pending=[])
        return user, mine, own_herd

    def test_grant_on_another_membership_is_not_read_access(self):
        user, mine, own_herd = self._caretaker()
        db.HerdAccessGrant.create(member=mine, herd=self.herd, granted_by=self.admin)
        db.HerdAccessGrant.create(member=mine, herd=own_herd, granted_by=self.admin)
        rows = list(db.Herd.select().where(db.Herd.genebank == self.genebanks[0]))
        self.assertEqual(matrikel_reader_herd_ids(user, rows), {own_herd.id})
        self.assertEqual(matrikel_reader_herd_ids(user, [db.Herd.get_by_id(self.herd.id)]), set())
        listed = {h["id"]: h for h in self.genebanks[0].get_herds(user)}
        self.assertNotEqual(listed[self.herd.id].get("email"), "anna@example.invalid")
        detail = self._get(user, f"/api/herd/{self.herd.herd}")
        self.assertNotIn("email", detail)  # same visibility as the list: derived, "private"
        self.assertEqual(set(detail["contact"]), {"rows"})  # the grant gives private access, not the register

    def test_caretaker_does_not_learn_main_members_name_in_fritext(self):
        herd = self._compare(self.herd, name="Gårdens Kontakt", pending=["name"])
        caretaker = self._person("Kim", "Exempel", "skotare", user=self._user("caretaker"))
        db.HerdAccessGrant.create(member=caretaker, herd=herd, granted_by=self.admin)
        data = self._get(db.User.get(db.User.username == "caretaker"), f"/api/herd/{herd.herd}")
        self.assertEqual(data["contact"]["mode"], "fritext")
        self.assertNotIn("Anna", json.dumps(data, ensure_ascii=False))
        main = self._user("mainuser", self.main)
        rows = self._get(main, f"/api/herd/{herd.herd}")["contact"]["rows"]
        self.assertEqual(rows["name"]["alternative"], "Anna Exempel")
