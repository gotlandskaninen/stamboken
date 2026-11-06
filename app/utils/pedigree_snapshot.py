"""One immutable pedigree snapshot per genebank and worker.

The service supplies two hooks: key_fn(genebank_id) returns the key of the
current state (cheap, read per request), load_fn(genebank_id) returns
(key, rows, member_numbers[, recovery_eligible]) read consistently. Keys are compared for equality
only; a per-process build sequence decides which build wins.

Stale-while-revalidate: a reader whose key moved on gets the
previous snapshot at once while one background build per genebank runs in a
small executor (own thread, own database connection). Only a cold start
waits. A failed build keeps the last good snapshot and cools down for
FAILURE_COOLDOWN_SECONDS instead of retrying on every request. A request can
pin the snapshot it started with so nested reads agree.
"""

import contextlib
import contextvars
import itertools
import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from utils.genetics import Individual, _calculate_inbreeding_henderson, topological_sort_pedigree
from utils.pedigree_math import (
    ancestor_completeness,
    band_cuts,
    completeness_scalar,
    generation_numbers,
    mk_to_reference,
    reference_block,
)

logger = logging.getLogger("herdbook.genetics")

_MISSING = object()


@dataclass(frozen=True, eq=False)
class PedigreeSnapshot:
    genebank_id: int
    key: tuple
    seq: int
    ids: list
    index: dict
    sire: np.ndarray
    dam: np.ndarray
    sex: list
    individuals: list
    F: np.ndarray
    gen_max: np.ndarray
    gen_full: np.ndarray
    gen_equiv: np.ndarray
    pci: np.ndarray
    completeness: np.ndarray
    ref_mask: np.ndarray
    mk: np.ndarray | None
    mean_mk: float | None
    gd: float | None
    fge: float | None
    band_cuts: tuple | None
    recovery_eligible: frozenset = frozenset()  # numbers plausibly alive and breedable, read with the pedigree
    derived: dict = field(default_factory=dict, repr=False)
    _guard: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _name_locks: dict = field(default_factory=dict, repr=False)

    @property
    def n_ref(self):
        return int(self.ref_mask.sum())

    @property
    def ref_ids(self):
        return [self.ids[i] for i in np.flatnonzero(self.ref_mask)]

    def memo(self, name, compute):
        """Per-snapshot memo, computed once per name.

        A hit never takes a lock. A miss locks only its own name, so a slow
        compute (gene drop) does not stall other names. Each lock is an RLock,
        so a memo may build on other memos; no memo nests in a cycle today
        (two names each waiting on the other would deadlock).
        """
        value = self.derived.get(name, _MISSING)
        if value is not _MISSING:
            return value
        with self._guard:
            lock = self._name_locks.setdefault(name, threading.RLock())
        with lock:
            value = self.derived.get(name, _MISSING)
            if value is _MISSING:
                value = self.derived[name] = compute()
            return value

    def reference_kinship(self):
        """(K_RR, ref_ids): dense kinship over the reference population."""

        def compute():
            ref_idx = np.flatnonzero(self.ref_mask)
            if len(ref_idx) == 0:
                return np.zeros((0, 0)), []
            return reference_block(self.sire, self.dam, self.F, ref_idx), self.ref_ids

        return self.memo("reference_kinship", compute)


def build_snapshot(genebank_id, rows, members, key, seq, recovery_eligible=frozenset()):
    raw = [
        Individual(
            id=row["number"],
            sire_id=row.get("father_number"),
            dam_id=row.get("mother_number"),
            is_active=row["number"] in members,
            sex=row.get("sex"),
        )
        for row in sorted(rows, key=lambda r: r["number"])
    ]
    # Sorted input: which cycle link is dropped never depends on the caller's row order.
    ordered, index = topological_sort_pedigree(raw)  # breaks and logs cycles
    n = len(ordered)
    sire = np.full(n, -1, dtype=np.int32)
    dam = np.full(n, -1, dtype=np.int32)
    for i, ind in enumerate(ordered):
        if ind.sire_id in index:
            sire[i] = index[ind.sire_id]
        if ind.dam_id in index:
            dam[i] = index[ind.dam_id]
    F = _calculate_inbreeding_henderson(n, sire, dam)
    gen_max, gen_full, gen_equiv = generation_numbers(sire, dam)
    pci = ancestor_completeness(sire, dam, 5)
    ref_mask = np.array([ind.is_active for ind in ordered], dtype=bool)
    result = mk_to_reference(sire, dam, F, ref_mask) if n else None
    if result is None:
        mk = mean_mk = gd = fge = cuts = None
    else:
        mk = result[0]
        mean_mk = float(mk[ref_mask].mean())
        gd = 1.0 - mean_mk
        fge = 1.0 / (2.0 * mean_mk)
        cuts = band_cuts(mk[ref_mask])
    return PedigreeSnapshot(
        genebank_id=genebank_id,
        key=key,
        seq=seq,
        ids=[ind.id for ind in ordered],
        index=index,
        sire=sire,
        dam=dam,
        sex=[ind.sex for ind in ordered],
        individuals=ordered,
        F=F,
        gen_max=gen_max,
        gen_full=gen_full,
        gen_equiv=gen_equiv,
        pci=pci,
        completeness=completeness_scalar(pci),
        ref_mask=ref_mask,
        mk=mk,
        mean_mk=mean_mk,
        gd=gd,
        fge=fge,
        band_cuts=cuts,
        recovery_eligible=frozenset(recovery_eligible),
    )


