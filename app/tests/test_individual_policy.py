"""
Tests for the declarative write policy (utils.individual_policy). No database: the module is pure.
"""

import unittest
from pathlib import Path
from unittest import mock

import utils.individual_policy as policy
from utils.individual_policy import COMMAND_FIELDS, POLICY, STATES, Role, State, allowed, matrix, render_matrix

# Every form field in the underlag's intent table.
UNDERLAG_FIELDS = {
    "name",
    "sex",
    "color",
    "color_note",
    "eye_color",
    "claw_color",
    "belly_color",
    "hair_notes",
    "notes",
    "foot_ring",
    "castration_date",
    "is_active",
    "has_photo",
    "death_date",
    "death_note",
    "butchered",
    "weights",
    "bodyfat",
    "herd",
    "yearly_report_date",
    "selling_date",
    "reason",
    "certificate",
    "number",
    "breeding",
    "origin_herd",
    "digital_certificate",
}
COMMANDS = [c for c in COMMAND_FIELDS if c != "GenebankCorrection"]
IN_GENEBANK = State(False, False)


# subTest parameters are plain strings: pytest-xdist cannot serialize enums or dataclasses in reports.
class TestIndividualPolicy(unittest.TestCase):
    def test_deny_by_default(self):
        self.assertIs(allowed("Unknown", frozenset(Role), IN_GENEBANK), False)
        self.assertIs(allowed("EditDescription", frozenset(), IN_GENEBANK), False)

    def test_caretaker_never_transfers(self):
        for state in STATES:
            with self.subTest(state=str(state)):
                self.assertIs(allowed("TransferIndividual", frozenset({Role.CARETAKER}), state), False)

    def test_owner_cannot_touch_certified_guarded_fields(self):
        owner = frozenset({Role.OWNER})
        for command in ("AssignPaperCertificate", "RenameIndividual", "MoveToLitter"):
            with self.subTest(command=command):
                self.assertIs(allowed(command, owner, State(True, False)), False)
                self.assertIs(allowed(command, owner, State(False, False)), True)

    def test_outside_genebank_only_editors(self):
        for state in (State(False, True), State(True, True)):
            for command in [*COMMANDS, "GenebankCorrection"]:
                with self.subTest(state=str(state), command=command):
                    self.assertIs(allowed(command, frozenset({Role.OWNER}), state), False)
                    self.assertIs(allowed(command, frozenset({Role.CARETAKER}), state), False)
                    self.assertIs(allowed(command, frozenset({Role.ADMIN}), state), True)
                    manager = command not in ("ChangeOriginHerd", "GenebankCorrection")
                    self.assertIs(allowed(command, frozenset({Role.MANAGER_CURRENT}), state), manager)

    def test_genebank_correction_admin_only(self):
        for state in STATES:
            for roles in policy.ROLE_SETS:
                with self.subTest(state=str(state), roles=sorted(r.value for r in roles)):
                    self.assertIs(allowed("GenebankCorrection", roles, state), Role.ADMIN in roles)
            everyone_else = frozenset({Role.MANAGER_CURRENT, Role.MANAGER_ORIGIN, Role.OWNER, Role.CARETAKER})
            self.assertIs(allowed("GenebankCorrection", everyone_else, state), False)

    def test_origin_herd_needs_origin_manager(self):
        def origin(*roles):
            return allowed("ChangeOriginHerd", frozenset(roles), IN_GENEBANK)

        self.assertIs(origin(Role.MANAGER_CURRENT), False)
        self.assertIs(origin(Role.MANAGER_ORIGIN), False)  # Entry is missing
        self.assertIs(origin(Role.MANAGER_ORIGIN, Role.OWNER), True)
        self.assertIs(origin(Role.MANAGER_ORIGIN, Role.MANAGER_CURRENT), True)

    def test_undo_needs_entry_and_actor_or_editor(self):
        def undo(*roles, state=IN_GENEBANK):
            return allowed("Undo", frozenset(roles), state)

        self.assertIs(undo(Role.ACTOR), False)  # Entry is missing
        self.assertIs(undo(Role.ACTOR, Role.OWNER), True)
        self.assertIs(undo(Role.ACTOR, Role.CARETAKER), True)
        self.assertIs(undo(Role.ACTOR, Role.OWNER, state=State(False, True)), False)
        self.assertIs(undo(Role.OWNER), False)
        self.assertIs(undo(Role.MANAGER_CURRENT), True)
        self.assertIs(undo(Role.ADMIN), True)

    def test_actor_grants_nothing_else(self):
        for command in ["Entry", *[c for c in COMMAND_FIELDS if c != "Undo"]]:
            for state in STATES:
                for roles in policy.ROLE_SETS:
                    with self.subTest(command=command, state=str(state), roles=sorted(r.value for r in roles)):
                        self.assertIs(
                            allowed(command, roles | {Role.ACTOR}, state), allowed(command, roles - {Role.ACTOR}, state)
                        )

    def test_every_policy_row_is_load_bearing(self):
        """The table is data, which mutmut does not mutate: removing any row must change the matrix."""
        baseline = matrix()
        for i, row in enumerate(POLICY):
            with self.subTest(row=repr(row)), mock.patch.object(policy, "POLICY", POLICY[:i] + POLICY[i + 1 :]):
                self.assertNotEqual(matrix(), baseline)

    def test_matrix_covers_every_role_field_state(self):
        fields = sum(len(f) for f in COMMAND_FIELDS.values())
        self.assertEqual(len(matrix()), fields * 2 ** len(Role) * 4)
        covered = {field for fields in COMMAND_FIELDS.values() for field in fields}
        self.assertLessEqual(UNDERLAG_FIELDS, covered)

    def test_rendered_matrix_is_checked_in(self):
        checked_in = Path(__file__).with_name("individual_permission_matrix.md").read_text(encoding="utf-8")
        self.assertEqual(render_matrix(), checked_in)
