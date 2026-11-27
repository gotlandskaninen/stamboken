"""
Individual registration v2 endpoint.

Creates individuals from litter context with stored litter numbers.
See ADR-0007 for blueprint conventions.
"""

import logging
import re
from datetime import date as date_type
from datetime import timedelta

import utils.data_access as da
from flask import Blueprint, jsonify, request
from flask_login import current_user
from peewee import DataError, DoesNotExist, IntegrityError
from utils.database import DATABASE, Breeding, Color, Herd, Individual, lock_individuals, not_voided
from utils.herd_tracking import record_herd_tracking
from utils.individual_commands import GESTATION_DAYS, lock_mother_litters
from utils.individual_number_v2 import (
    HARD_CEILING,
    LITTER_BORN_BEFORE_NUMBERED,
    LITTER_SIZE6W_ABOVE_BORN,
    NO_LITTER_NUMBER,
    PAPER_NUMBER_REQUIRED,
    RosterActionError,
    RosterAliveExceeds6w,
    _create_individual_record,
    conflict_extensions,
    herd_year,
    lock_herd_year,
    lock_litter,
    new_litter_number,
    number_check,
    number_to_register,
    number_unnumbered_litter,
    numbered_by_certificate,
    parse_number,
    record_number_choice,
    suggest_individual_number,
    suggest_litter_number,
    validate_first_certificate,
)

from .bunny_v2 import MIN_PROMOTE_AGE_DAYS, _apply_certificate, certificate_choice_problem, digital_certificate_refusal
from .common import json_login_required, problem, rex_problem

logger = logging.getLogger(__name__)


individual_v2_create_bp = Blueprint("individual_v2_create", __name__, url_prefix="/api")

CERTIFICATE_UNUSABLE = "Intygsnumret kan inte användas. Kontakta genbanksansvarig."


@individual_v2_create_bp.route("/v2/individual", methods=["POST"])
@json_login_required
def create_individual():
    """Register a new individual from litter context. Returns 201 + full entity."""
    form = request.get_json(silent=True)
    if not form or not isinstance(form, dict):
        return problem(400, "Bad Request", "Request body must be a JSON object")
    return register_individual(form)


def register_individual(form, may_register=None, created=None):
    """
    POST /v2/individual's registration; returns its response. The intake queue registers through it with
    `may_register(herd)`, the herds the caller may register in (its grant), and `created(individual)`, called
    in the transaction once the rabbit exists.
    """
    return _register(form, current_user, lambda herd: _may_register(herd, may_register), created)


# The report's member never reads NO_LITTER_NUMBER: an older litter without a number that has rabbits (option 1).
NO_LITTER_NUMBER_REPORT = (
    "Kullen har inget kullnummer än och redan registrerade kaniner. Välj Annan kull, eller kontakta genbanksansvarig."
)


def _no_litter_number(genebank):
    """NO_LITTER_NUMBER's refusal: in Swedish at the birth date on the report's path (`genebank`), else as before."""
    if genebank is not None:
        return problem(400, "Bad Request", NO_LITTER_NUMBER_REPORT, field="birth_date")
    return problem(400, "Bad Request", NO_LITTER_NUMBER)


def register_individual_as(actor, herd, form, created=None):
    """
    The report's registration (4b, L1): with `actor`'s own right only (a user, or the link's CodeActor), and only
    into `herd`, where the new rabbit and its litter are born. No current_user, so an account never lends a link
    its rights, nor a link an account its herd. Parents and litters outside the herd's genebank read as missing.
    """
    return _register(form, actor, may_register_in(actor, herd), created, herd.genebank_id)


def may_register_in(actor, herd):
    """The report's rule as a predicate: `herd` only, with the actor's own right there (a code's: its own herd)."""

    def may(target):
        if target is None or target.id != herd.id:
            return False
        code = getattr(actor, "code", None)
        return code.herd_id == herd.id if code is not None else _can_register_in_herd(actor, target)

    return may


