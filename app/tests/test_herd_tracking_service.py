"""Central writer, kind invariants, operations and the lock protocol."""

import os
import threading
import unittest
import uuid
from datetime import date, timedelta
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from herdbook import APP, limiter  # noqa: E402
from peewee import IntegrityError  # noqa: E402
from utils import herd_tracking  # noqa: E402
from utils.herd_tracking import (  # noqa: E402
    HerdTrackingConflict,
    HerdTrackingError,
    HerdTrackingInvalid,
    check_invariants,
    record_herd_tracking,
)

from tests.database_test import _USE_POSTGRES, DatabaseTest  # noqa: E402
from tests.ht_helpers import _void, count_queries, ht_row, make_individual  # noqa: E402

limiter.enabled = False


class TestRecordHerdTracking(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.g1, self.g2 = self.herds[0], self.herds[1]
        self.ind = make_individual(self.g1, "G1-2401", date(2024, 1, 1))
        self.birth = ht_row("BIRTH", individual=self.ind, herd=self.g1, herd_tracking_date=date(2024, 1, 1))

    def test_transfer_sets_from_herd_to_the_holder(self):
        row = record_herd_tracking(self.ind, "G2", date(2024, 6, 1), "TRANSFER", self.manager)
        self.assertEqual((row.kind, row.from_herd_id, row.herd_id), ("TRANSFER", self.g1.id, self.g2.id))
        self.assertIsNotNone(row.operation_id)

    def test_birth_has_no_from_herd(self):
        fresh = make_individual(self.g1, "G1-2402", date(2024, 2, 1))
        row = record_herd_tracking(fresh, self.g1, date(2024, 2, 1), "BIRTH", self.manager)
        self.assertIsNone(row.from_herd_id)

    def test_date_before_latest_active_row_is_refused(self):
        record_herd_tracking(self.ind, self.g2, date(2024, 6, 1), "TRANSFER", self.manager)
        with self.assertRaises(HerdTrackingConflict) as ctx:
            record_herd_tracking(self.ind, self.g1, date(2024, 5, 1), "TRANSFER", self.manager)
        self.assertEqual(ctx.exception.detail, "Datumet är före kaninens senaste registrerade händelse.")
        self.assertIsInstance(ctx.exception, ValueError, "legacy callers catch ValueError")

    def test_same_date_as_latest_is_allowed(self):
        record_herd_tracking(self.ind, self.g2, date(2024, 6, 1), "TRANSFER", self.manager)
        record_herd_tracking(self.ind, self.g1, date(2024, 6, 1), "TRANSFER", self.manager)
        self.assertEqual(self.ind.current_herd.herd, "G1")

    def test_attestation_must_be_in_the_holders_herd(self):
        """I2 — a prefilled report link can never move a rabbit."""
        with self.assertRaises(HerdTrackingConflict) as ctx:
            record_herd_tracking(self.ind, self.g2, date(2024, 6, 1), "ATTESTATION", self.manager)
        self.assertEqual([r["code"] for r in ctx.exception.rows], ["I2"])
        self.assertEqual(db.HerdTracking.select().where(db.HerdTracking.individual == self.ind).count(), 1)

    def test_transfer_to_the_holder_is_refused(self):
        with self.assertRaises(HerdTrackingConflict) as ctx:
            record_herd_tracking(self.ind, self.g1, date(2024, 6, 1), "TRANSFER", self.manager)
        self.assertEqual([r["code"] for r in ctx.exception.rows], ["I4"])

    def test_second_active_birth_is_refused_before_the_index_fires(self):
        with self.assertRaises(HerdTrackingConflict) as ctx:
            record_herd_tracking(self.ind, self.g1, date(2024, 1, 1), "BIRTH", self.manager)
        self.assertEqual([r["code"] for r in ctx.exception.rows], ["I1"])

    def test_correction_kind_is_not_a_writer_kind(self):
        with self.assertRaises(HerdTrackingInvalid):
            record_herd_tracking(self.ind, self.g2, date(2024, 6, 1), "CORRECTION", self.manager)

    def test_same_operation_id_twice_writes_once(self):
        op = uuid.uuid4()
        first = record_herd_tracking(self.ind, self.g2, date(2024, 6, 1), "TRANSFER", self.manager, op)
        again = record_herd_tracking(self.ind, self.g2, date(2024, 6, 1), "TRANSFER", self.manager, str(op))
        self.assertEqual(first.id, again.id)
        self.assertEqual(db.HerdTracking.select().where(db.HerdTracking.operation_id == op).count(), 1)

    def test_existing_legacy_violation_does_not_block_new_attestation(self):
        """Delta check: a pre-existing I3 (row before BIRTH) must not block Phase 6 attestations."""
        legacy = make_individual(self.g1, "G1-2403", date(2024, 1, 1))
        ht_row("ATTESTATION", individual=legacy, herd=self.g1, herd_tracking_date=date(2023, 12, 1))
        ht_row("BIRTH", individual=legacy, herd=self.g1, herd_tracking_date=date(2024, 1, 1))
        rows = list(db.HerdTracking.select().where(db.HerdTracking.individual == legacy))
        self.assertIn("I3", {v.code for v in check_invariants(legacy, rows)})
        row = record_herd_tracking(legacy, self.g1, date(2025, 1, 1), "ATTESTATION", self.manager)
        self.assertEqual(row.kind, "ATTESTATION")

    def test_one_operation_across_many_individuals(self):
        """Review Focus 4 — Phase 6 bulk: one op id, one row per rabbit, retries idempotent, flat cost."""
        op = uuid.uuid4()
        rabbits = [make_individual(self.g1, f"G1-29{n:02d}", date(2024, 1, 1)) for n in range(5)]
        for rabbit in rabbits:
            ht_row("BIRTH", individual=rabbit, herd=self.g1, herd_tracking_date=date(2024, 1, 1))

        def report_all():
            with db.DB_PROXY.atomic():
                db.lock_individuals([r.id for r in rabbits])
                return [
                    record_herd_tracking(r, self.g1, date(2025, 1, 1), "ATTESTATION", self.manager, op) for r in rabbits
                ]

        first = report_all()
        self.assertEqual(len({row.id for row in first}), 5)
        again = report_all()
        self.assertEqual([r.id for r in again], [r.id for r in first])
        self.assertEqual(db.HerdTracking.select().where(db.HerdTracking.operation_id == op).count(), 5)
        with count_queries() as one_call:
            record_herd_tracking(rabbits[0], self.g1, date(2025, 2, 1), "ATTESTATION", self.manager)
        self.assertLessEqual(one_call["n"], 12, f"per-rabbit cost: {one_call['n']} queries")

    def test_legacy_wrapper_keeps_its_signature(self):
        row = da.update_herdtracking_values(self.ind, "G2", self.manager, date(2024, 6, 1), "TRANSFER")
        self.assertEqual(row.kind, "TRANSFER")

    def test_legacy_wrapper_validates_against_active_rows_only(self):
        """A re-sale after an undone (voided) sale is dated against the ACTIVE history, holder included."""
        undone = ht_row(
            "TRANSFER", individual=self.ind, from_herd=self.g1, herd=self.g2, herd_tracking_date=date(2024, 6, 1)
        )
        _void(undone, self.manager)
        row = da.update_herdtracking_values(self.ind, "G2", self.manager, date(2024, 3, 1), "TRANSFER")
        self.assertEqual((row.from_herd_id, row.herd_id), (self.g1.id, self.g2.id))

    def test_replay_of_a_void_only_operation_writes_nothing(self):
        """Idempotency matches voided_operation_id too: an op that only voided rows is already done."""
        op = uuid.uuid4()
        herd_tracking._void_rows([self.birth], self.manager, "test", op)
        again = record_herd_tracking(self.ind, self.g2, date(2024, 6, 1), "TRANSFER", self.manager, op)
        self.assertEqual(again.id, self.birth.id)
        self.assertEqual(db.HerdTracking.select().where(db.HerdTracking.individual == self.ind).count(), 1)

    def test_birth_dated_after_existing_rows_is_refused(self):
        """A BIRTH skips the date-order rule but may not leave older rows before it (new I3)."""
        late = make_individual(self.g1, "G1-2404", date(2024, 1, 1))
        early = ht_row("ATTESTATION", individual=late, herd=self.g1, herd_tracking_date=date(2024, 3, 1))
        with self.assertRaises(HerdTrackingConflict) as ctx:
            record_herd_tracking(late, self.g1, date(2024, 6, 1), "BIRTH", self.manager)
        self.assertEqual([(r["code"], r["id"]) for r in ctx.exception.rows], [("I3", early.id)])

    def test_unparseable_date_is_invalid(self):
        for bad in ("inte-ett-datum", None):
            with self.subTest(bad=bad):
                with self.assertRaises(HerdTrackingInvalid) as ctx:
                    record_herd_tracking(self.ind, self.g2, bad, "TRANSFER", self.manager)
                self.assertEqual(ctx.exception.detail, "Ogiltigt datum.")

    def test_failed_birth_write_rolls_back_the_new_individual(self):
        """add_individual: a refused BIRTH row must not leave an Individual without herd tracking."""
        form = {
            "herd": "G1",
            "origin_herd": {"herd": "G1"},
            "number": "G1-1998",
            "breeding": self.breeding[0].id,
            "birth_date": "2024-01-01",
        }
        with mock.patch.object(da, "record_herd_tracking", side_effect=HerdTrackingConflict("boom")):
            result = da.add_individual(form, self.admin.uuid)
        self.assertEqual(result, {"status": "error", "message": "boom"})
        self.assertFalse(db.Individual.select().where(db.Individual.number == "G1-1998").exists())

    def test_legacy_holder_fallback_reads_the_stored_origin_herd(self):
        """No active rows: the holder is the STORED origin herd, not the one the same form is changing."""
        form = {
            "id": self.ind.id,
            "number": self.ind.number,
            "herd": "G1",
            "yearly_report_date": "2024-06-01",
            "origin_herd": {"herd": "G2"},
            "breeding": self.ind.breeding_id,
        }
        herd_tracking._void_rows([self.birth], self.manager, "test", uuid.uuid4())
        with mock.patch("utils.individual_commands.record_herd_tracking") as write:
            da.update_individual(form, self.manager.uuid)
        self.assertEqual(write.call_args.args[3], "ATTESTATION")  # (individual, herd, date, kind, user)


@unittest.skipUnless(_USE_POSTGRES, "partial unique index and FK diagnostics need PostgreSQL")
class TestRecordHerdTrackingIntegrity(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.ind, self.g1 = self.individuals[0], self.herds[0]

    def test_second_attestation_for_the_same_report_is_a_conflict(self):
        report = db.YearlyHerdReport.create(
            herd=self.g1,
            report_date=date(2022, 1, 1),
            generated_by=self.manager,
            name="2021",
            data="{}",
            publish=False,
            publish_tel=False,
            publish_email=False,
            publish_address=False,
        )

        def attest():
            return record_herd_tracking(
                self.ind, self.g1, date(2022, 1, 1), "ATTESTATION", self.manager, yearly_herd_report=report
            )

        attest()
        with self.assertRaises(HerdTrackingConflict) as ctx:
            attest()
        self.assertIn("för den här rapporten", ctx.exception.detail)

    def test_other_integrity_errors_propagate_unchanged(self):
        with self.assertRaises(IntegrityError) as ctx:
            record_herd_tracking(self.ind, self.herds[1], date(2022, 1, 1), "TRANSFER", 999_999)
        self.assertNotIsInstance(ctx.exception, HerdTrackingError)


@unittest.skipUnless(_USE_POSTGRES, "row locks need PostgreSQL")
class TestHerdTrackingConcurrency(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.g3 = db.Herd.create(genebank=self.genebanks[0], herd="G3", herd_name="Tre")

    def _race(self, *workers):
        barrier = threading.Barrier(len(workers))
        results, failures = [None] * len(workers), []

        def run(index, fn):
            try:
                barrier.wait(timeout=10)
                results[index] = fn()
            except HerdTrackingConflict as exc:
                results[index] = exc
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(exc)
            finally:
                try:
                    db.DB_PROXY.close()
                except Exception:  # pylint: disable=broad-except
                    pass

        threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        for thread in threads:
            self.assertFalse(thread.is_alive(), "a worker is still blocked — lock never released")
        self.assertEqual(failures, [])
        return results

    def test_parallel_sales_are_serialised(self):
        ind_id, manager_id = self.individuals[0].id, self.manager.id
        day = date.today() - timedelta(days=1)

        def sell(code):
            return lambda: record_herd_tracking(
                db.Individual.get_by_id(ind_id), code, day, "TRANSFER", db.User.get_by_id(manager_id)
            )

        a, b = self._race(sell("G2"), sell("G3"))
        rows = sorted([a, b], key=lambda r: r.id)
        self.assertEqual(rows[0].from_herd_id, self.herds[0].id)
        self.assertEqual(rows[1].from_herd_id, rows[0].herd_id, "the second sale must see the first under the lock")

    def test_legacy_update_vs_v2_patch_do_not_deadlock(self):
        self.client.post("/api/login", json={"username": "owner", "password": "pass"})
        ind = self.individuals[0]
        today = date.today().isoformat()
        legacy_form = {
            "id": ind.id,
            "number": ind.number,
            "herd": "G1",
            "yearly_report_date": today,
            "weights": [{"date": today, "weight": 3.1}],
        }
        manager_uuid = self.manager.uuid
        with mock.patch.object(da.logger, "error") as logged:
            sale, legacy = self._race(
                lambda: self.client.patch(f"/api/individual/{ind.number}", json={"herd": "G2", "selling_date": today}),
                lambda: da.update_individual(dict(legacy_form), manager_uuid),
            )
        self.assertIn(sale.status_code, (200, 400), sale.get_data(as_text=True))
        self.assertIn(legacy["status"], ("success", "error"))
        self.assertFalse(any("deadlock" in str(call).lower() for call in logged.call_args_list))
        rows = list(db.HerdTracking.select().where(db.HerdTracking.individual == ind, db.ht_not_voided()))
        self.assertEqual(check_invariants(db.Individual.get_by_id(ind.id), rows), set())
