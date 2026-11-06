"""Pedigree maths on index arrays.

Parents are int32 indices in topological order (parents before offspring);
-1 means unknown or not loaded. Nothing here touches the database.

Colleau (2002): with A = 2K = T·D·Tᵀ, T = (I − P)⁻¹, A·w costs two linear
passes over the pedigree instead of a dense matrix.
"""

import numpy as np

BANDS = ("A", "B", "C", "D", "E")
MIN_BAND_REFERENCE = 10


def mendelian_d(sire, dam, F):
    """Within-family variance D: 1 founder, 0.75 − 0.25·F_p one parent, 0.5 − 0.25·(F_s+F_d) two."""
    s_known = sire >= 0
    d_known = dam >= 0
    fs = np.where(s_known, F[np.maximum(sire, 0)], 0.0)
    fd = np.where(d_known, F[np.maximum(dam, 0)], 0.0)
    D = np.ones(len(sire))
    both = s_known & d_known
    one = s_known ^ d_known
    D[both] = 0.5 - 0.25 * (fs[both] + fd[both])
    D[one] = 0.75 - 0.25 * (fs + fd)[one]
    return D


def a_times(sire, dam, F, w):
    """A·w for a vector (n,) or a matrix (n, k), A = 2K. `w` is not modified."""
    w = np.array(w, dtype=float, copy=True)
    D = mendelian_d(sire, dam, F)
    s = sire.tolist()
    d = dam.tolist()
    n = len(s)
    if w.ndim == 1:
        v = w.tolist()
        for i in range(n - 1, -1, -1):  # v = Tᵀw
            half = 0.5 * v[i]
            if half:
                if s[i] >= 0:
                    v[s[i]] += half
                if d[i] >= 0:
                    v[d[i]] += half
        x = (np.array(v) * D).tolist()
        for i in range(n):  # x = T·(D∘v); parents are already final
            xs = x[s[i]] if s[i] >= 0 else 0.0
            xd = x[d[i]] if d[i] >= 0 else 0.0
            x[i] += 0.5 * (xs + xd)
        return np.array(x)
    v = w
    for i in range(n - 1, -1, -1):
        if s[i] >= 0:
            v[s[i]] += 0.5 * v[i]
        if d[i] >= 0:
            v[d[i]] += 0.5 * v[i]
    x = v * D[:, None]
    for i in range(n):
        if s[i] >= 0:
            x[i] += 0.5 * x[s[i]]
        if d[i] >= 0:
            x[i] += 0.5 * x[d[i]]
    return x


def mk_to_reference(sire, dam, F, ref_mask):
    """(mk, mk_sum) for every animal, or None for an empty reference.

    mk_sum[i] = Σ_{j∈R} K_ij. Members: mk_sum/n_R (self term included, as R's
    colMeans and PMx). Others: as if added to R, (mk_sum + K_ii)/(n_R + 1).
    """
    n_r = int(ref_mask.sum())
    if n_r == 0:
        return None
    mk_sum = a_times(sire, dam, F, ref_mask.astype(float)) / 2.0
    k_ii = 0.5 * (1.0 + F)
    mk = np.where(ref_mask, mk_sum / n_r, (mk_sum + k_ii) / (n_r + 1))
    return mk, mk_sum


def generation_numbers(sire, dam):
    """(max_gen, full_gen, equiv_gen) in one forward pass; equals calculate_generation_numbers."""
    s = sire.tolist()
    d = dam.tolist()
    n = len(s)
    mx = [0] * n
    full = [0] * n
    eq = [0.0] * n
    for i in range(n):
        si, di = s[i], d[i]
        mx[i] = max(mx[si] + 1 if si >= 0 else 0, mx[di] + 1 if di >= 0 else 0)
        full[i] = min(full[si], full[di]) + 1 if si >= 0 and di >= 0 else 0
        eq[i] = (0.5 * (1.0 + eq[si]) if si >= 0 else 0.0) + (0.5 * (1.0 + eq[di]) if di >= 0 else 0.0)
    return np.array(mx, dtype=np.int32), np.array(full, dtype=np.int32), np.array(eq)


def ancestor_completeness(sire, dam, generations=5):
    """Share of known ancestors per generation 1..generations, shape (n, generations)."""
    s_known = sire >= 0
    d_known = dam >= 0
    s_idx = np.maximum(sire, 0)
    d_idx = np.maximum(dam, 0)
    known_prev = np.ones(len(sire))  # generation 0: the animal itself
    out = np.zeros((len(sire), generations))
    for g in range(1, generations + 1):
        known = np.where(s_known, known_prev[s_idx], 0.0) + np.where(d_known, known_prev[d_idx], 0.0)
        out[:, g - 1] = known / 2**g
        known_prev = known
    return out


def completeness_scalar(pci):
    """Known ancestor positions over generations 1..k divided by all positions (62 for k = 5)."""
    weights = np.array([2**g for g in range(1, pci.shape[1] + 1)], dtype=float)
    return (pci * weights).sum(axis=1) / weights.sum()


def band_cuts(mk_ref):
    """20/40/60/80th percentiles of the members' MK, or None for fewer than 10 members."""
    if len(mk_ref) < MIN_BAND_REFERENCE:
        return None
    return tuple(float(c) for c in np.percentile(mk_ref, [20, 40, 60, 80]))


def band_for(mk, cuts):
    """A for mk ≤ q20, …, E above q80."""
    return BANDS[sum(1 for c in cuts if mk > c)]


def reference_block(sire, dam, F, ref_idx, block=128):
    """Dense K over the reference animals (ref_idx order), block by block."""
    n = len(sire)
    m = len(ref_idx)
    K = np.empty((m, m))
    for start in range(0, m, block):
        cols = ref_idx[start : start + block]
        W = np.zeros((n, len(cols)))
        W[cols, np.arange(len(cols))] = 1.0
        K[:, start : start + len(cols)] = a_times(sire, dam, F, W)[ref_idx] / 2.0
    return K
