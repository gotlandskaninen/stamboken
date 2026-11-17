"""migrate_41_to_42: the yearly report v2 schema, fresh-bootstrap parity, its guards and the legacy flow beside it."""

import unittest
import uuid
from datetime import date, datetime, timezone
from unittest import mock

import utils.data_access as da
import utils.database as db
from peewee import IntegrityError

from tests.database_test import _USE_POSTGRES, IsolatedSchemaTest
from tests.ht_helpers import ht_row

NEW_TABLES = (
    "report_access_code",
    "yearly_report_round_genebank",
    "yearly_report_submission",
    "sale_proposal",
    "yearly_report_draft",
    "member_change_request",
    "publication_consent_change",
)
TOUCHED_TABLES = (
    "yearlyreportround",
    "yearlyherdreport",
    "herd_tracking",
    "individual_command",
    "breeding",
    "inbox_item",
)
TABLES = list(NEW_TABLES + TOUCHED_TABLES)
NEW_COLUMNS = {
    "yearlyreportround": ("deadline",),
    "yearlyherdreport": (
        "status",
        "source",
        "access_code_id",
        "entered_by_id",
        "on_time_set_by_id",
        "support_approved_by_id",
        "voided_by_user_id",
        "inbox_item_id",
        "received_at",
        "support_approved_at",
        "voided_at",
        "on_time_override",
        "revision",
        "voided_by_access_code_id",
        "void_reason",
    ),
    "herd_tracking": ("access_code_id", "voided_by_access_code_id"),
    "individual_command": ("access_code_id",),
    "breeding": ("litter_size6w_preliminary",),
    "inbox_item": ("ref_data",),
}
LEGACY_NOT_NULL = ("name", "publish", "publish_tel", "publish_email", "publish_address", "generated_by_id")
NOW = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)


def _sql(query, params=None):
    return db.DB_PROXY.execute_sql(query, params)


def snapshot():
    """Columns, indexes, constraints and triggers of the tables migration 42 creates or changes."""
    return (
        set(
            _sql(
                "SELECT table_name, column_name, data_type, character_maximum_length, is_nullable, "
                "coalesce(column_default, '') FROM information_schema.columns WHERE table_name = ANY(%s)",
                (TABLES,),
            ).fetchall()
        ),
        set(_sql("SELECT tablename, indexname, indexdef FROM pg_indexes WHERE tablename = ANY(%s)", (TABLES,))),
        set(
            _sql(
                "SELECT c.relname, conname, pg_get_constraintdef(con.oid) FROM pg_constraint con "
                "JOIN pg_class c ON c.oid = con.conrelid WHERE c.relname = ANY(%s)",
                (TABLES,),
            ).fetchall()
        ),
        set(
            _sql(
                "SELECT c.relname, tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE c.relname = ANY(%s) AND NOT tgisinternal",
                (TABLES,),
            ).fetchall()
        ),
    )


def to_v41_shape():
    """The schema before migration 42: no new tables or columns, the old NOT NULLs and the old void CHECK."""
    _sql("DROP TABLE " + ", ".join(f'"{t}"' for t in NEW_TABLES) + " CASCADE")
    for table, columns in NEW_COLUMNS.items():
        _sql(f'ALTER TABLE "{table}" ' + ", ".join(f'DROP COLUMN "{c}"' for c in columns))
    _sql('ALTER TABLE "yearlyherdreport" ' + ", ".join(f'ALTER COLUMN "{c}" SET NOT NULL' for c in LEGACY_NOT_NULL))
    _sql('ALTER TABLE "individual_command" ALTER COLUMN "actor_id" SET NOT NULL')
    db._create_herd_tracking_guards()  # the void CHECK went with voided_by_access_code_id; put back the old one


