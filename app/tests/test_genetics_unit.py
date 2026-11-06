"""
Unit tests for genetics module with known pedigree examples.

These tests verify the correctness of inbreeding and kinship calculations
using well-documented examples from population genetics literature.

No external dependencies (R-API, database) are required.
"""

import os
import sys
from dataclasses import dataclass, replace
from datetime import date

import numpy as np
import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.genetics import (
    BreedingRecommendation,
    GeneticPriority,
    Individual,
    _calculate_inbreeding_henderson,
    calculate_allele_retention,
    calculate_average_founder_contributions,
    calculate_effective_population_size,
    calculate_founder_contributions,
    calculate_founder_equivalents,
    calculate_founder_genome_contributions,
    calculate_founder_genome_equivalents,
    calculate_founder_statistics,
    calculate_gene_diversity,
    calculate_gene_drop_statistics,
    calculate_generation_numbers,
    calculate_genetic_priorities,
    calculate_genome_uniqueness,
    calculate_inbreeding_henderson,
    calculate_inbreeding_rate,
    calculate_kinship_matrix,
    calculate_mean_kinship,
    calculate_offspring_inbreeding,
    calculate_offspring_inbreeding_fast,
    calculate_pedigree_completeness,
    calculate_population_metrics,
    gene_drop_simulation,
    identify_founders,
    suggest_breeding_pairs,
    topological_sort_pedigree,
)


class TestFounders:
    """Test cases for founder individuals (no known parents)."""

    def test_single_founder_inbreeding(self):
        """A single founder should have F=0."""
        individuals = [Individual("A", None, None)]
        F = calculate_inbreeding_henderson(individuals)
        assert F["A"] == 0.0

    def test_multiple_founders_inbreeding(self):
        """All founders should have F=0."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", None, None),
        ]
        F = calculate_inbreeding_henderson(individuals)
        assert all(F[ind.id] == 0.0 for ind in individuals)

    def test_founder_self_kinship(self):
        """Self-kinship for founder should be 0.5."""
        individuals = [Individual("A", None, None, is_active=True)]
        K, ids = calculate_kinship_matrix(individuals, active_only=True)
        assert abs(K[0, 0] - 0.5) < 1e-10

    def test_unrelated_founders_kinship(self):
        """Kinship between unrelated founders should be 0."""
        individuals = [
            Individual("A", None, None, is_active=True),
            Individual("B", None, None, is_active=True),
        ]
        K, ids = calculate_kinship_matrix(individuals, active_only=True)
        assert K[0, 1] == 0.0
        assert K[1, 0] == 0.0


class TestParentOffspring:
    """Test parent-offspring relationships."""

    def test_offspring_of_unrelated_founders(self):
        """Offspring of unrelated founders should have F=0."""
        individuals = [
            Individual("A", None, None),  # Founder father
            Individual("B", None, None),  # Founder mother
            Individual("C", "A", "B"),  # Their offspring
        ]
        F = calculate_inbreeding_henderson(individuals)
        assert F["A"] == 0.0
        assert F["B"] == 0.0
        assert F["C"] == 0.0

    def test_parent_offspring_kinship(self):
        """Kinship between parent and offspring should be 0.25."""
        individuals = [
            Individual("A", None, None, is_active=True),
            Individual("B", None, None, is_active=True),
            Individual("C", "A", "B", is_active=True),
        ]
        K, ids = calculate_kinship_matrix(individuals, active_only=True)
        id_to_idx = {id_: i for i, id_ in enumerate(ids)}

        # K[parent, offspring] = 0.25
        assert abs(K[id_to_idx["A"], id_to_idx["C"]] - 0.25) < 1e-10
        assert abs(K[id_to_idx["B"], id_to_idx["C"]] - 0.25) < 1e-10


class TestFullSiblings:
    """Test full sibling relationships (same parents)."""

    def test_full_siblings_kinship(self):
        """Kinship between full siblings should be 0.25."""
        individuals = [
            Individual("A", None, None, is_active=True),  # Father
            Individual("B", None, None, is_active=True),  # Mother
            Individual("C", "A", "B", is_active=True),  # First offspring
            Individual("D", "A", "B", is_active=True),  # Full sibling
        ]
        K, ids = calculate_kinship_matrix(individuals, active_only=True)
        id_to_idx = {id_: i for i, id_ in enumerate(ids)}

        # K[C, D] = 0.5 * (K[A, D] + K[B, D]) = 0.5 * (0.25 + 0.25) = 0.25
        assert abs(K[id_to_idx["C"], id_to_idx["D"]] - 0.25) < 1e-10

    def test_full_sibling_mating_inbreeding(self):
        """
        Offspring of full sibling mating should have F=0.25.

        Pedigree:
            A ─┬─ B
               │
           ┌───┴───┐
           C       D  (full siblings)
               │
               E      (offspring of C × D)
        """
        individuals = [
            Individual("A", None, None),  # Founder
            Individual("B", None, None),  # Founder
            Individual("C", "A", "B"),  # Full sibling 1
            Individual("D", "A", "B"),  # Full sibling 2
            Individual("E", "C", "D"),  # Offspring of full sibling mating
        ]
        F = calculate_inbreeding_henderson(individuals)

        assert F["A"] == 0.0
        assert F["B"] == 0.0
        assert F["C"] == 0.0
        assert F["D"] == 0.0
        assert abs(F["E"] - 0.25) < 1e-10


class TestHalfSiblings:
    """Test half sibling relationships (one shared parent)."""

    def test_half_siblings_kinship(self):
        """Kinship between half siblings should be 0.125."""
        individuals = [
            Individual("A", None, None, is_active=True),  # Shared parent
            Individual("B", None, None, is_active=True),  # Other parent 1
            Individual("C", None, None, is_active=True),  # Other parent 2
            Individual("D", "A", "B", is_active=True),  # Half sibling 1
            Individual("E", "A", "C", is_active=True),  # Half sibling 2
        ]
        K, ids = calculate_kinship_matrix(individuals, active_only=True)
        id_to_idx = {id_: i for i, id_ in enumerate(ids)}

        # K[D, E] = 0.5 * (K[A, E] + K[B, E]) = 0.5 * (0.25 + 0) = 0.125
        assert abs(K[id_to_idx["D"], id_to_idx["E"]] - 0.125) < 1e-10

    def test_half_sibling_mating_inbreeding(self):
        """Offspring of half sibling mating should have F=0.125."""
        individuals = [
            Individual("A", None, None),  # Shared parent (sire)
            Individual("B", None, None),  # Dam of D
            Individual("C", None, None),  # Dam of E
            Individual("D", "A", "B"),  # Half sibling 1 (male)
            Individual("E", "A", "C"),  # Half sibling 2 (female)
            Individual("F", "D", "E"),  # Offspring of half sibling mating
        ]
        F = calculate_inbreeding_henderson(individuals)

        assert abs(F["F"] - 0.125) < 1e-10


class TestCousinMating:
    """Test first cousin relationships."""

    def test_first_cousin_mating_inbreeding(self):
        """
        Offspring of first cousin mating should have F=0.0625.

        Pedigree:
            A ─┬─ B
               │
           ┌───┴───┐
           C       D
           │       │
        E ─┼       ┼─ F
           │       │
           G       H  (first cousins)
               │
               I      (offspring)
        """
        individuals = [
            Individual("A", None, None),  # Grandparent
            Individual("B", None, None),  # Grandparent
            Individual("C", "A", "B"),  # Parent of G
            Individual("D", "A", "B"),  # Parent of H
            Individual("E", None, None),  # Other parent of G
            Individual("F", None, None),  # Other parent of H
            Individual("G", "C", "E"),  # First cousin 1
            Individual("H", "D", "F"),  # First cousin 2
            Individual("I", "G", "H"),  # Offspring of first cousins
        ]
        F = calculate_inbreeding_henderson(individuals)

        # First cousin mating: F = 0.0625 (1/16)
        assert abs(F["I"] - 0.0625) < 1e-10


class TestOffspringInbreeding:
    """Test calculate_offspring_inbreeding (testbreed) function."""

    def test_unrelated_parents(self):
        """Offspring of unrelated parents should have F=0."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
        ]
        F = calculate_offspring_inbreeding(individuals, "A", "B")
        assert F == 0.0

    def test_full_sibling_mating_testbreed(self):
        """Testbreed for full sibling mating should return F=0.25."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
            Individual("D", "A", "B"),
        ]
        F = calculate_offspring_inbreeding(individuals, "C", "D")
        assert abs(F - 0.25) < 1e-10

    def test_half_sibling_mating_testbreed(self):
        """Testbreed for half sibling mating should return F=0.125."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", None, None),
            Individual("D", "A", "B"),
            Individual("E", "A", "C"),
        ]
        F = calculate_offspring_inbreeding(individuals, "D", "E")
        assert abs(F - 0.125) < 1e-10

    def test_testbreed_with_unregistered_parents(self):
        """
        Testbreed with unregistered parents using their pedigree info.

        Scenario: Two unregistered individuals X and Y whose parents
        are full siblings from the pedigree.
        """
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),  # Full sibling 1
            Individual("D", "A", "B"),  # Full sibling 2
        ]
        # Offspring of C×D would have F=0.25
        # If we mate two such offspring (X from C×D, Y from C×D),
        # their offspring would have even higher inbreeding
        F = calculate_offspring_inbreeding(
            individuals,
            sire_id="X",
            dam_id="Y",
            sire_parents=("C", "D"),
            dam_parents=("C", "D"),
        )
        # X and Y are full siblings with F=0.25 each
        # K[X, Y] should be > 0.25
        assert F > 0.25

    def test_offspring_inbreeding_fast_matches_slow(self):
        """calculate_offspring_inbreeding_fast must match calculate_offspring_inbreeding."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
            Individual("D", "A", "B"),
        ]
        expected = calculate_offspring_inbreeding(individuals, "C", "D")

        sorted_inds, id_to_idx = topological_sort_pedigree(individuals)
        n = len(sorted_inds)
        sire_arr = np.full(n, -1, dtype=np.int32)
        dam_arr = np.full(n, -1, dtype=np.int32)
        for i, ind in enumerate(sorted_inds):
            if ind.sire_id and ind.sire_id in id_to_idx:
                sire_arr[i] = id_to_idx[ind.sire_id]
            if ind.dam_id and ind.dam_id in id_to_idx:
                dam_arr[i] = id_to_idx[ind.dam_id]
        F = _calculate_inbreeding_henderson(n, sire_arr, dam_arr)
        kinship_cache = {(i, i): 0.5 * (1.0 + F[i]) for i in range(n)}

        result = calculate_offspring_inbreeding_fast(
            id_to_idx["C"], id_to_idx["D"], sire_arr, dam_arr, F, kinship_cache
        )
        assert abs(result - expected) < 1e-10
        assert abs(result - 0.25) < 1e-10

    def test_offspring_inbreeding_fast_with_virtual_parent(self):
        """Fast path with one virtual (unregistered) parent using grandparent indices."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
            Individual("D", "A", "B"),
        ]
        expected = calculate_offspring_inbreeding(individuals, sire_id="X", dam_id="C", sire_parents=("C", "D"))

        sorted_inds, id_to_idx = topological_sort_pedigree(individuals)
        n = len(sorted_inds)
        sire_arr = np.full(n, -1, dtype=np.int32)
        dam_arr = np.full(n, -1, dtype=np.int32)
        for i, ind in enumerate(sorted_inds):
            if ind.sire_id and ind.sire_id in id_to_idx:
                sire_arr[i] = id_to_idx[ind.sire_id]
            if ind.dam_id and ind.dam_id in id_to_idx:
                dam_arr[i] = id_to_idx[ind.dam_id]
        F = _calculate_inbreeding_henderson(n, sire_arr, dam_arr)
        kinship_cache = {(i, i): 0.5 * (1.0 + F[i]) for i in range(n)}

        # Compute F for virtual sire BEFORE extending arrays
        virtual_idx = n
        f_virtual = calculate_offspring_inbreeding_fast(
            id_to_idx["C"], id_to_idx["D"], sire_arr, dam_arr, F, kinship_cache
        )
        # Now extend arrays with virtual parent
        sire_ext = np.append(sire_arr, id_to_idx["C"])
        dam_ext = np.append(dam_arr, id_to_idx["D"])
        F_ext = np.append(F, f_virtual)
        kinship_cache[(virtual_idx, virtual_idx)] = 0.5 * (1.0 + f_virtual)

        result = calculate_offspring_inbreeding_fast(
            virtual_idx, id_to_idx["C"], sire_ext, dam_ext, F_ext, kinship_cache
        )
        assert abs(result - expected) < 1e-10

    def test_offspring_inbreeding_fast_both_virtual_parents(self):
        """Fast path with both parents virtual (unregistered)."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
            Individual("D", "A", "B"),
        ]
        expected = calculate_offspring_inbreeding(
            individuals,
            sire_id="X",
            dam_id="Y",
            sire_parents=("C", "D"),
            dam_parents=("C", "D"),
        )

        sorted_inds, id_to_idx = topological_sort_pedigree(individuals)
        n = len(sorted_inds)
        sire_arr = np.full(n, -1, dtype=np.int32)
        dam_arr = np.full(n, -1, dtype=np.int32)
        for i, ind in enumerate(sorted_inds):
            if ind.sire_id and ind.sire_id in id_to_idx:
                sire_arr[i] = id_to_idx[ind.sire_id]
            if ind.dam_id and ind.dam_id in id_to_idx:
                dam_arr[i] = id_to_idx[ind.dam_id]
        F = _calculate_inbreeding_henderson(n, sire_arr, dam_arr)
        kinship_cache = {(i, i): 0.5 * (1.0 + F[i]) for i in range(n)}

        # Virtual sire at index n — compute F before extending
        f_sire = calculate_offspring_inbreeding_fast(
            id_to_idx["C"], id_to_idx["D"], sire_arr, dam_arr, F, kinship_cache
        )
        sire_ext = np.append(sire_arr, id_to_idx["C"])
        dam_ext = np.append(dam_arr, id_to_idx["D"])
        F_ext = np.append(F, f_sire)
        kinship_cache[(n, n)] = 0.5 * (1.0 + f_sire)

        # Virtual dam at index n+1 — compute F before extending
        f_dam = calculate_offspring_inbreeding_fast(
            id_to_idx["C"], id_to_idx["D"], sire_ext, dam_ext, F_ext, kinship_cache
        )
        sire_ext = np.append(sire_ext, id_to_idx["C"])
        dam_ext = np.append(dam_ext, id_to_idx["D"])
        F_ext = np.append(F_ext, f_dam)
        kinship_cache[(n + 1, n + 1)] = 0.5 * (1.0 + f_dam)

        result = calculate_offspring_inbreeding_fast(n, n + 1, sire_ext, dam_ext, F_ext, kinship_cache)
        assert abs(result - expected) < 1e-10
        assert result > 0.25  # full siblings with inbred parents

    def test_offspring_inbreeding_fast_missing_grandparent(self):
        """Missing grandparent ID should be treated as -1 (founder)."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
        ]
        # Slow path: one grandparent is "MISSING" (not in pedigree)
        expected = calculate_offspring_inbreeding(individuals, sire_id="X", dam_id="C", sire_parents=("A", "MISSING"))

        sorted_inds, id_to_idx = topological_sort_pedigree(individuals)
        n = len(sorted_inds)
        sire_arr = np.full(n, -1, dtype=np.int32)
        dam_arr = np.full(n, -1, dtype=np.int32)
        for i, ind in enumerate(sorted_inds):
            if ind.sire_id and ind.sire_id in id_to_idx:
                sire_arr[i] = id_to_idx[ind.sire_id]
            if ind.dam_id and ind.dam_id in id_to_idx:
                dam_arr[i] = id_to_idx[ind.dam_id]
        F = _calculate_inbreeding_henderson(n, sire_arr, dam_arr)
        kinship_cache = {(i, i): 0.5 * (1.0 + F[i]) for i in range(n)}

        # Virtual sire: one known grandparent, one missing (-1)
        gf_idx = id_to_idx.get("A", -1)
        gm_idx = id_to_idx.get("MISSING", -1)  # -1, not in pedigree
        sire_ext = np.append(sire_arr, np.int32(gf_idx))
        dam_ext = np.append(dam_arr, np.int32(gm_idx))
        # F for virtual sire = 0 (one parent unknown)
        f_virtual = 0.0
        F_ext = np.append(F, f_virtual)
        kinship_cache[(n, n)] = 0.5 * (1.0 + f_virtual)

        result = calculate_offspring_inbreeding_fast(n, id_to_idx["C"], sire_ext, dam_ext, F_ext, kinship_cache)
        assert abs(result - expected) < 1e-10


