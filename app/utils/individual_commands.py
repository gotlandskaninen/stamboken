"""
Write commands on an individual (ADR-0015).

`execute` locks (Breeding → individual), re-reads the row under the lock, derives the user's
roles and the rabbit's state, and runs the commands' checks stage by stage, in the error order
of update_individual, before anything
is written. Errors are not mapped here: callers turn them into their responses.
data_access.py imports this module; this module never imports data_access.py.
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import IntEnum
from typing import ClassVar, Protocol

from peewee import DateField, fn

from utils import number_assets
from utils.database import DB_PROXY as DATABASE
from utils.database import (
    OUTSIDE_GENEBANK_HERDS,
    Bodyfat,
    Breeding,
    Color,
    Herd,
    HerdTracking,
    Individual,
    IndividualCommand,
    User,
    Weight,
    current_holder_row,
    ht_not_voided,
    lock_breedings,
    lock_individuals,
    validate_date,
)
from utils.herd_tracking import (
    BIRTH_DATE_CHANGED_REASON,
    BIRTH_HERD_CHANGED_REASON,
    CONTACT_MANAGER,
    HerdTrackingConflict,
    HerdTrackingError,
    HerdTrackingForbidden,
    HerdTrackingInvalid,
    HerdTrackingNotFound,
    record_herd_tracking,
    replace_birth_row,
    require_reason,
    resolve_herd,
    void_herd_tracking,
)
from utils.individual_number_v2 import (
    RosterAliveExceeds6w,
    conflict_extensions,
    litter_mismatch,
    number_check,
    parse_number,
    validate_first_certificate,
)
from utils.individual_policy import COMMAND_FIELDS, Role, State, allowed
from utils.pedigree_guard import CYCLE_PROBLEM, pedigree_cycle_error

logger = logging.getLogger("herdbook.da")  # the helpers moved from data_access keep their log name


class Stage(IntEnum):
    """One step per row of today's error order; checks run in this order."""

    NUMBER_UNIQUE = 1  # IR-15 (reads form["number"]: a KeyError goes on raw)
    CERT_UNIQUE = 2  # IR-16
    DIGITAL_ECHO = 3  # IR-17
    ORIGIN_PRE = 4  # IR-27 (unknown code and form["breeding"]: go on raw)
    HERD = 5  # IR-08 (form["herd"]: a KeyError goes on raw)
    REAUTH = 6  # IR-03 can_edit, then IR-05 voided (shared guards in the executor)
    MANAGER_ONLY = 7  # IR-18 number, IR-19 breeding
    ID_NUMBER = 8  # IR-06
    CERT_AUTH = 9  # IR-18 in admin_fields order: digital_certificate, then certificate
    BREEDING_EXISTS = 10  # IR-13 breeding (presence, null too)
    COLOR = 11  # IR-13 color
    ORIGIN_SHAPE = 12  # IR-41 origin_herd null or not an object
    PARENTS = 13  # IR-13 mother/father (presence, null too)
    DATES = 14  # IR-12, in FORM_WRITABLE_FIELDS order (death_date before castration_date)
    LITTER = 15  # IR-24
    CYCLE = 16  # IR-25
    QUOTA = 17  # IR-22, against the litter after the move
    ORIGIN_AUTH = 18  # IR-28, another genebank first (GenebankCorrection, IR-54)


RAW_UNTIL = Stage.HERD  # unexpected errors up to here are not mapped (today they come before the try)
MISSING = object()  # a key the form does not have


class IndividualRefused(Exception):
    """A typed refusal; `envelope` is the response body ({"status": "error", "message": …} unless given)."""

    def __init__(self, message: str | None = None, *, envelope: dict | None = None):
        self.envelope = envelope if envelope is not None else {"status": "error", "message": message}
        super().__init__(self.envelope.get("message"))


@dataclass
class WriteContext:
    user: User
    individual: Individual  # re-read under the lock; the commands write here
    stored: Individual  # the same row, re-read separately, never touched
    roles: frozenset[Role]
    state: State
    breeding_after: int | None  # the litter after the request; set before any check runs
    update_log: logging.Logger  # the genebank's <name>_update CSV log, of the holder before the request
    request_id: uuid.UUID = field(default_factory=uuid.uuid4)  # shared by the log rows of one execute()
    log_rows: list = field(default_factory=list)  # inserted together once every command has run
    number_verified: bool = False  # _verify_number runs once per request, whichever command asks

    def record(self, command, before, after, *, undoes=None, reason=None) -> uuid.UUID:
        """A command log row (ADR-0017); its operation_id now, the row with the others at the end of execute."""
        operation_id = uuid.uuid4()
        self.log_rows.append(
            {
                "operation_id": operation_id,
                "request_id": self.request_id,
                "command": command,
                "individual": self.individual.id,
                "actor": self.user.id,
                "before": before,
                "after": after,
                "undoes": undoes,
                "reason": reason,
            }
        )
        return operation_id


