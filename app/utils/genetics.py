"""
Genetic calculations for pedigree analysis.

This module implements algorithms for calculating:
- Inbreeding coefficients (Henderson's tabular method)
- Kinship matrix (Henderson's method)
- Mean kinship
- Founder contributions and Founder Equivalents (FE)
- Gene drop simulation and Founder Genome Equivalents (FGE)

These replace the R-API (optiSel/pedigree packages) with pure Python/NumPy.
"""

import logging
import re
from dataclasses import dataclass, replace
from datetime import date

import numpy as np

logger = logging.getLogger("herdbook.genetics")


@dataclass
class Individual:
    """Represents an individual in a pedigree."""

    id: str
    sire_id: str | None  # Father
    dam_id: str | None  # Mother
    is_active: bool = True
    sex: str | None = None  # "male", "female", or None if unknown


def topological_sort_pedigree(individuals: list[Individual]) -> tuple[list[Individual], dict[str, int]]:
    """
    Sort pedigree so that parents always come before offspring.

    This is required for Henderson's tabular method.

    Iterative depth-first placement (sire line first, then dam line, then the
    individual itself), so arbitrarily deep pedigrees work. A parent link that
    would close a cycle (e.g. an animal recorded as its own ancestor) is
    dropped and logged; the returned Individual is then a copy with that
    parent set to None, while the input objects are left untouched.

    Returns:
        Tuple of (sorted_individuals, id_to_index mapping)
    """
    # Build lookup
    id_to_individual = {ind.id: ind for ind in individuals}

    # 0/absent = not visited, 1 = being placed (on the stack), 2 = placed
    state: dict[str, int] = {}
    result = []

    for root in individuals:
        if state.get(root.id):
            continue
        state[root.id] = 1
        # Frames of (individual, dropped parent fields, next parent field to visit)
        stack = [(root, [], 0)]
        while stack:
            ind, dropped, step = stack.pop()
            if step < 2:
                field = "sire_id" if step == 0 else "dam_id"
                parent_id = getattr(ind, field)
                stack.append((ind, dropped, step + 1))
                if parent_id and parent_id in id_to_individual:
                    parent_state = state.get(parent_id, 0)
                    if parent_state == 1:
                        logger.warning(
                            "Pedigree cycle: dropping parent %s of individual %s (treated as unknown)",
                            parent_id,
                            ind.id,
                        )
                        dropped.append(field)
                    elif parent_state == 0:
                        state[parent_id] = 1
                        stack.append((id_to_individual[parent_id], [], 0))
                continue

            state[ind.id] = 2
            result.append(replace(ind, **dict.fromkeys(dropped)) if dropped else ind)

    # Create index mapping
    id_to_index = {ind.id: i for i, ind in enumerate(result)}

    return result, id_to_index


def calculate_inbreeding_henderson(individuals: list[Individual]) -> dict[str, float]:
    """
    Calculate inbreeding coefficients using Henderson's tabular method.

    Henderson's method computes F[i] = K[sire_i, dam_i] where K is the
    kinship (coancestry) matrix. It processes individuals in birth order
    and computes kinship values incrementally.

    Note: This is NOT Meuwissen & Luo (1992) which uses LDL' decomposition.
    Henderson's method is O(n²) in time but simpler to implement correctly.

    Args:
        individuals: List of Individual objects

    Returns:
        Dictionary mapping individual ID to inbreeding coefficient
    """
    if not individuals:
        return {}

    # Sort pedigree topologically
    sorted_inds, id_to_idx = topological_sort_pedigree(individuals)
    n = len(sorted_inds)

    # Prepare arrays
    sire = np.full(n, -1, dtype=np.int32)
    dam = np.full(n, -1, dtype=np.int32)

    for i, ind in enumerate(sorted_inds):
        if ind.sire_id and ind.sire_id in id_to_idx:
            sire[i] = id_to_idx[ind.sire_id]
        if ind.dam_id and ind.dam_id in id_to_idx:
            dam[i] = id_to_idx[ind.dam_id]

    # Use the Henderson-based implementation
    F = _calculate_inbreeding_henderson(n, sire, dam)

    # Build result dictionary
    return {ind.id: float(F[i]) for i, ind in enumerate(sorted_inds)}


def _calculate_inbreeding_henderson(n: int, sire: np.ndarray, dam: np.ndarray) -> np.ndarray:
    """
    Calculate inbreeding using Henderson's tabular method.

    For each individual i:
    F[i] = K[sire_i, dam_i] (kinship between parents)

    We build a sparse kinship cache iteratively, which is efficient
    for pedigrees where most pairs don't share recent ancestors.
    """
    F = np.zeros(n, dtype=np.float64)

    # Global cache for kinship values - shared across all calculations
    # This is critical for performance
    kinship_cache: dict[tuple[int, int], float] = {}

    for i in range(n):
        s = sire[i]
        d = dam[i]

        # Compute F[i] = K[s, d]
        if s < 0 or d < 0:
            F[i] = 0.0
        else:
            # Compute K[s, d] using iterative approach with shared cache
            F[i] = _compute_kinship_iterative(s, d, sire, dam, F, kinship_cache)

        # Store self-kinship in cache: K[i,i] = 0.5 * (1 + F[i])
        kinship_cache[(i, i)] = 0.5 * (1.0 + F[i])

    return F


def _compute_kinship_iterative(
    a: int, b: int, sire: np.ndarray, dam: np.ndarray, F: np.ndarray, cache: dict[tuple[int, int], float]
) -> float:
    """
    Compute kinship K[a, b] iteratively using a work stack.

    Avoids deep recursion by using explicit stack management.
    Uses the shared cache for memoization.
    """
    # Normalize key (smaller index first)
    if a > b:
        a, b = b, a

    key = (a, b)
    if key in cache:
        return cache[key]

    # Use a work stack to avoid recursion
    # Each item is (a, b, state) where state tracks computation progress
    # state: 0 = initial, 1 = computed sire contribution, 2 = done
    work_stack = [(a, b, 0, 0.0)]  # (a, b, state, partial_result)
    result_stack = []

    while work_stack:
        curr_a, curr_b, state, partial = work_stack.pop()

        # Normalize
        if curr_a > curr_b:
            curr_a, curr_b = curr_b, curr_a

        curr_key = (curr_a, curr_b)

        # Check cache first
        if curr_key in cache:
            result_stack.append(cache[curr_key])
            continue

        # Self-kinship - should already be in cache
        if curr_a == curr_b:
            val = cache.get(curr_key, 0.5)  # Default for founders
            result_stack.append(val)
            continue

        s_b = sire[curr_b]
        d_b = dam[curr_b]

        # Founder (no parents)
        if s_b < 0 and d_b < 0:
            cache[curr_key] = 0.0
            result_stack.append(0.0)
            continue

        if state == 0:
            # First visit - need to compute K[a, sire_b] and K[a, dam_b]
            # Push self back with state 1, then push dependencies
            work_stack.append((curr_a, curr_b, 1, 0.0))

            if d_b >= 0:
                d_key = (min(curr_a, d_b), max(curr_a, d_b))
                if d_key not in cache:
                    work_stack.append((curr_a, d_b, 0, 0.0))

            if s_b >= 0:
                s_key = (min(curr_a, s_b), max(curr_a, s_b))
                if s_key not in cache:
                    work_stack.append((curr_a, s_b, 0, 0.0))

        elif state == 1:
            # Dependencies computed, now combine results
            result = 0.0

            if s_b >= 0:
                s_key = (min(curr_a, s_b), max(curr_a, s_b))
                result += 0.5 * cache.get(s_key, 0.0)

            if d_b >= 0:
                d_key = (min(curr_a, d_b), max(curr_a, d_b))
                result += 0.5 * cache.get(d_key, 0.0)

            cache[curr_key] = result
            result_stack.append(result)

    return cache.get(key, 0.0)


def calculate_kinship_matrix(individuals: list[Individual], active_only: bool = True) -> tuple[np.ndarray, list[str]]:
    """
    Calculate the kinship matrix using Henderson's tabular method.

    The kinship coefficient K[i,j] represents the probability that a random
    allele from individual i is identical by descent (IBD) to a random allele
    from individual j.

    Henderson's method builds the matrix iteratively:
    - K[i,i] = 0.5 * (1 + F[i]) = 0.5 * (1 + K[sire_i, dam_i])
    - K[i,j] = 0.5 * (K[sire_i, j] + K[dam_i, j]) for j < i

    Args:
        individuals: List of Individual objects
        active_only: If True, only return matrix for active individuals

    Returns:
        Tuple of (kinship_matrix, list of individual IDs in matrix order)
    """
    if not individuals:
        return np.array([[]]), []

    # Sort pedigree
    sorted_inds, id_to_idx = topological_sort_pedigree(individuals)
    n = len(sorted_inds)

    if active_only:
        # Optimized: Only compute kinship for active individuals
        # But we need to trace through the full pedigree for relationships
        active_indices = [i for i, ind in enumerate(sorted_inds) if ind.is_active]
        active_ids = [sorted_inds[i].id for i in active_indices]

        if not active_indices:
            return np.array([[]]), []

        # Prepare parent indices
        sire = np.full(n, -1, dtype=np.int32)
        dam = np.full(n, -1, dtype=np.int32)
        for i, ind in enumerate(sorted_inds):
            if ind.sire_id and ind.sire_id in id_to_idx:
                sire[i] = id_to_idx[ind.sire_id]
            if ind.dam_id and ind.dam_id in id_to_idx:
                dam[i] = id_to_idx[ind.dam_id]

        # Use the inbreeding cache we already built
        F = _calculate_inbreeding_henderson(n, sire, dam)

        # Now compute kinship matrix only for active pairs
        m = len(active_indices)
        K_active = np.zeros((m, m), dtype=np.float64)

        # Shared cache for kinship
        kinship_cache: dict[tuple[int, int], float] = {}

        # Pre-populate diagonal (self-kinship)
        for i in range(n):
            kinship_cache[(i, i)] = 0.5 * (1.0 + F[i])

        # Compute kinship for all active pairs
        for ai, idx_i in enumerate(active_indices):
            K_active[ai, ai] = kinship_cache[(idx_i, idx_i)]

            for aj in range(ai + 1, m):
                idx_j = active_indices[aj]
                k_val = _compute_kinship_iterative(idx_i, idx_j, sire, dam, F, kinship_cache)
                K_active[ai, aj] = k_val
                K_active[aj, ai] = k_val

        return K_active, active_ids
    else:
        # Build full kinship matrix (O(n^2) memory)
        K = np.zeros((n, n), dtype=np.float64)

        for i in range(n):
            ind = sorted_inds[i]

            sire_idx = id_to_idx.get(ind.sire_id) if ind.sire_id else None
            dam_idx = id_to_idx.get(ind.dam_id) if ind.dam_id else None

            # Fill column/row for this individual
            for j in range(i):
                # K[i,j] = 0.5 * (K[sire_i, j] + K[dam_i, j])
                val = 0.0
                if sire_idx is not None:
                    val += 0.5 * K[sire_idx, j]
                if dam_idx is not None:
                    val += 0.5 * K[dam_idx, j]
                K[i, j] = val
                K[j, i] = val  # Symmetric

            # Diagonal: K[i,i] = 0.5 * (1 + F[i])
            if sire_idx is not None and dam_idx is not None:
                F_i = K[sire_idx, dam_idx]
            else:
                F_i = 0.0
            K[i, i] = 0.5 * (1.0 + F_i)

        all_ids = [ind.id for ind in sorted_inds]
        return K, all_ids


