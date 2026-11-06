"""
Tests for the command log and undo of individual writes (utils/individual_commands.py, ADR-0017).

isort:skip_file
"""

import threading
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import herdbook
import utils.data_access as da
import utils.database as db
import utils.individual_commands as ic
from herdbook import APP
from utils.herd_tracking import (
    HerdTrackingConflict,
    HerdTrackingForbidden,
    HerdTrackingInvalid,
    HerdTrackingNotFound,
    undo_herd_tracking_operation,
    void_herd_tracking,
)
from utils.individual_commands import (
    FREE_TEXT_FIELDS,
    FREE_TEXT_RETENTION,
    UNDO_REASON,
    EditDescription,
    IndividualRefused,
    RecordAttestation,
    RecordDeath,
    RenameIndividual,
    TransferIndividual,
    Undo,
    execute,
    purge_command_free_text,
)

from tests.database_test import _USE_POSTGRES, IsolatedSchemaTest
from tests.ht_helpers import ht_row
from tests.test_individual_commands import FORBIDDEN, IndividualTest, error
from tests.test_legacy_api_contracts import FlaskTest


def undo(user, operation_id, reason=None):
    """Undo on the logged command's individual, as the v2 endpoint runs it."""
    entry = db.IndividualCommand.get(db.IndividualCommand.operation_id == operation_id)
    return execute(user, entry.individual_id, lambda ctx: [Undo(operation_id, reason)])


def snapshot(ind):
    """The rabbit's row, its litter and its active herd-tracking rows (updated_at aside)."""
    rows = db.DB_PROXY.execute_sql(
        "SELECT to_jsonb(i) - 'updated_at', to_jsonb(b) - 'updated_at' FROM individual i "
        "JOIN breeding b ON b.breeding_id = i.breeding_id WHERE i.individual_id = %s",
        (ind.id,),
    ).fetchall()
    tracking = db.HerdTracking.select().where(db.HerdTracking.individual == ind.id, db.ht_not_voided())
    return rows, sorted((r.id, r.kind, r.herd_id, str(r.herd_tracking_date)) for r in tracking)


class UndoTest(IndividualTest):
    def _log(self, ind=None):
        rows = db.IndividualCommand.select().where(db.IndividualCommand.individual == (ind or self.ind).id)
        return list(rows.order_by(db.IndividualCommand.id))

    def _set(self, ind=None, **fields):
        db.Individual.update(**fields).where(db.Individual.id == (ind or self.ind).id).execute()

    def _legacy(self, user, ind=None, **fields):
        """A legacy PATCH body through update_individual; v2 passes clear_nulls=True."""
        ind = ind or self.ind
        clear_nulls = fields.pop("clear_nulls", False)
        form = {"id": ind.id, "number": ind.number, "herd": "G1", **fields}
        return da.update_individual(form, user.uuid, clear_nulls=clear_nulls)