class Command(Protocol):
    """A write intent. Subclass it to inherit the no-op defaults."""

    apply_rank: ClassVar[int] = 0  # apply/after_save order across commands (stable)

    def check(self, stage: Stage, ctx: WriteContext) -> None:
        return None

    def pre_write(self, ctx: WriteContext) -> dict:
        """Fields to clear in one UPDATE of their own, before apply (IR-51)."""
        return {}

    def apply(self, ctx: WriteContext) -> None:
        """Before the save."""
        return None

    def after_save(self, ctx: WriteContext) -> None:
        return None

    def verify(self, ctx: WriteContext) -> None:
        """After every after_save, on the final row; a refusal still rolls the whole request back."""
        return None

    def logged_columns(self) -> frozenset[str]:
        """The columns whose before and after execute logs under the class name, when they changed."""
        return frozenset()


class PolicyCommand(Command):
    """
    A command that asks the policy table, under its class name, at `policy_stage` (None: in its
    apply) and refuses with `denied()`. Its own checks are `check_<stage>` methods.
    """

    policy_stage: ClassVar[Stage | None] = Stage.REAUTH

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # check() finds the hooks by name, so a misspelled one would silently never run.
        stages = {f"check_{stage.name.lower()}" for stage in Stage}
        unknown = [name for name in vars(cls) if name.startswith("check_") and name not in stages]
        if unknown:
            raise TypeError(f"{cls.__name__}: no Stage for {', '.join(unknown)}")

    def denied(self) -> Exception:
        return IndividualRefused("Forbidden")

    def authorize(self, ctx: WriteContext) -> None:
        if not allowed(type(self).__name__, ctx.roles, ctx.state):
            raise self.denied()

    def check(self, stage: Stage, ctx: WriteContext) -> None:
        if stage == self.policy_stage:
            self.authorize(ctx)
        hook = getattr(self, f"check_{stage.name.lower()}", None)
        if hook is not None:
            hook(ctx)


def roles_for(user, individual) -> frozenset[Role]:
    """The user's roles on `individual`, from the same sources as User.can_edit and User.can_transfer."""
    herd = individual.current_herd  # the holder row's herd, else the origin herd (current_holder_row)
    managed = user.is_manager or []
    owned = user.transfer_herd_ids()
    roles = {
        Role.ADMIN: user.is_admin,
        Role.MANAGER_CURRENT: herd.genebank_id in managed,
        Role.MANAGER_ORIGIN: individual.origin_herd.genebank_id in managed,
        Role.OWNER: herd.id in owned,
        Role.CARETAKER: herd.id in user.effective_herd_ids() - owned,
    }
    return frozenset(role for role, held in roles.items() if held)


def state_for(individual) -> State:
    return State(
        certified=bool(individual.certificate or individual.digital_certificate),
        outside_genebank=individual.current_herd.herd in OUTSIDE_GENEBANK_HERDS,
    )


def _shared_guards(ctx):
    """Every write, whatever its commands: permission, then voided, both under the lock (IR-03, IR-05)."""
    if not ctx.user.can_edit(ctx.individual.id):
        raise IndividualRefused("Forbidden")
    if ctx.individual.voided:  # unpromoted while this request waited: its slot is free again
        raise IndividualRefused("Individual not found")


@number_assets.finishing  # inside a caller's transaction, teardown_request finishes instead
def execute(
    user: User,
    individual_id: int,
    translate: Callable[[WriteContext], list[Command]],
    *,
    target_breeding: int | None = None,
    with_parents: bool = False,
) -> Individual:
    """Run the commands `translate` builds from the locked row; raises their refusals unmapped."""
    with DATABASE.atomic():
        lock_individual_for_edit(individual_id, target_breeding, with_parents)
        individual = Individual.get_by_id(individual_id)
        target = canonical_breeding_id(target_breeding)
        ctx = WriteContext(
            user=user,
            individual=individual,
            stored=Individual.get_by_id(individual_id),
            roles=roles_for(user, individual),
            state=state_for(individual),
            breeding_after=individual.breeding_id if target is None else target,
            update_log=logging.getLogger(f"{individual.current_herd.genebank.name}_update"),
        )
        commands = translate(ctx)
        if not any(isinstance(command, MoveToLitter) for command in commands):
            ctx.breeding_after = individual.breeding_id  # a lock target alone moves nothing (the quota's litter)
        for stage in Stage:
            if stage == Stage.REAUTH:
                _shared_guards(ctx)
            for command in commands:
                try:
                    command.check(stage, ctx)
                except (IndividualRefused, HerdTrackingError):
                    raise
                except Exception as exc:
                    if stage <= RAW_UNTIL:  # the adapter lets these through raw (today's 500s)
                        exc.individual_stage = stage
                    raise
        cleared = {}
        for command in commands:
            cleared.update(command.pre_write(ctx))
        if cleared:
            Individual.update(**cleared).where(Individual.id == individual_id).execute()
            ctx.individual = Individual.get_by_id(individual_id)
        ordered = sorted(commands, key=lambda command: command.apply_rank)
        for command in ordered:
            command.apply(ctx)
        ctx.individual.save()
        for command in ordered:
            command.after_save(ctx)
        for command in ordered:
            command.verify(ctx)
        _log_changes(ctx, commands, Individual.get_by_id(individual_id))
    return ctx.individual


