"""Tests for Member (person rows), Membership and MemberApplication models (Member Model v2)."""

from datetime import datetime

import utils.database as db  # noqa: E402
from peewee import IntegrityError

from tests.database_test import DatabaseTest  # noqa: E402


class TestMemberModel(DatabaseTest):
    def test_create_minimal_person(self):
        membership = db.Membership.create()
        m = db.Member.create(first_name="Anna", last_name="Svensson", membership=membership)
        self.assertIsNotNone(m.id)
        self.assertIsNone(m.email)
        self.assertEqual(m.role, "huvudmedlem")
        self.assertIsNone(m.end_date)

    def test_member_requires_membership(self):
        with self.assertRaises(IntegrityError):
            db.Member.create(first_name="No", last_name="Membership")

    def test_consent_jsonb_roundtrip_on_membership(self):
        membership = db.Membership.create(publication_consent={"name": True, "email": False})
        reloaded = db.Membership.get_by_id(membership.id)
        self.assertEqual(reloaded.publication_consent, {"name": True, "email": False})

    def test_duplicate_contact_email_allowed(self):
        # v2 drops the per-gene-bank unique email index: families share one
        # contact email; the API layer warns instead of blocking.
        db.Member.create(first_name="Cia", last_name="A", email="cia@example.com", membership=db.Membership.create())
        db.Member.create(first_name="Cia", last_name="B", email="cia@example.com", membership=db.Membership.create())
        self.assertEqual(db.Member.select().where(db.Member.email == "cia@example.com").count(), 2)

    def test_workspace_email_globally_unique(self):
        db.Member.create(
            first_name="W",
            last_name="One",
            membership=db.Membership.create(),
            workspace_email="w.one@gotlandskaninen.se",
        )
        with self.assertRaises(IntegrityError):
            db.Member.create(
                first_name="W",
                last_name="Two",
                membership=db.Membership.create(),
                workspace_email="W.One@gotlandskaninen.se",  # case-insensitive LOWER() index
            )


class TestInvoiceAddress(DatabaseTest):
    POSTAL = {"address": "Hemvägen 1", "postal_code": "123 45", "city": "Exempelby"}

    def test_without_billing_address_falls_back_to_postal_address(self):
        ms = db.Membership.create(**self.POSTAL)
        self.assertEqual(
            db.Membership.get_by_id(ms.id).invoice_address,
            {
                "name": None,
                "address": "Hemvägen 1",
                "postal_code": "123 45",
                "city": "Exempelby",
                "email": None,
                "reference": None,
            },
        )

    def test_billing_address_replaces_postal_address(self):
        ms = db.Membership.create(
            **self.POSTAL,
            billing_name="Djurparken i Exempelby",
            billing_address="Box 99",
            billing_postal_code="987 65",
            billing_city="Annanstad",
            billing_email="faktura@djurparken.example",
            billing_reference="Kostnadsställe 4711",
        )
        self.assertEqual(
            db.Membership.get_by_id(ms.id).invoice_address,
            {
                "name": "Djurparken i Exempelby",
                "address": "Box 99",
                "postal_code": "987 65",
                "city": "Annanstad",
                "email": "faktura@djurparken.example",
                "reference": "Kostnadsställe 4711",
            },
        )

    def test_partial_billing_address_never_mixes_with_postal_address(self):
        """Only a billing city: the street and postal code are not borrowed from the postal address."""
        ms = db.Membership.create(**self.POSTAL, billing_city="Annanstad")
        invoice = db.Membership.get_by_id(ms.id).invoice_address
        self.assertEqual((invoice["address"], invoice["postal_code"], invoice["city"]), (None, None, "Annanstad"))

    def test_recipient_or_reference_alone_keeps_postal_address(self):
        """A reference or recipient without a billing street goes to the postal address."""
        ms = db.Membership.create(**self.POSTAL, billing_name="Gården", billing_reference="Er ref 12")
        invoice = db.Membership.get_by_id(ms.id).invoice_address
        self.assertEqual(invoice["name"], "Gården")
        self.assertEqual(invoice["reference"], "Er ref 12")
        self.assertEqual(
            (invoice["address"], invoice["postal_code"], invoice["city"]), ("Hemvägen 1", "123 45", "Exempelby")
        )


class TestMemberApplicationModel(DatabaseTest):
    def test_create_application(self):
        application = db.MemberApplication.create(
            first_name="Ny",
            last_name="Sökande",
            email="ny@example.com",
            gdpr_consented_at=datetime.now(),
            status="pending",
        )
        self.assertEqual(application.status, "pending")
        self.assertIsNone(application.reviewed_by)
        self.assertIsNone(application.created_member)

    def test_multiple_applications_same_email_allowed(self):
        # Reapply after rejection should be possible
        ts = datetime.now()
        db.MemberApplication.create(
            first_name="Re", last_name="Apply", email="reapply@example.com", gdpr_consented_at=ts, status="rejected"
        )
        db.MemberApplication.create(
            first_name="Re", last_name="Apply", email="reapply@example.com", gdpr_consented_at=ts, status="pending"
        )
        self.assertEqual(db.MemberApplication.select().count(), 2)
