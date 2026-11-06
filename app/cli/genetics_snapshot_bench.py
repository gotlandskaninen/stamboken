"""Cold-build time and memory for one genebank, in a fresh process. Prints aggregates only.

python -m cli.genetics_snapshot_bench <genebank_id> [--trace]

Without --trace: build/block time and RSS. With --trace: traced peak and retained
memory (tracemalloc slows the build roughly tenfold, so its times are not usable).
"""

import resource
import sys
import time
import tracemalloc

import numpy as np


def _rss_mb():
    """Current resident set size in MB (not the lifetime high-water mark)."""
    with open("/proc/self/statm") as f:
        pages = int(f.read().split()[1])
    return pages * resource.getpagesize() / 1e6


def main(genebank_id, trace=False):
    import utils.genetics_service as gs  # imported first so the idle baseline includes the modules

    rss_idle = _rss_mb()
    if trace:
        tracemalloc.start()
    t0 = time.perf_counter()
    snap = gs.snapshot(genebank_id)
    if not snap.ids or not snap.n_ref:
        print(f"gb={genebank_id} skipped: no animals or empty reference population")
        return
    t1 = time.perf_counter()
    snap.reference_kinship()
    t2 = time.perf_counter()
    for warm in (
        gs.get_inbreeding,
        gs.get_mean_kinship,
        gs.get_kinship_matrix,
        gs.get_generation_numbers,
        gs.get_pedigree_completeness,
        gs.get_population_metrics,
        gs.get_founder_statistics,
        gs.get_gene_drop_statistics,
        gs.get_genetic_priorities,
        gs.get_breeding_suggestions,
        gs.get_founders_at_risk,
    ):
        warm(genebank_id)  # every consumer the dashboard warms, so "retained" is the real footprint
    retained, peak = tracemalloc.get_traced_memory() if trace else (0, 0)
    rss_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # process high-water mark, MB
    members = gs.reference_population_numbers(genebank_id)
    print(
        f"gb={genebank_id} n={len(snap.ids)} ref={snap.n_ref} build={t1 - t0:.2f}s block={t2 - t1:.2f}s "
        f"rss_peak_over_idle={rss_peak - rss_idle:.0f}MB rss_now_over_idle={_rss_mb() - rss_idle:.0f}MB "
        + (f"traced_peak={peak / 1e6:.0f}MB retained_warm={retained / 1e6:.1f}MB " if trace else "")
        + f"members_equal={set(snap.ref_ids) == members} "
        f"mean_mk={snap.mean_mk:.4f} fge={snap.fge:.2f} "
        f"mk_p10_p90={np.round(np.percentile(snap.mk[snap.ref_mask], [10, 90]), 4).tolist()}"
    )


if __name__ == "__main__":
    main(int(sys.argv[1]), trace="--trace" in sys.argv[2:])