class TestMeanKinship:
    """Test mean kinship calculations."""

    def test_mean_kinship_founders(self):
        """Mean kinship for unrelated founders should be low."""
        individuals = [
            Individual("A", None, None, is_active=True),
            Individual("B", None, None, is_active=True),
            Individual("C", None, None, is_active=True),
        ]
        mk = calculate_mean_kinship(individuals, active_only=True)

        # For 3 unrelated founders:
        # MK[A] = (K[A,A] + K[A,B] + K[A,C]) / 3 = (0.5 + 0 + 0) / 3 = 0.1667
        assert abs(mk["A"] - 1 / 6) < 1e-10
        assert abs(mk["B"] - 1 / 6) < 1e-10
        assert abs(mk["C"] - 1 / 6) < 1e-10

    def test_mean_kinship_related_population(self):
        """Mean kinship increases with related individuals."""
        individuals = [
            Individual("A", None, None, is_active=True),
            Individual("B", None, None, is_active=True),
            Individual("C", "A", "B", is_active=True),
        ]
        mk = calculate_mean_kinship(individuals, active_only=True)

        # C is related to both A and B, so C should have higher MK
        assert mk["C"] > mk["A"]
        assert mk["C"] > mk["B"]


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_pedigree(self):
        """Empty pedigree should return empty results."""
        F = calculate_inbreeding_henderson([])
        assert F == {}

    def test_unknown_sire(self):
        """Offspring with unknown sire should have F=0."""
        individuals = [
            Individual("A", None, None),  # Mother
            Individual("B", None, "A"),  # Offspring with unknown sire
        ]
        F = calculate_inbreeding_henderson(individuals)
        assert F["B"] == 0.0

    def test_unknown_dam(self):
        """Offspring with unknown dam should have F=0."""
        individuals = [
            Individual("A", None, None),  # Father
            Individual("B", "A", None),  # Offspring with unknown dam
        ]
        F = calculate_inbreeding_henderson(individuals)
        assert F["B"] == 0.0

    def test_deep_pedigree(self):
        """Test with multiple generations (10 generations)."""
        individuals = [
            Individual("F0-M", None, None),
            Individual("F0-F", None, None),
        ]

        # Build 10 generations of single line descent
        for gen in range(1, 11):
            prev_male = f"F{gen - 1}-M" if gen > 1 else "F0-M"
            prev_female = f"F{gen - 1}-F" if gen > 1 else "F0-F"
            individuals.append(Individual(f"F{gen}-M", prev_male, prev_female))
            individuals.append(Individual(f"F{gen}-F", prev_male, prev_female))

        F = calculate_inbreeding_henderson(individuals)

        # With continued full sibling mating, inbreeding should increase
        assert F["F10-M"] > F["F5-M"] > F["F1-M"]

    def test_topological_sort_handles_unsorted_input(self):
        """Topological sort should handle individuals in any order."""
        # Deliberately out of order
        individuals = [
            Individual("C", "A", "B"),  # Offspring first
            Individual("A", None, None),
            Individual("B", None, None),
        ]
        sorted_inds, _ = topological_sort_pedigree(individuals)

        # Parents should come before offspring
        ids = [ind.id for ind in sorted_inds]
        assert ids.index("A") < ids.index("C")
        assert ids.index("B") < ids.index("C")


def _recursive_topological_order(individuals):
    """The original recursive sort, kept as the reference order for valid pedigrees."""
    lookup = {ind.id: ind for ind in individuals}
    placed, order = set(), []

    def place(ind_id):
        if ind_id in placed or ind_id not in lookup:
            return
        ind = lookup[ind_id]
        if ind.sire_id and ind.sire_id in lookup:
            place(ind.sire_id)
        if ind.dam_id and ind.dam_id in lookup:
            place(ind.dam_id)
        placed.add(ind_id)
        order.append(ind_id)

    for ind in individuals:
        place(ind.id)
    return order


class TestPedigreeCycles:
    """Cycles and very deep chains must not break the whole genebank's F/MK."""

    UNAFFECTED = [
        Individual("P", None, None, is_active=True),
        Individual("Q", None, None, is_active=True),
        Individual("S1", "P", "Q", is_active=True),
        Individual("S2", "P", "Q", is_active=True),
        Individual("I", "S1", "S2", is_active=True),  # full-sib mating, F = 0.25
    ]

    def test_order_unchanged_for_valid_pedigrees(self):
        """Same order (and same objects) as the recursive sort on random pedigrees."""
        rng = np.random.default_rng(7)
        for _ in range(20):
            individuals = []
            for i in range(300):
                parents = []
                for _side in range(2):
                    roll = rng.random()
                    if i == 0 or roll < 0.2:
                        parents.append(None)
                    elif roll < 0.25:
                        parents.append(f"missing-{i}")  # dangling parent id
                    else:
                        parents.append(f"I{rng.integers(0, i)}")
                individuals.append(Individual(f"I{i}", parents[0], parents[1]))
            rng.shuffle(individuals)

            sorted_inds, id_to_idx = topological_sort_pedigree(individuals)

            assert [ind.id for ind in sorted_inds] == _recursive_topological_order(individuals)
            originals = {ind.id: ind for ind in individuals}
            assert all(ind is originals[ind.id] for ind in sorted_inds)
            assert id_to_idx == {ind.id: i for i, ind in enumerate(sorted_inds)}

    def _assert_computes(self, cyclic):
        individuals = cyclic + [replace(ind) for ind in self.UNAFFECTED]
        F = calculate_inbreeding_henderson(individuals)
        mk = calculate_mean_kinship(individuals)

        assert set(F) == {ind.id for ind in individuals}
        assert F["I"] == 0.25
        assert all(F[ind.id] == 0.0 for ind in cyclic)
        assert set(mk) == {ind.id for ind in individuals}
        return F

    def test_self_parent(self, caplog):
        """An animal recorded as its own parent: that parent link is dropped and logged."""
        with caplog.at_level("WARNING", logger="herdbook.genetics"):
            self._assert_computes([Individual("X", "X", None, is_active=True)])

        assert "X" in caplog.text

    def test_two_cycle(self):
        self._assert_computes([Individual("A", "B", None, is_active=True), Individual("B", "A", None, is_active=True)])

    def test_three_cycle(self):
        sorted_inds, _ = topological_sort_pedigree(
            [
                Individual("A", "C", None, is_active=True),
                Individual("B", "A", None, is_active=True),
                Individual("C", "B", None, is_active=True),
            ]
        )
        ids = [ind.id for ind in sorted_inds]
        # Every remaining parent link points backwards in the order
        for ind in sorted_inds:
            if ind.sire_id:
                assert ids.index(ind.sire_id) < ids.index(ind.id)
        self._assert_computes(
            [
                Individual("A", "C", None, is_active=True),
                Individual("B", "A", None, is_active=True),
                Individual("C", "B", None, is_active=True),
            ]
        )

    def test_input_is_not_mutated(self):
        """The cached pedigree passed in keeps its parent ids."""
        cyclic = Individual("X", "X", None)
        topological_sort_pedigree([cyclic])
        assert cyclic.sire_id == "X"

    def test_deep_chain(self):
        """A 1500-generation chain (beyond Python's recursion limit) sorts and computes."""
        individuals = [Individual("C0", None, None, is_active=False)]
        for i in range(1, 1500):
            individuals.append(Individual(f"C{i}", f"C{i - 1}", None, is_active=i >= 1495))
        individuals.reverse()

        sorted_inds, _ = topological_sort_pedigree(individuals)
        F = calculate_inbreeding_henderson(individuals)
        mk = calculate_mean_kinship(individuals)

        assert [ind.id for ind in sorted_inds] == [f"C{i}" for i in range(1500)]
        assert len(F) == 1500
        assert set(mk) == {f"C{i}" for i in range(1495, 1500)}


class TestNumericalPrecision:
    """Test numerical precision at extreme values."""

    def test_high_inbreeding(self):
        """Test with very high inbreeding (repeated full sibling mating)."""
        # Start with founders
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
        ]

        # 5 generations of full sibling mating
        prev_m, prev_f = "A", "B"
        for gen in range(1, 6):
            m_id = f"M{gen}"
            f_id = f"F{gen}"
            individuals.append(Individual(m_id, prev_m, prev_f))
            individuals.append(Individual(f_id, prev_m, prev_f))
            prev_m, prev_f = m_id, f_id

        F = calculate_inbreeding_henderson(individuals)

        # After 5 generations of full sibling mating, F should be high
        # but still < 1.0
        assert 0 < F["M5"] < 1.0
        assert 0 < F["F5"] < 1.0
        # F should be increasing each generation
        assert F["M5"] > F["M4"] > F["M3"] > F["M2"] > F["M1"]


class TestKinshipMatrixKeyAccess:
    """
    Test safe access patterns for kinship matrix.

    These tests verify the pattern used in the testbreed endpoint to safely
    access kinship values without raising KeyError when individuals are missing.
    """

    def test_both_individuals_exist(self):
        """When both individuals exist, kinship value should be returned."""
        individuals = [
            Individual("A", None, None, is_active=True),
            Individual("B", None, None, is_active=True),
        ]
        kinship_matrix = _build_kinship_dict(individuals)

        male_id, female_id = "A", "B"
        # This is the pattern used in herdbook.py testbreed endpoint
        if male_id in kinship_matrix and female_id in kinship_matrix.get(male_id, {}):
            result = kinship_matrix[male_id][female_id]
            assert result == 0.0  # Unrelated founders have kinship 0

    def test_male_missing_from_matrix(self):
        """When male is missing, should not raise KeyError."""
        individuals = [
            Individual("A", None, None, is_active=True),
        ]
        kinship_matrix = _build_kinship_dict(individuals)

        male_id, female_id = "MISSING", "A"
        # Should return False without raising KeyError
        found = male_id in kinship_matrix and female_id in kinship_matrix.get(male_id, {})
        assert found is False

    def test_female_missing_from_matrix(self):
        """When female is missing, should not raise KeyError."""
        individuals = [
            Individual("A", None, None, is_active=True),
        ]
        kinship_matrix = _build_kinship_dict(individuals)

        male_id, female_id = "A", "MISSING"
        # Should return False without raising KeyError
        found = male_id in kinship_matrix and female_id in kinship_matrix.get(male_id, {})
        assert found is False

    def test_both_missing_from_matrix(self):
        """When both are missing, should not raise KeyError."""
        individuals = [
            Individual("A", None, None, is_active=True),
        ]
        kinship_matrix = _build_kinship_dict(individuals)

        male_id, female_id = "MISSING1", "MISSING2"
        found = male_id in kinship_matrix and female_id in kinship_matrix.get(male_id, {})
        assert found is False

    def test_empty_matrix(self):
        """Empty kinship matrix should not raise KeyError."""
        kinship_matrix = {}

        male_id, female_id = "A", "B"
        found = male_id in kinship_matrix and female_id in kinship_matrix.get(male_id, {})
        assert found is False

    def test_siblings_in_matrix(self):
        """Full siblings should have kinship 0.25."""
        individuals = [
            Individual("A", None, None, is_active=True),
            Individual("B", None, None, is_active=True),
            Individual("C", "A", "B", is_active=True),
            Individual("D", "A", "B", is_active=True),
        ]
        kinship_matrix = _build_kinship_dict(individuals)

        male_id, female_id = "C", "D"
        if male_id in kinship_matrix and female_id in kinship_matrix.get(male_id, {}):
            result = kinship_matrix[male_id][female_id]
            assert abs(result - 0.25) < 1e-10


