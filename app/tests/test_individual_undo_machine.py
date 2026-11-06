"""
State machine for the individual write commands and Undo (utils/individual_commands.py, ADR-0017).

Random sequences of EditDescription, RecordDeath, ClearFields, RecordAttestation, a legacy PATCH with two
commands and Undo, by five users, against a model. After every step the database equals the model, and
the rows no command owns (the other individuals, litters, bunnies, weights, bodyfat) are unchanged. The
rule do_then_undo checks the claim literally: right after an undo the state is the one before the
command, litter and active herd-tracking rows included. Ported from the undo-commands spike.

isort:skip_file
"""

import os
import unittest
from collections import Counter
from datetime import date, timedelta

import utils.data_access as da
import utils.database as db
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule, run_state_machine_as_test
from utils import herd_tracking as ht
from utils.individual_commands import (
    ClearFields,
    EditDescription,
    IndividualRefused,
    RecordAttestation,
    RecordDeath,
    Undo,
    _column_value,
    execute,
)

from tests.database_test import _USE_POSTGRES
from tests.test_individual_commands import IndividualTest

BIRTH = date(2021, 2, 1)  # the BIRTH rows of G1-2111 and G1-2112 in the fixture
TEXT = st.sampled_from(["", "Agnes", "Bråk med en annan kanin", "röd"])
DAYS = st.dates(min_value=BIRTH, max_value=date(2026, 10, 27))
EDITS = {
    "name": TEXT,
    "notes": TEXT,
    "sex": st.sampled_from(["female", "male"]),
    "is_active": st.booleans(),
    "has_photo": st.booleans(),
    "castration_date": DAYS.map(date.isoformat),
}
UNDOABLE_EDITS = sorted(set(EDITS) - {"has_photo"})  # do_then_undo always expects 200
DEATH_FIELDS = ("death_date", "death_note", "butchered")
CLEARABLE = ["butchered", "castration_date", "death_date", "death_note"]
MODEL_FIELDS = sorted(set(EDITS) | set(DEATH_FIELDS))
CORRECTORS = ("admin", "manager")
USERS = ("admin", "caretaker", "manager", "owner", "owner2")


def _rows(sql):
    return [r[0] for r in db.DB_PROXY.execute_sql(sql).fetchall()]


def snapshot(other_than=()):
    """Every row a command could disturb. The logs (audit_log, individual_command) grow by design."""
    skip = ",".join(str(i) for i in other_than) or "0"
    return {
        "individual": _rows(
            "SELECT to_jsonb(i) - 'updated_at' FROM individual i "
            f"WHERE individual_id NOT IN ({skip}) ORDER BY individual_id"
        ),
        "breeding": _rows("SELECT to_jsonb(b) - 'updated_at' FROM breeding b ORDER BY breeding_id"),
        "bunny": _rows("SELECT to_jsonb(b) - 'updated_at' FROM bunny b ORDER BY bunny_id"),
        "weight": _rows("SELECT to_jsonb(w) FROM weight w ORDER BY weight_id"),
        "bodyfat": _rows("SELECT to_jsonb(b) FROM bodyfat b ORDER BY bodyfat_id"),
        "herd_tracking": _rows(
            "SELECT jsonb_build_array(herd_tracking_id, individual_id, kind, herd_id, from_herd_id, "
            f"herd_tracking_date) FROM herd_tracking WHERE voided_at IS NULL AND individual_id NOT IN ({skip}) "
            "ORDER BY herd_tracking_id"
        ),
    }


def _last_log_id():
    return db.IndividualCommand.select(db.fn.MAX(db.IndividualCommand.id)).scalar() or 0


def _status(exc):
    """The v2 API's status for a refusal (blueprints/individuals.py undo_individual_command_v2)."""
    if isinstance(exc, ht.HerdTrackingError):
        return exc.status
    return 404 if exc.envelope.get("message") == "Individual not found" else 403


