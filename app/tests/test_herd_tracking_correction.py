"""Correction command and undoing an operation."""

import unittest
import uuid
from datetime import date, timedelta
from unittest import mock

import utils.data_access as da
import utils.database as db
from utils import herd_tracking
from utils.herd_tracking import (
    HerdTrackingConflict,
    HerdTrackingForbidden,
    HerdTrackingInvalid,
    HerdTrackingNotFound,
    correct_herd_tracking,
    record_herd_tracking,
    replace_birth_row,
    undo_herd_tracking_operation,
    void_all_for_unpromote,
    void_herd_tracking,
)

from tests.database_test import _USE_POSTGRES, DatabaseTest
from tests.ht_helpers import _active, ht_row, make_individual


class CorrectionBase(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.g1, self.g2 = self.herds[0], self.herds[1]
        self.gx1 = db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför", is_active=True)
        # Real-case shape: born 2025-04-01, sold out 2025-09-30, wrongly reported in 2026.
        self.rabbit = make_individual(self.g1, "G1-2511", date(2025, 4, 1))
        self.birth = ht_row("BIRTH", individual=self.rabbit, herd=self.g1, herd_tracking_date=date(2025, 4, 1))
        self.report = record_herd_tracking(self.rabbit, self.g1, date(2026, 2, 1), "ATTESTATION", self.owner)

    def _g1147_fix(self, op=None):
        return correct_herd_tracking(
            self.rabbit,
            self.manager,
            op or uuid.uuid4(),
            [self.report.id],
            [{"date": "2025-09-30", "herd": "GX1", "kind": "TRANSFER", "notes": None}],
            reason="Felaktig årsrapport, såld utanför genbanken",
        )


class TestCorrection(CorrectionBase):
    def test_g1147_end_to_end(self):
        written = self._g1147_fix()
        self.assertEqual(
            [(r.kind, r.herd_id, r.from_herd_id) for r in written], [("TRANSFER", self.gx1.id, self.g1.id)]
        )
        self.assertEqual(db.Individual.get_by_id(self.rabbit.id).current_herd.herd, "GX1")
        report = db.HerdTracking.get_by_id(self.report.id)
        self.assertEqual(report.voided_operation_id, written[0].operation_id)
        self.assertFalse(da.was_in_herd_at_date(self.rabbit.id, self.g1.id, date(2026, 1, 1)))
        v1 = db.Individual.get_by_id(self.rabbit.id).as_dict()
        self.assertEqual(v1["herd"]["herd"], "GX1")
        self.assertEqual([t["herd"] for t in v1["herd_tracking"]], ["GX1", "G1"])

    def test_same_day_with_an_unvoided_event_is_refused(self):
        sale = record_herd_tracking(self.rabbit, self.g2, date(2026, 3, 1), "TRANSFER", self.manager)
        with self.assertRaises(HerdTrackingConflict) as ctx:
            correct_herd_tracking(
                self.rabbit,
                self.manager,
                uuid.uuid4(),
                [],
                [{"date": "2026-03-01", "herd": "GX1", "kind": "CORRECTION"}],
            )
        self.assertEqual([r["id"] for r in ctx.exception.rows], [sale.id])

    def test_whole_day_re_entered_in_order_is_accepted(self):
        sale = record_herd_tracking(self.rabbit, self.g2, date(2026, 3, 1), "TRANSFER", self.manager)
        written = correct_herd_tracking(
            self.rabbit,
            self.manager,
            uuid.uuid4(),
            [sale.id],
            [
                {"date": "2026-03-01", "herd": "G2", "kind": "TRANSFER"},
                {"date": "2026-03-01", "herd": "G1", "kind": "TRANSFER"},
            ],
            reason="Tur och retur samma dag",
        )
        self.assertEqual([r.herd_id for r in written], [self.g2.id, self.g1.id])
        self.assertEqual(db.Individual.get_by_id(self.rabbit.id).current_herd.herd, "G1")

    def test_invariant_negatives(self):
        cases = {
            "I1": ([], [{"date": "2025-04-01", "herd": "G1", "kind": "BIRTH"}]),
            "I2": ([], [{"date": "2026-03-01", "herd": "G2", "kind": "ATTESTATION"}]),
            "I3": ([], [{"date": "2025-01-01", "herd": "G2", "kind": "CORRECTION"}]),
            "I4": ([], [{"date": "2026-03-01", "herd": "G1", "kind": "TRANSFER"}]),
            "I5": ([self.birth.id], []),
        }
        for code, (void_ids, events) in cases.items():
            with self.assertRaises(HerdTrackingConflict, msg=code) as ctx:
                correct_herd_tracking(self.rabbit, self.manager, uuid.uuid4(), void_ids, events, reason="test")
            self.assertIn(code, [r["code"] for r in ctx.exception.rows], code)
        self.assertEqual(len(_active(self.rabbit)), 2, "every refused correction rolled back")

    def test_only_managers_of_the_genebank(self):
        other_manager = da.register_user("othermgr", "pass")
        other_manager.add_role("manager", self.genebanks[1].id)
        for user in (self.owner, db.User.get_by_id(other_manager.id)):
            with self.assertRaises(HerdTrackingForbidden):
                self._g1147_fix_as(user)

    def _g1147_fix_as(self, user):
        return correct_herd_tracking(
            self.rabbit,
            user,
            uuid.uuid4(),
            [self.report.id],
            [{"date": "2025-09-30", "herd": "GX1", "kind": "TRANSFER"}],
            reason="test",
        )

    def test_input_validation(self):
        bad = {
            "not chronological": [
                {"date": "2025-10-02", "herd": "G2", "kind": "TRANSFER"},
                {"date": "2025-10-01", "herd": "G1", "kind": "TRANSFER"},
            ],
            "future": [{"date": (date.today() + timedelta(days=2)).isoformat(), "herd": "G2", "kind": "TRANSFER"}],
            "other genebank": [{"date": "2025-10-01", "herd": "M3", "kind": "TRANSFER"}],
            "unknown kind": [{"date": "2025-10-01", "herd": "G2", "kind": "DEATH"}],
            "bad date": [{"date": "1 okt", "herd": "G2", "kind": "TRANSFER"}],
            "contact in notes": [{"date": "2025-10-01", "herd": "G2", "kind": "TRANSFER", "notes": "a@b.example.com"}],
        }
        for label, events in bad.items():
            with self.assertRaises(HerdTrackingInvalid, msg=label):
                correct_herd_tracking(self.rabbit, self.manager, uuid.uuid4(), [], events)
        with self.assertRaises(HerdTrackingInvalid):
            correct_herd_tracking(self.rabbit, self.manager, uuid.uuid4(), [self.report.id], [], reason="  ")

    def test_contact_details_in_the_reason_are_refused(self):
        """No buyer identity in free text — the void reason of a correction."""
        with self.assertRaises(HerdTrackingInvalid):
            correct_herd_tracking(
                self.rabbit,
                self.manager,
                uuid.uuid4(),
                [self.report.id],
                [{"date": "2025-09-30", "herd": "GX1", "kind": "TRANSFER"}],
                reason="Köparen nås på 070-123 45 67",
            )
        self.assertEqual(len(_active(self.rabbit)), 2)

    def test_a_correction_birth_must_match_the_individual(self):
        """Ruling: Individual and BIRTH stay coupled — other herd/date goes through the individual edit."""
        bad = {
            "other herd": {"date": "2025-04-01", "herd": "G2", "kind": "BIRTH"},
            "other date": {"date": "2025-04-02", "herd": "G1", "kind": "BIRTH"},
        }
        for label, event in bad.items():
            with self.assertRaises(HerdTrackingInvalid, msg=label):
                correct_herd_tracking(self.rabbit, self.manager, uuid.uuid4(), [self.birth.id], [event], reason="test")
        self.assertEqual(len(_active(self.rabbit)), 2)

    def test_a_non_text_herd_is_a_400_not_a_500(self):
        for herd in ({"herd": "G2"}, ["G2"], 2):
            with self.assertRaises(HerdTrackingInvalid, msg=repr(herd)):
                correct_herd_tracking(
                    self.rabbit,
                    self.manager,
                    uuid.uuid4(),
                    [],
                    [{"date": "2025-10-01", "herd": herd, "kind": "TRANSFER"}],
                )
        self.assertEqual(len(_active(self.rabbit)), 2)

    def test_birth_re_entered_through_a_correction(self):
        op = uuid.uuid4()
        written = correct_herd_tracking(
            self.rabbit,
            self.manager,
            op,
            [self.birth.id],
            [{"date": "2025-04-01", "herd": "G1", "kind": "BIRTH"}],
            reason="Födelseraden matas in igen",
        )
        self.assertEqual([(r.kind, r.from_herd_id) for r in written], [("BIRTH", None)])
        self.assertEqual([r.id for r in _active(self.rabbit) if r.kind == "BIRTH"], [written[0].id])
        self.assertEqual(db.HerdTracking.get_by_id(self.birth.id).voided_operation_id, op)

    def test_multi_row_correction_is_idempotent(self):
        """Review Focus 4 — two rows for one rabbit under one op id, retried."""
        op = uuid.uuid4()
        events = [
            {"date": "2025-09-30", "herd": "G2", "kind": "TRANSFER"},
            {"date": "2025-10-15", "herd": "GX1", "kind": "TRANSFER"},
        ]
        reason = "Två flyttar"
        first = correct_herd_tracking(self.rabbit, self.manager, op, [self.report.id], events, reason=reason)
        again = correct_herd_tracking(self.rabbit, self.manager, str(op), [self.report.id], events, reason=reason)
        self.assertEqual([r.id for r in first], [r.id for r in again])
        self.assertEqual(db.HerdTracking.select().where(db.HerdTracking.operation_id == op).count(), 2)


class TestUndoOperation(CorrectionBase):
    def test_undo_restores_exactly(self):
        before_ids = [r.id for r in _active(self.rabbit)]
        written = self._g1147_fix()
        result = undo_herd_tracking_operation(written[0].operation_id, self.manager, "Fel korrigering")
        self.assertEqual([r.id for r in _active(self.rabbit)], before_ids)
        restored = db.HerdTracking.get_by_id(self.report.id)
        self.assertEqual(
            (restored.voided_at, restored.voided_by_user_id, restored.voided_reason, restored.voided_operation_id),
            (None, None, None, None),
        )
        undone = db.HerdTracking.get_by_id(written[0].id)
        self.assertEqual(str(undone.voided_operation_id), result["undo_operation_id"])
        self.assertEqual(result["individual_ids"], [self.rabbit.id])

    def test_later_operation_blocks_undo(self):
        written = self._g1147_fix()
        record_herd_tracking(self.rabbit, self.g2, date(2026, 5, 1), "TRANSFER", self.manager)
        with self.assertRaises(HerdTrackingConflict):
            undo_herd_tracking_operation(written[0].operation_id, self.manager, "Fel")

    def test_rows_voided_by_a_later_operation_block_undo(self):
        written = self._g1147_fix()
        void_herd_tracking(written[0].id, self.manager, "Senare rättelse")
        with self.assertRaises(HerdTrackingConflict):
            undo_herd_tracking_operation(written[0].operation_id, self.manager, "Fel")

    def test_undo_is_idempotent_and_manager_only(self):
        written = self._g1147_fix()
        op = written[0].operation_id
        with self.assertRaises(HerdTrackingForbidden):
            undo_herd_tracking_operation(op, self.owner, "Fel")
        undo_op = uuid.uuid4()
        undo_herd_tracking_operation(op, self.manager, "Fel", undo_op)
        undo_herd_tracking_operation(op, self.manager, "Fel", undo_op)
        self.assertEqual(db.HerdTracking.select().where(db.HerdTracking.voided_operation_id == undo_op).count(), 1)

    def test_replayed_undo_id_still_checks_permission(self):
        """Ruling M22: a non-manager replaying a known undo id gets 403, not the cached result."""
        written = self._g1147_fix()
        op, undo_op = written[0].operation_id, uuid.uuid4()
        undo_herd_tracking_operation(op, self.manager, "Fel", undo_op)
        with self.assertRaises(HerdTrackingForbidden):
            undo_herd_tracking_operation(op, self.owner, "Fel", undo_op)

    def test_contact_details_in_the_undo_reason_are_refused(self):
        written = self._g1147_fix()
        with self.assertRaises(HerdTrackingInvalid):
            undo_herd_tracking_operation(written[0].operation_id, self.manager, "Köparen: a@b.example.com")
        self.assertIsNone(db.HerdTracking.get_by_id(written[0].id).voided_at)

    def test_unknown_operation_is_404(self):
        with self.assertRaises(HerdTrackingNotFound):
            undo_herd_tracking_operation(uuid.uuid4(), self.manager, "Fel")

    def test_unpromote_cannot_be_undone_here(self):
        rows = void_all_for_unpromote(self.rabbit, self.manager)
        db.Individual.update(voided=True).where(db.Individual.id == self.rabbit.id).execute()
        op = db.HerdTracking.get_by_id(rows[0].id).voided_operation_id
        with self.assertRaises(HerdTrackingConflict):
            undo_herd_tracking_operation(op, self.manager, "Fel")

    def test_one_operation_over_two_rabbits_is_undone_under_one_lock(self):
        other = make_individual(self.g1, "G1-2512", date(2025, 4, 1))
        ht_row("BIRTH", individual=other, herd=self.g1, herd_tracking_date=date(2025, 4, 1))
        op = uuid.uuid4()
        rows = [
            record_herd_tracking(ind, self.g1, date(2026, 3, 1), "ATTESTATION", self.manager, op)
            for ind in (self.rabbit, other)
        ]
        with mock.patch.object(herd_tracking, "lock_individuals", wraps=herd_tracking.lock_individuals) as lock:
            result = undo_herd_tracking_operation(op, self.manager, "Fel rapport")
        lock.assert_called_once_with(sorted([self.rabbit.id, other.id]))
        self.assertEqual(result["individual_ids"], sorted([self.rabbit.id, other.id]))
        for row in rows:
            self.assertIsNotNone(db.HerdTracking.get_by_id(row.id).voided_at)

    def test_undo_of_a_birth_replacement_restores_the_old_birth(self):
        new_birth = replace_birth_row(self.rabbit, self.manager, date=date(2025, 3, 30), reason="Fel datum")
        undo_herd_tracking_operation(new_birth.operation_id, self.manager, "Fel")
        self.assertEqual([r.id for r in _active(self.rabbit) if r.kind == "BIRTH"], [self.birth.id])
        self.assertIsNotNone(db.HerdTracking.get_by_id(new_birth.id).voided_at)

    def test_undoing_the_undo_of_a_birth_replacement_is_a_409(self):
        """The redo would re-void the restored BIRTH and revive one that no longer matches the individual."""
        new_birth = replace_birth_row(self.rabbit, self.manager, date=date(2025, 3, 30), reason="Fel datum")
        undo = undo_herd_tracking_operation(new_birth.operation_id, self.manager, "Fel")
        active = [r.id for r in _active(self.rabbit)]
        with self.assertRaises(HerdTrackingConflict) as ctx:
            undo_herd_tracking_operation(undo["undo_operation_id"], self.manager, "Fel igen")
        self.assertEqual([r["id"] for r in ctx.exception.rows], [new_birth.id])
        self.assertEqual([r.id for r in _active(self.rabbit)], active)

    @unittest.skipUnless(_USE_POSTGRES, "partial unique index needs PostgreSQL")
    def test_undoing_the_undo_of_a_re_attestation_redoes_it(self):
        report = db.YearlyHerdReport.create(
            herd=self.g1,
            report_date=date(2026, 3, 1),
            generated_by=self.manager,
            name="2026",
            data="{}",
            publish=False,
            publish_tel=False,
            publish_email=False,
            publish_address=False,
        )
        first = record_herd_tracking(
            self.rabbit, self.g1, date(2026, 3, 1), "ATTESTATION", self.manager, yearly_herd_report=report
        )
        reattest = uuid.uuid4()  # a re-attestation: void + write for the same report in one operation
        herd_tracking._void_rows([first], self.manager, "Ny rapport", reattest)
        ht_row(
            "ATTESTATION",
            individual=self.rabbit,
            herd=self.g1,
            herd_tracking_date=date(2026, 3, 1),
            yearly_herd_report=report,
            operation_id=reattest,
        )
        reattested = [r.id for r in _active(self.rabbit)]
        undo = undo_herd_tracking_operation(reattest, self.manager, "Fel")
        self.assertIn(first.id, [r.id for r in _active(self.rabbit)])
        undo_herd_tracking_operation(undo["undo_operation_id"], self.manager, "Fel igen")
        self.assertEqual([r.id for r in _active(self.rabbit)], reattested, "re-void first, then unvoid: no collision")

    def test_second_undo_of_a_void_only_operation_is_a_404(self):
        void_herd_tracking(self.report.id, self.manager, "Fel rapport")
        op = db.HerdTracking.get_by_id(self.report.id).voided_operation_id
        undo_herd_tracking_operation(op, self.manager, "Fel")
        with self.assertRaises(HerdTrackingNotFound):
            undo_herd_tracking_operation(op, self.manager, "Fel")

    def test_rows_undone_while_waiting_for_the_lock_is_a_404(self):
        void_herd_tracking(self.report.id, self.manager, "Fel rapport")
        op = db.HerdTracking.get_by_id(self.report.id).voided_operation_id
        real_lock = herd_tracking.lock_individuals

        def lock_after_a_concurrent_undo(ids):
            herd_tracking._unvoid_rows([self.report], uuid.uuid4())  # the other undo commits before our lock
            return real_lock(ids)

        with mock.patch.object(herd_tracking, "lock_individuals", side_effect=lock_after_a_concurrent_undo):
            with self.assertRaises(HerdTrackingNotFound):
                undo_herd_tracking_operation(op, self.manager, "Fel")


class UndoChainBase(CorrectionBase):
    def setUp(self):
        super().setUp()
        self.g3 = db.Herd.create(genebank=self.genebanks[0], herd="G3", herd_name="Tre", is_active=True)
        self.doe = make_individual(self.g1, "G1-2513", date(2025, 1, 1))
        ht_row("BIRTH", individual=self.doe, herd=self.g1, herd_tracking_date=date(2025, 1, 1))
        self.april = record_herd_tracking(self.doe, self.g2, date(2025, 4, 10), "TRANSFER", self.manager)

    def _ids(self):
        return sorted(r.id for r in _active(self.doe))

    def _undo(self, op, undo_op=None):
        return undo_herd_tracking_operation(op, self.manager, "Fel", undo_op)


class TestUndoOfAnUndo(UndoChainBase):
    """An undo records what it restored, so undoing it re-voids exactly that."""

    def test_undo_chain_alternates_between_the_two_states(self):
        (may,) = correct_herd_tracking(
            self.doe,
            self.manager,
            uuid.uuid4(),
            [self.april.id],
            [{"date": "2025-05-10", "herd": "G3", "kind": "TRANSFER"}],
            reason="Såld till G3 i maj",
        )
        state_a = self._ids()
        self.assertIn(may.id, state_a)
        self.assertNotIn(self.april.id, state_a)

        b = self._undo(may.operation_id)
        state_b = self._ids()
        self.assertIn(self.april.id, state_b)
        self.assertNotIn(may.id, state_b)

        c = self._undo(b["undo_operation_id"])
        self.assertEqual(self._ids(), state_a, "undoing B gives exactly A's state: May active, April voided")
        self.assertEqual(db.Individual.get_by_id(self.doe.id).current_herd.herd, "G3")
        self.assertEqual(str(db.HerdTracking.get_by_id(self.april.id).voided_operation_id), c["undo_operation_id"])

        d = self._undo(c["undo_operation_id"])
        self.assertEqual(self._ids(), state_b, "undoing C gives B's state again")
        self.assertEqual(str(db.HerdTracking.get_by_id(self.april.id).restored_operation_id), d["undo_operation_id"])

    def test_undo_of_an_undo_is_idempotent(self):
        (may,) = correct_herd_tracking(
            self.doe,
            self.manager,
            uuid.uuid4(),
            [self.april.id],
            [{"date": "2025-05-10", "herd": "G3", "kind": "TRANSFER"}],
            reason="Såld till G3 i maj",
        )
        b = self._undo(may.operation_id)
        redo = uuid.uuid4()
        self._undo(b["undo_operation_id"], redo)
        state = self._ids()
        self._undo(b["undo_operation_id"], redo)
        self.assertEqual(self._ids(), state)
        with self.assertRaises(HerdTrackingConflict):  # a NEW undo of B: its effects are already reverted
            self._undo(b["undo_operation_id"])

    def test_undo_of_a_void_only_undo_re_voids_and_replays(self):
        void_herd_tracking(self.april.id, self.manager, "Fel försäljning")
        op = db.HerdTracking.get_by_id(self.april.id).voided_operation_id
        undo_op = uuid.uuid4()
        self._undo(op, undo_op)
        self.assertIn(self.april.id, self._ids())
        replay = self._undo(op, undo_op)  # the restore is recorded: the replay finds it
        self.assertEqual(replay["undo_operation_id"], str(undo_op))
        self.assertIn(self.april.id, self._ids())
        self._undo(undo_op)
        self.assertNotIn(self.april.id, self._ids(), "redo of the void-only operation")

    def test_a_later_row_blocks_undoing_a_restore(self):
        void_herd_tracking(self.april.id, self.manager, "Fel försäljning")
        op = db.HerdTracking.get_by_id(self.april.id).voided_operation_id
        undo = self._undo(op)
        record_herd_tracking(self.doe, self.g3, date(2025, 6, 1), "TRANSFER", self.manager)
        with self.assertRaises(HerdTrackingConflict):
            self._undo(undo["undo_operation_id"])
        self.assertIn(self.april.id, self._ids())


class TestLaterMutationBlocksUndo(UndoChainBase):
    """Any later create, void or restore on the individuals blocks undoing an operation."""

    def test_void_and_undo_of_a_restored_row_blocks_undoing_the_undo(self):
        (may,) = correct_herd_tracking(
            self.doe,
            self.manager,
            uuid.uuid4(),
            [self.april.id],
            [{"date": "2025-05-10", "herd": "G3", "kind": "TRANSFER"}],
            reason="Såld till G3 i maj",
        )
        b = self._undo(may.operation_id)
        void_herd_tracking(self.april.id, self.manager, "Fel")
        x = db.HerdTracking.get_by_id(self.april.id).voided_operation_id
        self._undo(x)  # April restored again, now by this undo — B's restore trace is overwritten
        state = self._ids()
        with self.assertRaises(HerdTrackingConflict) as ctx:
            self._undo(b["undo_operation_id"])
        self.assertIn(self.april.id, [r["id"] for r in ctx.exception.rows])
        self.assertEqual(self._ids(), state, "nothing written")
        history = herd_tracking.herd_tracking_history(db.Individual.get_by_id(self.doe.id), self.manager)
        may_row = next(r for r in history["rows"] if r["id"] == may.id)
        self.assertEqual(may_row["voided_operation_id"], b["undo_operation_id"])
        self.assertFalse(may_row["can_undo_operation"], "the hint agrees with the service")

    def test_a_later_void_only_operation_blocks_undo(self):
        """Supersedes T9's "a later void-only op does not block undo"."""
        older = record_herd_tracking(self.doe, self.g2, date(2025, 5, 1), "ATTESTATION", self.manager)
        report = record_herd_tracking(self.doe, self.g2, date(2025, 6, 1), "ATTESTATION", self.manager)
        void_herd_tracking(older.id, self.manager, "Fel rapport")  # writes no row, voids an OLDER one
        with self.assertRaises(HerdTrackingConflict) as ctx:
            self._undo(report.operation_id)
        self.assertEqual([r["id"] for r in ctx.exception.rows], [older.id])
        self.assertIsNone(db.HerdTracking.get_by_id(report.id).voided_at)


class TestUndoKeepsBirthCoupled(DatabaseTest):
    """Undoing a BIRTH replacement must not decouple the BIRTH row from the individual."""

    def setUp(self):
        super().setUp()
        self.g1, self.g2 = self.herds[0], self.herds[1]
        self.breeding = db.Breeding.create(
            breed_date=date(2026, 1, 1),
            birth_date=date(2026, 2, 1),
            mother=self.parents[0],
            father=self.parents[1],
            litter_size=1,
            litter_size6w=1,
            breeding_herd_id=self.g1,
        )
        self.kit = db.Individual.create(origin_herd=self.g1, breeding=self.breeding, number="G1-2621", sex="female")
        ht_row("BIRTH", individual=self.kit, herd=self.g1, herd_tracking_date=date(2026, 2, 1))

    def _new_birth(self):
        return next(r for r in _active(self.kit) if r.kind == "BIRTH")

    def _state(self):
        return [(r.id, r.voided_at) for r in db.HerdTracking.select().where(db.HerdTracking.individual == self.kit)]

    def _assert_undo_refused(self, op):
        before = self._state()
        with self.assertRaises(HerdTrackingConflict) as ctx:
            undo_herd_tracking_operation(op, self.manager, "Fel")
        self.assertIn("på kaninen i stället", ctx.exception.detail)
        self.assertEqual(self._state(), before, "nothing written")
        ind = db.Individual.get_by_id(self.kit.id)
        rows = herd_tracking.herd_tracking_history(ind, db.User.get_by_id(self.manager.id))["rows"]
        self.assertFalse(next(r for r in rows if r["operation_id"] == str(op))["can_undo_operation"])

    def test_undo_of_an_origin_change_is_a_409(self):
        form = {
            "id": self.kit.id,
            "number": self.kit.number,
            "herd": "G1",
            "origin_herd": {"herd": "G2"},
            "breeding": self.breeding.id,
        }
        self.assertEqual(da.update_individual(form, self.admin.uuid)["status"], "success")
        new_birth = self._new_birth()
        self.assertEqual(new_birth.herd_id, self.g2.id)
        self._assert_undo_refused(new_birth.operation_id)

    def test_undo_of_a_birth_date_change_is_a_409(self):
        result = da.update_breeding({"id": self.breeding.id, "birth_date": "2026-02-03"}, self.admin.uuid)
        self.assertEqual(result["status"], "success", result)
        new_birth = self._new_birth()
        self.assertEqual(new_birth.herd_tracking_date, date(2026, 2, 3))
        self._assert_undo_refused(new_birth.operation_id)
