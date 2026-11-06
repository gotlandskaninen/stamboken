"""
Bunny roster CRUD endpoints (v2).

Service functions and thin route handlers for managing the per-litter roster.
See ADR-0007 for blueprint conventions.
"""

import logging
from datetime import date, datetime

from flask import Blueprint, jsonify, request, session
from flask_login import current_user
from peewee import DataError, DoesNotExist, IntegrityError, fn
from utils.database import DATABASE, Breeding, Bunny, Color, Individual, User, lock_individuals
from utils.herd_tracking import HerdTrackingError, void_all_for_unpromote
from utils.individual_number_v2 import (
    CHOICES,
    LITTER_SIZE6W_ABOVE_BORN,
    PAPER_NUMBER_REQUIRED,
    RosterActionError,
    RosterAliveExceeds6w,
    _create_individual_record,
    check_litter_order,
    lock_litter,
    number_check,
    number_to_register,
    parse_number,
    provisional_number,
    record_number_choice,
    validate_first_certificate,
)

from .common import check_genebank_access, json_login_required, problem

logger = logging.getLogger(__name__)

bunny_v2_bp = Blueprint("bunny_v2", __name__, url_prefix="/api")

_VALID_FATES = {"undecided", "kept_unregistered", "sold_unregistered", "culled", "died"}
_PATCHABLE_FIELDS = {"observed_sex", "observed_color", "label", "notes", "fate"}
_ADD_FIELDS = {"observed_sex", "observed_color", "label", "notes"}
_PROMOTE_STRING_FIELDS = {
    "paper_certificate",
    "sex",
    "color",
    "name",
    "color_note",
    "eye_color",
    "claw_color",
    "belly_color",
    "hair_notes",
}

# Column widths for client-supplied CharFields (TextFields are type-checked only).
_STRING_FIELD_MAX_LENGTHS = {
    "label": Bunny.label.max_length,
    "observed_sex": Bunny.observed_sex.max_length,
    "observed_color": Bunny.observed_color.max_length,
    "name": Individual.name.max_length,
    "paper_certificate": Individual.certificate.max_length,
    "sex": Individual.sex.max_length,
}

# Sanity cap per add request — slots cap at 9 but rosters may hold non-keepers.
MAX_ADD_COUNT = 20

# Minimum age (days) before a bunny may be promoted to a registered Individual.
# Override in tests / config as needed.
MIN_PROMOTE_AGE_DAYS = 42

# Fate values that count as "not a keeper" — excluded from the promotion order.
# kept_unregistered bunnies will never be promoted, so they must not block the
# order gate and must not reserve a provisional slot.
_NON_KEEPER_FATES = ["registered", "died", "culled", "kept_unregistered", "sold_unregistered"]


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


def add_bunnies(breeding, count=1, **fields) -> list:
    """Add `count` new bunnies to a litter, starting after the current max slot_order.

    Must be called with only fields from _ADD_FIELDS (caller filters).
    Returns the created Bunny instances.
    """
    filtered = {k: v for k, v in fields.items() if k in _ADD_FIELDS}
    with DATABASE.atomic():
        locked = Breeding.select().where(Breeding.id == breeding.id).for_update().get()
        # Cap the roster at the reported litter size ("born"); rosters created
        # before litter_size was set (or legacy data without it) stay uncapped.
        if locked.litter_size is not None:
            current_count = Bunny.select().where(Bunny.breeding == breeding).count()
            if current_count + count > locked.litter_size:
                raise RosterActionError(
                    409,
                    "litter_full",
                    f"Kullen har redan {current_count} av {locked.litter_size} ungar",
                    litter_size=locked.litter_size,
                    current_count=current_count,
                )
        current_max = Bunny.select(fn.MAX(Bunny.slot_order)).where(Bunny.breeding == breeding).scalar() or 0
        created = []
        for i in range(count):
            bunny = Bunny.create(breeding=breeding, slot_order=current_max + 1 + i, **filtered)
            created.append(bunny)
        return created