def calculate_mean_kinship(individuals: list[Individual], active_only: bool = True) -> dict[str, float]:
    """
    Calculate mean kinship for each individual.

    Mean kinship MK[i] = average of K[i,j] for all j in the population.
    This is useful for selecting breeding pairs - individuals with lower
    mean kinship are genetically more valuable for maintaining diversity.

    Args:
        individuals: List of Individual objects
        active_only: If True, only calculate for active individuals

    Returns:
        Dictionary mapping individual ID to mean kinship value
    """
    K, ids = calculate_kinship_matrix(individuals, active_only=active_only)

    if K.size == 0:
        return {}

    # Mean kinship = column (or row) mean of the kinship matrix
    mean_k = np.mean(K, axis=0)

    return {id_: float(mk) for id_, mk in zip(ids, mean_k, strict=False)}


def calculate_offspring_inbreeding(
    individuals: list[Individual],
    sire_id: str,
    dam_id: str,
    sire_parents: tuple[str, str] | None = None,
    dam_parents: tuple[str, str] | None = None,
) -> float:
    """
    Calculate the inbreeding coefficient for a potential offspring.

    This is used for "test breeding" - checking genetic compatibility
    before mating.

    **Key insight:** F_offspring = kinship(sire, dam)

    We only need to compute the kinship between the two parents - no need
    to rebuild the entire pedigree! This is much faster than the R-API
    approach which recalculates all inbreeding coefficients.

    Args:
        individuals: Existing pedigree
        sire_id: ID of the father
        dam_id: ID of the mother
        sire_parents: (grandfather, grandmother) if sire is unregistered
        dam_parents: (grandfather, grandmother) if dam is unregistered

    Returns:
        Inbreeding coefficient for potential offspring (0.0 - 1.0)
    """
    # Build working pedigree (only add unregistered parents if needed)
    working_individuals = list(individuals)

    # Add unregistered sire if needed
    if sire_parents is not None:
        temp_sire_id = sire_id or f"_temp_sire_{sire_parents[0]}+{sire_parents[1]}"
        working_individuals.append(
            Individual(id=temp_sire_id, sire_id=sire_parents[0], dam_id=sire_parents[1], is_active=True)
        )
        sire_id = temp_sire_id

    # Add unregistered dam if needed
    if dam_parents is not None:
        temp_dam_id = dam_id or f"_temp_dam_{dam_parents[0]}+{dam_parents[1]}"
        working_individuals.append(
            Individual(id=temp_dam_id, sire_id=dam_parents[0], dam_id=dam_parents[1], is_active=True)
        )
        dam_id = temp_dam_id

    # Sort pedigree and prepare arrays
    sorted_inds, id_to_idx = topological_sort_pedigree(working_individuals)
    n = len(sorted_inds)

    sire_arr = np.full(n, -1, dtype=np.int32)
    dam_arr = np.full(n, -1, dtype=np.int32)

    for i, ind in enumerate(sorted_inds):
        if ind.sire_id and ind.sire_id in id_to_idx:
            sire_arr[i] = id_to_idx[ind.sire_id]
        if ind.dam_id and ind.dam_id in id_to_idx:
            dam_arr[i] = id_to_idx[ind.dam_id]

    # Get indices for sire and dam
    sire_idx = id_to_idx.get(sire_id, -1)
    dam_idx = id_to_idx.get(dam_id, -1)

    if sire_idx < 0 or dam_idx < 0:
        return 0.0

    # Calculate inbreeding coefficients (needed for kinship diagonal)
    F = _calculate_inbreeding_henderson(n, sire_arr, dam_arr)

    # Build kinship cache with diagonal values
    kinship_cache: dict[tuple[int, int], float] = {}
    for i in range(n):
        kinship_cache[(i, i)] = 0.5 * (1.0 + F[i])

    # F_offspring = kinship(sire, dam) - just compute this one value!
    return _compute_kinship_iterative(sire_idx, dam_idx, sire_arr, dam_arr, F, kinship_cache)


def calculate_offspring_inbreeding_fast(
    sire_idx: int,
    dam_idx: int,
    sire_indices: np.ndarray,
    dam_indices: np.ndarray,
    F: np.ndarray,
    kinship_cache: dict[tuple[int, int], float],
) -> float:
    """
    Fast version when you already have the pedigree arrays and inbreeding.

    Use this when doing multiple test breedings to avoid recalculating
    the pedigree structure each time.

    Args:
        sire_idx: Index of sire in sorted pedigree
        dam_idx: Index of dam in sorted pedigree
        sire_indices: Pre-computed sire index array
        dam_indices: Pre-computed dam index array
        F: Pre-computed inbreeding coefficients
        kinship_cache: Shared kinship cache (will be updated)

    Returns:
        Inbreeding coefficient for potential offspring
    """
    if sire_idx < 0 or dam_idx < 0:
        return 0.0

    return _compute_kinship_iterative(sire_idx, dam_idx, sire_indices, dam_indices, F, kinship_cache)


# ============================================================================
# Founder Analysis Functions
# ============================================================================


def identify_founders(individuals: list[Individual]) -> list[str]:
    """
    Identify founder individuals in the pedigree.

    A founder is an individual with neither parent in the pedigree (unknown, or
    recorded but not among `individuals`), as kinship and gene drop treat it.

    Args:
        individuals: List of Individual objects

    Returns:
        List of founder IDs
    """
    ids = {ind.id for ind in individuals}
    return [ind.id for ind in individuals if ind.sire_id not in ids and ind.dam_id not in ids]


def count_founders(individuals: list[Individual]) -> int:
    """Founders of the cycle-repaired pedigree plus its phantom parents: the count FE is bounded by.

    An animal with neither parent in the pedigree is a founder; one with exactly one
    parent in it has a phantom parent (see founder_equivalents_of). Each counts once.
    """
    pedigree = topological_sort_pedigree(individuals)[0]
    ids = {ind.id for ind in pedigree}
    return sum(not (ind.sire_id in ids and ind.dam_id in ids) for ind in pedigree)


def calculate_founder_contributions(
    individuals: list[Individual], population_ids: list[str] | None = None
) -> tuple[dict[str, dict[str, float]], list[str]]:
    """
    Calculate the genetic contribution of each founder to each individual.

    For each individual, this calculates the expected proportion of their genome
    that derives from each founder. This is based on Mendelian inheritance:
    - Each individual receives exactly 0.5 of their genome from each parent
    - Founders contribute 1.0 to themselves and 0.0 to other founders

    Args:
        individuals: List of Individual objects
        population_ids: If provided, only calculate for these individuals

    Returns:
        Tuple of:
        - Dict mapping individual ID to dict of {founder_id: contribution}
        - List of founder IDs (in consistent order)
    """
    if not individuals:
        return {}, []

    # Sort pedigree topologically (parents before offspring)
    sorted_inds, id_to_idx = topological_sort_pedigree(individuals)
    n = len(sorted_inds)

    # Identify founders
    founders = identify_founders(sorted_inds)
    n_founders = len(founders)

    if n_founders == 0:
        return {ind.id: {} for ind in individuals}, []

    # Create founder index mapping
    founder_to_idx = {f: i for i, f in enumerate(founders)}

    # Matrix of founder contributions: rows = individuals, cols = founders
    # FC[i, f] = proportion of individual i's genome from founder f
    FC = np.zeros((n, n_founders), dtype=np.float64)

    # Initialize founders: each founder contributes 1.0 to themselves
    for founder_id in founders:
        idx = id_to_idx[founder_id]
        f_idx = founder_to_idx[founder_id]
        FC[idx, f_idx] = 1.0

    # Process non-founders in topological order
    for i, ind in enumerate(sorted_inds):
        if ind.id in founder_to_idx:
            continue  # Skip founders

        sire_idx = id_to_idx.get(ind.sire_id) if ind.sire_id else None
        dam_idx = id_to_idx.get(ind.dam_id) if ind.dam_id else None

        # FC[i] = 0.5 * FC[sire] + 0.5 * FC[dam]
        if sire_idx is not None:
            FC[i, :] += 0.5 * FC[sire_idx, :]
        if dam_idx is not None:
            FC[i, :] += 0.5 * FC[dam_idx, :]

    # Convert to dictionary format
    result = {}
    for i, ind in enumerate(sorted_inds):
        if population_ids is not None and ind.id not in population_ids:
            continue

        # Only include non-zero contributions
        contributions = {}
        for f_idx, founder_id in enumerate(founders):
            if FC[i, f_idx] > 0:
                contributions[founder_id] = float(FC[i, f_idx])
        result[ind.id] = contributions

    return result, founders