class TestCommandLog(UndoTest):
    def test_edit_logs_before_and_after(self):
        self._set(notes="gammal")
        self._run(self.owner, EditDescription({"notes": "ny"}))
        [row] = self._log()
        self.assertEqual(
            (row.command, row.before, row.after, row.actor_id, row.individual_id),
            ("EditDescription", {"notes": "gammal"}, {"notes": "ny"}, self.owner.id, self.ind.id),
        )
        self.assertIsNotNone(row.created_at)  # the model default, through insert_many
        self.assertIsNone(row.undoes)

    def test_echo_logs_nothing(self):
        self._set(name="Agnes")
        self._run(self.owner, EditDescription({"name": "Agnes"}))
        self.assertEqual(self._log(), [])

    def test_legacy_patch_shares_request_id(self):
        self._legacy(self.owner, notes="ny", death_date="2024-05-01")
        death, edit = self._log()
        self.assertEqual((death.command, edit.command), ("RecordDeath", "EditDescription"))
        self.assertEqual((death.before, death.after), ({"death_date": None}, {"death_date": "2024-05-01"}))
        self.assertEqual(death.request_id, edit.request_id)
        self.assertNotEqual(death.operation_id, edit.operation_id)

    def test_clear_fields_logs_the_stored_value(self):
        """Read before the clearing's own UPDATE (IR-51), so the stored value is the before."""
        self._set(death_date=date(2024, 5, 1))
        self._legacy(self.owner, death_date=None, clear_nulls=True)
        [row] = self._log()
        self.assertEqual(
            (row.command, row.before, row.after), ("ClearFields", {"death_date": "2024-05-01"}, {"death_date": None})
        )

    def test_attestation_shares_operation_id(self):
        self._legacy(self.owner, yearly_report_date="2024-05-01")
        [row] = self._log()
        tracking = db.HerdTracking.select().where(db.HerdTracking.individual == self.ind.id)
        newest = tracking.order_by(db.HerdTracking.id.desc()).first()
        self.assertEqual((row.command, row.before, row.after), ("RecordAttestation", None, None))
        self.assertEqual((newest.kind, newest.operation_id), ("ATTESTATION", row.operation_id))

    def test_refusal_logs_nothing(self):
        caretaker = self._caretaker()
        self._refusal(
            caretaker,
            EditDescription({"notes": "ny"}),
            TransferIndividual("G2", "2024-05-01"),
            error=HerdTrackingForbidden,
        )
        self.assertEqual(self._log(), [])


