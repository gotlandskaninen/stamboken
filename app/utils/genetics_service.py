"""
Genetics Service - Bridge between database and genetics calculations.

This module fetches pedigree data from the database and calculates genetic
metrics using the Python implementation (replacing R-API).
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

import numpy as np
from peewee import JOIN, fn

from utils import pedigree_snapshot as ps
from utils import reference_population as rp
from utils.database import DB_PROXY as DATABASE
from utils.database import (
    Breeding,
    GeneticMetricsHistory,
    GeneticsHistoryState,
    Herd,
    HerdTracking,
    ht_not_voided,
    not_voided,
    read_genetics_key,
    read_genetics_version,
)
from utils.database import Individual as DBIndividual
from utils.genetics import (
    MAX_RABBIT_AGE_DAYS,
    Individual,
    calculate_effective_population_size,
    calculate_founder_contributions,
    calculate_founder_statistics,
    calculate_gene_drop_statistics,
    calculate_genetic_priorities,
    calculate_genome_uniqueness,
    calculate_offspring_inbreeding_fast,
    calculate_pedigree_completeness,
    calculate_population_metrics,
    founder_equivalents_of,
    gene_drop_simulation,
    identify_founders,
    identify_founders_at_risk,
    suggest_breeding_pairs,
)
from utils.pedigree_math import band_for, mk_to_reference
from utils.reference_population import (
    CURRENT_DEFINITION,
    live_members,
    reference_population_start,  # noqa: F401 — re-exported for existing callers
)
from utils.reference_population import members as population_members

logger = logging.getLogger("herdbook.genetics")

# Bumped when the reference population rule changes; part of the snapshot key.
REFERENCE_DEFINITION_VERSION = CURRENT_DEFINITION.version

# Bumped when a formula changes a published number (1: FE counts phantom parents;
# GU counts carriers).
# Part of the snapshot key, so the shared memo is never served across it, and of the
# history watermark, so the next reconcile recomputes the stored years (0 = before versioning).
ALGORITHM_VERSION = 1


def reference_population_numbers(genebank_id: int, start_date: date | None = None) -> set[str]:
    """Individual numbers making up the genebank's mean kinship reference population.

    The rule lives in utils.reference_population; without ``start_date`` this
    is ``live_members(genebank_id, date.today())``.
    """
    if start_date is None:
        return live_members(genebank_id, date.today())
    return population_members(genebank_id, start=start_date, as_of=date.today(), live=True)


def fetch_pedigree_rows(genebank_id: int) -> list[dict]:
    """All non-voided individuals of a genebank with their parents' numbers.

    Each row is ``{"number", "sex", "father_number", "mother_number"}``.
    Errors propagate: the snapshot keeps serving its previous build.
    """
    Father = DBIndividual.alias()
    Mother = DBIndividual.alias()
    query = (
        DBIndividual.select(
            DBIndividual.number,
            DBIndividual.sex,
            Father.number.alias("father_number"),
            Mother.number.alias("mother_number"),
        )
        .join(Herd, on=(DBIndividual.origin_herd == Herd.id))
        .switch(DBIndividual)
        .join(Breeding, JOIN.LEFT_OUTER, on=(DBIndividual.breeding == Breeding.id))
        .join(Father, JOIN.LEFT_OUTER, on=(Father.id == Breeding.father_id))
        .switch(Breeding)
        .join(Mother, JOIN.LEFT_OUTER, on=(Mother.id == Breeding.mother_id))
        .where(Herd.genebank == genebank_id)
        .where(not_voided(DBIndividual))
        # Stable reads only; build_snapshot sorts by number, which makes the cycle break canonical.
        .order_by(DBIndividual.id)
    )
    return list(query.dicts())


def _snapshot_key(genebank_id):
    version, epoch = read_genetics_key()
    return (version, date.today(), REFERENCE_DEFINITION_VERSION, ALGORITHM_VERSION, epoch)


def recovery_eligible_numbers(genebank_id: int, today: date) -> set[str]:
    """Individuals plausibly alive and breedable: candidate recoverable carriers.

    Same alive/certificate/castration rule as the reference population, plus
    an age cap (unknown birth date ⇒ excluded). Membership is not checked here.
    """
    born_after = today - timedelta(days=MAX_RABBIT_AGE_DAYS)
    query = (
        DBIndividual.select(DBIndividual.number)
        .join(Herd, on=(DBIndividual.origin_herd == Herd.id))
        .switch(DBIndividual)
        .join(Breeding, on=(DBIndividual.breeding == Breeding.id))
        .where(
            Herd.genebank == genebank_id,
            not_voided(DBIndividual),
            DBIndividual.death_date.is_null(),
            DBIndividual.death_note.is_null() | (DBIndividual.death_note == ""),
            DBIndividual.castration_date.is_null(),
            DBIndividual.certificate.is_null(False) | DBIndividual.digital_certificate.is_null(False),
            Breeding.birth_date >= born_after,
        )
    )
    return {row["number"] for row in query.dicts()}


def _read_snapshot_inputs(genebank_id):
    """Version, membership, pedigree and carrier eligibility from one REPEATABLE READ snapshot.

    Starts its own transaction: SET TRANSACTION has to be its first statement.
    """
    with DATABASE.atomic():
        DATABASE.execute_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        key = _snapshot_key(genebank_id)
        members = live_members(genebank_id, key[1])
        rows = fetch_pedigree_rows(genebank_id)
        eligible = recovery_eligible_numbers(genebank_id, today=key[1])  # the key's day
    return key, rows, members, frozenset(eligible)


# Builds run on ps's executor threads, never inside a caller's transaction,
# so the REPEATABLE READ transaction can always be started there.
ps.set_source(key_fn=_snapshot_key, load_fn=_read_snapshot_inputs)
snapshot_status = ps.snapshot_status


def snapshot(genebank_id):
    return ps.get_snapshot(genebank_id)


def fetch_pedigree_from_db(genebank_id: int) -> list[Individual]:
    """
    All individuals of a genebank as genetics Individual objects, in topological order.

    Served from the pedigree snapshot. Membership of the reference population
    (``is_active``) comes from reference_population_numbers(), never from the
    unmaintained Individual.is_active column.
    """
    snap = snapshot(genebank_id)
    return snap.individuals if snap else []


# Snapshot-bound helpers: pure, no fetch. Every public get_* takes one snapshot
# and passes it down, so a computation never mixes two snapshots.


def _inbreeding_of(snap):
    return snap.memo("inbreeding", lambda: {snap.ids[i]: float(snap.F[i]) for i in range(len(snap.ids))})


def _mean_kinship_of(snap):
    """Members only (legacy shows 0,00 for everyone else)."""
    if snap.mk is None:
        return {}
    return snap.memo("mean_kinship", lambda: {snap.ids[i]: float(snap.mk[i]) for i in np.flatnonzero(snap.ref_mask)})


def _generations_of(snap):
    return snap.memo(
        "generation_numbers",
        lambda: {
            snap.ids[i]: {
                "max_gen": int(snap.gen_max[i]),
                "full_gen": int(snap.gen_full[i]),
                "equiv_gen": float(snap.gen_equiv[i]),
            }
            for i in range(len(snap.ids))
        },
    )


def _pci_of(snap):
    return snap.memo(
        "pci",
        lambda: {snap.ids[i]: {g: float(snap.pci[i, g - 1]) for g in range(1, 6)} for i in range(len(snap.ids))},
    )


def _gene_drop_of(snap, n_iterations=1000, seed=None):
    def compute():
        return calculate_gene_drop_statistics(snap.individuals, n_iterations=n_iterations, seed=seed)

    # Only the endpoint's default run is memoized: a caller-chosen seed or count must not grow the snapshot.
    return snap.memo("gene_drop_1000_None", compute) if (n_iterations, seed) == (1000, None) else compute()


def _cached_gene_drop(snap):
    """The /gene-drop/ endpoint's default run, if it has been computed on this snapshot."""
    return snap.derived.get("gene_drop_1000_None")


