"""migrate_29_to_30: classification, backfill and fresh-bootstrap parity."""

import unittest
import uuid
from datetime import date, datetime, timezone

import utils.database as db
from peewee import IntegrityError

from tests.database_test import _USE_POSTGRES, DatabaseTest
from tests.ht_helpers import ht_row

NEW_COLUMNS = (
    "kind",
    "operation_id",
    "created_at",
    "notes",
    "voided_at",
    "voided_by_user_id",
    "voided_reason",
    "voided_operation_id",
    "restored_operation_id",
    "restored_at",
    "yearly_herd_report_id",
    "transfer_id",
    "holder_contact_id",
)


@unittest.skipUnless(_USE_POSTGRES, "raw-SQL migration path needs PostgreSQL")
class TestHerdTrackingMigration(DatabaseTest):
    def setUp(self):
        super().setUp()
        # Re-applying the idempotent helper restores the final schema for later tests.
        self.addCleanup(db._apply_herd_tracking_v30)

    def _sql(self, query, params=None):
        return db.DB_PROXY.execute_sql(query, params)

    def _to_v29_shape(self):
        self._sql('DROP TRIGGER IF EXISTS "herd_tracking_no_delete" ON "herd_tracking"')
        self._sql('TRUNCATE "herd_tracking"')
        for col in NEW_COLUMNS:
            self._sql(f'ALTER TABLE "herd_tracking" DROP COLUMN IF EXISTS "{col}"')
        self._sql(
            'CREATE INDEX IF NOT EXISTS "idx_herdtracking_individual_date" ON "herd_tracking" '
            "(individual_id, herd_tracking_date DESC, herd_tracking_id DESC)"
        )

    def _legacy_row(self, individual, herd, day):
        """A v29-shape row inserted with the audit trigger off (so no audit INSERT row exists)."""
        self._sql('ALTER TABLE "herd_tracking" DISABLE TRIGGER "audit_trigger"')
        try:
            return self._sql(
                'INSERT INTO "herd_tracking" ("individual_id", "herd_id", "herd_tracking_date") '
                'VALUES (%s, %s, %s) RETURNING "herd_tracking_id"',
                (individual.id, herd.id if herd else None, day),
            ).fetchone()[0]
        finally:
            self._sql('ALTER TABLE "herd_tracking" ENABLE TRIGGER "audit_trigger"')

    def _audit_count(self):
        return self._sql("SELECT count(*) FROM audit_log WHERE table_name = 'herd_tracking'").fetchone()[0]

    def _snapshot(self):
        q = self._sql
        return (
            set(
                q(
                    "SELECT column_name, data_type, character_maximum_length, is_nullable, "
                    "coalesce(column_default, '') "
                    "FROM information_schema.columns WHERE table_name = 'herd_tracking'"
                ).fetchall()
            ),
            set(q("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'herd_tracking'").fetchall()),
            set(
                q(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = 'herd_tracking'::regclass"
                ).fetchall()
            ),
            set(
                q(
                    "SELECT tgname FROM pg_trigger WHERE tgrelid = 'herd_tracking'::regclass AND NOT tgisinternal"
                ).fetchall()
            ),
        )

    def test_classification_by_position(self):
        self._to_v29_shape()
        g1, g2, _m3 = self.herds
        a, b, c, d = self.individuals[0], self.individuals[1], self.individuals[2], self.individuals[3]
        # a: origin G1; b: origin G2; c: origin M3; d: origin G1
        ids = {
            "a_birth": self._legacy_row(a, g1, date(2021, 2, 1)),
            "a_report": self._legacy_row(a, g1, date(2022, 1, 1)),
            "a_sale": self._legacy_row(a, g2, date(2022, 6, 1)),
            "a_report_buyer": self._legacy_row(a, g2, date(2023, 1, 1)),
            "a_back": self._legacy_row(a, g1, date(2023, 6, 1)),
            "b_birth": self._legacy_row(b, g2, date(2020, 2, 1)),
            "b_move_same_day": self._legacy_row(b, g1, date(2020, 2, 1)),
            "c_first_elsewhere": self._legacy_row(c, g1, date(2021, 2, 1)),
            "c_null_herd": self._legacy_row(c, None, date(2021, 5, 1)),
            "d_birth": self._legacy_row(d, g1, date(2021, 2, 1)),
            "d_dup_first_date": self._legacy_row(d, g1, date(2021, 2, 1)),
        }
        db._apply_herd_tracking_v30()
        kinds = {key: db.HerdTracking.get_by_id(pk).kind for key, pk in ids.items()}
        self.assertEqual(
            kinds,
            {
                "a_birth": "BIRTH",
                "a_report": "ATTESTATION",
                "a_sale": "TRANSFER",
                "a_report_buyer": "ATTESTATION",
                "a_back": "TRANSFER",
                "b_birth": "BIRTH",
                "b_move_same_day": "TRANSFER",
                "c_first_elsewhere": "TRANSFER",
                "c_null_herd": "TRANSFER",
                "d_birth": "BIRTH",
                "d_dup_first_date": "ATTESTATION",
            },
        )

    def test_backfill_created_at_operation_id_and_no_audit_rows(self):
        self._to_v29_shape()
        audited = self._legacy_row(self.individuals[0], self.herds[0], date(2022, 6, 1))
        plain = self._legacy_row(self.individuals[1], self.herds[1], date(2021, 2, 1))
        first_insert = datetime(2022, 6, 3, 9, 30, tzinfo=timezone.utc)
        for at in (datetime(2022, 6, 4, tzinfo=timezone.utc), first_insert):
            self._sql(
                "INSERT INTO audit_log (table_name, record_id, operation, changed_at) "
                "VALUES ('herd_tracking', %s, 'INSERT', %s)",
                (str(audited), at),
            )
        before = self._audit_count()
        db._apply_herd_tracking_v30()
        self.assertEqual(self._audit_count(), before, "backfill must not write audit rows")
        self.assertEqual(db.HerdTracking.get_by_id(audited).created_at, first_insert)
        # No audit row -> the tracking date at Stockholm midnight (CET = UTC+1 in February).
        self.assertEqual(db.HerdTracking.get_by_id(plain).created_at, datetime(2021, 1, 31, 23, 0, tzinfo=timezone.utc))
        op_ids = [r.operation_id for r in db.HerdTracking.select()]
        self.assertTrue(all(isinstance(o, uuid.UUID) for o in op_ids))
        self.assertEqual(len(set(op_ids)), len(op_ids))

    def test_columns_not_null_and_old_index_gone(self):
        self._to_v29_shape()
        self._legacy_row(self.individuals[0], self.herds[0], date(2021, 2, 1))
        db._apply_herd_tracking_v30()
        nullable = dict(
            self._sql(
                "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = 'herd_tracking'"
            ).fetchall()
        )
        self.assertEqual((nullable["kind"], nullable["operation_id"], nullable["created_at"]), ("NO", "NO", "NO"))
        default = self._sql(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'herd_tracking' AND column_name = 'kind'"
        ).fetchone()[0]
        self.assertIsNone(default, "kind must have no default")
        indexes = {row[0] for row in self._sql("SELECT indexname FROM pg_indexes WHERE tablename = 'herd_tracking'")}
        self.assertNotIn("idx_herdtracking_individual_date", indexes)
        self.assertLessEqual(
            {
                "idx_herdtracking_active_latest",
                "idx_herdtracking_one_birth",
                "idx_herdtracking_operation",
                "idx_herdtracking_voided_operation",
                "idx_herdtracking_restored_operation",
                "idx_herdtracking_report_attestation",
            },
            indexes,
        )

    def test_fresh_bootstrap_equals_migrated(self):
        # Make the fresh side genuinely fresh: earlier tests leave the migrated schema behind.
        self._sql('DROP TABLE "herd_tracking" CASCADE')
        db.init()
        bootstrapped = self._snapshot()
        self._to_v29_shape()
        db._apply_herd_tracking_v30()
        self.assertEqual(self._snapshot(), bootstrapped)

    def test_helper_is_idempotent_on_final_schema(self):
        before = self._snapshot()
        db._apply_herd_tracking_v30()
        db._apply_herd_tracking_v30()
        self.assertEqual(self._snapshot(), before)