class TestUndo(UndoTest):
    def setUp(self):
        super().setUp()
        self.owner2 = da.register_user("owner2", "pass")
        self.owner2.add_role("owner", self.herds[0].id)

    def _op(self, user, *commands):
        self._run(user, *commands)
        return self._log()[-1].operation_id

    def _refused(self, error, user, op, reason=None):
        with self.assertRaises(error) as raised:
            undo(user, op, reason)
        return raised.exception

    def _age(self, op, days):
        db.IndividualCommand.update(created_at=datetime.now(timezone.utc) - timedelta(days=days)).where(
            db.IndividualCommand.operation_id == op
        ).execute()

    def _undo_rows(self, op):
        return list(db.IndividualCommand.select().where(db.IndividualCommand.undoes == op))

    def _active_attestations(self):
        rows = db.HerdTracking.select().where(
            db.HerdTracking.individual == self.ind.id, db.HerdTracking.kind == "ATTESTATION", db.ht_not_voided()
        )
        return [r.id for r in rows]

    def test_actor_undoes_within_window(self):
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        undo(self.owner, op)
        self.assertIsNone(self._stored().notes)
        [row] = self._undo_rows(op)
        self.assertEqual(
            (row.command, row.before, row.after, row.reason, row.actor_id),
            ("Undo", {"notes": "ny"}, {"notes": None}, UNDO_REASON, self.owner.id),
        )

    def test_undo_restores_exact_state(self):
        """The rabbit's row, its litter and its active herd-tracking rows are as before the command."""
        before = snapshot(self.ind)
        op = self._op(self.owner, RecordDeath({"death_date": "2024-05-01", "death_note": "sjuk", "butchered": True}))
        undo(self.owner, op)
        self.assertEqual(snapshot(self.ind), before)

    def test_unknown_operation_404(self):
        with self.assertRaises(HerdTrackingNotFound) as raised:
            execute(self.owner, self.ind.id, lambda ctx: [Undo(uuid.uuid4())])
        self.assertEqual(raised.exception.status, 404)

    def test_photo_change_not_undoable_400(self):
        op = self._op(self.owner, EditDescription({"has_photo": True, "notes": "ny"}))
        self.assertEqual(self._refused(HerdTrackingInvalid, self.owner, op).status, 400)
        self.assertTrue(self._stored().has_photo)

    def test_rename_not_undoable_400(self):
        op = self._op(self.owner, RenameIndividual("G1-2119"))
        self.assertEqual(self._log()[-1].command, "RenameIndividual")
        self.assertEqual(self._refused(HerdTrackingInvalid, self.owner, op).status, 400)

    def test_undo_of_undo_400(self):
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        undo(self.owner, op)
        [row] = self._undo_rows(op)
        self.assertEqual(self._refused(HerdTrackingInvalid, self.owner, row.operation_id).status, 400)
        self.assertIsNone(self._stored().notes)

    def test_already_undone_409(self):
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        undo(self.owner, op)
        refusal = self._refused(HerdTrackingConflict, self.owner, op)
        self.assertEqual((refusal.status, refusal.detail), (409, "Ändringen är redan ångrad."))

    def test_attestation_voided_elsewhere_counts_as_undone_409(self):
        op = self._op(self.owner, RecordAttestation("G1", "2024-05-01"))
        void_herd_tracking(db.HerdTracking.get(db.HerdTracking.operation_id == op).id, self.manager, "Fel datum")
        self.assertEqual(self._refused(HerdTrackingConflict, self.owner, op).status, 409)

    def test_other_owner_of_same_herd_403(self):
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        refusal = self._refused(HerdTrackingForbidden, self.owner2, op)
        self.assertEqual(refusal.detail, "Bara den som gjorde ändringen kan ångra den. Kontakta genbanksansvarig.")
        self.assertEqual(self._stored().notes, "ny")

    def test_actor_after_sale_403(self):
        """Entry is missing: the shared guard refuses before Undo runs."""
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        self._run(self.owner, TransferIndividual("G2", "2024-05-01"))
        self.assertEqual(self._refused(IndividualRefused, self.owner, op).envelope, FORBIDDEN)

    def test_caretaker_undoes_own_change(self):
        caretaker = self._caretaker()
        op = self._op(caretaker, EditDescription({"notes": "ny"}))
        undo(caretaker, op)
        self.assertIsNone(self._stored().notes)

    def test_actor_after_window_403(self):
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        self._age(op, 8)
        refusal = self._refused(HerdTrackingForbidden, self.owner, op)
        self.assertEqual(refusal.detail, "Ändringen gjordes för mer än 7 dagar sedan. Kontakta genbanksansvarig.")

    def test_manager_corrects_old_change_with_reason(self):
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        self._age(op, 400)
        undo(self.manager, op, " Fel kanin ")
        self.assertIsNone(self._stored().notes)
        [row] = self._undo_rows(op)
        self.assertEqual((row.actor_id, row.reason), (self.manager.id, "Fel kanin"))

    def test_manager_without_reason_400(self):
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        self.assertEqual(self._refused(HerdTrackingInvalid, self.manager, op).status, 400)
        self.assertEqual(self._stored().notes, "ny")

    def test_redacted_entry_409(self):
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        db.IndividualCommand.update(redacted_at=datetime.now(timezone.utc)).where(
            db.IndividualCommand.operation_id == op
        ).execute()
        refusal = self._refused(HerdTrackingConflict, self.owner, op)
        self.assertEqual(refusal.detail, "Uppgifterna är rensade och kan inte återställas.")

    def test_later_change_409_lists_fields(self):
        op = self._op(self.owner, EditDescription({"name": "Agnes", "notes": "ny"}))
        self._run(self.manager, EditDescription({"name": "Ines"}))
        refusal = self._refused(HerdTrackingConflict, self.owner, op)
        self.assertEqual((refusal.detail, refusal.rows), ("Någon har ändrat samma uppgifter efteråt.", ["name"]))
        self.assertEqual((self._stored().name, self._stored().notes), ("Ines", "ny"))

    def test_y_z_y_is_allowed(self):
        """Values are compared, not versions: Y, Z and back to Y undoes."""
        op = self._op(self.owner, EditDescription({"name": "Agnes"}))
        self._run(self.manager, EditDescription({"name": "Ines"}))
        self._run(self.manager, EditDescription({"name": "Agnes"}))
        undo(self.owner, op)
        self.assertIsNone(self._stored().name)

    def test_undo_one_of_two_commands_from_one_patch(self):
        self._legacy(self.owner, notes="ny", death_date="2024-05-01")
        death, _edit = self._log()
        undo(self.owner, death.operation_id)
        self.assertEqual((self._stored().death_date, self._stored().notes), (None, "ny"))

    def test_voided_individual_404(self):
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        self._set(voided=True)  # as unpromote does
        self.assertEqual(self._refused(IndividualRefused, self.owner, op).envelope, error("Individual not found"))
        self.assertEqual(self._stored().notes, "ny")

    def test_voided_individual_404_before_already_undone(self):
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        undo(self.owner, op)
        self._set(voided=True)
        self.assertEqual(self._refused(IndividualRefused, self.owner, op).envelope, error("Individual not found"))

    def test_attestation_undo_voids_the_row(self):
        before = snapshot(self.ind)
        op = self._op(self.owner, RecordAttestation("G1", "2024-05-01"))
        undo(self.owner, op)
        self.assertEqual(snapshot(self.ind), before)
        [row] = self._undo_rows(op)
        tracking = db.HerdTracking.get(db.HerdTracking.operation_id == op)
        self.assertEqual(
            (tracking.voided_reason, tracking.voided_operation_id, row.before, row.after),
            (UNDO_REASON, row.operation_id, None, None),
        )

    def test_attestation_undo_leaves_another_rabbits_row_with_the_same_operation_id(self):
        """herd-tracking takes a client's operation id per individual: one UUID can name another rabbit's row."""
        op = self._op(self.owner, RecordAttestation("G1", "2024-05-01"))
        other = self.individuals[0]
        row = ht_row(
            "ATTESTATION",
            herd=self.herds[0],
            signature=self.manager,
            individual=other,
            herd_tracking_date=datetime(2024, 5, 2),
            operation_id=op,
        )
        undo(self.owner, op)
        self.assertEqual(self._active_attestations(), [])
        self.assertIsNone(db.HerdTracking.get_by_id(row.id).voided_at)

    def test_attestation_not_latest_refused_by_void_rules(self):
        first = self._op(self.owner, RecordAttestation("G1", "2024-05-01"))
        self._run(self.owner, RecordAttestation("G1", "2024-06-01"))
        refusal = self._refused(HerdTrackingForbidden, self.owner, first)
        self.assertEqual(refusal.detail, "Bara den senaste händelsen kan ångras. Kontakta genbanksansvarig.")
        self.assertEqual(len(self._active_attestations()), 2)

    def test_attestation_restored_then_undone_again(self):
        """Undo, the restoring undo through herd-tracking's API, and undo again: two Undo rows name the command."""
        op = self._op(self.owner, RecordAttestation("G1", "2024-05-01"))
        undo(self.owner, op)
        [first] = self._undo_rows(op)
        undo_herd_tracking_operation(first.operation_id, self.manager, "Rapporten var rätt")
        self.assertEqual(len(self._active_attestations()), 1)
        undo(self.owner, op)
        self.assertEqual((len(self._undo_rows(op)), self._active_attestations()), (2, []))


