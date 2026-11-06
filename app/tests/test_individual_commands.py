"""
Tests for the individual write commands and their executor (utils/individual_commands.py, ADR-0015).

IR-xx are rule ids from the design notes for the individual commands (not in this repo).

isort:skip_file
"""

import os
import tempfile
import unittest
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.individual_commands as ic  # noqa: E402
from herdbook import APP  # noqa: E402
from utils import number_assets  # noqa: E402
from utils.herd_tracking import (  # noqa: E402
    BIRTH_HERD_CHANGED_REASON,
    HerdTrackingConflict,
    HerdTrackingError,
    HerdTrackingForbidden,
    HerdTrackingInvalid,
)
from utils.individual_commands import (  # noqa: E402
    AssignPaperCertificate,
    ChangeOriginHerd,
    ClearFields,
    Command,
    EditDescription,
    IndividualRefused,
    IssueDigitalCertificate,
    MoveToLitter,
    RecordAttestation,
    RecordDeath,
    RenameIndividual,
    SetMeasurements,
    Stage,
    TransferIndividual,
    execute,
    roles_for,
    state_for,
)
from utils.individual_legacy import translate  # noqa: E402
from utils.individual_policy import Role, allowed  # noqa: E402
from utils.pedigree_guard import CYCLE_PROBLEM  # noqa: E402

from tests.database_test import _USE_POSTGRES, DatabaseTest  # noqa: E402
from tests.ht_helpers import ht_row  # noqa: E402
from tests.test_legacy_api_contracts import FlaskTest  # noqa: E402
from tests.test_renumber_assets import FakeS3  # noqa: E402


@dataclass
class Probe(Command):
    """Test command: logs its checks, raises `error` in `fail_at`, sets `fields` in apply."""

    name: str = "probe"
    log: list = field(default_factory=list)
    fail_at: Stage | None = None
    error: Exception | None = None
    fields: dict = field(default_factory=dict)
    clear: dict = field(default_factory=dict)

    def check(self, stage, ctx):
        self.log.append((self.name, stage))
        if stage == self.fail_at:
            raise self.error

    def pre_write(self, ctx):
        return self.clear

    def apply(self, ctx):
        for key, value in self.fields.items():
            setattr(ctx.individual, key, value)


FORBIDDEN = {"status": "error", "message": "Forbidden"}


def error(message):
    return {"status": "error", "message": message}


class IndividualTest(DatabaseTest):
    # self.individuals[0] = G1-2111 (paper certificate "12"), [3] = G1-2112 (no certificate), both in G1,
    # the owner's herd; [2] and [4] are in M3 (Mellerud).

    def setUp(self):
        super().setUp()
        self.ind = self.individuals[3]

    def _stored(self, ind=None):
        return db.Individual.get_by_id((ind or self.ind).id)

    def _run(self, user, *commands, ind=None, **kwargs):
        return execute(user, (ind or self.ind).id, lambda ctx: list(commands), **kwargs)

    def _refusal(self, user, *commands, error=IndividualRefused, **kwargs):
        with self.assertRaises(error) as raised:
            self._run(user, *commands, **kwargs)
        return raised.exception

    def _name(self, user):
        """The fixture users have no username, which the CSV log lines start with."""
        user.username = user.email
        user.save()
        return user

    def _caretaker(self):
        """A grant holder on G1, as in test_individual_sell_v2.py::TestTransferPermissionsV2."""
        membership = db.Membership.create(member_number=6, membership_status="active")
        self.herds[0].membership = membership
        self.herds[0].save()
        user = da.register_user("sune@example.com", "pass", username="sune")
        member = db.Member.create(
            membership=membership,
            first_name="Sune",
            last_name="Skötarsson",
            email="sune@example.com",
            role="skotare",
            user=user,
        )
        db.HerdAccessGrant.create(member=member, herd=self.herds[0], granted_by=self.admin)
        return user

    def _litter(self, birth=datetime(2021, 2, 1), herd=None, **parents):
        """A litter born `birth` in G1 (or `herd`), without parents unless given (no unique-key clash)."""
        return db.Breeding.create(
            breed_date=birth - timedelta(days=31),
            birth_date=birth,
            **parents,
            litter_size=2,
            litter_size6w=2,
            breeding_herd_id=herd or self.herds[0],
        )

    def _births(self, ind=None):
        """The active BIRTH rows as (herd, date)."""
        rows = db.HerdTracking.select().where(
            db.HerdTracking.individual == (ind or self.ind).id, db.HerdTracking.kind == "BIRTH", db.ht_not_voided()
        )
        return [(r.herd.herd, db.coerce_date(r.herd_tracking_date).isoformat()) for r in rows]

    def _certs(self, ind=None):
        stored = self._stored(ind)
        return stored.certificate, stored.digital_certificate

    def _roster_litter(self, litter_size6w, alive=1, certified=0):
        """A roster litter (litter_number and birth_date set) past 6 weeks, with `alive` kits in its roster."""
        litter = db.Breeding.create(
            breed_date=datetime(2024, 12, 10),
            birth_date=datetime(2025, 1, 10),
            litter_number=1,
            litter_size=3,
            litter_size6w=litter_size6w,
            mother=self.parents[0],
            father=self.parents[1],
            breeding_herd_id=self.herds[0],
        )
        for slot in range(1, alive + 1):
            db.Bunny.create(breeding=litter, slot_order=slot)
        for n in range(certified):
            db.Individual.create(
                origin_herd=self.herds[0], breeding=litter, number=f"G1-251{5 + n}", certificate=f"C{n}"
            )
        return litter

    def _kit(self, litter):
        return db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2511")

    def _outside_owner(self, ind=None):
        """Moves the rabbit to GX1 and makes the owner its holder there."""
        outside = db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför genbanken")
        ht_row("TRANSFER", individual=ind or self.ind, herd=outside, herd_tracking_date=datetime(2022, 1, 1))
        self.owner.add_role("owner", outside.id)
        return self.owner


