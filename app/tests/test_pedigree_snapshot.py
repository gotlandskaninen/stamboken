"""PedigreeSnapshot building and the per-worker cache."""

import threading
import time

import numpy as np
import pytest
import utils.pedigree_snapshot as ps

from tests.genetics_fixtures import dense_a, rows_from_arrays, synthetic_pedigree

ONE = [{"number": "A", "sex": None, "father_number": None, "mother_number": None}]


@pytest.fixture(autouse=True)
def isolated_source():
    """Save and restore the production hooks; leave no snapshots or builds behind."""
    saved = (ps._key_fn, ps._load_fn)
    ps.reset_for_tests()
    yield
    ps.reset_for_tests()
    ps._key_fn, ps._load_fn = saved


def test_build_matches_oracle():
    sire, dam, sex = synthetic_pedigree(n_founders=20, cohorts=4, per_cohort=80)
    rows, ids = rows_from_arrays(sire, dam, sex)
    snap = ps.build_snapshot(1, rows, set(ids[-120:]), key=("k",), seq=1)
    K = dense_a(sire, dam) / 2
    R = [ids.index(x) for x in snap.ref_ids]
    for number in ids[-120:]:
        assert abs(snap.mk[snap.index[number]] - K[ids.index(number), R].mean()) < 1e-12
    assert abs(snap.mean_mk - K[np.ix_(R, R)].mean()) < 1e-12
    assert abs(snap.fge - 1 / (2 * snap.mean_mk)) < 1e-12
    K_rr, ref_ids = snap.reference_kinship()
    assert ref_ids == snap.ref_ids and K_rr.shape == (120, 120)


def test_memo_is_reentrant():
    snap = ps.build_snapshot(1, ONE, {"A"}, key=("k",), seq=1)
    assert snap.memo("outer", lambda: snap.memo("inner", lambda: 41) + 1) == 42


def _hold_slow_memo(snap, name):
    """Start a thread inside a compute of `name` that waits until the returned event is set."""
    entered, release = threading.Event(), threading.Event()

    def slow():
        entered.set()
        release.wait(10)
        return "slow"

    t = threading.Thread(target=snap.memo, args=(name, slow), daemon=True)
    t.start()
    assert entered.wait(5)
    return t, release


def _returns_within(fn, timeout=1.0):
    out = []
    t = threading.Thread(target=lambda: out.append(fn()), daemon=True)
    t.start()
    t.join(timeout)
    return out


def test_memo_hit_does_not_wait_for_another_names_compute():
    snap = ps.build_snapshot(1, ONE, {"A"}, key=("k",), seq=1)
    snap.memo("hit", lambda: 1)
    slow, release = _hold_slow_memo(snap, "slow")
    try:
        assert _returns_within(lambda: snap.memo("hit", lambda: 2)) == [1]
        assert _returns_within(lambda: snap.memo("other", lambda: 3)) == [3]
    finally:
        release.set()
        slow.join(5)
    assert snap.memo("slow", lambda: "again") == "slow"


def test_same_name_is_computed_once_across_threads():
    snap = ps.build_snapshot(1, ONE, {"A"}, key=("k",), seq=1)
    calls = []
    gate = threading.Event()

    def compute():
        calls.append(1)
        gate.wait(5)
        return object()

    results = []
    threads = [threading.Thread(target=lambda: results.append(snap.memo("same", compute))) for _ in range(4)]
    for t in threads:
        t.start()
    time.sleep(0.2)
    gate.set()
    for t in threads:
        t.join(5)
    assert len(calls) == 1
    assert len(results) == 4 and all(r is results[0] for r in results)


def test_parent_outside_the_loaded_pedigree_is_unknown():
    rows = [
        {"number": "A", "sex": "male", "father_number": None, "mother_number": None},
        {"number": "B", "sex": "female", "father_number": "A", "mother_number": "GONE"},
    ]
    snap = ps.build_snapshot(1, rows, {"A", "B"}, key=("k",), seq=1)
    b = snap.index["B"]
    assert snap.dam[b] == -1 and snap.sire[b] == snap.index["A"]
    assert snap.completeness[b] < 0.8