def _build_kinship_dict(individuals):
    """
    Helper to build kinship dictionary in the format returned by get_kinship().

    Returns: {individual_i: {individual_j: kinship_value}}
    """
    K, ids = calculate_kinship_matrix(individuals, active_only=True)
    result = {}
    for i, id_i in enumerate(ids):
        result[id_i] = {}
        for j, id_j in enumerate(ids):
            result[id_i][id_j] = K[i, j]
    return result


class TestLacy1989Reference:
    """
    Test against Lacy 1989 reference pedigree verified with optiSel R package.

    This pedigree is a classic test case from:
    Lacy, R.C. (1989). Analysis of founder representation in pedigrees:
    Founder equivalents and founder genome equivalents. Zoo Biology, 8(2), 111-123.

    Reference values calculated with optiSel R package and saved in
    tests/reference_data/lacy1989_reference.json
    """

    @pytest.fixture
    def lacy_pedigree(self):
        """Create the Lacy 1989 pedigree."""
        return [
            Individual("A", None, None, is_active=True),  # Founder
            Individual("B", None, None, is_active=True),  # Founder
            Individual("C", "A", "B", is_active=True),  # Full sibling 1
            Individual("D", "A", "B", is_active=True),  # Full sibling 2
            Individual("E", None, None, is_active=True),  # Founder (unrelated)
            Individual("F", "D", "E", is_active=True),  # Offspring of D×E
            Individual("G", "D", "E", is_active=True),  # Offspring of D×E
        ]

    @pytest.fixture
    def expected_kinship(self):
        """Reference kinship matrix from optiSel."""
        # From lacy1989_reference.json (order: A, B, C, D, E, F, G)
        return np.array(
            [
                [0.500, 0.000, 0.250, 0.250, 0.000, 0.125, 0.125],
                [0.000, 0.500, 0.250, 0.250, 0.000, 0.125, 0.125],
                [0.250, 0.250, 0.500, 0.250, 0.000, 0.125, 0.125],
                [0.250, 0.250, 0.250, 0.500, 0.000, 0.250, 0.250],
                [0.000, 0.000, 0.000, 0.000, 0.500, 0.250, 0.250],
                [0.125, 0.125, 0.125, 0.250, 0.250, 0.500, 0.250],
                [0.125, 0.125, 0.125, 0.250, 0.250, 0.250, 0.500],
            ]
        )

    def test_kinship_matrix_matches_optisel(self, lacy_pedigree, expected_kinship):
        """Kinship matrix should match optiSel reference values."""
        K, ids = calculate_kinship_matrix(lacy_pedigree, active_only=True)

        # Verify order matches expected
        expected_order = ["A", "B", "C", "D", "E", "F", "G"]
        id_to_idx = {id_: i for i, id_ in enumerate(ids)}

        # Compare each element
        for i, id_i in enumerate(expected_order):
            for j, id_j in enumerate(expected_order):
                python_idx_i = id_to_idx[id_i]
                python_idx_j = id_to_idx[id_j]
                python_val = K[python_idx_i, python_idx_j]
                expected_val = expected_kinship[i, j]
                assert abs(python_val - expected_val) < 1e-10, (
                    f"K[{id_i},{id_j}]: Python={python_val}, optiSel={expected_val}"
                )

    def test_all_inbreeding_zero(self, lacy_pedigree):
        """
        In this pedigree, no individual is inbred because:
        - A, B, E are founders (F=0 by definition)
        - C, D have unrelated founders as parents (F=0)
        - F, G have D and E as parents, where E is unrelated to D (F=0)
        """
        F = calculate_inbreeding_henderson(lacy_pedigree)

        for ind_id in ["A", "B", "C", "D", "E", "F", "G"]:
            assert F[ind_id] == 0.0, f"F[{ind_id}] should be 0, got {F[ind_id]}"

    def test_full_sibling_kinship(self, lacy_pedigree):
        """C and D are full siblings, kinship should be 0.25."""
        K, ids = calculate_kinship_matrix(lacy_pedigree, active_only=True)
        id_to_idx = {id_: i for i, id_ in enumerate(ids)}

        assert abs(K[id_to_idx["C"], id_to_idx["D"]] - 0.25) < 1e-10

    def test_fg_are_full_siblings(self, lacy_pedigree):
        """F and G are full siblings (both D×E), kinship should be 0.25."""
        K, ids = calculate_kinship_matrix(lacy_pedigree, active_only=True)
        id_to_idx = {id_: i for i, id_ in enumerate(ids)}

        assert abs(K[id_to_idx["F"], id_to_idx["G"]] - 0.25) < 1e-10

    def test_self_kinship_is_half(self, lacy_pedigree):
        """Self-kinship for non-inbred individuals should be 0.5."""
        K, ids = calculate_kinship_matrix(lacy_pedigree, active_only=True)

        for i in range(len(ids)):
            assert abs(K[i, i] - 0.5) < 1e-10, f"K[{ids[i]},{ids[i]}] should be 0.5"

    def test_parent_offspring_kinship(self, lacy_pedigree):
        """Parent-offspring kinship should be 0.25."""
        K, ids = calculate_kinship_matrix(lacy_pedigree, active_only=True)
        id_to_idx = {id_: i for i, id_ in enumerate(ids)}

        # A-C, A-D, B-C, B-D should all be 0.25
        for parent, child in [
            ("A", "C"),
            ("A", "D"),
            ("B", "C"),
            ("B", "D"),
            ("D", "F"),
            ("D", "G"),
            ("E", "F"),
            ("E", "G"),
        ]:
            assert abs(K[id_to_idx[parent], id_to_idx[child]] - 0.25) < 1e-10, f"K[{parent},{child}] should be 0.25"

    def test_grandparent_grandchild_kinship(self, lacy_pedigree):
        """Grandparent-grandchild kinship should be 0.125."""
        K, ids = calculate_kinship_matrix(lacy_pedigree, active_only=True)
        id_to_idx = {id_: i for i, id_ in enumerate(ids)}

        # A and B are grandparents of F and G (through D)
        for grandparent in ["A", "B"]:
            for grandchild in ["F", "G"]:
                assert abs(K[id_to_idx[grandparent], id_to_idx[grandchild]] - 0.125) < 1e-10, (
                    f"K[{grandparent},{grandchild}] should be 0.125"
                )

    def test_unrelated_kinship_zero(self, lacy_pedigree):
        """Kinship between unrelated individuals should be 0."""
        K, ids = calculate_kinship_matrix(lacy_pedigree, active_only=True)
        id_to_idx = {id_: i for i, id_ in enumerate(ids)}

        # E is unrelated to A, B, C
        for unrelated in ["A", "B", "C"]:
            assert K[id_to_idx["E"], id_to_idx[unrelated]] == 0.0, f"K[E,{unrelated}] should be 0"


class TestLacy1989Extended:
    """
    Extended Lacy 1989 pedigree with inbred offspring.

    Adding individual H (offspring of F×G) to test inbreeding calculation.
    F and G are full siblings (kinship=0.25), so H should have F=0.25.
    """

    def test_sibling_mating_produces_inbreeding(self):
        """Offspring of F×G (full siblings) should have F=0.25."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
            Individual("D", "A", "B"),
            Individual("E", None, None),
            Individual("F", "D", "E"),
            Individual("G", "D", "E"),
            Individual("H", "F", "G"),  # Extended: offspring of F×G
        ]
        F = calculate_inbreeding_henderson(individuals)

        # H's inbreeding = kinship of F and G = 0.25
        assert abs(F["H"] - 0.25) < 1e-10

    def test_offspring_inbreeding_for_fg(self):
        """Using testbreed function: offspring of F×G should have F=0.25."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
            Individual("D", "A", "B"),
            Individual("E", None, None),
            Individual("F", "D", "E"),
            Individual("G", "D", "E"),
        ]
        F = calculate_offspring_inbreeding(individuals, "F", "G")
        assert abs(F - 0.25) < 1e-10


# =============================================================================
# Founder Analysis Tests
# =============================================================================