def get_litter_roster(breeding) -> list:
    """Return the litter roster ordered by slot_order.

    Injects ``provisional_number`` into each unlinked bunny's dict so that
    database.py stays import-free of individual_number_v2.
    """
    bunnies = list(Bunny.select().where(Bunny.breeding == breeding).order_by(Bunny.slot_order))
    result = []
    for bunny in bunnies:
        d = bunny.as_dict()
        if bunny.individual_id is None:
            d["provisional_number"] = provisional_number(breeding, bunny)
        result.append(d)
    return result


def reorder_roster(breeding, ordered_ids) -> None:
    """Reassign slot_order 1..N in the order given by ``ordered_ids``.

    Raises ValueError if ``ordered_ids`` doesn't match this breeding's bunny set exactly.
    """
    with DATABASE.atomic():
        Breeding.select().where(Breeding.id == breeding.id).for_update().get()
        locked = list(Bunny.select().where(Bunny.breeding == breeding).for_update())
        existing_ids = {b.id for b in locked}
        if (
            len(ordered_ids) != len(existing_ids)
            or len(set(ordered_ids)) != len(ordered_ids)
            or set(ordered_ids) != existing_ids
        ):
            raise ValueError("ordered_ids must be exactly the set of this breeding's bunny ids with no duplicates")
        for slot, bunny_id in enumerate(ordered_ids, start=1):
            Bunny.update(slot_order=slot).where(Bunny.id == bunny_id).execute()


def patch_bunny(bunny, **fields) -> None:
    """Update allowed fields on a bunny.

    Locks the breeding row and re-reads the bunny before the registered-guard,
    then persists only the changed fields.
    Raises RosterActionError(409) if trying to change fate on a registered bunny.
    Raises ValueError if ``fate`` is not in _VALID_FATES.
    Unknown fields are silently ignored.
    """
    with DATABASE.atomic():
        try:
            Breeding.select().where(Breeding.id == bunny.breeding_id).for_update().get()
            bunny = Bunny.get_by_id(bunny.id)
        except DoesNotExist as exc:
            raise RosterActionError(404, "Not Found", f"Bunny {bunny.id} not found") from exc
        if "fate" in fields and bunny.individual_id is not None:
            raise RosterActionError(
                409, "registered", "Cannot change the fate of a registered bunny; unpromote it first"
            )
        updates = {}
        for k, v in fields.items():
            if k not in _PATCHABLE_FIELDS:
                continue
            if k == "fate" and v not in _VALID_FATES:
                raise ValueError(f"Invalid fate: {v!r}. Allowed: {sorted(_VALID_FATES)}")
            updates[k] = v
        if updates:
            for k, v in updates.items():
                setattr(bunny, k, v)
            bunny.save(only=[*updates, "updated_at"])


def delete_bunny(bunny) -> None:
    """Delete a bunny from the roster.

    Locks the breeding row and re-reads the bunny before the registered-check.
    Raises ValueError if the bunny is linked to a registered individual.
    """
    with DATABASE.atomic():
        try:
            Breeding.select().where(Breeding.id == bunny.breeding_id).for_update().get()
            bunny = Bunny.get_by_id(bunny.id)
        except DoesNotExist:
            return
        if bunny.individual_id is not None:
            raise ValueError("Cannot delete a bunny that is linked to a registered individual")
        bunny.delete_instance()


# ---------------------------------------------------------------------------
# Certificate issuance (number assigned ONLY after sign+upload succeed)
# ---------------------------------------------------------------------------


def _certificate_error_detail(exc) -> dict:
    """Build a transient RFC 9457 problem-detail *dict* for a failed cert issue.

    Returned inside the promote response (``certificate_error``) — NOT a DB
    field; the Individual stays promoted and the breeder can retry.
    """
    status = getattr(exc, "code", None) or 503
    detail = getattr(exc, "description", None) or str(exc) or "Certificate issuance failed"
    return {
        "type": "about:blank",
        "title": "certificate_issuance_failed",
        "status": status,
        "detail": detail,
    }