def _founder_stats_of(snap):
    return snap.memo(
        "founder_statistics",
        lambda: calculate_founder_statistics(snap.individuals, mean_kinship=_mean_kinship_of(snap)),
    )


def get_inbreeding(genebank_id: int) -> dict[str, float]:
    """Get inbreeding coefficients for all individuals in a genebank."""
    snap = snapshot(genebank_id)
    return _inbreeding_of(snap) if snap else {}


def get_kinship_matrix(genebank_id: int) -> dict[str, dict[str, float]]:
    """
    Get kinship matrix for active individuals in a genebank.

    Returns:
        Nested dictionary: {individual_i: {individual_j: kinship_value}}
    """
    snap = snapshot(genebank_id)
    if snap is None or snap.n_ref == 0:
        return {}
    K, ids = snap.reference_kinship()
    return {a: {b: float(K[i, j]) for j, b in enumerate(ids)} for i, a in enumerate(ids)}


def get_mean_kinship(genebank_id: int) -> dict[str, float]:
    """
    Get mean kinship for all active individuals in a genebank.

    Returns:
        Dictionary mapping individual number to mean kinship value.
    """
    snap = snapshot(genebank_id)
    return _mean_kinship_of(snap) if snap else {}


# How long a request waits for a rebuild that knows a new or renumbered animal.
REFRESH_WAIT_SECONDS = 10


class SnapshotNotReady(Exception):
    """No snapshot at all (a failed cold build), or a supplied animal is missing from a stale one in time."""