class TestExecute(IndividualTest):
    def test_policy_agrees_with_user_methods(self):
        """The table is bound to User's methods: Entry is can_edit, TransferIndividual is can_transfer."""
        # Keyed by role, not username: the fixture users have none, and a dict on it would keep one of them.
        users = {
            "admin": self.admin,
            "manager": self.manager,
            "owner": self.owner,
            "viewer": self.viewer,
            "caretaker": self._caretaker(),
        }
        outside = db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför genbanken")
        for placement in ("G1", "GX1"):
            if placement == "GX1":
                ht_row("TRANSFER", individual=self.ind, herd=outside, herd_tracking_date=datetime(2022, 1, 1))
            ind = self._stored()
            self.assertEqual(ind.current_herd.herd, placement)
            for name, user in users.items():
                with self.subTest(user=name, herd=placement):
                    roles, state = roles_for(user, ind), state_for(ind)
                    self.assertEqual(allowed("EditDescription", roles, state), user.can_edit(ind.id))
                    self.assertEqual(allowed("TransferIndividual", roles, state), user.can_transfer(ind.id))
                    self.assertEqual(allowed("GenebankCorrection", roles, state), user.is_admin)
                    self.assertNotIn(Role.ACTOR, roles)  # derived only by Undo

    def test_no_commands_writes_nothing(self):
        before = self._stored()
        execute(self.owner, self.ind.id, lambda ctx: [])
        after = self._stored()
        self.assertNotEqual(after.updated_at, before.updated_at)
        before_row, after_row = before.__data__, after.__data__
        self.assertEqual({**after_row, "updated_at": None}, {**before_row, "updated_at": None})

    def test_checks_run_stage_by_stage(self):
        log = []
        execute(self.owner, self.ind.id, lambda ctx: [Probe("a", log), Probe("b", log)])
        self.assertEqual(log, [(name, stage) for stage in Stage for name in ("a", "b")])

    def test_refusal_before_apply_writes_nothing(self):
        refuse = Probe("refuse", fail_at=Stage.COLOR, error=IndividualRefused("x"))
        write = Probe("write", fields={"notes": "skrivet"})
        with self.assertRaises(IndividualRefused) as raised:
            execute(self.owner, self.ind.id, lambda ctx: [write, refuse])
        self.assertEqual(raised.exception.envelope, {"status": "error", "message": "x"})
        self.assertIsNone(self._stored().notes)

    def test_litter_changed_before_lock_conflicts(self):
        """Review Focus 4: the rabbit moves to another litter between the read and the lock: 409, nothing written."""
        original = ic.lock_breedings

        def move_then_lock(ids):
            locked = original(ids)
            db.Individual.update(breeding=self.breeding[2].id).where(db.Individual.id == self.ind.id).execute()
            return locked

        write = Probe("write", fields={"notes": "skrivet"})
        with (
            mock.patch.object(ic, "lock_breedings", side_effect=move_then_lock),
            self.assertRaises(HerdTrackingConflict),
        ):
            execute(self.owner, self.ind.id, lambda ctx: [write])
        self.assertEqual((self._stored().breeding_id, self._stored().notes), (self.breeding[0].id, None))

    def test_stored_is_not_mutated(self):
        db.Individual.update(notes="gammal").where(db.Individual.id == self.ind.id).execute()
        seen = {}

        def translate(ctx):
            seen["ctx"] = ctx
            return [Probe("write", fields={"notes": "ny"})]

        execute(self.owner, self.ind.id, translate)
        self.assertEqual((seen["ctx"].stored.notes, seen["ctx"].individual.notes), ("gammal", "ny"))
        self.assertEqual(self._stored().notes, "ny")

    def test_breeding_after_is_the_litter_after_the_request(self):
        """Set before any check: the stored litter, or the target litter (canonicalised) when the request moves."""
        seen = []
        execute(self.owner, self.ind.id, lambda ctx: seen.append(ctx.breeding_after) or [])
        target = self.breeding[2].id
        execute(self.owner, self.ind.id, lambda ctx: seen.append(ctx.breeding_after) or [], target_breeding=f"{target}")
        self.assertEqual(seen, [self.breeding[0].id, target])

    def test_shared_guards(self):
        """IR-03 before IR-05, under the lock and whatever the commands are."""
        with self.assertRaises(IndividualRefused) as viewer:
            execute(self.viewer, self.ind.id, lambda ctx: [])
        self.assertEqual(viewer.exception.envelope, {"status": "error", "message": "Forbidden"})
        db.Individual.update(voided=True).where(db.Individual.id == self.ind.id).execute()
        for user, message in ((self.owner, "Individual not found"), (self.viewer, "Forbidden")):
            with self.subTest(user=user.username), self.assertRaises(IndividualRefused) as raised:
                execute(user, self.ind.id, lambda ctx: [])
            self.assertEqual(raised.exception.envelope, {"status": "error", "message": message})

    def test_raw_stage_errors_are_tagged(self):
        cases = (
            (Stage.HERD, KeyError("herd"), Stage.HERD),
            (Stage.NUMBER_UNIQUE, IndividualRefused("Individual number already exists"), None),
            (Stage.COLOR, KeyError("color"), None),
        )
        for stage, error, tag in cases:
            with self.subTest(stage=stage.name, error=type(error).__name__):
                with self.assertRaises(type(error)) as raised:
                    execute(self.owner, self.ind.id, lambda ctx, s=stage, e=error: [Probe(fail_at=s, error=e)])
                self.assertEqual(getattr(raised.exception, "individual_stage", None), tag)

    @unittest.skipUnless(_USE_POSTGRES, "audit_log is written by PostgreSQL triggers")
    def test_pre_write_is_its_own_update(self):
        """IR-51: the clearing is its own UPDATE before the save, so audit_log gets two rows, the clearing first."""
        db.Individual.update(notes="gammal").where(db.Individual.id == self.ind.id).execute()
        db.DATABASE.execute_sql("TRUNCATE audit_log RESTART IDENTITY")
        commands = [Probe("clear", clear={"notes": None}), Probe("name", fields={"name": "Nyman"})]
        execute(self.owner, self.ind.id, lambda ctx: commands)
        rows = db.AuditLog.select().where(
            db.AuditLog.table_name == "individual", db.AuditLog.record_id == str(self.ind.id)
        )
        self.assertEqual([r.changed_fields for r in rows.order_by(db.AuditLog.id)], [["notes"], ["name"]])
        self.assertEqual((self._stored().notes, self._stored().name), (None, "Nyman"))

    def test_finishing_outside_and_inside_a_transaction(self):
        """IR-23: without an outer transaction execute finishes the asset moves itself; inside one it leaves
        them to the caller (teardown_request), and a rollback keeps the originals."""

        @dataclass(frozen=True)
        class Rename(Command):
            number: str

            def apply(self, ctx):
                ctx.individual.number = self.number

            def after_save(self, ctx):
                number_assets.record(ctx.individual.id, ctx.stored.number, ctx.individual.number, True)

        old = self.ind.number
        objects = {f"{old}/certificate.pdf": b"cert"}
        with (
            tempfile.TemporaryDirectory() as uploads,
            mock.patch.dict(os.environ, {"UPLOAD_FOLDER": uploads}),
            mock.patch("utils.s3.get_s3_client", return_value=FakeS3(objects)),
        ):
            with self.assertRaises(RuntimeError), db.DATABASE.atomic():
                execute(self.owner, self.ind.id, lambda ctx: [Rename("G1-2119")])
                self.assertEqual(set(objects), {f"{old}/certificate.pdf", "~G1-2119/certificate.pdf"})
                raise RuntimeError("the caller rolls back")
            number_assets.finish()  # what teardown_request does after the caller's transaction
            self.assertEqual((objects, self._stored().number), ({f"{old}/certificate.pdf": b"cert"}, old))

            execute(self.owner, self.ind.id, lambda ctx: [Rename("G1-2119")])
            self.assertEqual((objects, self._stored().number), ({"G1-2119/certificate.pdf": b"cert"}, "G1-2119"))

    def test_misspelled_check_hook_fails_at_definition(self):
        with self.assertRaisesRegex(TypeError, "check_colour"):

            class Misspelled(ic.PolicyCommand):  # noqa: F841
                def check_colour(self, ctx):
                    pass

    def test_apply_and_after_save_follow_rank(self):
        """apply by apply_rank (stable), then save, then after_save in the same order."""
        log = []

        def ranked(rank, name):
            class Ranked(Command):
                apply_rank = rank

                def apply(self, ctx):
                    log.append(("apply", name))
                    ctx.individual.notes = name

                def after_save(self, ctx):
                    saved = db.Individual.get_by_id(ctx.individual.id).notes
                    log.append(("after_save", name, saved))

            return Ranked()

        commands = [ranked(70, "a"), ranked(0, "b"), ranked(30, "c"), ranked(30, "d")]
        execute(self.owner, self.ind.id, lambda ctx: commands)
        order = ["b", "c", "d", "a"]
        self.assertEqual(log, [("apply", n) for n in order] + [("after_save", n, "a") for n in order])


