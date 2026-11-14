"""The genebank helper role (genbankshjälpare): granted per genebank like manager, with no edit rights of its own.

isort:skip_file
"""

import os

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402

limiter.enabled = False


class TestHelperRole(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.target = da.register_user("hjalpare@example.com", "pass", username="hjalpare")

    def login(self, username):
        self.client.get("/api/logout")
        self.client.post("/api/login", json={"username": username, "password": "pass"})

    def post_role(self, operation, genebank):
        role = {"level": "helper", "genebank": genebank.id}
        return self.client.post(
            "/api/v2/admin/role", json={"operation": operation, "user_id": self.target.id, "role": role}
        )

    def test_admin_grants_and_revokes_the_helper_role(self):
        gotland, mellerud = self.genebanks
        self.login("admin")
        self.assertEqual(self.post_role("add", gotland).get_json()["status"], "updated")
        self.assertEqual(self.post_role("add", mellerud).get_json()["status"], "updated")
        user = db.User.get_by_id(self.target.id)
        self.assertEqual(user.is_helper, [gotland.id, mellerud.id])
        self.assertTrue(user.has_role("helper", gotland.id))

        listed = self.client.get("/api/v2/admin/users?role=helper").get_json()["users"]
        self.assertEqual([(u["id"], u["role_summary"]) for u in listed], [(self.target.id, "helper(G,M)")])

        self.assertEqual(self.post_role("remove", gotland).get_json()["status"], "updated")
        self.assertEqual(db.User.get_by_id(self.target.id).is_helper, [mellerud.id])

    def test_a_helper_reads_the_genebank_but_edits_nothing(self):
        self.target.add_role("helper", self.genebanks[0].id)
        user = db.User.get_by_id(self.target.id)
        self.assertEqual(user.accessible_genebanks, [self.genebanks[0].id])
        self.assertIsNotNone(da.get_individual("G1-2111", user.uuid))
        for identifier in ("G1-2111", self.individuals[0].id, "G1", "Gotland"):
            with self.subTest(identifier=identifier):
                self.assertFalse(user.can_edit(identifier))
        self.assertFalse(user.can_transfer(self.individuals[0].id))
        self.assertFalse(user.can_view_certificate(self.individuals[0]))
        self.assertIsNone(user.is_manager)

    def test_a_manager_grants_helper_only_in_their_genebank(self):
        self.login("man")  # manager of Gotland, through the legacy role endpoint
        gotland, mellerud = self.genebanks
        for genebank, status in ((mellerud, "error"), (gotland, "updated")):
            body = {"action": "add", "role": "helper", "user": self.target.id, "genebank": genebank.id}
            self.assertEqual(self.client.post("/api/manage/role", json=body).get_json()["status"], status)
        self.assertEqual(db.User.get_by_id(self.target.id).is_helper, [gotland.id])