def snapshot_with(genebank_id: int, numbers):
    """The genebank's snapshot, waiting for a rebuild when a STALE one lacks any of `numbers`.

    Waits at most REFRESH_WAIT_SECONDS (read at call time) and raises
    SnapshotNotReady if the snapshot is still stale and still lacks a number.
    A FRESH snapshot that lacks a number is returned as is: that animal is not
    in this genebank's pedigree. Also raises SnapshotNotReady when there is no
    snapshot at all (a failed cold build, or its cooldown): never answer 0 for it.
    """
    numbers = [n for n in numbers if n]
    snap, stale = snapshot_status(genebank_id)
    if snap is None:
        raise SnapshotNotReady(f"No snapshot of genebank {genebank_id}")
    if not stale or all(n in snap.index for n in numbers):
        return snap
    # The build running now may predate the write that added the number, so keep
    # waiting for the next one until the deadline or until no build is coming.
    deadline = time.monotonic() + REFRESH_WAIT_SECONDS
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            waited = ps.wait_for_builds(genebank_id, timeout=remaining)
        except Exception:  # pylint: disable=broad-except
            logger.info("Genetics rebuild for genebank %s not ready for %s", genebank_id, numbers, exc_info=True)
            waited = True
        snap, stale = snapshot_status(genebank_id)
        if not stale or all(n in snap.index for n in numbers):
            return snap
        if not waited:
            break
    raise SnapshotNotReady(f"Snapshot of genebank {genebank_id} does not know {numbers} yet")


def _supplied_numbers(male_id, female_id, male_parents, female_parents):
    """The registered numbers a test mating names: each partner, or the named parents of an unregistered one."""
    numbers = []
    for number, parents in ((male_id, male_parents), (female_id, female_parents)):
        numbers.extend(parents if parents is not None else (number,))
    return [n for n in numbers if n]


def calculate_testbreed(
    genebank_id: int,
    male_id: str,
    female_id: str,
    male_parents: tuple[str, str] | None = None,
    female_parents: tuple[str, str] | None = None,
) -> float:
    """Calculate the inbreeding coefficient for a potential offspring.

    Reads the pedigree snapshot's parent arrays and inbreeding coefficients.
    Raises SnapshotNotReady when a supplied animal is missing from a stale
    snapshot and the rebuild does not finish in time (never answers 0 for it).

    Note: np.append returns new arrays (copies), so snap.sire etc.
    are never mutated — safe for concurrent requests.
    """
    snap = snapshot_with(genebank_id, _supplied_numbers(male_id, female_id, male_parents, female_parents))
    if snap is None or not snap.ids:
        return 0.0
    base_cache = snap.memo("testbreed_kinship", lambda: {(i, i): 0.5 * (1.0 + snap.F[i]) for i in range(len(snap.ids))})

    # Shallow-copy kinship cache (only mutable structure; arrays are read-only)
    kinship_cache = base_cache.copy()

    sire_arr = snap.sire
    dam_arr = snap.dam
    F = snap.F
    n = len(snap.ids)
    base_n = n

    # Resolve parent indices, extending arrays for virtual (unregistered) parents
    if male_parents is not None:
        # Virtual sire at index n
        gf_idx = snap.index.get(male_parents[0], -1) if male_parents[0] else -1
        gm_idx = snap.index.get(male_parents[1], -1) if male_parents[1] else -1
        # Compute F for virtual sire BEFORE extending arrays (keeps F/arrays in sync)
        if gf_idx >= 0 and gm_idx >= 0:
            f_virtual = calculate_offspring_inbreeding_fast(gf_idx, gm_idx, sire_arr, dam_arr, F, kinship_cache)
        else:
            f_virtual = 0.0
        # Now extend all arrays together with the virtual parent
        sire_arr = np.append(sire_arr, np.int32(gf_idx))
        dam_arr = np.append(dam_arr, np.int32(gm_idx))
        F = np.append(F, f_virtual)
        kinship_cache[(n, n)] = 0.5 * (1.0 + f_virtual)
        sire_idx = n
        n += 1
    else:
        sire_idx = snap.index.get(male_id, -1)

    if female_parents is not None:
        # Virtual dam at index n
        gf_idx = snap.index.get(female_parents[0], -1) if female_parents[0] else -1
        gm_idx = snap.index.get(female_parents[1], -1) if female_parents[1] else -1
        # Compute F for virtual dam BEFORE extending arrays
        if gf_idx >= 0 and gm_idx >= 0:
            f_virtual = calculate_offspring_inbreeding_fast(gf_idx, gm_idx, sire_arr, dam_arr, F, kinship_cache)
        else:
            f_virtual = 0.0
        # Now extend all arrays together
        sire_arr = np.append(sire_arr, np.int32(gf_idx))
        dam_arr = np.append(dam_arr, np.int32(gm_idx))
        F = np.append(F, f_virtual)
        kinship_cache[(n, n)] = 0.5 * (1.0 + f_virtual)
        dam_idx = n
        n += 1
    else:
        dam_idx = snap.index.get(female_id, -1)

    if sire_idx < 0 or dam_idx < 0:
        return 0.0

    result = calculate_offspring_inbreeding_fast(sire_idx, dam_idx, sire_arr, dam_arr, F, kinship_cache)

    # Merge real-pedigree kinship entries back to shared cache so subsequent
    # calls benefit from accumulated off-diagonal entries. Virtual parent
    # entries (index >= base_n) are excluded to avoid cross-request pollution.
    # GIL note: dict assignments are atomic under CPython and values are
    # deterministic (same pair always produces the same kinship value).
    # Not formally thread-safe — relies on GIL, not locks.
    for key, val in kinship_cache.items():
        if key not in base_cache and key[0] < base_n and key[1] < base_n:
            base_cache[key] = val

    return result