class TestUndoApi(UndoTest, FlaskTest):
    def setUp(self):
        super().setUp()
        self.owner2 = da.register_user("owner2", "pass")
        self.owner2.add_role("owner", self.herds[0].id)

    def _client(self, user):
        client = APP.test_client(use_cookies=True)
        self.login(client, user)
        return client

    def _op(self, user, *commands, ind=None):
        self._run(user, *commands, ind=ind)
        return self._log(ind)[-1].operation_id

    def _list(self, user, ind=None):
        return self._client(user).get(f"/api/v2/individual/{(ind or self.ind).number}/commands")

    def _undo(self, user, op, **body):
        return self._client(user).post(f"/api/v2/individual-commands/{op}/undo", json=body)

    def test_list_shows_own_recent_commands_only(self):
        mine = self._op(self.owner, EditDescription({"notes": "ny"}))
        old = self._op(self.owner, EditDescription({"name": "Agnes"}))
        db.IndividualCommand.update(created_at=datetime.now(timezone.utc) - timedelta(days=8)).where(
            db.IndividualCommand.operation_id == old
        ).execute()
        self._op(self.manager, EditDescription({"notes": "managerns"}))
        undone = self._op(self.owner, EditDescription({"sex": "male"}))
        undo(self.owner, undone)
        response = self._list(self.owner)
        self.assertEqual(response.status_code, 200)
        commands = response.get_json()["commands"]
        self.assertEqual([c["operation_id"] for c in commands], [str(undone), str(mine)])  # newest first, no Undo
        self.assertEqual([c["undone"] for c in commands], [True, False])
        self.assertEqual(
            {key: commands[1][key] for key in ("command", "before", "after")},
            {"command": "EditDescription", "before": {"notes": None}, "after": {"notes": "ny"}},
        )
        self.assertIn("created_at", commands[1])

    def test_list_hides_other_genebank_404(self):
        mellerud = self.individuals[2]  # M3, which the G1 owner may not read
        self._op(self.admin, EditDescription({"notes": "ny"}), ind=mellerud)
        response = self._list(self.owner, mellerud)
        self.assertEqual((response.status_code, response.content_type), (404, "application/problem+json"))

    def test_undo_200_and_row_restored(self):
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        response = self._undo(self.owner, op)
        self.assertEqual((response.status_code, response.get_json()), (200, {"operation_id": str(op)}))
        self.assertIsNone(self._stored().notes)

    def test_undo_errors_are_problem_json(self):
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        photo = self._op(self.owner, EditDescription({"has_photo": True}))
        mellerud = self._op(self.admin, EditDescription({"notes": "ny"}), ind=self.individuals[2])
        cases = (
            ("photo", self.owner, photo, 400),
            ("other owner", self.owner2, op, 403),
            ("unknown", self.owner, uuid.uuid4(), 404),
            ("unreadable", self.owner, mellerud, 404),
        )
        for name, user, operation_id, status in cases:
            with self.subTest(case=name):
                response = self._undo(user, operation_id)
                self.assertEqual((response.status_code, response.content_type), (status, "application/problem+json"))
                self.assertEqual(response.get_json()["status"], status)
        self.assertEqual(self._undo(self.owner, op).status_code, 200)
        conflict = self._undo(self.owner, op)
        self.assertEqual((conflict.status_code, conflict.get_json()["detail"]), (409, "Ändringen är redan ångrad."))
        self.assertEqual(conflict.content_type, "application/problem+json")
        self._set(voided=True)
        self.assertEqual(self._undo(self.owner, photo).status_code, 404)

    def test_correction_takes_the_reason_from_the_body(self):
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        self.assertEqual(self._undo(self.manager, op).status_code, 400)
        self.assertEqual(self._undo(self.manager, op, reason="Fel kanin").status_code, 200)
        self.assertEqual(db.IndividualCommand.get(db.IndividualCommand.undoes == op).reason, "Fel kanin")

    def test_viewer_cannot_undo(self):
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        response = self._undo(self.viewer, op)
        self.assertEqual((response.status_code, response.get_json()["detail"]), (403, "Forbidden"))
        self.assertEqual(self._stored().notes, "ny")