def _register(form, actor, may, created, genebank=None):
    """
    A registration with `actor` as the signer and `may(herd)` deciding every herd it writes in; with `genebank`, the
    parents and the litter are looked up in that genebank only (_in_genebank).
    """
    breeding_id = form.get("breeding_id")
    new_litter = None  # "Lägg till kanin": the litter to create, when no breeding_id and no matching litter
    if breeding_id is None:
        breeding, new_litter, refusal = _shortcut_litter(form, may, genebank)
        if refusal:
            return refusal
    else:
        try:
            breeding_id = int(breeding_id)
        except (TypeError, ValueError):
            return problem(400, "Bad Request", "breeding_id must be an integer")

        breeding = _litter_in(Breeding.get_or_none(Breeding.id == breeding_id), genebank)
        if breeding is None:
            return problem(404, "Not Found", f"Breeding {breeding_id} not found")

    if breeding is not None and (refusal := _registration_refusal(breeding, may)):
        return refusal

    # Generate individual number (optionally with explicit position)
    position = form.get("position")
    if position is not None:
        try:
            position = int(position)
        except (TypeError, ValueError):
            return problem(400, "Bad Request", "position must be an integer 1-9")

    certificate_type = form.get("certificate_type")
    paper_number, resolution = form.get("paper_number"), form.get("resolution")
    if refusal := certificate_choice_problem(certificate_type, form.get("paper_certificate"), paper_number, resolution):
        return refusal
    if certificate_type == "paper" and (refusal := _paper_outside(paper_number, genebank)):
        return refusal
    if certificate_type == "digital":
        herd = breeding.breeding_herd_id if breeding is not None else new_litter["herd"]
        if refusal := digital_certificate_refusal(actor, herd):
            return problem(*refusal)

    form_litter_size6w = form.get("litter_size6w")
    if form_litter_size6w is not None:
        try:
            form_litter_size6w = int(form_litter_size6w)
        except (TypeError, ValueError):
            return problem(400, "Bad Request", "litter_size6w must be an integer")

    if refusal := rex_problem(form):
        return refusal

    name = form.get("name")
    if name is not None and (not isinstance(name, str) or len(name) > 50):
        return problem(400, "Bad Request", "name must be a string of at most 50 characters")

    paper_certificate = form.get("paper_certificate") if certificate_type == "paper" else None
    if paper_certificate is not None and (not isinstance(paper_certificate, str) or len(paper_certificate) > 20):
        return problem(400, "Bad Request", "paper_certificate must be a string of at most 20 characters")
    # The report's scope: no lookup by certificate number, which reaches every genebank; the unique index decides.
    checked_certificate = paper_certificate if genebank is None else None

    sex = form.get("sex")  # "male", "female", or None
    color_name = form.get("color")

    # Lock the herd/year's breeding rows, then the litter, FOR UPDATE before minting; the mint runs inside
    # the helper so number generation and Individual creation are atomic.
    try:
        with DATABASE.atomic():
            # The paper's number against Stamboken's (a new litter's before it is created): a conflict raises
            # a 409 and nothing is written. A paper certificate takes the paper's position when free, not the form's.
            check = None
            if new_litter is not None:
                # Serialized with RegisterLitter (the same lock); _create_litter decides the dates again under it
                lock_mother_litters(new_litter["mother"].id)
                lock_herd_year(new_litter["herd"], new_litter["birth_date"].year)
                if certificate_type == "paper":
                    litter = {key: new_litter[key] for key in ("herd", "birth_date", "mother", "father")}
                    check = number_check(actor, paper_number, paper_certificate=checked_certificate, **litter)
                    position = parse_number(number_to_register(check, resolution))[3]
                breeding = _create_litter(**new_litter)
                # Again once every lock is held (herd-year, then the parents in _create_litter): a grant may have
                # been revoked meanwhile. Raising rolls back the new litter too.
                if certificate_type == "digital" and (
                    refusal := digital_certificate_refusal(actor, new_litter["herd"])
                ):
                    raise RosterActionError(*refusal)
            else:
                breeding = lock_litter(breeding.id)
                # Decided again on the locked litter: it may have moved to another herd (or been renumbered or
                # re-dated) since the check above, and the rabbit is born in the locked litter's herd.
                if refusal := _registration_refusal(breeding, may):
                    return refusal
                if certificate_type == "digital" and (
                    refusal := digital_certificate_refusal(actor, breeding.breeding_herd_id)
                ):
                    return problem(*refusal)
            herd = breeding.breeding_herd_id

            # If form provides litter_size6w and breeding doesn't have it yet, or has only a preliminary one
            # (L5: the certificate's count is the confirmed one), persist BEFORE certificate validation so the
            # quota check sees it.
            if form_litter_size6w is not None and (
                breeding.litter_size6w is None or breeding.litter_size6w_preliminary
            ):
                if breeding.litter_size is not None and form_litter_size6w > breeding.litter_size:
                    raise ValueError(LITTER_SIZE6W_ABOVE_BORN)
                breeding.litter_size6w = form_litter_size6w
                breeding.litter_size6w_preliminary = False
                breeding.save(only=[Breeding.litter_size6w, Breeding.litter_size6w_preliminary])

            if breeding.litter_number is None:  # a litter added without a certificate: its first one numbers it (L4)
                check, numbered_position = number_unnumbered_litter(
                    actor, breeding, certificate_type, paper_number, checked_certificate, resolution
                )
                if certificate_type == "paper":  # a digital certificate keeps the position the request chose
                    position = numbered_position

            # Validate certificate eligibility before creating anything: the same first-certificate
            # rules as promote (litter_size6w, roster in sync, quota).
            validate_first_certificate(breeding)
            if certificate_type == "paper" and check is None:
                check = number_check(actor, paper_number, breeding=breeding, paper_certificate=checked_certificate)
                position = parse_number(number_to_register(check, resolution))[3]

            individual = _create_individual_record(
                herd,
                breeding,
                position=position,
                sex=sex,
                color=color_name,
                name=name,
                color_note=form.get("color_note"),
                eye_color=form.get("eye_color"),
                claw_color=form.get("claw_color"),
                belly_color=form.get("belly_color"),
                hair_notes=form.get("hair_notes"),
                rex=form.get("rex", False),
                paper_certificate=paper_certificate,
                signature=actor,
            )
            if check is not None and check["status"] != "match":
                record_number_choice(individual, actor, check)
            if created is not None:
                created(individual)
    except RosterActionError as e:
        if e.detail == NO_LITTER_NUMBER:
            return _no_litter_number(genebank)
        return problem(e.status, e.title, e.detail, **e.extra)
    except RosterAliveExceeds6w as e:
        return problem(400, "Bad Request", str(e), must_mark_dead=e.must_mark_dead)
    except ValueError as e:
        return problem(400, "Bad Request", str(e))
    except IntegrityError:
        if genebank is not None:  # the same answer whichever genebank holds the number
            return problem(409, "Conflict", CERTIFICATE_UNUSABLE, field="paper_certificate")
        return problem(
            409, "Conflict", "A conflict prevented registration — a certificate number may already be in use"
        )
    except DataError:
        return problem(422, "Unprocessable Entity", "One or more fields exceed the maximum allowed length")

    # The certificate after the commit, as promote does: a failed digital issuance keeps the rabbit
    # and comes back as certificate_error.
    # session["user_id"] is the account's uuid; a link has none, and registers only with a paper certificate
    certificate, certificate_error = _apply_certificate(individual, certificate_type, getattr(actor, "uuid", None))
    response_data = {
        "individual": individual.as_dict(),
        "certificate": certificate,
        "certificate_error": certificate_error,
        "breeding": {"id": breeding.id, "litter_number": breeding.litter_number, "created": new_litter is not None},
    }

    # Cache invalidation (best-effort)
    try:
        from utils.cache_invalidation import get_genebank_id_for_herd, trigger_invalidation

        for gid in get_genebank_id_for_herd(herd.herd):
            trigger_invalidation(gid)
    except Exception:
        logger.warning("Cache invalidation failed for individual %s", individual.number)

    return jsonify(response_data), 201