def _j(value):
    """The JSON form a value is logged and compared in."""
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def _column_value(individual, name):
    return _j(individual.__data__.get(name))


def _db_value(name, value):
    if value is not None and isinstance(Individual._meta.fields[name], DateField):
        return date.fromisoformat(value)
    return value


def _log_changes(ctx, commands, saved):
    """One row per command whose columns changed, in list order (an echo logs nothing), then every row at once."""
    for command in commands:
        changed = sorted(c for c in command.logged_columns() if _column_value(ctx.stored, c) != _column_value(saved, c))
        if changed:
            before = {c: _column_value(ctx.stored, c) for c in changed}
            ctx.record(type(command).__name__, before, {c: _column_value(saved, c) for c in changed})
    if ctx.log_rows:
        IndividualCommand.insert_many(ctx.log_rows).execute()


def canonical_breeding_id(value):
    """
    The target breeding id as an int (None stays None). Values the ORM would coerce silently
    (1.0, " 1 ") are canonicalised so the lock set and the write agree; non-integral values are
    refused with form_to_individual's message.
    """
    if value is None:
        return None
    if isinstance(value, Breeding):
        return value.id
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise ValueError(f"Unknown breeding event: '{value}''")


def lock_individual_for_edit(individual_id, breeding_id=None, with_parents=False):
    """
    Lock an individual edit in the global order: its Breeding
    row(s) first — the stored one plus `breeding_id` if the edit moves it — then the
    individual. update_breeding holds Breeding → kits, so individual-first could deadlock.
    `with_parents`: the edit also runs update_breeding (certificates), which locks the
    litter's parents — lock them with the individual in the same ascending call.
    Returns the locked individual rows ([] if it does not exist).

    The stored breeding is read before any lock; if a concurrent edit moved the rabbit to
    another litter in between, abort with 409 instead of locking that Breeding while
    holding the individual — the caller retries the whole request.
    """
    breeding_id = canonical_breeding_id(breeding_id)
    stored = Individual.select(Individual.breeding).where(Individual.id == individual_id).scalar()
    breeding_ids = {b for b in (stored, breeding_id) if b is not None}
    lock_breedings(breeding_ids)
    wanted = {individual_id}
    if with_parents and breeding_ids:  # read under the Breeding locks: parents cannot change now
        for parents in Breeding.select(Breeding.mother, Breeding.father).where(Breeding.id.in_(breeding_ids)):
            wanted |= {p for p in (parents.mother_id, parents.father_id) if p is not None}
    locked = [row for row in lock_individuals(wanted) if row.id == individual_id]
    current = Individual.select(Individual.breeding).where(Individual.id == individual_id).scalar()
    if locked and current is not None and current not in breeding_ids:
        raise HerdTrackingConflict("Kaninen ändrades samtidigt. Försök igen.")
    return locked


def update_weights(individual, weights, username):
    """
    Updates the weight measurements of `individual` to match those in `weights`.

    `weights` should be a list formatted like:
    [{weight: <float>, date: 'yyyy-mm-dd'}, [...]]
    """
    update_logger = logging.getLogger(f"{individual.current_herd.genebank.name}_update")
    with DATABASE.atomic():
        current_weights = Weight.select().where(Weight.individual == individual.id)
        current_list = [(w.weight_date.strftime("%Y-%m-%d"), w.weight) for w in current_weights]
        new_list = [(w["date"], w["weight"]) for w in weights]

        # check for current measurements to delete
        for weight in current_list:
            if weight not in new_list:
                update_logger.info(f"{username},{individual.number},removing weight,{weight[0]},{weight[1]},")
                Weight.delete().where(
                    Weight.individual == individual,
                    Weight.weight_date == weight[0],
                    Weight.weight == weight[1],
                ).execute()

        # check for new measurements to add
        for weight in new_list:
            if weight not in current_list:
                update_logger.info(f"{username},{individual.number},adding weight,{weight[0]},{weight[1]},")
                Weight(
                    individual=individual,
                    weight_date=weight[0],
                    weight=weight[1],
                ).save()


def update_bodyfat(individual, bodyfat, username):
    """
    Updates the bodufat measurements of `individual` to match those in `bodyfat`.

    `bodyfat` should be a list formatted like:
    [{bodyfat: 'low' | 'normal' | 'high', date: 'yyyy-mm-dd'}, [...]]
    """
    update_logger = logging.getLogger(f"{individual.current_herd.genebank.name}_update")
    with DATABASE.atomic():
        logger.warning("bodyfat: %s", bodyfat)
        current_bodyfat = Bodyfat.select().where(Bodyfat.individual == individual.id)
        current_list = [(b.bodyfat_date.strftime("%Y-%m-%d"), b.bodyfat) for b in current_bodyfat]
        new_list = [(b["date"], b["bodyfat"]) for b in bodyfat]

        # check for current measurements to delete
        for measure in current_list:
            if measure not in new_list:
                update_logger.info(f"{username},{individual.number},removing hull,{measure[0]},{measure[1]},")
                Bodyfat.delete().where(
                    Bodyfat.individual == individual,
                    Bodyfat.bodyfat_date == measure[0],
                    Bodyfat.bodyfat == measure[1],
                ).execute()

        # check for new measurements to add
        for measure in new_list:
            if measure not in current_list:
                if measure[1] not in ["low", "normal", "high"]:
                    logger.error("Unknown bodyfat level: %s", measure[1])
                else:
                    update_logger.info(f"{username},{individual.number},adding hull,{measure[0]},{measure[1]},")
                    Bodyfat(
                        individual=individual,
                        bodyfat_date=measure[0],
                        bodyfat=measure[1],
                    ).save()


