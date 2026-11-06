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
from flask import Blueprint, jsonify, request, session
from flask_login import current_user
from peewee import DataError, DoesNotExist, IntegrityError
from utils.database import DATABASE, Breeding, Color, Herd, Individual, lock_individuals, not_voided
from utils.herd_tracking import record_herd_tracking
from utils.individual_number_v2 import (
    HARD_CEILING,
    LITTER_SIZE6W_ABOVE_BORN,
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
    parse_number,
    record_number_choice,
    suggest_individual_number,
    suggest_litter_number,
    validate_first_certificate,
)

from .bunny_v2 import MIN_PROMOTE_AGE_DAYS, _apply_certificate, certificate_choice_problem
from .common import json_login_required, problem

logger = logging.getLogger(__name__)

GESTATION_DAYS = 31  # the middle of a rabbit's 26–38 days
LITTER_BORN_BEFORE_NUMBERED = (
    "Kullen är född före en kull som redan har kullnummer det året. Registrera den med "
    "+ Ny kull under Kullar och parningar och numrera om kullarna."
)

individual_v2_create_bp = Blueprint("individual_v2_create", __name__, url_prefix="/api")


@individual_v2_create_bp.route("/v2/individual", methods=["POST"])
@json_login_required
def create_individual():
    """Register a new individual from litter context. Returns 201 + full entity."""
    form = request.get_json(silent=True)
    if not form or not isinstance(form, dict):
        return problem(400, "Bad Request", "Request body must be a JSON object")

    breeding_id = form.get("breeding_id")
    new_litter = None  # "Lägg till kanin": the litter to create, when no breeding_id and no matching litter
    if breeding_id is None:
        breeding, new_litter, refusal = _shortcut_litter(form)
        if refusal:
            return refusal
    else:
        try:
            breeding_id = int(breeding_id)
        except (TypeError, ValueError):
            return problem(400, "Bad Request", "breeding_id must be an integer")

        try:
            breeding = Breeding.get_by_id(breeding_id)
        except DoesNotExist:
            return problem(404, "Not Found", f"Breeding {breeding_id} not found")

    if breeding is not None and (refusal := _registration_refusal(breeding)):
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

    form_litter_size6w = form.get("litter_size6w")
    if form_litter_size6w is not None:
        try:
            form_litter_size6w = int(form_litter_size6w)
        except (TypeError, ValueError):
            return problem(400, "Bad Request", "litter_size6w must be an integer")

    name = form.get("name")
    if name is not None and (not isinstance(name, str) or len(name) > 50):
        return problem(400, "Bad Request", "name must be a string of at most 50 characters")

    paper_certificate = form.get("paper_certificate") if certificate_type == "paper" else None
    if paper_certificate is not None and (not isinstance(paper_certificate, str) or len(paper_certificate) > 20):
        return problem(400, "Bad Request", "paper_certificate must be a string of at most 20 characters")

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
                lock_herd_year(new_litter["herd"], new_litter["birth_date"].year)
                if certificate_type == "paper":
                    litter = {key: new_litter[key] for key in ("herd", "birth_date", "mother", "father")}
                    check = number_check(current_user, paper_number, paper_certificate=paper_certificate, **litter)
                    position = parse_number(number_to_register(check, resolution))[3]
                breeding = _create_litter(**new_litter)
            else:
                breeding = lock_litter(breeding.id)
                # Decided again on the locked litter: it may have moved to another herd (or been renumbered or
                # re-dated) since the check above, and the rabbit is born in the locked litter's herd.
                if refusal := _registration_refusal(breeding):
                    return refusal
            herd = breeding.breeding_herd_id

            # If form provides litter_size6w and breeding doesn't have it yet,
            # persist BEFORE certificate validation so the quota check sees it.
            if form_litter_size6w is not None and breeding.litter_size6w is None:
                if breeding.litter_size is not None and form_litter_size6w > breeding.litter_size:
                    raise ValueError(LITTER_SIZE6W_ABOVE_BORN)
                breeding.litter_size6w = form_litter_size6w
                breeding.save(only=[Breeding.litter_size6w])

            # Validate certificate eligibility before creating anything: the same first-certificate
            # rules as promote (litter_size6w, roster in sync, quota).
            validate_first_certificate(breeding)
            if certificate_type == "paper" and check is None:
                check = number_check(current_user, paper_number, breeding=breeding, paper_certificate=paper_certificate)
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
                paper_certificate=paper_certificate,
                signature=current_user,
            )
            if check is not None and check["status"] != "match":
                record_number_choice(individual, current_user, check)
    except RosterActionError as e:
        return problem(e.status, e.title, e.detail, **e.extra)
    except RosterAliveExceeds6w as e:
        return problem(400, "Bad Request", str(e), must_mark_dead=e.must_mark_dead)
    except ValueError as e:
        return problem(400, "Bad Request", str(e))
    except IntegrityError:
        return problem(
            409, "Conflict", "A conflict prevented registration — a certificate number may already be in use"
        )
    except DataError:
        return problem(422, "Unprocessable Entity", "One or more fields exceed the maximum allowed length")

    # The certificate after the commit, as promote does: a failed digital issuance keeps the rabbit
    # and comes back as certificate_error.
    certificate, certificate_error = _apply_certificate(individual, certificate_type, session.get("user_id"))
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
    breeding_id = request.args.get("breeding_id", type=int)
    if breeding_id:
        try:
            breeding = Breeding.get_by_id(breeding_id)
        except DoesNotExist:
            return problem(404, "Not Found", f"Breeding {breeding_id} not found")
    elif "mother" in request.args:
        key, refusal = _litter_key(request.args)
        if refusal:
            return refusal
        mother, father, birth_date = key
        breeding = Breeding.get_or_none(mother=mother, father=father, birth_date=birth_date)
        if breeding is None:
            return _new_litter_suggestion(mother.current_herd, father, birth_date)
    else:
        return problem(400, "Bad Request", "breeding_id query parameter is required")

    herd = breeding.breeding_herd_id
    if not _can_register_in_herd(current_user, herd):
        return problem(403, "Forbidden", "Åtkomst nekad")

    if breeding.litter_number is None:
        return problem(400, "Bad Request", "Breeding record has no litter_number. Assign one first.")

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
    paper_number, paper_certificate = form.get("paper_number"), form.get("paper_certificate")
    if parse_number(paper_number) is None:
        return problem(400, "Bad Request", PAPER_NUMBER_REQUIRED)
    if paper_certificate is not None and not isinstance(paper_certificate, str):
        return problem(400, "Bad Request", "paper_certificate must be a string")
    if form.get("breeding_id") is not None:
        breeding = Breeding.get_or_none(Breeding.id == _as_int(form["breeding_id"]))
        if breeding is None:
            return problem(404, "Not Found", f"Breeding {form['breeding_id']} not found")
        litter, herd = {"breeding": breeding}, breeding.breeding_herd_id
    else:
        key, refusal = _litter_key(form)
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
    if not _can_register_in_herd(current_user, herd):
        return problem(403, "Forbidden", "Åtkomst nekad")
    return jsonify(number_check(current_user, paper_number, paper_certificate=paper_certificate, **litter)), 200


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
    ``eye_color``, ``claw_color``, ``belly_color``, ``hair_notes``.
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