@individual_v2_create_bp.route("/v2/individual/suggest-number", methods=["GET"])
@json_login_required
def suggest_number():
    """Preview the next individual number for a litter without creating one.

    Without breeding_id the litter is named by mother, father and birth_date, as for a registration
    without breeding_id: an existing litter's suggestion, or the first number of the litter to be created.
    """
    return number_suggestion(request.args, lambda herd: _can_register_in_herd(current_user, herd))


def number_suggestion(args, may, genebank=None):
    """
    suggest-number's answer for the query `args`, with `may(herd)` deciding the litter's herd (the report's too) and
    `genebank` scoping the lookups (_in_genebank).
    """
    breeding_id = args.get("breeding_id", type=int)
    if breeding_id:
        breeding = _litter_in(Breeding.get_or_none(Breeding.id == breeding_id), genebank)
        if breeding is None:
            return problem(404, "Not Found", f"Breeding {breeding_id} not found")
    elif "mother" in args:
        key, refusal = _litter_key(args, genebank)
        if refusal:
            return refusal
        mother, father, birth_date = key
        breeding = Breeding.get_or_none(mother=mother, father=father, birth_date=birth_date)
        if breeding is None:
            return _new_litter_suggestion(mother.current_herd, father, birth_date, may)
    else:
        return problem(400, "Bad Request", "breeding_id query parameter is required")

    herd = breeding.breeding_herd_id
    if not may(herd):
        return problem(403, "Forbidden", "Åtkomst nekad")

    if breeding.litter_number is None:  # a litter added without a certificate: the number it would get now
        if not numbered_by_certificate(breeding):
            return _no_litter_number(genebank)
        if breeding.birth_date is None:
            return problem(400, "Bad Request", "Breeding record has no birth_date.")
        litter_number = new_litter_number(herd, breeding.birth_date, lock=False)
        if litter_number is None:
            return problem(409, "litter_order_conflict", LITTER_BORN_BEFORE_NUMBERED)
        return jsonify(_first_slot_suggestion(herd, breeding.birth_date, litter_number, breeding)), 200

    try:
        result = suggest_individual_number(herd.herd, breeding)
    except ValueError as e:
        return problem(400, "Bad Request", str(e))

    return jsonify({**result, "breeding_id": breeding.id, "litter_number": breeding.litter_number}), 200


