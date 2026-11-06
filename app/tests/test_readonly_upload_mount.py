"""
The demo API (api-test) runs with ./uppladdningar mounted read-only.
It must still start: neither the certificate service nor the app module may
need to create directories there. Each case runs in a subprocess where
os.makedirs fails with EROFS below uppladdningar, as on a fresh host dir.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent

# The mount point itself exists (makedirs(exist_ok=True) on it succeeds); anything below it does not.
_READ_ONLY_MAKEDIRS = textwrap.dedent(
    """
    import errno, os
    _makedirs = os.makedirs
    UP = {up!r}

    def makedirs(name, *args, **kwargs):
        if os.path.abspath(name).startswith(UP + os.sep):
            raise OSError(errno.EROFS, "Read-only file system", str(name))
        return _makedirs(name, *args, **kwargs)

    os.makedirs = makedirs
    """
).format(up=str(APP_DIR / "uppladdningar"))


@pytest.mark.parametrize("module", ["utils.cert_service_v2", "herdbook"])
def test_imports_when_uploads_dir_is_read_only(module):
    # With pytest loaded herdbook skips its blocking startup (database, scheduler), so the
    # subprocess has no side effects; only the import-time makedirs calls run.
    code = "import pytest\n" + _READ_ONLY_MAKEDIRS + f"import {module}\nprint('imported')\n"
    proc = subprocess.run([sys.executable, "-c", code], cwd=APP_DIR, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0 and "imported" in proc.stdout, proc.stderr[-2000:]