INCOMPLETE_PEDIGREE_BELOW = 0.8  # known ancestor share, generations 1–5


def individual_genetics(snap, number, *, alive, outside, stale):
    """F, MK and band of one animal for the v2 individual page; None if not in `snap`.

    Dead animals get neither MK nor band; `band_reason` explains every null band.
    """
    i = snap.index.get(number)
    if i is None:
        return None
    completeness = float(snap.completeness[i])
    mk = float(snap.mk[i]) if (snap.mk is not None and alive) else None
    if not alive:
        reason = "dead"
    elif outside:
        reason = "outside_genebank"
    elif snap.band_cuts is None:
        reason = "small_reference"
    elif completeness < INCOMPLETE_PEDIGREE_BELOW:
        reason = "incomplete_pedigree"
    else:
        reason = None
    definition = rp.CURRENT_DEFINITION
    return {
        "inbreeding": float(snap.F[i]),
        "mean_kinship": mk,
        "band": band_for(mk, snap.band_cuts) if reason is None else None,
        "band_reason": reason,
        "in_reference": bool(snap.ref_mask[i]),
        "alive": alive,
        "pedigree_completeness": completeness,
        "reference_size": snap.n_ref,
        "definition_version": definition.version,
        "preliminary": definition.preliminary,
        "stale": stale,
    }


def get_founder_statistics(genebank_id: int) -> dict:
    """
    Get founder statistics for a genebank.

    Returns a dictionary with:
    - n_founders: Number of founders contributing to the reference population
    - n_founders_total: Number of founders in the whole pedigree
    - founder_equivalents: FE value
    - proportional_loss: Proportion of the founders' gene diversity lost
      (1 - GD = mean MK over the reference population incl. self-kinship)
    - top_founders: List of (founder_id, contribution) sorted by contribution
    - avg_contributions: Dict of founder -> average contribution
    - population_size: Number of active individuals

    Reference:
        Lacy, R.C. (1989). Analysis of founder representation in pedigrees:
        Founder equivalents and founder genome equivalents. Zoo Biology, 8, 111-123.
    """
    snap = snapshot(genebank_id)
    if not snap or not snap.ids:
        return {
            "n_founders": 0,
            "n_founders_total": 0,
            "founder_equivalents": 0.0,
            "proportional_loss": 0.0,
            "top_founders": [],
            "avg_contributions": {},
            "population_size": 0,
        }

    # Diversitetsförlust = mean MK over the reference population, from the
    # snapshot's mean kinship (no extra kinship computation).
    return _founder_stats_of(snap)


# =============================================================================
# Phase 3: Gene Drop Simulation
# =============================================================================


def get_gene_drop_statistics(genebank_id: int, n_iterations: int = 1000, seed: int | None = None) -> dict:
    """
    Get gene drop simulation statistics for a genebank.

    This is computationally expensive, so the default run (1000 iterations, no
    seed) is cached on the snapshot; other runs are computed per call. Use a
    seed for reproducible results.

    Returns:
        Dictionary with FGE, gene diversity, allele retention, etc.
    """
    snap = snapshot(genebank_id)
    if not snap or not snap.ids:
        return {
            "n_founders": 0,
            "founder_genome_equivalents": 0.0,
            "founder_equivalents": 0.0,
            "genome_contributions": {},
            "allele_retention": {},
            "gene_diversity": 0.0,
            "n_iterations": n_iterations,
            "population_size": 0,
        }

    return _gene_drop_of(snap, n_iterations, seed)


# =============================================================================
# Phase 4: Population Metrics
# =============================================================================


def get_generation_numbers(genebank_id: int) -> dict[str, dict[str, float]]:
    """
    Get generation numbers for all individuals in a genebank.

    Returns:
        Dictionary mapping individual number to {max_gen, full_gen, equiv_gen}
    """
    snap = snapshot(genebank_id)
    return _generations_of(snap) if snap else {}


def get_pedigree_completeness(genebank_id: int, max_generations: int = 5) -> dict[str, dict[int, float]]:
    """
    Get pedigree completeness index for all individuals in a genebank.

    Returns:
        Dictionary mapping individual number to {generation: completeness}
    """
    snap = snapshot(genebank_id)
    if snap is None:
        return {}
    if max_generations != 5:  # rare, not cached
        return calculate_pedigree_completeness(snap.individuals, max_generations=max_generations)
    return _pci_of(snap)


