"""
The yearly report's right to void and undo its own writes (Role.RAPPORT, report_ops), and the ordinary undo
paths that send the report's rows to Ändra (REPORT_ROW). ADR-0017, addendum 2026-11-14.

isort:skip_file
"""

import unittest
import uuid
from datetime import date, datetime, timedelta, timezone

import utils.database as db
from herdbook import APP
from utils.herd_tracking import (
    GENEBANK_CHANGE_ADMIN_ONLY,
    REPORT_ROW,
    HerdTrackingForbidden,
    herd_tracking_history,
    record_herd_tracking,
    void_herd_tracking,
)
from utils.individual_commands import (
    REPORT_UNDO_REASON,
    UNDO_REASON,
    RecordAttestation,
    RecordDeath,
    TransferIndividual,
    Undo,
    execute,
)
from utils.individual_policy import COMMAND_FIELDS, STATES, Role, State, allowed

from tests.ht_helpers import age_row, count_queries, ht_row, make_individual
from tests.test_individual_commands import IndividualTest
from tests.test_legacy_api_contracts import FlaskTest

REPORT = {"herd": "G1", "year": 2025}
UNDO_DEATH = {"death_date": None, "death_note": None, "butchered": False, "herd": "G1"}  # the page's "Ångra död"


class Vouch:
    """A grant that vouches for the report's right; utils.arsrapport.ReportGrant checks it for real."""

    def roles(self, user, individual):
        return frozenset({Role.RAPPORT})

    def record(self, ctx):
        return None


class ReportRightTest(IndividualTest):
    def _op(self, user, *commands, ind=None):
        self._run(user, *commands, ind=ind)
        rows = db.IndividualCommand.select().where(db.IndividualCommand.individual == (ind or self.ind).id)
        return rows.order_by(db.IndividualCommand.id.desc()).first().operation_id

    def _row(self, op):
        return db.HerdTracking.get(db.HerdTracking.operation_id == op)

    def _age_command(self, op, days):
        db.IndividualCommand.update(created_at=datetime.now(timezone.utc) - timedelta(days=days)).where(
            db.IndividualCommand.operation_id == op
        ).execute()

    def _report(self, ops=(), year=2025):
        """A submitted report on G1 whose one submission wrote `ops`, built by hand (the service is Task 4's)."""
        round_, _ = db.YearlyReportRound.get_or_create(report_year=year, defaults={"created_by": self.admin})
        report = db.YearlyHerdReport.create(
            herd=self.herds[0], round=round_, report_date=date(year + 1, 1, 5), data="{}", status="submitted"
        )
        self._submission(report, ops)
        return report

    def _submission(self, report, ops):
        db.YearlyReportSubmission.create(
            report=report,
            submission_key=uuid.uuid4(),
            source="login",
            user=self.owner,
            operation_ids=[str(op) for op in ops],
            data={},
            request_hash="x",
        )

    def _rabbit(self, number):
        rabbit = make_individual(self.herds[0], number, date(2024, 1, 1))
        ht_row("BIRTH", individual=rabbit, herd=self.herds[0], herd_tracking_date=date(2024, 1, 1))
        return rabbit

    def _void(self, row, user, ops=None):
        return void_herd_tracking(row.id, user, "Årsrapporten ändrades", report_ops=ops)

    def _undo(self, user, op, ops):
        return execute(user, self.ind.id, lambda ctx: [Undo(op, report_ops=ops)], grant=Vouch())


