"""Unit tests for herdbook._resolve_secret_key() (D-04/D-05 fail-hard gate)."""

import os
import unittest
from unittest.mock import patch

from herdbook import _resolve_secret_key


class TestSecretKeyGate(unittest.TestCase):
    """Verify SECRET_KEY resolution and the production fail-hard gate."""

    def test_returns_env_value_when_set(self):
        """SECRET_KEY is returned verbatim when set, regardless of FLASK_ENV."""
        with patch.dict(os.environ, {"SECRET_KEY": "abc123"}):
            assert _resolve_secret_key() == "abc123"

    def test_raises_in_production_without_secret(self):
        """FLASK_ENV=production with no SECRET_KEY must raise RuntimeError."""
        with patch.dict(os.environ, {"FLASK_ENV": "production"}, clear=False):
            os.environ.pop("SECRET_KEY", None)
            with self.assertRaises(RuntimeError):
                _resolve_secret_key()

    def test_dev_fallback_when_not_production(self):
        """Non-production environments fall back to the fixed dev secret."""
        with patch.dict(os.environ, {"FLASK_ENV": "development"}, clear=False):
            os.environ.pop("SECRET_KEY", None)
            assert _resolve_secret_key() == "dev-secret-do-not-use-in-prod"
