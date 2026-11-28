"""Preview and confirmation of a herd link from the member register."""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import utils.database as db
from utils.herd_contact import is_matrikel_reader
from utils.matrikel import _herd_link_preview

from tests.test_person_link_api import LinkApiBase


class TestMembershipHerdLink(LinkApiBase):
    def setUp(self):
        super().setUp()
        self.login("matrikel")
        self.herd = self.herds[1]
        self.url = f"/api/v2/memberships/{self.ms.id}"
        self.invalidate = self.enterContext(patch("utils.matrikel._invalidate_genebanks"))

    def post(self, **fields):
        return self.client.post(f"{self.url}/herds", json={"herd_id": self.herd.id, **fields})

    def preview(self, **fields):
        response = self.post(**fields)
        self.assertEqual(response.status_code, 409, response.data)
        body = response.get_json()
        self.assertEqual(body["type"], "confirm-required")
        self.assertIsNone(db.Herd.get_by_id(self.herd.id).membership_id)
        self.assertFalse(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "herd_membership_linked").exists())
        self.invalidate.assert_not_called()
        return body

    def test_candidates_sorted_by_number_include_inactive_and_linked(self):
        other = db.Membership.create(member_number=17)
        db.Herd.create(herd="G10", genebank=self.genebanks[0], membership=other, is_active=True)
        response = self.client.get(f"{self.url}/herd-candidates?genebank_id={self.genebanks[0].id}")
        self.assertEqual(response.status_code, 200)
        rows = response.get_json()["herds"]
        self.assertEqual(
            [(r["herd"], r["is_active"], r["link"], r["member_number"]) for r in rows],
            [("G1", False, "detta", None), ("G2", False, "ingen", None), ("G10", True, "annat", 17)],
        )
        self.assertIsNone(rows[1]["unavailable_reason"])
        self.assertEqual(rows[1]["id"], self.herd.id)
        self.assertEqual(rows[1]["herd_name"], self.herd.herd_name)

    def test_only_admin_and_matrikel_admin_can_list_or_link(self):
        for username in ("man", "erik.lindqvist"):
            self.login(username)
            self.assertEqual(self.client.get(f"{self.url}/herd-candidates?genebank_id=1").status_code, 403)
            self.assertEqual(self.post().status_code, 403)
        self.login("admin")
        self.preview()

    def test_invalid_input_and_missing_resources(self):
        for suffix in ("", "?genebank_id=bad", "?genebank_id=999999"):
            self.assertEqual(self.client.get(f"{self.url}/herd-candidates{suffix}").status_code, 400)
        for value in (True, "1", None):
            self.assertEqual(self.post(herd_id=value).status_code, 400)
        self.assertEqual(self.post(confirm_token=True).status_code, 400)
        self.assertEqual(self.post(herd_id=999999).status_code, 404)
        self.url = "/api/v2/memberships/999999"
        self.assertEqual(self.client.get(f"{self.url}/herd-candidates?genebank_id=1").status_code, 404)
        self.assertEqual(self.post().status_code, 404)

    def test_confirmed_preview_matches_contact_changes_access_and_audit(self):
        self.main.user = self.account
        self.main.email = "huvud@example.com"
        self.main.phone = "0700000001"
        self.main.save()
        self.herd.name = f"{self.main.first_name} {self.main.last_name}"
        self.herd.email = self.main.email.upper()
        self.herd.mobile_phone = "0700000002"
        self.herd.save()
        self.owner.add_role("owner", self.herd.id)

        body = self.preview()
        preview = body["preview"]
        self.assertEqual(preview["herd"]["genebank_name"], self.genebanks[0].name)
        self.assertEqual(preview["membership"], {"id": self.ms.id, "member_number": 6, "membership_status": "active"})
        self.assertEqual(
            preview["new_access"],
            {
                "id": self.account.id,
                "username": self.account.username,
                "already_edits": False,
                "already_manages": False,
            },
        )
        self.assertEqual(preview["new_readers"], [{"id": self.account.id, "username": self.account.username}])
        self.assertNotIn(self.herd.id, self.account.owned_herd_ids())
        self.assertFalse(is_matrikel_reader(self.account, self.herd))
        self.assertIn(
            f"{self.main.first_name} {self.main.last_name} blir kontaktperson", preview["contact_rows"][0]["effect"]
        )
        for value in (self.main.email, self.herd.email, self.main.phone, self.herd.mobile_phone):
            self.assertNotIn(value, str(body))
        self.assertEqual([(u["id"], u["in_membership"]) for u in preview["legacy_owners"]], [(self.owner.id, False)])
        cases = {"name": "person", "email": "lika", "mobile_phone": "olika", "physical_address": "bada_tomma"}
        self.assertEqual({r["field"]: r["case"] for r in preview["contact_rows"]}, cases)
        self.assertEqual([r["label"] for r in preview["contact_rows"]], ["Namn", "E-post", "Mobil", "Adress"])
        self.assertEqual(db.Herd.get_by_id(self.herd.id).email, self.main.email.upper())

        with self.assertLogs("herdbook.auth", level="INFO") as logs:
            response = self.post(confirm_token=body["confirm_token"])
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.get_json()["id"], self.herd.id)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [f"herd linked actor={self.matrikel_user.id} membership={self.ms.id} herd={self.herd.id}"],
        )
        linked = db.Herd.get_by_id(self.herd.id)
        self.assertEqual(linked.membership_id, self.ms.id)
        self.assertIsNone(linked.email)
        self.assertIsNone(linked.name)
        self.assertEqual(linked.contact_member_id, self.main.id)
        self.assertEqual(linked.mobile_phone, self.herd.mobile_phone)
        self.assertEqual(linked.contact_pending, ["mobile_phone"])
        self.assertIn(linked.id, self.account.effective_herd_ids())
        self.assertIn(linked.id, self.account.owned_herd_ids())
        self.assertTrue(is_matrikel_reader(self.account, linked))
        self.assertIn(linked.id, self.owner.effective_herd_ids())
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "herd_membership_linked")
        self.assertEqual((audit.actor_id, audit.membership_id), (self.matrikel_user.id, self.ms.id))
        self.assertEqual(
            audit.payload,
            {"herd_id": linked.id, "source": "matrikel", "main_member_id": self.main.id},
        )
        self.invalidate.assert_called_once_with([linked.genebank_id])

    def test_new_main_account_invalidates_token_without_writing(self):
        before = self.preview()
        self.assertIsNone(before["preview"]["new_access"])
        self.main.user = self.account
        self.main.save()
        after = self.preview(confirm_token=before["confirm_token"])
        self.assertNotEqual(after["confirm_token"], before["confirm_token"])
        self.assertEqual(after["preview"]["new_access"]["id"], self.account.id)
        self.assertEqual(self.post(confirm_token=after["confirm_token"]).status_code, 201)

    def test_main_with_legacy_owner_role_keeps_it_and_can_now_grant_household_access(self):
        self.main.user = self.owner
        self.main.save()
        self.owner.add_role("owner", self.herd.id)
        preview = self.preview()["preview"]
        self.assertIsNone(preview["new_access"])
        self.assertTrue(preview["legacy_owners"][0]["gains_household_grants"])
        self.assertEqual([(u["id"], u["in_membership"]) for u in preview["legacy_owners"]], [(self.owner.id, True)])

    def test_incomplete_role_on_main_account_refuses_an_uncertain_preview(self):
        self.main.user = self.account
        self.main.save()
        self.account.privileges = [{"level": "owner"}]
        self.account.save(only=[db.User._privileges])
        response = self.post()
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("confirm_token", response.get_json())
        self.assertIsNone(db.Herd.get_by_id(self.herd.id).membership_id)

    def test_existing_link_to_either_membership_is_refused(self):
        token = self.preview()["confirm_token"]
        other = db.Membership.create(member_number=17)
        for membership in (other, self.ms):
            db.Herd.update(membership=membership).where(db.Herd.id == self.herd.id).execute()
            response = self.post(confirm_token=token)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.get_json()["title"], "Besättningen är redan kopplad")
            self.assertEqual(response.get_json()["type"], "herd-unavailable")
            if membership == other:
                self.assertIn("17", response.get_json()["detail"])
            self.assertEqual(db.Herd.get_by_id(self.herd.id).membership_id, membership.id)
            self.assertNotIn("confirm_token", response.get_json())

    def test_changed_contact_cases_invalidate_preview(self):
        before = self.preview()
        self.ms.address = "Testvägen 10"
        self.ms.save()
        rows = self.preview(confirm_token=before["confirm_token"])["preview"]["contact_rows"]
        self.assertEqual(
            {r["field"]: r["case"] for r in rows},
            {
                "name": "fritext",
                "email": "bara_besattningen",
                "mobile_phone": "bada_tomma",
                "physical_address": "bara_matrikeln",
            },
        )

    def test_refused_link_is_stale_without_audit_or_invalidation(self):
        token = self.preview()["confirm_token"]
        with patch("utils.matrikel.link_herd", return_value=None):
            response = self.post(confirm_token=token)
        self.assertEqual((response.status_code, response.get_json()["type"]), (409, "stale"))
        self.assertIsNone(db.Herd.get_by_id(self.herd.id).membership_id)
        self.assertFalse(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "herd_membership_linked").exists())
        self.invalidate.assert_not_called()

    def test_inactive_membership_defers_access_and_comparison(self):
        self.ms.membership_status = "inactive"
        self.ms.save()
        self.assertIsNone(self.preview()["preview"]["new_access"])
        self.main.user = self.account
        self.main.save()
        body = self.preview()
        self.assertEqual(body["preview"]["new_access"]["id"], self.account.id)
        self.assertIsNone(body["preview"]["contact_rows"])
        self.assertEqual(self.post(confirm_token=body["confirm_token"]).status_code, 201)
        linked = db.Herd.get_by_id(self.herd.id)
        self.assertEqual(linked.membership_id, self.ms.id)
        self.assertIsNone(linked.contact_pending)
        self.assertEqual(linked.name, self.herd.name)
        self.assertNotIn(linked.id, self.account.effective_herd_ids())
        self.assertFalse(body["preview"]["new_readers"])
        self.assertFalse(is_matrikel_reader(self.account, linked))

    def candidates(self, bank):
        return self.client.get(f"{self.url}/herd-candidates?genebank_id={bank.id}").json["herds"]

    def test_outside_genebank_herds_are_never_candidates_and_cannot_be_linked(self):
        for code, bank in zip(("GX1", "MX1"), self.genebanks, strict=True):
            herd = db.Herd.create(herd=code, genebank=bank)
            self.assertNotIn(herd.id, [r["id"] for r in self.candidates(bank)])
            refused = self.post(herd_id=herd.id)
            self.assertEqual(refused.status_code, 409)
            self.assertEqual(refused.json["title"], "Besättningen kan inte kopplas")
            self.assertEqual(refused.json["type"], "herd-unavailable")
            self.assertIn("kaniner sålda utanför genbanken", refused.json["detail"])
            self.assertIsNone(db.Herd.get_by_id(herd.id).membership_id)

    def test_duplicate_code_blocks_even_a_previously_confirmable_herd(self):
        token = self.preview()["confirm_token"]
        other = db.Herd.create(herd=self.herd.herd, genebank=self.genebanks[1])
        for herd in (self.herd, other):
            candidate = next(row for row in self.candidates(herd.genebank) if row["id"] == herd.id)
            self.assertEqual(candidate["unavailable_reason"], "koden finns i flera genbanker")
            response = self.post(herd_id=herd.id, confirm_token=token)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json["type"], "herd-unavailable")
            self.assertIn(candidate["unavailable_reason"], response.json["detail"].lower())
            self.assertIsNone(db.Herd.get_by_id(herd.id).membership_id)

    def test_membership_without_active_main_refuses_even_an_existing_token(self):
        token = self.preview()["confirm_token"]
        self.main.end_date = date.today()
        self.main.save()
        for status in ("active", "inactive"):
            self.ms.membership_status = status
            self.ms.save()
            response = self.post(confirm_token=token)
            self.assertEqual(response.status_code, 409)
            self.assertIn("saknar aktiv huvudmedlem", response.json["detail"])
            self.assertNotIn("confirm_token", response.json)
            self.assertIsNone(db.Herd.get_by_id(self.herd.id).membership_id)

    def test_main_with_grant_gains_owner_rights_and_inactive_account_gains_nothing(self):
        self.main.user = self.account
        self.main.save()
        first = self.preview()
        db.HerdAccessGrant.create(member=self.main, herd=self.herd, granted_by=self.admin)
        body = self.preview(confirm_token=first["confirm_token"])
        self.assertIn(self.herd.id, self.account.effective_herd_ids())
        self.assertNotIn(self.herd.id, self.account.owned_herd_ids())
        self.assertTrue(body["preview"]["new_access"]["already_edits"])
        self.assertEqual([u["id"] for u in body["preview"]["grant_holders"]], [self.account.id])
        self.account.is_active = False
        self.account.save()
        preview = self.preview(confirm_token=body["confirm_token"])["preview"]
        self.assertEqual(preview["inactive_main_account"], {"id": self.account.id, "username": self.account.username})
        self.assertIsNone(preview["new_access"])
        self.assertEqual(preview["new_readers"], [])
        self.assertEqual(preview["grant_holders"], [])

    def test_string_owner_role_appears_under_remaining_access(self):
        self.account.add_role("owner", str(self.herd.id))
        self.main.user = self.account
        self.main.save()
        preview = self.preview()["preview"]
        self.assertNotIn(self.herd.id, self.account.owned_herd_ids())
        self.assertIn(self.herd.herd, self.account.is_owner)
        # the rabbit write policies compare integer ids: the link adds that right
        self.assertFalse(preview["new_access"]["already_edits"])
        self.assertEqual([u["id"] for u in preview["legacy_owners"]], [self.account.id])
        self.assertTrue(preview["legacy_owners"][0]["gains_household_grants"])

    def test_preview_with_legacy_code_in_owner_role_on_another_herd(self):
        self.account.privileges = [{"level": "owner", "herd": "G12"}]
        self.account.save()
        self.main.user = self.account
        self.main.save()
        preview = self.preview()["preview"]
        self.assertEqual(preview["new_access"]["id"], self.account.id)
        self.assertFalse(preview["new_access"]["already_edits"])

    def test_user_endpoint_after_link_with_string_owner_role_on_another_herd(self):
        legacy_herd = self.herds[0]
        legacy_herd.membership = None
        legacy_herd.save()
        self.account.add_role("owner", str(legacy_herd.id))
        self.main.user = self.account
        self.main.save()
        member_client = self.client.application.test_client()
        login = member_client.post("/api/login", json={"username": self.account.username, "password": "pass"})
        self.assertEqual(login.get_json()["is_owner"], [legacy_herd.herd])

        token = self.preview()["confirm_token"]
        self.assertEqual(self.post(confirm_token=token).status_code, 201)
        response = member_client.get("/api/user")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertCountEqual(response.get_json()["is_owner"], [legacy_herd.herd, self.herd.herd])

    def test_accessible_genebanks_with_string_owner_role_and_membership_herd(self):
        legacy_herd = self.herds[2]
        self.account.add_role("owner", str(legacy_herd.id))
        self.main.user = self.account
        self.main.save()
        self.assertEqual(self.account.accessible_genebanks, [self.herds[0].genebank_id, legacy_herd.genebank_id])

    def test_family_read_access_alone_invalidates_confirmation(self):
        self.family.user = self.account
        self.family.save()
        first = self.preview()
        self.assertEqual(first["preview"]["new_readers"], [{"id": self.account.id, "username": self.account.username}])
        self.account.add_role("manager", self.herd.genebank_id)
        second = self.preview(confirm_token=first["confirm_token"])
        self.assertEqual(second["preview"], {**first["preview"], "new_readers": []})

    def test_account_with_two_active_grants_on_the_herd_is_listed_once(self):
        with db.DB_PROXY.atomic() as txn:
            # Before v29 one account could be linked to both grant holders.
            db.DB_PROXY.execute_sql("DROP INDEX idx_member_user_unique")
            for person in (self.family, self.skotare):
                person.user = self.account
                person.save()
                db.HerdAccessGrant.create(member=person, herd=self.herd, granted_by=self.admin)
            preview, _ = _herd_link_preview(self.herd, self.ms, None, {self.account.id: self.account})
            txn.rollback()
        self.assertEqual(preview["grant_holders"], [{"id": self.account.id, "username": self.account.username}])

    def test_readers_before_and_after_link_and_grants_on_other_memberships(self):
        self.main.user = self.admin
        self.main.save()
        self.family.user = self.account
        self.family.save()
        self.skotare.user = self.viewer
        self.skotare.save()
        db.Member.create(
            membership=self.ms, role="familjemedlem", first_name="Test", last_name="Chef", user=self.manager
        )
        outside = db.Member.create(
            membership=db.Membership.create(), role="skotare", first_name="Test", last_name="Extern", user=self.owner
        )
        grant = db.HerdAccessGrant.create(member=outside, herd=self.herd, granted_by=self.admin)
        first = self.preview()
        self.assertTrue(first["preview"]["new_access"]["already_manages"])
        self.assertEqual([u["id"] for u in first["preview"]["new_readers"]], [self.account.id])
        self.assertEqual([u["id"] for u in first["preview"]["grant_holders"]], [self.owner.id])
        db.HerdAccessGrant.create(member=self.skotare, herd=self.herd, valid_until=date.today(), granted_by=self.admin)
        body = self.preview(confirm_token=first["confirm_token"])
        readers = {u["id"] for u in body["preview"]["new_readers"]}
        self.assertEqual(readers, {self.account.id, self.viewer.id})
        self.assertCountEqual([u["id"] for u in body["preview"]["grant_holders"]], [self.owner.id, self.viewer.id])
        grant.revoked_at = datetime.now()
        grant.save()
        final = self.preview(confirm_token=body["confirm_token"])
        self.assertEqual([u["id"] for u in final["preview"]["grant_holders"]], [self.viewer.id])
        accounts = [self.admin, self.manager, self.account, self.viewer, self.owner]
        before = {u.id for u in accounts if is_matrikel_reader(u, self.herd)}
        self.assertEqual(self.post(confirm_token=final["confirm_token"]).status_code, 201)
        linked = db.Herd.get_by_id(self.herd.id)
        self.assertEqual({u.id for u in accounts if is_matrikel_reader(u, linked)} - before, readers)

    def test_suspended_ended_and_expired_grants_convey_no_access(self):
        other = db.Membership.create(membership_status="inactive")
        person = db.Member.create(
            membership=other, role="skotare", first_name="Test", last_name="Paus", user=self.owner
        )
        db.HerdAccessGrant.create(member=person, herd=self.herd, granted_by=self.admin)
        self.family.user = self.viewer
        self.family.end_date = date.today()
        self.family.save()
        db.HerdAccessGrant.create(member=self.family, herd=self.herd, granted_by=self.admin)
        self.skotare.user = self.account
        self.skotare.save()
        db.HerdAccessGrant.create(
            member=self.skotare, herd=self.herd, valid_until=date.today() - timedelta(days=1), granted_by=self.admin
        )
        preview = self.preview()["preview"]
        self.assertEqual(preview["grant_holders"], [])
        self.assertEqual(preview["new_readers"], [])

    def test_same_cases_require_new_confirmation_when_contact_write_changes(self):
        self.herd.name = None
        self.herd.save()
        first = self.preview()
        name = first["preview"]["contact_rows"][0]["effect"]
        self.assertIn(f"{self.main.first_name} {self.main.last_name} blir kontaktperson", name)
        self.assertIn("visas inte förrän någon väljer", name)
        # Same cases and contact values. Only the privacy write, then the column to clear, differ.
        self.herd.name_privacy = "private"
        self.herd.save()
        second = self.preview(confirm_token=first["confirm_token"])
        self.herd.name = " "
        self.herd.save()
        third = self.preview(confirm_token=second["confirm_token"])
        # Switch the matched family contact to another person with the same name.
        self.family.first_name, self.family.last_name = "Test", "Kontakt"
        self.family.save()
        self.herd.name = "Test Kontakt"
        self.herd.save()
        fourth = self.preview(confirm_token=third["confirm_token"])
        self.family.end_date = date.today()
        self.family.save()
        self.skotare.first_name, self.skotare.last_name = "Test", "Kontakt"
        self.skotare.save()
        last = self.preview(confirm_token=fourth["confirm_token"])
        self.assertEqual(last["preview"], fourth["preview"])
        self.assertEqual(self.post(confirm_token=last["confirm_token"]).status_code, 201)
        self.assertEqual(db.Herd.get_by_id(self.herd.id).contact_member_id, self.skotare.id)
