"""Billing address per membership: application, approval, matrikel read/write, export and erasure.

All names and addresses are made up.
"""

import csv
import io
import json
from datetime import datetime

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.matrikel as matrikel  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402

limiter.enabled = False

BILLING = {
    "billing_name": "Djurparken i Exempelby",
    "billing_address": "Box 99",
    "billing_postal_code": "98765",
    "billing_city": "Annanstad",
    "billing_email": "faktura@djurparken.example",
    "billing_reference": "Kostnadsställe 4711",
}
# As stored: the postal code normalised like the postal address.
BILLING_STORED = {**BILLING, "billing_postal_code": "987 65"}
NO_BILLING = dict.fromkeys(db.BILLING_FIELDS)


class BillingTestBase(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.matadmin = da.register_user("matadmin@example.com", "pass", username="matadmin")
        self.matadmin.add_role("matrikel_admin", None)
        self.membership = db.Membership.create(
            member_number=6, membership_status="active", address="Hemvägen 1", postal_code="123 45", city="Exempelby"
        )
        self.main = db.Member.create(
            membership=self.membership,
            first_name="Maja",
            last_name="Huvudsson",
            email="maja@example.com",
            role="huvudmedlem",
        )

    def login(self, username="matadmin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.post("/api/login", json={"username": username, "password": password})

    def patch_membership(self, body):
        return self.client.patch(
            f"/api/v2/memberships/{self.membership.id}", data=json.dumps(body), content_type="application/json"
        )

    def stored_billing(self):
        ms = db.Membership.get_by_id(self.membership.id)
        return {field: getattr(ms, field) for field in db.BILLING_FIELDS}


class TestMatrikelBillingAddress(BillingTestBase):
    def test_patch_saves_billing_address_and_detail_shows_it(self):
        self.login()
        resp = self.patch_membership(BILLING)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual({k: resp.get_json()[k] for k in db.BILLING_FIELDS}, BILLING_STORED)
        self.assertEqual(self.stored_billing(), BILLING_STORED)

        detail = self.client.get(f"/api/v2/members/{self.membership.id}").get_json()
        self.assertEqual({k: detail[k] for k in db.BILLING_FIELDS}, BILLING_STORED)
        # The postal address is untouched.
        self.assertEqual(
            (detail["address"], detail["postal_code"], detail["city"]), ("Hemvägen 1", "123 45", "Exempelby")
        )

    def test_patch_is_audited_like_the_postal_address(self):
        self.login()
        self.patch_membership({"billing_name": "Gården", "billing_city": "Annanstad"})
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "membership_updated")
        self.assertEqual(audit.payload["before"], {"billing_name": None, "billing_city": None})
        self.assertEqual(audit.payload["after"], {"billing_name": "Gården", "billing_city": "Annanstad"})

    def test_patch_with_nulls_clears_the_billing_address(self):
        db.Membership.update(**BILLING_STORED).where(db.Membership.id == self.membership.id).execute()
        self.login()
        resp = self.patch_membership(NO_BILLING)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self.stored_billing(), NO_BILLING)
        self.assertEqual(db.Membership.get_by_id(self.membership.id).invoice_address["city"], "Exempelby")

    def test_patch_blank_strings_are_stored_as_null(self):
        self.login()
        self.patch_membership({"billing_name": "  ", "billing_postal_code": "", "billing_email": " "})
        self.assertEqual(self.stored_billing(), NO_BILLING)

    def test_patch_rejects_invalid_billing_values(self):
        self.login()
        for body in (
            {"billing_postal_code": "1234"},
            {"billing_postal_code": 12345},
            {"billing_email": "inte-en-adress"},
            {"billing_city": "x" * 101},
            {"billing_name": "x" * 201},
            {"billing_reference": ["Er ref"]},
        ):
            with self.subTest(body=body):
                resp = self.patch_membership(body)
                self.assertEqual(resp.status_code, 400, resp.data)
                self.assertEqual(resp.content_type, "application/problem+json")
        self.assertEqual(self.stored_billing(), NO_BILLING)

    def test_list_rows_carry_the_billing_address(self):
        db.Membership.update(**BILLING_STORED).where(db.Membership.id == self.membership.id).execute()
        self.login()
        row = self.client.get("/api/v2/members").get_json()["items"][0]
        self.assertEqual(row["billing_name"], "Djurparken i Exempelby")


