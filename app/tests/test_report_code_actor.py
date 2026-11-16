#!/usr/bin/env python3
"""
Tests for the report link as the actor in the command layer (step 3, Task 3, ADR-0017 addendum): the three write
sites, the policy and ReportGrant(code=...). Synthetic herds and rabbits only.

isort:skip_file
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.report_code as report_code
import utils.settings as settings
from utils.arsrapport import ReportGrant
from utils.herd_tracking import HerdTrackingForbidden
from utils.individual_commands import (
    AssignPaperCertificate,
    ClearFields,
    EditDescription,
    IndividualRefused,
    IssueDigitalCertificate,
    MoveToLitter,
    RecordAttestation,
    RecordDeath,
    RenameIndividual,
    SetMeasurements,
    TransferIndividual,
    Undo,
    actor_role,
    execute,
    purge_command_free_text,
    roles_for,
    state_for,
)
from utils.individual_policy import COMMAND_FIELDS, Role, allowed
from utils.report_code import CodeActor

from tests.arsrapport_fixtures import ArsrapportTest
from tests.ht_helpers import ht_row

LAST = "2025-12-31"


class CodeActorTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.multiple(settings.mail, link_secret="test-link-secret", link_hosts=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.at(date(2026, 1, 15))
        self.round_ = self.round(2025)
        self.herd = db.Herd.create(genebank=self.gotland, herd="G9001", is_active=True)
        self.other = db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True)
        self.member = self.main_member(self.herd, "g9001@example.invalid")
        self.rabbits_ = self.rabbits(self.herd, 3)
        self.foreign = self.rabbits(self.other, 1)[0]
        self.code = report_code.issue_code(self.herd, self.round_, self.member, now=arsrapport.now())
        self.actor = CodeActor(self.code)

    def run_as_code(self, rabbit, *commands, code=None, **grant):
        code = code or self.code
        return execute(CodeActor(code), rabbit.id, lambda ctx: list(commands), grant=ReportGrant(code=code, **grant))

    def attest(self, rabbit=None):
        self.run_as_code(rabbit or self.rabbits_[0], RecordAttestation("G9001", LAST))

    def test_code_attestation_row_has_code_actor(self):
        rabbit = self.rabbits_[0]
        self.attest(rabbit)
        row = db.HerdTracking.get(db.HerdTracking.individual == rabbit.id, db.HerdTracking.kind == "ATTESTATION")
        self.assertIsNone(row.signature_id)
        self.assertEqual(row.access_code_id, self.code.id)
        command = db.IndividualCommand.get(db.IndividualCommand.individual == rabbit.id)
        self.assertEqual(
            (command.command, command.actor_id, command.access_code_id), ("RecordAttestation", None, self.code.id)
        )
        self.assertEqual(str(command.operation_id), str(row.operation_id))

    def test_code_writes_death_and_measurements(self):
        rabbit = self.rabbits_[1]
        self.run_as_code(
            rabbit,
            RecordDeath({"death_date": "2025-06-01", "butchered": False, "death_note": None}),
            SetMeasurements(weights=[{"weight": 2500, "date": LAST}]),
        )
        self.assertEqual(db.Individual.get_by_id(rabbit.id).death_date, date(2025, 6, 1))
        self.assertEqual(db.Weight.get(db.Weight.individual == rabbit.id).weight, 2500)
        self.assertEqual(
            {row.command: row.access_code_id for row in db.IndividualCommand.select()}, {"RecordDeath": self.code.id}
        )

    def test_code_void_writes_voided_by_access_code(self):
        rabbit = self.rabbits_[0]
        self.attest(rabbit)
        op = db.IndividualCommand.get(db.IndividualCommand.individual == rabbit.id).operation_id
        self.run_as_code(rabbit, Undo(op, report_ops=frozenset({str(op)})), report_ops=frozenset({str(op)}))
        row = db.HerdTracking.get(db.HerdTracking.individual == rabbit.id, db.HerdTracking.kind == "ATTESTATION")
        self.assertEqual((row.voided_by_user_id, row.voided_by_access_code_id), (None, self.code.id))
        undo = db.IndividualCommand.get(db.IndividualCommand.command == "Undo")
        self.assertEqual((undo.actor_id, undo.access_code_id), (None, self.code.id))

    def test_code_cannot_issue_certificate_or_rename(self):
        rabbit = self.rabbits_[0]
        for command in (
            IssueDigitalCertificate(),
            RenameIndividual("G9001-9999"),
            EditDescription({"name": "Nytt namn"}),
            MoveToLitter(1),
            TransferIndividual("G9002", LAST),
            AssignPaperCertificate("123"),
            ClearFields(frozenset({"death_date"})),
        ):
            with (
                self.subTest(command=type(command).__name__),
                self.assertRaises((IndividualRefused, HerdTrackingForbidden)),
            ):
                self.run_as_code(rabbit, command)
        self.assertEqual(db.IndividualCommand.select().count(), 0)

    def test_policy_gives_the_link_three_commands_and_undo(self):
        for rabbit in self.rabbits_:
            roles = roles_for(self.actor, db.Individual.get_by_id(rabbit.id), ReportGrant(code=self.code))
            self.assertEqual(roles, frozenset({Role.RAPPORT}))
        state = state_for(db.Individual.get_by_id(self.rabbits_[0].id))
        yes = {"RecordAttestation", "RecordDeath", "SetMeasurements", "Undo"}
        for command in COMMAND_FIELDS:
            self.assertIs(allowed(command, frozenset({Role.RAPPORT}), state), command in yes, command)

    def test_code_cannot_touch_a_rabbit_of_another_herd(self):
        with self.assertRaises((IndividualRefused, HerdTrackingForbidden)):
            self.run_as_code(
                self.foreign, RecordDeath({"death_date": "2025-06-01", "butchered": False, "death_note": None})
            )
        roles = roles_for(self.actor, db.Individual.get_by_id(self.foreign.id), ReportGrant(code=self.code))
        self.assertEqual(roles, frozenset())
        self.assertIsNone(db.Individual.get_by_id(self.foreign.id).death_date)

    def test_code_cannot_touch_rabbit_after_approved_sale(self):
        """FA1: the rabbit left the herd; the seller's link no longer reaches it."""
        rabbit = self.rabbits_[2]
        self.assertEqual(
            roles_for(self.actor, db.Individual.get_by_id(rabbit.id), ReportGrant(code=self.code)),
            frozenset({Role.RAPPORT}),
        )
        ht_row(
            "TRANSFER", herd=self.other, individual=rabbit, from_herd=self.herd, herd_tracking_date=date(2026, 1, 10)
        )
        self.assertEqual(
            roles_for(self.actor, db.Individual.get_by_id(rabbit.id), ReportGrant(code=self.code)), frozenset()
        )
        with self.assertRaises((IndividualRefused, HerdTrackingForbidden)):
            self.run_as_code(rabbit, RecordDeath({"death_date": "2025-06-01", "butchered": False, "death_note": None}))
        self.assertIsNone(db.Individual.get_by_id(rabbit.id).death_date)

    def test_rabbit_off_the_report_list_gets_no_role(self):
        uncertified = db.Individual.get_by_id(self.rabbits_[0].id)
        db.Individual.update(certificate=None, digital_certificate=None).where(
            db.Individual.id == uncertified.id
        ).execute()
        self.assertEqual(
            roles_for(self.actor, db.Individual.get_by_id(uncertified.id), ReportGrant(code=self.code)), frozenset()
        )

    def test_purge_free_text_still_runs_for_code_rows(self):
        rabbit = self.rabbits_[1]
        self.run_as_code(
            rabbit, RecordDeath({"death_date": "2025-06-01", "butchered": False, "death_note": "Test, hemlig text"})
        )
        row = db.IndividualCommand.get(db.IndividualCommand.individual == rabbit.id)
        self.assertIn("death_note", row.after)
        changed = purge_command_free_text(datetime.now(timezone.utc) + timedelta(days=400))
        self.assertGreaterEqual(changed, 1)
        row = db.IndividualCommand.get_by_id(row.id)
        self.assertNotIn("death_note", row.after)
        self.assertIsNotNone(row.redacted_at)
        self.assertEqual(row.access_code_id, self.code.id)

    def test_two_codes_are_different_actors(self):
        """R2: an old and a new code for the same herd are different actors."""
        rabbit = self.rabbits_[0]
        self.attest(rabbit)
        entry = db.IndividualCommand.get(db.IndividualCommand.individual == rabbit.id)
        report_code.revoke(self.code, now=arsrapport.now())
        new = report_code.issue_code(self.herd, self.round_, self.member, now=arsrapport.now())
        self.assertEqual(actor_role(CodeActor(self.code), entry), frozenset({Role.ACTOR}))
        self.assertEqual(actor_role(CodeActor(new), entry), frozenset())

    def test_account_and_link_are_different_actors(self):
        """R2: a user whose id equals the code's id is not the code, and the other way round."""
        rabbit = self.rabbits_[0]
        self.attest(rabbit)
        entry = db.IndividualCommand.get(db.IndividualCommand.individual == rabbit.id)
        same_number = mock.Mock(id=self.code.id, spec=["id"])
        self.assertEqual(actor_role(same_number, entry), frozenset())
        user_entry = db.IndividualCommand.create(
            operation_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
            command="RecordDeath",
            individual=rabbit.id,
            actor=self.owner.id,
        )
        self.assertEqual(actor_role(self.owner, user_entry), frozenset({Role.ACTOR}))
        self.assertEqual(actor_role(self.actor, user_entry), frozenset())

    def test_report_ops_grant_does_not_build_the_list(self):
        """L9: with report_ops the role is given without the heavy report_list, and still only inside the herd."""
        rabbit = db.Individual.get_by_id(self.rabbits_[0].id)
        with mock.patch.object(arsrapport, "report_list", side_effect=AssertionError("not needed")):
            grant = ReportGrant(code=self.code, report_ops=frozenset({"op"}))
            self.assertEqual(grant.roles(self.actor, rabbit), frozenset({Role.RAPPORT}))
            foreign = db.Individual.get_by_id(self.foreign.id)
            self.assertEqual(grant.roles(self.actor, foreign), frozenset())

    def test_report_ops_grant_for_a_rabbit_moved_on(self):
        """L2, for a code: the death the link recorded is not undone after the rabbit left the herd."""
        rabbit = self.rabbits_[1]
        self.run_as_code(rabbit, RecordDeath({"death_date": "2025-06-01", "butchered": False, "death_note": None}))
        op = db.IndividualCommand.get(db.IndividualCommand.individual == rabbit.id).operation_id
        ht_row(
            "TRANSFER", herd=self.other, individual=rabbit, from_herd=self.herd, herd_tracking_date=date(2026, 1, 10)
        )
        ops = frozenset({str(op)})
        with self.assertRaises((IndividualRefused, HerdTrackingForbidden)):
            self.run_as_code(rabbit, Undo(op, report_ops=ops), report_ops=ops)
        self.assertIsNotNone(db.Individual.get_by_id(rabbit.id).death_date)
