"""Preview and confirmation of a herd link from the member register."""

from unittest.mock import patch

import utils.database as db

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
        self.assertFalse(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "herd_linked").exists())
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
        self.assertEqual(preview["new_access"]["id"], self.account.id)
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
        self.assertIn(linked.id, self.owner.effective_herd_ids())
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "herd_linked")
        self.assertEqual((audit.actor_id, audit.membership_id), (self.matrikel_user.id, self.ms.id))
        self.assertEqual(
            audit.payload,
            {"herd_id": linked.id, "herd": linked.herd, "genebank_id": linked.genebank_id, "cases": cases},
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

    def test_main_account_that_already_owns_herd_gains_no_access(self):
        self.main.user = self.owner
        self.main.save()
        self.owner.add_role("owner", self.herd.id)
        preview = self.preview()["preview"]
        self.assertIsNone(preview["new_access"])
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
        self.assertFalse(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "herd_linked").exists())
        self.invalidate.assert_not_called()

    def test_inactive_membership_defers_access_and_comparison(self):
        self.ms.membership_status = "inactive"
        self.ms.save()
        self.main.user = self.account
        self.main.save()
        body = self.preview()
        self.assertIsNone(body["preview"]["new_access"])
        self.assertIsNone(body["preview"]["contact_rows"])
        self.assertEqual(self.post(confirm_token=body["confirm_token"]).status_code, 201)
        linked = db.Herd.get_by_id(self.herd.id)
        self.assertEqual(linked.membership_id, self.ms.id)
        self.assertIsNone(linked.contact_pending)
        self.assertEqual(linked.name, self.herd.name)
        self.assertNotIn(linked.id, self.account.effective_herd_ids())
        self.assertEqual(db.MatrikelAudit.get(db.MatrikelAudit.action == "herd_linked").payload["cases"], {})
