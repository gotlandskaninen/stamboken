"""The access rules (ACCESS_RULES): which logged-in account may use which function on which host."""

import base64
import os
import re
import unittest
import uuid
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

import utils.database as db
import utils.settings as settings
from herdbook import APP, limiter
from utils.legacy_compat import DEFAULT_LEGACY_HOSTS, EXEMPT_ENDPOINTS, LEGACY_ENDPOINTS, NOT_PROMOTED, course_message
from werkzeug.routing import RequestRedirect

from tests.database_test import DatabaseTest

limiter.enabled = False

DATA = Path(__file__).parent / "data"
# The repo's nginx/ beside app/; the pytest containers mount it at /nginx.
NGINX = Path(__file__).resolve().parents[2] / "nginx" / "production"
LEGACY = "https://stamboken.gotlandskaninen.se"
NEW = "https://gotlandskaninen.se"
NEXT_SERVER = "http://api:9090"  # the Next.js server calls the API directly by this name
OAUTH_REDIRECTS = {("google.login", "GET"), ("google.authorized", "GET")}


def data_rows(name):
    return [line.split() for line in (DATA / name).read_text().splitlines() if line and not line.startswith("#")]


def resolve(method, template):
    """The (endpoint, method) a call reaches, following the trailing-slash redirect Flask answers first."""
    adapter = APP.url_map.bind("localhost")
    path = template.replace("<x>", "1")
    try:
        endpoint, _ = adapter.match(path, method=method)
    except RequestRedirect as moved:
        endpoint, _ = adapter.match(urlparse(moved.new_url).path, method=method)
    return endpoint, method


def sample_path(endpoint, method):
    rule = next(r for r in APP.url_map.iter_rules(endpoint) if method in r.methods)
    return re.sub(r"<[^>]+>", "1", rule.rule)


