"""
V2 individual number helpers.

Uses stored Breeding.litter_number instead of computed ROW_NUMBER ranking.
Keeps the format: {herd}-{YY}{litter_number}{position}
"""

import re
import uuid
from datetime import date, datetime, timedelta

from peewee import DoesNotExist, fn

from utils import number_assets
from utils.database import (
    DATABASE,
    Breeding,
    Bunny,
    Color,
    Herd,
    Individual,
    IndividualCommand,
    lock_individuals,
    not_voided,
)
from utils.herd_tracking import record_herd_tracking


class IndividualRenumberNotAllowed(Exception):
    """Raised inside the renumber lock when a renumber would change a LIVE (registered)
    Individual but the caller is not authorised for individual-affecting renumbers.

    Raising aborts the surrounding ``DATABASE.atomic()`` so no mutation is applied.
    """


class IndividualNumberConflict(Exception):
    """Raised inside the renumber lock when a target number is already held by an
    Individual outside the change set (e.g. a verbatim-imported number).

    Raising aborts the surrounding ``DATABASE.atomic()`` so no mutation is applied.
    ``conflicts`` lists the colliding numbers.
    """

    def __init__(self, conflicts: list[str]):
        super().__init__(", ".join(conflicts))
        self.conflicts = conflicts


class RosterActionError(Exception):
    """Service-layer failure carrying an RFC 9457 status/title/detail.

    Routes catch this and translate it into a ``problem(...)`` response so the
    promote/unpromote service stays Flask-free (and unit/concurrency testable).
    """

    def __init__(self, status, title, detail, **extra):
        super().__init__(detail)
        self.status = status
        self.title = title
        self.detail = detail
        self.extra = extra


def suggest_litter_number(herd_identifier: str, birth_date: date, exclude_breeding_id: int | None = None) -> dict:
    """Suggest a litter number for a new litter and detect conflicts.

    Args:
        herd_identifier: Herd string (e.g. "G1274")
        birth_date: Birth date of the candidate litter
        exclude_breeding_id: Optional Breeding id to leave out of the existing set
            (used at birth registration, where the candidate already exists as a
            row and must not be double-counted against itself).

    Returns:
        {"suggested": int, "conflicts": list[dict]}
    """
    herd = Herd.get(Herd.herd == herd_identifier)
    year = birth_date.year

    # Get all litters for this herd/year with litter_number set
    query = (
        Breeding.select(
            Breeding.id,
            Breeding.birth_date,
            Breeding.breed_date,
            Breeding.litter_number,
            Breeding.mother,
        )
        .where(Breeding.breeding_herd_id == herd)
        .where(
            DATABASE.extract_date(
                "year",
                fn.COALESCE(Breeding.birth_date, Breeding.breed_date + 30),
            )
            == year
        )
        .where(Breeding.birth_date.is_null(False) | Breeding.breed_date.is_null(False))
    )
    if exclude_breeding_id is not None:
        query = query.where(Breeding.id != exclude_breeding_id)
    litters = list(
        query.order_by(
            fn.COALESCE(Breeding.birth_date, Breeding.breed_date + 30),
            Breeding.id,
        )
    )

    # Build the correct chronological order including the candidate
    all_entries = []
    for lit in litters:
        lit_date = lit.birth_date or (lit.breed_date + timedelta(days=30) if lit.breed_date else None)
        all_entries.append(
            {
                "breeding_id": lit.id,
                "birth_date": str(lit_date),
                "current_litter_number": lit.litter_number,
                "mother": lit.mother.number if lit.mother else None,
                "is_candidate": False,
            }
        )
    all_entries.append(
        {
            "breeding_id": None,
            "birth_date": str(birth_date),
            "current_litter_number": None,
            "is_candidate": True,
        }
    )

    # Sort by date
    all_entries.sort(key=lambda e: e["birth_date"])

    # Assign correct numbers
    suggested = None
    conflicts = []
    for i, entry in enumerate(all_entries):
        correct_number = i + 1
        if entry["is_candidate"]:
            suggested = correct_number
        elif entry["current_litter_number"] != correct_number:
            conflicts.append(
                {
                    "breeding_id": entry["breeding_id"],
                    "current_litter_number": entry["current_litter_number"],
                    "suggested_litter_number": correct_number,
                    "birth_date": entry["birth_date"],
                    "mother": entry.get("mother"),
                }
            )

    return {"suggested": suggested, "conflicts": conflicts}


SIX_WEEKS = timedelta(days=42)
HARD_CEILING = 9


