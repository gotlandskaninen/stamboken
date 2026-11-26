"""Locks F, MK, mean MK, FGE and band cuts for a fixed synthetic pedigree."""

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from utils import pedigree_snapshot as ps

from tests.genetics_fixtures import rows_from_arrays, synthetic_pedigree

GOLDEN = Path(__file__).parent / "golden" / "genetics_golden.json"
EXACT = {"rtol": 0, "atol": 1e-12}


def _values():
    sire, dam, sex = synthetic_pedigree(seed=11)
    rows, ids = rows_from_arrays(sire, dam, sex)
    snap = ps.build_snapshot(1, rows, set(ids[-200:]), key=("golden",), seq=1)
    return {
        "ids": snap.ids,
        "F": [float(x) for x in snap.F],
        "mk": [float(x) for x in snap.mk],
        "mean_mk": snap.mean_mk,
        "fge": snap.fge,
        "band_cuts": list(snap.band_cuts),
    }


def test_golden():
    values = _values()
    if os.environ.get("REGENERATE_GOLDEN"):
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(values))
    expected = json.loads(GOLDEN.read_text())
    assert values["ids"] == expected["ids"]
    for name in ("F", "mk", "band_cuts"):
        np.testing.assert_allclose(values[name], expected[name], **EXACT)
    assert abs(values["mean_mk"] - expected["mean_mk"]) < 1e-12
    assert abs(values["fge"] - expected["fge"]) < 1e-9


_RESPONSES = """
import json
import utils.genetics_service as gs
from utils import pedigree_snapshot as ps
from tests.genetics_fixtures import rows_from_arrays, synthetic_pedigree

sire, dam, sex = synthetic_pedigree(n_founders=30, cohorts=4, per_cohort=60, seed=11)
rows, ids = rows_from_arrays(sire, dam, sex)
snap = ps.build_snapshot(1, rows, set(ids[-80:]), key=("k",), seq=1, recovery_eligible=set(ids[-160:-80]))
with ps.pinned(snap):
    responses = [gs.get_genetic_priorities(1, n_iterations=50), gs.get_founders_at_risk(1)]
    print(json.dumps(responses + [gs.get_breeding_suggestions(1)]))
"""


def test_shared_results_do_not_depend_on_the_process():
    """One worker fills the shared memo and every worker serves it for days: string hashing must not show."""
    outputs = {
        subprocess.run(
            [sys.executable, "-c", _RESPONSES],
            cwd=Path(__file__).parents[1],
            env={**os.environ, "PYTHONHASHSEED": str(seed)},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for seed in range(4)
    }
    assert len(outputs) == 1
    assert "Carries underrepresented founder" in outputs.pop()  # precondition: the reason this guards
