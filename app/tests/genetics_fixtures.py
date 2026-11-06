"""Synthetic pedigrees and a dense oracle for the pedigree maths (test code only)."""

import numpy as np


def synthetic_pedigree(n_founders=40, cohorts=12, per_cohort=160, seed=7):
    """Founders, then overlapping cohorts bred from few sires of the last three cohorts.

    Returns (sire, dam, sex) in topological order. About 2 % of animals get an
    unknown dam so the one-parent D term is exercised.
    """
    rng = np.random.default_rng(seed)
    n = n_founders + cohorts * per_cohort
    sire = np.full(n, -1, dtype=np.int32)
    dam = np.full(n, -1, dtype=np.int32)
    sex = ["male" if i % 2 == 0 else "female" for i in range(n)]
    start = n_founders
    for _ in range(cohorts):
        pool = np.arange(max(0, start - 3 * per_cohort), start)
        males = pool[pool % 2 == 0]
        females = pool[pool % 2 == 1]
        few_sires = males[: max(4, len(males) // 5)]
        idx = np.arange(start, start + per_cohort)
        sire[idx] = rng.choice(few_sires, per_cohort)
        dam[idx] = rng.choice(females, per_cohort)
        dam[idx[rng.random(per_cohort) < 0.02]] = -1
        start += per_cohort
    return sire, dam, sex


def dense_a(sire, dam):
    """Numerator relationship matrix A = 2K by the tabular method (oracle)."""
    n = len(sire)
    A = np.zeros((n, n))
    for i in range(n):
        s, d = sire[i], dam[i]
        if i:
            row = np.zeros(i)
            if s >= 0:
                row += 0.5 * A[s, :i]
            if d >= 0:
                row += 0.5 * A[d, :i]
            A[i, :i] = row
            A[:i, i] = row
        A[i, i] = 1.0 + (0.5 * A[s, d] if s >= 0 and d >= 0 else 0.0)
    return A


def rows_from_arrays(sire, dam, sex):
    """DB-shaped rows (number, sex, father_number, mother_number) for build_snapshot."""
    ids = [f"X{i}" for i in range(len(sire))]
    rows = [
        {
            "number": ids[i],
            "sex": sex[i],
            "father_number": ids[sire[i]] if sire[i] >= 0 else None,
            "mother_number": ids[dam[i]] if dam[i] >= 0 else None,
        }
        for i in range(len(sire))
    ]
    return rows, ids