class TestFounderIdentification:
    """Test identification of founders in a pedigree."""

    def test_identify_founders_simple(self):
        """Founders are individuals with no known parents."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
        ]
        founders = identify_founders(individuals)
        assert set(founders) == {"A", "B"}

    def test_identify_founders_lacy1989(self):
        """Lacy 1989 pedigree has 3 founders: A, B, E."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
            Individual("D", "A", "B"),
            Individual("E", None, None),
            Individual("F", "D", "E"),
            Individual("G", "D", "E"),
        ]
        founders = identify_founders(individuals)
        assert set(founders) == {"A", "B", "E"}

    def test_identify_founders_all_founders(self):
        """When all individuals are founders."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", None, None),
        ]
        founders = identify_founders(individuals)
        assert set(founders) == {"A", "B", "C"}

    def test_identify_founders_empty(self):
        """Empty pedigree has no founders."""
        assert identify_founders([]) == []

    def test_parents_outside_the_pedigree_make_a_founder(self):
        """Recorded parents that are not loaded are unknown, as in kinship and gene drop."""
        individuals = [
            Individual("A", None, None),
            Individual("X", "M-1", "M-2"),  # both parents outside the loaded rows
            Individual("Y", "X", "M-3"),  # one parent loaded: not a founder
        ]
        assert set(identify_founders(individuals)) == {"A", "X"}


class TestFounderContributions:
    """Test calculation of founder contributions."""

    def test_founder_contributes_to_self(self):
        """A founder contributes 100% to themselves."""
        individuals = [
            Individual("A", None, None),
        ]
        contrib, founders = calculate_founder_contributions(individuals)
        assert contrib["A"]["A"] == 1.0
        assert founders == ["A"]

    def test_offspring_contributions(self):
        """Offspring gets 50% from each parent (if both are founders)."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
        ]
        contrib, founders = calculate_founder_contributions(individuals)

        # C gets 0.5 from A and 0.5 from B
        assert abs(contrib["C"]["A"] - 0.5) < 1e-10
        assert abs(contrib["C"]["B"] - 0.5) < 1e-10

    def test_lacy1989_founder_contributions(self):
        """
        Test Lacy 1989 founder contributions (verified against optiSel R package).

        Pedigree:
            A ─┬─ B        E
               │           │
           ┌───┴───┐       │
           C       D ──────┤
                           │
                       ┌───┴───┐
                       F       G

        Expected contributions to F and G:
        - A: 0.25 (through D)
        - B: 0.25 (through D)
        - E: 0.50 (direct parent)
        """
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
            Individual("D", "A", "B"),
            Individual("E", None, None),
            Individual("F", "D", "E"),
            Individual("G", "D", "E"),
        ]
        contrib, founders = calculate_founder_contributions(individuals)

        # Check F's contributions
        assert abs(contrib["F"]["A"] - 0.25) < 1e-10
        assert abs(contrib["F"]["B"] - 0.25) < 1e-10
        assert abs(contrib["F"]["E"] - 0.50) < 1e-10

        # Check G's contributions (same as F)
        assert abs(contrib["G"]["A"] - 0.25) < 1e-10
        assert abs(contrib["G"]["B"] - 0.25) < 1e-10
        assert abs(contrib["G"]["E"] - 0.50) < 1e-10

        # Check D's contributions
        assert abs(contrib["D"]["A"] - 0.50) < 1e-10
        assert abs(contrib["D"]["B"] - 0.50) < 1e-10
        assert "E" not in contrib["D"]  # D is not related to E

    def test_contributions_sum_to_one(self):
        """Total founder contributions for any individual should sum to 1.0."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
            Individual("D", "A", "B"),
            Individual("E", None, None),
            Individual("F", "D", "E"),
            Individual("G", "D", "E"),
        ]
        contrib, _ = calculate_founder_contributions(individuals)

        for ind_id, ind_contrib in contrib.items():
            total = sum(ind_contrib.values())
            assert abs(total - 1.0) < 1e-10, f"Individual {ind_id}: contributions sum to {total}, expected 1.0"


class TestAverageFounderContributions:
    """Test calculation of average founder contributions to a population."""

    def test_lacy1989_average_contributions(self):
        """
        Average contributions to population {F, G} in Lacy 1989.

        Both F and G have identical contributions:
        - A: 0.25
        - B: 0.25
        - E: 0.50

        So average is the same.
        """
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", None, None, is_active=False),
            Individual("C", "A", "B", is_active=False),
            Individual("D", "A", "B", is_active=False),
            Individual("E", None, None, is_active=False),
            Individual("F", "D", "E", is_active=True),  # Population member
            Individual("G", "D", "E", is_active=True),  # Population member
        ]

        avg_contrib, founders = calculate_average_founder_contributions(individuals)

        assert abs(avg_contrib["A"] - 0.25) < 1e-10
        assert abs(avg_contrib["B"] - 0.25) < 1e-10
        assert abs(avg_contrib["E"] - 0.50) < 1e-10


class TestFounderEquivalents:
    """Test Founder Equivalents (FE) calculation."""

    def test_lacy1989_founder_equivalents(self):
        """
        FE for Lacy 1989 pedigree with population {F, G}.

        FE = 1 / Σ(pᵢ²)
           = 1 / (0.25² + 0.25² + 0.50²)
           = 1 / (0.0625 + 0.0625 + 0.25)
           = 1 / 0.375
           = 2.6667

        Verified against optiSel R package.
        """
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", None, None, is_active=False),
            Individual("C", "A", "B", is_active=False),
            Individual("D", "A", "B", is_active=False),
            Individual("E", None, None, is_active=False),
            Individual("F", "D", "E", is_active=True),
            Individual("G", "D", "E", is_active=True),
        ]

        fe = calculate_founder_equivalents(individuals)

        # Expected: 2.6667 (from R optiSel)
        assert abs(fe - 2.6667) < 0.001

    def test_equal_contributions_fe_equals_n(self):
        """If all founders contribute equally, FE = n_founders."""
        individuals = [
            Individual("A", None, None, is_active=True),
            Individual("B", None, None, is_active=True),
            Individual("C", None, None, is_active=True),
        ]

        fe = calculate_founder_equivalents(individuals)

        # Each founder contributes 1/3, so FE = 1 / (3 * (1/3)²) = 1 / (3 * 1/9) = 3
        assert abs(fe - 3.0) < 1e-10

    def test_single_founder_fe_equals_one(self):
        """If population derives 100% from one founder, FE = 1."""
        # Create a pedigree where all genes trace back to founder A
        # A is the only founder, B and C are full siblings from A×A (self-mating)
        # Note: In practice self-mating doesn't occur, but this tests the math
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", "A", "A", is_active=True),  # 100% from A
            Individual("C", "A", "A", is_active=True),  # 100% from A
        ]

        fe = calculate_founder_equivalents(individuals)

        # Both B and C derive 100% from A, so FE = 1
        assert abs(fe - 1.0) < 1e-10

    def test_partial_unknown_ancestry(self):
        """When individuals have unknown parents, their known founder contribution < 1."""
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", "A", None, is_active=True),  # Only sire known: 0.5 from A
            Individual("C", "A", None, is_active=True),  # Only sire known: 0.5 from A
        ]

        avg_contrib, _ = calculate_average_founder_contributions(individuals)

        # Each individual gets only 0.5 from known founder A
        # (the other 0.5 is from unknown ancestry)
        assert abs(avg_contrib["A"] - 0.5) < 1e-10

    def test_unknown_parent_is_a_founder_of_its_own(self):
        """A x unknown dam -> X has two unrelated gamete sources, so FE = 2 (was 4)."""
        inds = [Individual("A", None, None, is_active=False), Individual("X", "A", None, is_active=True)]
        fe = calculate_founder_equivalents(inds)
        assert fe == pytest.approx(2.0), f"FE for one offspring of a founder and an unknown dam = {fe}"

    def test_each_unknown_parent_slot_is_a_separate_founder(self):
        """B and C each have their own unknown dam: shares A 1/2, two phantoms 1/4 each -> FE = 8/3."""
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", "A", None, is_active=True),
            Individual("C", "A", None, is_active=True),
        ]
        assert calculate_founder_equivalents(individuals) == pytest.approx(8 / 3)


class TestFounderStatistics:
    """Test comprehensive founder statistics."""

    def test_lacy1989_statistics(self):
        """Full founder statistics for Lacy 1989."""
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", None, None, is_active=False),
            Individual("C", "A", "B", is_active=False),
            Individual("D", "A", "B", is_active=False),
            Individual("E", None, None, is_active=False),
            Individual("F", "D", "E", is_active=True),
            Individual("G", "D", "E", is_active=True),
        ]

        stats = calculate_founder_statistics(individuals)

        assert stats["n_founders"] == 3
        assert abs(stats["founder_equivalents"] - 2.6667) < 0.001
        assert stats["population_size"] == 2

        # Proportional loss of gene diversity = 1 - GD = mean kinship incl. self
        # over {F, G}: (0.5 + 0.5 + 2 * 0.25) / 4 = 0.375
        assert abs(stats["proportional_loss"] - 0.375) < 1e-9

        # Top founder should be E with 0.50 contribution
        top_founder_id, top_contribution = stats["top_founders"][0]
        assert top_founder_id == "E"
        assert abs(top_contribution - 0.50) < 1e-10

    def test_n_founders_total_independent_of_reference(self):
        """An empty reference population still reports the pedigree's founders."""
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", None, None, is_active=False),
            Individual("C", "A", "B", is_active=False),
        ]

        stats = calculate_founder_statistics(individuals)

        assert stats["n_founders"] == 0
        assert stats["n_founders_total"] == 2

    def test_n_founders_total_uses_the_cycle_repaired_pedigree(self):
        """An animal recorded as its own sire becomes a founder in both counts."""
        stats = calculate_founder_statistics([Individual("X", "X", None, is_active=True)])

        assert stats["n_founders"] == 1
        assert stats["n_founders_total"] == 1

    def test_proportional_loss_uses_supplied_mean_kinship(self):
        """Supplied (cached) MK values are averaged instead of recomputed."""
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", None, None, is_active=False),
            Individual("C", "A", "B", is_active=True),
        ]

        stats = calculate_founder_statistics(individuals, mean_kinship={"C": 0.2, "X": 0.4})

        assert abs(stats["proportional_loss"] - 0.3) < 1e-12

    def test_fe_not_above_founder_count_with_unloaded_parents(self):
        """X's recorded parents are not loaded, so X is a founder line (as for kinship and gene drop)."""
        inds = [
            Individual("A", None, None, is_active=False),
            Individual("X", "M-1", "M-2", is_active=False),
            Individual("Y", "X", "A", is_active=True),
            Individual("Z", "X", "A", is_active=True),
        ]
        s = calculate_founder_statistics(inds, mean_kinship={"Y": 0.375, "Z": 0.375})
        # The dashboard renders "{founder_equivalents} av {n_founders} founders".
        assert s["founder_equivalents"] <= s["n_founders"], (
            f"FE {s['founder_equivalents']} > n_founders {s['n_founders']} (n_founders_total {s['n_founders_total']})"
        )
        assert (s["founder_equivalents"], s["n_founders"], s["n_founders_total"]) == (pytest.approx(2.0), 2, 2)

    def test_unknown_parent_counts_in_the_founder_numbers(self):
        """The phantom dam of X is a founder in FE, n_founders and n_founders_total alike."""
        inds = [Individual("A", None, None, is_active=False), Individual("X", "A", None, is_active=True)]
        s = calculate_founder_statistics(inds, mean_kinship={"X": 0.5})
        assert (s["founder_equivalents"], s["n_founders"], s["n_founders_total"]) == (pytest.approx(2.0), 2, 2)
        assert dict(s["top_founders"]) == {"A": 0.5}  # phantoms have no id to list

    def test_every_output_counts_founders_like_fe(self):
        """Gene drop and population metrics publish FE too, so their n_founders counts phantoms as well."""
        inds = [Individual("A", None, None, is_active=False), Individual("X", "A", None, is_active=True)]
        drop = calculate_gene_drop_statistics(inds, n_iterations=20, seed=1)
        metrics = calculate_population_metrics(inds)
        for name, out in (("gene drop", drop), ("population metrics", metrics)):
            assert (out["founder_equivalents"], out["n_founders"]) == (pytest.approx(2.0), 2), (name, out)
        # Without population members the pedigree's founder count is still reported the same way.
        nobody = [Individual("A", None, None, is_active=False), Individual("X", "A", None, is_active=False)]
        counts = [
            calculate_gene_drop_statistics(nobody, n_iterations=20, seed=1)["n_founders"],
            calculate_population_metrics(nobody)["n_founders"],
            calculate_founder_statistics(nobody, mean_kinship={})["n_founders_total"],
        ]
        assert counts == [2, 2, 2], counts

    def test_n_founders_counts_only_contributing_founders(self):
        """A founder line without descendants in the population is not counted."""
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", None, None, is_active=False),
            Individual("H", None, None, is_active=False),  # dead line
            Individual("C", "A", "B", is_active=True),
        ]

        stats = calculate_founder_statistics(individuals)

        assert stats["n_founders"] == 2
        assert stats["n_founders_total"] == 3
        # Single offspring of two founders: mean kinship incl. self = 0.5
        assert abs(stats["proportional_loss"] - 0.5) < 1e-9


# =============================================================================
# Gene Drop Simulation Tests
# =============================================================================


class TestGeneDropSimulation:
    """Test gene drop simulation."""

    @pytest.fixture
    def lacy_pedigree(self):
        """Lacy 1989 pedigree with population = {F, G}."""
        return [
            Individual("A", None, None, is_active=False),
            Individual("B", None, None, is_active=False),
            Individual("C", "A", "B", is_active=False),
            Individual("D", "A", "B", is_active=False),
            Individual("E", None, None, is_active=False),
            Individual("F", "D", "E", is_active=True),
            Individual("G", "D", "E", is_active=True),
        ]

    def test_gene_drop_returns_correct_shape(self, lacy_pedigree):
        """Gene drop should return matrix with correct dimensions."""
        n_iterations = 100
        alleles, pop_ids, founders = gene_drop_simulation(lacy_pedigree, n_iterations=n_iterations, seed=42)

        # Population has 2 individuals (F, G), each with 2 alleles = 4 rows
        assert alleles.shape == (4, n_iterations)
        assert len(pop_ids) == 2
        assert set(pop_ids) == {"F", "G"}
        assert set(founders) == {"A", "B", "E"}

    def test_gene_drop_deterministic_with_seed(self, lacy_pedigree):
        """Same seed should produce identical results."""
        alleles1, _, _ = gene_drop_simulation(lacy_pedigree, n_iterations=50, seed=42)
        alleles2, _, _ = gene_drop_simulation(lacy_pedigree, n_iterations=50, seed=42)

        np.testing.assert_array_equal(alleles1, alleles2)

    def test_gene_drop_does_not_touch_global_rng(self, lacy_pedigree):
        """A seeded simulation uses a local generator, not NumPy's global state."""
        np.random.seed(0)
        expected = np.random.random()
        np.random.seed(0)
        gene_drop_simulation(lacy_pedigree, n_iterations=20, seed=42)
        assert np.random.random() == expected

    def test_gene_drop_alleles_from_founders(self, lacy_pedigree):
        """All alleles should trace back to founders."""
        alleles, _, founders = gene_drop_simulation(lacy_pedigree, n_iterations=100, seed=42)

        # Valid allele IDs are 0 to 2*n_founders-1
        n_founders = len(founders)
        valid_alleles = set(range(n_founders * 2))

        # All alleles should be valid founder alleles
        unique_alleles = set(alleles.flatten())
        assert unique_alleles.issubset(valid_alleles | {-1})  # -1 for unknown

    def test_founder_only_population(self):
        """When population is founders, each has their own unique alleles."""
        individuals = [
            Individual("A", None, None, is_active=True),
            Individual("B", None, None, is_active=True),
        ]

        alleles, pop_ids, founders = gene_drop_simulation(individuals, n_iterations=10, seed=42)

        # A has alleles 0, 1; B has alleles 2, 3
        # Check that A's alleles are always 0 and 1
        a_idx = pop_ids.index("A")
        a_alleles = set(alleles[a_idx * 2 : a_idx * 2 + 2, :].flatten())
        assert a_alleles == {0, 1}


class TestFounderGenomeContributions:
    """Test founder genome contribution calculation from gene drop."""

    def test_contributions_sum_to_one(self):
        """Genome contributions should sum to approximately 1.0."""
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", None, None, is_active=False),
            Individual("C", "A", "B", is_active=True),
        ]

        alleles, _, founders = gene_drop_simulation(individuals, n_iterations=100, seed=42)
        contrib = calculate_founder_genome_contributions(alleles, founders)

        total = sum(contrib.values())
        assert abs(total - 1.0) < 0.01  # Allow some tolerance

    def test_lacy1989_genome_contributions(self):
        """
        Lacy 1989 genome contributions should be close to expected.

        Expected (from founder contributions):
        A: 0.25, B: 0.25, E: 0.50
        """
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", None, None, is_active=False),
            Individual("C", "A", "B", is_active=False),
            Individual("D", "A", "B", is_active=False),
            Individual("E", None, None, is_active=False),
            Individual("F", "D", "E", is_active=True),
            Individual("G", "D", "E", is_active=True),
        ]

        # Use many iterations for convergence
        alleles, _, founders = gene_drop_simulation(individuals, n_iterations=5000, seed=42)
        contrib = calculate_founder_genome_contributions(alleles, founders)

        # Should be close to expected values (within 5%)
        assert abs(contrib["A"] - 0.25) < 0.05
        assert abs(contrib["B"] - 0.25) < 0.05
        assert abs(contrib["E"] - 0.50) < 0.05


