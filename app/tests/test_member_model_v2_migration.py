"""Tests for Member Model v2: new models, constraints, and the 25→26 expand migration."""

import json
import unittest
from datetime import date, datetime

import utils.database as db  # noqa: E402
from peewee import IntegrityError

from tests.database_test import _USE_POSTGRES, DatabaseTest, IsolatedSchemaTest  # noqa: E402


def reshape_to_v25():
    """Rebuild the v25 schema shape from a v2-bootstrapped test DB (raw SQL).

    Forward-compatible with the contract migration (26→27): the ADD COLUMN
    IF NOT EXISTS statements are no-ops while the superseded columns still
    exist (the intermediate state) and re-create them once the final migration has dropped them.
    """
    db.DATABASE.execute_sql('DROP TABLE IF EXISTS "matrikel_audit" CASCADE')
    db.DATABASE.execute_sql('DROP TABLE IF EXISTS "herd_access_grant" CASCADE')
    db.DATABASE.execute_sql('DROP TABLE IF EXISTS "member_number_counter" CASCADE')
    db.DATABASE.execute_sql('ALTER TABLE "member" DROP COLUMN IF EXISTS "membership_id"')
    db.DATABASE.execute_sql('ALTER TABLE "member" DROP COLUMN IF EXISTS "role"')
    db.DATABASE.execute_sql('ALTER TABLE "member" DROP COLUMN IF EXISTS "end_date"')
    db.DATABASE.execute_sql('ALTER TABLE "herd" DROP COLUMN IF EXISTS "membership_id"')
    db.DATABASE.execute_sql('DROP TABLE IF EXISTS "membership" CASCADE')
    db.DATABASE.execute_sql(
        'ALTER TABLE "member" ADD COLUMN IF NOT EXISTS "genebank_id" INTEGER REFERENCES "genebank" ("genebank_id")'
    )
    db.DATABASE.execute_sql(
        'ALTER TABLE "member" ADD COLUMN IF NOT EXISTS "herd_id" INTEGER REFERENCES "herd" ("herd_id")'
    )
    db.DATABASE.execute_sql(
        'ALTER TABLE "member" ADD COLUMN IF NOT EXISTS "membership_status" VARCHAR(20) NOT NULL DEFAULT \'active\''
    )
    db.DATABASE.execute_sql('ALTER TABLE "member" ADD COLUMN IF NOT EXISTS "address" TEXT')
    db.DATABASE.execute_sql(
        'ALTER TABLE "member" ADD COLUMN IF NOT EXISTS "publication_consent" JSONB NOT NULL DEFAULT \'{}\'::jsonb'
    )
    db.DATABASE.execute_sql('ALTER TABLE "member" ADD COLUMN IF NOT EXISTS "joined_date" DATE')
    db.DATABASE.execute_sql(
        'ALTER TABLE "member_application" ADD COLUMN IF NOT EXISTS "genebank_id" INTEGER '
        'REFERENCES "genebank" ("genebank_id")'
    )
    db.SchemaHistory.delete().where(db.SchemaHistory.version >= 26).execute()
    if db.SchemaHistory.get_or_none(db.SchemaHistory.version == 25) is None:
        db.SchemaHistory.insert(version=25, comment="test reshape", applied=datetime.now()).execute()


def insert_v25_member(genebank_id, first, last, email, herd_id, created_at, address=None, consent=None):
    """Insert a v25-shaped member row via raw SQL (the ORM is v2-shaped)."""
    db.DATABASE.execute_sql(
        'INSERT INTO "member" (first_name, last_name, email, genebank_id, herd_id, membership_status, '
        "address, publication_consent, joined_date, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb), %s, %s, %s)",
        (
            first,
            last,
            email,
            genebank_id,
            herd_id,
            "active",
            address,
            json.dumps(consent or {}),
            "2020-01-15",
            created_at,
            created_at,
        ),
    )