@individual_v2_create_bp.route("/v2/individual/number-check", methods=["POST"])
@json_login_required
def number_check_route():
    """The dry run of a paper registration: the paper's individual number against Stamboken's.

    The body names the litter as a registration does (breeding_id, or mother, father and birth_date), plus
    paper_number (what the paper says) and paper_certificate. Writes nothing; returns number_check's fields.
    """
    form = request.get_json(silent=True)
    if not isinstance(form, dict):
        return problem(400, "Bad Request", "Request body must be a JSON object")
    return paper_number_check(form, current_user, lambda herd: _can_register_in_herd(current_user, herd))


def paper_number_check(form, actor, may, genebank=None):
    """
    number-check's answer for the body `form`, as `actor` sees the holders, with `may(herd)` deciding the herd and
    `genebank` scoping the lookups (_in_genebank).
    """
    paper_number, paper_certificate = form.get("paper_number"), form.get("paper_certificate")
    if parse_number(paper_number) is None:
        return problem(400, "Bad Request", PAPER_NUMBER_REQUIRED)
    if refusal := _paper_outside(paper_number, genebank):
        return refusal
    if paper_certificate is not None and not isinstance(paper_certificate, str):
        return problem(400, "Bad Request", "paper_certificate must be a string")
    if form.get("breeding_id") is not None:
        breeding = _litter_in(Breeding.get_or_none(Breeding.id == _as_int(form["breeding_id"])), genebank)
        if breeding is None:
            return problem(404, "Not Found", f"Breeding {form['breeding_id']} not found")
        litter, herd = {"breeding": breeding}, breeding.breeding_herd_id
    else:
        key, refusal = _litter_key(form, genebank)
        if refusal:
            return refusal
        mother, father, birth_date = key
        breeding = Breeding.get_or_none(mother=mother, father=father, birth_date=birth_date)
        herd = breeding.breeding_herd_id if breeding is not None else mother.current_herd
        litter = (
            {"breeding": breeding}
            if breeding is not None
            else {"herd": herd, "birth_date": birth_date, "mother": mother, "father": father}
        )
    if not may(herd):
        return problem(403, "Forbidden", "Åtkomst nekad")
    return jsonify(number_check(actor, paper_number, paper_certificate=paper_certificate, **litter)), 200