@unittest.skipUnless(_USE_POSTGRES, "raw-SQL migration path needs PostgreSQL")
class TestArsrapportMigration(IsolatedSchemaTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bootstrapped = snapshot()  # the class's own database, built by init() from nothing

    def setUp(self):
        super().setUp()
        # First, so it runs last: the helper restores the final schema and the new void CHECK for later tests.
        self.addCleanup(db._create_arsrapport_schema)
        self.round = db.YearlyReportRound.create(report_year=2025, created_by=self.admin, is_active=True)

    def _old_report(self, herd, data='{"numberOfLitters": 2}'):
        """A report row in the v41 shape, written with raw SQL as the legacy app left it."""
        return _sql(
            'INSERT INTO "yearlyherdreport" (herd_id, report_date, generated_by_id, name, data, publish, '
            "publish_tel, publish_email, publish_address, version, round_id) "
            "VALUES (%s, %s, %s, 'Yearly Report 2025', %s, true, false, false, false, '1.0', %s) "
            "RETURNING yearly_herd_report_id",
            (herd.id, date(2026, 1, 5), self.owner.id, data, self.round.id),
        ).fetchone()[0]

    def _report(self, herd=None, **fields):
        fields = {"status": "submitted", "round": self.round, "data": "{}", **fields}
        return db.YearlyHerdReport.create(herd=herd or self.herds[0], report_date=date(2026, 1, 5), **fields)

    def _code(self):
        membership = db.Membership.create()
        member = db.Member.create(first_name="Test", last_name="Medlem", membership=membership)
        return db.ReportAccessCode.create(
            herd=self.herds[0], round=self.round, member=member, expires_at=date(2026, 1, 31)
        )

    def _legacy_form(self, **fields):
        return {"report_round_id": self.round.id, "report_year": 2025, "data": {"numberOfLitters": 1}, **fields}

    def test_fresh_bootstrap_equals_chain(self):
        to_v41_shape()
        db._create_arsrapport_schema()
        self.assertEqual(snapshot(), self.bootstrapped)

    def test_helper_is_idempotent(self):
        db._create_arsrapport_schema()
        db._create_arsrapport_schema()
        self.assertEqual(snapshot(), self.bootstrapped)

    def stamp_42(self, comment):
        """schema_history's 42 as `comment` until the test ends: the class's database was bootstrapped by init()."""
        row = db.SchemaHistory.get_by_id(42)
        db.SchemaHistory.update(comment=comment).where(db.SchemaHistory.version == 42).execute()
        self.addCleanup(db.SchemaHistory.update(comment=row.comment).where(db.SchemaHistory.version == 42).execute)

    def test_boot_adds_the_columns_a_database_at_42_lacks(self):
        """S5: a database that ran an earlier 42 gets the columns added to it since, under the same number."""
        self.stamp_42(f"{db.ARSRAPPORT_42} rounds per genebank")
        with mock.patch.object(db, "_create_arsrapport_schema") as helper, self.assertNoLogs(db.logger, "WARNING"):
            db.check_migrations()
        helper.assert_not_called()  # a healthy database takes no table lock at boot
        _sql('ALTER TABLE "inbox_item" DROP COLUMN "ref_data"')
        _sql('ALTER TABLE "breeding" DROP COLUMN "litter_size6w_preliminary"')
        with (
            mock.patch.object(db, "_create_arsrapport_schema") as helper,
            self.assertLogs(db.logger, "WARNING") as logs,
        ):
            self.assertTrue(db.verify(try_init=False))  # the boot: migrations under their lock, then the models
        helper.assert_not_called()  # L4: the two columns alone
        self.assertIn("breeding.litter_size6w_preliminary, inbox_item.ref_data", logs.output[0])
        self.assertEqual(snapshot(), self.bootstrapped)
        self.assertEqual(db.SchemaHistory.select(db.fn.MAX(db.SchemaHistory.version)).scalar(), 42)  # pylint: disable=E1120

    def test_boot_creates_a_yearly_report_table_a_database_at_42_lacks(self):  # Codex round 2, P2
        """Under the migration lock, not by a worker's verify() and init() racing for it."""
        self.stamp_42(f"{db.ARSRAPPORT_42} rounds per genebank")
        _sql('DROP TABLE "sale_proposal"')
        with self.assertLogs(db.logger, "WARNING") as logs:
            self.assertTrue(db.verify(try_init=False))  # no init(): the boot's repair made it
        self.assertIn("sale_proposal", logs.output[0])
        self.assertEqual(snapshot(), self.bootstrapped)

    def test_boot_leaves_alone_a_42_of_another_migration(self):  # L4: a collision of migration numbers
        for comment in ("Bootstrapped", "another branch's migration 42"):
            with self.subTest(comment):
                self.stamp_42(comment)
                with self.assertNoLogs(db.logger, "WARNING"):  # nothing missing: nothing said
                    db.check_migrations()
                _sql('ALTER TABLE "inbox_item" DROP COLUMN "ref_data"')
                with mock.patch.object(db, "_add_columns") as add, self.assertLogs(db.logger, "ERROR") as logs:
                    db.check_migrations()
                add.assert_not_called()
                self.assertIn("not repairing inbox_item.ref_data", logs.output[0])
                self.assertNotIn("ref_data", {c.name for c in db.DATABASE.get_columns("inbox_item")})
                db._create_arsrapport_schema()

    def test_one_submitted_report_per_herd_and_round(self):
        self._report()
        with self.assertRaises(IntegrityError), db.DB_PROXY.atomic():
            self._report()
        self._report(status="legacy")
        self._report(status="voided", voided_at=NOW, voided_by_user=self.manager, void_reason="fel besättning")
        self._report(herd=self.herds[1])

    def test_voided_report_needs_a_voider(self):
        for fields in (
            {"status": "voided", "voided_at": NOW},
            {"status": "voided", "voided_by_user": self.manager},
            {"status": "submitted", "voided_at": NOW, "voided_by_user": self.manager},
            {"status": "skickad"},
            {"source": "mejl"},
        ):
            with self.subTest(fields=sorted(fields)), self.assertRaises(IntegrityError), db.DB_PROXY.atomic():
                self._report(**fields)
        self._report(status="voided", voided_at=NOW, voided_by_access_code_id=self._code().id)

    def test_herd_tracking_void_by_access_code_is_accepted(self):
        row = ht_row(
            "ATTESTATION", individual=self.individuals[0], herd=self.herds[0], herd_tracking_date=date(2025, 12, 31)
        )
        code = self._code()
        void = {"voided_at": NOW, "voided_operation_id": uuid.uuid4(), "voided_reason": "ändrad"}
        for fields in (
            {"voided_by_access_code_id": code.id},  # not voided
            {**void, "voided_by_user": self.manager, "voided_by_access_code_id": code.id},  # two voiders
        ):
            with self.subTest(fields=sorted(fields)), self.assertRaises(IntegrityError), db.DB_PROXY.atomic():
                db.HerdTracking.update(**fields).where(db.HerdTracking.id == row.id).execute()
        db.HerdTracking.update(voided_by_access_code_id=code.id, **void).where(db.HerdTracking.id == row.id).execute()
        self.assertEqual(db.HerdTracking.get_by_id(row.id).voided_by_access_code_id, code.id)

    def test_helper_replaces_the_first_42_void_check(self):
        """A database that ran this branch's first 42 has the "user or code" CHECK: the helper swaps it."""
        _sql('ALTER TABLE "herd_tracking" DROP CONSTRAINT "herd_tracking_void_fields_check"')
        _sql(
            'ALTER TABLE "herd_tracking" ADD CONSTRAINT "herd_tracking_void_fields_check" CHECK ('
            "(voided_at IS NULL AND voided_by_user_id IS NULL AND voided_by_access_code_id IS NULL "
            "AND voided_operation_id IS NULL AND voided_reason IS NULL) OR (voided_at IS NOT NULL "
            "AND (voided_by_user_id IS NOT NULL OR voided_by_access_code_id IS NOT NULL) "
            "AND voided_operation_id IS NOT NULL AND btrim(coalesce(voided_reason, '')) <> ''))"
        )
        self.assertNotEqual(snapshot(), self.bootstrapped)
        db._create_arsrapport_schema()
        self.assertEqual(snapshot(), self.bootstrapped)

    def test_command_actor_or_access_code_exactly_one(self):
        code = self._code()

        def command(**actor):
            return db.IndividualCommand.create(
                operation_id=uuid.uuid4(),
                request_id=uuid.uuid4(),
                command="RecordDeath",
                individual=self.individuals[0],
                **actor,
            )

        command(actor=self.owner)
        command(access_code_id=code.id)
        for actor in ({}, {"actor": self.owner, "access_code_id": code.id}):
            with self.subTest(actor=sorted(actor)), self.assertRaises(IntegrityError), db.DB_PROXY.atomic():
                command(**actor)

    def test_submission_user_or_access_code_exactly_one(self):
        report, code = self._report(), self._code()

        def submission(**fields):
            fields = {"source": "login", **fields}
            return db.YearlyReportSubmission.create(
                report=report, submission_key=uuid.uuid4(), data={}, request_hash="h", **fields
            )

        self.assertEqual(submission(user=self.owner).operation_ids, [])
        submission(access_code=code)
        for actor in ({}, {"user": self.owner, "access_code": code}):
            with self.subTest(actor=sorted(actor)), self.assertRaises(IntegrityError), db.DB_PROXY.atomic():
                submission(**actor)
        with self.assertRaises(IntegrityError), db.DB_PROXY.atomic():
            submission(user=self.owner, source="mejl")

    def test_existing_reports_become_legacy(self):
        to_v41_shape()
        old = self._old_report(self.herds[0])
        db._create_arsrapport_schema()
        report = db.YearlyHerdReport.get_by_id(old)
        self.assertEqual((report.status, report.revision, report.data), ("legacy", 0, '{"numberOfLitters": 2}'))

        result = da.save_yearly_report(self.herds[1].id, self._legacy_form(), self.admin)
        self.assertEqual(result["status"], "success", result)
        saved = db.YearlyHerdReport.get(db.YearlyHerdReport.herd == self.herds[1])
        self.assertEqual(saved.status, "legacy")

    def test_legacy_list_and_export_ignore_v2_rows(self):
        legacy = self._old_report(self.herds[0])
        self._report(data='{"ending_genbank": false}')  # generated_by, name and publish NULL
        v2_only = db.YearlyReportRound.create(report_year=2026, created_by=self.admin)
        self._report(round=v2_only)

        reports = da.get_yearly_reports(self.round.id, self.genebanks[0].id)
        self.assertEqual([(r["herd"], r["litter_count"]) for r in reports], [("G1", 2)])
        self.assertIn("G1", da.export_yearly_reports_csv(self.round.id, self.genebanks[0].id))
        self.assertEqual(da.get_yearly_report_by_round(self.herds[0].id, self.round.id)["id"], legacy)
        self.assertIsNone(da.get_yearly_report_by_round(self.herds[0].id, v2_only.id))
        counts = {r["report_year"]: r["report_count"] for r in da.get_yearly_report_rounds_with_counts()}
        self.assertEqual(counts, {2025: 1, 2026: 0})

    def test_legacy_save_is_closed_where_v2_took_over(self):
        older = self._old_report(self.herds[0])
        v2 = self._report(data='{"ending_genbank": false}')
        db.YearlyReportRoundGenebank.create(
            round=self.round,
            genebank=self.genebanks[0],
            activated_by=self.manager,
            activated_at=NOW,
            send_at=date(2026, 1, 2),
        )
        for is_active, manually_activated in ((True, False), (False, True)):
            with self.subTest(is_active=is_active, manually_activated=manually_activated):
                db.YearlyReportRound.update(is_active=is_active, manually_activated=manually_activated).execute()
                rows = db.YearlyHerdReport.select().count()
                result = da.save_yearly_report(self.herds[0].id, self._legacy_form(), self.admin)
                self.assertEqual(
                    result, {"status": "error", "message": "Årsrapporten för den här genbanken lämnas i nya Stamboken."}
                )
                self.assertEqual(db.YearlyHerdReport.select().count(), rows)
                kept = db.YearlyHerdReport.get_by_id(v2.id)
                self.assertEqual(
                    (kept.status, kept.data, kept.generated_by_id), ("submitted", '{"ending_genbank": false}', None)
                )

        result = da.save_yearly_report(self.herds[2].id, self._legacy_form(), self.admin)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(db.YearlyHerdReport.get(db.YearlyHerdReport.herd == self.herds[2]).status, "legacy")
        self.assertEqual([r["herd"] for r in da.get_yearly_reports(self.round.id, self.genebanks[1].id)], ["M3"])
        self.assertEqual([r["herd"] for r in da.get_yearly_reports(self.round.id, self.genebanks[0].id)], ["G1"])
        self.assertIn("G1", da.export_yearly_reports_csv(self.round.id, self.genebanks[0].id))
        self.assertEqual(db.YearlyHerdReport.get_by_id(older).data, '{"numberOfLitters": 2}')

    def test_chain_from_40_with_legacy_data(self):
        self.addCleanup(db.check_migrations)  # puts 41 and 42 back if the test stops halfway
        db.SchemaHistory.delete().where(db.SchemaHistory.version >= 41).execute()
        if db.SchemaHistory.get_or_none(db.SchemaHistory.version == 40) is None:
            db.SchemaHistory.insert(version=40, comment="test seed", applied=datetime.now()).execute()  # pylint: disable=E1120
        _sql('ALTER TABLE "herd_tracking" DROP CONSTRAINT "herd_tracking_holder_contact_id_fkey"')
        _sql('DROP INDEX "herdtracking_holder_contact_id"')
        _sql('DROP TABLE "buyer_contact"')
        to_v41_shape()
        report = self._old_report(self.herds[0])
        voided = _sql(
            'INSERT INTO "herd_tracking" (individual_id, herd_id, herd_tracking_date, kind, operation_id, voided_at, '
            "voided_by_user_id, voided_operation_id, voided_reason) "
            "VALUES (%s, %s, '2025-12-31', 'ATTESTATION', gen_random_uuid(), now(), %s, gen_random_uuid(), 'fel') "
            "RETURNING herd_tracking_id",
            (self.individuals[0].id, self.herds[0].id, self.manager.id),
        ).fetchone()[0]
        command = _sql(
            'INSERT INTO "individual_command" (operation_id, request_id, command, individual_id, actor_id, created_at) '
            "VALUES (gen_random_uuid(), gen_random_uuid(), 'RecordDeath', %s, %s, now()) RETURNING id",
            (self.individuals[0].id, self.owner.id),
        ).fetchone()[0]

        db.check_migrations()

        versions = {v for (v,) in db.SchemaHistory.select(db.SchemaHistory.version).tuples()}
        self.assertLessEqual({40, 41, 42}, versions)
        self.assertEqual(snapshot(), self.bootstrapped)
        legacy = db.YearlyHerdReport.get_by_id(report)
        self.assertEqual((legacy.status, legacy.data, legacy.publish), ("legacy", '{"numberOfLitters": 2}', True))
        row = db.HerdTracking.get_by_id(voided)
        self.assertEqual((row.voided_by_user_id, row.voided_by_access_code_id), (self.manager.id, None))
        cmd = db.IndividualCommand.get_by_id(command)
        self.assertEqual((cmd.actor_id, cmd.access_code_id), (self.owner.id, None))

        history = list(db.SchemaHistory.select().tuples())
        db.check_migrations()  # replay-safe: nothing left to do
        self.assertEqual(list(db.SchemaHistory.select().tuples()), history)
        self.assertEqual(snapshot(), self.bootstrapped)

    def test_inbox_item_columns_have_no_fk(self):
        targets = {
            (table, target)
            for table, target in _sql(
                "SELECT conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint WHERE contype = 'f' "
                "AND conrelid IN ('yearlyherdreport'::regclass, 'sale_proposal'::regclass)"
            )
        }
        self.assertTrue({("yearlyherdreport", "report_access_code"), ("sale_proposal", "individual")} <= targets)
        self.assertFalse({target for _table, target in targets} & {"inbox_item", "herd_tracking"})