def test_existing_cycle_is_broken_and_built():
    rows = [
        {"number": "A", "sex": "male", "father_number": "B", "mother_number": None},
        {"number": "B", "sex": "male", "father_number": "A", "mother_number": None},
    ]
    snap = ps.build_snapshot(1, rows, {"A", "B"}, key=("k",), seq=1)
    assert len(snap.ids) == 2 and np.isfinite(snap.mk).all()


def test_cycle_break_does_not_depend_on_row_order():
    """A and B are each other's sire, A has a known dam: dropping A→B or B→A gives different numbers."""

    def row(number, father=None, mother=None):
        return {"number": number, "sex": None, "father_number": father, "mother_number": mother}

    rows = [row("A", "B", "D"), row("B", "A"), row("D"), row("E"), row("K", "A", "E"), row("L", "B", "D")]
    members = {"A", "B", "D", "K", "L"}
    one = ps.build_snapshot(1, rows, members, key=("k",), seq=1)
    other = ps.build_snapshot(1, list(reversed(rows)), members, key=("k",), seq=1)

    assert np.isfinite(one.mean_mk)
    np.testing.assert_allclose(other.mean_mk, one.mean_mk, rtol=0, atol=1e-12)
    np.testing.assert_allclose(other.fge, one.fge, rtol=0, atol=1e-12)
    for number in one.ids:
        np.testing.assert_allclose(other.F[other.index[number]], one.F[one.index[number]], rtol=0, atol=1e-12)
        np.testing.assert_allclose(other.mk[other.index[number]], one.mk[one.index[number]], rtol=0, atol=1e-12)


def test_empty_and_small_reference():
    rows = [{"number": f"N{i}", "sex": None, "father_number": None, "mother_number": None} for i in range(5)]
    empty = ps.build_snapshot(1, rows, set(), key=("k",), seq=1)
    assert empty.mk is None and empty.mean_mk is None and empty.fge is None and empty.band_cuts is None
    assert empty.reference_kinship()[1] == []
    small = ps.build_snapshot(1, rows, {"N0", "N1"}, key=("k",), seq=1)
    assert small.mk is not None and small.band_cuts is None