@number_assets.finishing
def update_birth_date_herd_tracking(individual, user, new_date, old_date):
    """Moves the BIRTH row to `new_date` (void + new BIRTH) and fixes the number's year digits."""
    update_logger = logging.getLogger(f"{individual.current_herd.genebank.name}_update")
    update_logger.info(
        f"{user.username},{individual.id}:{individual.number},UPDATE birth tracking date,{old_date},{new_date},"
    )
    old_number = individual.number
    with DATABASE.atomic():
        if new_date.strftime("%y") != old_date.strftime("%y"):
            update_logger.info(
                f"{user.username},{individual.id},UPDATE year in number,"
                f"{old_date.strftime('%y')},{new_date.strftime('%y')},"
            )
            individual.number = (
                individual.number.split("-")[0] + "-" + new_date.strftime("%y") + individual.number.split("-")[1][2:]
            )
            logger.info(f"New number Year change for id: {individual.id} is: {individual.number}")
            individual.save()
        replace_birth_row(individual, user, date=new_date, reason=BIRTH_DATE_CHANGED_REASON)
        if individual.number != old_number:
            number_assets.record(
                individual.id, old_number, individual.number, individual.digital_certificate is not None
            )


def _form_date(value):
    """form_to_individual's date: '%Y-%m-%d' with strptime's message, a non-string as it is (IR-12)."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except TypeError:
        return value
    except ValueError as exc:
        raise IndividualRefused(f"{exc}") from None


# The form's lookups (IR-13), shared with add_individual's form_to_individual.
def known_litter(breeding_id):
    litter = Breeding.get_or_none(Breeding.id == breeding_id)
    if litter is None:
        raise IndividualRefused(f"Unknown breeding event: '{breeding_id}''")
    return litter


def known_color(name):
    """The first colour so named, of any genebank."""
    color = Color.get_or_none(Color.name == name)
    if color is None:
        raise IndividualRefused(f"Unknown color: '{name}''")
    return color


def known_origin_herd(code):
    """A ValueError when unknown: on PATCH it goes on raw (IR-27)."""
    herd = Herd.get_or_none(Herd.herd == code)
    if herd is None:
        raise ValueError(f"Unknown origin herd: '{code}''")
    return herd


def known_parent(number):
    """Looked up although never written: parents are the litter's."""
    parent = Individual.get_or_none(Individual.number == number)
    if parent is None:
        raise IndividualRefused("Invalid parents")
    return parent


def _writes_only(command, fields):
    if unknown := set(fields) - set(COMMAND_FIELDS[type(command).__name__]):
        raise ValueError(f"{type(command).__name__} does not write {sorted(unknown)}")


@dataclass(frozen=True)
class _FormFields(PolicyCommand):
    """Plain columns, set and logged as form_to_individual's update branch did (IR-11, IR-12, IR-13, IR-50)."""

    changes: dict

    def __post_init__(self):
        _writes_only(self, self.changes)

    def logged_columns(self):
        return frozenset(self.changes)

    def check_color(self, ctx):
        if "color" in self.changes:
            known_color(self.changes["color"])

    def check_dates(self, ctx):
        for key, value in self.changes.items():
            if key.endswith("date"):
                _form_date(value)

    def apply(self, ctx):
        ind, user = ctx.individual, ctx.user.username
        for key, value in self.changes.items():
            if key.endswith("date"):
                setattr(ind, key, _form_date(value))
                if isinstance(value, str):  # the parsed date in the old column, every time (IR-50)
                    ctx.update_log.info(f"{user},{ind.number},{key},{getattr(ind, key)},{value},")
                continue
            if key == "color":
                value = known_color(value)
            if getattr(ind, key) != value:
                ctx.update_log.info(f"{user},{ind.number},{key},{getattr(ind, key)},{value},")
            setattr(ind, key, value)


class EditDescription(_FormFields):
    apply_rank = 10


class RecordDeath(_FormFields):
    apply_rank = 10


@dataclass(frozen=True)
class ClearFields(PolicyCommand):
    """v2's undo of a death or castration: nulls in an UPDATE of their own, without a CSV line (IR-51)."""

    fields: frozenset[str]

    def __post_init__(self):
        _writes_only(self, self.fields)

    def logged_columns(self):
        return self.fields

    def pre_write(self, ctx):
        return dict.fromkeys(self.fields)


