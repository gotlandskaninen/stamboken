"""The committed dev/test signing key must never sign real certificates.

Startup under FLASK_ENV=production refuses the key in app/certs/ unless the
instance is a watermarked demo or has signing disabled. Verification trusts
the signing CA plus PDF_SIGNING_TRUST_CAS, so certificates issued before a
key rotation still verify.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import utils.settings as settings

APP_DIR = Path(__file__).resolve().parent.parent
COMMITTED = APP_DIR / "certs" / "key.pem"
SIGNING_VARS = ("PDF_SIGNING_KEY", "PDF_SIGNING_CA", "CERT_DEMO_WATERMARK", "PDF_SIGNING_ENABLED")

PROBE = (
    "import herdbook, os\n"
    "from utils import settings\n"
    "print('STARTED key=%s' % settings.certs.private_key, flush=True)\n"
    "os._exit(0)\n"
)


class TestRefuseCommittedKey(unittest.TestCase):
    def _run(self, prod=True, **env):
        base = {k: v for k, v in os.environ.items() if k not in SIGNING_VARS}
        if prod:
            base.update(FLASK_ENV="production", SECRET_KEY="guard-test-only")
        else:
            base.pop("FLASK_ENV", None)
        base.update(env)
        saved = (settings.certs.private_key, settings.certs.demo_watermark, settings.certs.signing_enabled)
        with patch.dict(os.environ, base, clear=True):
            settings.certs.private_key = Path(os.environ.get("PDF_SIGNING_KEY", "certs/key.pem"))
            settings.certs.demo_watermark = os.environ.get("CERT_DEMO_WATERMARK", "false").lower() == "true"
            settings.certs.signing_enabled = os.environ.get("PDF_SIGNING_ENABLED", "true").lower() != "false"
            try:
                settings.refuse_committed_signing_key()
                return "started"
            except RuntimeError:
                return "refused"
            finally:
                settings.certs.private_key, settings.certs.demo_watermark, settings.certs.signing_enabled = saved

    def test_production_refuses_default_key(self):
        self.assertEqual(self._run(), "refused")

    def test_production_refuses_template_path(self):
        self.assertEqual(self._run(PDF_SIGNING_KEY="certs/key.pem"), "refused")

    def test_production_refuses_a_copy_of_the_committed_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "pdf_signing_key.pem"
            shutil.copy(COMMITTED, copy)
            self.assertEqual(self._run(PDF_SIGNING_KEY=str(copy)), "refused")

    def test_production_accepts_another_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp) / "pdf_signing_key.pem"
            other.write_bytes(b"-----BEGIN PRIVATE KEY-----\nnot the committed one\n-----END PRIVATE KEY-----\n")
            self.assertEqual(self._run(PDF_SIGNING_KEY=str(other)), "started")

    def test_demo_and_disabled_and_dev_may_use_it(self):
        self.assertEqual(self._run(CERT_DEMO_WATERMARK="true"), "started")
        self.assertEqual(self._run(PDF_SIGNING_ENABLED="false"), "started")
        self.assertEqual(self._run(prod=False), "started")

    def test_import_of_the_app_refuses_in_production(self):
        """The guard runs at import, not only when called: the API never comes up."""
        env = {k: v for k, v in os.environ.items() if k not in SIGNING_VARS}
        env.update(
            FLASK_ENV="production", SECRET_KEY="guard-test-only", GOOGLE_CLIENT_ID="dummy.apps.googleusercontent.com"
        )
        p = subprocess.run(
            [sys.executable, "-c", PROBE], cwd=str(APP_DIR), env=env, capture_output=True, text=True, timeout=120
        )
        self.assertNotIn("STARTED", p.stdout, p.stdout + p.stderr[-500:])
        self.assertIn("committed dev/test key", p.stderr)


class TestTrustCas(unittest.TestCase):
    def test_trust_cas_defaults_to_the_signing_ca(self):
        self.assertEqual(settings.certs.trust_cas, [settings.certs.ca])