def get_population_metrics(genebank_id: int) -> dict:
    """
    Get comprehensive population metrics for a genebank.

    This is the main function for population-level statistics.

    Returns:
        Dictionary with:
        - population_size: Total individuals
        - n_active: Active individuals
        - n_founders: Founder count
        - founder_equivalents: FE value
        - mean_inbreeding: Average F
        - max_inbreeding: Maximum F
        - mean_kinship: Average mean kinship
        - effective_population_size: Realised Ne over the reference population (None if not estimable)
        - delta_f: Mean individual ΔF (None if not estimable)
        - ne_method, ne_se, ne_n: Ne method, standard error and animals used
        - expected_offspring_f: Expected offspring F under random mating in the reference population
        - mean_equiv_gen: Average equivalent generations
        - mean_full_gen: Average full generations
        - mean_max_gen: Average maximum generations
    """
    snap = snapshot(genebank_id)
    if snap is None or not snap.ids:
        return {
            "population_size": 0,
            "n_active": 0,
            "n_population": 0,
            "n_founders": 0,
            "founder_equivalents": 0.0,
            "mean_inbreeding": 0.0,
            "max_inbreeding": 0.0,
            "mean_kinship": 0.0,
            "effective_population_size": None,
            "delta_f": None,
            "ne_method": "individual_delta_f",
            "ne_se": None,
            "ne_n": 0,
            "expected_offspring_f": None,
            "mean_equiv_gen": 0.0,
            "mean_full_gen": 0.0,
            "mean_max_gen": 0.0,
        }

    return snap.memo(
        "population_metrics",
        lambda: calculate_population_metrics(
            snap.individuals,
            kinship=snap.reference_kinship(),
            inbreeding=_inbreeding_of(snap),
            gen_numbers=_generations_of(snap),
        ),
    )


def get_effective_population_size(genebank_id: int) -> dict[str, float]:
    """
    Get effective population size (Ne) for a genebank.

    Returns:
        Dictionary with ne, delta_f, r_squared, method
    """
    individuals = fetch_pedigree_from_db(genebank_id)
    if not individuals:
        return {"ne": 0.0, "delta_f": 0.0, "r_squared": 0.0, "method": "inbreeding"}

    logger.info(f"Calculating effective population size for genebank {genebank_id}")
    return calculate_effective_population_size(individuals)


# Fixed gene drop seed for priorities, so every worker computes the same result.
PRIORITIES_SEED = 2026


def get_genetic_priorities(
    genebank_id: int,
    n_iterations: int = 1000,
) -> list[dict]:
    """
    Get genetic conservation priorities for all active individuals.

    Returns list of dicts with individual_id, priority, reasons,
    genetic_value_score, genome_uniqueness.
    """
    snap = snapshot(genebank_id)
    if not snap or not snap.ids:
        return []
    return snap.memo(f"priorities_{n_iterations}", lambda: _priorities_of(snap, n_iterations))


def _priorities_of(snap, n_iterations):
    individuals = snap.individuals
    logger.info(f"Calculating genetic priorities for genebank {snap.genebank_id}")

    # Get required metrics
    mk = _mean_kinship_of(snap)
    contrib, founder_ids = calculate_founder_contributions(individuals)

    # Get genome uniqueness from gene drop
    allele_matrix, pop_ids, founders = gene_drop_simulation(
        individuals, n_iterations=n_iterations, seed=PRIORITIES_SEED
    )
    gu = calculate_genome_uniqueness(allele_matrix, pop_ids)

    priorities = calculate_genetic_priorities(individuals, mk, contrib, gu)

    # Convert to dicts for API
    result = [asdict(p) for p in priorities]

    # Sort: critical first, then important, then normal; within level by score desc
    priority_order = {"critical": 0, "important": 1, "normal": 2}
    result.sort(key=lambda x: (priority_order[x["priority"]], -x["genetic_value_score"]))
    return result


def get_breeding_suggestions(
    genebank_id: int,
    max_pairs: int = 10,
    max_inbreeding: float = 0.0625,
    max_per_male: int = 3,
    max_per_female: int = 1,
) -> list[dict]:
    """
    Get breeding pair suggestions using Dynamic MK Selection.

    Returns list of dicts with sire_id, dam_id, expected_f,
    delta_gd, mate_suitability_index, reasons.
    """
    snap = snapshot(genebank_id)
    if not snap or not snap.ids:
        return []

    def compute():
        logger.info(f"Calculating breeding suggestions for genebank {genebank_id}")
        K, ids = snap.reference_kinship()
        pairs = suggest_breeding_pairs(
            snap.individuals,
            K,
            ids,
            _mean_kinship_of(snap),
            max_pairs=max_pairs,
            max_inbreeding=max_inbreeding,
            max_per_male=max_per_male,
            max_per_female=max_per_female,
        )
        return [asdict(p) for p in pairs]

    return snap.memo(f"suggestions_{max_pairs}_{max_inbreeding}_{max_per_male}_{max_per_female}", compute)


def get_founders_at_risk(genebank_id: int) -> list[dict]:
    """
    Get all founders with conservation status and recoverable carrier info.

    For lost/critical founders, also lists alive-but-inactive individuals that
    carry the founder's genes (potential recovery candidates), as read with the snapshot.

    Returns:
        List of dicts with founder_id, n_carriers, avg_contribution,
        allele_retention, carrier_ids, risk_level, recoverable_carriers.
    """
    snap = snapshot(genebank_id)
    if not snap or not snap.ids:
        return []
    return snap.memo("founders_at_risk", lambda: _founders_at_risk_of(snap))


