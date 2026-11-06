"""Tests for /api/v2/member-applications endpoints (Member Model v2)."""

import json
import uuid
from datetime import datetime

import utils.database as db  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402

# Disable rate limiting in tests — the public POST carries a 10/hour cap
# and later classes log in more than 5 times/minute (see Test Conventions).
limiter.enabled = False


class TestPublicApplicationPOST(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _post(self, body, **kwargs):
        return self.client.post(
            "/api/v2/member-applications",
            data=json.dumps(body),
            content_type="application/json",
            **kwargs,
        )

    def test_valid_application_creates_pending(self):
        resp = self._post({"first_name": "Ny", "last_name": "Sokande", "email": "ny@example.com", "gdpr_consent": True})
        self.assertEqual(resp.status_code, 201, resp.data)
        data = resp.get_json()
        self.assertEqual(data["status"], "pending")
        app_row = db.MemberApplication.get_by_id(data["id"])
        self.assertEqual(app_row.status, "pending")
        self.assertIsNotNone(app_row.gdpr_consented_at)

    def test_genebank_id_in_body_is_ignored(self):
        """v2: membership is in the association — genebank_id is no longer
        read, validated, or stored (previously an unknown id was a 400)."""
        resp = self._post(
            {"first_name": "X", "last_name": "Y", "email": "x@y.example.com", "genebank_id": 9999, "gdpr_consent": True}
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        # The genebank column is dropped in v2; the ignored id
        # leaves a normal pending application.
        self.assertEqual(db.MemberApplication.get_by_id(resp.get_json()["id"]).status, "pending")

    def test_missing_gdpr_consent_rejected(self):
        resp = self._post({"first_name": "N", "last_name": "S", "email": "n@s.example.com"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.content_type, "application/problem+json")

    def test_gdpr_consent_false_rejected(self):
        resp = self._post({"first_name": "N", "last_name": "S", "email": "n@s.example.com", "gdpr_consent": False})
        self.assertEqual(resp.status_code, 400)

    def test_missing_required_field_rejected(self):
        resp = self._post({"last_name": "X", "email": "x@x.example.com", "gdpr_consent": True})
        self.assertEqual(resp.status_code, 400)

    def test_whitespace_only_field_rejected(self):
        resp = self._post(
            {"first_name": "   ", "last_name": "Svensson", "email": "ws@example.com", "gdpr_consent": True}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("first_name", resp.get_json().get("fields", []))

    def test_invalid_email_rejected(self):
        resp = self._post({"first_name": "X", "last_name": "Y", "email": "not-an-email", "gdpr_consent": True})
        self.assertEqual(resp.status_code, 400)

    def test_non_string_field_values_rejected_with_400(self):
        base = {"first_name": "Typ", "last_name": "Test", "email": "typ@example.com", "gdpr_consent": True}
        for patch in (
            {"first_name": ["Anna"]},
            {"last_name": 42},
            {"email": {"a": 1}},
            {"phone": 123},
            {"address": ["Gata 1"]},
            {"motivation": True},
        ):
            resp = self._post({**base, **patch})
            self.assertEqual(resp.status_code, 400, f"{patch}: {resp.data}")
            self.assertEqual(resp.content_type, "application/problem+json")
        self.assertFalse(db.MemberApplication.select().where(db.MemberApplication.email == "typ@example.com").exists())

    def test_structured_address_stored_and_validated(self):
        resp = self._post(
            {
                "first_name": "A",
                "last_name": "B",
                "email": "a@b.example.com",
                "gdpr_consent": True,
                "address": "Gatan 1",
                "postal_code": "62355",
                "city": "Visby",
            }
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        app_row = db.MemberApplication.get_by_id(resp.get_json()["id"])
        self.assertEqual((app_row.address, app_row.postal_code, app_row.city), ("Gatan 1", "623 55", "Visby"))
        resp = self._post(
            {"first_name": "A", "last_name": "B", "email": "a@b.example.com", "gdpr_consent": True, "postal_code": "12"}
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.get_json()["title"], "Ogiltigt postnummer")
        resp = self._post(
            {"first_name": "A", "last_name": "B", "email": "a@b.example.com", "gdpr_consent": True, "city": "x" * 101}
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.get_json()["detail"], "Postort får vara högst 100 tecken")


class TestReviewerApplicationEndpoints(DatabaseTest):
    """Gene banks are gone from the review flow: every reviewer (admin,
    matrikel_admin, manager) sees the whole queue."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        ts = datetime.now()
        self.app1 = db.MemberApplication.create(
            first_name="A", last_name="A", email="a@a.example.com", gdpr_consented_at=ts, status="pending"
        )
        self.app2 = db.MemberApplication.create(
            first_name="B", last_name="B", email="b@b.example.com", gdpr_consented_at=ts, status="pending"
        )

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.post("/api/login", json={"username": username, "password": password})

    def test_manager_sees_whole_queue(self):
        self.login("man", "pass")
        resp = self.client.get("/api/v2/member-applications?status=pending")
        self.assertEqual(resp.status_code, 200, resp.data)
        ids = [a["id"] for a in resp.get_json()["items"]]
        self.assertIn(self.app1.id, ids)
        self.assertIn(self.app2.id, ids)
        resp = self.client.get("/api/v2/member-applications/count?status=pending")
        self.assertEqual(resp.get_json(), {"pending": 2})

    def test_detail_has_no_genebank_fields(self):
        self.login("man", "pass")
        resp = self.client.get(f"/api/v2/member-applications/{self.app1.id}")
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.get_json()
        self.assertNotIn("genebank_id", data)
        self.assertNotIn("genebank_name", data)

    def test_unauthenticated_list_rejected(self):
        self.assertEqual(self.client.get("/api/v2/member-applications").status_code, 401)

    def test_owner_403(self):
        self.login("owner", "pass")
        self.assertEqual(self.client.get("/api/v2/member-applications").status_code, 403)

    def test_detail_exposes_postal_code_and_city(self):
        self.app1.postal_code, self.app1.city = "623 55", "Visby"
        self.app1.save()
        self.login()
        data = self.client.get(f"/api/v2/member-applications/{self.app1.id}").get_json()
        self.assertEqual((data["postal_code"], data["city"]), ("623 55", "Visby"))


class TestApplicationApproveReject(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        # Deterministic allocation regardless of the fixture's counter
        # re-seed policy: exactly one counter row at the 0 mark.
        db.MemberNumberCounter.delete().execute()
        db.MemberNumberCounter.create(value=0)
        self.pending = db.MemberApplication.create(
            first_name="A", last_name="A", email="a@a.example.com", gdpr_consented_at=datetime.now(), status="pending"
        )

    def login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.post("/api/login", json={"username": username, "password": password})

    def test_approve_creates_membership_and_main_person(self):
        self.login()
        resp = self.client.post(f"/api/v2/member-applications/{self.pending.id}/approve")
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.get_json()
        self.assertFalse(data["duplicate_contact_email"])
        self.assertNotIn("genebank_id", data)
        self.assertNotIn("genebank_name", data)
        person = db.Member.get_by_id(data["created_member_id"])
        self.assertEqual(person.role, "huvudmedlem")
        self.assertIsNone(person.end_date)
        self.assertEqual(person.email, "a@a.example.com")
        ms = person.membership
        self.assertEqual(ms.membership_status, "active")
        self.assertEqual(ms.member_number, 1)
        self.assertIsNone(ms.postal_address)
        audit = db.MatrikelAudit.get(db.MatrikelAudit.membership == ms)
        self.assertEqual(audit.action, "membership_created")
        app_row = db.MemberApplication.get_by_id(self.pending.id)
        self.assertEqual(app_row.status, "approved")
        self.assertEqual(app_row.reviewed_by_id, self.admin.id)
        self.assertIsNotNone(app_row.reviewed_at)

    def test_approve_allocates_sequential_numbers(self):
        second = db.MemberApplication.create(
            first_name="B", last_name="B", email="b@b.example.com", gdpr_consented_at=datetime.now(), status="pending"
        )
        self.login()
        r1 = self.client.post(f"/api/v2/member-applications/{self.pending.id}/approve")
        r2 = self.client.post(f"/api/v2/member-applications/{second.id}/approve")
        n1 = db.Member.get_by_id(r1.get_json()["created_member_id"]).membership.member_number
        n2 = db.Member.get_by_id(r2.get_json()["created_member_id"]).membership.member_number
        self.assertEqual([n1, n2], [1, 2])

    def test_approve_warns_on_duplicate_contact_email(self):
        ms = db.Membership.create(membership_status="active")
        db.Member.create(
            membership=ms, first_name="Gammal", last_name="Medlem", email="a@a.example.com", role="huvudmedlem"
        )
        self.login()
        resp = self.client.post(f"/api/v2/member-applications/{self.pending.id}/approve")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.get_json()["duplicate_contact_email"])
        # Warn, not block (families share contact emails — spec).
        self.assertEqual(db.Member.select().where(db.Member.email == "a@a.example.com").count(), 2)

    def test_double_approve_idempotent(self):
        self.login()
        self.assertEqual(self.client.post(f"/api/v2/member-applications/{self.pending.id}/approve").status_code, 200)
        r2 = self.client.post(f"/api/v2/member-applications/{self.pending.id}/approve")
        self.assertEqual(r2.status_code, 409)
        self.assertEqual(db.Member.select().count(), 1)
        self.assertEqual(db.Membership.select().count(), 1)

    def test_approve_rejected_application_409(self):
        self.pending.status = "rejected"
        self.pending.save()
        self.login()
        self.assertEqual(self.client.post(f"/api/v2/member-applications/{self.pending.id}/approve").status_code, 409)

    def test_reject_sets_reason_no_membership(self):
        self.login()
        resp = self.client.post(
            f"/api/v2/member-applications/{self.pending.id}/reject",
            data=json.dumps({"rejection_reason": "Not eligible"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        row = db.MemberApplication.get_by_id(self.pending.id)
        self.assertEqual(row.status, "rejected")
        self.assertEqual(row.rejection_reason, "Not eligible")
        self.assertFalse(db.Member.select().exists())
        self.assertFalse(db.Membership.select().exists())

    def test_reject_requires_reason(self):
        self.login()
        resp = self.client.post(
            f"/api/v2/member-applications/{self.pending.id}/reject",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_approve_never_auto_links_even_if_user_exists(self):
        db.User.create(username="existing", email="a@a.example.com", uuid=uuid.uuid4())
        self.login()
        resp = self.client.post(f"/api/v2/member-applications/{self.pending.id}/approve")
        self.assertEqual(resp.status_code, 200, resp.data)
        member = db.Member.get_by_id(resp.get_json()["created_member_id"])
        self.assertIsNone(member.user_id, "approve auto-linked despite OAuth-only policy")

    def test_approve_copies_structured_address(self):
        self.pending.address, self.pending.postal_code, self.pending.city = "Gatan 1", "623 55", "Visby"
        self.pending.save()
        self.login()
        resp = self.client.post(f"/api/v2/member-applications/{self.pending.id}/approve")
        ms = db.Member.get_by_id(resp.get_json()["created_member_id"]).membership
        self.assertEqual((ms.address, ms.postal_code, ms.city), ("Gatan 1", "623 55", "Visby"))

    def test_anonymize_after_approve_erases_application_address_columns(self):
        self.pending.address, self.pending.postal_code, self.pending.city = "Gatan 1", "623 55", "Visby"
        self.pending.save()
        self.login()
        resp = self.client.post(f"/api/v2/member-applications/{self.pending.id}/approve")
        person_id = resp.get_json()["created_member_id"]
        self.assertEqual(self.client.post(f"/api/v2/persons/{person_id}/anonymize").status_code, 200)
        app_row = db.MemberApplication.get_by_id(self.pending.id)
        self.assertEqual((app_row.address, app_row.postal_code, app_row.city), (None, None, None))

    def _applicant(self, first="Anna", last="Andersson", email="anna@example.com", **kwargs):
        defaults = {
            "phone": "0701234567",
            "address": "Gatan 1",
            "postal_code": "62355",
            "city": "Visby",
            "motivation": "Jag vill föda upp gotlandskaniner",
            "gdpr_consented_at": datetime.now(),
            "status": "pending",
        }
        return db.MemberApplication.create(first_name=first, last_name=last, email=email, **{**defaults, **kwargs})

    def _approve(self, application):
        """Approve as admin; returns the created person's id."""
        self.login()
        approved = self.client.post(f"/api/v2/member-applications/{application.id}/approve")
        self.assertEqual(approved.status_code, 200, approved.data)
        return approved.get_json()["created_member_id"]

    def _anonymize(self, person_id):
        resp = self.client.post(f"/api/v2/persons/{person_id}/anonymize")
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_anonymize_scrubs_duplicate_applications_of_the_same_applicant(self):
        """A rejected or pending duplicate from the same person keeps name, e-mail,
        phone and address after erasure — and every manager can list it. A relative who
        shares the contact e-mail, or a namesake with another e-mail, is not the person."""
        linked = self._applicant()
        rejected_dup = self._applicant(status="rejected", rejection_reason="Anna Andersson bor i Norge")
        pending_dup = self._applicant(email="ANNA@Example.com")  # same person, other casing
        relative = self._applicant(first="Bo")  # shares the household e-mail
        namesake = self._applicant(email="annan@example.com")
        self._anonymize(self._approve(linked))

        for dup in (rejected_dup, pending_dup):
            row = db.MemberApplication.get_by_id(dup.id)
            self.assertEqual(
                (row.first_name, row.last_name, row.email, row.phone, row.address, row.postal_code, row.city),
                ("Borttagen", "person", "[borttagen]", None, None, None, None),
            )
            self.assertIsNone(row.motivation)
        rejected = db.MemberApplication.get_by_id(rejected_dup.id)
        self.assertEqual(
            (rejected.status, rejected.rejection_reason), ("rejected", None)
        )  # reviewer text can quote her
        for other in (relative, namesake):
            row = db.MemberApplication.get_by_id(other.id)
            self.assertEqual((row.last_name, row.phone, row.address), ("Andersson", "0701234567", "Gatan 1"))

        self.client.get("/api/logout")
        self.login("man")
        listed = []
        for status in ("rejected", "pending"):
            listing = self.client.get(f"/api/v2/member-applications?status={status}")
            self.assertEqual(listing.status_code, 200, listing.data)
            listed += [(i["first_name"], i["email"], i["phone"]) for i in listing.get_json()["items"]]
        self.assertCountEqual(
            listed,
            [
                ("A", "a@a.example.com", None),  # setUp's pending application
                ("Borttagen", "[borttagen]", None),
                ("Borttagen", "[borttagen]", None),
                ("Bo", "anna@example.com", "0701234567"),
                ("Anna", "annan@example.com", "0701234567"),
            ],
        )

    def test_anonymize_closes_a_pending_duplicate_instead_of_leaving_it_approvable(self):
        """A scrubbed shell left pending could be approved into an active,
        numbered membership named "Borttagen person"."""
        linked = self._applicant()
        pending_dup = self._applicant()
        self._anonymize(self._approve(linked))

        row = db.MemberApplication.get_by_id(pending_dup.id)
        self.assertEqual((row.status, row.email), ("rejected", "[borttagen]"))
        resp = self.client.post(f"/api/v2/member-applications/{pending_dup.id}/approve")
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertEqual(db.Membership.select().count(), 1)

    def test_anonymize_scrubs_a_duplicate_that_was_approved_into_another_membership(self):
        """A reviewer approved the duplicate before (or while) the erasure ran;
        its application must not keep the PII just because it is linked elsewhere."""
        first = self._applicant()
        duplicate = self._applicant()
        first_person = self._approve(first)
        self._approve(duplicate)

        self._anonymize(first_person)

        row = db.MemberApplication.get_by_id(duplicate.id)
        self.assertEqual((row.status, row.email, row.phone, row.address), ("approved", "[borttagen]", None, None))

    def test_anonymize_scrubs_duplicates_made_under_the_old_email(self):
        """The person's e-mail was edited after approval; the duplicate still
        carries the one on the linked application."""
        linked = self._applicant()
        dup = self._applicant(status="rejected", rejection_reason="dubblett")
        person_id = self._approve(linked)
        person = db.Member.get_by_id(person_id)
        person.email = "anna.ny@example.se"
        person.save()

        self._anonymize(person_id)

        row = db.MemberApplication.get_by_id(dup.id)
        self.assertEqual((row.email, row.phone, row.address), ("[borttagen]", None, None))

    def test_anonymize_erases_the_household_address_of_the_only_person(self):
        """Approval copies the address onto the membership; erasing the only
        person must not leave it next to the member number."""
        self.pending.address, self.pending.postal_code, self.pending.city = "Storgatan 1", "623 55", "Visby"
        self.pending.save()
        person_id = self._approve(self.pending)
        membership_id = db.Member.get_by_id(person_id).membership_id

        self._anonymize(person_id)

        active = db.Member.select().where(db.Member.membership == membership_id, db.Member.end_date.is_null(True))
        self.assertEqual(active.count(), 0, "precondition: no active person left on the membership")
        ms = db.Membership.get_by_id(membership_id)
        self.assertEqual((ms.address, ms.postal_code, ms.city), (None, None, None))
        detail = self.client.get(f"/api/v2/members/{membership_id}").get_json()
        self.assertEqual((detail["address"], detail["postal_code"], detail["city"]), (None, None, None))