class TestFreeTextPurge(UndoTest):
    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc)

    def _op(self, user, *commands):
        self._run(user, *commands)
        return self._log()[-1].operation_id

    def _age(self, op, days):
        db.IndividualCommand.update(created_at=self.now - timedelta(days=days)).where(
            db.IndividualCommand.operation_id == op
        ).execute()

    def _entry(self, op):
        return db.IndividualCommand.get(db.IndividualCommand.operation_id == op)

    def test_old_rows_lose_free_text_only(self):
        """The name and the dates stay: only the free text goes, and the row is marked."""
        for i, key in enumerate(FREE_TEXT_FIELDS, start=1):
            with self.subTest(field=key):
                day, name = f"2024-05-{i:02d}", f"Namn {i}"
                if key == "death_note":
                    command = RecordDeath({"death_date": day, "death_note": "fritext"})
                    kept = {"death_date": day}
                else:
                    command = EditDescription({"name": name, "castration_date": day, key: "fritext"})
                    kept = {"name": name, "castration_date": day}
                op = self._op(self.owner, command)
                self._age(op, 425)
                self.assertEqual(purge_command_free_text(self.now), 1)
                entry = self._entry(op)
                self.assertEqual(entry.after, kept)
                self.assertNotIn(key, entry.before)
                self.assertEqual(entry.redacted_at, self.now)

    def test_recent_rows_untouched(self):
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        self._age(op, FREE_TEXT_RETENTION.days - 1)
        self.assertEqual(purge_command_free_text(self.now), 0)
        entry = self._entry(op)
        self.assertEqual((entry.after, entry.redacted_at), ({"notes": "ny"}, None))

    def test_old_change_without_free_text_stays_correctable(self):
        op = self._op(self.owner, RecordDeath({"death_date": "2024-05-01"}))
        self._age(op, 425)
        purge_command_free_text(self.now)
        self.assertIsNone(self._entry(op).redacted_at)
        undo(self.manager, op, "Fel kanin")
        self.assertIsNone(self._stored().death_date)

    def test_reason_is_purged_without_redacting(self):
        """A correction's reason is free text too, but nothing an undo would restore."""
        op = self._op(self.owner, RecordDeath({"death_date": "2024-05-01"}))
        undo(self.manager, op, "Fel kanin")
        correction = db.IndividualCommand.get(db.IndividualCommand.undoes == op)
        self._age(correction.operation_id, 425)
        self.assertEqual(purge_command_free_text(self.now), 1)
        purged = self._entry(correction.operation_id)
        self.assertEqual((purged.reason, purged.redacted_at), (None, None))

    def test_purge_is_idempotent(self):
        self._age(self._op(self.owner, EditDescription({"notes": "ny"})), 425)
        self.assertEqual(purge_command_free_text(self.now), 1)
        self.assertEqual(purge_command_free_text(self.now), 0)

    @unittest.skipUnless(_USE_POSTGRES, "row locks need PostgreSQL")
    def test_purge_waits_for_undo_holding_the_entry(self):
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        self._age(op, 425)
        locked, release, order = threading.Event(), threading.Event(), []

        def hold():
            try:
                with db.DB_PROXY.atomic():
                    db.IndividualCommand.select().where(db.IndividualCommand.operation_id == op).for_update().get()
                    locked.set()
                    release.wait(timeout=10)
                    order.append("commit")
            finally:
                db.DB_PROXY.close()

        def purge():
            try:
                locked.wait(timeout=10)
                order.append(purge_command_free_text(self.now))
            finally:
                db.DB_PROXY.close()

        threads = [threading.Thread(target=hold), threading.Thread(target=purge)]
        for thread in threads:
            thread.start()
        locked.wait(timeout=10)
        threads[1].join(timeout=1)
        self.assertTrue(threads[1].is_alive(), "the purge must wait for the row lock")
        self.assertIsNone(self._entry(op).redacted_at)
        release.set()
        for thread in threads:
            thread.join(timeout=20)
        self.assertEqual(order, ["commit", 1])
        self.assertIsNotNone(self._entry(op).redacted_at)

    @unittest.skipUnless(_USE_POSTGRES, "row locks need PostgreSQL")
    def test_user_erasure_waits_for_an_undo_instead_of_deadlocking(self):
        """
        purge_user_audit_pii locks audit_log exclusively (DROP RULE). If it did that before purging the command
        rows, an Undo holding the actor's entry would block it, and then block on audit_log through its trigger.
        """
        op = self._op(self.owner, EditDescription({"notes": "ny"}))
        locked, release, order, errors = threading.Event(), threading.Event(), [], []
        real_undone = ic._undone

        def undone_after_a_pause(entry):  # called by Undo after it holds the entry FOR UPDATE
            locked.set()
            release.wait(timeout=10)
            return real_undone(entry)

        def run(name, call):
            try:
                call()
                order.append(name)
            except Exception as exc:  # noqa: BLE001 — a deadlock surfaces here
                errors.append(repr(exc))
            finally:
                db.DB_PROXY.close()

        def erase():
            locked.wait(timeout=10)
            da.purge_user_audit_pii(self.owner.id, self.owner.username, self.owner.email)

        with mock.patch.object(ic, "_undone", side_effect=undone_after_a_pause):
            threads = [
                threading.Thread(target=run, args=("undo", lambda: undo(self.owner, op))),
                threading.Thread(target=run, args=("erase", erase)),
            ]
            for thread in threads:
                thread.start()
            locked.wait(timeout=10)
            threads[1].join(timeout=1)
            self.assertTrue(threads[1].is_alive(), "the erasure must wait for the entry's row lock")
            release.set()
            for thread in threads:
                thread.join(timeout=30)
        self.assertEqual((errors, order), ([], ["undo", "erase"]))

    def test_purge_job_closes_connection(self):
        with (
            mock.patch.object(herdbook, "purge_command_free_text", return_value=2) as purge,
            mock.patch.object(herdbook.genetics.ps, "_close_db_connection") as close,
        ):
            herdbook._purge_command_free_text()
            self.assertIsNotNone(purge.call_args.args[0].tzinfo)
            purge.side_effect = RuntimeError("database gone")
            with self.assertRaises(RuntimeError):
                herdbook._purge_command_free_text()
        self.assertEqual(close.call_count, 2)