def _issue_digital_certificate(individual, user_id) -> int:
    """Generate, sign and store a v2 certificate for a freshly promoted Individual.

    Uses the cert v2 pipeline (blueprints/certificates.py issue flow): a signed
    WeasyPrint PDF, a DigitalCertificateV2 row whose token makes the intyg
    verifiable on /stamboken/verifiera, disk + S3 storage.

    Ordering: the number assignment and the certificate row live in one
    transaction — a signing/S3 failure rolls both back, so no number is left
    dangling. On failure this raises; the caller converts the exception into
    a transient ``certificate_error``.

    Returns the assigned digital certificate number on success.
    """
    # Lazy import: the cert pipeline pulls in heavy PDF/signing deps.
    import utils.data_access as da
    from utils.cert_service_v2 import assign_certificate_number, generate_and_store, invalidate_caches

    user = da.fetch_user_info(user_id)
    if user is None:
        raise ValueError("individual_lookup_failed")

    # The global MAX+1 number can collide with a concurrent issuance in
    # another litter (only our own Breeding row is locked) — the collision
    # surfaces as IntegrityError on the unique digital_certificate column
    # before any PDF work; retry with a recomputed number.
    last_exc = None
    for _ in range(3):
        try:
            with DATABASE.atomic():
                # This runs after the promote commit: lock the litter, then the rabbit (as unpromote does), and
                # decide on the re-read row. An unpromote may have voided it (its slot then frees), another
                # route certified it, or the promoter lost the right (the v2 issue route's rule).
                da.lock_individual_for_edit(individual.id)
                locked = Individual.get_by_id(individual.id)
                if locked.voided:
                    raise ValueError("individual_lookup_failed")
                if locked.certificate or locked.digital_certificate:
                    raise ValueError("certificate_exists")
                if not user.can_issue_certificate(locked):
                    raise ValueError("forbidden")
                # The quota under the litter lock too, or two concurrent digital promotions could both take
                # the last slot.
                validate_first_certificate(Breeding.get_by_id(locked.breeding_id))
                ind_dict = da.get_individual(locked.number, user_id)
                if ind_dict is None:
                    raise ValueError("individual_lookup_failed")
                assign_certificate_number(locked)
                generate_and_store(locked, user, ind_dict, user_id)
            invalidate_caches(locked)
            individual.digital_certificate = locked.digital_certificate
            return individual.digital_certificate
        except IntegrityError as exc:
            individual.digital_certificate = None
            last_exc = exc
        except Exception:
            # The DB assignment rolled back — clear the stale in-memory value
            # so the promote response doesn't advertise an unpersisted number.
            individual.digital_certificate = None
            raise
    raise last_exc


def certificate_choice_problem(certificate_type, paper_certificate, paper_number=None, resolution=None):
    """400 unless the registration comes with a certificate, paper (with its number) or digital.

    Decision 2026-10-30: a rabbit only gets an individual number together with a certificate;
    registering without one ("none", allowed by the legacy app) is no longer offered. A paper certificate
    also brings the individual number the paper says (paper_number), and optionally the breeder's choice
    after a number conflict (resolution: {expected_number, choice}).
    """
    if certificate_type not in ("paper", "digital"):
        return problem(400, "Bad Request", "Intyg krävs: välj pappersintyg eller digitalt intyg.")
    if certificate_type == "paper" and not paper_certificate:
        return problem(400, "Bad Request", "Intygsnummer krävs för pappersintyg.")
    if certificate_type == "paper" and parse_number(paper_number) is None:
        return problem(400, "Bad Request", PAPER_NUMBER_REQUIRED)
    if resolution is not None and not (isinstance(resolution, dict) and resolution.get("choice") in CHOICES):
        return problem(400, "Bad Request", "resolution must be {expected_number, choice}")
    return None