def _get_litter_state(herd_identifier: str, breeding: Breeding) -> dict:
    """Compute the available/used positions and capacity for a litter.

    Registration cap (max_count) only considers HARD_CEILING and litter_size —
    NOT litter_size6w. Certificate issuance has its own separate quota.

    Returns a dict with:
        prefix: number prefix (e.g. "G1274-261")
        used_positions: sorted list of currently used (live) positions
        retired_positions: sorted list of slots held by voided siblings (never reissued)
        available_positions: sorted free positions in 1..9 minus (used ∪ retired)
        current_count: number of live (non-voided) registered individuals
        blocked_count: size of (used ∪ retired) — what counts against the cap
        max_count: smallest of HARD_CEILING, litter_size
        limited_by: None or one of "ceiling" / "litter_size"
        certified_count: number of live individuals in this litter with a certificate
        certified_max_count: litter_size6w (only enforced past 6w), else None
        past_6w: whether today >= birth_date + 42 days (registration's minimum age)
    """
    if breeding.litter_number is None:
        raise ValueError("Breeding record has no litter_number set")
    birth_date = breeding.birth_date
    if birth_date is None:
        raise ValueError("Breeding record has no birth_date")

    year_suffix = str(birth_date.year)[2:4]
    prefix = f"{herd_identifier}-{year_suffix}{breeding.litter_number}"

    existing = list(
        Individual.select(
            Individual.number,
            Individual.certificate,
            Individual.digital_certificate,
            Individual.voided,
        )
        .where(Individual.breeding == breeding)
        .order_by(Individual.number)
    )

    used_positions: set[int] = set()
    retired_positions: set[int] = set()
    certified_count = 0
    for ind in existing:
        pos: int | None = None
        if ind.number and ind.number.startswith(prefix):
            try:
                parsed = int(ind.number[len(prefix) :])
                if 1 <= parsed <= HARD_CEILING:
                    pos = parsed
            except (ValueError, IndexError):
                pos = None
        # Voided (unpromoted) siblings retire their slot: never live, never reissued.
        if ind.voided:
            if pos is not None:
                retired_positions.add(pos)
            continue
        if pos is not None:
            used_positions.add(pos)
        if ind.certificate or ind.digital_certificate:
            certified_count += 1

    blocked_positions = used_positions | retired_positions

    # Registration cap: hard ceiling + litter_size (no 6w here — it only gates certs)
    max_count = HARD_CEILING
    limited_by = "ceiling"
    if breeding.litter_size is not None and breeding.litter_size < max_count:
        max_count = breeding.litter_size
        limited_by = "litter_size"

    # The day registration opens (age >= 42 days, MIN_PROMOTE_AGE_DAYS) the quota applies too.
    past_6w = date.today() >= birth_date + SIX_WEEKS
    certified_max_count = breeding.litter_size6w if past_6w else None

    available_positions = sorted(p for p in range(1, HARD_CEILING + 1) if p not in blocked_positions)

    return {
        "prefix": prefix,
        "used_positions": sorted(used_positions),
        "retired_positions": sorted(retired_positions),
        "available_positions": available_positions,
        "current_count": len(used_positions),
        "blocked_count": len(blocked_positions),
        "max_count": max_count,
        "limited_by": limited_by,
        "certified_count": certified_count,
        "certified_max_count": certified_max_count,
        "past_6w": past_6w,
    }


def suggest_individual_number(herd_identifier: str, breeding: Breeding) -> dict:
    """Suggest the next individual number for a litter without creating anything.

    Returns a dict combining registration state and certificate state.
    Certificate issuance is gated separately from registration (see design 2026-03-30).

    Raises:
        ValueError: if litter_number or birth_date is missing
    """
    state = _get_litter_state(herd_identifier, breeding)

    # The cap counts (used ∪ retired): retired slots are gone for good.
    can_register = state["blocked_count"] < state["max_count"] and len(state["available_positions"]) > 0
    suggested_position = state["available_positions"][0] if can_register else None
    suggested = f"{state['prefix']}{suggested_position}" if suggested_position is not None else None

    # Certificate eligibility: requires litter_size6w set, and quota not exceeded
    # (only enforced past 6w — before that we don't know yet how many will survive)
    litter_size6w_set = breeding.litter_size6w is not None
    if state["past_6w"] and not litter_size6w_set:
        can_issue_certificate = False
        certificate_blocked_reason = "litter_size6w_required"
    elif state["past_6w"] and state["certified_count"] >= breeding.litter_size6w:
        can_issue_certificate = False
        certificate_blocked_reason = "certificate_quota_exceeded"
    else:
        can_issue_certificate = True
        certificate_blocked_reason = None

    return {
        "suggested": suggested,
        "suggested_position": suggested_position,
        "used_positions": state["used_positions"],
        "available_positions": state["available_positions"],
        "current_count": state["current_count"],
        "max_count": state["max_count"],
        "limited_by": state["limited_by"],
        "can_register": can_register,
        "certified_count": state["certified_count"],
        "certified_max_count": state["certified_max_count"],
        "past_6w": state["past_6w"],
        "can_issue_certificate": can_issue_certificate,
        "certificate_blocked_reason": certificate_blocked_reason,
    }


def validate_certificate_allowed(herd_identifier: str, breeding: Breeding) -> None:
    """Raise ValueError if a certificate cannot be issued for this litter right now.

    Error keys (for i18n translation on frontend):
        - "litter_size6w_required": past 6w but litter_size6w not set
        - "certificate_quota_exceeded": past 6w and certified >= litter_size6w
    """
    state = _get_litter_state(herd_identifier, breeding)
    if not state["past_6w"]:
        return  # Before 6w, no certificate cap
    if breeding.litter_size6w is None:
        raise ValueError("litter_size6w_required")
    if state["certified_count"] >= breeding.litter_size6w:
        raise ValueError("certificate_quota_exceeded")


# Roster fates of a kit that is no longer alive ("culled" is the roster's Slaktad).
DEAD_FATES = ("died", "culled")

# Refusal where litter_size6w (alive at 6 weeks) is written above litter_size (born).
LITTER_SIZE6W_ABOVE_BORN = "Antal levande vid 6 veckor kan inte vara fler än antal födda."


class RosterAliveExceeds6w(ValueError):
    """More kits alive in the roster than litter_size6w says were alive at 6 weeks."""

    def __init__(self, alive: int, litter_size6w: int):
        super().__init__("roster_alive_exceeds_6w")
        self.must_mark_dead = alive - litter_size6w
        self.detail = (
            f"Kullen har {alive} levande i rostern men {litter_size6w} levande vid 6 veckor. "
            f"Markera {self.must_mark_dead} kaniner som döda innan intyg kan utfärdas."
        )