FAILURE_COOLDOWN_SECONDS = 30

_snapshots = {}
_locks = defaultdict(threading.Lock)
_seq = itertools.count(1)
_key_fn = None
_load_fn = None
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pedigree-build")
_inflight = {}  # genebank_id -> Future of the latest build
_failed_at = {}  # genebank_id -> monotonic time of the last failed build
_pinned = contextvars.ContextVar("pinned_snapshots", default=None)  # genebank_id -> snapshot; never mutated


def set_source(key_fn, load_fn):
    global _key_fn, _load_fn  # pylint: disable=global-statement
    _key_fn, _load_fn = key_fn, load_fn


@contextlib.contextmanager
def pinned(snap):
    """Serve `snap` for its genebank to every read in this context (one request, one snapshot)."""
    token = _pinned.set({**(_pinned.get() or {}), snap.genebank_id: snap})
    try:
        yield snap
    finally:
        _pinned.reset(token)


def _publish(snap):
    current = _snapshots.get(snap.genebank_id)
    if current is None or snap.seq > current.seq:
        _snapshots[snap.genebank_id] = snap


def _build(genebank_id):
    seq = next(_seq)
    key, rows, members, *eligible = _load_fn(genebank_id)
    return build_snapshot(genebank_id, rows, members, key, seq, *eligible)


def _close_db_connection():
    """Close the build thread's connection; never raises, so it cannot mask a build error."""
    try:
        from utils.database import DB_PROXY  # pylint: disable=import-outside-toplevel

        if not DB_PROXY.is_closed():
            DB_PROXY.close()
    except Exception:  # no database configured (pure unit tests), or already gone
        logger.debug("Closing the snapshot build connection failed", exc_info=True)


def _build_job(genebank_id):
    try:
        new = _build(genebank_id)
    except Exception:
        logger.exception("Building the pedigree snapshot for genebank %s failed", genebank_id)
        _failed_at[genebank_id] = time.monotonic()
        return None
    finally:
        _close_db_connection()
    _failed_at.pop(genebank_id, None)
    with _locks[genebank_id]:
        _publish(new)
    return new


def _schedule(genebank_id, key=None):
    """Start a build unless one is running, the snapshot already has `key`, or a failure is cooling down.

    Returns the latest build's Future (possibly done), or None when nothing was ever started.
    """
    with _locks[genebank_id]:
        fut = _inflight.get(genebank_id)
        if fut is not None and not fut.done():
            return fut
        current = _snapshots.get(genebank_id)
        if key is not None and current is not None and current.key == key:
            return fut  # a build finished since the caller looked
        failed = _failed_at.get(genebank_id)
        if failed is not None and time.monotonic() - failed < FAILURE_COOLDOWN_SECONDS:
            return fut  # cooling down after a failure: no build storm
        fut = _executor.submit(_build_job, genebank_id)
        _inflight[genebank_id] = fut
        return fut


def snapshot_status(genebank_id):
    """(snapshot | None, stale): the current snapshot, or the previous one while a rebuild runs."""
    pinned_snap = (_pinned.get() or {}).get(genebank_id)
    if pinned_snap is not None:
        return pinned_snap, False
    try:
        key = _key_fn(genebank_id)
    except Exception:
        snap = _snapshots.get(genebank_id)
        if snap is None:
            raise  # cold start: nothing to fall back on
        logger.warning("Snapshot key read failed for genebank %s; serving the retained one", genebank_id, exc_info=True)
        return snap, True  # no rebuild: without a key there is nothing to compare against
    snap = _snapshots.get(genebank_id)
    if snap is not None and snap.key == key:
        return snap, False
    fut = _schedule(genebank_id, key)
    if snap is not None:
        return snap, True
    if fut is not None:
        fut.result()  # cold start: wait for the one build (it runs on its own connection)
    snap = _snapshots.get(genebank_id)
    return snap, snap is not None and snap.key != key


def get_snapshot(genebank_id):
    return snapshot_status(genebank_id)[0]


def mark_stale(genebank_id=None):
    """Rebuild in the background (all cached genebanks when None); readers keep the old snapshot meanwhile.

    Skips a genebank whose retained snapshot already has the current key (a reader or the
    leader's poller got there first); when the key cannot be read it rebuilds anyway.
    """
    for gb in [genebank_id] if genebank_id is not None else list(_snapshots):
        try:
            key = _key_fn(gb)
        except Exception:  # pylint: disable=broad-except
            logger.debug("Snapshot key read failed for genebank %s; rebuilding anyway", gb, exc_info=True)
            key = None
        _failed_at.pop(gb, None)
        _schedule(gb, key)


def wait_for_builds(genebank_id, timeout=None):
    """Wait for the genebank's running build; True if there was one to wait for."""
    fut = _inflight.get(genebank_id)
    if fut is None:
        return False
    fut.result(timeout=timeout)
    return True


def reset_for_tests():
    """Tests reuse genebank ids (TRUNCATE … RESTART IDENTITY): drain builds, start clean."""
    for fut in list(_inflight.values()):
        try:
            fut.result(timeout=30)
        except Exception:  # pylint: disable=broad-except
            logger.debug("A drained snapshot build failed", exc_info=True)
    _inflight.clear()
    _failed_at.clear()
    _snapshots.clear()
