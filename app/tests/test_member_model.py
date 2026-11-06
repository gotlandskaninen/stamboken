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