@individual_v2_create_bp.route("/v2/individual/import", methods=["POST"])
@json_login_required
def import_individual():
    """Import an existing individual without a litter context (utan kull).

    Creates a minimal Breeding (no mother/father) so Individual.breeding is never
    null — Individual.as_dict() dereferences self.breeding.birth_date without a
    null guard (database.py ~L771), and cert issuance also loads Breeding.

    Decision — provided vs minted number:
      If the request supplies ``number`` (historical import), it must lie in the
      authorized herd's namespace (``{herd}-<digits>``) and is then stored as-is
      on the Individual; the Individual is created directly (bypassing
      ``_create_individual_record``'s number-mint logic). The minimal Breeding takes
      the litter number the number names (an earlier import's phantom litter with that
      number and birth date is reused; any other litter with it refuses the import), and
      the number must pass number_check against it.
      If ``number`` is omitted, ``_create_individual_record`` mints the number
      normally from the minimal Breeding.

    Required body fields: ``herd`` (string), ``birth_date`` (YYYY-MM-DD).
    Optional: ``number``, ``sex``, ``color``, ``name``, ``color_note``,
    ``eye_color``, ``claw_color``, ``belly_color``, ``hair_notes``, ``rex`` (boolean).
    """
    form = request.get_json(silent=True)
    if not form or not isinstance(form, dict):
        return problem(400, "Bad Request", "Request body must be a JSON object")

    herd_identifier = form.get("herd")
    if not herd_identifier:
        return problem(400, "Bad Request", "herd is required")
    if not isinstance(herd_identifier, str):
        return problem(400, "Bad Request", "herd must be a string")

    try:
        herd = Herd.get(Herd.herd == herd_identifier)
    except DoesNotExist:
        return problem(404, "Not Found", f"Herd {herd_identifier!r} not found")

    if not _can_register_in_herd(current_user, herd):
        return problem(403, "Forbidden", "Åtkomst nekad")

    birth_date_str = form.get("birth_date")
    if not birth_date_str:
        return problem(400, "Bad Request", "birth_date is required (YYYY-MM-DD)")

    try:
        birth_date = date_type.fromisoformat(birth_date_str)
    except (TypeError, ValueError):
        return problem(400, "Bad Request", "birth_date must be YYYY-MM-DD")

    provided_number = form.get("number")
    if provided_number is not None and not isinstance(provided_number, str):
        return problem(400, "Bad Request", "number must be a string")
    if provided_number and (
        len(provided_number) > 20
        or not re.fullmatch(rf"{re.escape(herd.herd)}-\d+", provided_number)
        or parse_number(provided_number) is None
    ):
        return problem(422, "Unprocessable Entity", f"number must match {herd.herd}-<digits> (max 20 characters)")

    if refusal := rex_problem(form):
        return refusal

    sex = form.get("sex")
    color_name = form.get("color")

    try:
        with DATABASE.atomic():
            # Serialise the herd/year litter-number space before reading it (mirrors
            # register_birth's FOR UPDATE pattern), so two concurrent imports for the
            # same herd/year can't compute the same litter_number and collide on
            # idx_breeding_herd_year_litter.
            lock_herd_year(herd, birth_date.year)

            breeding = None
            if provided_number:
                # The phantom litter is the litter the number names: a new one in front would push the herd's
                # real litters +1 and flag the breeders' correct papers as wrong.
                litter_number = parse_number(provided_number)[2]
                named = herd_year(herd, birth_date.year).where(Breeding.litter_number == litter_number).first()
                if named is not None:
                    # An earlier import's phantom litter (no parents, the same birth date) takes the siblings.
                    if (named.mother_id, named.father_id, named.birth_date) != (None, None, birth_date):
                        raise RosterActionError(
                            409,
                            "Conflict",
                            f"Kull {litter_number} år {birth_date.year} finns redan i besättning {herd.herd}: "
                            "importera kaninen i den kullen eller kontakta genbanksansvarig.",
                        )
                    breeding = named
            else:
                litter_number = suggest_litter_number(herd.herd, birth_date)["suggested"]

            if breeding is None:
                # Minimal Breeding — no mother/father; litter_number from the number or the suggestion.
                breeding = Breeding.create(
                    breeding_herd_id=herd,
                    mother=None,
                    father=None,
                    birth_date=birth_date,
                    litter_number=litter_number,
                )
            # Lock the row before Individual creation (mirrors create_individual).
            breeding = Breeding.select().where(Breeding.id == breeding.id).for_update().get()

            if provided_number:
                # The same check as a registration: year, position and the number free everywhere (voided too).
                check = number_check(current_user, provided_number, breeding=breeding)
                if check["status"] != "match":
                    raise RosterActionError(
                        409,
                        "number_conflict",
                        f"Numret {provided_number} går inte att importera.",
                        **conflict_extensions(check),
                    )
                # Historical import: store the caller-supplied number verbatim.
                individual = Individual.create(
                    number=provided_number,
                    origin_herd=herd,
                    breeding=breeding,
                    sex=sex,
                    name=form.get("name"),
                    color_note=form.get("color_note"),
                    eye_color=form.get("eye_color"),
                    claw_color=form.get("claw_color"),
                    belly_color=form.get("belly_color"),
                    hair_notes=form.get("hair_notes"),
                    rex=form.get("rex", False),
                    is_active=True,
                )
                if color_name:
                    try:
                        color_obj = Color.get(Color.name == color_name, Color.genebank == herd.genebank)
                        individual.color = color_obj
                        individual.save()
                    except DoesNotExist:
                        pass
                record_herd_tracking(individual, herd, birth_date, "BIRTH", current_user)
            else:
                individual = _create_individual_record(
                    herd,
                    breeding,
                    sex=sex,
                    color=color_name,
                    name=form.get("name"),
                    color_note=form.get("color_note"),
                    eye_color=form.get("eye_color"),
                    claw_color=form.get("claw_color"),
                    belly_color=form.get("belly_color"),
                    hair_notes=form.get("hair_notes"),
                    rex=form.get("rex", False),
                    signature=current_user,
                )
    except RosterActionError as e:
        return problem(e.status, e.title, e.detail, **e.extra)
    except IntegrityError:
        # The atomic() block rolled back — no orphan Breeding/Individual remains.
        if provided_number:
            # Caller supplied a number that already exists on another Individual.
            return problem(409, "Conflict", f"Individual number {provided_number!r} already exists")
        # Mint path: concurrent import for the same herd/year claimed the litter slot first.
        return problem(409, "Conflict", "Litter-number conflict: a concurrent import used the same slot. Please retry.")
    except DataError:
        return problem(422, "Unprocessable Entity", "One or more fields exceed the maximum allowed length")
    except ValueError as e:
        return problem(400, "Bad Request", str(e))

    response_data = {
        "individual": individual.as_dict(),
        "certificate": None,
        "certificate_error": None,
    }

    # Cache invalidation (best-effort)
    try:
        from utils.cache_invalidation import get_genebank_id_for_herd, trigger_invalidation

        for gid in get_genebank_id_for_herd(herd.herd):
            trigger_invalidation(gid)
    except Exception:
        logger.warning("Cache invalidation failed for individual %s", individual.number)

    return jsonify(response_data), 201