class TestReportVoid(ReportRightTest):
    def test_attestation_carries_report_id(self):
        report = self._report()
        op = self._op(self.owner, RecordAttestation("G1", "2025-12-31", report=report.id))
        self.assertEqual(self._row(op).yearly_herd_report_id, report.id)

    def test_report_right_voids_another_users_old_attestation(self):
        op = self._op(self.owner, RecordAttestation("G1", "2025-12-31"))
        row = self._row(op)
        age_row(row, 10)
        caretaker = self._caretaker()
        with self.assertRaises(HerdTrackingForbidden):
            self._void(row, caretaker)
        self._void(row, caretaker, frozenset({str(op)}))
        self.assertEqual(db.HerdTracking.get_by_id(row.id).voided_by_user_id, caretaker.id)

    def test_report_right_refuses_a_row_outside_the_report(self):
        row = self._row(self._op(self.owner, RecordAttestation("G1", "2025-12-31")))
        with self.assertRaisesRegex(HerdTrackingForbidden, "hör inte till årsrapporten"):
            self._void(row, self.owner, frozenset({str(uuid.uuid4())}))

    def test_report_right_refuses_when_not_latest(self):
        op = self._op(self.owner, RecordAttestation("G1", "2025-12-31"))
        record_herd_tracking(self.ind, self.herds[1], date(2026, 1, 10), "TRANSFER", self.manager)
        with self.assertRaisesRegex(HerdTrackingForbidden, "efter årsrapporten. Genbanksansvarig kan rätta"):
            self._void(self._row(op), self.owner, frozenset({str(op)}))

    def test_report_right_refuses_birth_and_genebank_change(self):
        birth = db.HerdTracking.get(db.HerdTracking.individual == self.ind.id, db.HerdTracking.kind == "BIRTH")
        with self.assertRaisesRegex(HerdTrackingForbidden, "En födelserad kan inte ångras"):
            self._void(birth, self.owner, frozenset({str(birth.operation_id)}))
        moved = record_herd_tracking(self.ind, self.herds[2], date(2025, 12, 1), "TRANSFER", self.admin)
        with self.assertRaises(HerdTrackingForbidden) as raised:
            self._void(moved, self.owner, frozenset({str(moved.operation_id)}))
        self.assertEqual(raised.exception.detail, GENEBANK_CHANGE_ADMIN_ONLY)

    def test_report_right_refuses_a_sale_with_a_later_litter(self):
        sale = record_herd_tracking(self.ind, self.herds[1], date(2025, 11, 1), "TRANSFER", self.owner)
        db.Breeding.create(mother=self.ind, breeding_herd_id=self.herds[1], breed_date=date(2025, 12, 1))
        expected = "Kaninen har en parning eller kull registrerad efter försäljningen. Genbanksansvarig kan rätta."
        with self.assertRaises(HerdTrackingForbidden) as raised:
            self._void(sale, self.owner, frozenset({str(sale.operation_id)}))
        self.assertEqual(raised.exception.detail, expected)

    def test_report_right_refuses_a_transfer_flow_sale(self):
        sale = record_herd_tracking(self.ind, self.herds[1], date(2025, 11, 1), "TRANSFER", self.owner, transfer_id=7)
        with self.assertRaisesRegex(HerdTrackingForbidden, "överlåtelseflödet"):
            self._void(sale, self.owner, frozenset({str(sale.operation_id)}))

    def test_report_undo_of_an_attestation_voids_it_by_the_report_rules(self):
        op = self._op(self.owner, RecordAttestation("G1", "2025-12-31"))
        self._age_command(op, 10)
        age_row(self._row(op), 10)
        caretaker = self._caretaker()
        self._undo(caretaker, op, frozenset({str(op)}))
        self.assertEqual(self._row(op).voided_by_user_id, caretaker.id)

    def test_rapport_outside_report_ops_takes_the_ordinary_path(self):
        """The actor's own attestation within 7 days: herd-tracking's ordinary rules, not the report's."""
        op = self._op(self.owner, RecordAttestation("G1", "2025-12-31"))
        self._undo(self.owner, op, frozenset())
        self.assertIsNotNone(self._row(op).voided_at)
        self.assertEqual(db.IndividualCommand.get(db.IndividualCommand.undoes == op).reason, UNDO_REASON)