def calculate_average_founder_contributions(
    individuals: list[Individual], population_ids: list[str] | None = None
) -> tuple[dict[str, float], list[str]]:
    """
    Calculate the average founder contribution across a population.

    This is the mean proportion of genes from each founder in the population.
    Used for calculating Founder Equivalents (FE).

    Args:
        individuals: List of Individual objects
        population_ids: IDs of individuals in the target population
                       (defaults to all active individuals)

    Returns:
        Tuple of:
        - Dict mapping founder_id to average contribution
        - List of founder IDs
    """
    if not individuals:
        return {}, []

    # Default to active individuals
    if population_ids is None:
        population_ids = [ind.id for ind in individuals if ind.is_active]

    if not population_ids:
        return {}, []

    # Get individual founder contributions
    contrib, founders = calculate_founder_contributions(individuals, population_ids)

    if not founders:
        return {}, []

    # Calculate average across population
    n_pop = len(population_ids)
    avg_contrib = {f: 0.0 for f in founders}

    for ind_id in population_ids:
        if ind_id in contrib:
            for founder_id, value in contrib[ind_id].items():
                avg_contrib[founder_id] += value / n_pop

    return avg_contrib, founders


def founder_equivalents_of(sire, dam, founders, mask) -> tuple[float, int]:
    """(FE, phantom parents contributing) over the members in ``mask``, in one reverse pass.

    ``sire``/``dam`` are parent indices into a topologically sorted pedigree
    (-1 = not in the pedigree); ``founders`` are the indices of the animals with
    neither parent in it. Each member starts with weight 1 and hands half of it
    to each parent; a founder keeps it. The missing parent of an animal with one
    known parent is a phantom: an unrelated founder of its own, as in the kinship
    and gene-drop models. The shares then sum to 1, so FE never exceeds the
    founders plus phantoms (Lacy 1989). O(n), no individuals x founders matrix.
    """
    weight = mask.astype(float).tolist()
    phantoms = []
    for i in range(len(weight) - 1, -1, -1):
        w = weight[i]
        if w and (sire[i] >= 0 or dam[i] >= 0):
            for parent in (sire[i], dam[i]):
                if parent >= 0:
                    weight[parent] += 0.5 * w
                else:
                    phantoms.append(0.5 * w)
    n = int(mask.sum())
    p = np.asarray(weight)[np.asarray(founders, dtype=np.int64)] / n
    sum_p_squared = float(np.sum(p**2) + np.sum((np.asarray(phantoms) / n) ** 2))
    return (1.0 / sum_p_squared if sum_p_squared else 0.0), len(phantoms)


def _founder_equivalents_and_phantoms(individuals, population_ids):
    """founder_equivalents_of on Individual objects; (0.0, 0) without population members."""
    sorted_inds, index = topological_sort_pedigree(individuals)
    members = set(population_ids)
    mask = np.array([ind.id in members for ind in sorted_inds], dtype=bool)
    if not mask.any():
        return 0.0, 0
    sire = [index.get(ind.sire_id, -1) for ind in sorted_inds]
    dam = [index.get(ind.dam_id, -1) for ind in sorted_inds]
    return founder_equivalents_of(sire, dam, [index[f] for f in identify_founders(sorted_inds)], mask)


def calculate_founder_equivalents(individuals: list[Individual], population_ids: list[str] | None = None) -> float:
    """
    Calculate Founder Equivalents (FE) for a population.

    FE = 1 / Σ(pᵢ²) where pᵢ is the average contribution of founder i; the
    unknown parent of an animal with one known parent is a founder of its own
    (see founder_equivalents_of).

    FE represents the number of equally contributing founders that would give
    the same level of genetic diversity. A population with n founders but
    unequal contributions will have FE < n.

    Reference:
        Lacy, R.C. (1989). Analysis of founder representation in pedigrees:
        Founder equivalents and founder genome equivalents. Zoo Biology, 8, 111-123.

    Args:
        individuals: List of Individual objects
        population_ids: IDs of individuals in the target population
                       (defaults to all active individuals)

    Returns:
        Founder Equivalents value (float)
    """
    if population_ids is None:
        population_ids = [ind.id for ind in individuals if ind.is_active]
    return _founder_equivalents_and_phantoms(individuals, population_ids)[0]


def calculate_founder_statistics(
    individuals: list[Individual],
    population_ids: list[str] | None = None,
    mean_kinship: dict[str, float] | None = None,
) -> dict:
    """
    Calculate comprehensive founder statistics for a population.

    Returns a dictionary with:
    - n_founders: Number of founders contributing to the population (avg contribution > 0),
      phantom parents included (see founder_equivalents_of), so FE <= n_founders
    - n_founders_total: Number of founders in the whole pedigree, phantom parents included
    - founder_equivalents: FE value
    - proportional_loss: Proportion of the founders' gene diversity lost,
      1 - GD = mean kinship over the population including self-kinship
      (= 1 / (2 * FGE); Lacy 1995)
    - top_founders: List of (founder_id, contribution) sorted by contribution
    - avg_contributions: Dict of founder -> average contribution

    Args:
        individuals: List of Individual objects
        population_ids: IDs of individuals in the target population
        mean_kinship: Mean kinship per population member (incl. self-kinship),
            e.g. a cached calculate_mean_kinship() result. Computed when omitted.

    Returns:
        Dictionary with founder statistics
    """
    if population_ids is None:
        population_ids = [ind.id for ind in individuals if ind.is_active]

    avg_contrib, _ = calculate_average_founder_contributions(individuals, population_ids)

    fe, n_phantoms = _founder_equivalents_and_phantoms(individuals, population_ids)
    n_founders = sum(1 for p in avg_contrib.values() if p > 0) + n_phantoms

    # Sort founders by contribution (descending)
    sorted_founders = sorted(avg_contrib.items(), key=lambda x: x[1], reverse=True)

    if mean_kinship is None:
        population = set(population_ids)
        mean_kinship = calculate_mean_kinship([replace(ind, is_active=ind.id in population) for ind in individuals])
    proportional_loss = float(np.mean(list(mean_kinship.values()))) if mean_kinship else 0.0

    return {
        "n_founders": n_founders,
        "n_founders_total": count_founders(individuals),
        "founder_equivalents": fe,
        "proportional_loss": proportional_loss,
        "top_founders": sorted_founders[:20],  # Top 20
        "avg_contributions": avg_contrib,
        "population_size": len(population_ids),
    }


# ============================================================================
# Gene Drop Simulation Functions
# ============================================================================


def gene_drop_simulation(
    individuals: list[Individual],
    n_iterations: int = 1000,
    population_ids: list[str] | None = None,
    seed: int | None = None,
) -> tuple[np.ndarray, list[str], list[str]]:
    """
    Perform gene drop simulation to estimate allele retention.

    This Monte Carlo method simulates Mendelian inheritance through the pedigree
    to estimate the probability that founder alleles survive to the current
    population. Each founder is assigned two unique alleles (one per chromosome),
    and inheritance is simulated randomly.

    Reference:
        MacCluer, J.W., VandeBerg, J.L., Read, B., & Ryder, O.A. (1986).
        Pedigree analysis by computer simulation. Zoo Biology, 5(2), 147-160.

    Args:
        individuals: List of Individual objects
        n_iterations: Number of simulation iterations (default: 1000)
        population_ids: IDs of individuals in the target population
                       (defaults to all active individuals)
        seed: Random seed for reproducibility (optional)

    Returns:
        Tuple of:
        - allele_matrix: Shape (n_pop * 2, n_iterations) with allele IDs
        - population_ids: IDs of individuals in population
        - founder_ids: IDs of founder individuals
    """
    # Local generator: reproducible for a given seed without touching NumPy's
    # global RNG state (shared by everything else in the worker).
    rng = np.random.default_rng(seed)

    if not individuals:
        return np.array([[]]), [], []

    # Sort pedigree topologically
    sorted_inds, id_to_idx = topological_sort_pedigree(individuals)
    n = len(sorted_inds)

    # Identify founders
    founders = identify_founders(sorted_inds)
    n_founders = len(founders)

    if n_founders == 0:
        return np.array([[]]), [], []

    # Create founder to allele mapping
    # Each founder gets 2 unique alleles: founder_idx * 2 and founder_idx * 2 + 1
    founder_to_idx = {f: i for i, f in enumerate(founders)}

    # Default population is all active individuals
    if population_ids is None:
        population_ids = [ind.id for ind in individuals if ind.is_active]

    # Get population indices in sorted order
    pop_indices = [id_to_idx[pid] for pid in population_ids if pid in id_to_idx]

    if not pop_indices:
        return np.array([[]]), [], founders

    # Prepare parent indices
    sire_idx = np.full(n, -1, dtype=np.int32)
    dam_idx = np.full(n, -1, dtype=np.int32)

    for i, ind in enumerate(sorted_inds):
        if ind.sire_id and ind.sire_id in id_to_idx:
            sire_idx[i] = id_to_idx[ind.sire_id]
        if ind.dam_id and ind.dam_id in id_to_idx:
            dam_idx[i] = id_to_idx[ind.dam_id]

    # Run simulation
    # Each individual has 2 alleles (paternal and maternal)
    # Allele IDs: 0 to 2*n_founders-1 for founder alleles
    #             <= -2 for a missing (unknown or unloaded) parent: a unique
    #             phantom allele per slot, i.e. an unrelated founder, as in the
    #             kinship model. Founder-based outputs only look at ids >= 0.
    phantom_alleles = (-2 - np.arange(2 * n, dtype=np.int32)).reshape(n, 2)

    n_pop = len(pop_indices)
    allele_matrix = np.zeros((n_pop * 2, n_iterations), dtype=np.int32)

    for iteration in range(n_iterations):
        # Alleles for each individual: [paternal, maternal]; slots without a
        # known parent keep their phantom allele
        alleles = phantom_alleles.copy()

        # Initialize founder alleles
        for founder_id in founders:
            idx = id_to_idx[founder_id]
            f_idx = founder_to_idx[founder_id]
            alleles[idx, 0] = f_idx * 2  # Paternal allele
            alleles[idx, 1] = f_idx * 2 + 1  # Maternal allele

        # Propagate alleles through pedigree (topologically sorted)
        for i, ind in enumerate(sorted_inds):
            if ind.id in founder_to_idx:
                continue  # Founders already initialized

            s = sire_idx[i]
            d = dam_idx[i]

            # Randomly inherit one allele from each parent
            if s >= 0:
                # Pick paternal (0) or maternal (1) allele from sire
                alleles[i, 0] = alleles[s, rng.integers(2)]
            if d >= 0:
                # Pick paternal (0) or maternal (1) allele from dam
                alleles[i, 1] = alleles[d, rng.integers(2)]

        # Extract population alleles
        for pi, pop_idx in enumerate(pop_indices):
            allele_matrix[pi * 2, iteration] = alleles[pop_idx, 0]
            allele_matrix[pi * 2 + 1, iteration] = alleles[pop_idx, 1]

    actual_pop_ids = [sorted_inds[i].id for i in pop_indices]
    return allele_matrix, actual_pop_ids, founders