class TestFounderGenomeEquivalents:
    """Test Founder Genome Equivalents (FGE) calculation."""

    def test_fge_lacy1989_from_gene_diversity(self):
        """
        FGE = 1 / (2 * (1 - GD)) (Lacy 1989; Ballou & Lacy 1995), not 1/sum(p^2).

        Lacy 1989 with population {F, G}: mean kinship incl. self = 0.375,
        so GD = 0.625 and FGE = 4/3, while FE = 8/3. Averaged gene-drop
        contributions converge to FE, so the old formula returned ~2.67.
        """
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", None, None, is_active=False),
            Individual("C", "A", "B", is_active=False),
            Individual("D", "A", "B", is_active=False),
            Individual("E", None, None, is_active=False),
            Individual("F", "D", "E", is_active=True),
            Individual("G", "D", "E", is_active=True),
        ]

        fge = calculate_founder_genome_equivalents(individuals, n_iterations=5000, seed=42)
        fe = calculate_founder_equivalents(individuals)

        assert abs(fe - 8 / 3) < 1e-9
        assert abs(fge - 4 / 3) < 0.05

    def test_fge_single_offspring_of_two_founders_is_one(self):
        """One offspring of two unrelated founders: GD = 0.5, so FGE = 1.0 (FE = 2)."""
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", None, None, is_active=False),
            Individual("C", "A", "B", is_active=True),
        ]

        fge = calculate_founder_genome_equivalents(individuals, n_iterations=200, seed=1)

        assert abs(fge - 1.0) < 1e-9

    def test_unknown_parent_counts_as_unrelated_founder(self):
        """Sire = founder, dam unknown: the unknown dam is a distinct allele.

        Consistent with the kinship model (self-kinship 0.5, proportional_loss 0.5):
        GD = 0.5 and FGE = 1.0. Phantom alleles must not show up as founders.
        """
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("X", "A", None, is_active=True),
        ]

        stats = calculate_gene_drop_statistics(individuals, n_iterations=200, seed=3)
        alleles, pop_ids, _ = gene_drop_simulation(individuals, n_iterations=50, seed=3)

        assert abs(stats["gene_diversity"] - 0.5) < 1e-12
        assert abs(stats["founder_genome_equivalents"] - 1.0) < 1e-12
        assert set(stats["genome_contributions"]) == {"A"}
        assert abs(stats["genome_contributions"]["A"] - 0.5) < 1e-12
        assert set(stats["allele_retention"]) == {"A"}
        assert stats["allele_retention"]["A"] == 1.0
        assert calculate_founder_statistics(individuals)["proportional_loss"] == 0.5
        # Genome uniqueness counts only real founder alleles, as before
        assert calculate_genome_uniqueness(alleles, pop_ids) == {"X": 1.0}

    def test_fge_equals_n_for_founders_only(self):
        """When population is only founders, FGE = FE = n."""
        individuals = [
            Individual("A", None, None, is_active=True),
            Individual("B", None, None, is_active=True),
            Individual("C", None, None, is_active=True),
        ]

        fge = calculate_founder_genome_equivalents(individuals, n_iterations=100, seed=42)

        # FGE = FE = 3 when all are unrelated founders
        assert abs(fge - 3.0) < 0.01


class TestAlleleRetention:
    """Test allele retention probability calculation."""

    def test_founder_alleles_retained_in_simple_pedigree(self):
        """All founder alleles should be retained with high probability."""
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", None, None, is_active=False),
            Individual("C", "A", "B", is_active=True),
        ]

        retention = calculate_allele_retention(individuals, n_iterations=1000, seed=42)

        # Both A and B contribute to C, so retention should be high
        assert retention["A"] > 0.9
        assert retention["B"] > 0.9


class TestGeneDiversity:
    """Test gene diversity calculation."""

    def test_gene_diversity_founders_only(self):
        """With only founders, gene diversity is maximized."""
        individuals = [
            Individual("A", None, None, is_active=True),
            Individual("B", None, None, is_active=True),
        ]

        gd = calculate_gene_diversity(individuals, n_iterations=100, seed=42)

        # 2 founders * 2 alleles = 4 unique alleles, each at 25%
        # GD = 1 - sum(0.25^2 * 4) = 1 - 0.25 = 0.75
        assert abs(gd - 0.75) < 0.01

    def test_gene_diversity_single_founder(self):
        """With one founder, gene diversity is 0.5."""
        individuals = [
            Individual("A", None, None, is_active=True),
        ]

        gd = calculate_gene_diversity(individuals, n_iterations=100, seed=42)

        # 1 founder * 2 alleles, each at 50%
        # GD = 1 - (0.5^2 + 0.5^2) = 1 - 0.5 = 0.5
        assert abs(gd - 0.5) < 0.01


class TestGeneDropStatistics:
    """Test comprehensive gene drop statistics."""

    def test_gene_drop_statistics_lacy1989(self):
        """Full gene drop statistics for Lacy 1989."""
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", None, None, is_active=False),
            Individual("C", "A", "B", is_active=False),
            Individual("D", "A", "B", is_active=False),
            Individual("E", None, None, is_active=False),
            Individual("F", "D", "E", is_active=True),
            Individual("G", "D", "E", is_active=True),
        ]

        stats = calculate_gene_drop_statistics(individuals, n_iterations=1000, seed=42)

        assert stats["n_founders"] == 3
        assert stats["population_size"] == 2
        assert stats["n_iterations"] == 1000

        # FGE = 1 / (2 * (1 - GD)) = 4/3 for this pedigree (FE = 8/3)
        assert abs(stats["founder_genome_equivalents"] - 4 / 3) < 0.05
        assert abs(stats["founder_genome_equivalents"] - 1 / (2 * (1 - stats["gene_diversity"]))) < 1e-9
        assert abs(stats["founder_equivalents"] - 2.67) < 0.01

        # Gene diversity should be reasonable (between 0 and 1)
        assert 0 < stats["gene_diversity"] < 1

        # All founders should have contributions
        assert len(stats["genome_contributions"]) == 3
        assert len(stats["allele_retention"]) == 3


# =============================================================================
# Population Metrics Tests (Phase 4)
# =============================================================================


class TestGenerationNumbers:
    """Test generation number calculations."""

    def test_founders_have_generation_zero(self):
        """Founders should have max_gen=0, full_gen=0, equiv_gen=0."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
        ]

        gen = calculate_generation_numbers(individuals)

        assert gen["A"]["max_gen"] == 0
        assert gen["A"]["full_gen"] == 0
        assert gen["A"]["equiv_gen"] == 0.0
        assert gen["B"]["max_gen"] == 0
        assert gen["B"]["full_gen"] == 0
        assert gen["B"]["equiv_gen"] == 0.0

    def test_first_generation_offspring(self):
        """Offspring of founders should have max_gen=1, full_gen=1, equiv_gen=1."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
        ]

        gen = calculate_generation_numbers(individuals)

        assert gen["C"]["max_gen"] == 1
        assert gen["C"]["full_gen"] == 1
        assert abs(gen["C"]["equiv_gen"] - 1.0) < 1e-10

    def test_second_generation(self):
        """Second generation offspring should have gen=2."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
            Individual("D", "A", "B"),
            Individual("E", "C", "D"),
        ]

        gen = calculate_generation_numbers(individuals)

        assert gen["E"]["max_gen"] == 2
        assert gen["E"]["full_gen"] == 2
        assert abs(gen["E"]["equiv_gen"] - 2.0) < 1e-10

    def test_equiv_gen_with_partial_knowledge(self):
        """
        Equivalent generations account for incomplete pedigree.

        If only one parent is known:
        equiv_gen = 0.5 * (1 + equiv_gen_parent)
        """
        individuals = [
            Individual("A", None, None),
            Individual("B", "A", None),  # Only sire known
        ]

        gen = calculate_generation_numbers(individuals)

        # B has only sire known: equiv_gen = 0.5 * (1 + 0) = 0.5
        assert abs(gen["B"]["equiv_gen"] - 0.5) < 1e-10
        # full_gen should be 0 (need both parents for complete generation)
        assert gen["B"]["full_gen"] == 0
        # max_gen is 1 (through sire)
        assert gen["B"]["max_gen"] == 1

    def test_asymmetric_pedigree(self):
        """
        Test with asymmetric pedigree depth.

        A ─── B (founders)
        │
        C ─── D (D is founder)
        │
        E
        """
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
            Individual("D", None, None),
            Individual("E", "C", "D"),
        ]

        gen = calculate_generation_numbers(individuals)

        # E: max_gen = 2 (through C), full_gen = 1 (D is founder)
        assert gen["E"]["max_gen"] == 2
        assert gen["E"]["full_gen"] == 1  # min(full_gen_C, full_gen_D) + 1 = min(1,0) + 1

    def test_lacy1989_generations(self):
        """Test with Lacy 1989 pedigree."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
            Individual("D", "A", "B"),
            Individual("E", None, None),
            Individual("F", "D", "E"),
            Individual("G", "D", "E"),
        ]

        gen = calculate_generation_numbers(individuals)

        # F and G: max_gen=2, full_gen=1 (E is founder at gen 0)
        assert gen["F"]["max_gen"] == 2
        assert gen["G"]["max_gen"] == 2
        # full_gen: min(D's full_gen, E's full_gen) + 1 = min(1, 0) + 1 = 1
        assert gen["F"]["full_gen"] == 1
        assert gen["G"]["full_gen"] == 1


class TestPedigreeCompleteness:
    """Test Pedigree Completeness Index (PCI) calculation."""

    def test_complete_first_generation(self):
        """PCI at generation 1 = 1.0 when both parents known."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
        ]

        pci = calculate_pedigree_completeness(individuals)

        assert abs(pci["C"][1] - 1.0) < 1e-10  # 2/2 parents known

    def test_incomplete_first_generation(self):
        """PCI at generation 1 = 0.5 when one parent known."""
        individuals = [
            Individual("A", None, None),
            Individual("B", "A", None),  # Only sire known
        ]

        pci = calculate_pedigree_completeness(individuals)

        assert abs(pci["B"][1] - 0.5) < 1e-10  # 1/2 parents known

    def test_complete_two_generations(self):
        """PCI at generation 2 = 1.0 when all 4 grandparents known."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", None, None),
            Individual("D", None, None),
            Individual("E", "A", "B"),
            Individual("F", "C", "D"),
            Individual("G", "E", "F"),
        ]

        pci = calculate_pedigree_completeness(individuals)

        assert abs(pci["G"][1] - 1.0) < 1e-10  # 2/2 parents known
        assert abs(pci["G"][2] - 1.0) < 1e-10  # 4/4 grandparents known

    def test_lacy1989_pci(self):
        """PCI for Lacy 1989 pedigree."""
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
            Individual("D", "A", "B"),
            Individual("E", None, None),
            Individual("F", "D", "E"),
            Individual("G", "D", "E"),
        ]

        pci = calculate_pedigree_completeness(individuals)

        # F: parents D, E known (100%)
        assert abs(pci["F"][1] - 1.0) < 1e-10
        # F: grandparents: D's parents (A, B) known, E's parents (?, ?) unknown
        # 2/4 = 0.5
        assert abs(pci["F"][2] - 0.5) < 1e-10

    def test_founders_pci_zero(self):
        """Founders should have PCI = 0 at all generations."""
        individuals = [
            Individual("A", None, None),
        ]

        pci = calculate_pedigree_completeness(individuals)

        for gen in range(1, 6):
            assert pci["A"][gen] == 0.0


class TestInbreedingRate:
    """Test rate of inbreeding (ΔF) calculation."""

    def test_no_inbreeding_delta_f_zero(self):
        """When no inbreeding occurs, ΔF should be 0 or very small."""
        # Simple pedigree with no inbreeding
        individuals = [
            Individual("A", None, None),
            Individual("B", None, None),
            Individual("C", "A", "B"),
        ]

        result = calculate_inbreeding_rate(individuals)

        # With no inbreeding, delta_f should be 0 (or very small)
        assert result["delta_f"] < 0.01

    def test_full_sibling_mating_increases_inbreeding(self):
        """Continuous full sibling mating should increase ΔF."""
        # Build a pedigree with increasing inbreeding
        individuals = [
            Individual("F0-M", None, None),
            Individual("F0-F", None, None),
        ]

        # 5 generations of full sibling mating
        for gen in range(1, 6):
            prev_m = f"F{gen - 1}-M"
            prev_f = f"F{gen - 1}-F"
            individuals.append(Individual(f"F{gen}-M", prev_m, prev_f))
            individuals.append(Individual(f"F{gen}-F", prev_m, prev_f))

        result = calculate_inbreeding_rate(individuals, method="regression")

        # ΔF should be positive and significant
        assert result["delta_f"] > 0.05
        assert result["r_squared"] > 0.5  # Good fit

    def test_generational_method(self):
        """Test generational ΔF calculation."""
        individuals = [
            Individual("F0-M", None, None),
            Individual("F0-F", None, None),
        ]

        for gen in range(1, 4):
            prev_m = f"F{gen - 1}-M"
            prev_f = f"F{gen - 1}-F"
            individuals.append(Individual(f"F{gen}-M", prev_m, prev_f))
            individuals.append(Individual(f"F{gen}-F", prev_m, prev_f))

        result = calculate_inbreeding_rate(individuals, method="generational")

        assert "delta_f_by_gen" in result
        assert result["delta_f"] > 0