def validate_first_certificate(breeding: Breeding) -> None:
    """The rules for a rabbit's FIRST certificate, on every route that issues one.

    Call under the Breeding lock, with the litter read after any litter-size update, before the
    certificate is written. Reissues and paper→digital conversions are already counted: skip them.
    In a roster litter (litter_number and birth_date set) litter_size6w must be declared
    (litter_size6w_required), the roster may not have more kits alive than it
    (RosterAliveExceeds6w), and past 6 weeks the certificates may not exceed it
    (certificate_quota_exceeded). Pre-roster litters are exempt. Raises ValueError.
    """
    if breeding.litter_number is None or breeding.birth_date is None:
        return
    if breeding.litter_size6w is None:
        raise ValueError("litter_size6w_required")
    # Which kits died only the breeder knows: refuse until the roster agrees, never mark one here.
    alive = Bunny.select().where((Bunny.breeding == breeding) & Bunny.fate.not_in(DEAD_FATES)).count()
    if alive > breeding.litter_size6w:
        raise RosterAliveExceeds6w(alive, breeding.litter_size6w)
    validate_certificate_allowed(breeding.breeding_herd_id.herd, breeding)


def generate_individual_number(
    herd_identifier: str,
    breeding: Breeding,
    position: int | None = None,
    state: dict | None = None,
) -> str:
    """Generate (or validate) an individual number within a litter.

    Format: {herd}-{YY}{litter_number}{position}

    Args:
        herd_identifier: Herd string (e.g. "G1274")
        breeding: Breeding record with litter_number set
        position: Optional explicit position 1-9. If None, picks lowest available.
        state: The litter's _get_litter_state, when the caller has just read it.

    Returns:
        Generated number string

    Raises:
        ValueError: with an error key as message:
            - "litter_size" — litter_size cap reached
            - "max_reached" — 9-rabbit ceiling reached
            - "position_out_of_range" — position not in 1-9
            - "position_taken" — explicit position already in use

    Note: litter_size6w is NOT enforced here. It gates certificate issuance
    only, which is validated separately in the POST endpoint.
    """
    state = state or _get_litter_state(herd_identifier, breeding)

    # Capacity check — (used ∪ retired) against HARD_CEILING and litter_size.
    # Retired slots are permanently consumed, so they count toward the cap.
    if state["blocked_count"] >= state["max_count"]:
        raise ValueError(state["limited_by"] if state["limited_by"] != "ceiling" else "max_reached")

    if position is not None:
        if not (1 <= position <= HARD_CEILING):
            raise ValueError("position_out_of_range")
        if position in state["used_positions"] or position in state["retired_positions"]:
            raise ValueError("position_taken")
        return f"{state['prefix']}{position}"

    # Auto: lowest available (1..9 minus used ∪ retired)
    return f"{state['prefix']}{state['available_positions'][0]}"


def _create_individual_record(
    herd,
    breeding,
    *,
    position=None,
    sex=None,
    color=None,
    name=None,
    color_note=None,
    eye_color=None,
    claw_color=None,
    belly_color=None,
    hair_notes=None,
    paper_certificate=None,
    signature,
) -> Individual:
    """Create a single individual within a litter.

    Must be called inside the caller's atomic+locked block (e.g. Breeding FOR UPDATE).
    The mint runs here so it is included in the caller's lock, preventing races.

    Args:
        herd: Herd model instance
        breeding: Breeding model instance (locked FOR UPDATE by caller)
        position: Optional explicit slot 1–9; if None, picks the lowest available
        sex: "male", "female", or None
        color: Color name string or None; resolved against herd.genebank
        name, color_note, eye_color, claw_color, belly_color, hair_notes: Optional trait fields
        paper_certificate: When given, stored as individual.certificate
        signature: HbUser instance written to HerdTracking.signature

    Returns:
        Created Individual.

    Raises:
        ValueError: if the number cannot be minted (see generate_individual_number).
    """
    number = generate_individual_number(herd.herd, breeding, position=position)

    individual = Individual.create(
        number=number,
        origin_herd=herd,
        breeding=breeding,
        sex=sex,
        name=name,
        color_note=color_note,
        eye_color=eye_color,
        claw_color=claw_color,
        belly_color=belly_color,
        hair_notes=hair_notes,
        is_active=True,
    )

    if color:
        try:
            color_obj = Color.get(Color.name == color, Color.genebank == herd.genebank)
            individual.color = color_obj
            individual.save()
        except DoesNotExist:
            pass

    if paper_certificate:
        individual.certificate = paper_certificate
        individual.save()

    record_herd_tracking(individual, herd, breeding.birth_date or datetime.now().date(), "BIRTH", signature)

    return individual


def provisional_number(breeding: Breeding, bunny: Bunny) -> str | None:
    """Preview ("blir prel. …") number for an unpromoted Bunny.

    Simulates promoting, in ``slot_order``, the unpromoted non-``died``/``culled``
    Bunnies ahead of this one over ``available_positions`` (1..9 minus used ∪
    retired), then takes the next free slot. This equals the number
    ``generate_individual_number`` would mint, because promotion is order-
    constrained (the lowest-``slot_order`` keeper is promoted first).

    A ``count + rank`` shortcut is deliberately avoided: it breaks once an
    unpromote retires an early slot while the live ``used`` set starts higher.

    Returns ``None`` when no provisional number can be formed: the litter has no
    confirmed ``litter_number``/``birth_date``, the Bunny is already promoted or
    ``died``/``culled``, or the litter is full.
    """
    if breeding.litter_number is None or breeding.birth_date is None:
        return None
    # kept_/sold_unregistered will never be promoted — no provisional number (mirrors order gate).
    if bunny.individual_id is not None or bunny.fate in (
        "registered",
        "died",
        "culled",
        "kept_unregistered",
        "sold_unregistered",
    ):
        return None

    herd_identifier = breeding.breeding_herd_id.herd
    state = _get_litter_state(herd_identifier, breeding)
    available = state["available_positions"]

    ahead_count = (
        Bunny.select()
        .where(
            (Bunny.breeding == breeding)
            & (Bunny.individual.is_null())
            & (Bunny.fate.not_in(["registered", "died", "culled", "kept_unregistered", "sold_unregistered"]))
            & (Bunny.slot_order < bunny.slot_order)
        )
        .count()
    )

    if ahead_count >= len(available):
        return None
    return f"{state['prefix']}{available[ahead_count]}"