def _apply_certificate(individual, certificate_type, user_id):
    """Apply the chosen certificate to a freshly-created Individual.

    Called AFTER the promote transaction has committed, so the created
    Individual is kept regardless of cert outcome. Never raises: a
    digital-issuance failure is swallowed and surfaced as a transient
    ``certificate_error``. Returns ``(certificate_filename, error_dict)``.
    """
    if certificate_type == "paper":
        # _create_individual_record already stored the supplied paper number.
        return individual.certificate, None
    if certificate_type == "digital":
        try:
            number = _issue_digital_certificate(individual, user_id)
            return str(number), None
        except Exception as exc:  # noqa: BLE001 — any failure is a retryable cert error
            logger.warning("Digital certificate issuance failed for %s: %s", individual.number, exc)
            return None, _certificate_error_detail(exc)
    return None, None


# ---------------------------------------------------------------------------
# Promote / unpromote services
# ---------------------------------------------------------------------------


def promote_bunny(
    bunny_id,
    *,
    user,
    user_id=None,
    certificate_type,
    paper_certificate=None,
    paper_number=None,
    resolution=None,
    litter_size6w=None,
    sex=None,
    color=None,
    name=None,
    color_note=None,
    eye_color=None,
    claw_color=None,
    belly_color=None,
    hair_notes=None,
):
    """Promote a bunny to a registered Individual.

    Runs the whole 7-step flow inside ``DATABASE.atomic()`` with the herd/year's
    breeding rows, then the litter, ``SELECT … FOR UPDATE`` (lock_litter) so the
    litter's slot/number space is serialised. A paper certificate takes the paper's
    position when free and its number must match Stamboken's (number_check), or the
    breeder's resolution decides. Certificate issuance runs after the commit, in its
    own transaction, so a cert failure can never roll back the registration itself.

    Returns ``(individual, certificate_filename, certificate_error)``.
    Raises ``RosterActionError`` for any gate failure (403/404/409/422).
    """
    today = date.today()
    if certificate_type == "paper" and parse_number(paper_number) is None:
        raise RosterActionError(400, "Bad Request", PAPER_NUMBER_REQUIRED)

    try:
        bunny = Bunny.get_by_id(bunny_id)
    except DoesNotExist as exc:
        raise RosterActionError(404, "Not Found", f"Bunny {bunny_id} not found") from exc
    breeding_id = bunny.breeding_id

    with DATABASE.atomic():
        # Lock the litter; a concurrent breeding delete surfaces as 404.
        try:
            breeding = lock_litter(breeding_id)
        except DoesNotExist as exc:
            raise RosterActionError(404, "Not Found", "Breeding not found") from exc
        # Re-read the bunny under the lock (could have changed since the prelock read).
        try:
            bunny = Bunny.get_by_id(bunny_id)
        except DoesNotExist as exc:
            raise RosterActionError(404, "Not Found", f"Bunny {bunny_id} not found") from exc

        herd = breeding.breeding_herd_id

        # 1. Authorize — owner of the breeding herd, or genebank manager/admin.
        if not user.can_edit(herd.herd):
            raise RosterActionError(403, "Forbidden", "Åtkomst nekad")

        # 2. Litter-size precondition (the mint helper defaults max to 9 when
        #    null and would mint a colliding "…1" — guard explicitly).
        if breeding.litter_size is None:
            raise RosterActionError(422, "litter_size_required", "Litter size must be set before promotion")

        # 3. Age gate.
        if breeding.birth_date is None or (today - breeding.birth_date).days < MIN_PROMOTE_AGE_DAYS:
            raise RosterActionError(
                422, "too_young", f"Bunny must be at least {MIN_PROMOTE_AGE_DAYS} days old to promote"
            )

        # 4. Current-year litter-number conflict. Historical years are
        #    grandfathered — only the current year blocks registration.
        if breeding.birth_date.year == today.year:
            order = check_litter_order(herd.herd, breeding.birth_date.year)
            if not order["consistent"]:
                raise RosterActionError(
                    409,
                    "litter_order_conflict",
                    "Litter numbering conflicts must be resolved before registering this year's litters",
                    conflicts=order["conflicts"],
                )

        # 5. Order gate — must be the lowest-slot_order unpromoted keeper.
        lowest_keeper = (
            Bunny.select()
            .where((Bunny.breeding == breeding) & (Bunny.individual.is_null()) & (Bunny.fate.not_in(_NON_KEEPER_FATES)))
            .order_by(Bunny.slot_order, Bunny.id)
            .first()
        )
        if lowest_keeper is None or lowest_keeper.id != bunny.id:
            raise RosterActionError(409, "out_of_order", "Promote bunnies in slot order (lowest keeper first)")

        # 5b. Legacy-parity required fields, checked after the litter-structural
        #     gates so those trip first. A registered Individual must have a sex
        #     and an official genebank color; _create_individual_record silently
        #     drops unknown color names (lenient for legacy/import callers), so
        #     validate here where we can reject with a 422.
        effective_sex = sex if sex is not None else bunny.observed_sex
        if effective_sex not in ("male", "female"):
            raise RosterActionError(422, "sex_required", "Kön (hane/hona) måste anges vid registrering")
        effective_color = color if color is not None else bunny.observed_color
        if not effective_color:
            raise RosterActionError(422, "color_required", "Färg måste anges vid registrering")
        if not Color.select().where((Color.name == effective_color) & (Color.genebank == herd.genebank)).exists():
            raise RosterActionError(
                422, "unknown_color", f"Färgen '{effective_color}' finns inte i genbankens färglista"
            )

        # 5c. Certificate rules: litter_size6w declared, the roster in sync with it, and a free slot.
        #     Alive at 6 weeks sent with the registration is saved in this transaction: a refusal leaves it unset.
        if litter_size6w is not None and breeding.litter_size6w is None:
            if litter_size6w > breeding.litter_size:
                raise RosterActionError(422, "litter_size6w_above_born", LITTER_SIZE6W_ABOVE_BORN)
            breeding.litter_size6w = litter_size6w
            breeding.save(only=[Breeding.litter_size6w])
        try:
            validate_first_certificate(breeding)
        except RosterAliveExceeds6w as exc:
            raise RosterActionError(422, str(exc), exc.detail, must_mark_dead=exc.must_mark_dead) from exc
        except ValueError as exc:
            detail = (
                "Fyll i antal levande vid 6 veckor innan intyg kan utfärdas"
                if str(exc) == "litter_size6w_required"
                else "Kullen har inga fler intyg kvar"
            )
            raise RosterActionError(422, str(exc), detail) from exc

        # 5d. The paper's number against Stamboken's, under the lock: conflict → 409, nothing written.
        check = position = None
        if certificate_type == "paper":
            check = number_check(user, paper_number, breeding=breeding, paper_certificate=paper_certificate)
            try:
                position = parse_number(number_to_register(check, resolution))[3]
            except ValueError as exc:
                raise RosterActionError(422, "litter_full", str(exc)) from exc

        # 6. Mint + create the Individual (the helper mints under our lock).
        try:
            individual = _create_individual_record(
                herd,
                breeding,
                position=position,
                sex=effective_sex,
                color=effective_color,
                name=name,
                color_note=color_note,
                eye_color=eye_color,
                claw_color=claw_color,
                belly_color=belly_color,
                hair_notes=hair_notes,
                paper_certificate=paper_certificate if certificate_type == "paper" else None,
                signature=user,
            )
        except ValueError as exc:
            # litter_size / max_reached / position_* — a cap/validation failure (422, not 500).
            raise RosterActionError(422, "litter_full", str(exc)) from exc
        except IntegrityError as exc:
            # Duplicate certificate number or Individual.number — a conflict (409, not 500).
            raise RosterActionError(
                409, "conflict", "A conflict prevented registration — a certificate number may already be in use"
            ) from exc

        # 7. Link the bunny (the Meta.Check passes once individual is set).
        bunny.individual = individual
        bunny.fate = "registered"
        bunny.save()
        if check is not None and check["status"] != "match":
            record_number_choice(individual, user, check)

    # Certificate is a SEPARATE step AFTER the promote commit; never raises.
    certificate_filename, certificate_error = _apply_certificate(individual, certificate_type, user_id)

    return individual, certificate_filename, certificate_error


