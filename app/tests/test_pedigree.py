#!/usr/bin/env python3
"""
Tests for the pedigree tree API endpoint.

isort:skip_file
"""

import base64
import os
import unittest

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

from herdbook import APP  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402


class TestPedigreeEndpoint(DatabaseTest):
    """Tests for GET /api/individual/<number>/pedigree."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    # nosemgrep: python.lang.security.audit.hardcoded-password-default-argument.hardcoded-password-default-argument
    def _auth_headers(self, username="admin", password="pass"):
        creds = base64.b64encode(f"{username}:{password}".encode()).decode()
        return [("Authorization", f"Basic {creds}")]

    # nosemgrep: python.lang.security.audit.hardcoded-password-default-argument.hardcoded-password-default-argument
    def _get_auth(self, url, username="admin", password="pass"):
        return self.client.get(url, headers=self._auth_headers(username, password))

    def test_unauthenticated_returns_401(self):
        """Pedigree endpoint requires authentication (json_login_required)."""
        response = self.client.get("/api/individual/G1-2111/pedigree")
        self.assertEqual(response.status_code, 401)

    def test_not_found_returns_404(self):
        """Non-existent individual returns RFC 9457 404."""
        response = self._get_auth("/api/individual/NONEXISTENT/pedigree")
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertEqual(data["status"], 404)
        self.assertIn("detail", data)

    def test_returns_subject_with_parents(self):
        """Pedigree tree includes subject and parents."""
        # G1-2111 has mother=G1-1911, father=G2-1711
        response = self._get_auth("/api/individual/G1-2111/pedigree")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        self.assertEqual(data["number"], "G1-2111")
        self.assertIsNotNone(data["mother"])
        self.assertEqual(data["mother"]["number"], "G1-1911")
        self.assertIsNotNone(data["father"])
        self.assertEqual(data["father"]["number"], "G2-1711")

    def test_missing_grandparents_are_null(self):
        """When parents have no recorded parents, grandparents are null."""
        response = self._get_auth("/api/individual/G1-2111/pedigree")
        data = response.get_json()

        # Parents' breedings have no mother/father, so grandparents should be null
        self.assertIsNone(data["mother"]["mother"])
        self.assertIsNone(data["mother"]["father"])
        self.assertIsNone(data["father"]["mother"])
        self.assertIsNone(data["father"]["father"])

    def test_generations_param_limits_depth(self):
        """generations=1 returns only subject, no parents."""
        response = self._get_auth("/api/individual/G1-2111/pedigree?generations=1")
        data = response.get_json()

        self.assertEqual(data["number"], "G1-2111")
        self.assertIsNone(data["mother"])
        self.assertIsNone(data["father"])

    def test_generations_param_clamped(self):
        """generations > 6 is clamped to 6, generations < 1 to 1."""
        # Too high — clamped to 6, still returns valid data
        response = self._get_auth("/api/individual/G1-2111/pedigree?generations=100")
        self.assertEqual(response.status_code, 200)

        # Too low — clamped to 1
        response = self._get_auth("/api/individual/G1-2111/pedigree?generations=0")
        data = response.get_json()
        self.assertEqual(data["number"], "G1-2111")
        self.assertIsNone(data["mother"])

    def test_node_structure(self):
        """Each node has id, name, number, sex, mother, father keys."""
        response = self._get_auth("/api/individual/G1-2111/pedigree")
        data = response.get_json()

        expected_keys = {"id", "name", "number", "sex", "mother", "father"}
        self.assertEqual(set(data.keys()), expected_keys)
        self.assertEqual(set(data["mother"].keys()), expected_keys)

    def test_individual_without_breeding(self):
        """Individual with no breeding record returns subject only."""
        import utils.database as db

        orphan = db.Individual.create(
            origin_herd=self.herds[0],
            number="G1-ORPHAN",
            name="Orphan",
        )
        orphan.save()

        response = self._get_auth("/api/individual/G1-ORPHAN/pedigree")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["number"], "G1-ORPHAN")
        self.assertIsNone(data["mother"])
        self.assertIsNone(data["father"])


if __name__ == "__main__":
    unittest.main()