def check_litter_order(herd_identifier: str, year: int) -> dict:
    """Check if litter numbers match chronological birth_date order.

    Returns:
        {"consistent": bool, "conflicts": list[dict]}
    """
    herd = Herd.get(Herd.herd == herd_identifier)

    litters = list(
        Breeding.select(
            Breeding.id,
            Breeding.birth_date,
            Breeding.breed_date,
            Breeding.litter_number,
            Breeding.mother,
        )
        .where(Breeding.breeding_herd_id == herd)
        .where(
            DATABASE.extract_date(
                "year",
                fn.COALESCE(Breeding.birth_date, Breeding.breed_date + 30),
            )
            == year
        )
        .where(Breeding.litter_number.is_null(False))
        .order_by(
            fn.COALESCE(Breeding.birth_date, Breeding.breed_date + 30),
            Breeding.id,
        )
    )

    conflicts = []
    for i, lit in enumerate(litters):
        correct_number = i + 1
        if lit.litter_number != correct_number:
            # Count affected individuals
            affected = list(Individual.select(Individual.number).where(Individual.breeding == lit.id))
            conflicts.append(
                {
                    "breeding_id": lit.id,
                    "current_litter_number": lit.litter_number,
                    "suggested_litter_number": correct_number,
                    "birth_date": str(lit.birth_date or lit.breed_date),
                    "mother": lit.mother.number if lit.mother else None,
                    "affected_individuals": [ind.number for ind in affected],
                }
            )

    return {"consistent": len(conflicts) == 0, "conflicts": conflicts}


def _litter_change(herd_identifier: str, year_suffix: str, breeding: Breeding, new_number: int) -> dict:
    """Build the change dict for moving one breeding to ``new_number``.

    Moves ALL individuals with the breeding — voided ones too (Fix 2). A voided
    number must track its breeding's litter digit; the ``voided`` flag is carried
    so the renumber gate counts only LIVE individuals.
    """
    individuals = list(Individual.select().where(Individual.breeding == breeding.id))

    old_prefix = f"{herd_identifier}-{year_suffix}{breeding.litter_number}"
    new_prefix = f"{herd_identifier}-{year_suffix}{new_number}"

    ind_changes = []
    for ind in individuals:
        if ind.number.startswith(old_prefix):
            suffix = ind.number[len(old_prefix) :]
            ind_changes.append(
                {
                    "individual_id": ind.id,
                    "old_number": ind.number,
                    "new_number": f"{new_prefix}{suffix}",
                    "voided": bool(ind.voided),
                    "has_digital_certificate": ind.digital_certificate is not None,
                    "has_paper_certificate": ind.certificate is not None,
                }
            )

    return {
        "breeding_id": breeding.id,
        "old_litter_number": breeding.litter_number,
        "new_litter_number": new_number,
        "individuals": ind_changes,
    }


def _check_number_conflicts(changes: list[dict]) -> None:
    """Raise ``IndividualNumberConflict`` if a target number is already held by an
    Individual outside the change set (e.g. a verbatim-imported number).

    Must run under the caller's lock, right before ``_apply_changes`` — pass 2
    would otherwise hit the global unique index on ``Individual.number``.
    """
    change_ids = {ic["individual_id"] for c in changes for ic in c["individuals"]}
    new_numbers = [ic["new_number"] for c in changes for ic in c["individuals"]]
    if not new_numbers:
        return
    query = Individual.select(Individual.number).where(Individual.number.in_(new_numbers))
    if change_ids:
        query = query.where(Individual.id.not_in(change_ids))
    conflicts = sorted(ind.number for ind in query)
    if conflicts:
        raise IndividualNumberConflict(conflicts)


def _apply_changes(changes: list[dict]) -> None:
    """Apply litter/individual number changes under the caller's lock.

    Two-pass to dodge the unique indexes on Breeding.litter_number and
    Individual.number while the rows pass through transient values.

    The caller holds the Breeding locks; every affected Individual is then locked in ONE
    ascending call before the first UPDATE — updating in
    litter order would take them in an order that deadlocks against breeding registration.
    """
    lock_individuals([ic["individual_id"] for c in changes for ic in c["individuals"]])
    for change in changes:
        Breeding.update(litter_number=-change["new_litter_number"]).where(
            Breeding.id == change["breeding_id"]
        ).execute()
        for ind_change in change["individuals"]:
            Individual.update(number="~" + ind_change["new_number"]).where(
                Individual.id == ind_change["individual_id"]
            ).execute()

    for change in changes:
        Breeding.update(litter_number=change["new_litter_number"]).where(Breeding.id == change["breeding_id"]).execute()
        for ind_change in change["individuals"]:
            # updated_at is the photo URL's cache version: a swapped number must not reuse the old URL.
            Individual.update(number=ind_change["new_number"], updated_at=datetime.now()).where(
                Individual.id == ind_change["individual_id"]
            ).execute()

    # Certificates and photos follow the number: staged now, put in place after the commit.
    for change in changes:
        for ic in change["individuals"]:
            number_assets.record(ic["individual_id"], ic["old_number"], ic["new_number"], ic["has_digital_certificate"])