def unpromote_bunny(bunny_id):
    """Reverse a promotion: soft-void the Individual and free the bunny.

    Manager/admin only (``check_genebank_access`` — relies on ``current_user``,
    so call only from a request context). Same ``FOR UPDATE`` lock. Blocked once
    a certificate (paper or digital) has been issued.

    Returns ``(individual, bunny)`` (the voided Individual + the freed bunny).
    Raises ``RosterActionError`` (403/404/409).
    """
    try:
        bunny = Bunny.get_by_id(bunny_id)
    except DoesNotExist as exc:
        raise RosterActionError(404, "Not Found", f"Bunny {bunny_id} not found") from exc
    breeding_id = bunny.breeding_id

    with DATABASE.atomic():
        try:
            breeding = Breeding.select().where(Breeding.id == breeding_id).for_update().get()
        except DoesNotExist as exc:
            raise RosterActionError(404, "Not Found", "Breeding not found") from exc

        # Manager/admin only (unlike promote, owners may NOT unpromote).
        if check_genebank_access(breeding.breeding_herd_id.genebank_id) is not None:
            raise RosterActionError(403, "Forbidden", "Åtkomst nekad")

        try:
            bunny = Bunny.get_by_id(bunny_id)
        except DoesNotExist as exc:
            raise RosterActionError(404, "Not Found", f"Bunny {bunny_id} not found") from exc

        if bunny.individual_id is None:
            raise RosterActionError(409, "not_promoted", "Bunny is not promoted")

        # The same Individual lock register_breeding/update_breeding take on a new parent (Breeding
        # first, then the Individual): a mating either commits before this check or sees the void.
        lock_individuals([bunny.individual_id])
        individual = Individual.get_by_id(bunny.individual_id)
        if individual.certificate or individual.digital_certificate:
            raise RosterActionError(409, "certificate_issued", "Cannot unpromote an individual with a certificate")
        # A voided parent drops out of the genetics pedigree while its kits still name it.
        if Breeding.select().where((Breeding.mother == individual) | (Breeding.father == individual)).exists():
            raise RosterActionError(409, "has_offspring", "Cannot unpromote an individual that is a parent")

        # Soft-void: keep the row, retire its slot (never reissued).
        # Deactivate and void the herd-tracking rows the promotion created (never
        # deleted — DB trigger) so the individual no longer looks alive.
        individual.voided = True
        individual.voided_at = datetime.now()
        individual.is_active = False
        individual.save()

        try:
            void_all_for_unpromote(individual, User.get_by_id(current_user.id))
        except HerdTrackingError as exc:  # e.g. an admin's genebank correction: rolled back with the void above
            raise RosterActionError(exc.status, exc.title, exc.detail) from exc

        bunny.individual = None
        bunny.fate = "undecided"
        bunny.save()

    return individual, bunny