def _registration_refusal(breeding):
    """The problem response refusing a direct registration into `breeding` now, or None."""
    # Authorization: check user can edit in this herd
    if not _can_register_in_herd(current_user, breeding.breeding_herd_id):
        return problem(403, "Forbidden", "Åtkomst nekad")

    # Validate litter_number exists
    if breeding.litter_number is None:
        return problem(400, "Bad Request", "Breeding record has no litter_number. Assign one first.")

    # Same minimum age as roster promotion — direct registration from litter
    # context must not bypass the 42-day rule. (The manual import route is
    # separate and stays exempt for historical rabbits.)
    if breeding.birth_date is None or (date_type.today() - breeding.birth_date).days < MIN_PROMOTE_AGE_DAYS:
        return problem(422, "too_young", f"Individual must be at least {MIN_PROMOTE_AGE_DAYS} days old to register")
    return None


def _live_individual(number):
    """The registered (not voided) individual with this number, or None."""
    if not isinstance(number, str):
        return None
    return Individual.get_or_none((Individual.number == number) & not_voided())


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _litter_key(values):
    """((mother, father, birth_date), None) naming the litter of a registration without breeding_id, or (None, 400)."""
    mother, father = _live_individual(values.get("mother")), _live_individual(values.get("father"))
    if mother is None or father is None:
        return None, problem(400, "Bad Request", "Välj mor och far bland registrerade kaniner.")
    try:
        birth_date = date_type.fromisoformat(values.get("birth_date"))
    except (TypeError, ValueError):
        return None, problem(400, "Bad Request", "Födelsedatum måste anges som ÅÅÅÅ-MM-DD.")
    return (mother, father, birth_date), None