class TestEffectivePopulationSize:
    """Test Effective Population Size (Ne) calculation."""

    def test_large_unrelated_population_high_ne(self):
        """Large population of unrelated individuals should have high Ne."""
        # Create 20 unrelated founders
        individuals = [Individual(f"F{i}", None, None) for i in range(20)]

        result = calculate_effective_population_size(individuals)

        # With no inbreeding, Ne should be 0 (infinite)
        # Our implementation returns 0 when delta_f is 0
        assert result["delta_f"] < 0.01

    def test_small_inbred_population_low_ne(self):
        """Small inbred population should have low Ne."""
        individuals = [
            Individual("F0-M", None, None),
            Individual("F0-F", None, None),
        ]

        # 6 generations of full sibling mating
        for gen in range(1, 7):
            prev_m = f"F{gen - 1}-M"
            prev_f = f"F{gen - 1}-F"
            individuals.append(Individual(f"F{gen}-M", prev_m, prev_f))
            individuals.append(Individual(f"F{gen}-F", prev_m, prev_f))

        result = calculate_effective_population_size(individuals)

        # Ne should be calculable (delta_f > 0)
        if result["delta_f"] > 0:
            # With continuous full sibling mating, Ne ≈ 2
            # Ne = 1 / (2 * ΔF), and for full sibling mating ΔF ≈ 0.19
            assert result["ne"] > 0
            assert result["ne"] < 10  # Should be small


class TestPopulationMetrics:
    """Test comprehensive population metrics."""

    def test_empty_population(self):
        """Empty population should return zeros."""
        metrics = calculate_population_metrics([])

        assert metrics["population_size"] == 0
        assert metrics["n_founders"] == 0
        assert metrics["mean_inbreeding"] == 0.0

    def test_founders_only_population(self):
        """Population of only founders."""
        individuals = [
            Individual("A", None, None, is_active=True),
            Individual("B", None, None, is_active=True),
            Individual("C", None, None, is_active=True),
        ]

        metrics = calculate_population_metrics(individuals)

        assert metrics["population_size"] == 3
        assert metrics["n_active"] == 3
        assert metrics["n_founders"] == 3
        assert metrics["founder_equivalents"] == 3.0
        assert metrics["mean_inbreeding"] == 0.0
        assert metrics["max_inbreeding"] == 0.0
        assert metrics["mean_equiv_gen"] == 0.0

    def test_lacy1989_metrics(self):
        """Test with Lacy 1989 pedigree."""
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", None, None, is_active=False),
            Individual("C", "A", "B", is_active=False),
            Individual("D", "A", "B", is_active=False),
            Individual("E", None, None, is_active=False),
            Individual("F", "D", "E", is_active=True),
            Individual("G", "D", "E", is_active=True),
        ]

        metrics = calculate_population_metrics(individuals)

        assert metrics["population_size"] == 7
        assert metrics["n_active"] == 2
        assert metrics["n_population"] == 2
        assert metrics["n_founders"] == 3
        assert abs(metrics["founder_equivalents"] - 2.6667) < 0.001
        assert metrics["mean_inbreeding"] == 0.0  # F, G are not inbred
        assert metrics["mean_equiv_gen"] > 0  # F, G have equiv_gen > 0

    def test_inbred_population_metrics(self):
        """Test with inbred population."""
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", None, None, is_active=False),
            Individual("C", "A", "B", is_active=False),
            Individual("D", "A", "B", is_active=False),
            Individual("E", "C", "D", is_active=True),  # Inbred (F=0.25)
        ]

        metrics = calculate_population_metrics(individuals)

        assert metrics["n_active"] == 1
        assert abs(metrics["mean_inbreeding"] - 0.25) < 1e-10
        assert abs(metrics["max_inbreeding"] - 0.25) < 1e-10

    def test_realised_ne_from_individual_delta_f(self):
        """Ne = 1/(2·mean ΔFᵢ), ΔFᵢ = 1 - (1 - Fᵢ)^(1/(tᵢ - 1)) (Gutiérrez et al. 2008/2009).

        Two generations of full-sib mating. Reference {C, E, F, G}:
        C has t = 1 (excluded); E, F: t = 2, F = 0.25 → ΔF = 0.25;
        G: t = 3, F = 0.375 → ΔF = 1 - 0.625^(1/2).
        """
        individuals = [
            Individual("A", None, None, is_active=False),
            Individual("B", None, None, is_active=False),
            Individual("C", "A", "B", is_active=True),
            Individual("D", "A", "B", is_active=False),
            Individual("E", "C", "D", is_active=True),
            Individual("F", "C", "D", is_active=True),
            Individual("G", "E", "F", is_active=True),
        ]
        generations = calculate_generation_numbers(individuals)
        assert generations["C"]["equiv_gen"] == 1.0
        assert generations["E"]["equiv_gen"] == 2.0
        assert generations["G"]["equiv_gen"] == 3.0

        metrics = calculate_population_metrics(individuals)

        delta_fs = np.array([0.25, 0.25, 1 - 0.625**0.5])
        ne = 1 / (2 * delta_fs.mean())
        se = 2 * ne**2 * delta_fs.std(ddof=1) / np.sqrt(3)
        assert metrics["ne_method"] == "individual_delta_f"
        assert metrics["ne_n"] == 3
        assert abs(metrics["delta_f"] - delta_fs.mean()) < 1e-12
        assert abs(metrics["effective_population_size"] - ne) < 1e-9  # ≈ 2.114
        assert abs(metrics["ne_se"] - se) < 1e-9

    def test_ne_not_estimable_is_none(self):
        """No animal with t > 1, or mean ΔF ≤ 0: Ne and ΔF are None, not 0."""
        founders_only = [Individual("A", None, None, is_active=True), Individual("B", None, None, is_active=True)]
        # Lacy 1989 F, G: t = 1.5 but F = 0, so mean ΔF = 0.
        no_inbreeding = [
            Individual("A", None, None, is_active=False),
            Individual("B", None, None, is_active=False),
            Individual("D", "A", "B", is_active=False),
            Individual("E", None, None, is_active=False),
            Individual("F", "D", "E", is_active=True),
            Individual("G", "D", "E", is_active=True),
        ]
        for individuals, n_used in ((founders_only, 0), (no_inbreeding, 2)):
            metrics = calculate_population_metrics(individuals)
            assert metrics["effective_population_size"] is None
            assert metrics["delta_f"] is None
            assert metrics["ne_se"] is None
            assert metrics["ne_n"] == n_used

    def test_expected_offspring_f_is_mean_male_female_kinship(self):
        """Random mating among reference males × females: mean K over those pairs.

        M1 and F1 are full sibs (K = 0.25); M2 and F2 are unrelated founders,
        so the mean over the 2×2 pairs is 0.0625. Animals without sex are excluded.
        """
        individuals = [
            Individual("A", None, None, is_active=False, sex="male"),
            Individual("B", None, None, is_active=False, sex="female"),
            Individual("M1", "A", "B", is_active=True, sex="male"),
            Individual("F1", "A", "B", is_active=True, sex="female"),
            Individual("M2", None, None, is_active=True, sex="male"),
            Individual("F2", None, None, is_active=True, sex="female"),
            Individual("X", "M1", "F1", is_active=True, sex=None),
        ]

        metrics = calculate_population_metrics(individuals)

        assert abs(metrics["expected_offspring_f"] - 0.0625) < 1e-12

    def test_expected_offspring_f_none_without_both_sexes(self):
        individuals = [
            Individual("M1", None, None, is_active=True, sex="male"),
            Individual("M2", None, None, is_active=True, sex="male"),
            Individual("F1", None, None, is_active=False, sex="female"),
        ]

        assert calculate_population_metrics(individuals)["expected_offspring_f"] is None
        assert calculate_population_metrics([])["expected_offspring_f"] is None

    def test_all_metrics_present(self):
        """Verify all expected metrics are present."""
        individuals = [
            Individual("A", None, None, is_active=True),
            Individual("B", None, None, is_active=True),
        ]

        metrics = calculate_population_metrics(individuals)

        expected_keys = [
            "population_size",
            "n_active",
            "n_population",
            "n_founders",
            "founder_equivalents",
            "mean_inbreeding",
            "max_inbreeding",
            "mean_kinship",
            "effective_population_size",
            "delta_f",
            "ne_method",
            "ne_se",
            "ne_n",
            "expected_offspring_f",
            "mean_equiv_gen",
            "mean_full_gen",
            "mean_max_gen",
        ]

        for key in expected_keys:
            assert key in metrics, f"Missing key: {key}"


class TestGeneticPriorities:
    """Test genetic priority scoring."""

    @pytest.fixture
    def lacy_pedigree(self):
        """Lacy 1989 pedigree with sex information."""
        return [
            Individual("A", None, None, is_active=True, sex="male"),
            Individual("B", None, None, is_active=True, sex="female"),
            Individual("C", "A", "B", is_active=True, sex="male"),
            Individual("D", "A", "B", is_active=True, sex="female"),
            Individual("E", None, None, is_active=True, sex="male"),
            Individual("F", "D", "E", is_active=True, sex="male"),
            Individual("G", "D", "E", is_active=True, sex="female"),
        ]

    def test_all_individuals_get_priority(self, lacy_pedigree):
        """Every active individual should get a priority assignment."""
        mk = calculate_mean_kinship(lacy_pedigree)
        contrib, founders = calculate_founder_contributions(lacy_pedigree)
        # Use empty GU for simplicity
        gu = {ind.id: 0.0 for ind in lacy_pedigree}

        priorities = calculate_genetic_priorities(lacy_pedigree, mk, contrib, gu)

        active_ids = {ind.id for ind in lacy_pedigree if ind.is_active}
        priority_ids = {p.individual_id for p in priorities}
        assert priority_ids == active_ids

    def test_priority_levels_are_valid(self, lacy_pedigree):
        """All priorities should be 'critical', 'important', or 'normal'."""
        mk = calculate_mean_kinship(lacy_pedigree)
        contrib, founders = calculate_founder_contributions(lacy_pedigree)
        gu = {ind.id: 0.0 for ind in lacy_pedigree}

        priorities = calculate_genetic_priorities(lacy_pedigree, mk, contrib, gu)

        valid_levels = {"critical", "important", "normal"}
        for p in priorities:
            assert p.priority in valid_levels, f"{p.individual_id}: {p.priority}"

    def test_sole_founder_carrier_is_critical(self):
        """An individual that is the sole carrier of a founder line is critical."""
        # E is a founder. Only F and G carry E's genes. Make G inactive.
        individuals = [
            Individual("A", None, None, is_active=True, sex="male"),
            Individual("B", None, None, is_active=True, sex="female"),
            Individual("C", "A", "B", is_active=True, sex="male"),
            Individual("D", "A", "B", is_active=True, sex="female"),
            Individual("E", None, None, is_active=False, sex="male"),  # inactive
            Individual("F", "D", "E", is_active=True, sex="male"),
            Individual("G", "D", "E", is_active=False, sex="female"),  # inactive
        ]

        mk = calculate_mean_kinship(individuals)
        contrib, founders = calculate_founder_contributions(
            individuals, population_ids=[i.id for i in individuals if i.is_active]
        )
        gu = {ind.id: 0.0 for ind in individuals if ind.is_active}

        priorities = calculate_genetic_priorities(individuals, mk, contrib, gu)

        # F is the sole active carrier of founder E's line
        f_priority = next(p for p in priorities if p.individual_id == "F")
        assert f_priority.priority == "critical"
        assert any("sole" in r.lower() or "carrier" in r.lower() for r in f_priority.reasons)

    def test_low_mk_gets_higher_priority(self, lacy_pedigree):
        """Individuals with low MK should get higher genetic value scores."""
        mk = calculate_mean_kinship(lacy_pedigree)
        contrib, founders = calculate_founder_contributions(lacy_pedigree)
        gu = {ind.id: 0.0 for ind in lacy_pedigree}

        priorities = calculate_genetic_priorities(lacy_pedigree, mk, contrib, gu)

        # E has lowest MK (unrelated founder), should have high score
        e_priority = next(p for p in priorities if p.individual_id == "E")
        d_priority = next(p for p in priorities if p.individual_id == "D")

        # E (unrelated to A/B line) should have lower MK than D
        assert e_priority.genetic_value_score >= d_priority.genetic_value_score

    def test_genetic_value_score_range(self, lacy_pedigree):
        """Genetic value scores should be between 0 and 100."""
        mk = calculate_mean_kinship(lacy_pedigree)
        contrib, founders = calculate_founder_contributions(lacy_pedigree)
        gu = {ind.id: 0.0 for ind in lacy_pedigree}

        priorities = calculate_genetic_priorities(lacy_pedigree, mk, contrib, gu)

        for p in priorities:
            assert 0.0 <= p.genetic_value_score <= 100.0, f"{p.individual_id}: score={p.genetic_value_score}"

    def test_reasons_are_populated(self, lacy_pedigree):
        """Every priority assignment should have at least one reason."""
        mk = calculate_mean_kinship(lacy_pedigree)
        contrib, founders = calculate_founder_contributions(lacy_pedigree)
        gu = {ind.id: 0.0 for ind in lacy_pedigree}

        priorities = calculate_genetic_priorities(lacy_pedigree, mk, contrib, gu)

        for p in priorities:
            assert len(p.reasons) >= 1, f"{p.individual_id}: no reasons for priority={p.priority}"

    def test_lacy1989_hand_computed_priorities(self, lacy_pedigree):
        """Verify exact priority assignments using hand-computed values from Lacy 1989.

        Known MK values (from verified kinship matrix, optiSel):
          E=0.1429, A=B=0.1786, C=0.2143, F=G=0.2321, D=0.2500

        With 7 individuals:
          p5  = 0.1536 (np.percentile with linear interpolation)
          p25 = 0.1786

        Expected priorities (GU=0 for all, no underrepresented founders):
          E: critical  (MK=0.1429 < p5=0.1536)
          A: important (MK=0.1786 <= p25=0.1786)
          B: important (MK=0.1786 <= p25=0.1786)
          C: normal    (MK=0.2143 > p25)
          D: normal    (MK=0.2500 > p25)
          F: normal    (MK=0.2321 > p25)
          G: normal    (MK=0.2321 > p25)

        Genetic value scores (inverted MK percentile: higher_count / n * 100):
          E: 85.7 (6/7 have higher MK)
          A: 57.1, B: 57.1, C: 42.9, F: 14.3, G: 14.3, D: 0.0
        """
        mk = calculate_mean_kinship(lacy_pedigree)
        contrib, founders = calculate_founder_contributions(lacy_pedigree)
        gu = {ind.id: 0.0 for ind in lacy_pedigree}

        priorities = calculate_genetic_priorities(lacy_pedigree, mk, contrib, gu)

        p = {gp.individual_id: gp for gp in priorities}

        # Verify exact priority levels
        assert p["E"].priority == "critical"
        assert p["A"].priority == "important"
        assert p["B"].priority == "important"
        assert p["C"].priority == "normal"
        assert p["D"].priority == "normal"
        assert p["F"].priority == "normal"
        assert p["G"].priority == "normal"

        # Verify genetic value scores (hand-computed)
        assert p["E"].genetic_value_score == pytest.approx(85.7, abs=0.1)
        assert p["A"].genetic_value_score == pytest.approx(57.1, abs=0.1)
        assert p["B"].genetic_value_score == pytest.approx(57.1, abs=0.1)
        assert p["C"].genetic_value_score == pytest.approx(42.9, abs=0.1)
        assert p["D"].genetic_value_score == pytest.approx(0.0, abs=0.1)
        assert p["F"].genetic_value_score == pytest.approx(14.3, abs=0.1)
        assert p["G"].genetic_value_score == pytest.approx(14.3, abs=0.1)

    def test_empty_population(self):
        """Empty input should return empty list."""
        result = calculate_genetic_priorities([], {}, {}, {})
        assert result == []