def _invalidate_herd_cache(individual) -> None:
    """Best-effort Next.js cache invalidation for the individual's origin herd."""
    try:
        from utils.cache_invalidation import get_genebank_id_for_herd, trigger_invalidation

        for gid in get_genebank_id_for_herd(individual.origin_herd.herd):
            trigger_invalidation(gid)
    except Exception:  # noqa: BLE001 — cache invalidation must never fail the request
        logger.warning("Cache invalidation failed for individual %s", individual.number)


# ---------------------------------------------------------------------------
# Route helpers
# ---------------------------------------------------------------------------


def _check_breeding_auth(breeding):
    """Return True if current_user may edit this breeding's herd."""
    herd = breeding.breeding_herd_id
    return current_user.can_edit(herd.herd)


def _validate_string_fields(body, field_names):
    """Return a problem detail for the first invalid string field, or None."""
    for name in sorted(field_names):
        value = body.get(name)
        if value is None:
            continue
        if not isinstance(value, str):
            return f"{name} must be a string"
        max_length = _STRING_FIELD_MAX_LENGTHS.get(name)
        if max_length is not None and len(value) > max_length:
            return f"{name} must be at most {max_length} characters"
    return None


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@bunny_v2_bp.route("/v2/breeding/<int:bid>/roster", methods=["GET"])
@json_login_required
def get_roster(bid):
    """GET /api/v2/breeding/<bid>/roster — list the litter roster."""
    try:
        breeding = Breeding.get_by_id(bid)
    except DoesNotExist:
        return problem(404, "Not Found", f"Breeding {bid} not found")

    if not _check_breeding_auth(breeding):
        return problem(403, "Forbidden", "Åtkomst nekad")

    roster = get_litter_roster(breeding)
    return jsonify({"roster": roster}), 200