@dataclass(frozen=True)
class SetMeasurements(PolicyCommand):
    """Each given list replaces the stored one; null is passed on, and fails as today (IR-14, IR-42)."""

    weights: object = MISSING
    bodyfat: object = MISSING
    apply_rank = 60

    def apply(self, ctx):
        if self.weights is not MISSING:
            update_weights(ctx.individual, self.weights, ctx.user.username)
        if self.bodyfat is not MISSING:
            update_bodyfat(ctx.individual, self.bodyfat, ctx.user.username)


def _target(herd):
    """A herd as code, id, {"herd": code} or Herd; unknown is HerdTrackingInvalid (IR-52)."""
    return resolve_herd(herd.get("herd") if isinstance(herd, dict) else herd)


def _holder(ctx):
    """The holder under the lock; with no active row, the stored origin herd (IR-31)."""
    row = current_holder_row(ctx.individual.id)
    return row.herd if row and row.herd_id else ctx.stored.origin_herd


@dataclass(frozen=True)
class RecordAttestation(PolicyCommand):
    """A yearly report in the holder's herd (IR-30, IR-31, IR-33)."""

    herd: object
    date: str
    apply_rank = 70
    policy_stage = None  # asked in apply, after the measurements are written (IR-52)

    def apply(self, ctx):
        when = validate_date(self.date)
        target = _target(self.herd)
        self.authorize(ctx)
        if target.herd != _holder(ctx).herd:
            raise AssertionError(f"{target.herd} does not hold the rabbit: that is a TransferIndividual")
        # The herd-tracking row with the same operation_id holds what was written.
        op = ctx.record(type(self).__name__, None, None)
        record_herd_tracking(ctx.individual, target, when, "ATTESTATION", ctx.user, operation_id=op)


def _genebank_correction(ctx, from_herd, to_herd, reason):
    """Into another genebank only as an admin's correction with a reason, logged (IR-54); returns the note."""
    if not allowed("GenebankCorrection", ctx.roles, ctx.state):
        raise HerdTrackingForbidden("Bara administratör kan flytta en individ till en annan genbank.")
    note = require_reason(reason)
    logger.warning(
        f"Genebank change by admin {ctx.user.username}: {ctx.stored.number} from {from_herd.genebank.name} "
        f"({from_herd.herd}) to {to_herd.genebank.name} ({to_herd.herd}): {note}"
    )
    return note


@dataclass(frozen=True)
class TransferIndividual(PolicyCommand):
    """A sale or move out of the holder's herd; into another genebank an admin's correction (IR-32, IR-54)."""

    herd: object
    date: str
    reason: str | None = None
    apply_rank = 70
    policy_stage = None  # asked in apply, after the measurements are written (IR-52)

    def denied(self):
        return HerdTrackingForbidden("Du får inte sälja eller flytta individen till den besättningen.")

    def apply(self, ctx):
        when = validate_date(self.date)
        target = _target(self.herd)
        self.authorize(ctx)
        holder = _holder(ctx)
        note = None
        if target.genebank_id != holder.genebank_id:
            note = _genebank_correction(ctx, holder, target, self.reason)
        op = ctx.record(type(self).__name__, None, None)
        record_herd_tracking(ctx.individual, target, when, "TRANSFER", ctx.user, operation_id=op, notes=note)


def _first_certificate(ctx, certificate):
    """IR-22: a first certificate (truthy, IR-55) takes one of the slots of the litter after the request."""
    if ctx.stored.certificate or ctx.stored.digital_certificate or not certificate or ctx.breeding_after is None:
        return
    try:
        validate_first_certificate(Breeding.get_by_id(ctx.breeding_after))
    except RosterAliveExceeds6w as exc:
        envelope = {"status": "error", "message": f"{exc}", "must_mark_dead": exc.must_mark_dead}
        raise IndividualRefused(envelope=envelope) from None
    except ValueError as exc:
        raise IndividualRefused(f"{exc}") from None


def _verify_number(ctx, paper_number):
    """
    An uncertified rabbit's number after the request (a first paper certificate or a rename,
    in one call or two) must be the one its litter gives, and the paper's when the caller sends it; without
    it the number the user typed is what the paper says. Checked once, on the saved row.
    """
    if ctx.number_verified or ctx.state.certified:
        return
    ctx.number_verified = True
    ind = ctx.individual
    # The stored number must be the one the litter gives, and the paper's too: a paper agreeing with the litter
    # must not certify a rabbit stored under another number.
    for claim in [ind.number] if paper_number is None else [ind.number, paper_number]:
        if parse_number(claim) is None:
            raise IndividualRefused(
                "Individnumret ska skrivas som besättningsnummer-år, kullnummer och plats, till exempel G1274-2512."
            )
        check = number_check(ctx.user, claim, individual=ind)
        # shortcut: a litter without litter_number or birth_date cannot be checked and passes as before (the paper
        # is then not compared with the stored number either); refuse it too once every litter has a number.
        if check["status"] != "conflict":
            continue
        litter = Breeding.get_by_id(ind.breeding_id)
        right = check["stamboken_number"]
        message = (
            litter_mismatch(check["paper_number"], litter, right)
            if right and right != check["paper_number"]
            else f"Numret {check['paper_number']} finns redan på en annan kanin. Kontakta genbanksansvarig."
        )
        envelope = {"status": "error", "message": message, "problem_status": 409, "title": "number_conflict"}
        raise IndividualRefused(envelope={**envelope, **conflict_extensions(check)})