class TestAccessRules(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        super().setUp()
        for patcher in (mock.patch.object(settings.service, "access_rules", "enforce"), mock.patch.dict(os.environ)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("LEGACY_HOSTS", None)
        self.number = self.individuals[0].number

    def set(self, user, **fields):
        db.User.update(**fields).where(db.User.id == user.id).execute()

    def login(self, user, base_url=NEW):
        client = APP.test_client(use_cookies=True)
        resp = client.post("/api/login", json={"username": user.email, "password": "pass"}, base_url=base_url)
        self.assertEqual(resp.get_json()["id"], user.id, resp.data)
        return client

    def assertRefused(self, resp, message=NOT_PROMOTED):
        self.assertEqual(resp.status_code, 403, resp.data)
        self.assertEqual(resp.get_json(), {"status": "error", "message": message})

    def assertPassed(self, resp):
        body = resp.get_json(silent=True)
        refused = isinstance(body, dict) and body.get("message") in (NOT_PROMOTED, course_message())
        self.assertFalse(resp.status_code == 403 and refused, resp.data)

    def test_unpromoted_refused_on_v2_and_the_v2_patch(self):
        self.set(self.viewer, validated=True)
        for base in (NEW, NEXT_SERVER):
            with self.subTest(base):
                client = self.login(self.viewer, base)
                # sb_mode only picks a backend in the Next.js server; the API never reads it.
                client.set_cookie("sb_mode", "prod", domain=urlparse(base).hostname)
                self.assertRefused(client.get("/api/v2/my-membership", base_url=base))
                self.assertRefused(client.patch(f"/api/individual/{self.number}", json={"name": "Ny"}, base_url=base))
                self.assertRefused(client.get("/api/genebanks", base_url=base))  # a legacy function off a legacy host

    def test_legacy_host_refuses_the_v2_patch_and_logs_without_personal_data(self):
        self.set(self.viewer, validated=True)
        client = self.login(self.viewer, LEGACY)
        with self.assertLogs("utils.legacy_compat", "WARNING") as logs, self.assertNoLogs("herdbook", "WARNING"):
            resp = client.patch(f"/api/individual/{self.number}?q=spec", json={"name": "Ny"}, base_url=LEGACY)
        self.assertRefused(resp)
        self.assertEqual(
            logs.output, ["WARNING:utils.legacy_compat:Access rules refused PATCH individuals.update_individual_v2"]
        )

    def test_admin_and_promoted_pass(self):
        self.set(self.viewer, v2_prod_access=True)
        for user in (self.admin, self.viewer):
            with self.subTest(user.username):
                client = self.login(user)
                self.assertEqual(client.get("/api/genebanks", base_url=NEW).status_code, 200)
                self.assertPassed(client.patch(f"/api/individual/{self.number}", json={"name": "Ny"}, base_url=NEW))
                legacy = self.login(user, LEGACY)
                self.assertPassed(legacy.patch(f"/api/individual/{self.number}", json={"name": "Ny"}, base_url=LEGACY))
                # The legacy frontend's own functions need the course, also for them.
                self.assertRefused(legacy.get(f"/api/individual/{self.number}", base_url=LEGACY), course_message())

    def test_user_and_logout_work_unpromoted_and_unvalidated(self):
        for base in (NEW, LEGACY):
            with self.subTest(base):
                client = self.login(self.viewer, base)
                self.assertEqual(client.get("/api/user", base_url=base).status_code, 200)
                self.assertEqual(client.get("/api/logout", base_url=base).status_code, 200)
                self.assertEqual(client.get("/api/user", base_url=base).status_code, 401)

    def test_public_functions_work_with_an_unpromoted_session(self):
        client = self.login(self.viewer)
        token = uuid.uuid4()
        self.assertEqual(client.get(f"/api/v2/certificates/verify/{token}", base_url=NEW).status_code, 404)
        self.assertEqual(
            client.post(f"/api/v2/certificates/verify/{token}", data=b"%PDF", base_url=NEW).status_code, 404
        )
        application = {"first_name": "Ny", "last_name": "Sokande", "email": "ny@example.org", "gdpr_consent": True}
        resp = client.post("/api/v2/member-applications", json=application, base_url=NEW)
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertRefused(client.get("/api/v2/member-applications", base_url=NEW))

    def test_every_listed_function_passes_a_validated_unpromoted_account_on_a_legacy_host(self):
        self.set(self.viewer, validated=True)
        validated = self.login(self.viewer, LEGACY)
        unvalidated = self.login(self.owner, LEGACY)
        # Stubs stand in for the views: this tests the gate, not what each route answers.
        stubs = {endpoint: (lambda name: lambda **kwargs: name)(endpoint) for endpoint, _ in LEGACY_ENDPOINTS}
        with mock.patch.dict(APP.view_functions, stubs):
            for endpoint, method in sorted(LEGACY_ENDPOINTS):
                path = sample_path(endpoint, method)
                with self.subTest(f"{method} {path}"):
                    resp = validated.open(path, method=method, base_url=LEGACY)
                    self.assertEqual(resp.get_data(as_text=True), endpoint)
                    resp = unvalidated.open(path, method=method, base_url=LEGACY)
                    if (endpoint, method) in EXEMPT_ENDPOINTS:
                        self.assertEqual(resp.get_data(as_text=True), endpoint)
                    else:
                        self.assertRefused(resp, course_message())

    def test_unvalidated_refused_on_a_legacy_host_with_a_password_session(self):
        client = self.login(self.owner, LEGACY)
        self.assertRefused(client.get(f"/api/individual/{self.number}", base_url=LEGACY), course_message())

    def test_a_session_with_only_user_id_is_gated(self):
        """/api/manage/users reads session["user_id"] itself; flask-login does not see such a session."""
        for base, message in ((NEW, NOT_PROMOTED), (LEGACY, course_message())):
            with self.subTest(base):
                client = self.login(self.viewer, base)
                with client.session_transaction(base_url=base) as sess:
                    sess.pop("_user_id")
                self.assertRefused(client.get("/api/manage/users", base_url=base), message)

    def test_basic_auth_is_gated(self):
        auth = {"Authorization": "Basic " + base64.b64encode(b"spec:pass").decode()}
        self.assertRefused(APP.test_client().get("/api/genebanks", headers=auth, base_url=NEW))

    def test_routing_answers_and_anonymous_requests_are_untouched(self):
        client = self.login(self.viewer)
        self.assertEqual(client.get("/api/finns-inte", base_url=NEW).status_code, 404)
        self.assertEqual(client.post("/api/finns-inte", base_url=NEW).status_code, 405)
        self.assertEqual(client.post("/api/breeding/nextind", base_url=NEW).status_code, 308)
        self.assertEqual(client.options("/api/v2/my-membership", base_url=NEW).status_code, 200)
        self.assertEqual(client.head("/api/user", base_url=NEW).status_code, 200)
        anonymous = APP.test_client()
        self.assertEqual(anonymous.get("/api/genebanks", base_url=NEW).status_code, 401)
        self.assertEqual(anonymous.get("/api/manage/users", base_url=NEW).get_json(), {"users": None})

    def test_rules_off_refuse_nothing(self):
        client = self.login(self.viewer)
        with mock.patch.object(settings.service, "access_rules", "off"):
            self.assertEqual(client.get("/api/genebanks", base_url=NEW).status_code, 200)


class TestAccessRulesSetting(unittest.TestCase):
    def resolve(self, demo=False, **env):
        with mock.patch.dict(os.environ), mock.patch.object(settings.service, "demo_instance", demo):
            os.environ.pop("ACCESS_RULES", None)
            os.environ.update(env)
            return settings.resolve_access_rules()

    def test_unset_is_enforce_in_production_and_off_elsewhere(self):
        self.assertEqual(self.resolve(FLASK_ENV="production"), "enforce")
        self.assertEqual(self.resolve(FLASK_ENV="production", ACCESS_RULES=""), "enforce")
        self.assertEqual(self.resolve(FLASK_ENV="testing"), "off")
        self.assertEqual(self.resolve(FLASK_ENV="development"), "off")

    def test_an_explicit_value_wins_outside_the_demo(self):
        self.assertEqual(self.resolve(FLASK_ENV="testing", ACCESS_RULES="enforce"), "enforce")
        self.assertEqual(self.resolve(FLASK_ENV="production", ACCESS_RULES="off"), "off")

    def test_the_demo_is_always_off(self):
        self.assertEqual(self.resolve(demo=True, FLASK_ENV="production"), "off")
        self.assertEqual(self.resolve(demo=True, FLASK_ENV="production", ACCESS_RULES="enforce"), "off")

    def test_another_value_refuses_to_start(self):
        for demo in (False, True):
            with self.subTest(demo=demo), self.assertRaises(RuntimeError):
                self.resolve(demo=demo, FLASK_ENV="production", ACCESS_RULES="on")


class TestLegacyList(unittest.TestCase):
    def test_every_legacy_call_lands_on_a_listed_pair(self):
        calls = data_rows("legacy_calls.tsv")
        self.assertGreaterEqual(len(calls), 80)
        reached = set()
        for method, template, source in calls:
            with self.subTest(source):
                pair = resolve(method, template)
                self.assertIn(pair, LEGACY_ENDPOINTS, f"{method} {template}")
                reached.add(pair)
        # Nothing on the list that the legacy frontend does not call, but its OAuth redirects.
        self.assertEqual(LEGACY_ENDPOINTS - reached, OAUTH_REDIRECTS)

    def test_every_pair_in_the_old_access_log_is_listed_or_exempt(self):
        pairs = data_rows("legacy_access_log_pairs.txt")
        self.assertEqual(len(pairs), 41)
        for method, template in pairs:
            with self.subTest(f"{method} {template}"):
                self.assertIn(resolve(method, template), LEGACY_ENDPOINTS | EXEMPT_ENDPOINTS)

    def test_legacy_hosts_cover_every_legacy_server_name_in_nginx(self):
        names = set()
        for conf in sorted(NGINX.glob("*.conf")):
            # A block commented out until the migration counts too.
            text = re.sub(r"^\s*#", "", conf.read_text(), flags=re.M)
            for block in text.split("server {")[1:]:
                if "root /etc/nginx/legacy-frontend" in block:
                    names.update(re.search(r"server_name\s+([^;]+);", block).group(1).split())
        self.assertIn("stamboken.gotlandskaninen.se", names, f"no legacy server blocks read from {NGINX}")
        self.assertLessEqual(names, set(DEFAULT_LEGACY_HOSTS.split(",")))