class TestReportUndo(ReportRightTest):
    def setUp(self):
        super().setUp()
        self.op = self._op(self.owner, RecordDeath({"death_date": "2025-11-01"}))
        self._age_command(self.op, 10)

    def test_undo_with_rapport_after_the_window(self):
        self._undo(self._caretaker(), self.op, frozenset({str(self.op)}))
        self.assertIsNone(self._stored().death_date)
        last = db.IndividualCommand.select().order_by(db.IndividualCommand.id.desc()).first()
        self.assertEqual((last.command, last.undoes, last.reason), ("Undo", self.op, REPORT_UNDO_REASON))

    def test_undo_outside_report_ops_is_refused(self):
        with self.assertRaises(HerdTrackingForbidden):
            self._undo(self._caretaker(), self.op, frozenset())
        self.assertIsNotNone(self._stored().death_date)

    def test_rapport_does_not_lend_the_command_right(self):
        with self.assertRaises(HerdTrackingForbidden):
            self._undo(self.viewer, self.op, frozenset({str(self.op)}))
        self.assertIsNotNone(self._stored().death_date)

    def test_report_ops_without_the_grant_are_refused(self):
        ops = frozenset({str(self.op)})
        with self.assertRaises(HerdTrackingForbidden):
            execute(self.owner, self.ind.id, lambda ctx: [Undo(self.op, report_ops=ops)])
        self.assertIsNotNone(self._stored().death_date)


class TestReportRole(unittest.TestCase):
    def test_rapport_needs_a_role_with_entry(self):
        for command in ("Entry", *COMMAND_FIELDS):
            for state in STATES:
                with self.subTest(command=command, state=str(state)):
                    self.assertIs(allowed(command, frozenset({Role.RAPPORT}), state), False)
        for role in (Role.OWNER, Role.CARETAKER, Role.HANDLAGGARE):
            with self.subTest(role=role.value):
                self.assertIs(allowed("Undo", frozenset({Role.RAPPORT, role}), State(False, False)), True)
                self.assertIs(allowed("Undo", frozenset({role}), State(False, False)), False)