def calculate_founder_genome_contributions(allele_matrix: np.ndarray, founders: list[str]) -> dict[str, float]:
    """
    Calculate average founder genome contributions from gene drop results.

    Args:
        allele_matrix: Shape (n_pop * 2, n_iterations) from gene_drop_simulation
        founders: List of founder IDs

    Returns:
        Dictionary mapping founder_id to average genome proportion
    """
    if allele_matrix.size == 0 or len(founders) == 0:
        return {}

    n_allele_copies = allele_matrix.shape[0]  # Total allele copies in population
    n_iterations = allele_matrix.shape[1]

    # Count founder contributions across all iterations
    contributions = {f: 0.0 for f in founders}

    for iteration in range(n_iterations):
        iter_alleles = allele_matrix[:, iteration]

        for f_idx, founder_id in enumerate(founders):
            # Founder f has alleles 2*f_idx and 2*f_idx+1
            allele1 = f_idx * 2
            allele2 = f_idx * 2 + 1
            count = np.sum((iter_alleles == allele1) | (iter_alleles == allele2))
            contributions[founder_id] += count / n_allele_copies

    # Average across iterations
    for f in founders:
        contributions[f] /= n_iterations

    return contributions


def calculate_founder_genome_equivalents(
    individuals: list[Individual],
    n_iterations: int = 1000,
    population_ids: list[str] | None = None,
    seed: int | None = None,
) -> float:
    """
    Calculate Founder Genome Equivalents (FGE) using gene drop simulation.

    FGE accounts for genetic drift and allele loss during transmission,
    unlike FE which only considers expected contributions. FGE will always
    be less than or equal to FE.

    FGE = 1 / (2 * (1 - GD)), where GD is the gene diversity of the population
    (1 - mean kinship including self-kinship), here taken from the simulation.
    Note: 1 / Σ(pᵢ²) of the *averaged* simulated contributions converges to FE,
    not FGE, because drift averages out.

    Reference:
        Lacy, R.C. (1989). Analysis of founder representation in pedigrees:
        Founder equivalents and founder genome equivalents. Zoo Biology, 8, 111-123.
        Ballou, J.D. & Lacy, R.C. (1995). Identifying genetically important
        individuals for management of genetic variation in pedigreed populations.

    Args:
        individuals: List of Individual objects
        n_iterations: Number of simulation iterations (default: 1000)
        population_ids: IDs of individuals in the target population
        seed: Random seed for reproducibility

    Returns:
        Founder Genome Equivalents value (float)
    """
    allele_matrix, _, _ = gene_drop_simulation(individuals, n_iterations, population_ids, seed)

    if allele_matrix.size == 0:
        return 0.0

    return _fge_from_gene_diversity(_gene_diversity_from_alleles(allele_matrix))


def _gene_diversity_from_alleles(allele_matrix: np.ndarray) -> float:
    """Mean over iterations of 1 - Σfᵢ² of the simulated population alleles.

    Every allele copy counts, phantom alleles of missing parents included, so
    numerator and denominator cover the same copies.
    """
    n_allele_copies = allele_matrix.shape[0]
    gene_diversities = []
    for iteration in range(allele_matrix.shape[1]):
        _, allele_counts = np.unique(allele_matrix[:, iteration], return_counts=True)
        allele_freqs = allele_counts / n_allele_copies
        gene_diversities.append(1.0 - np.sum(allele_freqs**2))
    return float(np.mean(gene_diversities))


def _fge_from_gene_diversity(gene_diversity: float) -> float:
    """FGE = 1 / (2 * (1 - GD)) (Lacy 1989; Ballou & Lacy 1995)."""
    loss = 1.0 - gene_diversity
    if loss <= 0:
        return 0.0
    return 1.0 / (2.0 * loss)


def calculate_allele_retention(
    individuals: list[Individual],
    n_iterations: int = 1000,
    population_ids: list[str] | None = None,
    seed: int | None = None,
) -> dict[str, float]:
    """
    Calculate the probability that each founder's alleles survive in the population.

    For each founder, this estimates the proportion of iterations where at least
    one of their alleles is present in the population.

    Args:
        individuals: List of Individual objects
        n_iterations: Number of simulation iterations
        population_ids: IDs of individuals in the target population
        seed: Random seed for reproducibility

    Returns:
        Dictionary mapping founder_id to retention probability (0.0 - 1.0)
    """
    allele_matrix, _, founders = gene_drop_simulation(individuals, n_iterations, population_ids, seed)

    if allele_matrix.size == 0:
        return {}

    n_iterations_actual = allele_matrix.shape[1]
    retention = {f: 0.0 for f in founders}

    for iteration in range(n_iterations_actual):
        iter_alleles = set(allele_matrix[:, iteration])

        for f_idx, founder_id in enumerate(founders):
            allele1 = f_idx * 2
            allele2 = f_idx * 2 + 1
            if allele1 in iter_alleles or allele2 in iter_alleles:
                retention[founder_id] += 1

    # Convert to probability
    for f in founders:
        retention[f] /= n_iterations_actual

    return retention


def calculate_gene_diversity(
    individuals: list[Individual],
    n_iterations: int = 1000,
    population_ids: list[str] | None = None,
    seed: int | None = None,
) -> float:
    """
    Calculate expected gene diversity (heterozygosity) in the population.

    Gene diversity is 1 - Σfᵢ² where fᵢ is the frequency of allele i.
    This represents the probability that two randomly chosen alleles are different.

    Args:
        individuals: List of Individual objects
        n_iterations: Number of simulation iterations
        population_ids: IDs of individuals in the target population
        seed: Random seed for reproducibility

    Returns:
        Expected gene diversity (0.0 - 1.0)
    """
    allele_matrix, _, _ = gene_drop_simulation(individuals, n_iterations, population_ids, seed)

    if allele_matrix.size == 0:
        return 0.0

    return _gene_diversity_from_alleles(allele_matrix)


def calculate_gene_drop_statistics(
    individuals: list[Individual],
    n_iterations: int = 1000,
    population_ids: list[str] | None = None,
    seed: int | None = None,
) -> dict:
    """
    Calculate comprehensive gene drop statistics.

    Returns:
        Dictionary with:
        - n_founders: Number of founders, phantom parents included (count_founders)
        - founder_genome_equivalents: FGE value
        - founder_equivalents: FE value (for comparison)
        - genome_contributions: Dict of founder -> simulated genome proportion
        - allele_retention: Dict of founder -> retention probability
        - gene_diversity: Expected heterozygosity
        - n_iterations: Number of iterations used
    """
    if population_ids is None:
        population_ids = [ind.id for ind in individuals if ind.is_active]

    # Run single simulation for all metrics
    allele_matrix, actual_pop_ids, founders = gene_drop_simulation(individuals, n_iterations, population_ids, seed)

    n_founders = len(founders)

    if allele_matrix.size == 0 or n_founders == 0:
        return {
            "n_founders": count_founders(individuals),
            "founder_genome_equivalents": 0.0,
            "founder_equivalents": 0.0,
            "genome_contributions": {},
            "allele_retention": {},
            "gene_diversity": 0.0,
            "n_iterations": n_iterations,
            "population_size": len(population_ids),
        }

    # Calculate metrics from single simulation
    genome_contrib = calculate_founder_genome_contributions(allele_matrix, founders)

    # FE (expected, without drift)
    fe = calculate_founder_equivalents(individuals, population_ids)

    # Allele retention
    n_iterations_actual = allele_matrix.shape[1]
    retention = {f: 0.0 for f in founders}
    for iteration in range(n_iterations_actual):
        iter_alleles = set(allele_matrix[:, iteration])
        for f_idx, founder_id in enumerate(founders):
            if (f_idx * 2) in iter_alleles or (f_idx * 2 + 1) in iter_alleles:
                retention[founder_id] += 1
    for f in founders:
        retention[f] /= n_iterations_actual

    # Gene diversity, and FGE = 1 / (2 * (1 - GD)) from it
    gene_diversity = _gene_diversity_from_alleles(allele_matrix)
    fge = _fge_from_gene_diversity(gene_diversity)

    return {
        "n_founders": count_founders(individuals),  # phantom parents included, like FE
        "founder_genome_equivalents": fge,
        "founder_equivalents": fe,
        "genome_contributions": genome_contrib,
        "allele_retention": retention,
        "gene_diversity": gene_diversity,
        "n_iterations": n_iterations,
        "population_size": len(actual_pop_ids),
    }