def _new_litter_refusal(herd, father, birth_date):
    """The refusal of a new litter born in `herd` (the mother's) to `father`, or None."""
    if not _can_register_in_herd(current_user, herd):
        return problem(403, "Forbidden", "Modern finns inte i en besättning där du får registrera kaniner.")
    # Any registered buck of the genebank may be the father, alive or not (as for "Ny parning").
    if father.origin_herd.genebank_id != herd.genebank_id:
        return problem(400, "Bad Request", "Fadern måste vara registrerad i samma genbank som modern.")
    if (date_type.today() - birth_date).days < MIN_PROMOTE_AGE_DAYS:
        return problem(
            422, "too_young", f"Kaninen måste vara minst {MIN_PROMOTE_AGE_DAYS} dagar gammal för att registreras."
        )
    return None


def _shortcut_litter(form):
    """The litter of a registration without breeding_id ("Lägg till kanin", the legacy add form's shortcut).

    The body names the litter by mother, father and birth_date, unique in the litter table: an existing litter
    is reused (legacy's "Kull hittad"). Otherwise the new litter, in the mother's herd, is validated here before
    anything is written. Returns (existing_breeding, new_litter_fields, refusal) with exactly one set.
    """
    key, refusal = _litter_key(form)
    if refusal:
        return None, None, refusal
    mother, father, birth_date = key
    existing = Breeding.get_or_none(mother=mother, father=father, birth_date=birth_date)
    if existing is not None:
        return existing, None, None

    herd = mother.current_herd
    if refusal := _new_litter_refusal(herd, father, birth_date):
        return None, None, refusal
    litter_size, litter_size6w = _as_int(form.get("litter_size")), _as_int(form.get("litter_size6w"))
    if litter_size is None or litter_size < 1:
        return None, None, problem(400, "Bad Request", "Ange antal födda (minst 1).")
    if litter_size6w is None or litter_size6w < 1:
        return None, None, problem(400, "Bad Request", "Ange antal levande vid 6 veckor (minst 1).")
    if litter_size6w > litter_size:
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
    """Create the litter validated by _shortcut_litter. Call inside the registration's transaction."""
    litter_number = new_litter_number(herd, birth_date, lock=True)
    # Breeding rows before Individual rows (the global lock order); the parents re-read under their lock,
    # as "Ny parning" does (a sale or an unpromote may have changed them since the check).
    lock_individuals([mother.id, father.id])
    mother_now, father_now = Individual.get_by_id(mother.id), Individual.get_by_id(father.id)
    if mother_now.voided or father_now.voided or mother_now.current_herd.id != herd.id:
        raise RosterActionError(409, "Conflict", "Mor eller far ändrades samtidigt. Försök igen.")
    if litter_number is None:
        raise RosterActionError(409, "litter_order_conflict", LITTER_BORN_BEFORE_NUMBERED)
    return Breeding.create(
        breeding_herd_id=herd,
        mother=mother,
        father=father,
        breed_date=breed_date,
        birth_date=birth_date,
        litter_size=litter_size,
        litter_size6w=litter_size6w,
        litter_number=litter_number,
    )


def _new_litter_suggestion(herd, father, birth_date):
    """The number suggestion for the first rabbit of a litter not created yet: position 1 of the year's next."""
    if refusal := _new_litter_refusal(herd, father, birth_date):
        return refusal
    litter_number = new_litter_number(herd, birth_date, lock=False)
    if litter_number is None:
        return problem(409, "litter_order_conflict", LITTER_BORN_BEFORE_NUMBERED)
    suggestion = {
        "suggested": f"{herd.herd}-{birth_date:%y}{litter_number}1",
        "suggested_position": 1,
        "used_positions": [],
        "available_positions": list(range(1, HARD_CEILING + 1)),
        "current_count": 0,
        "max_count": HARD_CEILING,
        "limited_by": "ceiling",
        "can_register": True,
        "certified_count": 0,
        "certified_max_count": None,
        "past_6w": True,
        # Lifted by the litter_size6w the form sends with the new litter.
        "can_issue_certificate": False,
        "certificate_blocked_reason": "litter_size6w_required",
        "breeding_id": None,
        "litter_number": litter_number,
    }
    return jsonify(suggestion), 200


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