class TestRabbitPage(ReportRightTest, FlaskTest):
    """Codex 1: the rabbit page's void, Undo and "Ångra död" send the report's rows to Ändra."""

    def setUp(self):
        super().setUp()
        self.kept, self.sold, self.dead = (self._rabbit(f"G1-240{n}") for n in (1, 2, 3))
        attest = self._op(self.owner, RecordAttestation("G1", "2025-12-31"), ind=self.kept)
        sale = self._op(self.owner, TransferIndividual("G2", "2025-12-15"), ind=self.sold)
        self.death = self._op(self.owner, RecordDeath({"death_date": "2025-12-20"}), ind=self.dead)
        self.report = self._report([attest, sale, self.death])
        self.attestation, self.sale = self._row(attest), self._row(sale)

    def _client(self, user):
        client = APP.test_client(use_cookies=True)
        self.login(client, user)
        return client

    def _history(self, client, rabbit):
        return client.get(f"/api/v2/individual/{rabbit.number}/herd-tracking").get_json()

    def _history_row(self, client, rabbit, row_id):
        return next(r for r in self._history(client, rabbit)["rows"] if r["id"] == row_id)

    def test_rabbit_page_points_report_rows_to_andra(self):
        owner = self._client(self.owner)
        refused = {
            "void": owner.post(f"/api/v2/herd-tracking/{self.attestation.id}/void", json={"reason": "Fel"}),
            "undo sale": owner.post(f"/api/v2/herd-tracking/{self.sale.id}/void", json={"reason": "Fel"}),
            "undo": owner.post(f"/api/v2/individual-commands/{self.death}/undo", json={}),
            "undo death": owner.patch(f"/api/individual/{self.dead.number}", json=UNDO_DEATH),
        }
        for name, response in refused.items():
            with self.subTest(path=name):
                self.assertEqual((response.status_code, response.get_json()["detail"]), (403, REPORT_ROW))
        self.assertIsNotNone(self._stored(self.dead).death_date)

        for rabbit, row in ((self.kept, self.attestation), (self.sold, self.sale)):
            shown = self._history_row(owner, rabbit, row.id)
            self.assertEqual((shown["can_void"], shown["report"]), (False, REPORT))
        birth = self._history(owner, self.kept)["rows"][-1]
        self.assertEqual((birth["kind"], birth["report"]), ("BIRTH", None))
        self.assertEqual(self._history(owner, self.dead)["death_report"], REPORT)
        self.assertIsNone(self._history(owner, self.kept)["death_report"])

        manager = self._client(self.manager)
        self.assertTrue(self._history_row(manager, self.kept, self.attestation.id)["can_void"])
        void = manager.post(f"/api/v2/herd-tracking/{self.attestation.id}/void", json={"reason": "Fel kanin"})
        self.assertEqual(void.status_code, 200, void.get_data(as_text=True))

        legacy = self._row(self._op(self.owner, RecordAttestation("G1", "2026-01-05"), ind=self.kept))
        self.assertTrue(self._history_row(owner, self.kept, legacy.id)["can_void"])
        self.assertEqual(owner.post(f"/api/v2/herd-tracking/{legacy.id}/void", json={"reason": "Fel"}).status_code, 200)

        db.YearlyHerdReport.update(
            status="voided", voided_at=datetime.now(timezone.utc), voided_by_user=self.manager
        ).where(db.YearlyHerdReport.id == self.report.id).execute()
        self.assertIsNone(self._history_row(owner, self.sold, self.sale.id)["report"])
        self.assertIsNone(self._history(owner, self.dead)["death_report"])

    def test_the_owner_undoes_death_once_the_report_is_gone(self):
        db.YearlyHerdReport.update(
            status="voided", voided_at=datetime.now(timezone.utc), voided_by_user=self.manager
        ).where(db.YearlyHerdReport.id == self.report.id).execute()
        response = self._client(self.owner).patch(f"/api/individual/{self.dead.number}", json=UNDO_DEATH)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertIsNone(self._stored(self.dead).death_date)

    def test_the_manager_undoes_the_reports_death_with_a_reason(self):
        response = self._client(self.manager).post(
            f"/api/v2/individual-commands/{self.death}/undo", json={"reason": "Fel kanin"}
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertIsNone(self._stored(self.dead).death_date)

    def test_the_manager_clears_the_reports_death(self):
        response = self._client(self.manager).patch(f"/api/individual/{self.dead.number}", json=UNDO_DEATH)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertIsNone(self._stored(self.dead).death_date)

    def test_the_owner_cannot_move_the_reports_death_out_of_the_way(self):
        """Review Important 1: a changed death would be the latest RecordDeath and free "Ångra död" in a second
        request, so the first is refused. An echo changes nothing and still passes."""
        owner = self._client(self.owner)
        for change in ({"death_note": "Sjuk"}, {"death_date": "2025-12-21"}, {"butchered": True}):
            with self.subTest(change=str(change)):
                response = owner.patch(f"/api/individual/{self.dead.number}", json={**change, "herd": "G1"})
                self.assertEqual((response.status_code, response.get_json()["detail"]), (403, REPORT_ROW))
        stored = self._stored(self.dead)
        self.assertEqual((stored.death_date, stored.death_note, stored.butchered), (date(2025, 12, 20), None, False))
        echo = owner.patch(f"/api/individual/{self.dead.number}", json={"death_date": "2025-12-20", "herd": "G1"})
        self.assertEqual(echo.status_code, 200, echo.get_data(as_text=True))
        self.assertEqual(owner.patch(f"/api/individual/{self.dead.number}", json=UNDO_DEATH).status_code, 403)

    def test_the_manager_changes_the_reports_death(self):
        response = self._client(self.manager).patch(
            f"/api/individual/{self.dead.number}", json={"death_date": "2025-12-21", "herd": "G1"}
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(self._stored(self.dead).death_date, date(2025, 12, 21))

    def test_the_reports_own_change_of_its_death_still_writes(self):
        """Ändra writes through the report's right (ReportGrant gives RAPPORT); without it the owner is refused."""
        change = RecordDeath({"death_date": "2025-12-22"})
        self._refusal(self.owner, change, ind=self.dead, error=HerdTrackingForbidden)
        self._run(self.owner, change, ind=self.dead, grant=Vouch())
        self.assertEqual(self._stored(self.dead).death_date, date(2025, 12, 22))

    def test_history_query_count_does_not_grow_with_report_rows(self):
        """Pre-flight ruling: one report_owners call per history, not one per row."""

        def measure():
            with count_queries() as counter:
                herd_tracking_history(db.Individual.get_by_id(self.kept.id), db.User.get_by_id(self.owner.id))
            return counter["n"]

        few = measure()
        later = [
            ht_row("ATTESTATION", individual=self.kept, herd=self.herds[0], herd_tracking_date=date(2026, 1, day))
            for day in range(1, 6)
        ]
        self._submission(self.report, [row.operation_id for row in later])
        self.assertEqual(measure(), few)