def _registration_refusal(breeding, may):
    """The problem response refusing a direct registration into `breeding` now, or None."""
    # Authorization: may the caller register in this herd
    if not may(breeding.breeding_herd_id):
        return problem(403, "Forbidden", "Åtkomst nekad")

    # Same minimum age as roster promotion — direct registration from litter
    # context must not bypass the 42-day rule. (The manual import route is
    # separate and stays exempt for historical rabbits.)
    if breeding.birth_date is None or (date_type.today() - breeding.birth_date).days < MIN_PROMOTE_AGE_DAYS:
        return problem(422, "too_young", f"Individual must be at least {MIN_PROMOTE_AGE_DAYS} days old to register")
    return None


def _live_individual(number, genebank=None):
    """The registered (not voided) individual with this number, or None; with `genebank`, only one of that genebank."""
    if not isinstance(number, str):
        return None
    found = Individual.get_or_none((Individual.number == number) & not_voided())
    return found if found is not None and _in_genebank(found.origin_herd, genebank) else None


def _in_genebank(herd, genebank):
    """
    The report's scope (4b): with `genebank`, a parent or litter of another genebank reads exactly as a missing one,
    before anything about it is said, so a link learns nothing outside its own genebank.
    """
    return genebank is None or (herd is not None and herd.genebank_id == genebank)


def _paper_outside(paper_number, genebank):
    """
    The report's scope (4b) for the paper's own number: a herd outside `genebank`, or no such herd, is refused alike
    before anything is looked up by the number, so a link never learns whether another genebank's rabbit holds it.
    None when the herd is the genebank's, or without `genebank`.
    """
    paper = parse_number(paper_number)
    if genebank is None or paper is None or _in_genebank(Herd.get_or_none(Herd.herd == paper[0]), genebank):
        return None
    detail = "Besättningen i individnumret finns inte i genbanken. Kontrollera numret på intyget."
    return problem(400, "Bad Request", detail, field="paper_number")