class TestMemberModelV2(DatabaseTest):
    """Model-level smoke tests for the v2 tables and partial indexes."""

    def test_membership_person_roundtrip(self):
        membership = db.Membership.create(address="Storgatan 1", postal_code="123 45", city="Visby")
        person = db.Member.create(
            first_name="Anna",
            last_name="Svensson",
            membership=membership,
        )
        self.assertEqual(person.role, "huvudmedlem")
        self.assertIsNone(person.end_date)
        self.assertEqual(membership.membership_status, "active")
        self.assertIsNone(membership.member_number)
        self.assertEqual(membership.publication_consent, {})
        self.assertEqual([p.id for p in membership.persons], [person.id])

    def test_herd_membership_backref(self):
        membership = db.Membership.create()
        herd = self.herds[0]
        herd.membership = membership
        herd.save()
        self.assertEqual([h.id for h in membership.herds], [herd.id])

    def test_grant_unique_per_member_herd(self):
        membership = db.Membership.create()
        person = db.Member.create(first_name="A", last_name="B", membership=membership)
        db.HerdAccessGrant.create(member=person, herd=self.herds[0], granted_by=self.admin)
        with self.assertRaises(IntegrityError):
            db.HerdAccessGrant.create(member=person, herd=self.herds[0], granted_by=self.admin)

    def test_matrikel_audit_row(self):
        membership = db.Membership.create()
        entry = db.MatrikelAudit.create(
            actor=self.admin,
            action="membership_created",
            membership=membership,
            payload={"after": {"member_number": None}},
        )
        self.assertIsNone(entry.payload["after"]["member_number"])
        self.assertEqual([a.id for a in membership.audit_entries], [entry.id])

    def test_member_number_unique_where_set(self):
        db.Membership.create(member_number=7)
        db.Membership.create()  # NULL — allowed (friexemplar)
        db.Membership.create()  # second NULL — allowed (partial index)
        with self.assertRaises(IntegrityError):
            db.Membership.create(member_number=7)

    def test_single_active_main_member_per_membership(self):
        membership = db.Membership.create()
        db.Member.create(first_name="Huvud", last_name="Medlem", membership=membership)
        # familjemedlem and an ENDED huvudmedlem don't collide with the partial index
        db.Member.create(
            first_name="Familj",
            last_name="Medlem",
            membership=membership,
            role="familjemedlem",
        )
        db.Member.create(
            first_name="Gammal",
            last_name="Huvudman",
            membership=membership,
            end_date=date(2024, 1, 1),
        )
        with self.assertRaises(IntegrityError):
            db.Member.create(first_name="Andra", last_name="Huvudman", membership=membership)

    def test_counter_has_single_seeded_row(self):
        rows = list(db.MemberNumberCounter.select())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].value, 0)


@unittest.skipUnless(_USE_POSTGRES, "CHECK constraints are added on PostgreSQL only")
class TestMemberModelV2Checks(DatabaseTest):
    """CHECK-constraint rejections (raw-SQL constraints, Postgres-only)."""

    def test_membership_status_check_rejects_unknown(self):
        with self.assertRaises(IntegrityError):
            db.Membership.create(membership_status="bogus")

    def test_membership_status_accepts_all_known_values(self):
        for status in ("active", "inactive", "pending", "friexemplar"):
            db.Membership.create(membership_status=status)
        self.assertEqual(db.Membership.select().count(), 4)

    def test_member_number_zero_rejected(self):
        with self.assertRaises(IntegrityError):
            db.Membership.create(member_number=0)

    def test_member_number_negative_rejected(self):
        with self.assertRaises(IntegrityError):
            db.Membership.create(member_number=-4)

    def test_member_role_check_rejects_unknown(self):
        membership = db.Membership.create()
        with self.assertRaises(IntegrityError):
            db.Member.create(
                first_name="A",
                last_name="B",
                membership=membership,
                role="styrelsemedlem",
            )


@unittest.skipUnless(_USE_POSTGRES, "the expand migration uses PostgreSQL-only raw SQL")
class TestMigrate25To26(IsolatedSchemaTest):
    """Populated v25 → 26 upgrade: backfill, herd linking, counter seed."""

    def test_populated_v25_backfill(self):
        reshape_to_v25()
        # One member owning herd G1; two members both pointing at herd G2
        # (the old FK was unconstrained — several rows per herd were possible).
        insert_v25_member(
            self.genebanks[0].id,
            "Anna",
            "Svensson",
            "anna@example.com",
            self.herds[0].id,
            "2020-01-01",
            address="Storgatan 1",
            consent={"name": True},
        )
        insert_v25_member(self.genebanks[0].id, "Bo", "Karlsson", "bo@example.com", self.herds[1].id, "2020-02-01")
        insert_v25_member(self.genebanks[0].id, "Cia", "Karlsson", "cia@example.com", self.herds[1].id, "2020-03-01")

        with self.assertLogs("herdbook.db", level="WARNING") as logs:
            db.migrate_25_to_26()

        # One membership per member row; fields copied; role huvudmedlem.
        self.assertEqual(db.Membership.select().count(), 3)
        anna = db.Member.get(db.Member.email == "anna@example.com")
        self.assertEqual(anna.role, "huvudmedlem")
        self.assertIsNotNone(anna.membership_id)
        self.assertEqual(anna.membership.membership_status, "active")
        self.assertEqual(anna.membership.address, "Storgatan 1")
        self.assertEqual(anna.membership.publication_consent, {"name": True})
        self.assertEqual(anna.membership.joined_date, date(2020, 1, 15))
        self.assertIsNone(anna.membership.member_number)

        # Exactly one referencing member: herd G1 → Anna's membership.
        g1 = db.Herd.get(db.Herd.herd == "G1")
        self.assertEqual(g1.membership_id, anna.membership_id)

        # Several referencing members: oldest row (Bo) wins + warning logged.
        bo = db.Member.get(db.Member.email == "bo@example.com")
        g2 = db.Herd.get(db.Herd.herd == "G2")
        self.assertEqual(g2.membership_id, bo.membership_id)
        self.assertTrue(any("referenced by" in line for line in logs.output))

        # Counter seeded from herd suffixes G1/G2/M3 → 3 (no member numbers yet).
        self.assertEqual(db.MemberNumberCounter.select().first().value, 3)

        self.assertEqual(db.SchemaHistory.select(db.fn.MAX(db.SchemaHistory.version)).scalar(), 26)

    def test_counter_seed_reports_nonmatching_herd_codes(self):
        db.MemberNumberCounter.delete().execute()
        db.Herd.create(genebank=self.genebanks[0], herd="G9X")
        with self.assertLogs("herdbook.db", level="WARNING") as logs:
            db._seed_member_number_counter()
        self.assertTrue(any("G9X" in line for line in logs.output))
        # G9X ignored; fixture herds G1/G2/M3 → mark 3.
        self.assertEqual(db.MemberNumberCounter.select().first().value, 3)

    def test_counter_seed_includes_existing_member_numbers(self):
        db.MemberNumberCounter.delete().execute()
        db.Membership.create(member_number=50)
        db._seed_member_number_counter()
        self.assertEqual(db.MemberNumberCounter.select().first().value, 50)