def make_machine(case, stats):
    kits = [case.individuals[0].id, case.individuals[3].id]  # the two G1 kits of litter breeding[0]
    users = {
        "admin": case.admin,
        "caretaker": case.caretaker,
        "manager": case.manager,
        "owner": case.owner,
        "owner2": case.owner2,
    }

    class UndoMachine(RuleBasedStateMachine):
        def __init__(self):
            super().__init__()
            self.scope = db.DB_PROXY.atomic()
            self.txn = self.scope.__enter__()  # every sequence runs in one transaction that is rolled back
            self.fixed = snapshot(other_than=kits)
            self.model = {k: self._read(k) for k in kits}
            self.attests = {k: [] for k in kits}  # active attestations: [(op, date)]
            self.ops = []  # logged commands and undos, as dicts
            self.voided = set()  # kits voided as unpromote does
            stats["sekvenser"] += 1

        def teardown(self):
            self.txn.rollback()
            self.scope.__exit__(None, None, None)

        assertEqual = staticmethod(case.assertEqual)

        @staticmethod
        def _read(kit):
            ind = db.Individual.get_by_id(kit)
            return {f: _column_value(ind, f) for f in MODEL_FIELDS}

        def _refused_if_voided(self, actor, kit, commands):
            if kit not in self.voided:
                return False
            with case.assertRaises(IndividualRefused) as caught:
                execute(users[actor], kit, lambda ctx: commands)
            self.assertEqual(_status(caught.exception), 404)
            stats["execute på makulerad kanin -> 404"] += 1
            return True

        def _expect_rows(self, actor, kit, commands, run):
            """Runs `run`, then checks one log row per command that changed the model, in list order."""
            last = _last_log_id()
            run()
            rows = list(
                db.IndividualCommand.select().where(db.IndividualCommand.id > last).order_by(db.IndividualCommand.id)
            )
            expected = []
            for name, wanted in commands:
                changed = {f: v for f, v in wanted.items() if self.model[kit][f] != v}
                if changed:
                    expected.append((name, {f: self.model[kit][f] for f in changed}, changed))
                    self.model[kit].update(changed)
                stats[f"execute {name}: {'skrivet' if changed else 'eko'}"] += 1
            got = [(r.command, r.before, r.after) for r in rows]
            self.assertEqual(got, expected)
            for row in rows:
                self.ops.append(
                    {
                        "op": row.operation_id,
                        "kit": kit,
                        "actor": actor,
                        "command": row.command,
                        "before": row.before,
                        "after": row.after,
                    }
                )
            return rows

        def _run(self, actor, kit, command, wanted):
            if self._refused_if_voided(actor, kit, [command]):
                return []
            name = type(command).__name__
            return self._expect_rows(
                actor, kit, [(name, wanted)], lambda: execute(users[actor], kit, lambda ctx: [command])
            )

        @staticmethod
        def _edit(data, names):
            return {n: data.draw(EDITS[n]) for n in names}

        @rule(kit=st.sampled_from(kits), actor=st.sampled_from(USERS), data=st.data())
        def edit(self, kit, actor, data):
            changes = self._edit(data, data.draw(st.sets(st.sampled_from(sorted(EDITS)), min_size=1, max_size=3)))
            self._run(actor, kit, EditDescription(changes), changes)

        @rule(kit=st.sampled_from(kits), actor=st.sampled_from(USERS), day=DAYS, note=TEXT, b=st.booleans())
        def death(self, kit, actor, day, note, b):
            changes = {"death_date": day.isoformat(), "death_note": note, "butchered": b}
            self._run(actor, kit, RecordDeath(changes), changes)

        @rule(
            kit=st.sampled_from(kits),
            actor=st.sampled_from(USERS),
            names=st.sets(st.sampled_from(CLEARABLE), min_size=1),
        )
        def clear(self, kit, actor, names):
            self._run(actor, kit, ClearFields(frozenset(names)), dict.fromkeys(names))

        @rule(kit=st.sampled_from(kits), actor=st.sampled_from(USERS), day=DAYS, note=TEXT)
        def legacy_patch(self, kit, actor, day, note):
            """update_individual with death_date and notes: RecordDeath and EditDescription in one request."""
            if kit in self.voided:
                return
            ind = db.Individual.get_by_id(kit)
            form = {"id": kit, "number": ind.number, "herd": "G1", "death_date": day.isoformat(), "notes": note}
            commands = [("RecordDeath", {"death_date": day.isoformat()}), ("EditDescription", {"notes": note})]
            rows = self._expect_rows(
                actor,
                kit,
                commands,
                lambda: self.assertEqual(da.update_individual(form, users[actor].uuid)["status"], "success"),
            )
            self.assertEqual(len({r.request_id for r in rows}), min(len(rows), 1))

        @rule(kit=st.sampled_from(kits), actor=st.sampled_from(USERS), gap=st.integers(0, 400))
        def attest(self, kit, actor, gap):
            latest = self.attests[kit][-1][1] if self.attests[kit] else BIRTH
            day = latest + timedelta(days=gap)
            command = RecordAttestation("G1", day.isoformat())
            if self._refused_if_voided(actor, kit, [command]):
                return
            last = _last_log_id()
            execute(users[actor], kit, lambda ctx: [command])
            [row] = db.IndividualCommand.select().where(db.IndividualCommand.id > last)
            self.attests[kit].append((row.operation_id, day))
            self.ops.append({"op": row.operation_id, "kit": kit, "actor": actor, "command": "RecordAttestation"})
            stats["execute RecordAttestation: skrivet"] += 1

        def _expected(self, entry, actor, reason):
            """The status Undo should give, in the order it checks."""
            kit = entry["kit"]
            if kit in self.voided:
                return 404
            attestation = entry["command"] == "RecordAttestation"
            if entry["command"] == "Undo" or (entry["command"] == "EditDescription" and "has_photo" in entry["after"]):
                return 400
            if (entry["op"] not in [a[0] for a in self.attests[kit]]) if attestation else entry.get("undone"):
                return 409
            corrector = actor in CORRECTORS
            if actor != entry["actor"]:
                if not corrector:
                    return 403
                if not reason:
                    return 400
            if attestation:
                if not corrector and self.attests[kit][-1][0] != entry["op"]:
                    return 403
                return 200
            if any(self.model[kit][f] != v for f, v in entry["after"].items()):
                return 409
            return 200

        def _undo(self, actor, entry, reason):
            last = _last_log_id()
            try:
                execute(users[actor], entry["kit"], lambda ctx: [Undo(entry["op"], reason)])
            except (ht.HerdTrackingError, IndividualRefused) as exc:
                return _status(exc), None
            [row] = db.IndividualCommand.select().where(db.IndividualCommand.id > last)
            return 200, row

        def _apply_undo(self, entry, actor, row):
            kit = entry["kit"]
            self.assertEqual((row.command, row.undoes), ("Undo", entry["op"]))
            undo = {"op": row.operation_id, "kit": kit, "actor": actor, "command": "Undo"}
            entry["undone"] = True
            if entry["command"] == "RecordAttestation":
                self.attests[kit] = [a for a in self.attests[kit] if a[0] != entry["op"]]
            else:
                self.assertEqual((row.before, row.after), (entry["after"], entry["before"]))
                self.model[kit].update(entry["before"])
                undo.update(before=entry["after"], after=entry["before"])
            self.ops.append(undo)

        @precondition(lambda self: self.ops)
        @rule(data=st.data(), other=st.sampled_from(USERS), reason=st.sampled_from([None, "Fel kanin"]))
        def undo(self, data, other, reason):
            entry = data.draw(st.sampled_from(self.ops))
            actor = entry["actor"] if data.draw(st.integers(0, 2)) else other  # mostly the one who did it
            want = self._expected(entry, actor, reason)
            got, row = self._undo(actor, entry, reason)
            kind = "årsrapport" if entry["command"] == "RecordAttestation" else entry["command"]
            stats[f"undo {kind} -> {got}"] += 1
            self.assertEqual(got, want, f"undo {entry} by {actor} reason={reason}")
            if got == 200:
                self._apply_undo(entry, actor, row)

        @rule(kit=st.sampled_from(kits), actor=st.sampled_from(USERS))
        def photo_undo_refused(self, kit, actor):
            """A photo edit is logged, but undoing it is 400 and changes nothing."""
            if kit in self.voided:
                return
            changes = {"has_photo": self.model[kit]["has_photo"] is not True}
            [row] = self._run(actor, kit, EditDescription(changes), changes)
            before = snapshot()
            got, _ = self._undo(actor, self.ops[-1], None)
            self.assertEqual((got, snapshot()), (400, before))
            stats["photo_undo_refused -> 400"] += 1

        @precondition(lambda self: any(self.attests.values()))
        @rule(data=st.data())
        def void_elsewhere(self, data):
            """A manager voids an attestation through herd-tracking's own API, not through Undo."""
            if data.draw(st.integers(0, 4)):  # rare, so most sequences keep their attestations
                return
            kit = data.draw(st.sampled_from([k for k in kits if self.attests[k]]))
            op, _ = data.draw(st.sampled_from(self.attests[kit]))
            row = db.HerdTracking.get(db.HerdTracking.operation_id == op)
            ht.void_herd_tracking(row.id, case.manager, "Fel datum")
            self.attests[kit] = [a for a in self.attests[kit] if a[0] != op]
            stats["void via herd-tracking"] += 1

        @precondition(lambda self: kits[1] not in self.voided)
        @rule(roll=st.integers(0, 9))
        def unpromote(self, roll):
            """The second kit is voided with its herd-tracking rows, as unpromote does."""
            if roll:  # rare: the first kit is never voided
                return
            ind = db.Individual.get_by_id(kits[1])
            ht.void_all_for_unpromote(ind, case.manager)
            db.Individual.update(voided=True).where(db.Individual.id == kits[1]).execute()
            self.voided.add(kits[1])
            self.attests[kits[1]] = []
            stats["makulering (som unpromote)"] += 1

        @rule(kit=st.sampled_from(kits), actor=st.sampled_from(USERS), data=st.data())
        def do_then_undo(self, kit, actor, data):
            """The literal claim: an undo right after a command gives back the state before it."""
            if kit in self.voided:
                return
            kind = data.draw(st.sampled_from(["edit", "death", "clear", "attest"]))
            if kind == "edit":
                names = data.draw(st.sets(st.sampled_from(UNDOABLE_EDITS), min_size=1, max_size=3))
                command = EditDescription(self._edit(data, names))
            elif kind == "death":
                command = RecordDeath(
                    {
                        "death_date": data.draw(DAYS).isoformat(),
                        "death_note": data.draw(TEXT),
                        "butchered": data.draw(st.booleans()),
                    }
                )
            elif kind == "clear":
                command = ClearFields(frozenset(data.draw(st.sets(st.sampled_from(CLEARABLE), min_size=1))))
            else:
                latest = self.attests[kit][-1][1] if self.attests[kit] else BIRTH
                day = latest + timedelta(days=data.draw(st.integers(0, 400)))
                command = RecordAttestation("G1", day.isoformat())
            before = snapshot()
            last = _last_log_id()
            execute(users[actor], kit, lambda ctx: [command])
            rows = list(db.IndividualCommand.select().where(db.IndividualCommand.id > last))
            for row in rows:
                execute(users[actor], kit, lambda ctx, op=row.operation_id: [Undo(op)])
            self.assertEqual(snapshot(), before)
            stats[f"do_then_undo {kind}: {'ångrat, lika' if rows else 'eko'}"] += 1

        @invariant()
        def database_matches_model(self):
            for kit in kits:
                self.assertEqual(self._read(kit), self.model[kit])
                days = _rows(
                    "SELECT herd_tracking_date::text FROM herd_tracking WHERE voided_at IS NULL "
                    f"AND kind = 'ATTESTATION' AND individual_id = {kit} ORDER BY herd_tracking_date, herd_tracking_id"
                )
                self.assertEqual(days, [d.isoformat() for _, d in self.attests[kit]])
            self.assertEqual(snapshot(other_than=kits), self.fixed)

    return UndoMachine


@unittest.skipUnless(_USE_POSTGRES, "the snapshot reads rows as jsonb")
class TestUndoStateMachine(IndividualTest):
    def setUp(self):
        super().setUp()
        self.owner2 = da.register_user("owner2", "pass")
        self.owner2.add_role("owner", self.herds[0].id)
        self.caretaker = self._caretaker()

    def test_random_sequences(self):
        stats = Counter()
        examples = int(os.environ.get("UNDO_EXAMPLES", "50"))
        run_state_machine_as_test(
            make_machine(self, stats),
            settings=settings(
                max_examples=examples,
                stateful_step_count=20,
                deadline=None,
                database=None,
                suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
            ),
        )
        print("\n".join(f"{k}\t{v}" for k, v in sorted(stats.items())))
        self.assertGreaterEqual(stats["sekvenser"], examples)
