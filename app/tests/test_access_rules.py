"""The access rules (ACCESS_RULES): which logged-in account may use which function on which host."""

import base64
import io
import os
import re
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

import utils.data_access as da
import utils.database as db
import utils.settings as settings
from herdbook import APP, limiter
from utils import app_logging
from utils.legacy_compat import DEFAULT_LEGACY_HOSTS, EXEMPT_ENDPOINTS, LEGACY_ENDPOINTS, NOT_PROMOTED, course_message
from werkzeug.routing import RequestRedirect

from tests.database_test import DatabaseTest
from tests.google_login import ID_TOKEN, redirect_login, token_login
from tests.inbox_fixtures import InboxTest, encoded, photo

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

    def test_refusal_is_one_denied_line_without_query_string_or_address(self):
        self.set(self.viewer, validated=True)
        client = self.login(self.viewer, LEGACY)
        out = io.StringIO()
        with mock.patch.object(app_logging.HANDLER, "stream", out):
            self.assertRefused(
                client.patch(f"/api/individual/{self.number}?q=HEMLIG", json={"name": "Ny"}, base_url=LEGACY)
            )
        denied = [line for line in out.getvalue().splitlines() if line.startswith("herdbook.auth INFO Denied 403")]
        self.assertEqual(len(denied), 1, out.getvalue())
        self.assertRegex(denied[0], rf"user id={self.viewer.id} ")
        self.assertNotIn("HEMLIG", out.getvalue())
        self.assertNotIn(self.viewer.email, out.getvalue())

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