@number_assets.finishing
def renumber_litters(
    herd_identifier: str,
    year: int,
    confirm: bool = False,
    allow_individual_changes: bool = True,
) -> dict:
    """Renumber all litters for a herd/year to match chronological birth_date order.

    Args:
        herd_identifier: Herd string
        year: Year to renumber
        confirm: If False, returns preview only. If True, applies changes.
        allow_individual_changes: When ``confirm`` is True, if a LIVE (registered)
            Individual would be renumbered and this is False, raise
            ``IndividualRenumberNotAllowed`` *inside the lock* (aborts the
            transaction). Lets the caller enforce the auth atomically with the apply.

    Returns:
        ``{"changes": list[dict], "affected_individuals": int}`` -- preview or applied
        changes plus the count of LIVE Individuals whose number changes (the renumber gate).

    When ``confirm`` is True the affected ``Breeding`` rows are locked
    ``FOR UPDATE`` (deterministic order) *before* the change set is recomputed
    inside the lock — a stale pre-lock preview could otherwise miss a concurrent
    promote/direct-create in the same litter space.

    Raises ``IndividualNumberConflict`` under the lock (aborting the transaction)
    when a target number is already held by an Individual outside the change set.

    Fix 2: a renumbered breeding moves **all** its Individuals — including voided
    ones — so every number reflects its breeding's current ``litter_number``. A
    voided slot stays retired in the *new* namespace (``_get_litter_state`` re-reads
    it against the new prefix), so the slot is never reissued to a live individual
    in its litter, but it also never orphans a stale ``…{old}X`` that a litter
    swapping into the old namespace could collide with.
    """
    herd = Herd.get(Herd.herd == herd_identifier)
    year_suffix = str(year)[2:4]

    def _year_filter():
        return (
            Breeding.select()
            .where(Breeding.breeding_herd_id == herd)
            .where(
                DATABASE.extract_date(
                    "year",
                    fn.COALESCE(Breeding.birth_date, Breeding.breed_date + 30),
                )
                == year
            )
            .where(Breeding.litter_number.is_null(False))
        )

    def _compute_changes():
        litters = list(
            _year_filter().order_by(
                fn.COALESCE(Breeding.birth_date, Breeding.breed_date + 30),
                Breeding.id,
            )
        )
        changes = []
        for i, lit in enumerate(litters):
            new_number = i + 1
            if lit.litter_number == new_number:
                continue
            changes.append(_litter_change(herd_identifier, year_suffix, lit, new_number))
        return changes

    def _affected_live(changes: list[dict]) -> int:
        # Renumber gate: only LIVE (non-voided) individuals count as "renumbering a
        # registered individual"; voided slots are bookkeeping.
        return sum(1 for c in changes for ic in c["individuals"] if not ic["voided"])

    if not confirm:
        changes = _compute_changes()
        return {"changes": changes, "affected_individuals": _affected_live(changes)}

    with DATABASE.atomic():
        # Lock ALL litters for this herd/year first (deterministic order), then
        # recompute the change set under the lock.
        list(_year_filter().order_by(Breeding.id).for_update())
        changes = _compute_changes()
        affected_live = _affected_live(changes)

        # Under the lock: abort (rollback) if a live individual would change and
        # the caller is not authorised — a promote could have landed a live
        # individual into a renumbered litter since any unlocked preview.
        if affected_live and not allow_individual_changes:
            raise IndividualRenumberNotAllowed()

        if changes:
            _check_number_conflicts(changes)
            _apply_changes(changes)

    return {"changes": changes, "affected_individuals": affected_live}


@number_assets.finishing
def set_litter_number(breeding_id: int, new_litter_number: int, allow_individual_changes: bool = True) -> dict:
    """Set the litter number for a single breeding, moving its Individuals with it.

    Locks the Breeding row FOR UPDATE and re-reads it, then reuses the same
    change/apply machinery as ``renumber_litters``: every Individual whose number
    carries the old prefix moves to the new prefix — voided ones too — and
    certificate flags are carried in the change set.

    Args:
        breeding_id: Breeding id
        new_litter_number: Target litter number
        allow_individual_changes: When False and any LIVE (non-voided) Individual
            belongs to the breeding, raise ``IndividualRenumberNotAllowed`` inside
            the lock (aborts the transaction) — the renumber gate.

    Returns:
        One change dict (same shape as the ``renumber_litters`` changes entries).

    Raises:
        DoesNotExist: the breeding disappeared before the lock was taken.
        IndividualRenumberNotAllowed: renumber gate (see ``allow_individual_changes``).
        IndividualNumberConflict: a target number is held outside the change set.
    """
    with DATABASE.atomic():
        breeding = Breeding.select().where(Breeding.id == breeding_id).for_update().get()

        change = {
            "breeding_id": breeding.id,
            "old_litter_number": breeding.litter_number,
            "new_litter_number": new_litter_number,
            "individuals": [],
        }
        if breeding.litter_number == new_litter_number:
            return change

        has_live = (
            Individual.select(Individual.id)
            .where(Individual.breeding == breeding)
            .where(Individual.voided == False)  # noqa: E712 — peewee ORM requires == not `is`
            .exists()
        )
        if has_live and not allow_individual_changes:
            raise IndividualRenumberNotAllowed()

        ref_date = breeding.birth_date or (breeding.breed_date + timedelta(days=30) if breeding.breed_date else None)
        if ref_date is not None:
            herd_identifier = breeding.breeding_herd_id.herd
            change = _litter_change(herd_identifier, str(ref_date.year)[2:4], breeding, new_litter_number)

        if change["individuals"]:
            _check_number_conflicts([change])
            _apply_changes([change])
        else:
            breeding.litter_number = new_litter_number
            breeding.save(only=[Breeding.litter_number])

    return change


# ---------------------------------------------------------------------------
# The paper certificate's individual number against Stamboken's
# ---------------------------------------------------------------------------

