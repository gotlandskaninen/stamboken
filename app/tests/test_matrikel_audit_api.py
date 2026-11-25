"""GET /api/v2/members/audit — the matrikel's change log (#244)."""

import json
from datetime import date, datetime, timedelta

import utils.database as db
import utils.matrikel as matrikel

from tests.test_member_api import MatrikelApiTest, _mk_membership, _mk_person

URL = "/api/v2/members/audit"


class TestMatrikelAudit(MatrikelApiTest):
    def setUp(self):
        super().setUp()
        self.ms = _mk_membership(number=41, address="Gata 1")
        self.person = _mk_person(self.ms, "Tova", "Testsson", "tova@example.com", phone="0701111111")
        self.other_ms = _mk_membership(number=42)
        _mk_person(self.other_ms, "Ulf", "Provsson", "ulf@example.com")

    def get(self, query=""):
        return self.client.get(f"{URL}?{query}")

    def patch_person(self, body):
        resp = self.client.patch(
            f"/api/v2/persons/{self.person.id}", data=json.dumps(body), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_email_change_shows_actor_and_time(self):
        self.login("matrikel")
        self.patch_person({"email": "tova.ny@example.com"})
        resp = self.get(f"membership_id={self.ms.id}")
        self.assertEqual(resp.status_code, 200, resp.data)
        row = resp.get_json()["rows"][0]
        self.assertEqual(row["action"], "person_updated")
        self.assertEqual(row["actor"], {"id": self.matrikel_user.id, "name": "matrikel"})
        self.assertEqual(row["membership"], {"id": self.ms.id, "member_number": 41})
        self.assertEqual(row["person"], {"id": self.person.id, "name": "Tova Testsson"})
        self.assertEqual(row["payload"]["before"], {"email": "tova@example.com"})
        self.assertEqual(row["payload"]["after"], {"email": "tova.ny@example.com"})
        created = datetime.fromisoformat(row["created_at"])
        self.assertIsNotNone(created.tzinfo)  # the browser must not guess the server's time zone
        self.assertLess(abs(created.astimezone() - datetime.now().astimezone()), timedelta(minutes=5))

    def test_access_per_role(self):
        matrikel.write_matrikel_audit(self.admin, "membership_updated", self.ms, {"before": {}, "after": {}})
        for username, status in (("admin", 200), ("matrikel", 200), ("man", 200), ("spec", 403), ("owner", 403)):
            with self.subTest(username=username):
                self.client.get("/api/logout")
                self.login(username)
                resp = self.get()
                self.assertEqual(resp.status_code, status, resp.data)
                if status == 403:
                    self.assertNotIn(b"rows", resp.data)
        self.client.get("/api/logout")
        self.assertEqual(self.get().status_code, 401)

    def test_manager_sees_what_the_member_page_shows_them(self):
        """Organisation number and a person's notes are not in GET /v2/members/<id> for a manager."""
        matrikel.write_matrikel_audit(
            self.admin,
            "membership_updated",
            self.ms,
            {"before": {"organization_number": "5560000000", "notes": "hushallsnot"}, "after": {"notes": "ny not"}},
        )
        matrikel.write_matrikel_audit(
            self.admin,
            "person_updated",
            self.ms,
            {"person_id": self.person.id, "before": {"notes": "personnot"}, "after": {"notes": "ny personnot"}},
        )
        self.login("man")
        text = self.get().get_data(as_text=True)
        for hidden in ("5560000000", "personnot"):
            self.assertNotIn(hidden, text)
        self.assertIn("hushallsnot", text)  # the membership's notes are in the manager's GET
        self.client.get("/api/logout")
        self.login("matrikel")
        text = self.get().get_data(as_text=True)
        for shown in ("5560000000", "personnot", "hushallsnot"):
            self.assertIn(shown, text)

    def test_anonymised_person_is_masked(self):
        self.login("matrikel")
        self.patch_person({"phone": "0702222222", "notes": "hemlig not"})
        matrikel.anonymize_person(db.Member.get_by_id(self.person.id), self.matrikel_user)
        resp = self.get(f"membership_id={self.ms.id}")
        text = resp.get_data(as_text=True)
        for erased in ("Tova", "Testsson", "tova@example.com", "0701111111", "0702222222", "hemlig not"):
            self.assertNotIn(erased, text)
        rows = resp.get_json()["rows"]
        self.assertEqual(rows[0]["action"], "person_anonymized")
        updated = next(r for r in rows if r["action"] == "person_updated")
        self.assertEqual(updated["payload"]["after"]["phone"], matrikel.REDACTED_VALUE)

    def test_stored_payload_that_escaped_erasure_is_masked_on_read(self):
        matrikel.anonymize_person(db.Member.get_by_id(self.person.id), self.matrikel_user)
        # as if written after the erasure, or by a path the erasure missed
        matrikel.write_matrikel_audit(
            self.admin, "person_updated", self.ms, {"person_id": self.person.id, "after": {"email": "kvar@example.com"}}
        )
        self.login()
        text = self.get().get_data(as_text=True)
        self.assertNotIn("kvar@example.com", text)

    def test_nightly_rows_without_actor_are_listed(self):
        matrikel.write_matrikel_audit(None, "person_anonymized", self.ms, {"person_id": self.person.id})
        self.login()
        rows = self.get().get_json()["rows"]
        self.assertEqual([(r["action"], r["actor"]) for r in rows], [("person_anonymized", None)])

    def test_filters_and_paging(self):
        old = matrikel.write_matrikel_audit(self.admin, "membership_updated", self.ms, {"before": {}, "after": {}})
        db.MatrikelAudit.update(created_at=datetime(2025, 1, 10, 12)).where(db.MatrikelAudit.id == old.id).execute()
        matrikel.write_matrikel_audit(self.matrikel_user, "person_removed", self.ms, {"person_id": self.person.id})
        matrikel.write_matrikel_audit(self.admin, "membership_retired", self.other_ms, {"ended_person_ids": []})
        self.login()

        def actions(query):
            resp = self.get(query)
            self.assertEqual(resp.status_code, 200, resp.data)
            return [r["action"] for r in resp.get_json()["rows"]]

        self.assertEqual(actions(f"membership_id={self.ms.id}"), ["person_removed", "membership_updated"])
        self.assertEqual(actions("member_number=41"), ["person_removed", "membership_updated"])
        self.assertEqual(actions("member_number=42"), ["membership_retired"])
        self.assertEqual(actions(f"member_number=41&membership_id={self.other_ms.id}"), [])
        self.assertEqual(actions("action=membership_retired"), ["membership_retired"])
        self.assertEqual(actions("actor=matrikel"), ["person_removed"])
        self.assertEqual(actions("to=2025-01-10"), ["membership_updated"])  # the whole day
        today = date.today().isoformat()
        self.assertEqual(actions(f"from={today}&to={today}"), ["membership_retired", "person_removed"])
        page = self.get("per_page=1&page=2").get_json()
        self.assertEqual((page["total"], page["page"], page["per_page"]), (3, 2, 1))
        self.assertEqual([r["action"] for r in page["rows"]], ["person_removed"])
        self.assertEqual(self.get("per_page=999").get_json()["per_page"], 200)
        for bad in ("from=igar", "page=x", "membership_id=y", "member_number=z"):
            with self.subTest(bad=bad):
                self.assertEqual(self.get(bad).status_code, 400)
