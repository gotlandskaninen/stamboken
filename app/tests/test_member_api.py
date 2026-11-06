"""Tests for /api/v2/members endpoints (Member Model v2 — membership rows)."""

import csv as _csv_lib
import io as _io
import json
import os
import tempfile
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.matrikel as matrikel  # noqa: E402
from blueprints import members as members_routes  # noqa: E402

# The export is consumed by the importer — reuse its pure parsing helpers.
from cli.members import _group_rows, _read_rows  # noqa: E402
from herdbook import APP, limiter  # noqa: E402
from utils.members import consent_answered, effective_consent  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402

limiter.enabled = False


def _mk_membership(number=None, status="active", **kwargs):
    return db.Membership.create(member_number=number, membership_status=status, **kwargs)


def _mk_person(membership, first, last, email=None, role="huvudmedlem", **kwargs):
    return db.Member.create(membership=membership, first_name=first, last_name=last, email=email, role=role, **kwargs)


class MatrikelApiTest(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.matrikel_user = da.register_user("matrikel", "pass")
        self.matrikel_user.add_role("matrikel_admin", None)

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.post("/api/login", json={"username": username, "password": password})


class TestMembershipList(MatrikelApiTest):
    def setUp(self):
        super().setUp()
        self.ms1 = _mk_membership(number=6, address="Gata 1")
        _mk_person(self.ms1, "Anna", "Andersson", "anna@example.com")
        _mk_person(self.ms1, "Frida", "Andersson", role="familjemedlem")
        self.ms2 = _mk_membership(number=7)
        _mk_person(self.ms2, "Bo", "Bengtsson", "bo@example.com")
        self.ms3 = _mk_membership(status="friexemplar")
        _mk_person(self.ms3, "Biblioteket", "Visby", "bibl@example.com")

    def test_list_returns_flat_membership_rows(self):
        self.login("man")
        resp = self.client.get("/api/v2/members")
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.get_json()
        self.assertEqual(data["total"], 3)
        row = next(r for r in data["items"] if r["member_number"] == 6)
        self.assertEqual(row["main_first_name"], "Anna")
        self.assertEqual(row["address"], "Gata 1")
        self.assertEqual(len(row["persons"]), 2)
        self.assertEqual({p["role"] for p in row["persons"]}, {"huvudmedlem", "familjemedlem"})

    def test_matrikel_admin_can_list(self):
        self.login("matrikel")
        resp = self.client.get("/api/v2/members")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.get_json()["total"], 3)

    def test_owner_cannot_list(self):
        self.login("owner")
        self.assertEqual(self.client.get("/api/v2/members").status_code, 403)

    def test_list_unauthenticated_401(self):
        self.assertEqual(self.client.get("/api/v2/members").status_code, 401)

    def test_search_matches_person_name(self):
        self.login()
        data = self.client.get("/api/v2/members?search=bengts").get_json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["member_number"], 7)

    def test_search_matches_member_number(self):
        self.login()
        data = self.client.get("/api/v2/members?search=7").get_json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["member_number"], 7)

    def test_search_oversized_number_matches_nothing(self):
        self.login()
        data = self.client.get("/api/v2/members?search=99999999999").get_json()
        self.assertEqual(data["total"], 0)

    def test_search_non_ascii_digit_does_not_crash(self):
        self.login()
        resp = self.client.get("/api/v2/members?search=²")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["total"], 0)

    def test_status_filter(self):
        self.login()
        data = self.client.get("/api/v2/members?status=friexemplar").get_json()
        self.assertEqual(data["total"], 1)
        self.assertIsNone(data["items"][0]["member_number"])

    def test_pagination(self):
        self.login()
        data = self.client.get("/api/v2/members?per_page=2&page=1").get_json()
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(data["total"], 3)