# Herd, two year digits, the litter number, one position digit: G1274-2512, G1274-25102.
NUMBER_PATTERN = re.compile(r"([A-Za-z]+\d+)-(\d{2})(\d+)(\d)")
PAPER_NUMBER_REQUIRED = "Skriv individnumret som det står på pappersintyget, till exempel G1274-2512."
DUPLICATE_LITTER_DAYS = 35  # a litter of the same mother this close is the same litter registered twice
CHOICES = ("use_stamboken_number", "paper_is_right")
ONLY_PAPER_IS_RIGHT = {"litter_order", "prefix", "year"}  # facts the breeder must correct, not the paper


def parse_number(number):
    """(herd, year digits, litter number, position) of an individual number, or None when it has another form."""
    if not isinstance(number, str) or len(number.strip()) > Individual.number.max_length:
        return None
    match = NUMBER_PATTERN.fullmatch(number.strip())
    return (match[1].upper(), match[2], int(match[3]), int(match[4])) if match else None


def litter_mismatch(number, litter, right):
    """The refusal of a number its litter does not give (legacy's add form and the write commands)."""
    return (
        f"Numret {number} stämmer inte med kullen (kull {litter.litter_number} år {litter.birth_date.year}). "
        f"Använd {right} eller kontakta genbanksansvarig."
    )


def herd_year(herd, year):
    """The herd's litters of `year`; a litter not born yet counts from its mating date + 30 days."""
    return Breeding.select().where(
        (Breeding.breeding_herd_id == herd)
        & (DATABASE.extract_date("year", fn.COALESCE(Breeding.birth_date, Breeding.breed_date + 30)) == year)
    )


def lock_herd_year(herd, year):
    """Lock the herd's litters of `year` in id order: the litter-number space, locked before any own litter."""
    return list(herd_year(herd, year).order_by(Breeding.id).for_update())


def litter_year(breeding):
    ref = breeding.birth_date or (breeding.breed_date + timedelta(days=30) if breeding.breed_date else None)
    return ref.year if ref else None


def lock_litter(breeding_id):
    """The litter locked in the global order: its herd/year's litters in id order first (the litter-number space
    the number check reads), then the litter itself. Moved to another herd or year meanwhile: 409, retry.
    Raises DoesNotExist when the litter is gone.
    """
    seen = Breeding.get_by_id(breeding_id)
    key = (seen.breeding_herd_id_id, litter_year(seen))
    if key[1] is not None:
        lock_herd_year(*key)
    locked = Breeding.select().where(Breeding.id == breeding_id).for_update().get()
    if (locked.breeding_herd_id_id, litter_year(locked)) != key:
        raise RosterActionError(409, "Conflict", "Kullen ändrades samtidigt. Försök igen.")
    return locked


def new_litter_number(herd, birth_date, *, lock):
    """The number of a new litter born on `birth_date` in `herd`: the year's next, or None when a numbered litter
    of that year is born later (litters are numbered by birth date; fitting one in needs a renumber).

    max+1 rather than suggest_litter_number's chronological position, which collides with an existing number
    when the year has a gap (a deleted litter). With `lock`, the herd/year rows are locked first (as
    import_individual does), so two registrations cannot take the same number.
    """
    query = herd_year(herd, birth_date.year).order_by(Breeding.id)
    numbered = [b for b in (query.for_update() if lock else query) if b.litter_number is not None]
    if any((b.birth_date or b.breed_date + timedelta(days=30)) > birth_date for b in numbered):
        return None
    return max((b.litter_number for b in numbered), default=0) + 1


def _litter_text(litter):
    parts = [f"parning {litter.breed_date}" if litter.breed_date else None]
    parts.append(f"född {litter.birth_date}" if litter.birth_date else None)
    return ", ".join(part for part in parts if part) or None


def _number_in(litter):
    first = Individual.select(Individual.number).where(Individual.breeding == litter).order_by(Individual.number)
    return first.scalar()