class TestBillingAddressPermissions(BillingTestBase):
    """Same gates as the postal address: matrikel read for GET, matrikel admin for PATCH."""

    def setUp(self):
        super().setUp()
        db.Membership.update(**BILLING_STORED).where(db.Membership.id == self.membership.id).execute()

    def test_manager_reads_but_cannot_change(self):
        self.login("man")
        detail = self.client.get(f"/api/v2/members/{self.membership.id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.get_json()["billing_city"], "Annanstad")
        self.assertEqual(self.patch_membership({"billing_city": "Någonstans"}).status_code, 403)
        self.assertEqual(self.stored_billing(), BILLING_STORED)

    def test_without_matrikel_rights_neither_read_nor_change(self):
        for username in ("owner", "spec"):
            with self.subTest(username=username):
                self.client = APP.test_client(use_cookies=True)
                self.login(username)
                self.assertEqual(self.client.get(f"/api/v2/members/{self.membership.id}").status_code, 403)
                self.assertEqual(self.client.get("/api/v2/members").status_code, 403)
                self.assertEqual(self.client.get("/api/v2/members/export").status_code, 403)
                self.assertEqual(self.patch_membership({"billing_city": "Någonstans"}).status_code, 403)
        self.assertEqual(self.stored_billing(), BILLING_STORED)

    def test_anonymous_gets_401(self):
        self.assertEqual(self.client.get(f"/api/v2/members/{self.membership.id}").status_code, 401)
        self.assertEqual(self.patch_membership({"billing_city": "Någonstans"}).status_code, 401)

    def test_self_service_view_leaves_the_billing_address_out(self):
        """/v2/my-membership feeds the profile, which does not show the billing address."""
        user = da.register_user("maja@example.com", "pass", username="maja")
        db.Member.update(user=user).where(db.Member.id == self.main.id).execute()
        self.login("maja")
        resp = self.client.get("/api/v2/my-membership")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(set(db.BILLING_FIELDS) & set(resp.get_json()["membership"]))


def _csv_rows(resp):
    return list(csv.reader(io.StringIO(resp.data.decode("utf-8-sig"))))


class TestBillingAddressExport(BillingTestBase):
    def setUp(self):
        super().setUp()
        db.Member.create(membership=self.membership, first_name="Frank", last_name="Huvudsson", role="familjemedlem")
        db.Membership.update(**BILLING_STORED).where(db.Membership.id == self.membership.id).execute()
        self.plain = db.Membership.create(
            member_number=7, membership_status="active", address="Byvägen 2", postal_code="234 56", city="Lillby"
        )
        db.Member.create(membership=self.plain, first_name="Bo", last_name="Bengtsson", email="bo@example.com")

    def test_matrikel_export_has_invoice_columns(self):
        self.login()
        header, *rows = _csv_rows(self.client.get("/api/v2/members/export"))
        invoice_columns = header[-6:]
        self.assertEqual(
            invoice_columns,
            [
                "Fakturamottagare",
                "Fakturaadress",
                "Fakturapostnummer",
                "Fakturapostort",
                "E-post för faktura",
                "Fakturareferens",
            ],
        )
        by_name = {r[header.index("Namn Efternamn")]: r for r in rows}
        self.assertEqual(
            by_name["Maja Huvudsson"][-6:],
            [
                "Djurparken i Exempelby",
                "Box 99",
                "987 65",
                "Annanstad",
                "faktura@djurparken.example",
                "Kostnadsställe 4711",
            ],
        )
        # Membership-level cells only on the main row.
        self.assertEqual(by_name["Frank Huvudsson"][-6:], [""] * 6)
        # Without a billing address the invoice goes to the postal address.
        self.assertEqual(by_name["Bo Bengtsson"][-6:], ["", "Byvägen 2", "234 56", "Lillby", "", ""])

    def test_published_matrikel_never_has_the_billing_address(self):
        """The Koharen export is published: the billing address must not reach it, whatever the consent."""
        everything = {"name": True, "phone": True, "email": True, "address": True}
        db.Membership.update(publication_consent=everything).execute()
        self.login()
        resp = self.client.get("/api/v2/members/koharen-export")
        self.assertEqual(resp.status_code, 200, resp.data)
        text = resp.data.decode("utf-8-sig")
        self.assertIn("Hemvägen 1", text)  # the postal address is published with consent
        for value in BILLING_STORED.values():
            with self.subTest(value=value):
                self.assertNotIn(value, text)
        self.assertNotIn("Faktura", _csv_rows(resp)[0])


class TestApplicationBillingAddress(BillingTestBase):
    def setUp(self):
        super().setUp()
        db.MemberNumberCounter.delete().execute()
        db.MemberNumberCounter.create(value=100)

    def post_application(self, **extra):
        body = {
            "first_name": "Nora",
            "last_name": "Nysson",
            "email": "nora@example.com",
            "address": "Hemvägen 3",
            "postal_code": "12345",
            "city": "Exempelby",
            "gdpr_consent": True,
            **extra,
        }
        return self.client.post("/api/v2/member-applications", data=json.dumps(body), content_type="application/json")

    def test_application_stores_billing_address_and_approval_copies_it(self):
        resp = self.post_application(**BILLING)
        self.assertEqual(resp.status_code, 201, resp.data)
        app_id = resp.get_json()["id"]
        application = db.MemberApplication.get_by_id(app_id)
        self.assertEqual({k: getattr(application, k) for k in db.BILLING_FIELDS}, BILLING_STORED)

        self.login("man")  # gene bank managers review applications
        detail = self.client.get(f"/api/v2/member-applications/{app_id}").get_json()
        self.assertEqual({k: detail[k] for k in db.BILLING_FIELDS}, BILLING_STORED)

        approved = self.client.post(f"/api/v2/member-applications/{app_id}/approve")
        self.assertEqual(approved.status_code, 200, approved.data)
        ms = db.Member.get_by_id(approved.get_json()["created_member_id"]).membership
        self.assertEqual({k: getattr(ms, k) for k in db.BILLING_FIELDS}, BILLING_STORED)
        self.assertEqual((ms.address, ms.postal_code, ms.city), ("Hemvägen 3", "123 45", "Exempelby"))
        self.assertEqual(ms.invoice_address["address"], "Box 99")

    def test_application_without_billing_address_approves_to_postal_invoice(self):
        app_id = self.post_application().get_json()["id"]
        self.login()
        approved = self.client.post(f"/api/v2/member-applications/{app_id}/approve")
        ms = db.Member.get_by_id(approved.get_json()["created_member_id"]).membership
        self.assertEqual({k: getattr(ms, k) for k in db.BILLING_FIELDS}, NO_BILLING)
        invoice = ms.invoice_address
        self.assertEqual(
            (invoice["address"], invoice["postal_code"], invoice["city"]), ("Hemvägen 3", "123 45", "Exempelby")
        )

    def test_application_rejects_invalid_billing_values(self):
        for extra in (
            {"billing_postal_code": "abcde"},
            {"billing_email": "faktura@"},
            {"billing_city": "x" * 101},
            {"billing_reference": "x" * 101},
            {"billing_name": 7},
        ):
            with self.subTest(extra=extra):
                resp = self.post_application(**extra)
                self.assertEqual(resp.status_code, 400, resp.data)
                self.assertEqual(resp.content_type, "application/problem+json")
        self.assertEqual(db.MemberApplication.select().count(), 0)


class TestBillingAddressErasure(BillingTestBase):
    def test_erasing_the_last_person_clears_and_redacts_the_billing_address(self):
        family = db.Member.create(
            membership=self.membership, first_name="Frank", last_name="Huvudsson", role="familjemedlem"
        )
        self.login()
        self.patch_membership(BILLING)
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "membership_updated")

        matrikel.anonymize_person(family, self.admin)
        self.assertEqual(self.stored_billing(), BILLING_STORED)  # someone still lives there

        matrikel.anonymize_person(self.main, self.admin)
        self.assertEqual(self.stored_billing(), NO_BILLING)
        payload = db.MatrikelAudit.get_by_id(audit.id).payload
        self.assertEqual(payload["before"], NO_BILLING)
        self.assertEqual(payload["after"], dict.fromkeys(db.BILLING_FIELDS, matrikel.REDACTED_VALUE))

    def test_erasure_scrubs_the_billing_address_from_the_application(self):
        application = db.MemberApplication.create(
            first_name="Nora",
            last_name="Nysson",
            email="nora@example.com",
            gdpr_consented_at=datetime.now(),
            status="pending",
            **BILLING_STORED,
        )
        db.MemberNumberCounter.delete().execute()
        db.MemberNumberCounter.create(value=100)
        self.login()
        approved = self.client.post(f"/api/v2/member-applications/{application.id}/approve")
        person_id = approved.get_json()["created_member_id"]
        self.assertEqual(self.client.post(f"/api/v2/persons/{person_id}/anonymize").status_code, 200)

        scrubbed = db.MemberApplication.get_by_id(application.id)
        self.assertEqual({k: getattr(scrubbed, k) for k in db.BILLING_FIELDS}, NO_BILLING)
        ms = db.Member.get_by_id(person_id).membership
        self.assertEqual({k: getattr(ms, k) for k in db.BILLING_FIELDS}, NO_BILLING)
