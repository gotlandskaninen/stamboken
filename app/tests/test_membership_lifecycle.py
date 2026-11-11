"""
Tests for the membership state machine (utils.membership_lifecycle). No database: the module is pure.
"""

import re
import unittest
from pathlib import Path

from utils.membership_lifecycle import (
    TRANSITIONS,
    Event,
    State,
    Status,
    TransitionRefused,
    next_state,
    render_mermaid,
    state_of,
)

APP_DIR = Path(__file__).resolve().parent.parent
WRITE = re.compile(r"membership_status\s*=[^=]")
ALLOWED = {  # path relative to app/ -> reason; the target is none
    "utils/matrikel.py": "the one module that writes the status",
    "utils/database.py": "the field definition",
}


class TestMembershipLifecycle(unittest.TestCase):
    def test_every_state_is_reachable_from_create(self):
        seen = {None}
        while True:
            new = {row.dst for row in TRANSITIONS if row.src in seen} - seen
            if not new:
                break
            seen |= new
        self.assertEqual(seen - {None}, set(State))

    def test_retired_cannot_change_status(self):
        for status in Status:
            if status is Status.INACTIVE:
                self.assertIs(next_state(State.RETIRED, Event.SET_STATUS, status), State.RETIRED)
            else:
                with self.assertRaises(TransitionRefused):
                    next_state(State.RETIRED, Event.SET_STATUS, status)

    def test_deny_by_default(self):
        with self.assertRaises(TransitionRefused):
            next_state(State.ACTIVE, Event.ADD_MAIN, Status.ACTIVE)
        with self.assertRaises(TransitionRefused):
            next_state(State.PAUSED, Event.CREATE, Status.ACTIVE)
        with self.assertRaises(TransitionRefused):
            next_state(None, Event.RETIRE)

    def test_state_of_covers_every_status_and_main(self):
        self.assertEqual(
            {state_of(s, m) for s in Status for m in (True, False)},
            set(State),
        )

    def test_rendered_document_is_checked_in(self):
        self.assertEqual(render_mermaid(), (Path(__file__).parent / "membership_lifecycle.md").read_text())

    def test_check_constraint_lists_the_statuses(self):
        source = (APP_DIR / "utils" / "database.py").read_text()
        listed = re.search(r"membership_status IN \(([^)]*)\)", source).group(1)
        self.assertEqual(set(re.findall(r"'(\w+)'", listed)), {s.value for s in Status})

    def test_only_matrikel_writes_the_status(self):
        offenders = []
        for path in APP_DIR.rglob("*.py"):
            rel = path.relative_to(APP_DIR)
            if rel.parts[0] == "tests" or str(rel) in ALLOWED:
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if WRITE.search(line):
                    offenders.append(f"{rel}:{number}: {line.strip()}")
        self.assertEqual(offenders, [])