def number_check(
    user,
    paper_number,
    *,
    breeding=None,
    individual=None,
    herd=None,
    birth_date=None,
    mother=None,
    father=None,
    paper_certificate=None,
):
    """Compare the individual number a paper certificate says with the one Stamboken gives (the dry run).

    Stamboken's number never comes from the paper: in an existing `breeding` the slot generate_individual_number
    mints, at the paper's position when that is free and not retired; for a litter not created yet (`herd`,
    `birth_date`, `mother`, `father`) the litter new_litter_number creates, at the paper's position; for an
    existing `individual` (the write commands) its own number under its litter's prefix. A pure read: callers
    that write lock the herd/year rows first. `paper_number` must parse (parse_number).

    Returns {stamboken_number, paper_number, status (match | conflict | uncomputable), conflicts, choices,
    actions}, plus reason (generate_individual_number's error key) when the litter has no slot to give.
    """
    paper = parse_number(paper_number)
    canonical = f"{paper[0]}-{paper[1]}{paper[2]}{paper[3]}"
    new_litter = breeding is None and individual is None
    if individual is not None:
        breeding = Breeding.get_or_none(Breeding.id == individual.breeding_id)
    if breeding is not None:
        herd, birth_date = breeding.breeding_herd_id, breeding.birth_date
        mother, father = breeding.mother, breeding.father
    stamboken, reason, later_litter = None, None, None
    if new_litter and birth_date is not None:
        litter_number = new_litter_number(herd, birth_date, lock=False)
        if litter_number is None:
            born = fn.COALESCE(Breeding.birth_date, Breeding.breed_date + 30)  # as new_litter_number counts
            later_litter = (
                herd_year(herd, birth_date.year)
                .where(Breeding.litter_number.is_null(False) & (born > birth_date))
                .order_by(born, Breeding.id)
                .first()
            )
        else:
            position = paper[3] if 1 <= paper[3] <= HARD_CEILING else 1
            stamboken = f"{herd.herd}-{birth_date:%y}{litter_number}{position}"
    elif breeding is not None and breeding.litter_number is not None and birth_date is not None:
        if individual is not None:
            own = parse_number(individual.number)
            if own is not None:
                stamboken = f"{herd.herd}-{birth_date:%y}{breeding.litter_number}{own[3]}"
        else:
            state = _get_litter_state(herd.herd, breeding)
            free = paper[3] in state["available_positions"]
            try:
                stamboken = generate_individual_number(
                    herd.herd, breeding, position=paper[3] if free else None, state=state
                )
            except ValueError as exc:
                reason = str(exc)

    accessible = set(user.accessible_genebanks)
    managed = set(user.is_manager or [])

    def holder(rabbit=None, litter=None):
        """The rabbit or litter that holds what the paper says, if it is in a genebank the user may see."""
        if litter is None and rabbit is not None:
            litter = Breeding.get_or_none(Breeding.id == rabbit.breeding_id)
        place = rabbit.current_herd if rabbit is not None else litter.breeding_herd_id
        if place is None or place.genebank_id not in accessible:
            return None
        found = {
            "number": rabbit.number if rabbit is not None else _number_in(litter),
            "herd": place.herd,
            "breeding_id": litter.id if litter is not None else None,
            "litter_number": litter.litter_number if litter is not None else None,
            "litter": _litter_text(litter) if litter is not None else None,
        }
        if user.is_admin or place.genebank_id in managed:
            found["contactable"] = place.membership_id is not None  # reachable through the member register
        return found

    exclude = individual.id if individual is not None else None
    conflicts = []
    if stamboken is not None:
        ours = parse_number(stamboken)
        for kind, i in (("prefix", 0), ("year", 1), ("litter", 2), ("position", 3)):
            if paper[i] == ours[i]:
                continue
            found = None
            if kind == "litter":
                kind = "litter_missing" if new_litter else "litter"
                other = herd_year(herd, birth_date.year).where(Breeding.litter_number == paper[2]).first()
                found = holder(litter=other) if other is not None else None
            elif kind == "position":
                sibling = Individual.get_or_none(Individual.number == f"{stamboken[:-1]}{paper[3]}")
                found = holder(rabbit=sibling) if sibling is not None else None
            conflicts.append({"kind": kind, "paper": str(paper[i]), "stamboken": str(ours[i]), "holder": found})
    elif later_litter is not None:
        conflicts.append(
            {"kind": "litter_order", "paper": str(paper[2]), "stamboken": None, "holder": holder(litter=later_litter)}
        )

    others = Individual.id != (exclude or 0)
    # As typed too: a legacy row may hold the zero-padded form (G1274-25012) parse_number canonicalises away.
    taken = Individual.get_or_none(Individual.number.in_([canonical, paper_number.strip().upper()]) & others)
    if taken is not None:  # voided too: a retired number is never reissued
        conflicts.append({"kind": "number_taken", "paper": canonical, "stamboken": stamboken, "holder": holder(taken)})
    owner = None
    if paper_certificate:
        owner = Individual.get_or_none((Individual.certificate == paper_certificate) & others)
        if owner is not None:
            litter = Breeding.get_or_none(Breeding.id == owner.breeding_id)
            known = mother is not None and father is not None and litter is not None
            same = known and (litter.mother_id, litter.father_id, litter.birth_date) == (
                mother.id,
                father.id,
                birth_date,
            )
            kind = "duplicate_rabbit" if same else "certificate_taken"
            conflicts.append({"kind": kind, "paper": paper_certificate, "stamboken": None, "holder": holder(owner)})
    if individual is None and breeding is not None and (mother is not None or father is not None):
        # A sibling registered without a certificate (and not a roster kit) may be this very rabbit; not in an
        # import's phantom litter, whose rabbits share no known parents.
        siblings = Individual.select().where(
            (Individual.breeding == breeding)
            & not_voided()
            & Individual.certificate.is_null()
            & Individual.digital_certificate.is_null()
            & Individual.id.not_in(Bunny.select(Bunny.individual).where(Bunny.individual.is_null(False)))
        )
        for sibling in siblings.order_by(Individual.number):
            conflicts.append({"kind": "duplicate_rabbit", "paper": None, "stamboken": None, "holder": holder(sibling)})
    if individual is None and mother is not None and birth_date is not None:
        window = timedelta(days=DUPLICATE_LITTER_DAYS)
        near = Breeding.select().where(
            (Breeding.mother == mother)
            & Breeding.birth_date.between(birth_date - window, birth_date + window)
            & (Breeding.id != (breeding.id if breeding is not None else 0))
        )
        for other in near.order_by(Breeding.birth_date, Breeding.id):
            found = holder(litter=other)
            conflicts.append(
                {"kind": "duplicate_litter", "paper": None, "stamboken": str(other.birth_date), "holder": found}
            )

    if stamboken is None and later_litter is None:
        status = "uncomputable"
    else:
        status = "conflict" if conflicts else "match"
    choices = [] if status == "match" else ["paper_is_right"]
    # Stamboken's number with this certificate must also survive the unique indexes (number, certificate).
    collides = owner is not None or (taken is not None and canonical == stamboken)
    if (
        status == "conflict"
        and stamboken is not None
        and not collides
        and not ONLY_PAPER_IS_RIGHT & {c["kind"] for c in conflicts}
    ):
        choices.insert(0, "use_stamboken_number")
    litter_facts = {
        "herd": herd.herd if herd is not None else None,
        "birth_date": birth_date,
        "mother": getattr(mother, "number", None),
        "father": getattr(father, "number", None),
    }
    result = {
        "stamboken_number": stamboken,
        "paper_number": canonical,
        "status": status,
        "conflicts": conflicts,
        "choices": choices,
        "actions": [_action(c, canonical, stamboken, litter_facts) for c in conflicts],
    }
    if reason is not None:
        result["reason"] = reason
    return result