@bunny_v2_bp.route("/v2/breeding/<int:bid>/bunnies", methods=["POST"])
@json_login_required
def add_bunnies_route(bid):
    """POST /api/v2/breeding/<bid>/bunnies — add one or more bunnies to a litter."""
    try:
        breeding = Breeding.get_by_id(bid)
    except DoesNotExist:
        return problem(404, "Not Found", f"Breeding {bid} not found")

    if not _check_breeding_auth(breeding):
        return problem(403, "Forbidden", "Åtkomst nekad")

    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return problem(400, "Bad Request", "Request body must be a JSON object")
    count = body.get("count", 1)
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_ADD_COUNT:
        return problem(400, "Bad Request", f"count must be an integer between 1 and {MAX_ADD_COUNT}")

    detail = _validate_string_fields(body, _ADD_FIELDS)
    if detail:
        return problem(400, "Bad Request", detail)

    fields = {k: body[k] for k in _ADD_FIELDS if k in body}
    try:
        bunnies = add_bunnies(breeding, count=count, **fields)
    except RosterActionError as exc:
        return problem(exc.status, exc.title, exc.detail, **exc.extra)
    except DataError:
        return problem(422, "Unprocessable Entity", "One or more fields exceed the maximum allowed length")
    return jsonify({"bunnies": [b.as_dict() for b in bunnies]}), 201


@bunny_v2_bp.route("/v2/bunny/<int:id>", methods=["PATCH"])
@json_login_required
def patch_bunny_route(id):
    """PATCH /api/v2/bunny/<id> — update fields on a bunny."""
    try:
        bunny = Bunny.get_by_id(id)
    except DoesNotExist:
        return problem(404, "Not Found", f"Bunny {id} not found")

    breeding = bunny.breeding
    if not _check_breeding_auth(breeding):
        return problem(403, "Forbidden", "Åtkomst nekad")

    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return problem(400, "Bad Request", "Request body must be a JSON object")

    detail = _validate_string_fields(body, _PATCHABLE_FIELDS - {"fate"})
    if detail:
        return problem(400, "Bad Request", detail)

    fields = {k: body[k] for k in _PATCHABLE_FIELDS if k in body}
    try:
        patch_bunny(bunny, **fields)
    except RosterActionError as exc:
        return problem(exc.status, exc.title, exc.detail, **exc.extra)
    except ValueError as exc:
        return problem(400, "Bad Request", str(exc))
    except DataError:
        return problem(422, "Unprocessable Entity", "One or more fields exceed the maximum allowed length")

    bunny_refreshed = Bunny.get_by_id(id)
    return jsonify(bunny_refreshed.as_dict()), 200