def calculate_genome_uniqueness(
    allele_matrix: np.ndarray,
    population_ids: list[str],
) -> dict[str, float]:
    """
    Calculate Genome Uniqueness (GU) for each individual from gene drop results.

    GU[i] = fraction of simulation iterations where individual i carries at least
    one allele that no other individual in the population carries.

    Args:
        allele_matrix: Shape (n_pop * 2, n_iterations) from gene_drop_simulation()
        population_ids: IDs of individuals in the population

    Returns:
        Dictionary mapping individual ID to GU value (0.0 to 1.0)
    """
    if allele_matrix.size == 0 or not population_ids:
        return {}

    n_pop = len(population_ids)
    n_iterations = allele_matrix.shape[1]
    gu_counts = np.zeros(n_pop)

    for iteration in range(n_iterations):
        col = allele_matrix[:, iteration]

        # Count carriers of each allele, not copies: a homozygous private allele is still unique.
        # Each individual has 2 rows: idx*2 (paternal) and idx*2+1 (maternal)
        allele_counts: dict[int, int] = {}
        for ind_idx in range(n_pop):
            for allele in {col[ind_idx * 2], col[ind_idx * 2 + 1]}:
                if allele >= 0:
                    allele_counts[allele] = allele_counts.get(allele, 0) + 1

        # Check each individual for unique alleles
        for ind_idx in range(n_pop):
            paternal = col[ind_idx * 2]
            maternal = col[ind_idx * 2 + 1]

            has_unique = False
            if paternal >= 0 and allele_counts.get(paternal, 0) == 1:
                has_unique = True
            if maternal >= 0 and allele_counts.get(maternal, 0) == 1:
                has_unique = True

            if has_unique:
                gu_counts[ind_idx] += 1

    return {pop_id: float(gu_counts[i] / n_iterations) for i, pop_id in enumerate(population_ids)}


# ============================================================================
# Population Metrics Functions (Phase 4)
# ============================================================================


def calculate_generation_numbers(individuals: list[Individual]) -> dict[str, dict[str, float]]:
    """
    Calculate generation numbers for each individual.

    Returns three different generation measures for each individual:
    - max_gen: Maximum number of generations to any founder
    - full_gen: Number of complete generations (all 2^n ancestors known)
    - equiv_gen: Equivalent complete generations (Σ(1/2)^n for each known ancestor)

    The equivalent complete generations (equiGen) is the most informative measure,
    as it accounts for partial pedigree knowledge.

    Reference:
        Maignel, L., Boichard, D., & Verrier, E. (1996). Genetic variability of
        French dairy breeds estimated from pedigree information. Interbull Bulletin, 14, 49-54.

    Args:
        individuals: List of Individual objects

    Returns:
        Dictionary mapping individual ID to {max_gen, full_gen, equiv_gen}
    """
    if not individuals:
        return {}

    # Sort pedigree topologically
    sorted_inds, id_to_idx = topological_sort_pedigree(individuals)

    # Build parent lookup
    id_to_ind = {ind.id: ind for ind in sorted_inds}

    result = {}

    for ind in sorted_inds:
        # Calculate max generation (depth to deepest founder)
        max_gen = _calculate_max_generation(ind.id, id_to_ind, {})

        # Calculate full generations (complete generations)
        full_gen = _calculate_full_generation(ind.id, id_to_ind, {})

        # Calculate equivalent complete generations
        equiv_gen = _calculate_equiv_generation(ind.id, id_to_ind, {})

        result[ind.id] = {"max_gen": max_gen, "full_gen": full_gen, "equiv_gen": equiv_gen}

    return result


def _calculate_max_generation(ind_id: str, id_to_ind: dict[str, Individual], cache: dict[str, int]) -> int:
    """
    Calculate maximum generation number (depth to deepest founder).

    Founders have generation 0.
    Non-founders have max(gen_sire, gen_dam) + 1.
    """
    if ind_id in cache:
        return cache[ind_id]

    if ind_id not in id_to_ind:
        return 0

    ind = id_to_ind[ind_id]

    # Founders have generation 0
    if ind.sire_id is None and ind.dam_id is None:
        cache[ind_id] = 0
        return 0

    gen_sire = 0
    gen_dam = 0

    if ind.sire_id and ind.sire_id in id_to_ind:
        gen_sire = _calculate_max_generation(ind.sire_id, id_to_ind, cache) + 1
    if ind.dam_id and ind.dam_id in id_to_ind:
        gen_dam = _calculate_max_generation(ind.dam_id, id_to_ind, cache) + 1

    result = max(gen_sire, gen_dam)
    cache[ind_id] = result
    return result


def _calculate_full_generation(ind_id: str, id_to_ind: dict[str, Individual], cache: dict[str, int]) -> int:
    """
    Calculate number of complete generations.

    A complete generation n means all 2^n ancestors are known.
    """
    if ind_id in cache:
        return cache[ind_id]

    if ind_id not in id_to_ind:
        return 0

    ind = id_to_ind[ind_id]

    # Founders have full_gen = 0
    if ind.sire_id is None and ind.dam_id is None:
        cache[ind_id] = 0
        return 0

    # Both parents must be known for at least 1 complete generation
    if ind.sire_id is None or ind.dam_id is None:
        cache[ind_id] = 0
        return 0

    if ind.sire_id not in id_to_ind or ind.dam_id not in id_to_ind:
        cache[ind_id] = 0
        return 0

    # Full generation = min of parents' full generations + 1
    full_sire = _calculate_full_generation(ind.sire_id, id_to_ind, cache)
    full_dam = _calculate_full_generation(ind.dam_id, id_to_ind, cache)

    result = min(full_sire, full_dam) + 1
    cache[ind_id] = result
    return result


def _calculate_equiv_generation(ind_id: str, id_to_ind: dict[str, Individual], cache: dict[str, float]) -> float:
    """
    Calculate equivalent complete generations.

    equiGen = Σ(1/2)^n for each known ancestor at generation n.

    This is calculated recursively:
    equiGen(i) = 0.5 * (1 + equiGen(sire)) + 0.5 * (1 + equiGen(dam))
               = 1 + 0.5 * equiGen(sire) + 0.5 * equiGen(dam)

    For founders (no known parents): equiGen = 0
    For one known parent: equiGen = 0.5 * (1 + equiGen(parent))
    """
    if ind_id in cache:
        return cache[ind_id]

    if ind_id not in id_to_ind:
        return 0.0

    ind = id_to_ind[ind_id]

    # Founders have equiv_gen = 0
    if ind.sire_id is None and ind.dam_id is None:
        cache[ind_id] = 0.0
        return 0.0

    result = 0.0

    # Each known parent contributes 0.5 * (1 + their equiv_gen)
    if ind.sire_id and ind.sire_id in id_to_ind:
        result += 0.5 * (1.0 + _calculate_equiv_generation(ind.sire_id, id_to_ind, cache))

    if ind.dam_id and ind.dam_id in id_to_ind:
        result += 0.5 * (1.0 + _calculate_equiv_generation(ind.dam_id, id_to_ind, cache))

    cache[ind_id] = result
    return result


def calculate_pedigree_completeness(
    individuals: list[Individual], max_generations: int = 5
) -> dict[str, dict[int, float]]:
    """
    Calculate pedigree completeness index (PCI) for each individual.

    PCI at generation g = proportion of known ancestors at that generation.
    At generation g, there are 2^g possible ancestors.

    Args:
        individuals: List of Individual objects
        max_generations: Maximum generations to check (default: 5)

    Returns:
        Dictionary mapping individual ID to {generation: completeness}
        where completeness is 0.0-1.0
    """
    if not individuals:
        return {}

    sorted_inds, id_to_idx = topological_sort_pedigree(individuals)
    id_to_ind = {ind.id: ind for ind in sorted_inds}

    result = {}

    for ind in sorted_inds:
        pci = {}
        for gen in range(1, max_generations + 1):
            known, total = _count_ancestors_at_generation(ind.id, gen, id_to_ind, {})
            pci[gen] = known / total if total > 0 else 0.0
        result[ind.id] = pci

    return result


def _count_ancestors_at_generation(
    ind_id: str, target_gen: int, id_to_ind: dict[str, Individual], cache: dict[tuple[str, int], tuple[int, int]]
) -> tuple[int, int]:
    """
    Count known vs expected ancestors at a specific generation.

    Returns (known_count, expected_count).
    """
    cache_key = (ind_id, target_gen)
    if cache_key in cache:
        return cache[cache_key]

    if target_gen == 0:
        # At generation 0, it's the individual itself
        if ind_id in id_to_ind:
            return (1, 1)
        return (0, 1)

    if ind_id not in id_to_ind:
        # Unknown individual - all ancestors at this level are unknown
        expected = 2**target_gen
        return (0, expected)

    ind = id_to_ind[ind_id]

    if target_gen == 1:
        # Direct parents
        known = 0
        if ind.sire_id and ind.sire_id in id_to_ind:
            known += 1
        if ind.dam_id and ind.dam_id in id_to_ind:
            known += 1
        result = (known, 2)
        cache[cache_key] = result
        return result

    # Recursively count for each parent
    known_sire, exp_sire = (0, 2 ** (target_gen - 1))
    known_dam, exp_dam = (0, 2 ** (target_gen - 1))

    if ind.sire_id and ind.sire_id in id_to_ind:
        known_sire, exp_sire = _count_ancestors_at_generation(ind.sire_id, target_gen - 1, id_to_ind, cache)

    if ind.dam_id and ind.dam_id in id_to_ind:
        known_dam, exp_dam = _count_ancestors_at_generation(ind.dam_id, target_gen - 1, id_to_ind, cache)

    result = (known_sire + known_dam, exp_sire + exp_dam)
    cache[cache_key] = result
    return result


