"""The certificate lifecycle table (utils/certificate_lifecycle.py) and who may write the certificate columns."""

import re
import unittest
from pathlib import Path

from utils.certificate_lifecycle import (
    TRANSITIONS,
    CertState,
    Event,
    check,
    next_state,
    render_mermaid,
    state_of,
)

APP = Path(__file__).resolve().parent.parent

# A write of the certificate columns or of is_current: `x.certificate = ...` or the keyword `certificate=...`.
# `paper_certificate=`, `certificate_type=` and spaced local variables (`certificate = ...`) do not match.
WRITE = re.compile(
    r"\.(?:digital_certificate|certificate|is_current)\s*=(?!=)"
    r"|(?<![\w.])(?:digital_certificate|certificate|is_current)=(?!=)"
)
OWNERS = {
    "utils/individual_commands.py": "the commands own the certificate columns (ADR-0015)",
    "utils/database.py": "the model owns is_current (DigitalCertificateV2.issue_current / retire_current)",
}
ALLOWED = {
    "utils/individual_number_v2.py": "creation: the paper number of a new rabbit (REGISTER_WITH_PAPER, checked there)",
    "blueprints/bunny_v2.py": "in-memory fix-up of the promoted instance for the response, never saved",
    "cli/seed.py": "seed data creates rabbits with a certificate",
    "herdbook.py": "update of a plain dict (the form), not of the model",
}


class TestCertificateLifecycle(unittest.TestCase):
    def test_every_state_is_reachable_from_none(self):
        reached = {CertState.NONE}
        while grown := {row.target for row in TRANSITIONS if row.source in reached} - reached:
            reached |= grown
        self.assertEqual(reached, set(CertState))

    def test_one_row_per_state_and_event(self):
        keys = [(row.source, row.event) for row in TRANSITIONS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_deny_by_default(self):
        rows = {(row.source, row.event) for row in TRANSITIONS}
        for state in CertState:
            for event in Event:
                with self.subTest(state=state.value, event=event.value):  # plain str: xdist cannot serialise a StrEnum
                    if (state, event) in rows:
                        next_state(state, event)
                    else:
                        with self.assertRaises(ValueError):
                            next_state(state, event)
        # The paper number replaces the digital one, but a digital number cannot be issued over a digital one.
        self.assertEqual(next_state(CertState.DIGITAL, Event.ASSIGN_PAPER), CertState.PAPER)
        with self.assertRaises(ValueError):
            next_state(CertState.DIGITAL, Event.ISSUE_NUMBER)

    def test_check_refuses_a_state_the_table_does_not_give(self):
        check(CertState.DIGITAL, Event.ASSIGN_PAPER, CertState.PAPER)
        with self.assertRaises(AssertionError):
            check(CertState.DIGITAL, Event.ASSIGN_PAPER, CertState.DIGITAL)

    def test_check_lets_a_writer_leave_an_illegal_combination_but_never_enter_one(self):
        check(None, Event.ISSUE_NUMBER, CertState.DIGITAL)  # a row from before the table
        with self.assertRaises(AssertionError):
            check(CertState.DIGITAL, Event.ASSIGN_PAPER, None)
        with self.assertRaises(AssertionError):
            check(None, Event.ASSIGN_PAPER, None)

    def test_state_of(self):
        self.assertEqual(state_of(None, None, False), CertState.NONE)
        self.assertEqual(state_of("", None, False), CertState.NONE)  # the legacy blank paper number is none
        self.assertEqual(state_of("12", None, False), CertState.PAPER)
        self.assertEqual(state_of(None, 100000, False), CertState.DIGITAL_NUMBER)
        self.assertEqual(state_of(None, 100000, True), CertState.DIGITAL)

    def test_state_of_refuses_illegal_combinations(self):
        for args in (("12", 100000, False), ("12", 100000, True), ("12", None, True), (None, None, True)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                state_of(*args)

    def test_rendered_diagram_is_checked_in(self):
        checked_in = Path(__file__).with_name("certificate_lifecycle.md").read_text(encoding="utf-8")
        self.assertEqual(render_mermaid(), checked_in)

    def test_only_the_owners_write_the_certificate_columns(self):
        """Grep gate: the writers check their transition, so nobody else may write the columns."""
        found = {}
        for path in sorted(APP.rglob("*.py")):
            relative = path.relative_to(APP).as_posix()
            if relative.startswith("tests/"):
                continue
            hits = [n for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if WRITE.search(line)]
            if hits:
                found[relative] = hits
        self.assertEqual(sorted(set(found) - set(OWNERS) - set(ALLOWED)), [], "write outside the owning modules")
        self.assertEqual(sorted((set(ALLOWED) | set(OWNERS)) - set(found)), [], "stale entry")