@dataclass(frozen=True)
class AssignPaperCertificate(PolicyCommand):
    """
    The paper number, stored as text (IR-55), replacing a digital one (IR-20). Null writes nothing (IR-40).
    A first certificate is issued for the rabbit's number only if the paper's individual number matches
    (paper_number, else the number after the request).
    """

    certificate: str | None
    paper_number: str | None = None
    apply_rank = 20
    policy_stage = Stage.CERT_AUTH

    def denied(self):
        return IndividualRefused("Bara managers kan uppdatera certificate")

    def logged_columns(self):
        return frozenset({"certificate", "digital_certificate"})

    def check_cert_unique(self, ctx):
        value = self.certificate
        # Raw, as today: an int echo of the stored text is a change and finds the rabbit itself (IR-49).
        if value is None or value == ctx.stored.certificate:
            return
        if Individual.select().where(Individual.certificate == value).exists():
            logger.warning(
                f"User: {ctx.user.username} trying to change {ctx.stored.id}:{ctx.stored.number} "
                f"intyg number already exists {value}"
            )
            raise IndividualRefused("Individual certificate already exists")

    def check_quota(self, ctx):
        if self.certificate is not None:
            _first_certificate(ctx, str(self.certificate))

    def apply(self, ctx):
        if self.certificate is None:
            return
        ind, user, value = ctx.individual, ctx.user.username, str(self.certificate)
        if ind.certificate != value:
            if ind.digital_certificate is not None:
                ctx.update_log.info(f"{user},{ind.number},digital_certificate,{ind.digital_certificate},'None',")
                ind.digital_certificate = None
            ctx.update_log.info(f"{user},{ind.number},certificate,{ind.certificate},{value},")
        ind.certificate = value

    def verify(self, ctx):
        if self.certificate:
            _verify_number(ctx, self.paper_number)


@dataclass(frozen=True)
class RenameIndividual(PolicyCommand):
    """A new number; its certificate and photo follow once the transaction commits (IR-15, IR-23)."""

    number: str
    apply_rank = 50
    policy_stage = Stage.MANAGER_ONLY

    def denied(self):
        return IndividualRefused("Bara managers kan uppdatera number")

    def logged_columns(self):
        return frozenset({"number"})

    def check_number_unique(self, ctx):
        if Individual.select().where(Individual.number == self.number).exists():
            logger.warning(
                f"User: {ctx.user.username} trying to update {ctx.stored.id}:{ctx.stored.number} "
                f"new number already exists {self.number}"
            )
            raise IndividualRefused("Individual number already exists")

    def apply(self, ctx):
        old = ctx.stored.number
        ctx.individual.number = self.number
        ctx.update_log.info(f"{ctx.user.username},{old},new_number,{old},{self.number},")

    def after_save(self, ctx):
        # To the final number: MoveToLitter's birth-year fix may have changed it again since apply.
        ind = ctx.individual
        number_assets.record(ind.id, ctx.stored.number, ind.number, ind.digital_certificate is not None)

    def verify(self, ctx):
        _verify_number(ctx, None)


@dataclass(frozen=True)
class MoveToLitter(PolicyCommand):
    """Into another litter of the rabbit's genebank; the birth date and its year digits follow (IR-24–IR-26)."""

    breeding_id: int
    apply_rank = 30
    policy_stage = Stage.MANAGER_ONLY

    def denied(self):
        return IndividualRefused("Bara managers kan uppdatera breeding")

    def logged_columns(self):
        return frozenset({"breeding", "number"})  # the number's year digits follow the litter

    def check_breeding_exists(self, ctx):
        if ctx.breeding_after != self.breeding_id:
            raise AssertionError("execute's target_breeding must be the litter moved to: it is locked first")
        known_litter(self.breeding_id)

    def check_litter(self, ctx):
        herd = Breeding.get_by_id(self.breeding_id).breeding_herd_id
        if herd.genebank_id != ctx.stored.origin_herd.genebank_id or not ctx.user.can_edit(herd.herd):
            raise IndividualRefused("Forbidden")

    def check_cycle(self, ctx):
        litter = Breeding.get_by_id(self.breeding_id)
        if pedigree_cycle_error([ctx.individual.id], litter.father_id, litter.mother_id):
            raise IndividualRefused(envelope=dict(CYCLE_PROBLEM))

    def apply(self, ctx):
        ind = ctx.individual
        ctx.update_log.info(f"{ctx.user.username},{ind.number},breeding,{ind.breeding_id},{self.breeding_id},")
        ind.breeding = self.breeding_id

    def after_save(self, ctx):
        old, new = ctx.stored.breeding.birth_date, ctx.individual.breeding.birth_date
        if old != new:
            update_birth_date_herd_tracking(ctx.individual, ctx.user, new_date=new, old_date=old)