class TestMembershipDetailAndPatch(MatrikelApiTest):
    def setUp(self):
        super().setUp()
        self.ms = _mk_membership(number=6)
        self.main = _mk_person(self.ms, "Anna", "Andersson", "anna@example.com")
        self.herds[0].membership = self.ms
        self.herds[0].save()

    def test_detail_includes_persons_herds_grants(self):
        self.login("man")
        resp = self.client.get(f"/api/v2/members/{self.ms.id}")
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.get_json()
        self.assertEqual(data["member_number"], 6)
        self.assertEqual([p["first_name"] for p in data["persons"]], ["Anna"])
        self.assertEqual([h["herd"] for h in data["herds"]], ["G1"])
        self.assertNotIn("grants", data)
        self.assertEqual(data["persons"][0]["grants"], [])

    def test_detail_404(self):
        self.login()
        self.assertEqual(self.client.get("/api/v2/members/99999").status_code, 404)

    def test_patch_status_as_matrikel_admin_is_audited(self):
        self.login("matrikel")
        resp = self.client.patch(
            f"/api/v2/members/{self.ms.id}",
            data=json.dumps({"membership_status": "pending"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(db.Membership.get_by_id(self.ms.id).membership_status, "pending")
        audit = db.MatrikelAudit.get(db.MatrikelAudit.membership == self.ms)
        self.assertEqual(audit.action, "membership_status_changed")
        self.assertEqual(
            audit.payload,
            {"before": {"membership_status": "active"}, "after": {"membership_status": "pending"}},
        )

    def test_patch_invalid_status_400(self):
        self.login("matrikel")
        resp = self.client.patch(
            f"/api/v2/members/{self.ms.id}",
            data=json.dumps({"membership_status": "garbage"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_manager_cannot_patch(self):
        self.login("man")
        resp = self.client.patch(
            f"/api/v2/members/{self.ms.id}",
            data=json.dumps({"membership_status": "inactive"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_patch_accepts_postal_address_alias_and_returns_split(self):
        self.login()
        resp = self.client.patch(
            f"/api/v2/memberships/{self.ms.id}",
            data=json.dumps({"postal_address": "62355 Visby"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json()
        self.assertEqual(
            (body["postal_code"], body["city"], body["postal_address"]), ("623 55", "Visby", "623 55 Visby")
        )
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "membership_updated")
        self.assertEqual(audit.payload["after"], {"postal_code": "623 55", "city": "Visby"})

    def test_patch_rejects_both_address_layouts(self):
        self.login()
        resp = self.client.patch(
            f"/api/v2/memberships/{self.ms.id}",
            data=json.dumps({"postal_address": "62355 Visby", "city": "Visby"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.get_json()["detail"], "Ange antingen postal_address eller postal_code/city")

    def test_patch_trims_address(self):
        self.login()
        resp = self.client.patch(
            f"/api/v2/memberships/{self.ms.id}",
            data=json.dumps({"address": "  Gatan 1  "}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.get_json()["address"], "Gatan 1")
        self.assertEqual(
            db.MatrikelAudit.get(db.MatrikelAudit.action == "membership_updated").payload["after"],
            {"address": "Gatan 1"},
        )

    def test_patch_structured_keys_validated(self):
        self.login()
        resp = self.client.patch(
            f"/api/v2/memberships/{self.ms.id}",
            data=json.dumps({"postal_code": "ABC"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        resp = self.client.patch(
            f"/api/v2/memberships/{self.ms.id}",
            data=json.dumps({"city": "y" * 101}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        # Non-parsing legacy alias lands whole in city — the cap still applies.
        resp = self.client.patch(
            f"/api/v2/memberships/{self.ms.id}",
            data=json.dumps({"postal_address": "Box " + "y" * 100}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.get_json()["detail"], "Postort får vara högst 100 tecken")
        self.assertIsNone(db.Membership.get_by_id(self.ms.id).city)


class TestSelfService(MatrikelApiTest):
    def setUp(self):
        super().setUp()
        self.linked_user = da.register_user("linked@example.com", "pass", username="linked")
        self.ms = _mk_membership(number=8, address="Gata 2")
        self.person = _mk_person(self.ms, "Linked", "User", "linked@example.com", user=self.linked_user)

    def test_get_me(self):
        self.login("linked")
        resp = self.client.get("/api/v2/members/me")
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.get_json()
        self.assertEqual(data["first_name"], "Linked")
        self.assertEqual(data["membership"]["member_number"], 8)

    def test_get_me_orphan_404(self):
        da.register_user("orphan@example.com", "pass", username="orphan")
        self.login("orphan")
        self.assertEqual(self.client.get("/api/v2/members/me").status_code, 404)

    def test_get_me_unauthenticated_401(self):
        self.assertEqual(self.client.get("/api/v2/members/me").status_code, 401)

    def test_patch_contact_updates_person_and_membership_address(self):
        self.login("linked")
        resp = self.client.patch(
            "/api/v2/members/me/contact",
            data=json.dumps({"phone": "+46701234567", "address": "Box 1"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(db.Member.get_by_id(self.person.id).phone, "+46701234567")
        self.assertEqual(db.Membership.get_by_id(self.ms.id).address, "Box 1")

    def test_patch_contact_invalid_email_400(self):
        self.login("linked")
        resp = self.client.patch(
            "/api/v2/members/me/contact",
            data=json.dumps({"email": "not-an-email"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_consent_writes_membership(self):
        self.login("linked")
        resp = self.client.patch(
            "/api/v2/members/me/consent",
            data=json.dumps({"email": True}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(db.Membership.get_by_id(self.ms.id).publication_consent.get("email"))
        self.assertEqual(
            resp.get_json()["publication_consent"],
            {"name": False, "phone": False, "email": True, "address": False},
        )

    def test_patch_consent_rejects_non_boolean(self):
        self.login("linked")
        resp = self.client.patch(
            "/api/v2/members/me/consent",
            data=json.dumps({"email": "false"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertFalse((db.Membership.get_by_id(self.ms.id).publication_consent or {}).get("email", False))

    def test_patch_consent_merges_onto_the_stored_answer(self):
        """The body is a PARTIAL update: keys the member did not
        submit keep their stored value, and no key is invented for them."""
        self.ms.publication_consent = {"email": True}
        self.ms.save()
        self.login("linked")
        resp = self.client.patch(
            "/api/v2/members/me/consent",
            data=json.dumps({"phone": True}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(db.Membership.get_by_id(self.ms.id).publication_consent, {"email": True, "phone": True})
        self.assertEqual(
            resp.get_json()["publication_consent"],
            {"name": False, "phone": True, "email": True, "address": False},
        )

    def test_withdrawn_consent_stays_withdrawn_in_the_koharen_export(self):
        """GDPR: a withdrawal must survive the next partial save of another
        switch — the export's e-post cell stays blank."""
        self.ms.publication_consent = {"email": True}
        self.ms.save()
        self.person.phone = "070-9"
        self.person.save()
        self.login("linked")
        for body in ({"phone": True}, {"email": False}):
            resp = self.client.patch(
                "/api/v2/members/me/consent",
                data=json.dumps(body),
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(db.Membership.get_by_id(self.ms.id).publication_consent, {"email": False, "phone": True})

        self.client.get("/api/logout")
        self.login("matrikel")
        resp = self.client.get("/api/v2/members/koharen-export")
        self.assertEqual(resp.status_code, 200, resp.data)
        rows = list(_csv_lib.reader(_io.StringIO(resp.get_data(as_text=True).lstrip("\ufeff"))))
        row = next(r for r in rows[1:] if r[0] == "8")
        self.assertEqual(row[2], "070-9")  # Telefon — the key that was granted
        self.assertEqual(row[3], "")  # E-post — the withdrawal held
        self.assertEqual(row[7], "angivet")

    def test_malformed_stored_consent_is_not_consent(self):
        """Fail-closed: only a literal JSON true publishes. A stored
        "false" or 1 — a legacy or hand-edited blob the PATCH route would have
        refused — must not print in the Koharen export (bool("false") is True),
        GET /me must report it as off, and the next partial save must persist
        it as false instead of carrying the coercion forward."""
        self.ms.publication_consent = {"name": True, "email": "false", "phone": 1}
        self.ms.save()
        self.person.phone = "070-9"
        self.person.save()

        self.login("matrikel")
        resp = self.client.get("/api/v2/members/koharen-export")
        self.assertEqual(resp.status_code, 200, resp.data)
        rows = list(_csv_lib.reader(_io.StringIO(resp.get_data(as_text=True).lstrip("\ufeff"))))
        row = next(r for r in rows[1:] if r[0] == "8")
        self.assertEqual(row[1], "Linked User")  # Namn — the one literal true
        self.assertEqual(row[2], "")  # Telefon — 1 is not consent
        self.assertEqual(row[3], "")  # E-post — "false" is not consent
        self.assertEqual(row[7], "angivet")

        self.client.get("/api/logout")
        self.login("linked")
        me = self.client.get("/api/v2/members/me").get_json()
        self.assertEqual(me["publication_consent"], {"name": True, "phone": False, "email": False, "address": False})
        self.assertTrue(me["consent_answered"])
        resp = self.client.patch(
            "/api/v2/members/me/consent", data=json.dumps({"address": True}), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(
            db.Membership.get_by_id(self.ms.id).publication_consent,
            {"name": True, "email": False, "phone": False, "address": True},
        )

    def test_non_object_stored_consent_is_never_answered(self):
        """A JSONB array or scalar in publication_consent is neither consent nor
        an answer — the export falls back to "ej angivet"."""
        for blob in (["email"], "email", 1):
            row = SimpleNamespace(publication_consent=blob)
            self.assertEqual(effective_consent(row), {k: False for k in ("name", "phone", "email", "address")})
            self.assertFalse(consent_answered(row))

    def test_patch_consent_empty_body_400(self):
        """Never a silent no-op: {} would leave the row at "ej angivet"."""
        self.login("linked")
        resp = self.client.patch(
            "/api/v2/members/me/consent",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.content_type, "application/problem+json")
        self.assertEqual(resp.get_json()["title"], "Inga publiceringsval angivna")

    def test_patch_consent_unknown_key_400(self):
        self.login("linked")
        resp = self.client.patch(
            "/api/v2/members/me/consent",
            data=json.dumps({"herd": True}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.get_json()["title"], "Ogiltigt fält")
        self.assertEqual(db.Membership.get_by_id(self.ms.id).publication_consent, {})

    def test_get_me_reports_consent_answered(self):
        """{} = never answered — the profil page sends all four keys
        on the first save so an all-off answer is still recorded."""
        self.login("linked")
        self.assertFalse(self.client.get("/api/v2/members/me").get_json()["consent_answered"])
        resp = self.client.patch(
            "/api/v2/members/me/consent",
            data=json.dumps({"name": False}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.get_json()["consent_answered"])
        self.assertTrue(self.client.get("/api/v2/members/me").get_json()["consent_answered"])

    def test_patch_contact_refuses_after_anonymization(self):
        """GDPR: the route reads the person at request start, so an
        anonymization committed in between would have the body's phone written
        straight back onto the scrubbed row. The re-read under the membership
        lock must answer 409 and leave the row scrubbed."""
        self.login("linked")
        stale = db.Member.get_by_id(self.person.id)  # what the route reads at request start
        matrikel.anonymize_person(db.Member.get_by_id(self.person.id), self.matrikel_user)
        with patch.object(members_routes, "_member_for_current_user", return_value=stale):
            resp = self.client.patch(
                "/api/v2/members/me/contact",
                data=json.dumps({"phone": "+46701234567", "address": "Box 1"}),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(resp.content_type, "application/problem+json")
        self.assertEqual(resp.get_json()["title"], "Kontot är inte längre kopplat")
        person = db.Member.get_by_id(self.person.id)
        self.assertIsNone(person.phone)
        self.assertEqual(
            (person.first_name, person.last_name), (matrikel.ANONYMIZED_FIRST_NAME, matrikel.ANONYMIZED_LAST_NAME)
        )
        self.assertIsNone(person.user_id)
        # Erasing the household's only person cleared its address; the
        # refused PATCH must not have written "Box 1" back.
        self.assertIsNone(db.Membership.get_by_id(self.ms.id).address)

    def test_non_main_member_is_read_only(self):
        """Spec: non-main persons see their entry read-only — both mutation
        endpoints refuse them; GET stays available."""
        family_user = da.register_user("family@example.com", "pass", username="family")
        _mk_person(self.ms, "Familj", "User", "family@example.com", role="familjemedlem", user=family_user)
        self.login("family")

        self.assertEqual(self.client.get("/api/v2/members/me").status_code, 200)
        resp = self.client.patch(
            "/api/v2/members/me/contact",
            data=json.dumps({"phone": "+46700000000"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403, resp.data)
        resp = self.client.patch(
            "/api/v2/members/me/consent",
            data=json.dumps({"email": True}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403, resp.data)
        self.assertEqual(db.Membership.get_by_id(self.ms.id).address, "Gata 2")

    def test_get_me_carries_structured_address_and_main_member_name(self):
        self.ms.postal_code, self.ms.city = "623 55", "Visby"
        self.ms.save()
        self.login("linked")
        data = self.client.get("/api/v2/members/me").get_json()
        self.assertEqual(data["membership"]["postal_code"], "623 55")
        self.assertEqual(data["membership"]["city"], "Visby")
        self.assertEqual(data["membership"]["postal_address"], "623 55 Visby")
        self.assertEqual(data["main_member_name"], "Linked User")

    def test_main_member_name_for_family_and_skotare_callers(self):
        for role, username, email in (
            ("familjemedlem", "fam2", "fam2@example.com"),
            ("skotare", "sko2", "sko2@example.com"),
        ):
            user = da.register_user(email, "pass", username=username)
            _mk_person(self.ms, role.title(), "Person", email, role=role, user=user)
            self.login(username)
            self.assertEqual(self.client.get("/api/v2/members/me").get_json()["main_member_name"], "Linked User")

    def test_main_member_name_null_without_active_main(self):
        self.person.role = "familjemedlem"
        self.person.save()
        self.login("linked")
        self.assertIsNone(self.client.get("/api/v2/members/me").get_json()["main_member_name"])

    def test_patch_contact_structured_address_round_trip(self):
        self.login("linked")
        resp = self.client.patch(
            "/api/v2/members/me/contact",
            data=json.dumps({"address": "Storgatan 2", "postal_code": "62355", "city": " Visby "}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json()["membership"]
        self.assertEqual(
            (body["postal_code"], body["city"], body["postal_address"]), ("623 55", "Visby", "623 55 Visby")
        )
        ms = db.Membership.get_by_id(self.ms.id)
        self.assertEqual((ms.address, ms.postal_code, ms.city), ("Storgatan 2", "623 55", "Visby"))

    def test_patch_contact_bad_postnummer_400(self):
        self.login("linked")
        resp = self.client.patch(
            "/api/v2/members/me/contact",
            data=json.dumps({"postal_code": "6235"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.get_json()["title"], "Ogiltigt postnummer")
        self.assertEqual(resp.get_json()["detail"], "Postnummer ska vara fem siffror")

    def test_patch_contact_city_too_long_400(self):
        self.login("linked")
        resp = self.client.patch(
            "/api/v2/members/me/contact",
            data=json.dumps({"city": "x" * 101}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.get_json()["detail"], "Postort får vara högst 100 tecken")

    def test_patch_contact_ignores_postal_address_alias(self):
        """Self-service never accepted the legacy alias — the helper must not smuggle it in."""
        self.ms.postal_code, self.ms.city = "623 55", "Visby"
        self.ms.save()
        self.login("linked")
        resp = self.client.patch(
            "/api/v2/members/me/contact",
            data=json.dumps({"postal_address": "999 99 Annanstans"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        ms = db.Membership.get_by_id(self.ms.id)
        self.assertEqual((ms.postal_code, ms.city), ("623 55", "Visby"))

    def test_patch_contact_writes_only_changed_columns(self):
        """The self-service PATCH saved the person
        and the membership it read at request start in full. That writes
        member.user_id back (undoing — or resurrecting — a link committed in
        between) and membership_status back (restoring herd access after a
        concurrent flip to inactive). Both UPDATEs must carry only what the body
        changed."""
        self.login("linked")
        with (
            patch.object(db.Member, "save", autospec=True, side_effect=db.Member.save) as person_spy,
            patch.object(db.Membership, "save", autospec=True, side_effect=db.Membership.save) as ms_spy,
        ):
            resp = self.client.patch(
                "/api/v2/members/me/contact",
                data=json.dumps({"phone": "+46701234567", "address": "Box 9"}),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        # Compare by field NAME: Field.__eq__ builds an Expression, so `in`/`not in`
        # over a list of Fields would be meaningless.
        person_only = {f.name for f in person_spy.call_args.kwargs["only"]}
        self.assertIn("phone", person_only)
        self.assertIn("updated_at", person_only)
        self.assertNotIn("user", person_only)
        ms_only = {f.name for f in ms_spy.call_args.kwargs["only"]}
        self.assertIn("address", ms_only)
        self.assertIn("updated_at", ms_only)
        self.assertNotIn("membership_status", ms_only)
        person = db.Member.get_by_id(self.person.id)
        self.assertEqual((person.phone, person.user_id), ("+46701234567", self.linked_user.id))
        self.assertEqual(db.Membership.get_by_id(self.ms.id).address, "Box 9")

    def test_patch_consent_writes_only_the_consent_column(self):
        """Same rule for the consent route: it must never carry membership_status
        (or the address) along from its stale read."""
        self.login("linked")
        with patch.object(db.Membership, "save", autospec=True, side_effect=db.Membership.save) as ms_spy:
            resp = self.client.patch(
                "/api/v2/members/me/consent",
                data=json.dumps({"email": True}),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual({f.name for f in ms_spy.call_args.kwargs["only"]}, {"publication_consent", "updated_at"})
        self.assertTrue(db.Membership.get_by_id(self.ms.id).publication_consent.get("email"))

    def test_patch_contact_clears_with_null(self):
        self.ms.postal_code, self.ms.city = "623 55", "Visby"
        self.ms.save()
        self.login("linked")
        resp = self.client.patch(
            "/api/v2/members/me/contact",
            data=json.dumps({"postal_code": None, "city": ""}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        ms = db.Membership.get_by_id(self.ms.id)
        self.assertEqual((ms.postal_code, ms.city), (None, None))

    # Both self-service writes authorize on a row read at request start. Each
    # test below drives ONE rejected condition by handing the route that stale
    # read — what a writer committing between the read and the membership lock
    # leaves behind — and asserts the route re-decides on the row it finds
    # under the lock instead of saving.

    SELF_SERVICE_WRITES = (
        ("/api/v2/members/me/contact", {"phone": "+46701234567", "address": "Box 1"}),
        ("/api/v2/members/me/consent", {"email": True}),
    )

    def _assert_both_writes_refuse(self, stale, status, title, address="Gata 2"):
        for path, body in self.SELF_SERVICE_WRITES:
            # The post-state assertions live INSIDE the subTest so a regression
            # is attributed to the route that wrote — not to whichever ran last.
            with self.subTest(path=path):
                with patch.object(members_routes, "_member_for_current_user", return_value=stale):
                    resp = self.client.patch(path, data=json.dumps(body), content_type="application/json")
                self.assertEqual(resp.status_code, status, resp.data)
                self.assertEqual(resp.content_type, "application/problem+json")
                self.assertEqual(resp.get_json()["title"], title)
                person = db.Member.get_by_id(self.person.id)
                ms = db.Membership.get_by_id(self.ms.id)
                self.assertIsNone(person.phone)
                self.assertEqual(ms.address, address)
                self.assertEqual(ms.publication_consent, {})

    def test_self_service_writes_refuse_a_demotion_committed_under_the_lock(self):
        """The pre-lock role gate is stale: a main-member swap that commits in
        between would leave an ex-huvudmedlem writing the household's address
        and publication consent."""
        self.login("linked")
        other = _mk_person(self.ms, "Ny", "Huvud", "ny@example.com", role="familjemedlem")
        stale = db.Member.get_by_id(self.person.id)  # still huvudmedlem
        matrikel.swap_main_member(self.ms, other, self.matrikel_user)
        self._assert_both_writes_refuse(stale, 403, "Endast huvudmedlem")

    def test_self_service_writes_refuse_after_the_account_is_unlinked(self):
        self.login("linked")
        stale = db.Member.get_by_id(self.person.id)
        matrikel.unlink_member_user(self.person.id, actor=self.matrikel_user)
        self._assert_both_writes_refuse(stale, 409, "Kontot är inte längre kopplat")

    def test_self_service_writes_refuse_an_ended_person(self):
        self.login("linked")
        stale = db.Member.get_by_id(self.person.id)
        # Raw update: the person is the active huvudmedlem, so soft_delete_person
        # refuses it — the ENDED STATE is what this test needs, not the operation.
        db.Member.update(end_date=date.today()).where(db.Member.id == self.person.id).execute()
        self._assert_both_writes_refuse(stale, 409, "Kontot är inte längre kopplat")

    def test_self_service_writes_refuse_after_anonymization(self):
        self.login("linked")
        stale = db.Member.get_by_id(self.person.id)
        matrikel.anonymize_person(db.Member.get_by_id(self.person.id), self.matrikel_user)
        # The sole person's erasure cleared the household address (no stale "Box 1" either).
        self._assert_both_writes_refuse(stale, 409, "Kontot är inte längre kopplat", address=None)


MATR_HEADER = [
    "G",
    "M",
    "Nr",
    "Namn Efternamn",
    "Adress",
    "Postnummer",
    "Postort",
    "Telefonnr",
    "e-postadress",
    "Bet senast",
    "Noteringar",
]


class TestStatsAndExport(MatrikelApiTest):
    def setUp(self):
        super().setUp()
        today = date.today()
        self.ms_a = _mk_membership(
            number=1,
            joined_date=date(today.year, 1, 2),
            address="Adagatan 3",
            postal_code="123 45",
            city="Visby",
        )
        _mk_person(self.ms_a, "Ada", "A", "ada@example.com", phone="070-1111111")
        _mk_person(self.ms_a, "Alf", "A", "alf@example.com", role="familjemedlem", phone="070-2222222")
        # Herd G1 (from the DatabaseTest fixture) makes the G flag true.
        self.herds[0].membership = self.ms_a
        self.herds[0].save()
        ms_b = _mk_membership(number=2, status="inactive", joined_date=date(today.year - 2, 1, 1))
        _mk_person(ms_b, "Bi", "B", "bi@example.com")
        ms_free = _mk_membership(status="friexemplar", address="Biblioteksgatan 1")
        _mk_person(ms_free, "Biblioteket", "Visby")

    def _export_rows(self):
        resp = self.client.get("/api/v2/members/export")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data.startswith("\ufeff".encode()))
        rows = list(_csv_lib.reader(_io.StringIO(resp.data.decode("utf-8-sig"))))
        return resp, rows[0], rows[1:]

    def test_stats_counts_memberships_and_persons_separately(self):
        self.login("man")
        resp = self.client.get("/api/v2/members/stats")
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.get_json()
        self.assertEqual(data["memberships"]["total"], 2)  # friexemplar excluded
        self.assertEqual(data["memberships"]["active"], 1)
        self.assertEqual(data["memberships"]["inactive"], 1)
        self.assertEqual(data["memberships"]["new_this_year"], 1)
        self.assertEqual(data["persons"]["total"], 3)
        self.assertEqual(data["persons"]["active"], 3)
        self.assertEqual(data["friexemplar"], 1)

    def test_export_requires_matrikel_admin(self):
        self.login("man")
        self.assertEqual(self.client.get("/api/v2/members/export").status_code, 403)

    def test_export_uses_matr_header(self):
        self.login("matrikel")
        _, header, _ = self._export_rows()
        self.assertEqual(header, MATR_HEADER)

    def test_export_friexemplar_first_with_nr_zero(self):
        """friexemplar rows lead the file (as in the paper matrikel), carry
        Nr 0 and enough for the magazine mailing list."""
        self.login("matrikel")
        _, header, data_rows = self._export_rows()
        first = data_rows[0]
        self.assertEqual(first[header.index("Nr")], "0")
        self.assertEqual(first[header.index("Namn Efternamn")], "Biblioteket Visby")
        self.assertEqual(first[header.index("Adress")], "Biblioteksgatan 1")

    def test_export_excludes_inactive(self):
        self.login("matrikel")
        _, header, data_rows = self._export_rows()
        self.assertNotIn("2", {r[header.index("Nr")] for r in data_rows})
        self.assertNotIn("Bi B", {r[header.index("Namn Efternamn")] for r in data_rows})

    def test_export_excludes_pending(self):
        """MATR has no status column — a pending membership would come back
        ACTIVE on re-import, so it must not export at all."""
        ms = _mk_membership(number=77, status="pending")
        _mk_person(ms, "Pella", "Pending", "pella@example.com")
        self.login("matrikel")
        _, header, data_rows = self._export_rows()
        self.assertNotIn("77", {r[header.index("Nr")] for r in data_rows})

    def test_export_numberless_active_has_empty_nr(self):
        """A numberless ACTIVE membership stays in the mailing list with an
        empty Nr cell; the importer deliberately errors on that row so the
        anomaly is surfaced instead of re-importing as friexemplar."""
        ms = _mk_membership(number=None, status="active")
        _mk_person(ms, "Numa", "Numberless", "numa@example.com")
        self.login("matrikel")
        _, header, data_rows = self._export_rows()
        row = next(r for r in data_rows if r[header.index("Namn Efternamn")] == "Numa Numberless")
        self.assertEqual(row[header.index("Nr")], "")

    def test_export_family_row_repeats_nr_without_membership_fields(self):
        """Two rows share the Nr; membership-level cells (G/M, address,
        postal address) sit on the main row only — the family row keeps its
        own person fields."""
        self.login("matrikel")
        _, header, data_rows = self._export_rows()
        rows = [r for r in data_rows if r[header.index("Nr")] == "1"]
        self.assertEqual([r[header.index("Namn Efternamn")] for r in rows], ["Ada A", "Alf A"])
        main, family = rows

        self.assertEqual(main[header.index("G")], "G")  # herd G1 is linked
        self.assertEqual(main[header.index("M")], "")
        self.assertEqual(main[header.index("Adress")], "Adagatan 3")
        # Structured columns straight from postal_code + city.
        self.assertEqual(main[header.index("Postnummer")], "123 45")
        self.assertEqual(main[header.index("Postort")], "Visby")
        self.assertEqual(main[header.index("Telefonnr")], "070-1111111")
        self.assertEqual(main[header.index("e-postadress")], "ada@example.com")

        self.assertEqual(family[header.index("G")], "")
        self.assertEqual(family[header.index("M")], "")
        self.assertEqual(family[header.index("Adress")], "")
        self.assertEqual(family[header.index("Postnummer")], "")
        self.assertEqual(family[header.index("Postort")], "")
        self.assertEqual(family[header.index("Telefonnr")], "070-2222222")
        self.assertEqual(family[header.index("e-postadress")], "alf@example.com")

    def test_export_writes_postnummer_and_postort_columns(self):
        self.login()
        text = self.client.get("/api/v2/members/export").get_data(as_text=True).lstrip("\ufeff")
        rows = list(_csv_lib.reader(_io.StringIO(text)))
        self.assertEqual(rows[0], MATR_HEADER)
        # self.ms_a (postal_code="123 45", city="Visby") is member number 1.
        main_row = next(r for r in rows[1:] if r[2] == "1")
        self.assertEqual(main_row[5:7], ["123 45", "Visby"])

    def test_export_round_trips_through_importer(self):
        """The exported file is a valid MATR2026 import file — the registrar can
        re-import what they downloaded."""
        self.login("matrikel")
        resp = self._export_rows()[0]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "matrikel_export.csv")
            with open(path, "wb") as f:
                f.write(resp.data)
            rows, errors, file_errors = _read_rows(path)
        self.assertEqual(file_errors, [])
        self.assertEqual(errors, [])
        groups, friexemplar_groups = _group_rows(rows)
        self.assertEqual(set(groups), {1})
        self.assertEqual(len(groups[1]), 2)  # huvudmedlem + familjemedlem
        self.assertEqual(len(friexemplar_groups), 1)

    def test_export_escapes_formula_injection(self):
        ms = _mk_membership(number=3)
        _mk_person(ms, "=SUM(A1)", "Evil", "evil@example.com")
        self.login("matrikel")
        content = self.client.get("/api/v2/members/export").data.decode("utf-8-sig")
        for row in list(_csv_lib.reader(_io.StringIO(content)))[1:]:
            for cell in row:
                if cell:
                    self.assertFalse(
                        cell[0] in ("=", "+", "-", "@", "\t", "\r"),
                        f"unescaped formula-injection cell: {cell!r}",
                    )


KOHAREN_HEADER = ["Nr", "Namn", "Telefon", "E-post", "Gatuadress", "Postnummer", "Postort", "Samtycke"]


class TestKoharenExport(MatrikelApiTest):
    def setUp(self):
        super().setUp()
        self.full = _mk_membership(
            number=6,
            address="Gatan 1",
            postal_code="623 55",
            city="Visby",
            publication_consent={"name": True, "phone": True, "email": True, "address": True},
        )
        _mk_person(self.full, "Anna", "Andersson", "anna@example.com", phone="070-1")
        _mk_person(self.full, "Frida", "Andersson", "frida@example.com", role="familjemedlem", phone="070-2")
        self.partial = _mk_membership(
            number=7,
            address="Gatan 2",
            postal_code="621 45",
            city="Visby",
            publication_consent={"name": True, "phone": False, "email": True, "address": False},
        )
        _mk_person(self.partial, "Bo", "Bengtsson", "bo@example.com", phone="070-3")
        self.opted_out = _mk_membership(
            number=8, publication_consent={"name": False, "phone": False, "email": False, "address": False}
        )
        _mk_person(self.opted_out, "Cy", "Cyklop", "cy@example.com")
        self.unset = _mk_membership(number=9, address="Gatan 9", publication_consent={})
        _mk_person(self.unset, "Ulla", "Unset", "ulla@example.com")
        self.fri = _mk_membership(status="friexemplar", publication_consent={"name": True})
        _mk_person(self.fri, "Biblioteket", "Visby")
        self.inactive = _mk_membership(number=10, status="inactive", publication_consent={"name": True})
        _mk_person(self.inactive, "In", "Aktiv")

    def _rows(self):
        self.login("matrikel")
        resp = self.client.get("/api/v2/members/koharen-export")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn('filename="koharen-matrikel.csv"', resp.headers["Content-Disposition"])
        text = resp.get_data(as_text=True)
        self.assertTrue(text.startswith("\ufeff"))
        return list(_csv_lib.reader(_io.StringIO(text.lstrip("\ufeff"))))

    def test_header_order_membership_scope_and_person_order(self):
        rows = self._rows()
        self.assertEqual(rows[0], KOHAREN_HEADER)
        self.assertEqual([r[0] for r in rows[1:]], ["6", "6", "7", "8", "9"])  # friexemplar + inactive excluded
        self.assertEqual(rows[1][1], "Anna Andersson")  # huvudmedlem first

    def test_full_consent_prints_everything(self):
        self.assertEqual(
            self._rows()[2],
            ["6", "Frida Andersson", "070-2", "frida@example.com", "Gatan 1", "623 55", "Visby", "angivet"],
        )

    def test_per_key_blanking(self):
        self.assertEqual(self._rows()[3], ["7", "Bo Bengtsson", "", "bo@example.com", "", "", "", "angivet"])

    def test_explicit_opt_out_keeps_nr_and_samtycke(self):
        self.assertEqual(self._rows()[4], ["8", "", "", "", "", "", "", "angivet"])

    def test_unset_consent_is_ej_angivet_and_blank(self):
        self.assertEqual(self._rows()[5], ["9", "", "", "", "", "", "", "ej angivet"])

    def test_requires_matrikel_admin(self):
        self.login("man")
        self.assertEqual(self.client.get("/api/v2/members/koharen-export").status_code, 403)

    def test_formula_injection_guarded(self):
        db.Member.update(first_name="=HYPERLINK()").where(db.Member.email == "anna@example.com").execute()
        self.assertTrue(self._rows()[1][1].startswith(" ="))