class TestOwnUploadsUnpromoted(InboxTest):
    """Production access is required to submit new certificates. Members can still read their own submissions."""

    def setUp(self):
        super().setUp()
        db.User.update(v2_prod_access=False).where(db.User.id.in_([self.owner.id, self.helper.id])).execute()
        for patcher in (mock.patch.object(settings.service, "access_rules", "enforce"), mock.patch.dict(os.environ)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("LEGACY_HOSTS", None)

    def client_of(self, user, base_url=NEW):
        client = APP.test_client(use_cookies=True)
        resp = client.post("/api/login", json={"username": user.email, "password": "pass"}, base_url=base_url)
        self.assertEqual(resp.status_code, 200, resp.data)
        return client

    def send(self, client, base_url=NEW, herd="G1"):
        data = {"herd": herd, "files": [(io.BytesIO(encoded(photo())), "intyg.jpg")]}
        return client.post("/api/v2/inkorg/upload", data=data, content_type="multipart/form-data", base_url=base_url)

    def test_an_unpromoted_owner_can_only_read_her_existing_submissions(self):
        own = self.item(sender=self.owner)
        self.item(herd=1, sender=self.manager)
        for base in (NEW, LEGACY):
            with self.subTest(base):
                client = self.client_of(self.owner, base)
                resp = self.send(client, base)
                self.assertEqual(resp.status_code, 403, resp.get_json())
                listed = client.get("/api/v2/inkorg/mina-inskick", base_url=base)
                self.assertEqual(listed.status_code, 200, listed.data)
                ids = [item["id"] for item in listed.get_json()["items"]]
                self.assertEqual(ids, [own.id])
                count = client.get("/api/v2/inkorg/notiser/antal", base_url=base)
                self.assertEqual(count.get_json(), {"unread": 0, "works_in_queue": False})
        self.assertEqual(db.InboxItem.select().count(), 2)
        self.assertEqual(os.listdir(self.folder), [])

    def test_demo_upload_stays_on_demo_even_for_a_promoted_owner(self):
        db.User.update(v2_prod_access=True).where(db.User.id == self.owner.id).execute()
        with mock.patch.object(settings.service, "demo_instance", True):
            client = self.client_of(self.owner)
            self.assertEqual(self.send(client).status_code, 201)
        client.set_cookie("sb_mode", "prod", domain=urlparse(NEW).hostname)
        self.assertEqual(self.send(client).status_code, 401)
        self.assertEqual(db.InboxItem.select().count(), 1)

    def test_demo_accepts_an_owner_without_production_access(self):
        with (
            mock.patch.object(settings.service, "demo_instance", True),
            mock.patch.object(settings.service, "access_rules", "off"),
        ):
            client = self.client_of(self.owner)
            client.set_cookie("sb_mode", "demo", domain=urlparse(NEW).hostname)
            self.assertEqual(self.send(client).status_code, 201)

    def test_production_refuses_demo_mode_and_unpromoted_accounts_with_rules_off(self):
        with mock.patch.object(settings.service, "access_rules", "off"):
            client = self.client_of(self.owner)
            self.assertEqual(self.send(client).status_code, 403)
            db.User.update(v2_prod_access=True).where(db.User.id == self.owner.id).execute()
            client.set_cookie("sb_mode", "demo", domain=urlparse(NEW).hostname)
            self.assertEqual(self.send(client).status_code, 403)
            self.assertFalse(db.InboxItem.select().exists())
            self.assertEqual(os.listdir(self.folder), [])
            client.set_cookie("sb_mode", "prod", domain=urlparse(NEW).hostname)
            self.assertEqual(self.send(client).status_code, 201)

    def test_the_queue_its_items_and_originals_stay_gated(self):
        own = self.item(herd=0, sender=self.owner)
        other = self.item(herd=1, sender=self.manager)
        document = other.documents.get()
        paths = ("", f"/{other.id}", f"/{own.id}", f"/{other.id}/dokument/{document.id}/original", "/notiser")
        # The helper works in the queue: her role alone would let her in.
        for user in (self.owner, self.helper):
            client = self.client_of(user)
            for path in paths:
                with self.subTest(user=user.email, path=path):
                    resp = client.get(f"/api/v2/inkorg{path}", base_url=NEW)
                    self.assertEqual(resp.status_code, 403, resp.data)
                    self.assertEqual(resp.get_json(), {"status": "error", "message": NOT_PROMOTED})
        db.User.update(v2_prod_access=True).where(db.User.id == self.helper.id).execute()
        self.assertEqual(self.client_of(self.helper).get("/api/v2/inkorg", base_url=NEW).status_code, 200)

    def test_anonymous_requests_are_untouched(self):
        anonymous = APP.test_client()
        self.assertEqual(self.send(anonymous).status_code, 401)
        for path in ("/mina-inskick", "/notiser/antal", ""):
            with self.subTest(path):
                self.assertEqual(anonymous.get(f"/api/v2/inkorg{path}", base_url=NEW).status_code, 401)


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
                pair = resolve(method, template)
                self.assertNotEqual(pair[0], "main")  # the catch-all: the route is gone
                self.assertIn(pair, LEGACY_ENDPOINTS | EXEMPT_ENDPOINTS)

    def test_the_exemptions_are_exactly_these(self):
        """An exemption is open to every logged-in account: adding one is a decision, not a side effect."""
        self.assertEqual(
            EXEMPT_ENDPOINTS,
            {
                ("get_user", "GET"),
                ("logout", "GET"),
                ("login_handler", "POST"),
                ("google_token_login", "POST"),
                ("code_login.status", "GET"),
                ("code_login.request_code", "POST"),
                ("code_login.verify_code", "POST"),
                ("code_login.preview_link", "POST"),
                ("code_login.redeem_link", "POST"),
                ("external_login_handler", "GET"),
                ("external_login_handler", "POST"),
                ("google.login", "GET"),
                ("google.authorized", "GET"),
                ("external_link_handler", "GET"),
                ("external_link_handler", "POST"),
                ("certificates_v2.verify_certificate_get", "GET"),
                ("certificates_v2.verify_certificate_post", "POST"),
                ("rapport_link.open_link", "POST"),
                ("rapport_link.mine", "GET"),
                ("rapport_link.contacts", "GET"),
                ("rapport_link.show_changes", "POST"),
                ("rapport_link.confirm_changes", "POST"),
                ("rapport_link.not_me", "POST"),
                ("member_applications.create_application", "POST"),
                ("member_applications.list_public_genebanks", "GET"),
                ("inbox.my_uploads", "GET"),
                ("inbox.uploads_seen", "POST"),
                ("inbox.notice_count", "GET"),
                ("certificates_v2.check_page_name", "GET"),
                ("certificates_v2.check_page_name", "PUT"),
                ("tyck_till.send", "POST"),
                ("health_check", "GET"),
                ("main", "GET"),
                ("static", "GET"),
            },
        )

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


class TestLegacyGoogleLoginNeverAdopts(DatabaseTest):
    """The legacy Google path's auto-registration links only an account it creates itself."""

    ADDRESS = ID_TOKEN["email"]
    TAKEN = "Det finns redan ett konto"

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        super().setUp()

    def first_login(self, client, auto_validate=True):
        account = {"email": self.ADDRESS, "username": "medlem"}
        return redirect_login(client, da.authenticate_with_credentials, auto_validate=auto_validate, account=account)

    def assertNothingLinked(self, client, resp):
        self.assertIn(self.TAKEN, resp.get_data(as_text=True))
        self.assertFalse(db.Authenticators.select().where(db.Authenticators.auth_data == "google-sub").exists())
        self.assertEqual(client.get("/api/user").status_code, 401)

    def test_an_address_an_existing_account_holds_is_refused(self):
        for validated in (False, True):
            for with_google in (False, True):
                with self.subTest(validated=validated, with_google=with_google):
                    db.User.delete().where(db.User.email == "Medlem@gotlandskaninen.se").execute()
                    holder = da.register_user("Medlem@gotlandskaninen.se", "pass", validated=validated)
                    if with_google:
                        db.Authenticators.create(user=holder.id, auth="google", auth_data="sub-annan")
                    client = APP.test_client(use_cookies=True)
                    self.assertNothingLinked(client, self.first_login(client))
                    self.assertEqual(db.User.select().where(db.User.email**self.ADDRESS).count(), 1)
                    db.Authenticators.delete().where(db.Authenticators.user == holder.id).execute()

    def test_a_brand_new_address_gets_an_account_linked_and_logged_in(self):
        client = APP.test_client(use_cookies=True)
        self.assertEqual(self.first_login(client).status_code, 302)
        me = client.get("/api/user").get_json()
        self.assertEqual(me["email"], self.ADDRESS)
        google = db.Authenticators.get(db.Authenticators.auth_data == "google-sub")
        self.assertEqual(google.user_id, me["id"])

    def test_a_self_set_address_never_captures_the_members_google_login(self):
        """An account unlinks Google and takes the address of a member who has never
        signed in, then the member signs in with Google both ways."""
        member = db.Member.create(
            membership=db.Membership.create(membership_status="active"),
            first_name="Ny",
            last_name="Medlem",
            role="huvudmedlem",
            workspace_email=self.ADDRESS,
        )
        attacker = da.register_user("annan@gotlandskaninen.se", "pass", validated=True)
        db.User.update(v2_prod_access=True).where(db.User.id == attacker.id).execute()
        db.Authenticators.create(user=attacker.id, auth="google", auth_data="sub-annan")
        own_token = {**ID_TOKEN, "sub": "sub-annan", "email": "annan@gotlandskaninen.se"}

        with mock.patch.object(settings.service, "access_rules", "enforce"):
            evil = APP.test_client(use_cookies=True)
            with mock.patch("google.oauth2.id_token.verify_oauth2_token", return_value=own_token):
                self.assertEqual(evil.post("/api/auth/google", json={"credential": "t"}).status_code, 200)
            self.assertEqual(evil.post("/api/unlink/google").get_data(as_text=True), "1")
            # Removing the identity ended the session; the attacker signs in with the password.
            evil.post("/api/login", json={"username": attacker.email, "password": "pass"})
            # the old route is closed (ADR-0020); the account's e-mail changes as it did through it
            moved = da.update_user({"id": attacker.id, "email": self.ADDRESS, "validated": False}, attacker.uuid)
            self.assertEqual(moved, {"status": "updated"})

            victim = APP.test_client(use_cookies=True)
            self.assertNothingLinked(victim, self.first_login(victim, auto_validate=False))
            self.assertEqual(token_login(victim, da.authenticate_with_credentials).status_code, 401)
            self.assertEqual(victim.get("/api/user").status_code, 401)

            self.assertEqual(evil.get("/api/user").get_json()["id"], attacker.id)
        held = db.Authenticators.select().where(db.Authenticators.user == attacker.id)
        self.assertEqual([row.auth for row in held], ["password"])
        self.assertIsNone(db.Member.get_by_id(member.id).user_id)

    def test_the_last_way_to_sign_in_cannot_be_unlinked(self):
        only_google = da.register_user("bara-google@gotlandskaninen.se", None, validated=True)
        db.Authenticators.create(user=only_google.id, auth="google", auth_data="sub-bara")
        token = {**ID_TOKEN, "sub": "sub-bara", "email": only_google.email}
        client = APP.test_client(use_cookies=True)
        with mock.patch("google.oauth2.id_token.verify_oauth2_token", return_value=token):
            self.assertEqual(client.post("/api/auth/google", json={"credential": "t"}).status_code, 200)
        self.assertEqual(client.get("/api/user").get_json()["id"], only_google.id)  # "null" also answers no session
        self.assertEqual(client.post("/api/unlink/google").get_data(as_text=True), "null")
        self.assertTrue(db.Authenticators.select().where(db.Authenticators.user == only_google.id).exists())

    def at_once(self, *calls):
        """Each call on its own connection, as in test_admin_role_invariant; what they returned, falsy first."""
        barrier = threading.Barrier(len(calls), timeout=10)
        outcomes = []

        def run(call):
            try:
                barrier.wait()
                outcomes.append(call())
            except Exception as exc:  # fails the caller's assert
                outcomes.append(exc)
            finally:
                db.DATABASE.close()

        threads = [threading.Thread(target=run, args=(call,)) for call in calls]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        return sorted(
            (bool(outcome) if not isinstance(outcome, Exception) else outcome for outcome in outcomes), key=str
        )

    def identities(self, **where):
        rows = db.Authenticators.select().where(*(getattr(db.Authenticators, k) == v for k, v in where.items()))
        return sorted(row.auth_data for row in rows if row.auth == "google")

    def test_two_unlinks_at_once_leave_one_way_to_sign_in(self):
        both = da.register_user("tva@gotlandskaninen.se", "pass", validated=True)
        db.Authenticators.create(user=both.id, auth="google", auth_data="sub-tva")
        done = self.at_once(lambda: da.unlink_account(both, "google"), lambda: da.unlink_account(both, "password"))
        self.assertEqual(done, [False, True])
        self.assertEqual(db.Authenticators.select().where(db.Authenticators.user == both.id).count(), 1)

    def test_two_accounts_linking_one_identity_at_once_give_it_to_one(self):
        first = da.register_user("ett@gotlandskaninen.se", "pass", validated=True)
        second = da.register_user("tva@gotlandskaninen.se", "pass", validated=True)
        done = self.at_once(
            lambda: da.link_account(first, "google", "sub-delad"),
            lambda: da.link_account(second, "google", "sub-delad"),
        )
        self.assertEqual(done, [False, True])
        self.assertEqual(self.identities(auth_data="sub-delad"), ["sub-delad"])

    def test_two_links_to_one_account_at_once_leave_one_identity(self):
        account = da.register_user("ett@gotlandskaninen.se", "pass", validated=True)
        done = self.at_once(
            lambda: da.link_account(account, "google", "sub-a", from_google_session=True),
            lambda: da.link_account(account, "google", "sub-b", from_google_session=True),
        )
        self.assertEqual(done, [True, True])
        self.assertEqual(len(self.identities(user=account.id)), 1)

    def test_a_first_login_whose_link_fails_leaves_no_account(self):
        client = APP.test_client(use_cookies=True)
        with mock.patch.object(da, "link_account", return_value=None):
            self.assertEqual(self.first_login(client).status_code, 500)
        self.assertFalse(db.User.select().where(db.User.email == self.ADDRESS).exists())
        self.first_login(client)  # and the next attempt is not refused for the address
        self.assertEqual(client.get("/api/user").get_json()["email"], self.ADDRESS)

    def test_a_link_to_an_identity_another_account_holds_keeps_the_old_one(self):
        mine = da.register_user("min@gotlandskaninen.se", None, validated=True)
        other = da.register_user("annans@gotlandskaninen.se", None, validated=True)
        db.Authenticators.create(user=mine.id, auth="google", auth_data="sub-min")
        db.Authenticators.create(user=other.id, auth="google", auth_data="sub-annans")

        def held():
            rows = db.Authenticators.select().where(db.Authenticators.user == mine.id)
            return [row.auth_data for row in rows]

        self.assertIsNone(da.link_account(mine, "google", "sub-annans"))
        self.assertEqual(held(), ["sub-min"])
        # a free identity replaces the old one
        self.assertTrue(da.link_account(mine, "google", "sub-ny", from_google_session=True))
        self.assertEqual(held(), ["sub-ny"])


class TestHolderCannotChangeValidated(DatabaseTest):
    """validated marks the web course; the legacy "Ändra e-postadress" call must not clear it."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        super().setUp()

    def update(self, actor, body):  # the legacy route is closed (410, ADR-0020): the function behind it
        return da.update_user(body, actor.uuid)

    def validated(self, user):
        return db.User.get_by_id(user.id).validated

    def test_the_legacy_change_email_call_leaves_validated_alone(self):
        for user in (self.viewer, self.manager, self.admin):
            with self.subTest(user.email):
                db.User.update(validated=True).where(db.User.id == user.id).execute()
                body = {"id": user.id, "email": f"ny-{user.email}@example.org", "validated": False}
                self.assertEqual(self.update(user, body), {"status": "updated"})
                self.assertTrue(self.validated(user))

    def test_a_manager_cannot_validate_their_own_account(self):
        body = {"id": self.manager.id, "email": self.manager.email, "validated": True}
        self.assertEqual(self.update(self.manager, body), {"status": "unchanged"})
        self.assertFalse(self.validated(self.manager))

    def test_another_spelling_of_the_own_id_changes_nothing(self):
        for actor in (self.manager, self.admin):
            for value in (True, False):
                db.User.update(validated=not value).where(db.User.id == actor.id).execute()
                for own_id in (f"00{actor.id}", float(actor.id), str(actor.id)):
                    with self.subTest(actor=actor.email, value=value, id=own_id):
                        body = {"id": own_id, "email": actor.email, "validated": value}
                        answer = self.update(actor, body)
                        self.assertEqual(answer, {"status": "unchanged"})
                        self.assertEqual(self.validated(actor), not value)

    def test_an_id_that_is_no_number_is_no_account(self):
        body = {"id": "t", "email": "ny@example.org", "validated": True}
        answer = self.update(self.manager, body)
        self.assertEqual(answer, {"status": "error", "message": "unknown user"})

    def test_admin_and_manager_still_set_validated_on_another_account(self):
        for actor, value in ((self.admin, True), (self.manager, False)):
            with self.subTest(actor.email):
                body = {"id": self.viewer.id, "email": self.viewer.email, "validated": value}
                self.assertEqual(self.update(actor, body), {"status": "updated"})
                self.assertEqual(self.validated(self.viewer), value)

    def test_a_member_still_cannot_send_validated_true(self):
        body = {"id": self.viewer.id, "email": self.viewer.email, "validated": True}
        self.assertEqual(self.update(self.viewer, body), {"status": "error", "message": "forbidden"})
        self.assertFalse(self.validated(self.viewer))


class TestCourseRequirement(DatabaseTest):
    """The web course gates the legacy frontend; /api/auth/google demands it only without the access rules."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        super().setUp()
        for patcher in (
            mock.patch("herdbook._should_auto_validate_users", return_value=False),
            mock.patch.dict(os.environ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("LEGACY_HOSTS", None)

    def as_viewer(self, method, ident):
        return db.User.get_by_id(self.viewer.id)

    def test_token_login_lets_an_unvalidated_account_in_under_enforce(self):
        client = APP.test_client(use_cookies=True)
        with mock.patch.object(settings.service, "access_rules", "enforce"):
            self.assertEqual(token_login(client, self.as_viewer).status_code, 200)
            self.assertEqual(client.get("/api/user").status_code, 200)
            refused = client.get("/api/v2/my-membership")
            self.assertEqual((refused.status_code, refused.get_json()["message"]), (403, NOT_PROMOTED))
            # The same session on a legacy host: the legacy frontend's functions need the course.
            name = APP.config["SESSION_COOKIE_NAME"]
            client.set_cookie(name, client.get_cookie(name).value, domain=urlparse(LEGACY).hostname)
            legacy = client.get(f"/api/individual/{self.individuals[0].number}", base_url=LEGACY)
            self.assertEqual((legacy.status_code, legacy.get_json()["message"]), (403, course_message()))
        self.assertFalse(db.User.get_by_id(self.viewer.id).validated)

    def test_token_login_demands_the_course_with_the_rules_off(self):
        client = APP.test_client(use_cookies=True)
        with mock.patch.object(settings.service, "access_rules", "off"):
            resp = token_login(client, self.as_viewer)
        self.assertEqual((resp.status_code, resp.get_json()["error"]), (401, course_message()))
        self.assertEqual(client.get("/api/user").status_code, 401)

    def test_the_legacy_google_login_demands_the_course_either_way(self):
        for rules in ("off", "enforce"):
            with self.subTest(rules), mock.patch.object(settings.service, "access_rules", rules):
                client = APP.test_client(use_cookies=True)
                resp = redirect_login(client, self.as_viewer)
                self.assertIn("bli validerad", resp.get_data(as_text=True))
                self.assertEqual(client.get("/api/user").status_code, 401)