@dataclass(frozen=True)
class ChangeOriginHerd(PolicyCommand):
    """
    A new origin herd: the BIRTH row is replaced and a single kit's litter follows; into another
    genebank an admin's correction, for a rabbit never moved (IR-27–IR-29, IR-54, IR-56).
    """

    herd_code: str
    reason: str | None = None
    apply_rank = 40
    policy_stage = Stage.ORIGIN_AUTH

    def denied(self):
        return HerdTrackingForbidden("Endast genbanksansvarig eller administratör kan ändra ursprungsbesättning.")

    def logged_columns(self):
        return frozenset({"origin_herd"})

    def _herd(self):
        return Herd.get(Herd.herd == self.herd_code)

    def check_origin_pre(self, ctx):
        known_origin_herd(self.herd_code)
        # Counted in the litter after the request, as today's form["breeding"] (IR-27).
        if Individual.select().where(Individual.breeding_id == ctx.breeding_after).count() != 1:
            raise IndividualRefused("origin_herd more inds")

    def authorize(self, ctx):
        old, new = ctx.stored.origin_herd, self._herd()
        if new.genebank_id != old.genebank_id:  # the genebank first, also for a manager of the origin (IR-28)
            _genebank_correction(ctx, old, new, self.reason)
        else:
            super().authorize(ctx)

    def apply(self, ctx):
        ind, new = ctx.individual, self._herd()
        # The field line form_to_individual's update branch wrote (ids); new_origin_herd follows the save.
        ctx.update_log.info(f"{ctx.user.username},{ind.number},origin_herd,{ind.origin_herd_id},{new.id},")
        ind.origin_herd = new

    def after_save(self, ctx):
        ind, old = ctx.individual, ctx.stored.origin_herd
        new = ind.origin_herd
        ctx.update_log.info(f"{ctx.user.username},{ctx.stored.number},new_origin_herd,{old.herd},{new.herd},")
        reason = BIRTH_HERD_CHANGED_REASON
        if new.genebank_id != old.genebank_id:
            # Also a move this request wrote: its TRANSFER rows would still start in the old genebank (IR-56).
            moved = HerdTracking.select().where(
                HerdTracking.individual == ind.id,
                HerdTracking.kind.in_(("TRANSFER", "CORRECTION")),
                ht_not_voided(),
            )
            if moved.exists():
                raise HerdTrackingConflict(
                    "Kaninen har flyttats. Rätta besättningshistoriken innan ursprungsbesättningen "
                    "byts till en annan genbank."
                )
            reason = f"{BIRTH_HERD_CHANGED_REASON}: {require_reason(self.reason)}"
        replace_birth_row(ind, ctx.user, herd=new, reason=reason)
        if Individual.select().where(Individual.breeding_id == ind.breeding_id).count() == 1:
            litter = Breeding.get_by_id(ind.breeding_id)
            litter.breeding_herd_id = new.id
            litter.save()


@dataclass(frozen=True)
class IssueDigitalCertificate(PolicyCommand):
    """The next digital number, under the lock (IR-21), replacing the paper one (IR-20). The certificate routes only."""

    apply_rank = 20

    def logged_columns(self):
        return frozenset({"certificate", "digital_certificate"})

    def check_quota(self, ctx):
        _first_certificate(ctx, True)

    def apply(self, ctx):
        ind, user = ctx.individual, ctx.user.username
        latest = Individual.select(fn.MAX(Individual.digital_certificate)).scalar()
        number = 100000 if latest is None else latest + 1
        if ind.certificate is not None:
            ctx.update_log.info(f"{user},{ind.number},certificate,{ind.certificate},'None',")
            ind.certificate = None
        ctx.update_log.info(f"{user},{ind.number},digital_certificate,{ind.digital_certificate},{number},")
        ind.digital_certificate = number


UNDO_WINDOW = timedelta(days=7)  # as undoing a sale or an attestation in herd-tracking
UNDOABLE = frozenset({"EditDescription", "RecordDeath", "ClearFields", "RecordAttestation"})
UNDO_REASON = "Ångrad av den som registrerade den"
# The TextFields of FORM_WRITABLE_FIELDS; not name, the rabbit's name.
FREE_TEXT_FIELDS = ("notes", "hair_notes", "color_note", "death_note", "eye_color", "claw_color", "belly_color")
FREE_TEXT_RETENTION = timedelta(days=396)  # 13 months, rounded up


def actor_role(user, entry) -> frozenset[Role]:
    """{ACTOR} when `user` ran the logged command `entry`: only Undo derives it, never roles_for."""
    return frozenset({Role.ACTOR}) if entry.actor_id == user.id else frozenset()


def _active_attestation_rows(entry):
    # The rabbit's own ATTESTATION rows: herd-tracking accepts a client's operation id per individual, so the
    # same UUID can name another rabbit's rows.
    return list(
        HerdTracking.select().where(
            HerdTracking.operation_id == entry.operation_id,
            HerdTracking.individual == entry.individual_id,
            HerdTracking.kind == "ATTESTATION",
            ht_not_voided(),
        )
    )