@bunny_v2_bp.route("/v2/breeding/<int:bid>/roster/reorder", methods=["POST"])
@json_login_required
def reorder_roster_route(bid):
    """POST /api/v2/breeding/<bid>/roster/reorder — reorder the litter roster."""
    try:
        breeding = Breeding.get_by_id(bid)
    except DoesNotExist:
        return problem(404, "Not Found", f"Breeding {bid} not found")

    if not _check_breeding_auth(breeding):
        return problem(403, "Forbidden", "Åtkomst nekad")

    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return problem(400, "Bad Request", "Request body must be a JSON object")
    ordered_ids = body.get("order")
    if not isinstance(ordered_ids, list) or not all(
        isinstance(i, int) and not isinstance(i, bool) for i in ordered_ids
    ):
        return problem(400, "Bad Request", "order must be a list of bunny ids")

    try:
        reorder_roster(breeding, ordered_ids)
    except ValueError as exc:
        return problem(400, "Bad Request", str(exc))

    roster = get_litter_roster(breeding)
    return jsonify({"roster": roster}), 200


@bunny_v2_bp.route("/v2/bunny/<int:id>", methods=["DELETE"])
@json_login_required
def delete_bunny_route(id):
    """DELETE /api/v2/bunny/<id> — remove a bunny from the roster."""
    try:
        bunny = Bunny.get_by_id(id)
    except DoesNotExist:
        return problem(404, "Not Found", f"Bunny {id} not found")

    breeding = bunny.breeding
    if not _check_breeding_auth(breeding):
        return problem(403, "Forbidden", "Åtkomst nekad")

    try:
        delete_bunny(bunny)
    except ValueError as exc:
        return problem(409, "Conflict", str(exc))

    return "", 204


@bunny_v2_bp.route("/v2/bunny/<int:id>/promote", methods=["POST"])
@json_login_required
def promote_bunny_route(id):
    """POST /api/v2/bunny/<id>/promote — register a bunny as an Individual."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return problem(400, "Bad Request", "Request body must be a JSON object")
    certificate_type = body.get("certificate_type")
    if refusal := certificate_choice_problem(
        certificate_type, body.get("paper_certificate"), body.get("paper_number"), body.get("resolution")
    ):
        return refusal

    detail = _validate_string_fields(body, _PROMOTE_STRING_FIELDS)
    if detail:
        return problem(400, "Bad Request", detail)
    litter_size6w = body.get("litter_size6w")
    if litter_size6w is not None:
        try:
            litter_size6w = int(litter_size6w)
        except (TypeError, ValueError):
            return problem(400, "Bad Request", "litter_size6w must be an integer")

    try:
        individual, certificate_filename, certificate_error = promote_bunny(
            id,
            user=current_user,
            user_id=session.get("user_id"),
            certificate_type=certificate_type,
            paper_certificate=body.get("paper_certificate"),
            paper_number=body.get("paper_number"),
            resolution=body.get("resolution"),
            litter_size6w=litter_size6w,
            sex=body.get("sex"),
            color=body.get("color"),
            name=body.get("name"),
            color_note=body.get("color_note"),
            eye_color=body.get("eye_color"),
            claw_color=body.get("claw_color"),
            belly_color=body.get("belly_color"),
            hair_notes=body.get("hair_notes"),
        )
    except RosterActionError as exc:
        return problem(exc.status, exc.title, exc.detail, **exc.extra)
    except DataError:
        return problem(422, "Unprocessable Entity", "One or more fields exceed the maximum allowed length")

    _invalidate_herd_cache(individual)
    return (
        jsonify(
            {
                "individual": individual.as_dict(),
                "certificate": certificate_filename,
                "certificate_error": certificate_error,
            }
        ),
        201,
    )


@bunny_v2_bp.route("/v2/bunny/<int:id>/unpromote", methods=["POST"])
@json_login_required
def unpromote_bunny_route(id):
    """POST /api/v2/bunny/<id>/unpromote — reverse a promotion (manager/admin)."""
    try:
        individual, bunny = unpromote_bunny(id)
    except RosterActionError as exc:
        return problem(exc.status, exc.title, exc.detail, **exc.extra)

    _invalidate_herd_cache(individual)
    return jsonify({"individual": individual.as_dict(), "bunny": bunny.as_dict()}), 200
