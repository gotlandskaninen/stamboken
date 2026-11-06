"""Phase 19 — migrate_28_to_29: structured address backfill + member.user_id partial unique index."""

import unittest
from datetime import date

import utils.data_access as da
import utils.database as db
from peewee import IntegrityError

from tests.database_test import _USE_POSTGRES, DatabaseTest


@unittest.skipUnless(_USE_POSTGRES, "raw-SQL migration path needs PostgreSQL")
class TestPhase19Migration(DatabaseTest):
    def setUp(self):
        super().setUp()
        # Whatever this test does to the shared schema is undone by re-applying
        # the idempotent helper (columns back, postal_address dropped, index on).
        self.addCleanup(db._apply_phase19_schema_changes)

    def _to_v28_shape(self):
        sql = db.DB_PROXY.execute_sql
        sql('DROP INDEX IF EXISTS "idx_member_user_unique"')
        sql('CREATE INDEX IF NOT EXISTS "idx_member_user" ON "member" ("user_id")')
        sql('ALTER TABLE "membership" DROP COLUMN IF EXISTS "postal_code"')
        sql('ALTER TABLE "membership" DROP COLUMN IF EXISTS "city"')
        sql('ALTER TABLE "member_application" DROP COLUMN IF EXISTS "postal_code"')
        sql('ALTER TABLE "member_application" DROP COLUMN IF EXISTS "city"')
        sql('ALTER TABLE "membership" ADD COLUMN IF NOT EXISTS "postal_address" VARCHAR(100)')

    def _legacy_membership(self, postal_address):
        return db.DB_PROXY.execute_sql(
            'INSERT INTO "membership" ("membership_status", "publication_consent", "joined_date", '
            '"created_at", "updated_at", "postal_address") '
            "VALUES ('active', '{}', CURRENT_DATE, NOW(), NOW(), %s) RETURNING membership_id",
            (postal_address,),
        ).fetchone()[0]

    def _columns(self, table):
        return {c.name for c in db.DB_PROXY.get_columns(table)}

    def test_backfill_splits_parsing_values_and_drops_column(self):
        self._to_v28_shape()
        ids = {
            "spaced": self._legacy_membership("623 55 Visby"),
            "compact": self._legacy_membership("62355 Visby"),
            "padded": self._legacy_membership("  621 45   Visby  "),
            "box": self._legacy_membership("Box 12 Visby"),
            "empty": self._legacy_membership(""),
            "null": self._legacy_membership(None),
        }
        db._apply_phase19_schema_changes()
        got = {k: (db.Membership.get_by_id(v).postal_code, db.Membership.get_by_id(v).city) for k, v in ids.items()}
        self.assertEqual(got["spaced"], ("623 55", "Visby"))
        self.assertEqual(got["compact"], ("623 55", "Visby"))
        self.assertEqual(got["padded"], ("621 45", "Visby"))
        self.assertEqual(got["box"], (None, "Box 12 Visby"))
        self.assertEqual(got["empty"], (None, None))
        self.assertEqual(got["null"], (None, None))
        self.assertNotIn("postal_address", self._columns("membership"))
        self.assertLessEqual({"postal_code", "city"}, self._columns("member_application"))

    def test_preflight_keeps_one_row_per_user_then_index_rejects_duplicates(self):
        self._to_v28_shape()
        user = da.register_user("dup@example.com", "pass", username="dup")
        ms_a = db.Membership.create(membership_status="active")
        ms_b = db.Membership.create(membership_status="active")
        ended = db.Member.create(
            membership=ms_a,
            first_name="E",
            last_name="E",
            role="huvudmedlem",
            end_date=date(2020, 1, 1),
            user=user,
        )
        family = db.Member.create(membership=ms_b, first_name="F", last_name="F", role="familjemedlem", user=user)
        main = db.Member.create(membership=ms_b, first_name="M", last_name="M", role="huvudmedlem", user=user)

        db._apply_phase19_schema_changes()

        self.assertEqual(db.Member.get_by_id(main.id).user_id, user.id)
        self.assertIsNone(db.Member.get_by_id(family.id).user_id)
        self.assertIsNone(db.Member.get_by_id(ended.id).user_id)
        with self.assertRaises(IntegrityError):
            with db.DB_PROXY.atomic():
                db.Member.create(membership=ms_a, first_name="X", last_name="X", role="familjemedlem", user=user)

    def test_helper_is_idempotent_on_final_schema(self):
        before = self._columns("membership")
        db._apply_phase19_schema_changes()
        db._apply_phase19_schema_changes()
        self.assertEqual(self._columns("membership"), before)
        self.assertNotIn("postal_address", before)
        indexes = {i.name for i in db.DB_PROXY.get_indexes("member")}
        self.assertIn("idx_member_user_unique", indexes)
        self.assertNotIn("idx_member_user", indexes)

    def test_init_on_existing_schema_never_rewrites_links(self):
        """init() runs at every API start — it may (re)create the index but must
        not touch data; the preflight is migration-only."""
        a = da.register_user("a@example.com", "pass", username="a")
        b = da.register_user("b@example.com", "pass", username="b")
        ms = db.Membership.create(membership_status="active")
        row_a = db.Member.create(membership=ms, first_name="A", last_name="A", role="huvudmedlem", user=a)
        row_b = db.Member.create(membership=ms, first_name="B", last_name="B", role="familjemedlem", user=b)
        db.init()
        self.assertEqual((db.Member.get_by_id(row_a.id).user_id, db.Member.get_by_id(row_b.id).user_id), (a.id, b.id))
        self.assertNotIn("_reconcile_member_user_links", db._create_member_indexes.__code__.co_names)

    def test_init_bootstrap_path_enforces_unique_link(self):
        """Fresh databases never run migrations — init() must create the same index."""
        db.DB_PROXY.execute_sql('DROP INDEX IF EXISTS "idx_member_user_unique"')
        db.init()
        user = da.register_user("boot@example.com", "pass", username="boot")
        ms = db.Membership.create(membership_status="active")
        db.Member.create(membership=ms, first_name="A", last_name="A", role="huvudmedlem", user=user)
        with self.assertRaises(IntegrityError):
            with db.DB_PROXY.atomic():
                db.Member.create(membership=ms, first_name="B", last_name="B", role="familjemedlem", user=user)
