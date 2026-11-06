"""
update_individual's adapter (ADR-0015): the legacy write form as commands.

`translate` compares the form with the row stored under the lock and lists the commands whose stages
give today's answers in today's order.
It only compares (form.get, isinstance): execute tags the errors raised in check(), not those raised
in translate, so every read that can fail is a LegacyFormChecks stage.
"""

from dataclasses import dataclass

from utils.database import Herd, Individual, validate_date
from utils.herd_tracking import resolve_herd
from utils.individual_commands import (
    MISSING,
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
    _holder,
    known_litter,
    known_origin_herd,
    known_parent,
)
from utils.individual_policy import COMMAND_FIELDS, Role


def _differs(sent, stored):
    """A managers-only change: null and the string "None" differ, an int or str echo does not (IR-18, IR-40)."""
    return (sent is None) != (stored is None) or f"{sent}" != f"{stored}"


def _can_manage(ctx):
    """Who may change the managers-only fields of a certified rabbit (IR-18): form_to_individual's former can_manage."""
    return not ctx.state.certified or bool(ctx.roles & {Role.ADMIN, Role.MANAGER_CURRENT})


@dataclass(frozen=True)
class LegacyFormChecks(Command):
    """
    What today's form is checked for beyond its commands' own checks, one method per rule and named by
    its IR, so that each can be dropped on its own (Decision 3). Errors up to HERD go on raw, as today's
    checks before the lock; later unexpected ones, as the AttributeErrors after the save, are the generic
    "Kunde inte uppdatera individ." with everything rolled back.
    """

    form: dict
    issue_digital: bool = False
    apply_rank = 0

    def check(self, stage, ctx):
        rule = {
            Stage.NUMBER_UNIQUE: self.ir49_number,
            Stage.CERT_UNIQUE: self.ir49_certificate,
            Stage.DIGITAL_ECHO: self.ir17_digital_echo,
            Stage.ORIGIN_PRE: self.ir27_origin_herd,
            Stage.HERD: self.ir08_herd,
            Stage.ID_NUMBER: self.ir06_id,
            Stage.CERT_AUTH: self.ir45_digital_certificate,
            Stage.BREEDING_EXISTS: self.ir43_breeding,
            Stage.ORIGIN_SHAPE: self.ir41_origin_herd,
            Stage.PARENTS: self.ir41_parents,
        }.get(stage)
        if rule is not None:
            rule(ctx)

    def ir49_number(self, ctx):
        """IR-02, IR-15, IR-49: number is required, and compared raw, so null or "" is searched too."""
        number = self.form["number"]
        if number != ctx.stored.number:
            RenameIndividual(number).check_number_unique(ctx)

    def ir49_certificate(self, ctx):
        """IR-16, IR-49: compared raw, so the numeric echo 12 is searched and finds the rabbit's own "12"."""
        AssignPaperCertificate(self.form.get("certificate")).check_cert_unique(ctx)

    def ir17_digital_echo(self, ctx):
        """IR-17: a digital number comes only from issuance; an int or str echo of the stored one passes."""
        sent = self.form.get("digital_certificate")
        if sent is not None and f"{sent}" != f"{ctx.stored.digital_certificate}":
            raise IndividualRefused("Digitala intyg utfärdas via intygsfunktionen")

    def ir27_origin_herd(self, ctx):
        """
        IR-27: an unknown code is a ValueError (legacy 500, v2 400). A change counts the kits of
        form["breeding"], a KeyError when it is left out, where ChangeOriginHerd counts the litter after
        the request.
        """
        origin = self.form.get("origin_herd")
        if not (origin and isinstance(origin, dict)):
            return
        if known_origin_herd(origin["herd"]).id != ctx.stored.origin_herd_id:
            if Individual.select().where(Individual.breeding_id == self.form["breeding"]).count() != 1:
                raise IndividualRefused("origin_herd more inds")

    def ir08_herd(self, ctx):
        """IR-08: herd is required, and an object must name a known herd. A code is looked up by the herd event."""
        herd = self.form["herd"]
        if herd and isinstance(herd, dict) and not Herd.select().where(Herd.herd == herd.get("herd")).exists():
            raise IndividualRefused("Individual must have a valid herd")

    def ir06_id(self, ctx):
        """IR-06: the number is always the stored rabbit's here, so only an id of another type, such as "5", differs."""
        if self.form["id"] != ctx.stored.id:
            raise IndividualRefused("Number can not be updated")

    def ir45_digital_certificate(self, ctx):
        """
        IR-40, IR-45: digital_certificate, null too, is a managers' field on a certified rabbit, asked
        before certificate (AssignPaperCertificate). Issuance assigns it itself.
        """
        if "digital_certificate" not in self.form or self.issue_digital or _can_manage(ctx):
            return
        if _differs(self.form["digital_certificate"], ctx.stored.digital_certificate):
            raise IndividualRefused("Bara managers kan uppdatera digital_certificate")

    def ir43_breeding(self, ctx):
        """IR-43: breeding, null too, must name a litter (MoveToLitter comes only for another one)."""
        if "breeding" in self.form:
            known_litter(self.form["breeding"])

    def ir41_origin_herd(self, ctx):
        """IR-41: origin_herd null or not an object fails today's lookup with a TypeError or KeyError."""
        if "origin_herd" in self.form:
            self.form["origin_herd"]["herd"]

    def ir41_parents(self, ctx):
        """
        IR-13, IR-41: mother and father are looked up although never written (they are the litter's): an
        unknown number is "Invalid parents", null or another shape than an object fails the lookup.
        """
        for parent in ("mother", "father"):
            if parent in self.form:
                known_parent(self.form[parent]["number"])

    def after_save(self, ctx):
        if self.ir47_litter_changed(ctx):
            self.ir48_birth_dates(ctx)

    def ir47_litter_changed(self, ctx):
        """IR-47: today's comparison reads the stored litter's id, so a rabbit without a litter is never updated."""
        return ctx.stored.breeding.id != ctx.individual.breeding.id

    def ir48_birth_dates(self, ctx):
        """IR-48: both birth dates are formatted, so a move from or into a litter without one fails."""
        ctx.stored.breeding.birth_date.strftime("%Y-%m-%d")
        ctx.individual.breeding.birth_date.strftime("%Y-%m-%d")