def _undone(entry):
    """An attestation by its herd-tracking rows, which herd-tracking's own API also voids; else by the log."""
    if entry.command == "RecordAttestation":
        return not _active_attestation_rows(entry)
    return IndividualCommand.select().where(IndividualCommand.undoes == entry.operation_id).exists()


@dataclass(frozen=True)
class Undo(Command):
    """
    Undoes a logged command: its actor within UNDO_WINDOW, or a correction by an editor with a reason
    (ADR-0017). The steps run in apply, under the individual's lock, in this order.
    """

    operation_id: uuid.UUID
    reason: str | None = None

    def apply(self, ctx):
        # FOR UPDATE: the free-text purge's UPDATE waits for this undo, or this undo reads the purged row.
        entry = (
            IndividualCommand.select()
            .where(
                IndividualCommand.operation_id == self.operation_id, IndividualCommand.individual == ctx.individual.id
            )
            .for_update()
            .first()
        )
        if entry is None:
            raise HerdTrackingNotFound("Ändringen finns inte.")
        if entry.command not in UNDOABLE or (entry.command == "EditDescription" and "has_photo" in entry.after):
            raise HerdTrackingInvalid(f"Den här ändringen kan inte ångras. {CONTACT_MANAGER}")
        if _undone(entry):
            raise HerdTrackingConflict("Ändringen är redan ångrad.")
        actor = actor_role(ctx.user, entry)
        if not (allowed("Undo", ctx.roles | actor, ctx.state) and allowed(entry.command, ctx.roles, ctx.state)):
            raise HerdTrackingForbidden(f"Bara den som gjorde ändringen kan ångra den. {CONTACT_MANAGER}")
        if actor and datetime.now(timezone.utc) - entry.created_at <= UNDO_WINDOW:
            note = UNDO_REASON
        elif ctx.roles & {Role.MANAGER_CURRENT, Role.ADMIN}:
            note = require_reason(self.reason)
        else:
            raise HerdTrackingForbidden(f"Ändringen gjordes för mer än 7 dagar sedan. {CONTACT_MANAGER}")
        if entry.redacted_at is not None:
            raise HerdTrackingConflict("Uppgifterna är rensade och kan inte återställas.")
        if entry.command == "RecordAttestation":
            undo_op = ctx.record("Undo", None, None, undoes=entry.operation_id, reason=note)
            for row in _active_attestation_rows(entry):  # herd-tracking's void rules apply unchanged
                void_herd_tracking(row.id, ctx.user, note, operation_id=undo_op)
            return
        changed = sorted(key for key, value in entry.after.items() if _column_value(ctx.individual, key) != value)
        if changed:
            raise HerdTrackingConflict("Någon har ändrat samma uppgifter efteråt.", rows=changed)
        for key, value in entry.before.items():
            setattr(ctx.individual, key, _db_value(key, value))
        ctx.record("Undo", entry.after, entry.before, undoes=entry.operation_id, reason=note)


def own_recent_commands(user, individual_id):
    """The user's own commands on the individual within UNDO_WINDOW, newest first, without the undos."""
    rows = (
        IndividualCommand.select()
        .where(
            IndividualCommand.individual == individual_id,
            IndividualCommand.actor == user.id,
            IndividualCommand.command != "Undo",
            IndividualCommand.created_at >= datetime.now(timezone.utc) - UNDO_WINDOW,
        )
        .order_by(IndividualCommand.created_at.desc(), IndividualCommand.id.desc())
    )
    return [
        {
            "operation_id": str(row.operation_id),
            "command": row.command,
            "created_at": row.created_at.isoformat(),
            "before": row.before,
            "after": row.after,
            "undone": _undone(row),
        }
        for row in rows
    ]


def purge_command_free_text(now, *, actor_id=None) -> int:
    """
    Removes the free text from old command log rows (FREE_TEXT_RETENTION), or with `actor_id` from every
    row of that actor (purge_user_audit_pii): the FREE_TEXT_FIELDS keys of before and after, and the reason.
    Only a row that lost a field gets redacted_at, since only there would an undo restore a value that is
    gone. Returns the number of rows changed.
    """
    which = ("actor_id = %s", actor_id) if actor_id is not None else ("created_at < %s", now - FREE_TEXT_RETENTION)
    keys = list(FREE_TEXT_FIELDS)
    # The UPDATE takes the row lock an Undo holds (FOR UPDATE), so it waits for that undo to commit.
    cursor = DATABASE.execute_sql(
        f"""
        UPDATE individual_command
        SET before = before - %s::text[],
            after = after - %s::text[],
            reason = NULL,
            redacted_at = CASE WHEN before ?| %s::text[] OR after ?| %s::text[] THEN %s ELSE redacted_at END
        WHERE {which[0]} AND (before ?| %s::text[] OR after ?| %s::text[] OR reason IS NOT NULL)
        """,
        (keys, keys, keys, keys, now, which[1], keys, keys),
    )
    return cursor.rowcount or 0