def _litter_in(breeding, genebank):
    return breeding if breeding is not None and _in_genebank(breeding.breeding_herd_id, genebank) else None


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _litter_key(values, genebank=None):
    """((mother, father, birth_date), None) naming the litter of a registration without breeding_id, or (None, 400)."""
    mother, father = _live_individual(values.get("mother"), genebank), _live_individual(values.get("father"), genebank)
    if mother is None or father is None:
        return None, problem(400, "Bad Request", "Välj mor och far bland registrerade kaniner.")
    try:
        birth_date = date_type.fromisoformat(values.get("birth_date"))
    except (TypeError, ValueError):
        return None, problem(400, "Bad Request", "Födelsedatum måste anges som ÅÅÅÅ-MM-DD.")
    return (mother, father, birth_date), None


def _new_litter_refusal(herd, father, birth_date, may):
    """The refusal of a new litter born in `herd` (the mother's) to `father`, or None."""
    if herd is None or not may(herd):  # a mother whose latest herd event left her in no herd
        return problem(403, "Forbidden", "Modern finns inte i en besättning där du får registrera kaniner.")
    # Any registered buck of the genebank may be the father, alive or not (as for "Ny parning").
    if father.origin_herd.genebank_id != herd.genebank_id:
        return problem(400, "Bad Request", "Fadern måste vara registrerad i samma genbank som modern.")
    if (date_type.today() - birth_date).days < MIN_PROMOTE_AGE_DAYS:
        return problem(
            422, "too_young", f"Kaninen måste vara minst {MIN_PROMOTE_AGE_DAYS} dagar gammal för att registreras."
        )
    return None


def _shortcut_litter(form, may, genebank=None):
    """The litter of a registration without breeding_id ("Lägg till kanin", the legacy add form's shortcut).

    The body names the litter by mother, father and birth_date, unique in the litter table: an existing litter
    is reused (legacy's "Kull hittad"). Otherwise the new litter, in the mother's herd, is validated here before
    anything is written. Returns (existing_breeding, new_litter_fields, refusal) with exactly one set.
    """
    key, refusal = _litter_key(form, genebank)
    if refusal:
        return None, None, refusal
    mother, father, birth_date = key
    existing = Breeding.get_or_none(mother=mother, father=father, birth_date=birth_date)
    if existing is not None:
        return existing, None, None

    herd = mother.current_herd
    if refusal := _new_litter_refusal(herd, father, birth_date, may):
        return None, None, refusal
    litter_size, litter_size6w = _as_int(form.get("litter_size")), _as_int(form.get("litter_size6w"))
    if litter_size is None or litter_size < 1:
        return None, None, problem(400, "Bad Request", "Ange antal födda (minst 1).")
    # The report's member may leave the count empty: it is the count born, preliminary, as in "Lägg till kull"
    # (RegisterLitter); elsewhere it is asked for.
    if (litter_size6w is None and genebank is None) or (litter_size6w is not None and litter_size6w < 1):
        return None, None, problem(400, "Bad Request", "Ange antal levande vid 6 veckor (minst 1).")
    if litter_size6w is not None and litter_size6w > litter_size:
        return None, None, problem(400, "Bad Request", LITTER_SIZE6W_ABOVE_BORN)
    try:
        # Rabbit gestation is 26–38 days: without a mating date, the mating is put 31 days before the birth
        # (the same default as "+ Ny kull").
        breed_date = (
            date_type.fromisoformat(form["breed_date"])
            if form.get("breed_date")
            else birth_date - timedelta(days=GESTATION_DAYS)
        )
    except (TypeError, ValueError):
        return None, None, problem(400, "Bad Request", "Parningsdatum måste anges som ÅÅÅÅ-MM-DD.")
    # The same rules as a mating plus a birth: dates, parent ages and sexes, gestation, overlapping litters.
    errors, _warnings = da.validate_breeding_dates(
        breed_date=breed_date, birth_date=birth_date, mother=mother, father=father, litter_size=litter_size
    )
    if errors:
        return None, None, problem(400, "Bad Request", " ".join(errors))
    new_litter = {
        "herd": herd,
        "mother": mother,
        "father": father,
        "birth_date": birth_date,
        "breed_date": breed_date,
        "litter_size": litter_size,
        "litter_size6w": litter_size6w,
    }
    return None, new_litter, None