@dataclass(frozen=True)
class LegacyHerdEvent(Command):
    """
    The form's herd and date (IR-30): a yearly report in the holder's herd, a move to any other (IR-31),
    with today's CSV line, written before the target is looked up.
    """

    herd: object  # as sent: a code, an id or {"herd": code}
    field: str  # selling_date or yearly_report_date: the key the date came from
    date: object
    reason: str | None = None
    apply_rank = 70

    def apply(self, ctx):
        when = validate_date(self.date)  # a bad date is the generic error, before the target (IR-52)
        code = self.herd.get("herd") if self.herd and isinstance(self.herd, dict) else self.herd
        old = ctx.stored.current_herd.herd
        ctx.update_log.info(f"{ctx.user.username},{ctx.individual.number},{self.field},{old},{code},{when}")
        target = resolve_herd(code)
        if target.herd == _holder(ctx).herd:
            RecordAttestation(target, self.date).apply(ctx)
        else:
            TransferIndividual(target, self.date, self.reason).apply(ctx)


def _rename(form, stored):
    number = form.get("number")
    return RenameIndividual(number) if number and number != stored.number else None  # IR-49: falsy renames nothing


def _paper_certificate(form, stored):
    if "certificate" in form and _differs(form["certificate"], stored.certificate):  # null too (IR-40)
        return AssignPaperCertificate(form["certificate"], form.get("paper_number"))
    return None


def _origin_herd(form, stored, reason):
    origin = form.get("origin_herd")
    if not (origin and isinstance(origin, dict)) or origin.get("herd") == stored.origin_herd.herd:
        return None
    # With breeding null the request is refused at BREEDING_EXISTS (IR-43): the command's own count, of the
    # stored litter, must not answer first. Left out, LegacyFormChecks answers first (IR-27).
    return ChangeOriginHerd(origin.get("herd"), reason=reason) if form.get("breeding") is not None else None


def _litter(form, stored):
    breeding = form.get("breeding")  # canonical: update_individual has made it an int
    return MoveToLitter(breeding) if breeding is not None and breeding != stored.breeding_id else None


def _changed(form, stored, key):
    """
    A value that is not null and differs (IR-10, IR-11). A date always, since it is logged whenever sent
    (IR-50). A colour always: its name resolves to the first colour so named, of any genebank.
    """
    value = form.get(key)
    return value is not None and (key.endswith("date") or key == "color" or value != getattr(stored, key))


def _fields(command, form, stored):
    changes = {key: form[key] for key in COMMAND_FIELDS[command.__name__] if _changed(form, stored, key)}
    return command(changes) if changes else None


def _cleared(form):
    fields = frozenset(key for key in COMMAND_FIELDS["ClearFields"] if key in form and form[key] is None)
    return ClearFields(fields) if fields else None


def _measurements(form):
    if "weights" in form or "bodyfat" in form:
        return SetMeasurements(form.get("weights", MISSING), form.get("bodyfat", MISSING))
    return None


def _herd_event(form, reason):
    if ("yearly_report_date" in form or "selling_date" in form) and "herd" in form:
        field = "selling_date" if form.get("selling_date") else "yearly_report_date"
        return LegacyHerdEvent(form["herd"], field, form.get(field), reason)
    return None


def translate(form, ctx, *, issue_digital=False, clear_nulls=False, genebank_change_reason=None):
    """
    The commands for `form`, in list order within a stage. A key is read by its presence, null too, and
    gets today's lookup; only the writes skip null (IR-10, IR-40–IR-43).
    """
    stored = ctx.stored
    commands = (
        LegacyFormChecks(form, issue_digital),
        _rename(form, stored),
        _paper_certificate(form, stored),
        _origin_herd(form, stored, genebank_change_reason),
        _litter(form, stored),
        IssueDigitalCertificate() if issue_digital else None,
        _fields(RecordDeath, form, stored),
        _fields(EditDescription, form, stored),
        _cleared(form) if clear_nulls else None,
        _measurements(form),
        _herd_event(form, genebank_change_reason),
    )
    return [command for command in commands if command is not None]