def _founders_at_risk_of(snap):
    genebank_id = snap.genebank_id
    individuals = snap.individuals
    logger.info(f"Calculating founders at risk for genebank {genebank_id}")

    # Get founder contributions per individual
    contrib, founder_ids = calculate_founder_contributions(individuals)

    # Get average contributions from founder statistics
    avg_contributions = _founder_stats_of(snap).get("avg_contributions", {})

    # Try to get allele retention from gene drop (if computed on this snapshot)
    allele_retention = None
    cached_gd = _cached_gene_drop(snap)
    if cached_gd is not None:
        allele_retention = cached_gd.get("allele_retention")

    result = identify_founders_at_risk(individuals, contrib, avg_contributions, allele_retention)

    # Enrich lost/critical founders with recoverable carriers: individuals
    # outside the reference population that are plausibly alive and breedable
    # (recovery_eligible_numbers), read in the snapshot's own transaction.
    needs_recovery = [f for f in result if f["risk_level"] in ("lost", "critical")]
    if needs_recovery:
        # Outside the reference population (same rule as MK), not the raw
        # Individual.is_active column. Taken from the same loaded individuals
        # `contrib` was computed from, so the two cannot drift apart.
        member_numbers = {ind.id for ind in individuals if ind.is_active}
        alive_inactive_ids = snap.recovery_eligible - member_numbers

        for f_entry in needs_recovery:
            founder_id = f_entry["founder_id"]
            recoverable = [ind_id for ind_id in alive_inactive_ids if contrib.get(ind_id, {}).get(founder_id, 0.0) > 0]
            f_entry["recoverable_carriers"] = recoverable

    return result


def _compute_rolling_ne(rows: list[dict], window: int = 10, generation_interval: float = 2.0) -> None:
    """Compute rolling Ne from stored yearly mean_inbreeding using log regression.

    Uses ln(1 - F̄) regression against year (Wright-Malécot model):
        ln(1 - F_t) ≈ -ΔF * t  →  Ne = 1 / (2 * ΔF_per_generation)

    Modifies rows in place, overriding effective_population_size.
    """
    min_points = 5

    for i, row in enumerate(rows):
        start_idx = max(0, i - window + 1)
        window_rows = rows[start_idx : i + 1]

        years = []
        ln_vals = []
        for w in window_rows:
            f = w.get("mean_inbreeding")
            if f is None or f <= 0.0 or f >= 1.0:
                continue
            years.append(float(w["year"]))
            ln_vals.append(np.log(1.0 - f))

        if len(years) < min_points:
            row["effective_population_size"] = None
            continue

        x = np.array(years)
        y = np.array(ln_vals)
        x_mean = x.mean()
        ss_xx = np.dot(x - x_mean, x - x_mean)
        if ss_xx < 1e-9:
            beta = 0.0
        else:
            beta = np.dot(x - x_mean, y - y.mean()) / ss_xx

        # β should be negative (F increasing → ln(1-F) decreasing)
        # ΔF per year ≈ -β, ΔF per generation = -β * L
        delta_f_per_gen = -beta * generation_interval

        ne_cap = 10000.0
        if delta_f_per_gen > 1e-6:
            ne = min(1.0 / (2.0 * delta_f_per_gen), ne_cap)
        else:
            # F stable or decreasing — Ne effectively very large
            ne = ne_cap
        row["effective_population_size"] = round(ne, 1)


HISTORY_STALE_AFTER = timedelta(hours=26)
_reconcile_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="history-reconcile")
_reconcile_inflight = {}
_reconcile_lock = threading.Lock()


def _reconcile_quietly(genebank_id):
    try:
        return reconcile_history(genebank_id)
    except Exception:
        logger.exception("History reconcile failed for genebank %s", genebank_id)
        return None
    finally:
        ps._close_db_connection()


def maybe_reconcile_in_background(genebank_id):
    """Queue a history reconcile when the last check is older than HISTORY_STALE_AFTER."""
    state = GeneticsHistoryState.get_or_none(GeneticsHistoryState.genebank == genebank_id)
    if state is not None and datetime.now(timezone.utc) - state.checked_at < HISTORY_STALE_AFTER:
        return
    with _reconcile_lock:  # check-and-submit is atomic: one queued reconcile per genebank and worker
        fut = _reconcile_inflight.get(genebank_id)
        if fut is not None and not fut.done():
            return
        _reconcile_inflight[genebank_id] = _reconcile_executor.submit(_reconcile_quietly, genebank_id)