def _action(conflict, paper, stamboken, litter):
    """What the breeder must do when the paper is right, per kind: a text, a link and a message to the manager."""
    kind, held = conflict["kind"], conflict["holder"] or {}
    herd, born = litter["herd"], litter["birth_date"]
    litters = f"/stamboken/min-besattning?herd={herd}&tab=breeding"
    rabbit = f"/stamboken/individ/{held['number']}" if held.get("number") else None
    where = (
        f"kanin {held['number']} i besättning {held['herd']}" if held.get("number") else "en kanin i en annan genbank"
    )
    claim = None
    if kind == "litter":
        first = "inte registrerad i Stamboken"
        if held:
            first = f"kullen {held['litter']}" + (f" ({held['number']}…)" if held["number"] else "")
        text = (
            f"Kull {conflict['paper']} år {born.year} är {first}. Är din kanin född före den: rätta kullens "
            "födelsedatum eller lägg in den kull som saknas. Sedan måste årets kullar numreras om; det gör "
            "genbanksansvarig, skicka meddelandet."
        )
        link = litters
        claim = f"kaninen är född i kull {conflict['paper']} år {born.year}; årets kullar behöver numreras om"
    elif kind == "litter_missing":
        text, link = f"Kullen finns inte i Stamboken. Lägg in den så blir numret {stamboken}.", litters
    elif kind == "litter_order":
        later = f"kull {held['litter_number']}" if held else "en kull"
        text = (
            f"Kullen är född före {later} som redan har nummer. Lägg in kullen, skicka sedan meddelandet så "
            "numrerar genbanksansvarig om året."
        )
        link, claim = litters, f"kullen är kull {conflict['paper']} år {born.year}; året behöver numreras om"
    elif kind == "position":
        text = (
            f"Plats {conflict['paper']} är upptagen av {held.get('number') or 'en annan kanin'} (eller annullerad). "
            "Är det samma kanin: registrera intyget på den i stället. Annars är det den kaninens papper som är fel: "
            "kontakta genbanksansvarig."
        )
        link, claim = rabbit, f"kaninen har plats {conflict['paper']} i kullen"
    elif kind == "year":
        text = f"Kullen är född {born}, pappret säger {conflict['paper']}. "
        text += "Är födelsedatumet fel: rätta det. Annars pappret."
        link = litters
    elif kind == "prefix":
        text = (
            f"Kullen ligger i besättning {conflict['stamboken']}, pappret säger {conflict['paper']}. Är kullen född i "
            f"{conflict['paper']} (dräktig hona såld): kullen flyttas av genbanksansvarig, skicka meddelandet."
        )
        link, claim = litters, f"kullen är född i besättning {conflict['paper']}"
    elif kind == "duplicate_litter":
        text = f"Modern har en kull född {conflict['stamboken']}. Är det den kullen: registrera kaninen där."
        link = litters
    else:  # number_taken, certificate_taken, duplicate_rabbit
        what = {"number_taken": "Numret", "certificate_taken": "Intyget"}.get(kind, "En kanin utan intyg")
        text = (
            f"{what} finns redan på {where}. Är det samma kanin: registrera intyget på den. "
            "Annars: kontakta genbanksansvarig."
        )
        if kind == "duplicate_rabbit" and conflict["paper"] is None:
            text = f"{where[0].upper()}{where[1:]} har samma föräldrar och födelsedatum men inget intyg. "
            text += "Är det samma kanin: registrera intyget på den. Annars: kontakta genbanksansvarig."
        link, claim = rabbit, f"{paper} hör till den här kaninen, inte till {held.get('number') or 'den andra'}"
    message = None
    if claim is not None:
        facts = [f"besättning {herd}" if herd else None, f"mor {litter['mother'] or 'okänd'}"]
        facts += [f"far {litter['father'] or 'okänd'}", f"född {born}" if born else None]
        message = (
            f"Pappersintyget säger {paper}, Stamboken ger {stamboken or 'inget nummer'}. "
            f"Kullen: {', '.join(fact for fact in facts if fact)}. Jag menar att pappret stämmer: {claim}. Varför: "
        )
    return {"kind": kind, "text": text, "self_service": link, "manager_message": message}


def conflict_extensions(check):
    """The dry-run fields as RFC 9457 extensions: its status as check_status, since status is the HTTP code."""
    return {**{key: value for key, value in check.items() if key != "status"}, "check_status": check["status"]}


NUMBER_CONFLICT = "Individnumret på pappersintyget stämmer inte med Stambokens. Inget sparas förrän du väljer."


def number_to_register(check, resolution):
    """The number a paper registration gets after number_check (recomputed under the lock): the match, or
    Stamboken's when the breeder chose it while seeing that same number. Otherwise a 409 number_conflict with
    the dry-run fields, raised so nothing in the transaction commits ("pappret stämmer" writes nothing either).
    A litter without a slot to give keeps its error (ValueError with generate_individual_number's key).
    """
    if check["status"] == "match":
        return check["stamboken_number"]
    if "reason" in check:
        raise ValueError(check["reason"])
    chosen = resolution or {}
    if (
        chosen.get("choice") == "use_stamboken_number"
        and "use_stamboken_number" in check["choices"]
        and chosen.get("expected_number") == check["stamboken_number"]
    ):
        return check["stamboken_number"]
    raise RosterActionError(409, "number_conflict", NUMBER_CONFLICT, **conflict_extensions(check))


def record_number_choice(individual, user, check):
    """ "Pappret rättas" in the rabbit's change history (ADR-0017's table); the paper's number is not stored."""
    IndividualCommand.create(
        operation_id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        command="UseStambokenNumber",
        individual=individual,
        actor=user.id,
        before={"paper_number": check["paper_number"]},
        after={"number": individual.number, "conflicts": sorted({c["kind"] for c in check["conflicts"]})},
    )