@unittest.skipUnless(_USE_POSTGRES, "the schema snapshot reads PostgreSQL catalogs")
class TestCommandLogMigration(IsolatedSchemaTest):
    """migrate_34_to_35 in a throwaway database, since it drops the table."""

    def _sql(self, query):
        return set(db.DATABASE.execute_sql(query).fetchall())

    def _snapshot(self):
        return (
            self._sql(
                "SELECT column_name, data_type, is_nullable, coalesce(column_default, '') "
                "FROM information_schema.columns WHERE table_name = 'individual_command'"
            ),
            self._sql("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'individual_command'"),
            self._sql(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'individual_command'::regclass"
            ),
        )

    def _to_v34(self):
        db.DATABASE.execute_sql('DROP TABLE IF EXISTS "individual_command"')
        db.SchemaHistory.delete().where(db.SchemaHistory.version >= 35).execute()

    def _version(self):
        return db.SchemaHistory.select(db.fn.MAX(db.SchemaHistory.version)).scalar()

    def test_migration_creates_table(self):
        self._to_v34()
        db.migrate_34_to_35()
        self.assertEqual(self._version(), 35)
        indexes = {name for name, _ in self._snapshot()[1]}
        self.assertLessEqual(
            {
                "individualcommand_operation_id",
                "individualcommand_request_id",
                "individualcommand_undoes",
                "individualcommand_individual_id_created_at",
            },
            indexes,
        )
        migrated = self._snapshot()
        db.SchemaHistory.delete().where(db.SchemaHistory.version >= 35).execute()
        db.migrate_34_to_35()  # a rerun on the table is a no-op
        self.assertEqual((self._snapshot(), self._version()), (migrated, 35))

    def test_fresh_bootstrap_equals_migrated(self):
        bootstrapped = self._snapshot()  # the class database is bootstrapped through init()
        self.assertTrue(bootstrapped[0])
        self._to_v34()
        db.migrate_34_to_35()
        self.assertEqual(self._snapshot(), bootstrapped)


if __name__ == "__main__":
    unittest.main()