def get_genetics_trends(genebank_id: int, start_year: int | None = None, end_year: int | None = None) -> list[dict]:
    """Fetch stored trend data per report year and compute rolling Ne from mean_inbreeding."""
    maybe_reconcile_in_background(genebank_id)

    # Fetch extra years before start_year so rolling window has enough data
    window = 10
    fetch_start = start_year - window if start_year else None

    query = (
        GeneticMetricsHistory.select()
        .where(GeneticMetricsHistory.genebank == genebank_id)
        .order_by(GeneticMetricsHistory.report_year)
    )
    if fetch_start:
        query = query.where(GeneticMetricsHistory.report_year >= fetch_start)
    if end_year:
        query = query.where(GeneticMetricsHistory.report_year <= end_year)

    rows = [
        {
            "year": row.report_year,
            "snapshot_date": row.as_of.strftime("%Y-%m-%d"),
            "population_size": row.population_size,
            "active_count": row.active_count,
            "mean_inbreeding": row.mean_inbreeding,
            "mean_kinship": row.mean_kinship,
            "effective_population_size": None,  # computed below
            "founder_equivalents": row.founder_equivalents,
            "data_quality": row.data_quality,
            "definition_version": row.definition_version,
        }
        for row in query
    ]

    # Ne is computed on-the-fly from stored mean_inbreeding using a rolling
    # ln(1-F̄) regression (Wright-Malécot model), not stored in the DB.
    _compute_rolling_ne(rows, window=window)

    # Trim pre-fetched rows if start_year was specified
    if start_year:
        rows = [r for r in rows if r["year"] >= start_year]

    return rows


# Advisory lock ids, + genebank_id.
_HISTORY_XACT_LOCK = 0x6E6E0000  # publication
_HISTORY_SESSION_LOCK = 0x6E6E8000  # one reconcile per genebank at a time, cluster-wide


def _first_birth_year(genebank_id):
    first = (
        Breeding.select(fn.MIN(Breeding.birth_date))
        .join(DBIndividual, on=(DBIndividual.breeding == Breeding.id))
        .join(Herd, on=(DBIndividual.origin_herd == Herd.id))
        .where(Herd.genebank == genebank_id, not_voided(DBIndividual))
        .scalar()
    )
    return first.year if first else None


def _first_tracking_year(genebank_id):
    first = (
        HerdTracking.select(fn.MIN(HerdTracking.herd_tracking_date))
        .join(DBIndividual, on=(HerdTracking.individual == DBIndividual.id))
        .join(Herd, on=(DBIndividual.origin_herd == Herd.id))
        .where(Herd.genebank == genebank_id, ht_not_voided(), not_voided(DBIndividual))
        .scalar()
    )
    return first.year if first else None


def _birth_dates(genebank_id):
    rows = (
        DBIndividual.select(DBIndividual.number, Breeding.birth_date)
        .join(Herd, on=(DBIndividual.origin_herd == Herd.id))
        .switch(DBIndividual)
        .join(Breeding, JOIN.LEFT_OUTER, on=(DBIndividual.breeding == Breeding.id))
        .where(Herd.genebank == genebank_id, not_voided(DBIndividual))
        .dicts()
    )
    return {r["number"]: r["birth_date"] for r in rows}


def desired_history_rows(genebank_id, today):
    """(version, rows): the history the data asks for, one row per closed report year.

    Version, rounds, pedigree and every year's membership come from one
    REPEATABLE READ snapshot; the maths runs after it on an own pedigree object
    (never the cached snapshot, which may be stale). Starts its own
    transaction: call it with none open.
    """
    version, rows, births, years = _read_history_inputs(genebank_id, today)
    return version, _history_rows(genebank_id, version, rows, births, years)


def _read_history_inputs(genebank_id, today):
    """(version, pedigree rows, birth dates, {year: (as_of, members)}) from one REPEATABLE READ snapshot."""
    with DATABASE.atomic():
        DATABASE.execute_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        version = read_genetics_version()
        rows = fetch_pedigree_rows(genebank_id)
        births = _birth_dates(genebank_id)
        # Start at the earliest evidence: membership admits unknown births, and a
        # herd-tracking row dated early in a year can fall in the previous year's window.
        tracking_year = _first_tracking_year(genebank_id)
        evidence = [_first_birth_year(genebank_id), tracking_year - 1 if tracking_year else None]
        years = {}
        # Up to and including this year: a round can end before the calendar year does (is_closed decides).
        for year in range(min((y for y in evidence if y), default=today.year), today.year + 1):
            if not rp.is_closed(year, today):
                continue
            start, as_of = rp.history_window(year)
            years[year] = (as_of, rp.members(genebank_id, start=start, as_of=as_of, live=False))
    return version, rows, births, years


def _founder_equivalents(sire, dam, founders, mask):
    """FE over the members in ``mask``; equals calculate_founder_equivalents(individuals, members).

    The shared reverse pass (genetics.founder_equivalents_of): O(n) per year, no
    individuals × founders matrix. ``founders`` are the indices of animals with
    neither parent in the pedigree (identify_founders); ``sire``/``dam`` are index lists.
    """
    return founder_equivalents_of(sire, dam, founders, mask)[0]


def _history_rows(genebank_id, version, rows, births, years):
    """History rows from the read inputs (pure: no database)."""
    snap = ps.build_snapshot(genebank_id, rows, set(), key=("history", version), seq=0)
    return _history_rows_on(snap, version, births, years)