def calculate_inbreeding_rate(individuals: list[Individual], method: str = "regression") -> dict[str, float]:
    """
    Calculate the rate of inbreeding (ΔF) over generations.

    Methods:
    - "regression": Linear regression of ln(1-F) on equivalent complete
      generations, over all supplied individuals with equiGen > 0
    - "generational": ΔF = (F_t - F_{t-1}) / (1 - F_{t-1}) per generation

    The regression method is more robust and recommended for practical use.

    Note: this is NOT the estimator of Gutiérrez et al. (2008), which uses the
    individual increase in inbreeding ΔFᵢ = 1 - (1 - Fᵢ)^(1/(tᵢ-1)) per animal
    (tᵢ = equivalent complete generations; t-1 exponent from Gutiérrez,
    Cervantes & Goyache 2009) and averages it over the population.

    Args:
        individuals: List of Individual objects
        method: Calculation method ("regression" or "generational")

    Returns:
        Dictionary with:
        - delta_f: Overall rate of inbreeding
        - delta_f_by_gen: ΔF for each generation (if method="generational")
        - r_squared: R² of regression (if method="regression")
    """
    if not individuals:
        return {"delta_f": 0.0}

    # Get inbreeding coefficients and generation numbers
    inbreeding = calculate_inbreeding_henderson(individuals)
    gen_numbers = calculate_generation_numbers(individuals)

    # Filter to individuals with equiv_gen > 0 and inbreeding data
    data = []
    for ind_id, gen_info in gen_numbers.items():
        if ind_id in inbreeding and gen_info["equiv_gen"] > 0:
            f = inbreeding[ind_id]
            g = gen_info["equiv_gen"]
            if f < 1.0:  # Exclude F=1 (undefined ln(1-F))
                data.append((g, f))

    if len(data) < 2:
        return {"delta_f": 0.0, "r_squared": 0.0}

    generations = np.array([d[0] for d in data])
    f_values = np.array([d[1] for d in data])

    if method == "regression":
        # Linear regression of ln(1-F) on generation
        # ln(1-F_t) = ln(1-F_0) - t * ΔF
        y = np.log(1 - f_values)
        x = generations

        # Simple linear regression
        n = len(x)
        sum_x = np.sum(x)
        sum_y = np.sum(y)
        sum_xy = np.sum(x * y)
        sum_x2 = np.sum(x**2)

        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x**2 + 1e-10)

        # ΔF = -slope (since ln(1-F) decreases with generation)
        delta_f = -slope

        # Calculate R²
        y_mean = np.mean(y)
        ss_tot = np.sum((y - y_mean) ** 2)
        y_pred = np.mean(y) + slope * (x - np.mean(x))
        ss_res = np.sum((y - y_pred) ** 2)
        r_squared = 1 - ss_res / (ss_tot + 1e-10)

        return {
            "delta_f": float(max(0, delta_f)),  # ΔF should be non-negative
            "r_squared": float(max(0, r_squared)),
            "n_individuals": len(data),
        }

    elif method == "generational":
        # Group by generation and calculate mean F
        gen_to_f = {}
        for g, f in data:
            gen_rounded = int(round(g))
            if gen_rounded not in gen_to_f:
                gen_to_f[gen_rounded] = []
            gen_to_f[gen_rounded].append(f)

        gen_mean_f = {g: np.mean(fs) for g, fs in gen_to_f.items()}

        # Calculate ΔF between consecutive generations
        sorted_gens = sorted(gen_mean_f.keys())
        delta_f_by_gen = {}

        for i in range(1, len(sorted_gens)):
            g_curr = sorted_gens[i]
            g_prev = sorted_gens[i - 1]
            f_curr = gen_mean_f[g_curr]
            f_prev = gen_mean_f[g_prev]

            if f_prev < 1.0:
                delta_f = (f_curr - f_prev) / (1 - f_prev)
                delta_f_by_gen[g_curr] = float(delta_f)

        # Overall ΔF is mean of per-generation values
        if delta_f_by_gen:
            overall_delta_f = np.mean(list(delta_f_by_gen.values()))
        else:
            overall_delta_f = 0.0

        return {"delta_f": float(max(0, overall_delta_f)), "delta_f_by_gen": delta_f_by_gen, "n_individuals": len(data)}

    return {"delta_f": 0.0}


def calculate_effective_population_size(individuals: list[Individual], method: str = "inbreeding") -> dict[str, float]:
    """
    Calculate effective population size (Ne).

    Methods:
    - "inbreeding": Ne = 1 / (2 * ΔF) based on rate of inbreeding
    - "variance": Based on variance in family sizes (requires breeding data)
    - "kinship": Based on increase in mean kinship over generations

    Reference:
        Falconer, D.S., & Mackay, T.F.C. (1996). Introduction to Quantitative
        Genetics (4th ed.). Longman.

    Args:
        individuals: List of Individual objects
        method: Calculation method (currently only "inbreeding" supported)

    Returns:
        Dictionary with:
        - ne: Effective population size
        - delta_f: Rate of inbreeding used
        - method: Method used
    """
    if not individuals:
        return {"ne": 0.0, "delta_f": 0.0, "method": method}

    if method == "inbreeding":
        # Ne = 1 / (2 * ΔF)
        inbreeding_rate = calculate_inbreeding_rate(individuals, method="regression")
        delta_f = inbreeding_rate.get("delta_f", 0.0)

        if delta_f > 0:
            ne = 1.0 / (2.0 * delta_f)
        else:
            ne = float("inf")  # No inbreeding = infinite Ne

        return {
            "ne": ne if ne != float("inf") else 0.0,  # Return 0 if inf
            "delta_f": delta_f,
            "r_squared": inbreeding_rate.get("r_squared", 0.0),
            "method": method,
            "n_individuals": inbreeding_rate.get("n_individuals", 0),
        }

    return {"ne": 0.0, "delta_f": 0.0, "method": method}


NE_METHOD = "individual_delta_f"


def calculate_realised_ne(inbreeding: list[float], equiv_gens: list[float]) -> dict:
    """
    Realised effective population size from the individual increase in inbreeding.

    For each animal with equivalent complete generations tᵢ > 1:
    ΔFᵢ = 1 - (1 - Fᵢ)^(1/(tᵢ - 1)); Ne = 1 / (2·mean ΔFᵢ) and
    SE(Ne) = 2·Ne²·sd(ΔFᵢ)/√N.

    Reference:
        Gutiérrez, J.P., Cervantes, I., Molina, A., Valera, M., & Goyache, F. (2008).
        Individual increase in inbreeding allows estimating effective sizes from
        pedigrees. Genetics Selection Evolution, 40, 359-378.
        Gutiérrez, J.P., Cervantes, I., & Goyache, F. (2009). Improving the
        estimation of realized effective population sizes in farm animals.
        Journal of Animal Breeding and Genetics, 126, 327-332 (the t - 1 exponent).

    Args:
        inbreeding: F per animal of the population
        equiv_gens: Equivalent complete generations per animal, same order

    Returns:
        Dict with ne, delta_f (mean ΔFᵢ), ne_se and ne_n; ne, delta_f and
        ne_se are None when Ne cannot be estimated (no animal with t > 1, or
        mean ΔFᵢ ≤ 0). ne_se is also None with fewer than two animals.
    """
    delta_fs = np.array(
        [1.0 - (1.0 - f) ** (1.0 / (t - 1.0)) for f, t in zip(inbreeding, equiv_gens, strict=True) if t > 1]
    )
    n = len(delta_fs)
    mean_delta_f = float(delta_fs.mean()) if n else 0.0
    if mean_delta_f <= 0:
        return {"ne": None, "delta_f": None, "ne_se": None, "ne_n": n}

    ne = 1.0 / (2.0 * mean_delta_f)
    ne_se = float(2.0 * ne**2 * delta_fs.std(ddof=1) / np.sqrt(n)) if n > 1 else None
    return {"ne": ne, "delta_f": mean_delta_f, "ne_se": ne_se, "ne_n": n}


def calculate_population_metrics(
    individuals: list[Individual],
    population_ids: list[str] | None = None,
    kinship: tuple[np.ndarray, list[str]] | None = None,
    inbreeding: dict[str, float] | None = None,
    gen_numbers: dict[str, dict[str, float]] | None = None,
) -> dict:
    """
    Calculate comprehensive population metrics.

    This function combines all population-level metrics into a single summary.
    ``kinship`` is an optional precomputed calculate_kinship_matrix(individuals,
    active_only=True) result, so a cached matrix is not rebuilt.
    ``inbreeding`` is an optional precomputed calculate_inbreeding_henderson(individuals)
    result and ``gen_numbers`` an optional precomputed
    calculate_generation_numbers(individuals) result; both are computed when omitted.

    Returns:
        Dictionary with:
        - population_size: Number of individuals in population
        - n_active: Number of active individuals
        - n_founders: Number of founders, phantom parents included (count_founders)
        - founder_equivalents: FE value
        - mean_inbreeding: Average inbreeding coefficient
        - max_inbreeding: Maximum inbreeding coefficient
        - mean_kinship: Average mean kinship
        - effective_population_size: Realised Ne from individual increase in
          inbreeding over the population (None when not estimable)
        - delta_f: Mean individual ΔF behind that Ne (None when not estimable)
        - ne_method: "individual_delta_f"
        - ne_se: Standard error of Ne (None when fewer than 2 animals or not estimable)
        - ne_n: Number of animals used for Ne (equivalent generations > 1)
        - expected_offspring_f: Expected offspring F under random mating among
          active males × active females = mean kinship over those pairs
          (None without both sexes)
        - mean_equiv_gen: Average equivalent generations
        - mean_full_gen: Average full generations
        - mean_max_gen: Average maximum generations
    """
    if not individuals:
        return {
            "population_size": 0,
            "n_active": 0,
            "n_founders": 0,
            "founder_equivalents": 0.0,
            "mean_inbreeding": 0.0,
            "max_inbreeding": 0.0,
            "mean_kinship": 0.0,
            "effective_population_size": None,
            "delta_f": None,
            "ne_method": NE_METHOD,
            "ne_se": None,
            "ne_n": 0,
            "expected_offspring_f": None,
            "mean_equiv_gen": 0.0,
            "mean_full_gen": 0.0,
            "mean_max_gen": 0.0,
        }

    # Determine population
    if population_ids is None:
        population_ids = [ind.id for ind in individuals if ind.is_active]

    n_active = len([ind for ind in individuals if ind.is_active])

    # Get individual metrics
    if inbreeding is None:
        inbreeding = calculate_inbreeding_henderson(individuals)
    if gen_numbers is None:
        gen_numbers = calculate_generation_numbers(individuals)

    # Filter to population
    pop_inbreeding = [inbreeding.get(pid, 0.0) for pid in population_ids]
    pop_gen = [gen_numbers.get(pid, {"max_gen": 0, "full_gen": 0, "equiv_gen": 0.0}) for pid in population_ids]

    # Kinship matrix over active individuals: mean kinship, and the expected
    # offspring F under random mating (mean K over active male × female pairs)
    K, kinship_ids = kinship if kinship is not None else calculate_kinship_matrix(individuals, active_only=True)
    mean_kinship_values = (
        {id_: float(mk) for id_, mk in zip(kinship_ids, np.mean(K, axis=0), strict=True)} if K.size else {}
    )
    sex_by_id = {ind.id: ind.sex for ind in individuals}
    male_idx = [i for i, id_ in enumerate(kinship_ids) if sex_by_id.get(id_) == "male"]
    female_idx = [i for i, id_ in enumerate(kinship_ids) if sex_by_id.get(id_) == "female"]
    expected_offspring_f = float(np.mean(K[np.ix_(male_idx, female_idx)])) if male_idx and female_idx else None
    pop_mean_kinship = [mean_kinship_values.get(pid, 0.0) for pid in population_ids if pid in mean_kinship_values]

    # Founder statistics
    fe = calculate_founder_equivalents(individuals, population_ids)

    # Realised effective population size over the population
    ne_result = calculate_realised_ne(
        [inbreeding.get(pid, 0.0) for pid in population_ids],
        [g["equiv_gen"] for g in pop_gen],
    )

    return {
        "population_size": len(individuals),
        "n_active": n_active,
        "n_population": len(population_ids),
        "n_founders": count_founders(individuals),  # phantom parents included, like FE
        "founder_equivalents": fe,
        "mean_inbreeding": float(np.mean(pop_inbreeding)) if pop_inbreeding else 0.0,
        "max_inbreeding": float(max(pop_inbreeding)) if pop_inbreeding else 0.0,
        "mean_kinship": float(np.mean(pop_mean_kinship)) if pop_mean_kinship else 0.0,
        "effective_population_size": ne_result["ne"],
        "delta_f": ne_result["delta_f"],
        "ne_method": NE_METHOD,
        "ne_se": ne_result["ne_se"],
        "ne_n": ne_result["ne_n"],
        "expected_offspring_f": expected_offspring_f,
        "mean_equiv_gen": float(np.mean([g["equiv_gen"] for g in pop_gen])) if pop_gen else 0.0,
        "mean_full_gen": float(np.mean([g["full_gen"] for g in pop_gen])) if pop_gen else 0.0,
        "mean_max_gen": float(np.mean([g["max_gen"] for g in pop_gen])) if pop_gen else 0.0,
    }