@unittest.skipUnless(_USE_POSTGRES, "the contract migration uses PostgreSQL-only raw SQL")
class TestMigrate26To27(IsolatedSchemaTest):
    """Populated v25 → 26 → 27 chain: superseded columns dropped, NOT NULL set."""

    SUPERSEDED_MEMBER_COLUMNS = (
        "genebank_id",
        "herd_id",
        "membership_status",
        "address",
        "publication_consent",
        "joined_date",
    )

    def test_contract_drops_superseded_columns(self):
        reshape_to_v25()
        insert_v25_member(
            self.genebanks[0].id,
            "Anna",
            "Svensson",
            "anna@example.com",
            self.herds[0].id,
            "2020-01-01",
            address="Storgatan 1",
        )
        db.migrate_25_to_26()
        db.migrate_26_to_27()

        member_cols = [c.name for c in db.DATABASE.get_columns("member")]
        for column in self.SUPERSEDED_MEMBER_COLUMNS:
            self.assertNotIn(column, member_cols)
        application_cols = [c.name for c in db.DATABASE.get_columns("member_application")]
        self.assertNotIn("genebank_id", application_cols)

        # Data survived: person row + membership with the copied address.
        anna = db.Member.get(db.Member.email == "anna@example.com")
        self.assertEqual(anna.membership.address, "Storgatan 1")
        self.assertEqual(anna.role, "huvudmedlem")

        # NOT NULL applied (the 25→26 backfill guarantees zero NULLs).
        is_nullable = db.DATABASE.execute_sql(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'member' AND column_name = 'membership_id'"
        ).fetchone()[0]
        self.assertEqual(is_nullable, "NO")

        # The per-gene-bank contact-email unique index is gone.
        index_row = db.DATABASE.execute_sql(
            "SELECT 1 FROM pg_indexes WHERE indexname = 'idx_member_genebank_email_unique'"
        ).fetchone()
        self.assertIsNone(index_row)

        self.assertEqual(db.SchemaHistory.select(db.fn.MAX(db.SchemaHistory.version)).scalar(), 27)

    def test_contract_is_a_noop_on_final_shape(self):
        """Re-running 26→27 against the already-contracted schema must not crash."""
        db.SchemaHistory.delete().where(db.SchemaHistory.version >= 27).execute()
        db.migrate_26_to_27()
        self.assertEqual(db.SchemaHistory.select(db.fn.MAX(db.SchemaHistory.version)).scalar(), 27)

    def test_contract_refuses_null_membership_rows(self):
        """A member row the 25→26 backfill missed must abort the contract
        migration BEFORE any column is dropped (the superseded columns hold
        that row's only data)."""
        reshape_to_v25()
        insert_v25_member(
            self.genebanks[0].id,
            "Orphan",
            "Rad",
            "orphan@example.com",
            self.herds[0].id,
            "2020-01-01",
        )
        db.migrate_25_to_26()
        db.DATABASE.execute_sql(
            'UPDATE "member" SET "membership_id" = NULL WHERE "email" = %s',
            ("orphan@example.com",),
        )

        with self.assertRaises(RuntimeError):
            db.migrate_26_to_27()

        # Rolled back: superseded columns survive, version stays 26.
        member_cols = [c.name for c in db.DATABASE.get_columns("member")]
        for column in self.SUPERSEDED_MEMBER_COLUMNS:
            self.assertIn(column, member_cols)
        self.assertEqual(db.SchemaHistory.select(db.fn.MAX(db.SchemaHistory.version)).scalar(), 26)