class TestEditDescription(IndividualTest):
    def test_editors_and_holders_edit(self):
        for user in (self.admin, self.manager, self.owner):
            with self.subTest(user=user.email):
                self._run(user, EditDescription({"notes": f"av {user.email}"}))
                self.assertEqual(self._stored().notes, f"av {user.email}")

    def test_caretaker_edits_notes(self):
        self._run(self._caretaker(), EditDescription({"notes": "skött"}))
        self.assertEqual(self._stored().notes, "skött")

    def test_viewer_is_refused_forbidden(self):
        self.assertEqual(self._refusal(self.viewer, EditDescription({"notes": "x"})).envelope, FORBIDDEN)
        self.assertIsNone(self._stored().notes)

    def test_owner_refused_on_outside_genebank_rabbit(self):
        """A holder never edits outside the genebank (_can_edit_herd); an editor still does."""
        owner = self._outside_owner()
        self.assertEqual(self._refusal(owner, EditDescription({"notes": "x"})).envelope, FORBIDDEN)
        self._run(self.manager, EditDescription({"notes": "av manager"}))
        self.assertEqual(self._stored().notes, "av manager")

    def test_unknown_color_message(self):
        refusal = self._refusal(self.owner, EditDescription({"color": "finns-inte"}))
        self.assertEqual(refusal.envelope, error("Unknown color: 'finns-inte''"))

    def test_color_by_name(self):
        self._run(self.owner, EditDescription({"color": "stgröhn"}))
        self.assertEqual(self._stored().color_id, self.colors[1].id)

    def test_bad_castration_date_message(self):
        """IR-12: strptime's message; a non-string is set as it is."""
        refusal = self._refusal(self.owner, EditDescription({"castration_date": "31/12"}))
        self.assertEqual(refusal.envelope, error("time data '31/12' does not match format '%Y-%m-%d'"))
        self._run(self.owner, EditDescription({"castration_date": datetime(2024, 5, 1).date()}))
        self.assertEqual(self._stored().castration_date, datetime(2024, 5, 1).date())

    def test_csv_line_format(self):
        """Changed fields as {user},{number},{field},{old},{new}, and a date field always, with the parsed
        date in the old column (IR-11, IR-50)."""
        db.Individual.update(name="Bosse").where(db.Individual.id == self.ind.id).execute()
        changes = {"name": "Bosse", "notes": "ny", "color": "stgröhn", "castration_date": "2024-05-01"}
        with self.assertLogs("Gotland_update", level="INFO") as logs:
            self._run(self._name(self.owner), EditDescription(changes))
        self.assertEqual(
            logs.output,
            [
                "INFO:Gotland_update:owner,G1-2112,notes,None,ny,",
                f"INFO:Gotland_update:owner,G1-2112,color,{self.colors[0].id},{self.colors[1].id},",
                "INFO:Gotland_update:owner,G1-2112,castration_date,2024-05-01,2024-05-01,",
            ],
        )
        stored = self._stored()
        self.assertEqual((stored.notes, stored.castration_date), ("ny", datetime(2024, 5, 1).date()))

    def test_unknown_keys_rejected(self):
        for changes in ({"number": "G1-2199"}, {"certificate": "77"}, {"voided": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                EditDescription(changes)


class TestRecordDeath(IndividualTest):
    DEATH = {"death_date": "2024-05-01", "death_note": "sjuk", "butchered": True}

    def _death(self, ind=None):
        stored = self._stored(ind)
        return stored.death_date, stored.death_note, stored.butchered

    def test_owner_records_death_and_butchered(self):
        self._run(self.owner, RecordDeath(self.DEATH))
        self.assertEqual(self._death(), (datetime(2024, 5, 1).date(), "sjuk", True))

    def test_editors_record_death(self):
        for user, ind in ((self.admin, self.individuals[3]), (self.manager, self.individuals[0])):
            with self.subTest(user=user.email):
                self._run(user, RecordDeath(self.DEATH), ind=ind)
                self.assertEqual(self._death(ind), (datetime(2024, 5, 1).date(), "sjuk", True))

    def test_caretaker_records_death(self):
        self._run(self._caretaker(), RecordDeath({"death_date": "2024-05-01"}))
        self.assertEqual(self._stored().death_date, datetime(2024, 5, 1).date())

    def test_viewer_refused(self):
        self.assertEqual(self._refusal(self.viewer, RecordDeath(self.DEATH)).envelope, FORBIDDEN)
        self.assertEqual(self._death(), (None, None, False))

    def test_death_date_parsed_before_castration_date(self):
        """FORM_WRITABLE_FIELDS order within DATES: RecordDeath is listed before EditDescription."""
        commands = (RecordDeath({"death_date": "1/5"}), EditDescription({"castration_date": "2/5"}))
        refusal = self._refusal(self.owner, *commands)
        self.assertEqual(refusal.envelope, error("time data '1/5' does not match format '%Y-%m-%d'"))

    def test_unknown_keys_rejected(self):
        for changes in ({"name": "Bosse"}, {"castration_date": "2024-05-01"}, {"voided": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                RecordDeath(changes)


class TestClearFields(IndividualTest):
    DEATH_FIELDS = frozenset({"death_date", "death_note", "butchered"})

    def setUp(self):
        super().setUp()
        dead = {"death_date": datetime(2024, 5, 1).date(), "death_note": "sjuk", "butchered": True}
        db.Individual.update(**dead, castration_date=datetime(2023, 1, 1).date()).where(
            db.Individual.id == self.ind.id
        ).execute()

    def _death(self):
        stored = self._stored()
        return stored.death_date, stored.death_note, stored.butchered

    def test_owner_clears_death_fields(self):
        """No CSV line for the clearing (IR-51)."""
        with self.assertNoLogs("Gotland_update"):
            self._run(self._name(self.owner), ClearFields(self.DEATH_FIELDS))
        self.assertEqual(self._death(), (None, None, None))
        self.assertEqual(self._stored().castration_date, datetime(2023, 1, 1).date())

    def test_caretaker_clears_castration_date(self):
        self._run(self._caretaker(), ClearFields(frozenset({"castration_date"})))
        self.assertIsNone(self._stored().castration_date)

    def test_viewer_refused(self):
        self.assertEqual(self._refusal(self.viewer, ClearFields(self.DEATH_FIELDS)).envelope, FORBIDDEN)
        self.assertEqual(self._death(), (datetime(2024, 5, 1).date(), "sjuk", True))

    def test_unknown_fields_rejected(self):
        for fields in ({"name"}, {"death_date", "voided"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                ClearFields(frozenset(fields))

    @unittest.skipUnless(_USE_POSTGRES, "audit_log is written by PostgreSQL triggers")
    def test_clear_and_butchered_false_give_two_audit_rows(self):
        """IR-51, v2's undo of death (V4): the clearing, then `butchered: false`, each its own audit row."""
        db.DATABASE.execute_sql("TRUNCATE audit_log RESTART IDENTITY")
        self._run(self.owner, ClearFields(self.DEATH_FIELDS), RecordDeath({"butchered": False}))
        rows = db.AuditLog.select().where(
            db.AuditLog.table_name == "individual", db.AuditLog.record_id == str(self.ind.id)
        )
        changed = [set(r.changed_fields) for r in rows.order_by(db.AuditLog.id)]
        self.assertEqual(changed, [set(self.DEATH_FIELDS), {"butchered"}])
        self.assertEqual(self._death(), (None, None, False))


class TestSetMeasurements(IndividualTest):
    WEIGHTS = [{"date": "2024-01-01", "weight": 2.5}]

    def _weights(self, ind=None):
        rows = db.Weight.select().where(db.Weight.individual == (ind or self.ind).id).order_by(db.Weight.weight_date)
        return [(r.weight_date.strftime("%Y-%m-%d"), r.weight) for r in rows]

    def _bodyfat(self, ind=None):
        rows = db.Bodyfat.select().where(db.Bodyfat.individual == (ind or self.ind).id)
        return [(r.bodyfat_date.strftime("%Y-%m-%d"), r.bodyfat) for r in rows.order_by(db.Bodyfat.bodyfat_date)]

    def test_list_replacement_adds_and_removes(self):
        """IR-14: the list replaces the stored one; a list left out (MISSING) is not touched. Weights that
        float4 holds exactly: the fixture's 2.1 is never matched by the DELETE (as today)."""
        ind = self.individuals[0]  # G1-2111: a bodyfat on 2020-02-02
        self._run(self.owner, SetMeasurements(weights=self.WEIGHTS), ind=ind)
        later = {"date": "2024-02-01", "weight": 2.75}
        self._run(self.owner, SetMeasurements(weights=[later]), ind=ind)
        self.assertEqual(self._weights(ind), [("2020-02-02", 2.1), ("2024-02-01", 2.75)])
        self.assertEqual(self._bodyfat(ind), [("2020-02-02", "low")])
        self._run(self.owner, SetMeasurements(bodyfat=[{"date": "2024-01-01", "bodyfat": "high"}]), ind=ind)
        self.assertEqual(self._bodyfat(ind), [("2024-01-01", "high")])

    def test_unknown_bodyfat_dropped(self):
        bodyfat = [{"date": "2024-01-01", "bodyfat": "fet"}, {"date": "2024-02-01", "bodyfat": "normal"}]
        self._run(self.owner, SetMeasurements(bodyfat=bodyfat))
        self.assertEqual(self._bodyfat(), [("2024-02-01", "normal")])

    def test_editors_weigh(self):
        for user, ind in ((self.admin, self.individuals[3]), (self.manager, self.individuals[1])):
            with self.subTest(user=user.email):
                self._run(user, SetMeasurements(weights=self.WEIGHTS), ind=ind)
                self.assertEqual(self._weights(ind), [("2024-01-01", 2.5)])

    def test_caretaker_may_weigh(self):
        self._run(self._caretaker(), SetMeasurements(weights=self.WEIGHTS))
        self.assertEqual(self._weights(), [("2024-01-01", 2.5)])

    def test_viewer_refused(self):
        self.assertEqual(self._refusal(self.viewer, SetMeasurements(weights=self.WEIGHTS)).envelope, FORBIDDEN)
        self.assertEqual(self._weights(), [])

    def test_null_list_raises_type_error(self):
        """IR-42: null is passed on, and the TypeError rolls back the other list."""
        self._refusal(self.owner, SetMeasurements(weights=self.WEIGHTS, bodyfat=None), error=TypeError)
        self.assertEqual(self._weights(), [])


class TestRecordAttestation(IndividualTest):
    def _newest(self, ind=None):
        row = (
            db.HerdTracking.select()
            .where(db.HerdTracking.individual == (ind or self.ind).id, db.ht_not_voided())
            .order_by(db.HerdTracking.id.desc())
            .first()
        )
        return row.kind, row.herd.herd, db.coerce_date(row.herd_tracking_date).isoformat(), row.signature_id

    def test_owner_attests(self):
        self._run(self.owner, RecordAttestation("G1", "2024-05-01"))
        self.assertEqual(self._newest(), ("ATTESTATION", "G1", "2024-05-01", self.owner.id))

    def test_editors_and_caretaker_attest(self):
        for day, user in enumerate((self.admin, self.manager, self._caretaker()), start=1):
            with self.subTest(user=user.email):
                self._run(user, RecordAttestation("G1", f"2024-05-0{day}"))
                self.assertEqual(self._newest(), ("ATTESTATION", "G1", f"2024-05-0{day}", user.id))

    def test_viewer_refused(self):
        self.assertEqual(self._refusal(self.viewer, RecordAttestation("G1", "2024-05-01")).envelope, FORBIDDEN)

    def test_herd_as_code_id_object_or_row(self):
        for day, herd in enumerate(("G1", self.herds[0].id, {"herd": "G1"}, self.herds[0]), start=1):
            with self.subTest(herd=repr(herd)):  # a str: pytest-xdist cannot serialize a model
                self._run(self.owner, RecordAttestation(herd, f"2024-05-0{day}"))
                self.assertEqual(self._newest()[:3], ("ATTESTATION", "G1", f"2024-05-0{day}"))

    def test_date_before_latest_row_conflicts(self):
        """IR-33: the writer's 409, raised from apply."""
        refusal = self._refusal(self.owner, RecordAttestation("G1", "2020-01-01"), error=HerdTrackingConflict)
        self.assertEqual(refusal.status, 409)
        self.assertEqual(self._newest()[0], "BIRTH")

    def test_bad_date_before_unknown_herd(self):
        """validate_date's ValueError goes on (the adapter's "Kunde inte uppdatera individ."), before the lookup."""
        refusal = self._refusal(self.owner, RecordAttestation("Q9", "31/12"), error=ValueError)
        self.assertNotIsInstance(refusal, HerdTrackingError)

    def test_other_herd_is_not_an_attestation(self):
        """The caller picks the kind against the holder (IR-31): another herd is a TransferIndividual."""
        self._refusal(self.owner, RecordAttestation("G2", "2024-05-01"), error=AssertionError)
        self.assertEqual(self._newest()[0], "BIRTH")

    def test_without_active_row_the_stored_origin_holds(self):
        """IR-31: no active row, so the stored origin herd is the holder."""
        ind = db.Individual.create(origin_herd=self.herds[0], breeding=self.breeding[0], number="G1-2130")
        self._run(self.owner, RecordAttestation("G1", "2024-05-01"), ind=ind)
        self.assertEqual(self._newest(ind)[:2], ("ATTESTATION", "G1"))


SALE_REFUSED = "Du får inte sälja eller flytta individen till den besättningen."
GENEBANK_ADMIN_ONLY = "Bara administratör kan flytta en individ till en annan genbank."


class TestTransferIndividual(IndividualTest):
    WEIGHTS = [{"date": "2024-01-01", "weight": 2.5}]

    def _transfers(self, ind=None):
        rows = db.HerdTracking.select().where(
            db.HerdTracking.individual == (ind or self.ind).id,
            db.HerdTracking.kind == "TRANSFER",
            db.ht_not_voided(),
        )
        return [(r.herd.herd, r.notes) for r in rows.order_by(db.HerdTracking.id)]

    def _forbidden(self, user, herd, message, **kwargs):
        refusal = self._refusal(user, TransferIndividual(herd, "2021-06-01", **kwargs), error=HerdTrackingForbidden)
        self.assertEqual((refusal.status, refusal.detail), (403, message))
        self.assertEqual(self._transfers(), [])

    def test_owner_sells_within_genebank(self):
        self._run(self.owner, TransferIndividual("G2", "2021-06-01"))
        self.assertEqual(self._transfers(), [("G2", None)])

    def test_editors_move_within_genebank(self):
        for user, ind in ((self.admin, self.individuals[3]), (self.manager, self.individuals[0])):
            with self.subTest(user=user.email):
                self._run(user, TransferIndividual("G2", "2021-06-01"), ind=ind)
                self.assertEqual(self._transfers(ind), [("G2", None)])

    def test_caretaker_refused_403(self):
        """A caretaker's grant never sells or moves."""
        self._forbidden(self._caretaker(), "G2", SALE_REFUSED)

    def test_viewer_refused(self):
        self.assertEqual(self._refusal(self.viewer, TransferIndividual("G2", "2021-06-01")).envelope, FORBIDDEN)

    def test_owner_refused_cross_genebank_403(self):
        self._forbidden(self.owner, "M3", GENEBANK_ADMIN_ONLY)

    def test_manager_refused_cross_genebank_403(self):
        self._forbidden(self.manager, "M3", GENEBANK_ADMIN_ONLY)

    def test_caretaker_cross_genebank_gets_sale_refusal(self):
        """IR-52: the right to sell is asked before the genebank."""
        self._forbidden(self._caretaker(), "M3", SALE_REFUSED)

    def test_admin_moves_cross_genebank_with_reason(self):
        """IR-54: the cleaned reason is the TRANSFER row's note, and the change is logged on herdbook.da."""
        admin = self._name(self.admin)
        with self.assertLogs("herdbook.da", level="WARNING") as logs:
            self._run(admin, TransferIndividual("M3", "2021-06-01", reason="  Felregistrerad  "))
        self.assertEqual(self._transfers(), [("M3", "Felregistrerad")])
        self.assertEqual(
            logs.output,
            [
                "WARNING:herdbook.da:Genebank change by admin admin: G1-2112 from Gotland (G1) to Mellerud (M3): "
                "Felregistrerad"
            ],
        )

    def test_admin_cross_genebank_without_reason_400(self):
        refusal = self._refusal(self.admin, TransferIndividual("M3", "2021-06-01"), error=HerdTrackingInvalid)
        self.assertEqual((refusal.status, refusal.detail), (400, "Ange en anledning."))
        self.assertEqual(self._transfers(), [])

    def test_owner_refused_from_outside_genebank(self):
        """The owner of GX1 has no Entry there: the shared guard refuses before apply; a manager moves it back."""
        owner = self._outside_owner()
        self.assertEqual(self._refusal(owner, TransferIndividual("G1", "2022-06-01")).envelope, FORBIDDEN)
        self._run(self.manager, TransferIndividual("G1", "2022-06-01"))
        self.assertEqual(self._transfers(), [("GX1", None), ("G1", None)])

    def test_integer_herd_id_cannot_bypass_genebank_check(self):
        """The check sees the herd the writer resolves (code or id)."""
        self._forbidden(self.owner, self.herds[2].id, GENEBANK_ADMIN_ONLY)

    def test_caretaker_unknown_herd_is_invalid_not_forbidden(self):
        """IR-52: the target is resolved before the right to sell is asked."""
        refusal = self._refusal(self._caretaker(), TransferIndividual("Q9", "2021-06-01"), error=HerdTrackingInvalid)
        self.assertEqual((refusal.status, refusal.detail), (400, "Okänd besättning: Q9."))

    def test_refusal_rolls_back_weights(self):
        """IR-32: the measurements are written before the refusal and roll back with it."""
        commands = (SetMeasurements(weights=self.WEIGHTS), TransferIndividual("G2", "2021-06-01"))
        self._refusal(self._caretaker(), *commands, error=HerdTrackingForbidden)
        self.assertFalse(db.Weight.select().where(db.Weight.individual == self.ind.id).exists())


class TestAssignPaperCertificate(IndividualTest):
    MANAGERS_ONLY = error("Bara managers kan uppdatera certificate")

    def test_owner_sets_first_paper_certificate(self):
        self._run(self.owner, AssignPaperCertificate("P1"))
        self.assertEqual(self._certs(), ("P1", None))

    def test_caretaker_sets_paper_certificate_on_uncertified(self):
        self._run(self._caretaker(), AssignPaperCertificate("P1"))
        self.assertEqual(self._certs(), ("P1", None))

    def test_owner_refused_on_certified(self):
        ind = self.individuals[0]
        for user in (self.owner, self._caretaker()):
            with self.subTest(user=user.email):
                refusal = self._refusal(user, AssignPaperCertificate("77"), ind=ind)
                self.assertEqual(refusal.envelope, self.MANAGERS_ONLY)
                self.assertEqual(self._certs(ind), ("12", None))

    def test_manager_changes_certified(self):
        self._run(self.manager, AssignPaperCertificate("77"), ind=self.individuals[0])
        self.assertEqual(self._certs(self.individuals[0]), ("77", None))

    def test_admin_changes_certified(self):
        self._run(self.admin, AssignPaperCertificate("78"), ind=self.individuals[0])
        self.assertEqual(self._certs(self.individuals[0]), ("78", None))

    def test_null_is_refused_or_nothing(self):
        """IR-40: null asks the policy like any value, and a manager's null writes nothing."""
        ind = self.individuals[0]
        self.assertEqual(self._refusal(self.owner, AssignPaperCertificate(None), ind=ind).envelope, self.MANAGERS_ONLY)
        self._run(self.manager, AssignPaperCertificate(None), ind=ind)
        self.assertEqual(self._certs(ind), ("12", None))

    def test_replaces_digital_certificate_with_csv_lines(self):
        """IR-20: the digital number is cleared and logged, then the paper number."""
        db.Individual.update(digital_certificate=100000).where(db.Individual.id == self.ind.id).execute()
        with self.assertLogs("Gotland_update", level="INFO") as logs:
            self._run(self._name(self.manager), AssignPaperCertificate("P1"))
        self.assertEqual(
            logs.output,
            [
                "INFO:Gotland_update:man,G1-2112,digital_certificate,100000,'None',",
                "INFO:Gotland_update:man,G1-2112,certificate,None,P1,",
            ],
        )
        self.assertEqual(self._certs(), ("P1", None))

    def test_duplicate_certificate(self):
        refusal = self._refusal(self.owner, AssignPaperCertificate("13"))
        self.assertEqual(refusal.envelope, error("Individual certificate already exists"))
        self.assertEqual(self._certs(), (None, None))

    def test_numeric_echo_is_a_collision(self):
        """IR-49: compared raw and searched with the value, as today, so 12 finds the rabbit's own "12"."""
        refusal = self._refusal(self.manager, AssignPaperCertificate(12), ind=self.individuals[0])
        self.assertEqual(refusal.envelope, error("Individual certificate already exists"))

    def test_quota_exceeded(self):
        kit = self._kit(self._roster_litter(1, alive=1, certified=1))
        refusal = self._refusal(self.owner, AssignPaperCertificate("P2"), ind=kit)
        self.assertEqual(refusal.envelope, error("certificate_quota_exceeded"))
        self.assertEqual(self._certs(kit), (None, None))

    def test_litter_size6w_required(self):
        kit = self._kit(self._roster_litter(None))
        refusal = self._refusal(self.owner, AssignPaperCertificate("P2"), ind=kit)
        self.assertEqual(refusal.envelope, error("litter_size6w_required"))

    def test_roster_alive_exceeds_6w_has_must_mark_dead(self):
        kit = self._kit(self._roster_litter(2, alive=3))
        refusal = self._refusal(self.owner, AssignPaperCertificate("P2"), ind=kit)
        self.assertEqual(refusal.envelope, {**error("roster_alive_exceeds_6w"), "must_mark_dead": 1})
        self.assertEqual(self._certs(kit), (None, None))

    def test_json_zero_is_a_certificate(self):
        """IR-55: 0 is stored as "0", a first certificate that takes the litter rules."""
        kit = self._kit(self._roster_litter(None))
        refusal = self._refusal(self.owner, AssignPaperCertificate(0), ind=kit)
        self.assertEqual(refusal.envelope, error("litter_size6w_required"))
        self._run(self.owner, AssignPaperCertificate(0))
        self.assertEqual(self._certs(), ("0", None))

    def test_string_none_is_not_null(self):
        """The string "None" is a paper number, so on a digitally certified rabbit it is a manager's change."""
        db.Individual.update(digital_certificate=100001).where(db.Individual.id == self.ind.id).execute()
        self.assertEqual(self._refusal(self.owner, AssignPaperCertificate("None")).envelope, self.MANAGERS_ONLY)
        self.assertEqual(self._certs(), (None, 100001))

    def test_quota_uses_litter_after_move_into_full_litter(self):
        full = self._roster_litter(1, alive=1, certified=1)
        commands = [MoveToLitter(full.id), AssignPaperCertificate("P2")]
        refusal = self._refusal(self.owner, *commands, target_breeding=full.id)
        self.assertEqual(refusal.envelope, error("certificate_quota_exceeded"))
        self.assertEqual(self._stored().breeding_id, self.breeding[0].id)

    def test_quota_uses_litter_after_move_out_of_full_litter(self):
        kit = self._kit(self._roster_litter(1, alive=1, certified=1))
        # Same birth date, so the move renames nothing; another father, as litters are unique per parents and date.
        roomy = db.Breeding.create(
            breed_date=datetime(2024, 12, 10),
            birth_date=datetime(2025, 1, 10),
            litter_number=2,
            litter_size=3,
            litter_size6w=3,
            mother=self.parents[0],
            father=self.individuals[1],
            breeding_herd_id=self.herds[0],
        )
        # With the number of the litter it moves into: a first certificate needs a matching number.
        commands = [MoveToLitter(roomy.id), RenameIndividual("G1-2521"), AssignPaperCertificate("P2")]
        self._run(self.owner, *commands, ind=kit, target_breeding=roomy.id)
        self.assertEqual((self._certs(kit), self._stored(kit).breeding_id), (("P2", None), roomy.id))

    def test_lock_target_without_a_move_keeps_the_stored_litter(self):
        """The quota is the litter the rabbit is in after the request, not one that was only locked."""
        kit = self._kit(self._roster_litter(1, alive=1, certified=1))
        refusal = self._refusal(self.owner, AssignPaperCertificate("P2"), ind=kit, target_breeding=self.breeding[0].id)
        self.assertEqual(refusal.envelope, error("certificate_quota_exceeded"))


class TestRenameIndividual(IndividualTest):
    MANAGERS_ONLY = error("Bara managers kan uppdatera number")

    def _number(self, ind=None):
        return self._stored(ind).number

    def test_owner_renames_uncertified(self):
        with self.assertLogs("Gotland_update", level="INFO") as logs:
            self._run(self._name(self.owner), RenameIndividual("G1-2119"))
        self.assertEqual(logs.output, ["INFO:Gotland_update:owner,G1-2112,new_number,G1-2112,G1-2119,"])
        self.assertEqual(self._number(), "G1-2119")

    def test_caretaker_renames_uncertified(self):
        self._run(self._caretaker(), RenameIndividual("G1-2119"))
        self.assertEqual(self._number(), "G1-2119")

    def test_owner_refused_on_certified(self):
        """A certified rabbit's number is a manager's change."""
        ind = self.individuals[0]
        for user in (self.owner, self._caretaker()):
            with self.subTest(user=user.email):
                refusal = self._refusal(user, RenameIndividual("G1-2119"), ind=ind)
                self.assertEqual(refusal.envelope, self.MANAGERS_ONLY)
                self.assertEqual(self._number(ind), "G1-2111")

    def test_editors_rename_certified(self):
        ind = self.individuals[0]
        for user, number in ((self.admin, "G1-2118"), (self.manager, "G1-2117")):
            with self.subTest(user=user.email):
                self._run(user, RenameIndividual(number), ind=ind)
                self.assertEqual(self._number(ind), number)

    def test_number_taken(self):
        """IR-15, also before the managers-only refusal on a certified rabbit."""
        for ind in (self.individuals[3], self.individuals[0]):
            with self.subTest(number=ind.number):
                refusal = self._refusal(self.owner, RenameIndividual("G2-2011"), ind=ind)
                self.assertEqual(refusal.envelope, error("Individual number already exists"))
                self.assertEqual(self._number(ind), ind.number)

    def test_assets_follow_the_number(self):
        """IR-23: without an outer transaction the certificate and the photo are at the new number on return."""
        db.Individual.update(digital_certificate=100000).where(db.Individual.id == self.ind.id).execute()
        objects = {"G1-2112/certificate.pdf": b"cert"}
        with (
            tempfile.TemporaryDirectory() as uploads,
            mock.patch.dict(os.environ, {"UPLOAD_FOLDER": uploads}),
            mock.patch("utils.s3.get_s3_client", return_value=FakeS3(objects)),
        ):
            photos = os.path.join(uploads, "kaniner")
            os.makedirs(photos)
            with open(os.path.join(photos, "G1-2112.jpg"), "wb") as photo:
                photo.write(b"photo")
            self._run(self.manager, RenameIndividual("G1-2119"))
            self.assertEqual(os.listdir(photos), ["G1-2119.jpg"])
        self.assertEqual(objects, {"G1-2119/certificate.pdf": b"cert"})
        self.assertEqual(self._number(), "G1-2119")

    def test_rename_and_birth_year_fix_moves_from_original_number(self):
        """Two number changes in one call, the rename and then MoveToLitter's birth-year fix: the assets move
        from the stored number to the final one, as in test_renumber_assets.py's legacy rename with a move."""
        newer, older = self._litter(datetime(2026, 2, 1)), self._litter(datetime(2025, 6, 1))
        kit = db.Individual.create(
            origin_herd=self.herds[0], breeding=newer, number="G1-2621", digital_certificate=100000
        )
        ht_row("BIRTH", herd=self.herds[0], individual=kit, herd_tracking_date=datetime(2026, 2, 1))
        objects = {"G1-2621/certificate.pdf": b"cert"}
        with (
            tempfile.TemporaryDirectory() as uploads,
            mock.patch.dict(os.environ, {"UPLOAD_FOLDER": uploads}),
            mock.patch("utils.s3.get_s3_client", return_value=FakeS3(objects)),
        ):
            photos = os.path.join(uploads, "kaniner")
            os.makedirs(photos)
            with open(os.path.join(photos, "G1-2621.jpg"), "wb") as photo:
                photo.write(b"photo")
            commands = (RenameIndividual("G1-2629"), MoveToLitter(older.id))
            self._run(self.manager, *commands, ind=kit, target_breeding=older.id)
            self.assertEqual(os.listdir(photos), ["G1-2529.jpg"])
        self.assertEqual(objects, {"G1-2529/certificate.pdf": b"cert"})
        self.assertEqual(self._number(kit), "G1-2529")


class TestMoveToLitter(IndividualTest):
    MANAGERS_ONLY = error("Bara managers kan uppdatera breeding")

    def _move(self, user, litter, ind=None):
        return self._run(user, MoveToLitter(litter.id), ind=ind, target_breeding=litter.id)

    def _breeding(self, ind=None):
        return self._stored(ind).breeding_id

    def test_owner_moves_within_own_herd(self):
        litter = self._litter()
        self._move(self.owner, litter)
        self.assertEqual((self._breeding(), self._stored().number), (litter.id, "G1-2112"))
        self.assertEqual(self._births(), [("G1", "2021-02-01")])

    def test_csv_line(self):
        """form_to_individual's field line, with the litters' ids."""
        litter = self._litter()
        with self.assertLogs("Gotland_update", level="INFO") as logs:
            self._move(self._name(self.owner), litter)
        self.assertEqual(
            logs.output, [f"INFO:Gotland_update:owner,G1-2112,breeding,{self.breeding[0].id},{litter.id},"]
        )

    def test_caretaker_moves_uncertified(self):
        litter = self._litter()
        self._move(self._caretaker(), litter)
        self.assertEqual(self._breeding(), litter.id)

    def test_owner_refused_on_certified(self):
        """IR-19: a certified rabbit's litter is a manager's change."""
        ind, litter = self.individuals[0], self._litter()
        for user in (self.owner, self._caretaker()):
            with self.subTest(user=user.email):
                self.assertEqual(
                    self._refusal(user, MoveToLitter(litter.id), ind=ind, target_breeding=litter.id).envelope,
                    self.MANAGERS_ONLY,
                )
                self.assertEqual(self._breeding(ind), self.breeding[0].id)

    def test_editors_move_certified(self):
        ind = self.individuals[0]
        for user in (self.admin, self.manager):
            with self.subTest(user=user.email):
                litter = self._litter()
                self._move(user, litter, ind=ind)
                self.assertEqual(self._breeding(ind), litter.id)

    def test_unknown_litter(self):
        refusal = self._refusal(self.owner, MoveToLitter(9999), target_breeding=9999)
        self.assertEqual(refusal.envelope, error("Unknown breeding event: '9999''"))

    def test_target_breeding_is_the_litter_moved_to(self):
        """The caller locks the litter it moves to: execute's target_breeding is the command's."""
        self._refusal(self.owner, MoveToLitter(self._litter().id), error=AssertionError)
        self.assertEqual(self._breeding(), self.breeding[0].id)

    def test_refused_into_foreign_genebank(self):
        """Not into a litter of another genebank, not even for an admin."""
        refusal = self._refusal(self.admin, MoveToLitter(self.breeding[1].id), target_breeding=self.breeding[1].id)
        self.assertEqual(refusal.envelope, FORBIDDEN)

    def test_refused_into_other_owners_litter(self):
        """IR-24: into a herd the user may edit (G2 is not the owner's)."""
        refusal = self._refusal(self.owner, MoveToLitter(self.breeding[2].id), target_breeding=self.breeding[2].id)
        self.assertEqual(refusal.envelope, FORBIDDEN)
        self.assertEqual(self._breeding(), self.breeding[0].id)

    def test_cycle_refused(self):
        """IR-25: the rabbit's own litter as a mother."""
        litter = self._litter(mother=self.ind)
        refusal = self._refusal(self.owner, MoveToLitter(litter.id), target_breeding=litter.id)
        self.assertEqual(refusal.envelope, dict(CYCLE_PROBLEM))
        self.assertEqual(self._breeding(), self.breeding[0].id)

    def test_birth_year_change_renumbers(self):
        """IR-26: the BIRTH row moves to the litter's birth date, and the number gets its year."""
        litter = self._litter(birth=datetime(2022, 2, 1))
        self._move(self.owner, litter)
        self.assertEqual((self._breeding(), self._stored().number), (litter.id, "G1-2212"))
        self.assertEqual(self._births(), [("G1", "2022-02-01")])


class TestChangeOriginHerd(IndividualTest):
    SAME_GENEBANK_REFUSED = "Endast genbanksansvarig eller administratör kan ändra ursprungsbesättning."
    MOVED = "Kaninen har flyttats. Rätta besättningshistoriken innan ursprungsbesättningen byts till en annan genbank."

    def setUp(self):
        """self.kit = G1-2113: certified, alone in its G1 litter, with a BIRTH row (as in test_individual_sell_v2)."""
        super().setUp()
        self.single = self._litter(datetime(2021, 3, 1))
        self.kit = db.Individual.create(
            origin_herd=self.herds[0], breeding=self.single, color=self.colors[0], certificate="99", number="G1-2113"
        )
        ht_row("BIRTH", herd=self.herds[0], individual=self.kit, herd_tracking_date=datetime(2021, 3, 1))

    def _change(self, user, code, *more, reason=None, ind=None, **kwargs):
        return self._run(user, ChangeOriginHerd(code, reason), *more, ind=ind or self.kit, **kwargs)

    def _refused(self, user, code, error, reason=None, ind=None):
        return self._refusal(user, ChangeOriginHerd(code, reason), ind=ind or self.kit, error=error)

    def _origin(self, ind=None):
        return self._stored(ind or self.kit).origin_herd.herd

    def _birth_history(self, ind=None):
        rows = db.HerdTracking.select().where(
            db.HerdTracking.individual == (ind or self.kit).id, db.HerdTracking.kind == "BIRTH"
        )
        return [(r.herd.herd, r.voided_reason) for r in rows.order_by(db.HerdTracking.id)]

    def test_manager_changes_origin(self):
        with self.assertLogs("Gotland_update", level="INFO") as logs:
            self._change(self._name(self.manager), "G2")
        self.assertEqual(
            logs.output,
            [
                f"INFO:Gotland_update:man,G1-2113,origin_herd,{self.herds[0].id},{self.herds[1].id},",
                "INFO:Gotland_update:man,G1-2113,new_origin_herd,G1,G2,",
            ],
        )
        self.assertEqual(self._origin(), "G2")
        self.assertEqual(self._birth_history(), [("G1", BIRTH_HERD_CHANGED_REASON), ("G2", None)])

    def test_admin_changes_origin(self):
        self._change(self.admin, "G2")
        self.assertEqual(self._origin(), "G2")

    def test_owner_refused_403(self):
        refusal = self._refused(self.owner, "G2", HerdTrackingForbidden)
        self.assertEqual((refusal.status, refusal.detail), (403, self.SAME_GENEBANK_REFUSED))
        self.assertEqual(self._birth_history(), [("G1", None)])

    def test_current_manager_refused_403(self):
        """MANAGER_ORIGIN, not the manager of the herd that holds the rabbit (IR-28)."""
        m4 = db.Herd.create(genebank=self.genebanks[1], herd="M4", herd_name="Mellerudherd4")
        ind = db.Individual.create(
            origin_herd=self.herds[2], breeding=self._litter(herd=self.herds[2]), number="M3-2101"
        )
        ht_row("BIRTH", herd=self.herds[2], individual=ind, herd_tracking_date=datetime(2021, 2, 1))
        ht_row(
            "TRANSFER",
            from_herd=self.herds[2],
            herd=self.herds[0],
            individual=ind,
            herd_tracking_date=datetime(2021, 6, 1),
        )
        refusal = self._refused(self.manager, m4.herd, HerdTrackingForbidden, ind=ind)
        self.assertEqual(refusal.detail, self.SAME_GENEBANK_REFUSED)
        self.assertEqual(self._origin(ind), "M3")

    def test_manager_cross_genebank_403(self):
        refusal = self._refused(self.manager, "M3", HerdTrackingForbidden, reason="Felregistrerad")
        self.assertEqual((refusal.status, refusal.detail), (403, GENEBANK_ADMIN_ONLY))
        self.assertEqual(self._origin(), "G1")

    def test_admin_cross_genebank_with_reason(self):
        """IR-29, IR-54: the cleaned reason ends the replaced BIRTH row's voided_reason."""
        with self.assertLogs("herdbook.da", level="WARNING") as logs:
            self._change(self._name(self.admin), "M3", reason=" Felregistrerad ")
        self.assertEqual(
            logs.output,
            [
                "WARNING:herdbook.da:Genebank change by admin admin: G1-2113 from Gotland (G1) to Mellerud (M3): "
                "Felregistrerad"
            ],
        )
        self.assertEqual(self._origin(), "M3")
        replaced = f"{BIRTH_HERD_CHANGED_REASON}: Felregistrerad"
        self.assertEqual(self._birth_history(), [("G1", replaced), ("M3", None)])

    def test_admin_cross_genebank_without_reason_400(self):
        refusal = self._refused(self.admin, "M3", HerdTrackingInvalid)
        self.assertEqual((refusal.status, refusal.detail), (400, "Ange en anledning."))
        self.assertEqual(self._origin(), "G1")

    def test_moved_rabbit_cross_genebank_409(self):
        """IR-56: after the save and the CSV line, before the BIRTH row is replaced."""
        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[1],
            individual=self.kit,
            herd_tracking_date=datetime(2021, 6, 1),
        )
        with self.assertLogs("Gotland_update", level="INFO") as logs:
            refusal = self._refused(self._name(self.admin), "M3", HerdTrackingConflict, reason="Felregistrerad")
        self.assertEqual((refusal.status, refusal.detail), (409, self.MOVED))
        self.assertEqual(
            logs.output,
            [
                f"INFO:Gotland_update:admin,G1-2113,origin_herd,{self.herds[0].id},{self.herds[2].id},",
                "INFO:Gotland_update:admin,G1-2113,new_origin_herd,G1,M3,",
            ],
        )
        self.assertEqual((self._origin(), self._birth_history()), ("G1", [("G1", None)]))

    def test_move_and_cross_genebank_origin_in_one_request_409(self):
        """IR-56 counts the TRANSFER this request wrote: after_save runs after every apply."""
        sale = TransferIndividual("G2", "2021-06-01")
        with self.assertRaises(HerdTrackingConflict):
            self._change(self.admin, "M3", sale, reason="Felregistrerad")
        transfers = db.HerdTracking.select().where(
            db.HerdTracking.individual == self.kit.id, db.HerdTracking.kind == "TRANSFER"
        )
        self.assertEqual((self._origin(), transfers.count()), ("G1", 0))

    def test_single_kit_litter_follows(self):
        self._change(self.manager, "G2")
        self.assertEqual(db.Breeding.get_by_id(self.single.id).breeding_herd_id.herd, "G2")

    def test_litter_with_more_kits_refused(self):
        """IR-27: G1-2112's litter also has G1-2111."""
        refusal = self._refused(self.manager, "G2", IndividualRefused, ind=self.ind)
        self.assertEqual(refusal.envelope, error("origin_herd more inds"))

    def test_unknown_origin_herd_is_raw(self):
        """IR-27: a ValueError tagged with its stage, which the adapter lets through (legacy 500, v2 400)."""
        refusal = self._refused(self.admin, "Q9", ValueError)
        self.assertEqual((str(refusal), refusal.individual_stage), ("Unknown origin herd: 'Q9''", Stage.ORIGIN_PRE))

    def test_origin_change_with_move_into_single_kit_litter(self):
        """Counted in the litter after the request: from a litter of two into one with a single kit, accepted
        as today; that litter then has two kits and keeps its herd."""
        target = self._litter()
        db.Individual.create(origin_herd=self.herds[0], breeding=target, number="G1-2131")
        self._change(self.manager, "G2", MoveToLitter(target.id), ind=self.ind, target_breeding=target.id)
        self.assertEqual((self._origin(self.ind), self._stored().breeding_id), ("G2", target.id))
        self.assertEqual(self._births(), [("G2", "2021-02-01")])
        self.assertEqual(db.Breeding.get_by_id(target.id).breeding_herd_id.herd, "G1")

    def test_origin_manager_without_edit_right_refused(self):
        """The manager of the origin's genebank, not of the holder's (M3): no Entry, the shared guard refuses."""
        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[2],
            individual=self.kit,
            herd_tracking_date=datetime(2021, 6, 1),
        )
        self.assertEqual(self._refused(self.manager, "G2", IndividualRefused).envelope, FORBIDDEN)
        self.assertEqual(self._origin(), "G1")


class TestIssueDigitalCertificate(IndividualTest):
    def test_issue_assigns_next_number_and_clears_paper(self):
        """IR-20, IR-21: MAX+1 (100000 when there is none), and the paper number is cleared and logged."""
        ind = self.individuals[0]  # G1-2111, paper "12"
        with self.assertLogs("Gotland_update", level="INFO") as logs:
            self._run(self._name(self.owner), IssueDigitalCertificate(), ind=ind)
        self.assertEqual(
            logs.output,
            [
                "INFO:Gotland_update:owner,G1-2111,certificate,12,'None',",
                "INFO:Gotland_update:owner,G1-2111,digital_certificate,None,100000,",
            ],
        )
        self.assertEqual(self._certs(ind), (None, 100000))

    def test_two_issues_in_sequence_get_consecutive_numbers(self):
        for ind, number in ((self.individuals[3], 100000), (self.individuals[1], 100001)):
            self._run(self.manager, IssueDigitalCertificate(), ind=ind)
            self.assertEqual(self._certs(ind), (None, number))

    def test_editors_and_caretaker_issue(self):
        for user, ind in ((self.admin, self.individuals[3]), (self._caretaker(), self.individuals[0])):
            with self.subTest(user=user.email):
                self._run(user, IssueDigitalCertificate(), ind=ind)
                self.assertIsNotNone(self._certs(ind)[1])

    def test_viewer_refused(self):
        self.assertEqual(self._refusal(self.viewer, IssueDigitalCertificate()).envelope, FORBIDDEN)
        self.assertEqual(self._certs(), (None, None))

    def test_first_certificate_takes_the_litter_rules(self):
        """IR-22, in the litter after the request."""
        kit = self._kit(self._roster_litter(None))
        refusal = self._refusal(self.owner, IssueDigitalCertificate(), ind=kit)
        self.assertEqual(refusal.envelope, error("litter_size6w_required"))
        self.assertEqual(self._certs(kit), (None, None))

    def test_roster_alive_exceeds_6w_has_must_mark_dead(self):
        kit = self._kit(self._roster_litter(2, alive=3))
        refusal = self._refusal(self.owner, IssueDigitalCertificate(), ind=kit)
        self.assertEqual(refusal.envelope, {**error("roster_alive_exceeds_6w"), "must_mark_dead": 1})
        self.assertEqual(self._certs(kit), (None, None))


UPDATED = {"status": "success", "message": "Individual Updated", "digital_certificate": None}


class TestLegacyAdapter(IndividualTest, FlaskTest):
    """update_individual through translate (utils/individual_legacy.py): today's answers, in today's order."""

    def _translated(self, form, user=None, ind=None, **kwargs):
        """translate's commands for `form`, built under the lock as update_individual builds them; none runs."""
        commands = []

        def capture(ctx):
            commands.extend(translate(form, ctx, **kwargs))
            return []

        execute(user or self.owner, (ind or self.ind).id, capture)
        return commands

    def _names(self, commands):
        return [type(command).__name__ for command in commands]

    def _body(self, ind=None, **fields):
        ind = ind or self.ind
        return {"id": ind.id, "number": ind.number, "herd": "G1", **fields}

    def _client(self, user):
        client = APP.test_client(use_cookies=True)
        self.login(client, user)
        return client

    def test_adapter_order(self):
        body = self._body(
            number="G1-2119",
            certificate="P1",
            origin_herd={"herd": "G2"},
            breeding=self._litter().id,
            death_date="2024-05-01",
            notes="ny",
            castration_date=None,
            weights=[{"date": "2024-01-01", "weight": 2.5}],
            selling_date="2024-06-01",
        )
        commands = self._translated(body, self.admin, issue_digital=True, clear_nulls=True)
        expected = [
            "LegacyFormChecks",
            "RenameIndividual",
            "AssignPaperCertificate",
            "ChangeOriginHerd",
            "MoveToLitter",
            "IssueDigitalCertificate",
            "RecordDeath",
            "EditDescription",
            "ClearFields",
            "SetMeasurements",
            "LegacyHerdEvent",
        ]
        self.assertEqual(self._names(commands), expected)

    def test_report_to_other_herd_is_a_transfer(self):
        """Review Focus 3: a yearly report to a herd other than the holder is a move, which needs the right to sell."""
        body = self._body(herd="G2", yearly_report_date="2021-06-01")
        refused = da.update_individual(dict(body), self._caretaker().uuid)
        self.assertEqual(refused, {**error(SALE_REFUSED), "problem_status": 403, "title": "Åtkomst nekad", "rows": []})
        self.assertEqual(da.update_individual(dict(body), self.owner.uuid), UPDATED)
        rows = db.HerdTracking.select().where(db.HerdTracking.individual == self.ind.id, db.ht_not_voided())
        newest = rows.order_by(db.HerdTracking.id.desc()).first()
        self.assertEqual((newest.kind, newest.herd.herd), ("TRANSFER", "G2"))

    def test_echo_produces_no_writes(self):
        """The GET object back (L1): no move, rename or certificate. The computed is_active differs from the stored
        one (IR-11); the colour goes along as it resolves by name, here to the stored one; the lists are the stored."""
        ind = self.individuals[0]
        body = self._client(self.owner).get(f"/api/individual/{ind.number}").get_json()
        commands = self._translated(body, ind=ind)
        self.assertEqual(self._names(commands), ["LegacyFormChecks", "EditDescription", "SetMeasurements"])
        self.assertEqual(commands[1].changes, {"color": "bleighe", "is_active": False})

    def test_typed_refusal_in_raw_stage_is_an_envelope(self):
        """A refusal in a stage up to HERD is an envelope (200); only unexpected errors there go on raw."""
        response = self._client(self.owner).patch("/api/individual", json=self._body(number="G2-2011"))
        self.assertEqual((response.status_code, response.get_json()), (200, error("Individual number already exists")))

    def test_raw_errors_keep_their_http_status(self):
        """IR-08, IR-27: errors of today's checks before the lock go on raw, so legacy answers 500 and v2 400."""
        client = self._client(self.admin)
        legacy = client.patch("/api/individual", json={"id": self.ind.id, "number": self.ind.number})
        self.assertEqual(legacy.status_code, 500)
        v2 = client.patch(f"/api/individual/{self.ind.number}", json={"origin_herd": {"herd": "Q9"}})
        self.assertEqual((v2.status_code, v2.get_json()["title"]), (400, "Update failed"))

    def test_id_of_one_number_of_another_is_a_duplicate(self):
        """IR-15 before IR-06: another rabbit's number is a taken number, and neither rabbit changes."""
        other = self.individuals[0]
        response = self._client(self.owner).patch("/api/individual", json=self._body(number=other.number))
        self.assertEqual((response.status_code, response.get_json()), (200, error("Individual number already exists")))
        self.assertEqual((self._stored().number, self._stored(other).number), ("G1-2112", "G1-2111"))

    def test_numeric_certificate_echo_is_a_collision(self):
        """IR-49: 12 for the stored "12" is no AssignPaperCertificate, but LegacyFormChecks compares it raw."""
        ind = self.individuals[0]
        body = self._body(ind, certificate=12)
        self.assertNotIn("AssignPaperCertificate", self._names(self._translated(body, self.manager, ind=ind)))
        self.assertEqual(da.update_individual(body, self.manager.uuid), error("Individual certificate already exists"))

    def test_null_breeding_with_new_origin_is_unknown_breeding_event(self):
        """IR-27 counts the kits of breeding null, which passes with exactly one rabbit without a litter. The
        stored litter has two kits: ChangeOriginHerd's own count must not answer before IR-43."""
        db.Individual.create(origin_herd=self.herds[0], number="G1-2120")
        body = self._body(origin_herd={"herd": "G2"}, breeding=None)
        self.assertEqual(da.update_individual(body, self.manager.uuid), error("Unknown breeding event: 'None''"))

    def test_herd_event_csv_line(self):
        """Today's line: the key the date came from (selling_date when set), the holder before the request, the
        herd as sent or its object's code, and the parsed date."""
        owner = self._name(self.owner)
        cases = (
            (
                {"herd": {"herd": "G1"}, "selling_date": "2021-06-01", "yearly_report_date": "2021-07-01"},
                "selling_date,G1,G1",
            ),
            ({"herd": "G2", "selling_date": None, "yearly_report_date": "2021-07-01"}, "yearly_report_date,G1,G2"),
        )
        for fields, line in cases:
            with self.subTest(line=line), self.assertLogs("Gotland_update", level="INFO") as logs:
                self.assertEqual(da.update_individual(self._body(**fields), owner.uuid), UPDATED)
            date = fields["selling_date"] or fields["yearly_report_date"]
            self.assertEqual(logs.output, [f"INFO:Gotland_update:owner,G1-2112,{line},{date} 00:00:00"])

    def test_legacy_rename_moves_the_assets_once(self):
        """IR-23: one record of the move, finished on return although both update_individual and execute finish."""
        db.Individual.update(digital_certificate=100000).where(db.Individual.id == self.ind.id).execute()
        objects = {"G1-2112/certificate.pdf": b"cert"}
        with (
            tempfile.TemporaryDirectory() as uploads,
            mock.patch.dict(os.environ, {"UPLOAD_FOLDER": uploads}),
            mock.patch("utils.s3.get_s3_client", return_value=FakeS3(objects)),
            mock.patch.object(number_assets, "record", wraps=number_assets.record) as record,
        ):
            photos = os.path.join(uploads, "kaniner")
            os.makedirs(photos)
            with open(os.path.join(photos, "G1-2112.jpg"), "wb") as photo:
                photo.write(b"photo")
            result = da.update_individual(self._body(number="G1-2119"), self.manager.uuid)
            self.assertEqual(os.listdir(photos), ["G1-2119.jpg"])
        self.assertEqual(result, {**UPDATED, "digital_certificate": 100000})
        record.assert_called_once_with(self.ind.id, "G1-2112", "G1-2119", True)
        self.assertEqual(objects, {"G1-2119/certificate.pdf": b"cert"})

    def test_new_behaviour_refused_request_logs_no_field_lines(self):
        """
        Pins NEW behaviour, not today's: Decision 2 in the plan, read as a fix. At 85b3e26 form_to_individual
        logged the field lines (here `notes`) before update_individual refused the cycle; the commands log in
        apply, which a refusal never reaches.
        """
        litter = db.Breeding.create(
            breed_date=datetime(2022, 1, 1),
            birth_date=datetime(2022, 2, 1),
            mother=self.ind,
            father=self.parents[1],
            litter_size=1,
            litter_size6w=1,
            breeding_herd_id=self.herds[0],
        )
        db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2301")
        notes = self._stored().notes
        client = self._client(self._name(self.owner))
        with self.assertNoLogs("Gotland_update", level="INFO"):
            response = client.patch("/api/individual", json=self._body(notes="ny", breeding=litter.id))
        self.assertEqual((response.get_json(), self._stored().notes), (dict(CYCLE_PROBLEM), notes))


class TestFormToIndividual(IndividualTest):
    """form_to_individual: add_individual's builder of a new rabbit, with the commands' lookups (POST)."""

    def _build(self, **fields):
        return da.form_to_individual({"number": "G1-9990", "herd": "G1", **fields}, self.owner)

    def test_create_sets_allowlisted_fields_only(self):
        individual = self._build(name="Nyss", voided=True, digital_certificate=100000)
        self.assertEqual((individual.name, individual.voided, individual.digital_certificate), ("Nyss", False, None))

    def test_create_does_not_save(self):
        individual = self._build(origin_herd={"herd": "G1"}, breeding=self.breeding[0].id, color="bleighe")
        self.assertIsNone(individual.id)
        self.assertEqual(
            (individual.origin_herd.herd, individual.breeding.id, individual.color.name),
            ("G1", self.breeding[0].id, "bleighe"),
        )
        self.assertFalse(db.Individual.select().where(db.Individual.number == "G1-9990").exists())

    def test_create_returns_existing_row(self):
        """IR-58: a rabbit that has the number comes back, and add_individual refuses it."""
        self.assertEqual(self._build(number=self.ind.number).id, self.ind.id)

    def test_create_unknown_color(self):
        with self.assertRaisesRegex(ValueError, r"^Unknown color: 'ultra-beige''$"):
            self._build(color="ultra-beige")

    def test_create_unknown_litter_and_parents(self):
        """The commands' messages, as add_individual's ValueError (IR-13)."""
        cases = (
            ({"breeding": 999999}, "Unknown breeding event: '999999''"),
            ({"mother": {"number": "X"}}, "Invalid parents"),
        )
        for fields, message in cases:
            with self.subTest(message=message), self.assertRaises(ValueError) as raised:
                self._build(**fields)
            self.assertEqual(f"{raised.exception}", message)

    def test_create_certificate_as_text(self):
        """IR-55: JSON 0 is the certificate "0"."""
        self.assertEqual(self._build(certificate=0).certificate, "0")

    def test_create_with_an_id_is_refused(self):
        """IR-06 holds on POST too: an id that is not the number's rabbit, none for a new number."""
        with self.assertRaisesRegex(ValueError, r"^Number can not be updated$"):
            self._build(id=self.ind.id)