# ============================================================================
# Genetic Priority & Breeding Recommendation Functions (Phase 5)
# ============================================================================


@dataclass
class GeneticPriority:
    """Genetic conservation priority for an individual."""

    individual_id: str
    priority: str  # "critical" | "important" | "normal"
    reasons: list[str]
    genetic_value_score: float  # 0-100, inverted MK percentile (100=most valuable)
    genome_uniqueness: float  # 0.0-1.0, from gene drop simulation


@dataclass
class BreedingRecommendation:
    """A recommended breeding pair."""

    sire_id: str
    dam_id: str
    expected_f: float  # Offspring inbreeding = kinship(sire, dam)
    delta_gd: float  # Change in population gene diversity
    mate_suitability_index: int  # 1-6 (1=best), PMx-style
    reasons: list[str]


DEATH_YEAR_RE = re.compile(r"^(19\d{2}|20\d{2})[\s,]")


def extract_death_year(death_note: str | None) -> int | None:
    """Extract year from death_note like '2018 slakt' → 2018."""
    if not death_note:
        return None
    m = DEATH_YEAR_RE.match(death_note.strip())
    return int(m.group(1)) if m else None


MAX_RABBIT_AGE_DAYS = 8 * 365
HERD_TRACKING_ERA = date(2005, 1, 1)


def _get_birth_date(ind):
    """Get birth_date from an individual, handling DB model (breeding.birth_date) and mocks."""
    bd = getattr(ind, "birth_date", None)
    if bd is not None:
        return bd
    breeding = getattr(ind, "breeding", None)
    if breeding:
        return getattr(breeding, "birth_date", None)
    return None


def is_active_at_date(ind, target_date: date, tracking_lookup: dict | None = None) -> bool:
    """Determine if individual was likely active at target_date.

    Args:
        ind: Individual (or mock) with birth_date, certificate, death_date, etc.
            For DB models, birth_date is accessed via ind.breeding.birth_date.
        target_date: Snapshot date (typically YYYY-12-30).
        tracking_lookup: Dict {individual_id: bool} for herd tracking presence.
            If None, herd tracking check is skipped entirely.
    """
    birth_date = _get_birth_date(ind)
    if not birth_date or birth_date > target_date:
        return False
    if not (ind.certificate or ind.digital_certificate):
        return False
    if ind.castration_date and ind.castration_date <= target_date:
        return False

    # Death check
    if ind.death_date:
        if ind.death_date <= target_date:
            return False
    elif ind.death_note:
        year = extract_death_year(ind.death_note)
        if year and year <= target_date.year:
            return False
        elif not year:
            if (target_date - birth_date).days > MAX_RABBIT_AGE_DAYS:
                return False
    else:
        if (target_date - birth_date).days > MAX_RABBIT_AGE_DAYS:
            return False

    # Herd tracking (post-2005 only)
    if target_date >= HERD_TRACKING_ERA and tracking_lookup is not None:
        if not tracking_lookup.get(ind.id, False):
            return False

    return True


def identify_founders_at_risk(
    individuals: list[Individual],
    founder_contributions: dict[str, dict[str, float]],
    avg_contributions: dict[str, float],
    allele_retention: dict[str, float] | None = None,
) -> list[dict]:
    """
    Classify all founders by conservation status.

    Args:
        individuals: List of Individual objects
        founder_contributions: Per-individual founder contributions
        avg_contributions: Average founder contributions to the population
        allele_retention: Optional allele retention probabilities from gene drop

    Returns:
        List of dicts sorted by risk level then number of carriers:
        - founder_id, n_carriers, avg_contribution, allele_retention,
          carrier_ids, risk_level
        Risk levels: "lost" (0 active), "critical" (1), "warning" (2-3),
                     "monitor" (underrepresented), "ok" (healthy)
    """
    active = [ind for ind in individuals if ind.is_active]
    founders = identify_founders(individuals)
    if not founders or not active:
        return []

    equal_share = 1.0 / len(founders)

    results = []
    for founder_id in founders:
        # Find active carriers
        carriers = [ind.id for ind in active if founder_contributions.get(ind.id, {}).get(founder_id, 0.0) > 0]
        n_carriers = len(carriers)
        avg_c = avg_contributions.get(founder_id, 0.0)
        retention = allele_retention.get(founder_id, None) if allele_retention else None

        # Determine risk level
        if n_carriers == 0:
            risk_level = "lost"
        elif n_carriers == 1:
            risk_level = "critical"
        elif n_carriers <= 3:
            risk_level = "warning"
        elif avg_c < equal_share * 0.5:
            risk_level = "monitor"
        else:
            risk_level = "ok"

        # Only include carrier_ids when actionable (few carriers)
        include_carriers = risk_level in ("critical", "warning")

        results.append(
            {
                "founder_id": founder_id,
                "n_carriers": n_carriers,
                "avg_contribution": round(avg_c, 6),
                "allele_retention": round(retention, 4) if retention is not None else None,
                "carrier_ids": carriers if include_carriers else [],
                "risk_level": risk_level,
            }
        )

    risk_order = {"lost": 0, "critical": 1, "warning": 2, "monitor": 3, "ok": 4}
    results.sort(key=lambda x: (risk_order[x["risk_level"]], x["n_carriers"]))

    return results


def calculate_genetic_priorities(
    individuals: list[Individual],
    mean_kinship: dict[str, float],
    founder_contributions: dict[str, dict[str, float]],
    genome_uniqueness: dict[str, float],
) -> list[GeneticPriority]:
    """
    Assign genetic conservation priorities to active individuals.

    Priority rules (following PMx/Ballou & Lacy 1995):
    - critical: Sole living carrier of a founder line, or MK < 5th percentile
    - important: MK < 25th percentile, or GU > 75th percentile,
                 or carries underrepresented founder
    - normal: All others

    Args:
        individuals: List of Individual objects
        mean_kinship: Dict mapping individual ID to MK value
        founder_contributions: Dict mapping individual ID to {founder: contribution}
        genome_uniqueness: Dict mapping individual ID to GU value (0-1)

    Returns:
        List of GeneticPriority objects for all active individuals
    """
    active = [ind for ind in individuals if ind.is_active]
    if not active:
        return []

    # Get MK values for active individuals
    mk_values = [mean_kinship.get(ind.id, 0.0) for ind in active]

    if not mk_values:
        return []

    # Calculate percentiles
    mk_array = np.array(mk_values)
    p5 = float(np.percentile(mk_array, 5))
    p25 = float(np.percentile(mk_array, 25))

    # GU percentiles
    gu_values = [genome_uniqueness.get(ind.id, 0.0) for ind in active]
    gu_array = np.array(gu_values)
    gu_p75 = float(np.percentile(gu_array, 75)) if gu_array.size > 0 else 1.0

    # Identify founders and their active carriers
    founders = identify_founders(individuals)
    equal_share = 1.0 / len(founders) if founders else 0.0

    # Find sole carriers: founders where only one active individual has contribution > 0
    sole_carrier_of: dict[str, str] = {}  # individual_id -> founder_id
    for founder_id in founders:
        carriers = []
        for ind in active:
            contrib = founder_contributions.get(ind.id, {})
            if contrib.get(founder_id, 0.0) > 0:
                carriers.append(ind.id)
        if len(carriers) == 1:
            sole_carrier_of[carriers[0]] = founder_id

    # Find underrepresented founders (avg contribution < 50% of equal share)
    underrep_founders = set()
    if founders and equal_share > 0:
        for founder_id in founders:
            total_contrib = 0.0
            for ind in active:
                contrib = founder_contributions.get(ind.id, {})
                if founder_id in contrib:
                    total_contrib += contrib[founder_id]
            avg_contrib = total_contrib / len(active) if active else 0.0
            if avg_contrib < equal_share * 0.5:
                underrep_founders.add(founder_id)

    # Compute results
    results = []
    for ind in active:
        mk = mean_kinship.get(ind.id, 0.0)
        gu = genome_uniqueness.get(ind.id, 0.0)
        contrib = founder_contributions.get(ind.id, {})

        reasons = []
        priority = "normal"

        # Check critical conditions
        if ind.id in sole_carrier_of:
            priority = "critical"
            reasons.append(f"Sole active carrier of founder {sole_carrier_of[ind.id]}")

        if mk <= p5:
            if priority != "critical":
                priority = "critical"
            reasons.append(f"Mean kinship {mk:.4f} is below 5th percentile ({p5:.4f})")

        # Check important conditions (only upgrade, never downgrade)
        if priority == "normal":
            if mk <= p25:
                priority = "important"
                reasons.append(f"Mean kinship {mk:.4f} is below 25th percentile ({p25:.4f})")

            if gu > gu_p75 and gu > 0:
                if priority == "normal":
                    priority = "important"
                reasons.append(f"Genome uniqueness {gu:.4f} is above 75th percentile ({gu_p75:.4f})")

            # Check if individual carries underrepresented founder
            for founder_id in underrep_founders:
                if contrib.get(founder_id, 0.0) > 0:
                    if priority == "normal":
                        priority = "important"
                    reasons.append(f"Carries underrepresented founder {founder_id}")
                    break  # One reason is enough

        # Default reason for normal
        if not reasons:
            reasons.append("Genetic representation within normal range")

        # Genetic value score: inverted MK percentile rank (0-100)
        # Find rank position (how many have higher MK)
        higher_count = int(np.sum(mk_array > mk))
        score = (higher_count / len(mk_array)) * 100.0

        results.append(
            GeneticPriority(
                individual_id=ind.id,
                priority=priority,
                reasons=reasons,
                genetic_value_score=round(score, 1),
                genome_uniqueness=round(gu, 4),
            )
        )

    return results