def _create_litter(herd, mother, father, birth_date, breed_date, litter_size, litter_size6w):
    """
    Create the litter validated by _shortcut_litter, a count alive at 6 weeks of None as the count born, preliminary.
    Call inside the registration's transaction.
    """
    litter_number = new_litter_number(herd, birth_date, lock=True)
    # Breeding rows before Individual rows (the global lock order); the parents re-read under their lock,
    # as "Ny parning" does (a sale or an unpromote may have changed them since the check).
    lock_individuals([mother.id, father.id])
    mother_now, father_now = Individual.get_by_id(mother.id), Individual.get_by_id(father.id)
    if mother_now.voided or father_now.voided or mother_now.current_herd.id != herd.id:
        raise RosterActionError(409, "Conflict", "Mor eller far ändrades samtidigt. Försök igen.")
    # _shortcut_litter looked before any lock: a litter of the mother's (35-day rule) or a parent may have changed
    errors, _warnings = da.validate_breeding_dates(
        breed_date=breed_date, birth_date=birth_date, mother=mother_now, father=father_now, litter_size=litter_size
    )
    if errors:
        raise ValueError(" ".join(errors))
    if litter_number is None:
        raise RosterActionError(409, "litter_order_conflict", LITTER_BORN_BEFORE_NUMBERED)
    return Breeding.create(
        breeding_herd_id=herd,
        mother=mother,
        father=father,
        breed_date=breed_date,
        birth_date=birth_date,
        litter_size=litter_size,
        litter_size6w=litter_size if litter_size6w is None else litter_size6w,
        litter_size6w_preliminary=litter_size6w is None,
        litter_number=litter_number,
    )


def _new_litter_suggestion(herd, father, birth_date, may):
    """The number suggestion for the first rabbit of a litter not created yet: position 1 of the year's next."""
    if refusal := _new_litter_refusal(herd, father, birth_date, may):
        return refusal
    litter_number = new_litter_number(herd, birth_date, lock=False)
    if litter_number is None:
        return problem(409, "litter_order_conflict", LITTER_BORN_BEFORE_NUMBERED)
    return jsonify(_first_slot_suggestion(herd, birth_date, litter_number)), 200


def _first_slot_suggestion(herd, birth_date, litter_number, breeding=None):
    """The suggestion for the first rabbit of a litter that has no number yet (`breeding`: one that exists)."""
    blocked = "litter_size6w_required"  # a new litter: lifted by the litter_size6w the form sends with it
    certified = 0
    if breeding is not None:  # the quota of validate_first_certificate, which skips a litter with no number
        certified = (
            Individual.select()
            .where(
                (Individual.breeding == breeding.id)
                & not_voided()
                & (Individual.certificate.is_null(False) | Individual.digital_certificate.is_null(False))
            )
            .count()
        )
        blocked = (
            "litter_size6w_required"
            if breeding.litter_size6w is None
            else "certificate_quota_exceeded"
            if certified >= breeding.litter_size6w
            else None
        )
    return {
        "suggested": f"{herd.herd}-{birth_date:%y}{litter_number}1",
        "suggested_position": 1,
        "used_positions": [],
        "available_positions": list(range(1, HARD_CEILING + 1)),
        "current_count": 0,
        "max_count": HARD_CEILING,
        "limited_by": "ceiling",
        "can_register": True,
        "certified_count": certified,
        "certified_max_count": breeding.litter_size6w if breeding is not None else None,
        "past_6w": True,
        "can_issue_certificate": blocked is None,
        "certificate_blocked_reason": blocked,
        "breeding_id": breeding.id if breeding is not None else None,
        "litter_number": litter_number,
    }


def _may_register(herd, may_register):
    """The current user's own right to register in `herd`, or the intake queue's `may_register`."""
    return _can_register_in_herd(current_user, herd) or bool(may_register and herd is not None and may_register(herd))


def _can_register_in_herd(user, herd):
    """Check if user can register individuals in this herd (None: a mother whose herd is unknown)."""
    if herd is None:
        return False
    if user.is_admin:
        return True
    if user.is_manager and herd.genebank_id in (user.is_manager or []):
        return True
    if user.is_owner and herd.herd in (user.is_owner or []):
        return True
    return False