def test_concurrent_cold_calls_build_once():
    calls = []

    def load(gb):
        calls.append(gb)
        time.sleep(0.2)
        return ("v1",), ONE, {"A"}

    ps.set_source(key_fn=lambda gb: ("v1",), load_fn=load)
    threads = [threading.Thread(target=ps.get_snapshot, args=(7,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls == [7]


def test_an_older_build_never_replaces_a_newer_one():
    newer = ps.build_snapshot(3, ONE, {"A"}, key=("v2",), seq=10)
    older = ps.build_snapshot(3, ONE, {"A"}, key=("v1",), seq=9)
    ps._publish(newer)
    ps._publish(older)
    assert ps._snapshots[3] is newer


def test_failed_rebuild_keeps_serving_the_previous_snapshot():
    key = {"k": ("v1",)}

    def load(gb):
        if key["k"] == ("v2",):
            raise RuntimeError("boom")
        return key["k"], ONE, {"A"}

    ps.set_source(key_fn=lambda gb: key["k"], load_fn=load)
    first = ps.get_snapshot(3)
    key["k"] = ("v2",)
    assert ps.get_snapshot(3) is first  # stale while the rebuild runs
    ps.wait_for_builds(3, timeout=5)
    assert ps.get_snapshot(3) is first  # and still after it failed


def test_failed_cold_build_returns_none_and_publishes_nothing():
    def load(gb):
        raise RuntimeError("boom")

    ps.set_source(key_fn=lambda gb: ("v1",), load_fn=load)
    assert ps.get_snapshot(5) is None
    assert 5 not in ps._snapshots


def test_stale_while_revalidate_serves_old_then_new():
    built = []
    gate = threading.Event()
    key = {"k": (1,)}

    def load(gb):
        built.append(key["k"])
        if key["k"] == (2,):
            gate.wait(5)
        return key["k"], ONE, {"A"}

    ps.set_source(key_fn=lambda gb: key["k"], load_fn=load)
    first = ps.get_snapshot(9)  # cold: waits for the one build
    key["k"] = (2,)
    snap, stale = ps.snapshot_status(9)
    assert snap is first and stale
    for _ in range(5):
        assert ps.get_snapshot(9) is first  # no second build while one is in flight
    gate.set()
    ps.wait_for_builds(9, timeout=5)
    assert built == [(1,), (2,)] and ps.get_snapshot(9).key == (2,)


def test_failed_build_keeps_last_good_snapshot_and_cools_down():
    state = {"fail": False, "k": (1,), "calls": 0}

    def load(gb):
        state["calls"] += 1
        if state["fail"]:
            raise RuntimeError("db down")
        return state["k"], ONE, {"A"}

    ps.set_source(key_fn=lambda gb: state["k"], load_fn=load)
    good = ps.get_snapshot(4)
    state.update(fail=True, k=(2,))
    ps.mark_stale(4)
    ps.wait_for_builds(4, timeout=5)
    calls = state["calls"]
    for _ in range(10):
        snap, stale = ps.snapshot_status(4)
        assert snap is good and stale
    ps.wait_for_builds(4, timeout=5)
    assert state["calls"] == calls  # cooldown: no build storm


def test_pinned_snapshot_is_used_by_nested_reads():
    key = {"k": (1,)}
    ps.set_source(key_fn=lambda gb: key["k"], load_fn=lambda gb: (key["k"], ONE, {"A"}))
    snap = ps.get_snapshot(5)
    key["k"] = (2,)
    with ps.pinned(snap):
        assert ps.get_snapshot(5) is snap
        assert ps.snapshot_status(5) == (snap, False)


def test_new_key_serves_stale_then_new():
    key = {"k": ("v1",)}
    ps.set_source(key_fn=lambda gb: key["k"], load_fn=lambda gb: (key["k"], ONE, {"A"}))
    first = ps.get_snapshot(3)
    key["k"] = ("v2",)
    assert ps.get_snapshot(3) is first
    ps.wait_for_builds(3, timeout=5)
    second = ps.get_snapshot(3)
    assert second.key == ("v2",) and second.seq > first.seq


def test_failing_key_read_serves_the_retained_snapshot_without_a_build():
    """A transient version-read failure must not hide the last good snapshot."""
    state = {"fail": False, "loads": 0}

    def key_fn(gb):
        if state["fail"]:
            raise RuntimeError("version read failed")
        return ("v1",)

    def load(gb):
        state["loads"] += 1
        return ("v1",), ONE, {"A"}

    ps.set_source(key_fn=key_fn, load_fn=load)
    retained = ps.get_snapshot(6)
    state["fail"] = True
    assert ps.snapshot_status(6) == (retained, True)
    ps.wait_for_builds(6, timeout=5)
    assert state["loads"] == 1  # no rebuild scheduled on an unreadable key


def test_failing_key_read_without_a_retained_snapshot_raises():
    def key_fn(gb):
        raise RuntimeError("version read failed")

    ps.set_source(key_fn=key_fn, load_fn=lambda gb: (("v1",), ONE, {"A"}))
    with pytest.raises(RuntimeError):
        ps.snapshot_status(6)


def _counting_source(key):
    loads = []

    def load(gb):
        loads.append(key["k"])
        return key["k"], ONE, {"A"}

    ps.set_source(key_fn=lambda gb: key["k"], load_fn=load)
    return loads


def test_mark_stale_skips_the_build_when_the_snapshot_already_has_the_current_key():
    key = {"k": ("v1",)}
    loads = _counting_source(key)
    first = ps.get_snapshot(6)
    ps.mark_stale(6)  # e.g. the pub/sub hint for a write the reader already rebuilt for
    ps.wait_for_builds(6, timeout=5)
    assert loads == [("v1",)]
    assert ps.get_snapshot(6) is first


def test_mark_stale_builds_once_when_the_key_moved():
    key = {"k": ("v1",)}
    loads = _counting_source(key)
    ps.get_snapshot(6)
    key["k"] = ("v2",)
    ps.mark_stale(6)
    ps.wait_for_builds(6, timeout=5)
    assert loads == [("v1",), ("v2",)]
    assert ps.get_snapshot(6).key == ("v2",)


def test_mark_stale_builds_when_the_key_read_fails():
    key = {"k": ("v1",)}
    loads = _counting_source(key)
    ps.get_snapshot(6)

    def failing_key(gb):
        raise RuntimeError("db down")

    ps._key_fn = failing_key
    ps.mark_stale(6)
    ps.wait_for_builds(6, timeout=5)
    assert loads == [("v1",), ("v1",)]
