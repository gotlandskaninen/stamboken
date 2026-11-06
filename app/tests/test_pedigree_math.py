"""Pedigree maths against a dense oracle."""

import numpy as np
import pytest
from utils.genetics import (
    Individual,
    _calculate_inbreeding_henderson,
    calculate_generation_numbers,
    calculate_kinship_matrix,
    calculate_pedigree_completeness,
)
from utils.pedigree_math import (
    BANDS,
    a_times,
    ancestor_completeness,
    band_cuts,
    band_for,
    completeness_scalar,
    generation_numbers,
    mk_to_reference,
    reference_block,
)

from tests.genetics_fixtures import dense_a, synthetic_pedigree

EXACT = {"rtol": 0, "atol": 1e-12}


@pytest.fixture(scope="module")
def ped():
    sire, dam, sex = synthetic_pedigree()
    F = _calculate_inbreeding_henderson(len(sire), sire, dam)
    return sire, dam, sex, F, dense_a(sire, dam)


def _individuals(sire, dam):
    ids = [f"X{i}" for i in range(len(sire))]
    return [
        Individual(
            id=ids[i],
            sire_id=ids[sire[i]] if sire[i] >= 0 else None,
            dam_id=ids[dam[i]] if dam[i] >= 0 else None,
        )
        for i in range(len(sire))
    ]


def test_dense_oracle_matches_existing_kinship_matrix():
    sire, dam, _ = synthetic_pedigree(n_founders=10, cohorts=3, per_cohort=60, seed=3)
    K_old, ids = calculate_kinship_matrix(_individuals(sire, dam), active_only=False)
    order = [int(x[1:]) for x in ids]
    np.testing.assert_allclose(K_old, dense_a(sire, dam)[np.ix_(order, order)] / 2, **EXACT)


def test_a_times_matches_dense_for_vector_and_matrix(ped):
    sire, dam, _, F, A = ped
    rng = np.random.default_rng(1)
    w = rng.random(len(sire))
    w0 = w.copy()
    got = a_times(sire, dam, F, w)
    assert np.isfinite(got).all()
    np.testing.assert_allclose(got, A @ w, **EXACT)
    np.testing.assert_array_equal(w, w0)  # input untouched
    W = rng.random((len(sire), 5))
    np.testing.assert_allclose(a_times(sire, dam, F, W), A @ W, **EXACT)


def test_a_times_two_unrelated_founders():
    sire = np.array([-1, -1], dtype=np.int32)
    dam = np.array([-1, -1], dtype=np.int32)
    np.testing.assert_allclose(a_times(sire, dam, np.zeros(2), np.array([0.0, 1.0])) / 2, [0.0, 0.5], **EXACT)


def test_one_known_inbred_parent():
    # 0,1 founders; 2 = 0x1; 3 = 2x2 (F3 = 0.5); 4 has only parent 3.
    sire = np.array([-1, -1, 0, 2, 3], dtype=np.int32)
    dam = np.array([-1, -1, 1, 2, -1], dtype=np.int32)
    F = _calculate_inbreeding_henderson(5, sire, dam)
    np.testing.assert_allclose(a_times(sire, dam, F, np.ones(5)), dense_a(sire, dam) @ np.ones(5), **EXACT)


def test_mk_members_and_as_if_member(ped):
    sire, dam, _, F, A = ped
    K = A / 2
    ref = np.zeros(len(sire), dtype=bool)
    ref[-300:] = True
    mk, mk_sum = mk_to_reference(sire, dam, F, ref)
    R = np.flatnonzero(ref)
    np.testing.assert_allclose(mk[R], K[np.ix_(R, R)].mean(axis=0), **EXACT)
    outsider = 5
    with_it = np.append(R, outsider)
    assert abs(mk[outsider] - K[np.ix_(with_it, with_it)].mean(axis=0)[-1]) < 1e-12
    np.testing.assert_allclose(mk_sum, K[:, R].sum(axis=1), **EXACT)


def test_mk_empty_reference_is_none(ped):
    sire, dam, _, F, _ = ped
    assert mk_to_reference(sire, dam, F, np.zeros(len(sire), dtype=bool)) is None


def test_generation_numbers_identical_to_recursive(ped):
    sire, dam, *_ = ped
    old = calculate_generation_numbers(_individuals(sire, dam))
    mx, full, eq = generation_numbers(sire, dam)
    for i in range(len(sire)):
        g = old[f"X{i}"]
        assert (mx[i], full[i]) == (g["max_gen"], g["full_gen"])
        assert abs(eq[i] - g["equiv_gen"]) < 1e-12


def test_completeness_identical_to_recursive(ped):
    sire, dam, *_ = ped
    old = calculate_pedigree_completeness(_individuals(sire, dam), max_generations=5)
    pci = ancestor_completeness(sire, dam, 5)
    for i in range(len(sire)):
        np.testing.assert_allclose(pci[i], [old[f"X{i}"][g] for g in range(1, 6)], **EXACT)


def test_completeness_scalar_crosses_eighty_percent():
    pci = np.array([[1.0, 1.0, 1.0, 1.0, 24 / 32]])  # 54/62 ≈ 0.871
    assert abs(completeness_scalar(pci)[0] - 54 / 62) < 1e-12
    assert completeness_scalar(np.array([[1.0, 1.0, 0, 0, 0]]))[0] < 0.8  # 6/62


@pytest.mark.parametrize("n,expect_none", [(0, True), (1, True), (9, True), (10, False)])
def test_band_cuts_need_ten(n, expect_none):
    assert (band_cuts(np.linspace(0.01, 0.05, n)) is None) == expect_none


def test_bands_quintiles_without_ties():
    values = np.linspace(0.0, 1.0, 101)
    cuts = band_cuts(values)
    counts = dict.fromkeys(BANDS, 0)
    for v in values:
        counts[band_for(v, cuts)] += 1
    assert all(18 <= c <= 22 for c in counts.values()), counts


def test_bands_all_ties_get_one_band():
    assert band_for(0.02, band_cuts(np.full(50, 0.02))) == "A"


def test_reference_block_matches_dense(ped):
    sire, dam, _, F, A = ped
    R = np.arange(len(sire) - 300, len(sire))
    np.testing.assert_allclose(reference_block(sire, dam, F, R, block=64), A[np.ix_(R, R)] / 2, **EXACT)