class TestBreedingRecommendations:
    """Test breeding pair selection using Dynamic MK Selection."""

    @pytest.fixture
    def lacy_pedigree_with_sex(self):
        """Lacy 1989 pedigree with sex assignments."""
        return [
            Individual("A", None, None, is_active=True, sex="male"),
            Individual("B", None, None, is_active=True, sex="female"),
            Individual("C", "A", "B", is_active=True, sex="male"),
            Individual("D", "A", "B", is_active=True, sex="female"),
            Individual("E", None, None, is_active=True, sex="male"),
            Individual("F", "D", "E", is_active=True, sex="male"),
            Individual("G", "D", "E", is_active=True, sex="female"),
        ]

    def test_returns_breeding_recommendations(self, lacy_pedigree_with_sex):
        """Should return a list of BreedingRecommendation objects."""
        K, ids = calculate_kinship_matrix(lacy_pedigree_with_sex)
        mk = calculate_mean_kinship(lacy_pedigree_with_sex)

        pairs = suggest_breeding_pairs(lacy_pedigree_with_sex, K, ids, mk, max_pairs=3)

        assert len(pairs) > 0
        assert all(isinstance(p, BreedingRecommendation) for p in pairs)

    def test_respects_max_pairs(self, lacy_pedigree_with_sex):
        """Should not return more pairs than max_pairs."""
        K, ids = calculate_kinship_matrix(lacy_pedigree_with_sex)
        mk = calculate_mean_kinship(lacy_pedigree_with_sex)

        pairs = suggest_breeding_pairs(lacy_pedigree_with_sex, K, ids, mk, max_pairs=2)

        assert len(pairs) <= 2

    def test_respects_max_inbreeding(self, lacy_pedigree_with_sex):
        """No pair should produce offspring with F > max_inbreeding."""
        K, ids = calculate_kinship_matrix(lacy_pedigree_with_sex)
        mk = calculate_mean_kinship(lacy_pedigree_with_sex)
        max_f = 0.0625

        pairs = suggest_breeding_pairs(lacy_pedigree_with_sex, K, ids, mk, max_pairs=10, max_inbreeding=max_f)

        for pair in pairs:
            assert pair.expected_f <= max_f, f"Pair {pair.sire_id}×{pair.dam_id}: F={pair.expected_f} > {max_f}"

    def test_pairs_are_male_female(self, lacy_pedigree_with_sex):
        """Sire should be male, dam should be female."""
        K, ids = calculate_kinship_matrix(lacy_pedigree_with_sex)
        mk = calculate_mean_kinship(lacy_pedigree_with_sex)

        pairs = suggest_breeding_pairs(lacy_pedigree_with_sex, K, ids, mk, max_pairs=5)

        sex_map = {ind.id: ind.sex for ind in lacy_pedigree_with_sex}
        for pair in pairs:
            assert sex_map[pair.sire_id] == "male", f"Sire {pair.sire_id} is not male"
            assert sex_map[pair.dam_id] == "female", f"Dam {pair.dam_id} is not female"

    def test_respects_max_per_male(self, lacy_pedigree_with_sex):
        """A male should not appear more than max_per_male times."""
        K, ids = calculate_kinship_matrix(lacy_pedigree_with_sex)
        mk = calculate_mean_kinship(lacy_pedigree_with_sex)

        pairs = suggest_breeding_pairs(lacy_pedigree_with_sex, K, ids, mk, max_pairs=10, max_per_male=1)

        sire_counts: dict[str, int] = {}
        for pair in pairs:
            sire_counts[pair.sire_id] = sire_counts.get(pair.sire_id, 0) + 1

        for sire_id, count in sire_counts.items():
            assert count <= 1, f"Male {sire_id} appears {count} times (max 1)"

    def test_msi_range(self, lacy_pedigree_with_sex):
        """MSI should be between 1 and 6."""
        K, ids = calculate_kinship_matrix(lacy_pedigree_with_sex)
        mk = calculate_mean_kinship(lacy_pedigree_with_sex)

        pairs = suggest_breeding_pairs(lacy_pedigree_with_sex, K, ids, mk, max_pairs=5)

        for pair in pairs:
            assert 1 <= pair.mate_suitability_index <= 6, f"MSI={pair.mate_suitability_index} out of range [1,6]"

    def test_prefers_low_mk_individuals(self, lacy_pedigree_with_sex):
        """First recommended pair should involve individuals with low MK.

        From Lacy 1989 verified kinship matrix:
          Males sorted by MK: E(0.1429), A(0.1786), C(0.2143), F(0.2321)
          Females sorted by MK: B(0.1786), G(0.2321), D(0.2500)

        Dynamic MK Selection picks lowest-MK male (E) paired with
        lowest-MK female (B). K[E,B]=0.0 so expected_f=0.0.
        """
        K, ids = calculate_kinship_matrix(lacy_pedigree_with_sex)
        mk = calculate_mean_kinship(lacy_pedigree_with_sex)

        pairs = suggest_breeding_pairs(lacy_pedigree_with_sex, K, ids, mk, max_pairs=1)

        # E has the lowest MK (unrelated founder)
        # E is male, so he should be the sire in the first pair
        assert len(pairs) == 1
        assert pairs[0].sire_id == "E", f"Expected E as first sire (lowest MK male), got {pairs[0].sire_id}"

    def test_expected_f_matches_kinship(self, lacy_pedigree_with_sex):
        """expected_f should equal kinship between sire and dam.

        Verified against Lacy 1989 kinship matrix (optiSel):
          K[E,B]=0.0, K[E,G]=0.25, K[E,D]=0.0, K[A,B]=0.0, etc.
        """
        K, ids = calculate_kinship_matrix(lacy_pedigree_with_sex)
        mk = calculate_mean_kinship(lacy_pedigree_with_sex)
        id_to_idx = {id_: i for i, id_ in enumerate(ids)}

        pairs = suggest_breeding_pairs(lacy_pedigree_with_sex, K, ids, mk, max_pairs=3)

        for pair in pairs:
            actual_kinship = K[id_to_idx[pair.sire_id], id_to_idx[pair.dam_id]]
            assert abs(pair.expected_f - actual_kinship) < 1e-10, (
                f"{pair.sire_id}×{pair.dam_id}: expected_f={pair.expected_f}, kinship={actual_kinship}"
            )

    def test_first_pair_lacy1989_known_kinship(self, lacy_pedigree_with_sex):
        """Verify first pair uses known kinship values from Lacy 1989.

        E×B: K[E,B]=0.0 (unrelated, verified by optiSel)
        This is the optimal first pair since both have lowest MK in their sex.
        """
        K, ids = calculate_kinship_matrix(lacy_pedigree_with_sex)
        mk = calculate_mean_kinship(lacy_pedigree_with_sex)

        pairs = suggest_breeding_pairs(lacy_pedigree_with_sex, K, ids, mk, max_pairs=1)

        assert pairs[0].sire_id == "E"
        assert pairs[0].dam_id == "B"
        assert pairs[0].expected_f == 0.0  # K[E,B]=0.0 from optiSel

    def test_delta_gd_is_exact_change_in_mean_kinship(self):
        """ΔGD = μ - μ_new with μ_new = (n²μ + 2n·r̄ + d) / (n+1)².

        Unrelated buck M and two full-sib does D1, D2 in the reference:
        n = 3, μ = 2/9, offspring row r = [0.25, 0.25, 0.125], d = 0.5,
        μ_new = 3.75/16, ΔGD = -0.012153. The old weighted-average
        approximation reported +0.003472 (wrong sign).
        """
        individuals = [
            Individual("A", None, None, is_active=False, sex="male"),
            Individual("B", None, None, is_active=False, sex="female"),
            Individual("M", None, None, is_active=True, sex="male"),
            Individual("D1", "A", "B", is_active=True, sex="female"),
            Individual("D2", "A", "B", is_active=True, sex="female"),
        ]
        K, ids = calculate_kinship_matrix(individuals)
        mk = calculate_mean_kinship(individuals)

        pairs = suggest_breeding_pairs(individuals, K, ids, mk, max_pairs=1)

        assert len(pairs) == 1
        assert pairs[0].sire_id == "M"
        exact = 2 / 9 - 3.75 / 16
        assert pairs[0].delta_gd == round(exact, 6) == -0.012153

    def test_delta_gd_matches_extended_matrix_in_later_rounds(self):
        """Each pair's ΔGD equals mean(K) before minus mean(K') after adding its offspring."""
        individuals = [
            Individual("M1", None, None, is_active=True, sex="male"),
            Individual("M2", None, None, is_active=True, sex="male"),
            Individual("F1", None, None, is_active=True, sex="female"),
            Individual("F2", "M1", "F1", is_active=True, sex="female"),
            Individual("F3", None, None, is_active=True, sex="female"),
        ]
        K, ids = calculate_kinship_matrix(individuals)
        mk = calculate_mean_kinship(individuals)

        # The result is sorted by MSI, so recover the selection order from
        # successive runs: run k adds exactly one pair to run k-1.
        order = []
        for k in range(1, 4):
            pairs = suggest_breeding_pairs(individuals, K, ids, mk, max_pairs=k, max_inbreeding=0.25, max_per_male=3)
            new = [p for p in pairs if (p.sire_id, p.dam_id) not in {(q.sire_id, q.dam_id) for q in order}]
            assert len(new) == 1
            order.append(new[0])

        idx = {id_: i for i, id_ in enumerate(ids)}
        work = K.copy()
        for pair in order:
            m, f = idx[pair.sire_id], idx[pair.dam_id]
            n = work.shape[0]
            row = 0.5 * (work[m, :] + work[f, :])
            extended = np.zeros((n + 1, n + 1))
            extended[:n, :n] = work
            extended[n, :n] = row
            extended[:n, n] = row
            extended[n, n] = 0.5 * (1 + work[m, f])
            assert pair.delta_gd == round(float(np.mean(work) - np.mean(extended)), 6)
            work = extended

    def test_each_dam_used_at_most_once_by_default(self):
        """max_per_female defaults to 1 (PMx): one doe and three bucks give one pair."""
        individuals = [
            Individual("M1", None, None, is_active=True, sex="male"),
            Individual("M2", None, None, is_active=True, sex="male"),
            Individual("M3", None, None, is_active=True, sex="male"),
            Individual("F1", None, None, is_active=True, sex="female"),
        ]
        K, ids = calculate_kinship_matrix(individuals)
        mk = calculate_mean_kinship(individuals)

        pairs = suggest_breeding_pairs(individuals, K, ids, mk, max_pairs=5, max_per_male=1)

        assert [p.dam_id for p in pairs] == ["F1"]

    def test_respects_max_per_female(self, lacy_pedigree_with_sex):
        """A female should not appear more than max_per_female times."""
        K, ids = calculate_kinship_matrix(lacy_pedigree_with_sex)
        mk = calculate_mean_kinship(lacy_pedigree_with_sex)

        pairs = suggest_breeding_pairs(
            lacy_pedigree_with_sex, K, ids, mk, max_pairs=10, max_inbreeding=0.25, max_per_female=2
        )

        dam_counts: dict[str, int] = {}
        for pair in pairs:
            dam_counts[pair.dam_id] = dam_counts.get(pair.dam_id, 0) + 1
        assert dam_counts
        assert max(dam_counts.values()) <= 2

    def test_empty_population(self):
        """Empty input should return empty list."""
        result = suggest_breeding_pairs([], np.array([[]]), [], {})
        assert result == []

    def test_no_valid_pairs_with_strict_inbreeding(self):
        """Very strict inbreeding limit with related population → no pairs."""
        # All related, very strict limit
        individuals = [
            Individual("A", None, None, is_active=True, sex="male"),
            Individual("B", None, None, is_active=True, sex="female"),
            Individual("C", "A", "B", is_active=True, sex="male"),
            Individual("D", "A", "B", is_active=True, sex="female"),
        ]
        K, ids = calculate_kinship_matrix(individuals)
        mk = calculate_mean_kinship(individuals)

        # max_inbreeding=0 → only completely unrelated pairs allowed
        # A×B has kinship 0.0, so that pair should work
        # C×D has kinship 0.25, so that pair should be rejected
        pairs = suggest_breeding_pairs(individuals, K, ids, mk, max_pairs=5, max_inbreeding=0.0)

        for pair in pairs:
            assert pair.expected_f <= 0.0