def _history_rows_on(snap, version, births, years):
    """History rows on a built pedigree snapshot (its own membership is ignored).

    Years start at the first one with at least ``rp.MIN_HISTORY_MEMBERS``
    members; later small years stay.
    """
    sire, dam = snap.sire.tolist(), snap.dam.tolist()
    founders = np.array([snap.index[f] for f in identify_founders(snap.individuals)], dtype=np.int64)
    out = []
    started = False
    for year, (as_of, member_set) in sorted(years.items()):
        if not started and len(member_set) < rp.MIN_HISTORY_MEMBERS:
            continue
        started = True
        mask = np.array([i in member_set for i in snap.ids], dtype=bool)
        mk = mk_to_reference(snap.sire, snap.dam, snap.F, mask)
        mean_mk = float(mk[0][mask].mean()) if mk is not None else None
        member_ids = [snap.ids[i] for i in np.flatnonzero(mask)]
        out.append(
            {
                "report_year": year,
                "as_of": as_of,
                "snapshot_date": as_of,
                "definition_version": rp.CURRENT_DEFINITION.version,
                "pedigree_version": version,
                "active_count": len(member_ids),
                "mean_inbreeding": float(snap.F[mask].mean()) if member_ids else None,
                "mean_kinship": mean_mk,
                "fge": 1.0 / (2.0 * mean_mk) if mean_mk else None,
                "founder_equivalents": _founder_equivalents(sire, dam, founders, mask) if member_ids else None,
                "population_size": sum(1 for b in births.values() if b is None or b <= as_of),
                "data_quality": "high" if year >= 2015 else "medium" if year >= 2005 else "low",
            }
        )
    return out


def _publish_history(genebank_id, version, rows, definition=None):
    """Replace the genebank's history with ``rows`` unless a newer candidate is already published.

    ``definition`` is the candidate's reference definition version (default:
    this worker's current one); the candidate's algorithm is this worker's
    ALGORITHM_VERSION. "discarded": the stored state is newer by (definition,
    algorithm, version) (also when that publication was empty). "unchanged":
    same version, definition and algorithm, same years with the same as_of.
    Otherwise "replaced". The state row is written in every case but "discarded".
    """
    if definition is None:
        definition = rp.CURRENT_DEFINITION.version
    candidate = (definition, ALGORITHM_VERSION, version)
    now = datetime.now(timezone.utc)
    with DATABASE.atomic():
        DATABASE.execute_sql("SELECT pg_advisory_xact_lock(%s)", (_HISTORY_XACT_LOCK + genebank_id,))
        state = GeneticsHistoryState.get_or_none(GeneticsHistoryState.genebank == genebank_id)
        published = None if state is None else (state.definition_version, state.algorithm_version, state.version)
        if published is not None and published > candidate:
            return "discarded"
        stored = sorted(
            (r.report_year, r.as_of)
            for r in GeneticMetricsHistory.select().where(GeneticMetricsHistory.genebank == genebank_id)
        )
        same_generation = published == candidate
        if same_generation and stored == sorted((r["report_year"], r["as_of"]) for r in rows):
            result = "unchanged"
        else:
            GeneticMetricsHistory.delete().where(GeneticMetricsHistory.genebank == genebank_id).execute()
            for r in rows:
                GeneticMetricsHistory.create(genebank=genebank_id, **r)
            result = "replaced"
        GeneticsHistoryState.insert(
            genebank=genebank_id,
            checked_at=now,
            version=version,
            definition_version=definition,
            algorithm_version=ALGORITHM_VERSION,
        ).on_conflict(
            conflict_target=[GeneticsHistoryState.genebank],
            update={
                GeneticsHistoryState.checked_at: now,
                GeneticsHistoryState.version: version,
                GeneticsHistoryState.definition_version: definition,
                GeneticsHistoryState.algorithm_version: ALGORITHM_VERSION,
            },
        ).execute()
        return result


def reconcile_history(genebank_id, today=None):
    """Bring the genebank's stored history in line with today's data: "busy" | "unchanged" | "replaced" | "discarded".

    At most one reconcile per genebank runs at a time (non-blocking session
    lock; "busy" otherwise). Takes and releases that lock on this thread's
    connection and opens its own transactions: call it with none open.
    """
    today = today or date.today()
    lock = _HISTORY_SESSION_LOCK + genebank_id
    if not DATABASE.execute_sql("SELECT pg_try_advisory_lock(%s)", (lock,)).fetchone()[0]:
        return "busy"
    try:
        version, rows = desired_history_rows(genebank_id, today)
        # The rows carry this definition version; publish under the same one.
        return _publish_history(genebank_id, version, rows, definition=rp.CURRENT_DEFINITION.version)
    finally:
        DATABASE.execute_sql("SELECT pg_advisory_unlock(%s)", (lock,))


def invalidate_cache(genebank_id: int = None):
    """
    Invalidate cached genetics data.

    Call this when the pedigree changes (new individuals, updates, etc.).
    Readers keep the previous snapshot while the rebuild runs in the background.
    """

    ps.mark_stale(genebank_id)
    if genebank_id is None:
        logger.info("Cleared all genetics caches")
    else:
        logger.info(f"Cleared genetics cache for genebank {genebank_id}")