def _calculate_msi(
    expected_f: float,
    delta_gd: float,
    mean_f: float,
) -> int:
    """
    Calculate Mate Suitability Index (1-6) following PMx convention.

    1 = excellent (low F, positive GD impact)
    6 = poor (high F, negative GD impact)

    Args:
        expected_f: Expected offspring inbreeding coefficient
        delta_gd: Change in gene diversity if this pair breeds
        mean_f: Current population mean inbreeding coefficient
    """
    # Score based on offspring inbreeding relative to population mean.
    # When mean_f ≈ 0 (founder-only populations), use absolute thresholds
    # to avoid all pairs scoring 6 due to 0-multiplication.
    if expected_f == 0.0:
        f_score = 1
    elif mean_f < 1e-10:
        if expected_f < 0.03125:
            f_score = 2
        elif expected_f < 0.0625:
            f_score = 3
        elif expected_f < 0.125:
            f_score = 4
        elif expected_f < 0.25:
            f_score = 5
        else:
            f_score = 6
    elif expected_f < mean_f * 0.5:
        f_score = 1
    elif expected_f < mean_f:
        f_score = 2
    elif expected_f < mean_f * 1.5:
        f_score = 3
    elif expected_f < mean_f * 2.0:
        f_score = 4
    elif expected_f < mean_f * 3.0:
        f_score = 5
    else:
        f_score = 6

    # Adjust based on gene diversity impact
    if delta_gd > 0:
        f_score = max(1, f_score - 1)
    elif delta_gd < -0.001:
        f_score = min(6, f_score + 1)

    return f_score


def suggest_breeding_pairs(
    individuals: list[Individual],
    kinship_matrix: np.ndarray,
    kinship_ids: list[str],
    mean_kinship: dict[str, float],
    max_pairs: int = 10,
    max_inbreeding: float = 0.0625,
    max_per_male: int = 3,
    max_per_female: int = 1,
) -> list[BreedingRecommendation]:
    """
    Suggest breeding pairs using Dynamic MK Selection (Ivy & Lacy 2012).

    This iterative algorithm:
    1. Ranks individuals by mean kinship (lowest first)
    2. Pairs the lowest-MK male with lowest-MK female
    3. Recalculates MK after adding hypothetical offspring
    4. Repeats until max_pairs is reached

    Args:
        individuals: List of Individual objects (must include sex field)
        kinship_matrix: Kinship matrix from calculate_kinship_matrix()
        kinship_ids: Individual IDs matching kinship_matrix rows/columns
        mean_kinship: Dict of individual ID to mean kinship value
        max_pairs: Maximum number of pairs to return
        max_inbreeding: Maximum acceptable offspring inbreeding coefficient
        max_per_male: Maximum times a single male can be used
        max_per_female: Maximum times a single female can be used (PMx default 1)

    Returns:
        List of BreedingRecommendation objects, sorted by MSI (best first)
    """
    if not individuals or kinship_matrix.size == 0 or not kinship_ids:
        return []

    id_to_idx = {id_: i for i, id_ in enumerate(kinship_ids)}

    # Build sex-specific pools from active individuals present in kinship matrix
    active = [ind for ind in individuals if ind.is_active and ind.id in id_to_idx]

    males = [ind for ind in active if ind.sex == "male"]
    females = [ind for ind in active if ind.sex == "female"]

    if not males or not females:
        return []

    # Current population gene diversity: GD = 1 - mean of all kinship matrix entries
    current_mean_mk = float(np.mean(kinship_matrix))

    # Mean inbreeding for MSI calculation
    inbreeding = calculate_inbreeding_henderson(individuals)
    active_f = [inbreeding.get(ind.id, 0.0) for ind in active]
    mean_f = float(np.mean(active_f)) if active_f else 0.0

    # Working copy of kinship matrix (we'll extend it with offspring)
    K = kinship_matrix.copy()
    current_ids = list(kinship_ids)
    current_id_to_idx = dict(id_to_idx)

    # Working copy of MK values
    working_mk = dict(mean_kinship)

    # Track male and female usage
    male_usage: dict[str, int] = {m.id: 0 for m in males}
    female_usage: dict[str, int] = {f.id: 0 for f in females}

    recommendations = []

    for _ in range(max_pairs):
        # Sort males and females by current MK (lowest first)
        available_males = [m for m in males if male_usage.get(m.id, 0) < max_per_male]
        available_males.sort(key=lambda m: working_mk.get(m.id, 0.0))
        females_sorted = sorted(
            (f for f in females if female_usage.get(f.id, 0) < max_per_female),
            key=lambda f: working_mk.get(f.id, 0.0),
        )

        best_pair = None

        for male in available_males:
            m_idx = current_id_to_idx.get(male.id)
            if m_idx is None:
                continue

            for female in females_sorted:
                f_idx = current_id_to_idx.get(female.id)
                if f_idx is None:
                    continue

                # Expected offspring F = kinship between parents
                expected_f = K[m_idx, f_idx]

                if expected_f > max_inbreeding:
                    continue

                # Exact change in gene diversity over the full current population
                # (active + hypothetical offspring from previous iterations):
                # μ_new = (n²μ + 2n·r̄ + d) / (n+1)², with r̄ the offspring's mean
                # kinship to the n animals and d its self-kinship 0.5·(1 + F).
                n_current = K.shape[0]
                offspring_mean_k = float(np.mean(0.5 * (K[m_idx, :] + K[f_idx, :])))
                offspring_self_k = 0.5 * (1.0 + expected_f)
                new_mean_mk = (n_current**2 * current_mean_mk + 2 * n_current * offspring_mean_k + offspring_self_k) / (
                    n_current + 1
                ) ** 2
                delta_gd = current_mean_mk - new_mean_mk  # positive = improvement

                # Build reasons
                reasons = []
                m_mk = working_mk.get(male.id, 0.0)
                f_mk = working_mk.get(female.id, 0.0)
                reasons.append(f"Sire MK={m_mk:.4f}, Dam MK={f_mk:.4f}")
                if expected_f == 0.0:
                    reasons.append("Parents are unrelated")
                elif expected_f <= 0.03125:
                    reasons.append("Low offspring inbreeding")

                msi = _calculate_msi(expected_f, delta_gd, mean_f)

                best_pair = BreedingRecommendation(
                    sire_id=male.id,
                    dam_id=female.id,
                    expected_f=round(expected_f, 6),
                    delta_gd=round(delta_gd, 6),
                    mate_suitability_index=msi,
                    reasons=reasons,
                )
                break  # Found a valid female for this male

            if best_pair is not None:
                break

        if best_pair is None:
            break  # No more valid pairs

        recommendations.append(best_pair)
        male_usage[best_pair.sire_id] = male_usage.get(best_pair.sire_id, 0) + 1
        female_usage[best_pair.dam_id] = female_usage.get(best_pair.dam_id, 0) + 1

        # Dynamic MK: add hypothetical offspring to kinship matrix
        m_idx = current_id_to_idx[best_pair.sire_id]
        f_idx = current_id_to_idx[best_pair.dam_id]

        # Offspring kinship with each existing individual
        n = K.shape[0]
        offspring_row = 0.5 * (K[m_idx, :] + K[f_idx, :])
        # Offspring self-kinship = 0.5 * (1 + F_offspring)
        offspring_self = 0.5 * (1.0 + K[m_idx, f_idx])

        # Extend kinship matrix
        K = np.pad(K, ((0, 1), (0, 1)), "constant")
        K[n, :n] = offspring_row
        K[:n, n] = offspring_row
        K[n, n] = offspring_self

        offspring_id = f"_offspring_{len(recommendations)}"
        current_ids.append(offspring_id)
        current_id_to_idx[offspring_id] = n

        # Recalculate MK over full current population (active + hypothetical offspring)
        # per Dynamic MK Selection (Ivy & Lacy 2012) / PMx behavior
        for ind in active:
            idx = current_id_to_idx[ind.id]
            working_mk[ind.id] = float(np.mean(K[idx, :]))

        current_mean_mk = float(np.mean(K)) if K.size > 0 else 0.0

    # Sort by MSI (best first)
    recommendations.sort(key=lambda r: r.mate_suitability_index)

    return recommendations