class TestGenomeUniqueness:
    """Test genome uniqueness calculation from gene drop simulation."""

    def test_deterministic_allele_matrix(self):
        """Verify GU with a hand-constructed allele matrix where we know exact results.

        3 individuals (6 rows), 2 iterations:
        Iteration 0: [0, 1, 2, 3, 4, 5] — all alleles unique, everyone has unique alleles
        Iteration 1: [0, 0, 2, 2, 4, 5] — Ind0 has 0,0 (homozygous, sole carrier: unique),
                                            Ind1 has 2,2 (homozygous, sole carrier: unique),
                                            Ind2 has 4,5 (both carried by Ind2 only, unique)

        Expected GU: everyone 1.0. GU counts carriers, not copies (Ballou & Lacy).
        """
        allele_matrix = np.array(
            [
                [0, 0],  # Ind0 paternal
                [1, 0],  # Ind0 maternal
                [2, 2],  # Ind1 paternal
                [3, 2],  # Ind1 maternal
                [4, 4],  # Ind2 paternal
                [5, 5],  # Ind2 maternal
            ]
        )
        pop_ids = ["X", "Y", "Z"]
        gu = calculate_genome_uniqueness(allele_matrix, pop_ids)

        assert gu["X"] == 1.0
        assert gu["Y"] == 1.0
        assert gu["Z"] == 1.0

    def test_homozygous_private_allele_is_unique(self):
        """X = 0/0 and nobody else carries 0, so X is unique in every iteration."""
        alleles = np.array([[0], [0], [1], [2]])  # X: 0/0, Y: 1/2
        gu = calculate_genome_uniqueness(alleles, ["X", "Y"])
        assert gu["X"] == 1.0, f"GU of X (sole carrier of allele 0, homozygous) = {gu['X']}"
        assert gu["Y"] == 1.0, f"GU of Y = {gu['Y']}"

    def test_shared_allele_still_not_unique(self):
        """X = 0/0, Y = 0/1, Z = 2/2: allele 0 has two carriers; Y's 1 and Z's 2 are private."""
        alleles = np.array([[0], [0], [0], [1], [2], [2]])
        gu = calculate_genome_uniqueness(alleles, ["X", "Y", "Z"])
        assert gu == {"X": 0.0, "Y": 1.0, "Z": 1.0}, f"GU = {gu}"

    def test_deterministic_no_unique_alleles(self):
        """When all alleles are shared, GU should be 0.0.

        2 individuals, 2 iterations. Both individuals always carry the same alleles.
        """
        allele_matrix = np.array(
            [
                [0, 0],  # Ind0 paternal
                [1, 1],  # Ind0 maternal
                [0, 0],  # Ind1 paternal
                [1, 1],  # Ind1 maternal
            ]
        )
        pop_ids = ["A", "B"]
        gu = calculate_genome_uniqueness(allele_matrix, pop_ids)

        assert gu["A"] == 0.0
        assert gu["B"] == 0.0

    def test_founder_only_population(self):
        """In a population of unrelated founders, each has unique alleles."""
        # 3 founders, 2 alleles each = 6 unique alleles, everyone is unique
        individuals = [
            Individual("A", None, None, is_active=True),
            Individual("B", None, None, is_active=True),
            Individual("C", None, None, is_active=True),
        ]
        allele_matrix, pop_ids, founder_ids = gene_drop_simulation(individuals, n_iterations=100, seed=42)
        gu = calculate_genome_uniqueness(allele_matrix, pop_ids)

        # Every founder's alleles are unique (only they carry them)
        # With 3 founders and 6 unique alleles, every individual has unique alleles
        for fid in ["A", "B", "C"]:
            assert fid in gu
            assert gu[fid] == 1.0, f"Founder {fid} should have GU=1.0"

    def test_inbred_population_lower_gu(self):
        """Individuals sharing alleles should have lower GU."""
        # After inbreeding, alleles become shared, reducing uniqueness
        individuals = [
            Individual("A", None, None, is_active=True),
            Individual("B", None, None, is_active=True),
            Individual("C", "A", "B", is_active=True),
            Individual("D", "A", "B", is_active=True),
        ]
        allele_matrix, pop_ids, founder_ids = gene_drop_simulation(individuals, n_iterations=500, seed=42)
        gu = calculate_genome_uniqueness(allele_matrix, pop_ids)

        # Founders should have higher GU than offspring who share alleles
        # C and D share parents so they're likely to share alleles
        assert gu["A"] >= gu["C"] or gu["A"] >= gu["D"]

    def test_gu_values_in_range(self):
        """GU values should be between 0.0 and 1.0."""
        individuals = [
            Individual("A", None, None, is_active=True),
            Individual("B", None, None, is_active=True),
            Individual("C", "A", "B", is_active=True),
        ]
        allele_matrix, pop_ids, founder_ids = gene_drop_simulation(individuals, n_iterations=100, seed=42)
        gu = calculate_genome_uniqueness(allele_matrix, pop_ids)

        for ind_id, value in gu.items():
            assert 0.0 <= value <= 1.0, f"GU[{ind_id}] = {value} out of range"

    def test_empty_population(self):
        """Empty input should return empty dict."""
        allele_matrix = np.array([[]])
        gu = calculate_genome_uniqueness(allele_matrix, [])
        assert gu == {}


class TestDataclasses:
    """Test new Phase 5 dataclasses."""

    def test_individual_sex_field(self):
        """Individual should support optional sex field."""
        male = Individual("M1", None, None, is_active=True, sex="male")
        female = Individual("F1", None, None, is_active=True, sex="female")
        unknown = Individual("U1", None, None, is_active=True)

        assert male.sex == "male"
        assert female.sex == "female"
        assert unknown.sex is None

    def test_genetic_priority_creation(self):
        """GeneticPriority dataclass should hold all fields."""
        gp = GeneticPriority(
            individual_id="A",
            priority="critical",
            reasons=["Sole carrier of founder line X"],
            genetic_value_score=95.0,
            genome_uniqueness=0.43,
        )
        assert gp.priority == "critical"
        assert len(gp.reasons) == 1

    def test_breeding_recommendation_creation(self):
        """BreedingRecommendation dataclass should hold all fields."""
        br = BreedingRecommendation(
            sire_id="M1",
            dam_id="F1",
            expected_f=0.031,
            delta_gd=0.002,
            mate_suitability_index=1,
            reasons=["Both parents have low MK"],
        )
        assert br.mate_suitability_index == 1
        assert br.expected_f == 0.031


class TestExtractDeathYear:
    """Test year extraction from death_note field."""

    def test_year_space_format(self):
        from utils.genetics import extract_death_year

        assert extract_death_year("2018 dåligt temperament") == 2018

    def test_year_comma_format(self):
        from utils.genetics import extract_death_year

        assert extract_death_year("2020, ålder") == 2020

    def test_historical_year(self):
        from utils.genetics import extract_death_year

        assert extract_death_year("1995 rymt") == 1995

    def test_no_year(self):
        from utils.genetics import extract_death_year

        assert extract_death_year("Ålder") is None

    def test_none_input(self):
        from utils.genetics import extract_death_year

        assert extract_death_year(None) is None

    def test_empty_string(self):
        from utils.genetics import extract_death_year

        assert extract_death_year("") is None

    def test_year_question_mark(self):
        from utils.genetics import extract_death_year

        assert extract_death_year("1998 ?") == 1998


@dataclass
class MockIndividual:
    """Minimal Individual for is_active_at_date() testing."""

    number: str
    birth_date: date | None = None
    certificate: str | None = "CERT-001"
    digital_certificate: int | None = None
    castration_date: date | None = None
    death_date: date | None = None
    death_note: str | None = None
    id: int = 0


class TestIsActiveAtDate:
    """Test historical active status reconstruction."""

    def test_born_after_target_not_active(self):
        from utils.genetics import is_active_at_date

        ind = MockIndividual(number="A1", birth_date=date(2010, 3, 15))
        assert is_active_at_date(ind, date(2009, 12, 30)) is False

    def test_no_birth_date_not_active(self):
        from utils.genetics import is_active_at_date

        ind = MockIndividual(number="A1", birth_date=None)
        assert is_active_at_date(ind, date(2020, 12, 30)) is False

    def test_no_certificate_not_active(self):
        from utils.genetics import is_active_at_date

        ind = MockIndividual(number="A1", birth_date=date(2018, 1, 1), certificate=None, digital_certificate=None)
        assert is_active_at_date(ind, date(2020, 12, 30)) is False

    def test_castrated_before_date_not_active(self):
        from utils.genetics import is_active_at_date

        ind = MockIndividual(number="A1", birth_date=date(2018, 1, 1), castration_date=date(2019, 6, 1))
        assert is_active_at_date(ind, date(2020, 12, 30)) is False

    def test_death_date_before_target(self):
        from utils.genetics import is_active_at_date

        ind = MockIndividual(number="A1", birth_date=date(2018, 1, 1), death_date=date(2020, 6, 1))
        assert is_active_at_date(ind, date(2020, 12, 30)) is False

    def test_death_date_after_target(self):
        from utils.genetics import is_active_at_date

        ind = MockIndividual(number="A1", birth_date=date(2018, 1, 1), death_date=date(2021, 6, 1))
        assert is_active_at_date(ind, date(2020, 12, 30)) is True

    def test_death_note_year_before_target(self):
        from utils.genetics import is_active_at_date

        ind = MockIndividual(number="A1", birth_date=date(2015, 1, 1), death_note="2019 slakt")
        assert is_active_at_date(ind, date(2020, 12, 30)) is False

    def test_death_note_year_after_target(self):
        from utils.genetics import is_active_at_date

        ind = MockIndividual(number="A1", birth_date=date(2015, 1, 1), death_note="2022 ålder")
        assert is_active_at_date(ind, date(2020, 12, 30)) is True

    def test_death_note_no_year_max_age_exceeded(self):
        from utils.genetics import is_active_at_date

        ind = MockIndividual(number="A1", birth_date=date(2005, 1, 1), death_note="Ålder")
        # 2020 - 2005 = 15 years > 8 year max
        assert is_active_at_date(ind, date(2020, 12, 30)) is False

    def test_death_note_no_year_within_max_age(self):
        from utils.genetics import is_active_at_date

        ind = MockIndividual(number="A1", birth_date=date(2016, 1, 1), death_note="Låg död")
        # 2020 - 2016 = 4 years < 8 year max
        assert is_active_at_date(ind, date(2020, 12, 30)) is True

    def test_no_death_info_max_age_fallback(self):
        from utils.genetics import is_active_at_date

        ind = MockIndividual(number="A1", birth_date=date(2000, 1, 1))
        # 2020 - 2000 = 20 years > 8 year max
        assert is_active_at_date(ind, date(2020, 12, 30)) is False

    def test_no_death_info_within_max_age(self):
        from utils.genetics import is_active_at_date

        ind = MockIndividual(number="A1", birth_date=date(2017, 1, 1))
        assert is_active_at_date(ind, date(2020, 12, 30)) is True

    def test_herd_tracking_required_post_2005(self):
        from utils.genetics import is_active_at_date

        ind = MockIndividual(number="A1", birth_date=date(2018, 1, 1), id=42)
        tracking = {}  # empty = no tracking for this individual
        assert is_active_at_date(ind, date(2020, 12, 30), tracking_lookup=tracking) is False

    def test_herd_tracking_present_post_2005(self):
        from utils.genetics import is_active_at_date

        ind = MockIndividual(number="A1", birth_date=date(2018, 1, 1), id=42)
        tracking = {42: True}
        assert is_active_at_date(ind, date(2020, 12, 30), tracking_lookup=tracking) is True

    def test_herd_tracking_not_required_pre_2005(self):
        from utils.genetics import is_active_at_date

        ind = MockIndividual(number="A1", birth_date=date(2000, 1, 1), id=42)
        tracking = {}  # no tracking, but pre-2005 so not required
        # 2003 - 2000 = 3 years < 8 year max, should be active
        assert is_active_at_date(ind, date(2003, 12, 30), tracking_lookup=tracking) is True

    def test_digital_certificate_counts(self):
        from utils.genetics import is_active_at_date

        ind = MockIndividual(number="A1", birth_date=date(2018, 1, 1), certificate=None, digital_certificate=12345)
        assert is_active_at_date(ind, date(2020, 12, 30)) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