@unittest.skipUnless(_USE_POSTGRES, "CHECK constraints and partial indexes need PostgreSQL")
class TestHerdTrackingGuards(DatabaseTest):
    def test_kind_check_rejects_unknown_kind(self):
        with self.assertRaises(IntegrityError), db.DB_PROXY.atomic():
            ht_row("DEATH", individual=self.individuals[0], herd=self.herds[0], herd_tracking_date=date(2022, 1, 1))

    def test_void_fields_all_or_nothing(self):
        row = ht_row(
            "ATTESTATION", individual=self.individuals[0], herd=self.herds[0], herd_tracking_date=date(2022, 1, 1)
        )
        with self.assertRaises(IntegrityError), db.DB_PROXY.atomic():
            db.HerdTracking.update(voided_at=datetime.now(timezone.utc)).where(db.HerdTracking.id == row.id).execute()
        with self.assertRaises(IntegrityError), db.DB_PROXY.atomic():
            db.HerdTracking.update(
                voided_at=datetime.now(timezone.utc),
                voided_by_user=self.manager,
                voided_operation_id=uuid.uuid4(),
                voided_reason="   ",
            ).where(db.HerdTracking.id == row.id).execute()

    def test_one_active_birth_per_individual(self):
        # The fixture already gave individuals[0] an active BIRTH.
        with self.assertRaises(IntegrityError), db.DB_PROXY.atomic():
            ht_row("BIRTH", individual=self.individuals[0], herd=self.herds[0], herd_tracking_date=date(2021, 2, 1))

    def test_one_active_attestation_per_report(self):
        report = db.YearlyHerdReport.create(
            herd=self.herds[0],
            report_date=date(2022, 1, 1),
            generated_by=self.manager,
            name="2021",
            data="{}",
            publish=False,
            publish_tel=False,
            publish_email=False,
            publish_address=False,
        )
        first = ht_row(
            "ATTESTATION",
            individual=self.individuals[0],
            herd=self.herds[0],
            herd_tracking_date=date(2022, 1, 1),
            yearly_herd_report=report,
        )
        with self.assertRaises(IntegrityError), db.DB_PROXY.atomic():
            ht_row(
                "ATTESTATION",
                individual=self.individuals[0],
                herd=self.herds[0],
                herd_tracking_date=date(2022, 1, 2),
                yearly_herd_report=report,
            )
        db.HerdTracking.update(
            voided_at=datetime.now(timezone.utc),
            voided_by_user=self.manager,
            voided_operation_id=uuid.uuid4(),
            voided_reason="test",
        ).where(db.HerdTracking.id == first.id).execute()
        ht_row(
            "ATTESTATION",
            individual=self.individuals[0],
            herd=self.herds[0],
            herd_tracking_date=date(2022, 1, 2),
            yearly_herd_report=report,
        )
