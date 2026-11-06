"""Genebank scoping of the genetics routes and the breedings-by-date route."""

import os

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402


class TestGeneticsRouteAccess(DatabaseTest):
    def setUp(self):
        APP.config["TESTING"] = True  # nosemgrep
        APP.config["SESSION_COOKIE_NAME"] = "test_session"
        limiter.enabled = False
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, user):
        self.client.post("/api/login", json={"username": user.email, "password": "pass"})

    def test_genetics_routes_deny_other_genebank(self):
        own, other = self.genebanks[0].id, self.genebanks[1].id
        for user in (self.viewer, self.manager, self.owner):
            self._login(user)
            for route in ("inbreeding", "kinship", "meankinship"):
                self.assertEqual(self.client.get(f"/api/{other}/{route}/").status_code, 403, route)
                self.assertEqual(self.client.get(f"/api/{own}/{route}/").status_code, 200, route)
            self.client.get("/api/logout")

    def test_genetics_routes_allow_admin(self):
        self._login(self.admin)
        for route in ("inbreeding", "kinship", "meankinship"):
            self.assertEqual(self.client.get(f"/api/{self.genebanks[1].id}/{route}/").status_code, 200, route)

    def test_breedings_by_date_only_from_accessible_genebanks(self):
        # Two breedings share this birth date, one per genebank.
        date = "2021-02-01"
        self._login(self.manager)
        ids = {b["id"] for b in self.client.get(f"/api/breeding/date/{date}").get_json()["breedings"]}
        self.assertEqual(ids, {self.breeding[0].id})
        self.client.get("/api/logout")
        self._login(self.admin)
        ids = {b["id"] for b in self.client.get(f"/api/breeding/date/{date}").get_json()["breedings"]}
        self.assertEqual(ids, {self.breeding[0].id, self.breeding[1].id})

    def test_testbreed_denies_other_genebank(self):
        # Animals the user cannot see fall through to the genebank's snapshot by number.
        other = self.genebanks[1]
        pair = {"male": "M3-2111", "female": "M3-2122"}  # both in the other genebank
        self._login(self.viewer)
        res = self.client.post("/api/testbreed", json={"genebankId": other.id, **pair})
        self.assertEqual(res.status_code, 403)

    def test_genetics_routes_require_login(self):
        for route in ("inbreeding", "kinship", "meankinship"):
            self.assertEqual(self.client.get(f"/api/{self.genebanks[0].id}/{route}/").status_code, 401, route)
