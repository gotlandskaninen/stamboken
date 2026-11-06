#!/usr/bin/env python3
"""
Unit tests for the herdbook endpoints.

isort:skip_file
"""
# Fairly lax pylint settings as we want to test a lot of things

# pylint: disable=too-many-public-methods
# pylint: disable=too-many-statements
# pylint: disable=wrong-import-position

import base64
import os
import unittest
from datetime import datetime, timedelta
from unittest import mock

import flask
import requests
from herdbook import limiter

# Set configuration file for external accounts
os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

# pylint: disable=import-error
import herdbook  # noqa: E402
import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from herdbook import APP  # noqa: E402
from moto import mock_aws  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402
from tests.ht_helpers import ht_row  # noqa: E402

HOST = "http://localhost:4200"


# pylint: disable=too-few-public-methods
class FlaskTest(DatabaseTest):
    """
    Starts and stops the flask application so that endpoints can be tested.
    """

    # pylint: disable=invalid-name
    def setUp(self):
        """
        Starts the flask APP on port `self.PORT`.
        """
        APP.config["TESTING"] = True  # fmt: skip  # noqa: E501  # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["DEBUG"] = False  # fmt: skip  # noqa: E501  # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_DEBUG
        APP.config["SESSION_COOKIE_NAME"] = "test_session"
        APP.config["SESSION_PERMANENT"] = False
        # Disable rate limiting during tests to prevent 429 errors
        limiter.enabled = False
        APP.static_folder = "../frontend/"
        # Create a fresh test client with use_cookies=True but no cookie jar from previous tests
        self.app = APP.test_client(use_cookies=True)
        super().setUp()

    def tearDown(self):
        """
        Clean up Flask-Login state and call parent tearDown.
        """
        super().tearDown()


class TestEndpoints(FlaskTest):
    """
    Checks that all endpoints are valid.
    """

    def test_main(self):
        """
        Checks that the main endpoint (/) is available.
        """

        try:
            self.assertEqual(requests.get(HOST + "/").status_code, 200)
        except requests.exceptions.ConnectionError:
            self.skipTest("Server not running")

    def test_get_user(self):
        """
        Checks that `herdbook.get_user` returns the correct user.
        """
        for test_user in [self.admin, self.manager, self.viewer, self.owner]:
            user_data = {
                "id": test_user.id,
                "email": test_user.email,
                "fullname": test_user.fullname,
                "is_admin": test_user.is_admin,
                "is_matrikel_admin": test_user.is_matrikel_admin,
                "is_manager": test_user.is_manager,
                "is_owner": test_user.is_owner,
                "username": test_user.username,
                "validated": test_user.validated,
                "profile_picture": test_user.profile_picture,
                "google_picture": test_user.google_picture,
                "google_name": test_user.google_name,
                "google_email": test_user.google_email,
                "use_google_picture": test_user.use_google_picture,
                # frontend_data derives this: admins are implicitly promoted
                "v2_prod_access": test_user.v2_prod_access or test_user.is_admin,
            }
            with self.app as context:
                # Unauthenticated users get an error response
                unauthenticated_response = context.get("/api/user").get_json()
                self.assertEqual(unauthenticated_response.get("status"), "error")
                # Login
                context.post("/api/login", json={"username": test_user.email, "password": "pass"})
                self.assertEqual(flask.session["user_id"].hex, test_user.uuid.hex)
                self.assertEqual(context.get("/api/user").get_json(), user_data)
                context.get("/api/logout")
                # After logout, should get error response
                logout_response = context.get("/api/user").get_json()
                self.assertEqual(logout_response.get("status"), "error")

    def test_get_users(self):
        """
        Checks that `herdbook.get_users` returns the correct user.
        """
        user_results = [
            (
                self.admin,
                [
                    {
                        "id": u.id,
                        "email": u.email,
                        "name": u.username,
                        "fullname": u.fullname,
                    }
                    for u in [self.admin, self.viewer, self.manager, self.owner]
                ],
            ),
            (
                self.manager,
                [
                    {
                        "id": u.id,
                        "email": u.email,
                        "name": u.username,
                        "fullname": u.fullname,
                    }
                    for u in [self.viewer, self.manager, self.owner]
                ],
            ),
            (self.viewer, None),
            (self.owner, None),
        ]

        for user, result in user_results:
            with self.app as context:
                context.post("/api/login", json={"username": user.email, "password": "pass"})
                response = context.get("/api/manage/users").get_json()
                # Sort by id for consistent comparison (PostgreSQL may return different order)
                if result is not None and response.get("users") is not None:
                    result_sorted = sorted(result, key=lambda x: x["id"])
                    response_sorted = sorted(response["users"], key=lambda x: x["id"])
                    self.assertEqual(result_sorted, response_sorted)
                else:
                    self.assertDictEqual(response, {"users": result})
                context.get("/api/logout")
                self.assertEqual(context.get("/api/manage/users").get_json(), {"users": None})

    def test_breeding_list(self):
        """
        Checks that `herdbook.breeding_list` returns the intended information.
        """
        # not logged in
        self.assertEqual(self.app.get("/api/breeding").get_json(), None)

        # jscpd:ignore-start
        with self.app as context:
            # login
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            # register a valid breeding event
            response = context.get(f"/api/breeding/{self.herds[0].herd}")

            breedings_dict = []
            for breedings in db.Breeding.select().where(db.Breeding.breeding_herd_id == self.herds[0]):
                individuals_dict = []
                for data in (
                    db.Individual.select(
                        db.Individual.number,
                        db.Individual.name,
                        db.Individual.color,
                        db.Individual.sex,
                        db.Individual.id,
                        db.Individual.origin_herd,
                        db.Individual.certificate,
                        db.Individual.digital_certificate,
                    )
                    .where(db.Individual.breeding_id == breedings.id)
                    .order_by(db.Individual.number)
                ):
                    ind = dict()
                    if data:
                        ind["number"] = data.number
                        ind["name"] = data.name
                        ind["sex"] = data.sex
                        ind["color"] = data.color.name if data.color else None
                        ind["current_herd"] = data.current_herd.herd
                        ind["is_registered"] = True if data.certificate or data.digital_certificate else False
                    individuals_dict.append(ind)
                b = breedings.as_dict()
                b["individuals"] = individuals_dict
                breedings_dict.append(b)

            expected = {"breedings": breedings_dict}
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), expected)
        # jscpd:ignore-end

    def test_request_loader_breeding(self):
        """
        Checks that `herdbook.load_user_from_request` works as intended for
        authenticating the supplied user.
        """
        herd = self.herds[0].herd

        # not logged in — API paths return 401 JSON, not redirect
        unauth_response = self.app.get(f"/api/breeding/{herd}")
        self.assertEqual(unauth_response.status_code, 401)
        self.assertEqual(unauth_response.get_json()["status"], "error")

        bad_auth_response = self.app.get(f"/api/breeding/{herd}", headers=[("Authorization", "somethingwrong")])
        self.assertEqual(bad_auth_response.status_code, 401)
        self.assertEqual(bad_auth_response.get_json()["status"], "error")

        auth_head = base64.b64encode(bytes(self.admin.email, "utf-8") + b":pass").decode("ascii")

        breedings_dict = []
        for breedings in db.Breeding.select().where(db.Breeding.breeding_herd_id == self.herds[0]):
            individuals_dict = []
            for data in (
                db.Individual.select(
                    db.Individual.number,
                    db.Individual.name,
                    db.Individual.color,
                    db.Individual.sex,
                    db.Individual.id,
                    db.Individual.origin_herd,
                    db.Individual.certificate,
                    db.Individual.digital_certificate,
                )
                .where(db.Individual.breeding_id == breedings.id)
                .order_by(db.Individual.number)
            ):
                ind = dict()
                if data:
                    ind["number"] = data.number
                    ind["name"] = data.name
                    ind["sex"] = data.sex
                    ind["color"] = data.color.name if data.color else None
                    ind["current_herd"] = data.current_herd.herd
                    ind["is_registered"] = True if data.certificate or data.digital_certificate else False
                individuals_dict.append(ind)
            b = breedings.as_dict()
            b["individuals"] = individuals_dict
            breedings_dict.append(b)

        expected_breedings = {"breedings": breedings_dict}

        response = self.app.get(
            f"/api/breeding/{herd}",
            headers=[("Authorization", "Basic " + auth_head)],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected_breedings)

    def test_register_breeding(self):
        """
        Checks that `herdbook.register_breeding` works as intended.

        This will only do a subset of the checks that is done for the
        data_access.register_breeding function, as to avoid too much redundancy.
        """

        valid_form = {
            "father": self.individuals[0].number,
            "mother": self.individuals[1].number,
            "breeding_herd": self.herds[0].herd,
            "date": datetime.today().strftime("%Y-%m-%d"),
        }

        # not logged in
        self.assertEqual(self.app.get("/api/breeding").get_json(), None)

        # jscpd:ignore-start
        with self.app as context:
            # login
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            # register a valid breeding event
            response = context.post("/api/breeding", json=valid_form)
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["status"], "success")
            self.assertIn("breeding_id", data)
        # jscpd:ignore-end

    def test_register_birth(self):
        """
        Checks that `herdbook.register_birth` works as intended.

        This will only do a subset of the checks that is done for the
        data_access.register_birth function, as to avoid too much redundancy.
        """

        valid_form = {
            "id": self.breeding[3].id,
            "date": datetime(2022, 2, 1).strftime("%Y-%m-%d"),  # 31 days after breed_date 2022-01-01
            "litter_size": 4,
        }

        # not logged in — API paths return 401 JSON, not redirect
        unauth_response = self.app.post("/api/birth", json=valid_form)
        self.assertEqual(unauth_response.status_code, 401)
        self.assertEqual(unauth_response.get_json()["status"], "error")

        with self.app as context:
            # login
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            # register a valid breeding event
            response = context.post("/api/birth", json=valid_form)
            self.assertEqual(response.status_code, 200)
            # register_birth now assigns and surfaces the stored litter_number.
            self.assertEqual(response.get_json(), {"status": "success", "litter_number": 1})

    def test_update_breeding(self):
        """
        Checks that `herdbook.update_breeding` works as intended.

        This will only do a subset of the checks that is done for the
        data_access.update_breeding function, as to avoid too much redundancy.
        """

        valid_form = {
            "id": self.breeding[0].id,
            "breed_notes": "Updated via test",
        }

        # not logged in — API paths return 401 JSON, not redirect
        unauth_response = self.app.post("/api/breeding", json=valid_form)
        self.assertEqual(unauth_response.status_code, 401)
        self.assertEqual(unauth_response.get_json()["status"], "error")

        with self.app as context:
            # login
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            # register a valid breeding event
            response = context.patch("/api/breeding", json=valid_form)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), {"status": "success"})

    def test_available_auth_methods(self):
        """
        Checks that `herdbook.external_login_handler` works as intended.
        """

        response = self.app.post("/api/login/available")
        self.assertEqual(response.status_code, 200)

        available_request = response.get_json()
        available_request.sort()
        self.assertEqual(available_request, ["google"])

    def test_google_token_login_no_json(self):
        """
        Checks that `herdbook.google_token_login` returns 415 when request
        is not JSON (missing Content-Type: application/json).
        """
        # Send POST without JSON content-type - should return 415 Unsupported Media Type
        response = self.app.post("/api/auth/google", data="not json")
        self.assertEqual(response.status_code, 415)

    def test_google_token_login_missing_credential(self):
        """
        Checks that `herdbook.google_token_login` returns 400 when credential
        is missing from the JSON body.
        """
        response = self.app.post("/api/auth/google", json={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "Missing Google credential"})

    def test_google_token_login_empty_credential(self):
        """
        Checks that `herdbook.google_token_login` returns 400 when credential
        is empty.
        """
        response = self.app.post("/api/auth/google", json={"credential": ""})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "Missing Google credential"})

    def test_google_token_login_rejected_token(self):
        """
        Checks that `herdbook.google_token_login` returns 401 with the
        documented error shape when token verification fails — e.g. a Google
        ID token minted for another OAuth app (wrong audience).
        """
        with mock.patch(
            "google.oauth2.id_token.verify_oauth2_token",
            side_effect=ValueError("Token has wrong audience"),
        ):
            response = self.app.post("/api/auth/google", json={"credential": "token-for-another-app"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"error": "Invalid Google token"})

    def test_google_token_login_pins_audience(self):
        """
        Checks that `herdbook.google_token_login` passes the configured GIS
        client id as the expected audience to Google token verification.
        """
        with (
            mock.patch.object(herdbook, "GOOGLE_CLIENT_ID", "gis-client.apps.googleusercontent.com"),
            mock.patch(
                "google.oauth2.id_token.verify_oauth2_token",
                side_effect=ValueError("Token has wrong audience"),
            ) as verify,
        ):
            response = self.app.post("/api/auth/google", json={"credential": "some-token"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(verify.call_args.args[2], "gis-client.apps.googleusercontent.com")

    def test_no_link_without_auth(self):
        """
        Checks that `herdbook.external_link_handler` does not run without
        the user being authenticated.
        """

        response = self.app.post("/api/link/somservice")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), None)

    def test_unlink_method(self):
        """
        Checks that `herdbook.external_unlink_handler` works as intended.
        """

        # jscpd:ignore-start
        with self.app as context:
            # login
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})

            admin_user = db.User.select().where(db.User.email == self.admin.email).get()
            db.Authenticators(user=admin_user.id, auth="testauth", auth_data="data").save()

            response = context.post("/api/unlink/testauth")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data.strip(), b"1")
            # jscpd:ignore-end

            with self.assertRaises(type(db.Authenticators.DoesNotExist())):
                db.Authenticators.select().where(
                    db.Authenticators.user == admin_user.id,
                    db.Authenticators.auth == "testauth",
                ).get()

    def test_linked_method(self):
        """
        Checks that `herdbook.external_linked_accounts_handler` works as intended.
        """
        # jscpd:ignore-start
        with self.app as context:
            # login
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})

            admin_user = db.User.select().where(db.User.email == self.admin.email).get()
            db.Authenticators(user=admin_user.id, auth="testauth", auth_data="data").save()

            response = context.post("/api/linked")
            # jscpd:ignore-end

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), ["testauth"])

            response = context.post("/api/unlink/testauth")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data.strip(), b"1")

            response = context.post("/api/linked")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), None)

    def test_unlink_get_does_not_unlink(self):
        """A GET (cross-site navigation, <img src>) must not unlink the caller's login.

        The route is POST-only, so a GET falls through to the SPA catch-all."""
        db.Authenticators.create(user=self.viewer.id, auth="google", auth_data="google-subject-viewer")
        cross_site = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        with self.app as client:
            client.post("/api/login", json={"username": self.viewer.email, "password": "pass"})
            for headers in (cross_site, {}):
                with self.subTest(headers=headers):
                    response = client.get("/api/unlink/google", headers=headers)
                    self.assertNotEqual(response.data.strip(), b"1")
                    remaining = (
                        db.Authenticators.select()
                        .where((db.Authenticators.user == self.viewer.id) & (db.Authenticators.auth == "google"))
                        .count()
                    )
                    self.assertEqual(remaining, 1)

    OAUTH_SITE = "https://gotlandskaninen.se"
    # None of these may survive. 'http:evil.example' and '////evil.example' are resolved by browsers to another host;
    # Werkzeug rewrites the backslash forms to on-site paths, but a relative URL is an allowlist all the same.
    OFFSITE_RETURN_TO = [
        "http:evil.example",
        "HTTP:evil.example/x",
        "https:/\\evil.example",
        "//evil.example",
        "///evil.example",
        "////evil.example",
        "/\\evil.example",
        "/\t/evil.example",
        "\\\\evil.example",
        "https://evil.example/",
        "javascript://gotlandskaninen.se/%0aalert(1)",
    ]

    def _post_oauth_location(self, return_to):
        """Location of the redirect that ends /api/login/google when `return_to` was saved before OAuth."""
        user = mock.Mock(validated=True, uuid="u-1", username="x", email="x@example.com", id=1)
        client = APP.test_client()
        with client.session_transaction(base_url=self.OAUTH_SITE) as sess:
            sess["return_to_after_oauth"] = return_to
        with (
            mock.patch("utils.external_auth.available_methods", return_value=["google"]),
            mock.patch("utils.external_auth.authorized", return_value=True),
            mock.patch("utils.external_auth.get_persistent", return_value="pid"),
            mock.patch("utils.data_access.authenticate_with_credentials", return_value=user),
            mock.patch("utils.data_access.fetch_user_info", return_value=user),
            mock.patch("utils.external_auth.google_userinfo", return_value=None),
            mock.patch("utils.external_auth.google_idtoken", return_value=None),
            mock.patch("herdbook.login_user"),
            mock.patch("herdbook._link_member_if_any"),
            mock.patch.object(APP.session_interface, "regenerate", create=True),
        ):
            response = client.get("/api/login/google", base_url=self.OAUTH_SITE)
        self.assertEqual(response.status_code, 302, response.data[:200])
        return response.headers["Location"]

    def test_oauth_return_to_never_leaves_the_site(self):
        """The saved return_to becomes the post-OAuth Location; only same-site targets may pass."""
        self.assertEqual(self._post_oauth_location("/stamboken/x?y=1#z"), "/stamboken/x?y=1#z")
        self.assertEqual(self._post_oauth_location(f"{self.OAUTH_SITE}/stamboken/x"), f"{self.OAUTH_SITE}/stamboken/x")
        leaked = {
            target: location
            for target in self.OFFSITE_RETURN_TO
            if (location := self._post_oauth_location(target)) != "/"
        }
        self.assertEqual(leaked, {}, "return_to values that were not replaced by the default Location")

    def test_safe_redirect_url(self):
        """same-site paths and same-host http(s) URLs (the Referer fallback) are kept, the rest is not."""
        keep = [
            "/",
            "/stamboken/x",
            "/a/b?c=d#e",
            "/.//path",
            f"{self.OAUTH_SITE}/api/login",
            "http://gotlandskaninen.se/x",
        ]
        drop = [
            None,
            "",
            "foo/bar",
            "?x",
            " /x",
            "/x\ny",
            "/ok\\path",
            "//gotlandskaninen.se/x",
            *self.OFFSITE_RETURN_TO,
        ]
        with APP.test_request_context("/", base_url=self.OAUTH_SITE):
            for url in keep:
                with self.subTest(keep=url):
                    self.assertEqual(herdbook._safe_redirect_url(url), url)
            for url in drop:
                with self.subTest(drop=url):
                    self.assertEqual(herdbook._safe_redirect_url(url), "/")

    @unittest.skip("Temporarily disabled: MuPDF PDF generation fails and corrupts test state")
    def test_certificate_ops(self):
        """
        Checks that certificate endpoints issuing, updating and verifying work as intended.
        """

        individual = self.individuals[3].number
        individual_2 = self.individuals[4].number

        valid_issue_form = {
            "color_id": 3,
            "birth_date": datetime.now() - timedelta(days=30),
            "litter_size": 5,
            "litter_size6w": 4,
        }
        valid_update_form = {
            "color_id": 2,
            "birth_date": datetime.now() - timedelta(days=30),
            "litter_size": 5,
            "litter_size6w": 4,
        }

        mock = mock_aws()
        mock.start()
        self.addCleanup(mock.stop)  # Ensure mock is stopped even if test fails

        # not logged in
        self.assertEqual(self.app.post("/api/certificates/issue/{individual}").get_json(), None)
        self.assertEqual(self.app.patch("/api/certificates/update/{individual}").get_json(), None)

        with self.app as context:
            # login
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})

            # Issue a certificate
            first_pdf_response = context.post(f"/api/certificates/issue/{individual}", json=valid_issue_form)
            digital_certificate = db.Individual.get(self.individuals[3].id).digital_certificate
            self.assertEqual(digital_certificate, 100000)
            self.assertEqual(first_pdf_response.headers["Content-Type"], "application/pdf")
            self.assertEqual(first_pdf_response.status_code, 200)

            # Issue a second certificate
            pdf_response = context.post(f"/api/certificates/issue/{individual_2}", json=valid_issue_form)
            digital_certificate = db.Individual.get(self.individuals[4].id).digital_certificate
            self.assertEqual(digital_certificate, 100001)
            self.assertEqual(pdf_response.headers["Content-Type"], "application/pdf")
            self.assertEqual(pdf_response.status_code, 200)

            # Issue a certificate again
            response = context.post(f"/api/certificates/issue/{individual_2}", json=valid_issue_form)
            self.assertEqual(response.status_code, 400)

            # Download a certificate
            download_response = context.get(f"/api/certificates/issue/{individual}")
            self.assertEqual(download_response.headers["Content-Type"], "application/pdf")
            self.assertEqual(download_response.status_code, 200)
            self.assertEqual(download_response.data, first_pdf_response.data)

            # Download a certificate from a non-existing individual
            download_response = context.get("/api/certificates/issue/doesnotexist")
            self.assertEqual(download_response.status_code, 404)

            # Update a certificate
            pdf_response = context.patch(f"/api/certificates/update/{individual}", json=valid_update_form)
            self.assertEqual(pdf_response.status_code, 200)
            self.assertEqual(pdf_response.headers["Content-Type"], "application/pdf")
            color = db.Individual.get(self.individuals[0].id).color.id
            self.assertEqual(color, 1)

            # Get the preview of a unsigned certificate
            unsigned_response = context.get(f"/api/certificates/preview/{individual}")
            self.assertEqual(unsigned_response.status_code, 200)
            self.assertEqual(unsigned_response.headers["Content-Type"], "application/pdf")

            unsigned_response = context.post(f"/api/certificates/preview/{individual}", json=valid_issue_form)
            self.assertEqual(unsigned_response.status_code, 200)
            self.assertEqual(unsigned_response.headers["Content-Type"], "application/pdf")
            # Verify using an unsigned certificate
            response = context.post(f"/api/certificates/verify/{individual}", data=unsigned_response.data)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(
                response.get_json(),
                {"response": "The uploaded certificate is not valid"},
            )

            # Verify using some random data
            response = context.post(f"/api/certificates/verify/{individual}", data=b"some random bytes")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(
                response.get_json(),
                {"response": "The uploaded certificate is not valid"},
            )

            # Verify an old certificate
            response = context.post(f"/api/certificates/verify/{individual}", data=first_pdf_response.data)
            self.assertEqual(response.status_code, 202)

            # Verify a valid certificate
            response = context.post(f"/api/certificates/verify/{individual}", data=pdf_response.data)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), {"response": "Certificate is valid"})

    def test_certificate_issue_without_signing_key_returns_503(self):
        """When cert files are missing, issuing a certificate returns 503."""
        from pathlib import Path
        from unittest.mock import patch

        import utils.settings as settings

        individual = self.individuals[3].number
        valid_issue_form = {
            "color_id": 3,
            "birth_date": datetime.now() - timedelta(days=30),
            "litter_size": 5,
            "litter_size6w": 4,
        }

        mock_s3 = mock_aws()
        mock_s3.start()
        self.addCleanup(mock_s3.stop)

        with self.app as context:
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            with patch.object(settings.certs, "private_key", Path("/nonexistent/key.pem")):
                response = context.post(f"/api/certificates/issue/{individual}", json=valid_issue_form)
            self.assertEqual(response.status_code, 503)


class TestAPIEndpoints(FlaskTest):
    """
    Additional API endpoint tests for health, individuals, herds, and genebanks.
    """

    def test_health_endpoint(self):
        """Test the health check endpoint."""
        response = self.app.get("/api/health")
        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["database"], "connected")
        self.assertIn("timestamp", data)

    def test_cors_only_localhost_in_development(self):
        """Foreign origins never get CORS headers; localhost only in development."""
        for env, origin, allowed in [
            ("production", "https://example.org", False),
            ("production", "http://localhost:3000", False),
            ("development", "https://example.org", False),
            ("development", "http://localhost:3000", True),
        ]:
            with self.subTest(env=env, origin=origin), mock.patch.dict(os.environ, {"FLASK_ENV": env}):
                response = self.app.get("/api/health", headers={"Origin": origin})
                self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), origin if allowed else None)
                self.assertEqual("Access-Control-Allow-Credentials" in response.headers, allowed)

    def _credentialed_cors_for(self, response, origin):
        return (
            response.headers.get("Access-Control-Allow-Origin") == origin
            and response.headers.get("Access-Control-Allow-Credentials") == "true"
        )

    def test_foreign_origin_preflight_not_granted(self):
        """A foreign site must not pass the credentialed preflight for an admin endpoint."""
        response = self.app.options(
            "/api/v2/admin/role",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertFalse(self._credentialed_cors_for(response, "https://evil.example"), dict(response.headers))

    def test_authenticated_response_not_readable_by_foreign_origin(self):
        """An admin's /api/user response must not be readable from a foreign origin."""
        with self.app as client:
            client.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            response = client.get("/api/user", headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self._credentialed_cors_for(response, "https://evil.example"), dict(response.headers))

    def test_get_individual(self):
        """Test getting individual information."""
        individual = self.individuals[0]

        # Test without login - API paths return 401 JSON
        response = self.app.get(f"/api/individual/{individual.number}")
        self.assertEqual(response.status_code, 401)

        # Test with login
        with self.app as context:
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            response = context.get(f"/api/individual/{individual.number}")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIsNotNone(data)
            self.assertEqual(data["number"], individual.number)

    def test_get_herd_info(self):
        """Test getting herd information."""
        herd = self.herds[0]

        # Test without login - API paths return 401 JSON
        response = self.app.get(f"/api/herd/{herd.herd}")
        self.assertEqual(response.status_code, 401)

        # Test with login
        with self.app as context:
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            response = context.get(f"/api/herd/{herd.herd}")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIsNotNone(data)
            self.assertEqual(data["herd"], herd.herd)
            self.assertEqual(data["herd_name"], herd.herd_name)

    def test_get_genebanks(self):
        """Test getting list of genebanks."""
        # Test without login - API paths return 401 JSON
        response = self.app.get("/api/genebanks")
        self.assertEqual(response.status_code, 401)

        # Test with login
        with self.app as context:
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            response = context.get("/api/genebanks")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIsNotNone(data)
            self.assertIn("genebanks", data)
            self.assertGreater(len(data["genebanks"]), 0)

    def test_get_genebank_info(self):
        """Test getting specific genebank information."""
        genebank = self.genebanks[0]

        # Test without login - API paths return 401 JSON
        response = self.app.get(f"/api/genebank/{genebank.id}")
        self.assertEqual(response.status_code, 401)

        # Test with login
        with self.app as context:
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            response = context.get(f"/api/genebank/{genebank.id}")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIsNotNone(data)
            self.assertEqual(data["id"], genebank.id)
            self.assertEqual(data["name"], genebank.name)

    def test_get_genebank_individuals(self):
        """Test getting individuals for a genebank."""
        genebank = self.genebanks[0]

        # Test without login - API paths return 401 JSON
        response = self.app.get(f"/api/genebank/{genebank.id}/individuals")
        self.assertEqual(response.status_code, 401)

        # Test with login
        with self.app as context:
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            response = context.get(f"/api/genebank/{genebank.id}/individuals")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIsNotNone(data)
            self.assertIn("individuals", data)


class TestPaginatedIndividuals(FlaskTest):
    """
    Tests for GET /api/individuals — paginated individual listing endpoint.
    """

    def setUp(self):
        super().setUp()
        # Set names on test individuals for search testing
        self.individuals[0].name = "Bruno"
        self.individuals[0].save()
        self.individuals[1].name = "Bella"
        self.individuals[1].save()
        self.individuals[2].name = "Charlie"
        self.individuals[2].save()
        self.individuals[3].name = "Bruno Junior"
        self.individuals[3].save()
        self.individuals[4].name = "Astrid"
        self.individuals[4].save()
        # Set sex for sex-filter tests
        self.individuals[0].sex = "male"
        self.individuals[0].save()
        self.individuals[1].sex = "female"
        self.individuals[1].save()
        self.individuals[3].sex = "male"
        self.individuals[3].save()

        # Make individuals[0] ("Bruno") genuinely active:
        # needs certificate, active herd, no death, no castration, recent herd tracking
        self.individuals[0].certificate = "CERT-001"
        self.individuals[0].save()
        self.herds[0].is_active = True
        self.herds[0].save()
        # Update herd tracking to be recent (within 13 months) — test-only in-place edit
        db.HerdTracking.update(herd_tracking_date=datetime.now() - timedelta(days=30)).where(
            db.HerdTracking.id == self.herd_tracking[0].id
        ).execute()

        # Make individuals[1] ("Bella") dead (generic "död") for status filter tests
        self.individuals[1].death_date = datetime(2024, 6, 1)
        self.individuals[1].death_note = "Ålderssvaghet"
        self.individuals[1].save()

        # Create additional individuals for death-status filter coverage
        death_breeding = db.Breeding.create(
            breed_date=datetime(2020, 1, 1),
            birth_date=datetime(2020, 2, 1),
            litter_size=4,
            litter_size6w=4,
            breeding_herd_id=self.herds[0],
        )
        self._slaktad = db.Individual.create(
            origin_herd=self.herds[0],
            breeding=death_breeding,
            number="G1-SLAGT",
            name="Slaktad Kanin",
            death_date=datetime(2024, 1, 1),
            death_note="Slaktad för kött",
        )
        ht_row(
            "BIRTH",
            herd=self.herds[0],
            individual=self._slaktad,
            herd_tracking_date=datetime(2021, 2, 1),
        )
        self._avlivad = db.Individual.create(
            origin_herd=self.herds[0],
            breeding=death_breeding,
            number="G1-AVLIV",
            name="Avlivad Kanin",
            death_date=datetime(2024, 2, 1),
            death_note="Avlivad pga sjukdom",
        )
        ht_row(
            "BIRTH",
            herd=self.herds[0],
            individual=self._avlivad,
            herd_tracking_date=datetime(2021, 2, 1),
        )
        self._forsvunnen = db.Individual.create(
            origin_herd=self.herds[0],
            breeding=death_breeding,
            number="G1-RYMD",
            name="Försvunnen Kanin",
            death_note="Rymde från hagen",
        )
        ht_row(
            "BIRTH",
            herd=self.herds[0],
            individual=self._forsvunnen,
            herd_tracking_date=datetime(2021, 2, 1),
        )

    def _login(self, context, user):
        context.post("/api/login", json={"username": user.email, "password": "pass"})

    def test_unauthenticated_returns_401_json(self):
        with self.app as ctx:
            resp = ctx.get("/api/individuals")
            self.assertEqual(resp.status_code, 401)
            self.assertEqual(resp.content_type, "application/problem+json")
            data = resp.get_json()
            self.assertEqual(data["type"], "about:blank")
            self.assertEqual(data["title"], "Autentisering krävs")
            self.assertEqual(data["status"], 401)
            self.assertIn("detail", data)

    def test_basic_pagination_response_shape(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?page=1&per_page=50")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            for key in ("items", "total_count", "page", "per_page", "total_pages"):
                self.assertIn(key, data, f"Missing key: {key}")
            self.assertEqual(data["page"], 1)
            self.assertEqual(data["per_page"], 50)
            self.assertIsInstance(data["items"], list)
            self.assertGreater(data["total_count"], 0)

    def test_item_fields(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals")
            data = resp.get_json()
            item = data["items"][0]
            expected_fields = {
                "number",
                "name",
                "sex",
                "birth_date",
                "status",
                "herd",
                "color",
                "has_photo",
                "litter_size",
                "litter_size6w",
                "mother_number",
                "mother_name",
                "father_number",
                "father_name",
            }
            missing = expected_fields - set(item.keys())
            self.assertFalse(missing, f"Missing fields: {missing}")

    def test_parent_and_litter_fields_values(self):
        """Verify parent/litter fields contain correct data from Breeding."""
        with self.app as ctx:
            self._login(ctx, self.admin)
            # individuals[0] = "G1-2111", breeding[0] has mother=parents[0], father=parents[1]
            resp = ctx.get("/api/individuals?search=G1-2111")
            data = resp.get_json()
            self.assertEqual(data["total_count"], 1)
            item = data["items"][0]
            self.assertEqual(item["number"], "G1-2111")
            self.assertEqual(item["litter_size"], 2)
            self.assertEqual(item["litter_size6w"], 2)
            self.assertEqual(item["mother_number"], self.parents[0].number)
            self.assertEqual(item["father_number"], self.parents[1].number)
            # parents don't have names set in test data, so these should be None
            self.assertIsNone(item["mother_name"])
            self.assertIsNone(item["father_name"])

    def test_individual_without_breeding(self):
        """Individual with no Breeding FK should return null parent/litter fields."""
        ind = db.Individual.create(
            origin_herd=self.herds[0],
            breeding=None,
            number="G1-NOBREED",
            name="No Breeding",
        )
        ht_row(
            "BIRTH",
            herd=self.herds[0],
            individual=ind,
            herd_tracking_date=datetime(2023, 3, 1),
        )
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?search=G1-NOBREED")
            data = resp.get_json()
            self.assertEqual(data["total_count"], 1)
            item = data["items"][0]
            self.assertIsNone(item["litter_size"])
            self.assertIsNone(item["mother_number"])
            self.assertIsNone(item["father_number"])
            self.assertIsNone(item["birth_date"])

    def test_individual_without_herd_tracking(self):
        """Individual with no HerdTracking should still appear (falls back to origin_herd)."""
        b = db.Breeding.create(
            breed_date=datetime(2023, 1, 1),
            birth_date=datetime(2023, 2, 1),
            litter_size=1,
            breeding_herd_id=self.herds[0],
        )
        db.Individual.create(
            origin_herd=self.herds[0],
            breeding=b,
            number="G1-NOTRACK",
            name="No Tracking",
        )
        # No HerdTracking created — should use origin_herd
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?search=G1-NOTRACK")
            data = resp.get_json()
            self.assertEqual(data["total_count"], 1)
            item = data["items"][0]
            self.assertEqual(item["herd"], self.herds[0].herd)

    def test_pagination_page_and_total(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?page=1&per_page=2")
            data = resp.get_json()
            self.assertEqual(data["per_page"], 2)
            self.assertEqual(len(data["items"]), 2)
            total = data["total_count"]
            self.assertGreater(total, 2)
            import math

            self.assertEqual(data["total_pages"], math.ceil(total / 2))

    def test_pagination_second_page(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp1 = ctx.get("/api/individuals?page=1&per_page=2")
            resp2 = ctx.get("/api/individuals?page=2&per_page=2")
            items1 = resp1.get_json()["items"]
            items2 = resp2.get_json()["items"]
            numbers1 = {i["number"] for i in items1}
            numbers2 = {i["number"] for i in items2}
            self.assertTrue(numbers1.isdisjoint(numbers2), "Pages should not overlap")

    def test_per_page_max_200(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?per_page=500")
            data = resp.get_json()
            self.assertEqual(data["per_page"], 200)

    def test_search_by_name(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?search=Bruno")
            data = resp.get_json()
            names = [i["name"] for i in data["items"]]
            self.assertTrue(all("Bruno" in n for n in names if n), f"Unexpected names: {names}")
            self.assertEqual(data["total_count"], 2)  # Bruno and Bruno Junior

    def test_search_by_number_partial(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            # Partial genbanksnummer search — must use contains(), not exact match
            resp = ctx.get("/api/individuals?search=G1-21")
            data = resp.get_json()
            self.assertGreater(data["total_count"], 1, "Partial number search should match multiple")
            numbers = [i["number"] for i in data["items"]]
            self.assertTrue(all("G1-21" in n for n in numbers))

    def test_search_case_insensitive(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?search=bruno")
            data = resp.get_json()
            self.assertEqual(data["total_count"], 2)

    def test_genebank_filter(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            # Gotland genebank
            resp = ctx.get(f"/api/individuals?genebank_id={self.genebanks[0].id}")
            data = resp.get_json()
            gotland_count = data["total_count"]
            # Mellerud genebank
            resp2 = ctx.get(f"/api/individuals?genebank_id={self.genebanks[1].id}")
            data2 = resp2.get_json()
            mellerud_count = data2["total_count"]
            # All
            resp_all = ctx.get("/api/individuals")
            all_count = resp_all.get_json()["total_count"]
            self.assertEqual(gotland_count + mellerud_count, all_count)

    def test_status_filter_active(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?status=active")
            data = resp.get_json()
            self.assertGreater(data["total_count"], 0, "Expected at least one active individual")
            for item in data["items"]:
                self.assertEqual(item["status"], "active", f"{item['number']} has status={item['status']}")

    def test_status_filter_dead(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?status=dead")
            data = resp.get_json()
            self.assertGreater(data["total_count"], 0, "Expected at least one dead individual")
            for item in data["items"]:
                self.assertEqual(item["status"], "död", f"{item['number']} has status={item['status']}")

    def test_status_filter_slaktad(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?status=slaktad")
            data = resp.get_json()
            self.assertGreater(data["total_count"], 0, "Expected at least one slaktad individual")
            for item in data["items"]:
                self.assertEqual(item["status"], "slaktad", f"{item['number']} has status={item['status']}")

    def test_status_filter_avlivad(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?status=avlivad")
            data = resp.get_json()
            self.assertGreater(data["total_count"], 0, "Expected at least one avlivad individual")
            for item in data["items"]:
                self.assertEqual(item["status"], "avlivad", f"{item['number']} has status={item['status']}")

    def test_status_filter_forsvunnen(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?status=försvunnen")
            data = resp.get_json()
            self.assertGreater(data["total_count"], 0, "Expected at least one försvunnen individual")
            for item in data["items"]:
                self.assertEqual(
                    item["status"],
                    "försvunnen",
                    f"{item['number']} has status={item['status']}",
                )

    def test_sort_by_name_asc(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?sort=name&order=asc")
            data = resp.get_json()
            named = [i["name"] for i in data["items"] if i["name"]]
            self.assertEqual(named, sorted(named))

    def test_sort_by_name_desc(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?sort=name&order=desc")
            data = resp.get_json()
            named = [i["name"] for i in data["items"] if i["name"]]
            self.assertEqual(named, sorted(named, reverse=True))

    def test_swedish_collation_sort(self):
        """Å, Ä, Ö should sort after Z in Swedish alphabetical order."""
        # Create individuals with Swedish names
        swedish_breeding = db.Breeding.create(
            breed_date=datetime(2023, 1, 1),
            birth_date=datetime(2023, 2, 1),
            litter_size=4,
            breeding_herd_id=self.herds[0],
        )
        swedish_names = ["Zebra", "Ärlig", "Åsa", "Östen"]
        for idx, name in enumerate(swedish_names):
            ind = db.Individual.create(
                origin_herd=self.herds[0],
                breeding=swedish_breeding,
                number=f"G1-SV{idx}",
                name=name,
            )
            ht_row(
                "BIRTH",
                herd=self.herds[0],
                individual=ind,
                herd_tracking_date=datetime(2023, 3, 1),
            )

        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?sort=name&order=asc&search=G1-SV")
            data = resp.get_json()
            names = [i["name"] for i in data["items"]]
            # Swedish order: Zebra < Åsa < Ärlig < Östen
            self.assertEqual(names, ["Zebra", "Åsa", "Ärlig", "Östen"])

    def test_sort_by_number(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?sort=number&order=asc")
            data = resp.get_json()
            numbers = [i["number"] for i in data["items"]]
            self.assertEqual(numbers, sorted(numbers))

    def test_sort_by_birth_date(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?sort=birth_date&order=asc")
            data = resp.get_json()
            dates = [i["birth_date"] or "" for i in data["items"]]
            self.assertEqual(dates, sorted(dates))

    def test_access_control_viewer_sees_own_genebank_only(self):
        with self.app as ctx:
            self._login(ctx, self.viewer)
            resp = ctx.get("/api/individuals")
            data = resp.get_json()
            # Viewer has access to Gotland only — should not see Mellerud individuals
            for item in data["items"]:
                self.assertNotIn("M3", item["number"], f"Viewer should not see Mellerud individual {item['number']}")

    def test_access_control_viewer_denied_other_genebank(self):
        with self.app as ctx:
            self._login(ctx, self.viewer)
            # Request Mellerud genebank explicitly
            resp = ctx.get(f"/api/individuals?genebank_id={self.genebanks[1].id}")
            data = resp.get_json()
            self.assertEqual(data["total_count"], 0)

    def test_defaults(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals")
            data = resp.get_json()
            self.assertEqual(data["page"], 1)
            self.assertEqual(data["per_page"], 50)

    def test_response_time_under_500ms(self):
        """Smoke test: verifies the query plan (LEFT OUTER JOINs + count + paginate)
        stays under 500ms with ~200 rows. This catches obvious regressions (N+1,
        missing indices) but does NOT validate the 15k+ production workload from AC6.
        Production SLA must be verified via load testing against staging.
        """
        import time

        # Seed 200 extra individuals to exercise the query plan more realistically
        for i in range(200):
            b = db.Breeding.create(
                breed_date=datetime(2023, 1, 1),
                birth_date=datetime(2023, 2, 1),
                litter_size=1,
                breeding_herd_id=self.herds[0],
            )
            ind = db.Individual.create(
                origin_herd=self.herds[0],
                breeding=b,
                number=f"G1-PERF{i:03d}",
                name=f"PerfTest{i}",
                sex="male",
            )
            ht_row(
                "BIRTH",
                herd=self.herds[0],
                individual=ind,
                herd_tracking_date=datetime.now() - timedelta(days=10),
            )
        with self.app as ctx:
            self._login(ctx, self.admin)
            start = time.monotonic()
            resp = ctx.get("/api/individuals?per_page=50")
            elapsed_ms = (time.monotonic() - start) * 1000
            self.assertEqual(resp.status_code, 200)
            self.assertLess(elapsed_ms, 500, f"Default page took {elapsed_ms:.0f}ms (limit: 500ms)")

    def test_status_filter_inactive(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?status=inactive")
            data = resp.get_json()
            self.assertGreater(data["total_count"], 0, "Expected at least one inactive individual")
            for item in data["items"]:
                self.assertEqual(item["status"], "inactive", f"{item['number']} has status={item['status']}")

    def test_status_filter_matches_derived_status(self):
        """Each status filter must only return items whose derived status matches."""
        with self.app as ctx:
            self._login(ctx, self.admin)
            for status_val in ("active", "inactive"):
                resp = ctx.get(f"/api/individuals?status={status_val}")
                data = resp.get_json()
                for item in data["items"]:
                    self.assertEqual(
                        item["status"],
                        status_val,
                        f"?status={status_val} returned item with status={item['status']}",
                    )

    def test_deterministic_pagination_no_drift(self):
        """Pages should not overlap when using default sort."""
        with self.app as ctx:
            self._login(ctx, self.admin)
            all_numbers = []
            resp = ctx.get("/api/individuals")
            total = resp.get_json()["total_count"]
            for page in range(1, total + 1):
                resp = ctx.get(f"/api/individuals?page={page}&per_page=1")
                items = resp.get_json()["items"]
                if not items:
                    break
                all_numbers.append(items[0]["number"])
            self.assertEqual(len(all_numbers), len(set(all_numbers)), "Duplicate items across pages")

    def test_sex_filter_male(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?sex=male")
            data = resp.get_json()
            self.assertGreater(data["total_count"], 0)
            for item in data["items"]:
                self.assertEqual(item["sex"], "male", f"{item['number']} is not male")

    def test_sex_filter_female(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?sex=female")
            data = resp.get_json()
            self.assertGreater(data["total_count"], 0)
            for item in data["items"]:
                self.assertEqual(item["sex"], "female", f"{item['number']} is not female")

    def test_sex_filter_combined_with_search(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            resp = ctx.get("/api/individuals?sex=male&search=Bruno")
            data = resp.get_json()
            self.assertEqual(data["total_count"], 2)  # Bruno and Bruno Junior, both male
            for item in data["items"]:
                self.assertEqual(item["sex"], "male")
                self.assertIn("Bruno", item["name"])

    def test_herd_id_sorts_own_herd_first(self):
        with self.app as ctx:
            self._login(ctx, self.admin)
            # G1 is a Gotland herd; request with herd_id=G1
            resp = ctx.get(f"/api/individuals?herd_id={self.herds[0].herd}")
            data = resp.get_json()
            items = data["items"]
            # Find where the first non-G1 individual appears
            own_herd_items = [i for i in items if i["herd"] == self.herds[0].herd]
            other_items = [i for i in items if i["herd"] != self.herds[0].herd]
            if own_herd_items and other_items:
                # All own-herd items should come before any other-herd items
                own_indices = [items.index(i) for i in own_herd_items]
                other_indices = [items.index(i) for i in other_items]
                self.assertLess(
                    max(own_indices),
                    min(other_indices),
                    "Own-herd individuals should sort before others",
                )


class TestUnauthorizedHandler(FlaskTest):
    """Tests that the unauthorized handler returns JSON 401 for /api/* requests."""

    def test_api_endpoint_returns_401_json_not_redirect(self):
        """GET /api/profile without session → 401 JSON, not 302 redirect."""
        with self.app as ctx:
            response = ctx.get("/api/profile")
            self.assertEqual(response.status_code, 401)
            data = response.get_json()
            self.assertIsNotNone(data, "Response should be JSON, not HTML/redirect")
            self.assertEqual(data["status"], "error")
            self.assertEqual(data["message"], "Authentication required")

    def test_api_endpoint_returns_401_json_with_accept_wildcard(self):
        """GET /api/profile with Accept: */* → 401 JSON (the RTK Query scenario)."""
        with self.app as ctx:
            response = ctx.get("/api/profile", headers={"Accept": "*/*"})
            self.assertEqual(response.status_code, 401)
            data = response.get_json()
            self.assertIsNotNone(data, "Accept: */* should still get JSON 401")
            self.assertEqual(data["status"], "error")

    def test_api_endpoint_returns_401_json_with_accept_html(self):
        """GET /api/profile with Accept: text/html → still 401 JSON (it's an API path)."""
        with self.app as ctx:
            response = ctx.get("/api/profile", headers={"Accept": "text/html"})
            self.assertEqual(response.status_code, 401)
            data = response.get_json()
            self.assertIsNotNone(data, "API paths should always return JSON 401 regardless of Accept header")
            self.assertEqual(data["status"], "error")


class TestGeneticsParameterBounds(FlaskTest):
    """/gene-drop/ and /pedigree-completeness/ clamp their cost parameters, as breeding-suggestions does."""

    def _login_manager(self, client):
        client.post("/api/login", json={"username": self.manager.email, "password": "pass"})

    def test_gene_drop_iterations_are_clamped(self):
        gb = self.genebanks[0].id
        service = mock.patch.object(herdbook.genetics, "get_gene_drop_statistics", return_value={})
        with self.app as client, service as m:
            self._login_manager(client)
            for value, expected in ((1_000_000_000, 10000), (0, 1), (-1, 1), (500, 500)):
                m.reset_mock()
                resp = client.get(f"/api/{gb}/gene-drop/?n_iterations={value}")
                passed = m.call_args.kwargs.get("n_iterations") if m.called else None
                self.assertEqual(
                    (resp.status_code, passed),
                    (200, expected),
                    f"n_iterations={value}: status {resp.status_code}, service got n_iterations={passed}",
                )

    def test_pedigree_completeness_generations_are_clamped(self):
        gb = self.genebanks[0].id
        service = mock.patch.object(herdbook.genetics, "get_pedigree_completeness", return_value={})
        with self.app as client, service as m:
            self._login_manager(client)
            for value, expected in ((50000, 10), (0, 1), (5, 5)):
                m.reset_mock()
                resp = client.get(f"/api/{gb}/pedigree-completeness/?max_generations={value}")
                passed = m.call_args.kwargs.get("max_generations") if m.called else None
                self.assertEqual(
                    (resp.status_code, passed),
                    (200, expected),
                    f"max_generations={value}: status {resp.status_code}, service got {passed}",
                )


class TestUpdateHerdAllowList(FlaskTest):
    """
    update_herd (legacy PATCH /api/manage/herd and PATCH /api/v2/herd/<code>)
    writes real columns only, and id/herd/genebank/membership are admin-only.
    """

    def _client_for(self, email):
        client = self.app.application.test_client(use_cookies=True)
        resp = client.post("/api/login", json={"username": email, "password": "pass"})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        return client

    def test_owner_cannot_move_herd_to_other_genebank_legacy(self):
        g1, gb0, gb1 = self.herds[0], self.genebanks[0], self.genebanks[1]
        client = self._client_for(self.owner.email)
        self.assertNotIn(gb1.id, db.User.get_by_id(self.owner.id).accessible_genebanks)
        resp = client.patch("/api/manage/herd", json={"id": g1.id, "genebank": gb1.id})
        moved_to = db.Herd.get_by_id(g1.id).genebank_id
        self.assertEqual(
            moved_to,
            gb0.id,
            f"owner moved G1 into genebank {moved_to} (response {resp.get_json()}); "
            f"owner's accessible_genebanks now {db.User.get_by_id(self.owner.id).accessible_genebanks}",
        )

    def test_owner_cannot_move_herd_to_other_genebank_v2(self):
        g1, gb0, gb1 = self.herds[0], self.genebanks[0], self.genebanks[1]
        client = self._client_for(self.owner.email)
        before = client.get(f"/api/v2/individual/{self.individuals[4].number}").status_code
        resp = client.patch(f"/api/v2/herd/{g1.herd}", json={"genebank": gb1.id})
        after = client.get(f"/api/v2/individual/{self.individuals[4].number}").status_code
        moved_to = db.Herd.get_by_id(g1.id).genebank_id
        self.assertEqual(
            moved_to,
            gb0.id,
            f"PATCH /api/v2/herd/G1 -> {resp.status_code}, G1 now in genebank {moved_to}; "
            f"GET Mellerud rabbit M3-2111 went {before} -> {after}",
        )

    def test_owner_cannot_rename_herd_code_into_other_genebanks_herd(self):
        g1 = self.herds[0]
        m3_rabbit = self.individuals[2]  # M3-2122, current herd M3 in genebanks[1]
        self.assertEqual(m3_rabbit.current_herd.herd, "M3")
        self.assertFalse(db.User.get_by_id(self.owner.id).can_edit(m3_rabbit.id))
        client = self._client_for(self.owner.email)
        resp = client.patch("/api/manage/herd", json={"id": g1.id, "herd": "M3"})
        code = db.Herd.get_by_id(g1.id).herd
        can_edit = db.User.get_by_id(self.owner.id).can_edit(m3_rabbit.id)
        self.assertFalse(
            can_edit,
            f"after PATCH {resp.get_json()} G1's code is {code!r} and the G1 owner can_edit "
            f"Mellerud's M3-2122 = {can_edit}",
        )

    def test_caretaker_grant_cannot_reassign_membership(self):
        g1 = self.herds[0]
        owner_ms = db.Membership.create(member_number=6, membership_status="active")
        g1.membership = owner_ms
        g1.save()
        main_user = da.register_user("maja@ex.se", "pass", username="maja")
        db.Member.create(membership=owner_ms, first_name="M", last_name="H", role="huvudmedlem", user=main_user)
        # Sune is huvudmedlem of his own (herd-less) membership B; an admin
        # granted him caretaker access to G1 (create_person_grant allows any herd).
        sune = da.register_user("sune@ex.se", "pass", username="sune")
        own_ms = db.Membership.create(member_number=7, membership_status="active")
        sune_person = db.Member.create(membership=own_ms, first_name="S", last_name="S", role="huvudmedlem", user=sune)
        db.HerdAccessGrant.create(member=sune_person, herd=g1, granted_by=self.admin)

        rabbit = self.individuals[0]  # G1-2111, current herd G1
        self.assertFalse(db.User.get_by_id(sune.id).can_transfer(rabbit.id))

        client = self._client_for("sune@ex.se")
        resp = client.patch("/api/manage/herd", json={"id": g1.id, "membership": own_ms.id})
        now_ms = db.Herd.get_by_id(g1.id).membership_id
        self.assertEqual(
            now_ms,
            owner_ms.id,
            f"caretaker PATCH {resp.get_json()} re-pointed G1.membership {owner_ms.id} -> {now_ms}; "
            f"caretaker can_transfer={db.User.get_by_id(sune.id).can_transfer(rabbit.id)}, "
            f"huvudmedlem still owns G1={g1.id in db.User.get_by_id(main_user.id).effective_herd_ids()}",
        )

    def test_fk_accessor_spellings_are_not_columns(self):
        """hasattr(herd, 'genebank_id') is true, but only the FK field name is a column."""
        g1, gb0 = self.herds[0], self.genebanks[0]
        ms = db.Membership.create(member_number=8, membership_status="active")
        client = self._client_for(self.owner.email)
        resp = client.patch(
            "/api/manage/herd",
            json={"id": g1.id, "genebank_id": self.genebanks[1].id, "membership_id": ms.id},
        )
        herd = db.Herd.get_by_id(g1.id)
        self.assertEqual(
            (herd.genebank_id, herd.membership_id),
            (gb0.id, None),
            f"PATCH {resp.get_json()} moved G1 via the *_id spelling",
        )

    def test_non_column_attributes_are_ignored(self):
        """Keys that only match a method or backref on the model must not be set."""
        g1 = self.herds[0]
        try:
            result = da.update_herd({"id": g1.id, "save": 1, "herd_name": "Ny"}, self.owner.uuid)
        except TypeError as exc:
            self.fail(f"update_herd setattr'd a method name and broke herd.save(): {exc!r}")
        self.assertEqual(result, {"status": "updated"})
        self.assertEqual(db.Herd.get_by_id(g1.id).herd_name, "Ny")

    def test_manager_cannot_move_herd_either(self):
        """Locked for every non-admin, managers included; their ordinary edits still work."""
        g1, gb0 = self.herds[0], self.genebanks[0]
        client = self._client_for(self.manager.email)
        resp = client.patch(
            "/api/manage/herd",
            json={"id": g1.id, "genebank": self.genebanks[1].id, "herd": "ZZ9", "herd_name": "Ny"},
        )
        herd = db.Herd.get_by_id(g1.id)
        self.assertEqual(resp.get_json(), {"status": "updated"})
        self.assertEqual((herd.genebank_id, herd.herd, herd.herd_name), (gb0.id, "G1", "Ny"))

    def test_admin_can_still_change_identity_columns(self):
        g1 = self.herds[0]
        client = self._client_for(self.admin.email)
        resp = client.patch("/api/manage/herd", json={"id": g1.id, "genebank": self.genebanks[1].id, "herd": "Z1"})
        herd = db.Herd.get_by_id(g1.id)
        self.assertEqual(resp.get_json(), {"status": "updated"})
        self.assertEqual((herd.genebank_id, herd.herd), (self.genebanks[1].id, "Z1"))

    def test_legacy_full_object_echo_still_updates_editable_fields(self):
        """The legacy SPA PATCHes the whole herd object back (ADR-0006): locked keys are dropped, the rest applies."""
        g1 = self.herds[0]
        client = self._client_for(self.owner.email)
        body = client.get(f"/api/herd/{g1.herd}").get_json()
        self.assertEqual(body["genebank"], g1.genebank_id)
        body["email"] = "ny@example.se"
        resp = client.patch("/api/manage/herd", json=body)
        herd = db.Herd.get_by_id(g1.id)
        self.assertEqual(resp.get_json(), {"status": "updated"})
        self.assertEqual((herd.email, herd.herd, herd.genebank_id), ("ny@example.se", "G1", self.genebanks[0].id))


class TestHerdPrivacyLevels(FlaskTest):
    """
    OAuth autocreate and add_user make every new account a viewer of both
    genebanks. A plain viewer reads other herds' fields as 'authenticated'; only
    admin, the genebank's manager and the herd's own users get 'private'.
    """

    def _new_member_client(self):
        da.register_user(
            "new@x.se",
            "pass",
            validated=True,
            privileges=[
                {"level": "viewer", "genebank": self.genebanks[0].id},
                {"level": "viewer", "genebank": self.genebanks[1].id},
            ],
        )
        client = self.app.application.test_client(use_cookies=True)
        login = client.post("/api/login", json={"username": "new@x.se", "password": "pass"})
        self.assertEqual(login.status_code, 200, login.get_data(as_text=True))
        return client

    def _g2_with_private_fields(self):
        g2 = self.herds[1]
        g2.bank_account_number = "1234-5"
        g2.physical_address = "Gatan 1"
        g2.physical_address_privacy = "private"
        g2.save()
        self.assertEqual(g2.bank_account_number_privacy, "private")
        return g2

    def test_new_member_cannot_read_other_herds_private_fields(self):
        g2 = self._g2_with_private_fields()
        data = self._new_member_client().get(f"/api/herd/{g2.herd}").get_json()
        leaked = {k: data.get(k) for k in ("bank_account_number", "physical_address") if k in data}
        self.assertEqual(
            leaked,
            {},
            f"freshly registered member (default viewer roles, owns no herd) GET /api/herd/G2 "
            f"returned private fields {leaked}",
        )
        self.assertEqual(data["name"], "owner2")  # name_privacy="authenticated": still visible to members

    def test_new_member_cannot_read_private_fields_in_genebank_herd_list(self):
        self._g2_with_private_fields()
        data = self._new_member_client().get(f"/api/genebank/{self.genebanks[0].id}").get_json()
        for herd in data["herds"]:
            self.assertNotIn("bank_account_number", herd, herd["herd"])
            self.assertNotIn("physical_address", herd, herd["herd"])

    def test_manager_and_admin_still_read_private_fields(self):
        g2 = self._g2_with_private_fields()
        for user in (self.manager, self.admin):
            client = self.app.application.test_client(use_cookies=True)
            client.post("/api/login", json={"username": user.email, "password": "pass"})
            data = client.get(f"/api/herd/{g2.herd}").get_json()
            self.assertEqual(data.get("bank_account_number"), "1234-5", user.email)
            self.assertEqual(data.get("physical_address"), "Gatan 1", user.email)

    def test_owner_reads_own_private_fields_but_not_other_herds(self):
        g1, g2 = self.herds[0], self._g2_with_private_fields()
        g1.bank_account_number = "9999-9"
        g1.save()
        client = self.app.application.test_client(use_cookies=True)
        client.post("/api/login", json={"username": self.owner.email, "password": "pass"})
        self.assertEqual(client.get(f"/api/herd/{g1.herd}").get_json().get("bank_account_number"), "9999-9")
        self.assertNotIn("bank_account_number", client.get(f"/api/herd/{g2.herd}").get_json())


class TestHerdPrivacyValues(FlaskTest):
    """
    An unknown *_privacy value stored by a herd owner used to make every
    herd read raise ValueError (500), admins included.
    """

    def _client_for(self, email):
        client = self.app.application.test_client(use_cookies=True)
        resp = client.post("/api/login", json={"username": email, "password": "pass"})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        return client

    def _send(self, client, method, url, **kwargs):
        """A request that blows up on a bad stored value fails the test instead of erroring."""
        try:
            return getattr(client, method)(url, **kwargs)
        except ValueError as exc:
            self.fail(f"{method.upper()} {url} raised {exc!r}")

    def test_owner_privacy_value_cannot_break_genebank_herd_list(self):
        g1 = self.herds[0]
        client = self._client_for(self.owner.email)
        write = client.patch("/api/manage/herd", json={"id": g1.id, "email_privacy": "hemlig"}).get_json()

        raised = None
        try:
            self.genebanks[0].get_herds(self.admin)
        except ValueError as exc:
            raised = exc
        self.assertIsNone(
            raised,
            f"owner PATCH /api/manage/herd email_privacy='hemlig' -> {write}; "
            f"afterwards Gotland get_herds(admin) raised {raised!r}",
        )

    def test_legacy_patch_returns_200_error_envelope_and_keeps_value(self):
        g1 = self.herds[0]
        client = self._client_for(self.owner.email)
        resp = client.patch("/api/manage/herd", json={"id": g1.id, "email_privacy": "hemlig"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"status": "error", "message": "Invalid value for email_privacy"})
        self.assertEqual(db.Herd.get_by_id(g1.id).email_privacy, "authenticated")

    def test_v2_patch_returns_400_and_keeps_value(self):
        g1 = self.herds[0]
        client = self._client_for(self.owner.email)
        resp = self._send(client, "patch", f"/api/v2/herd/{g1.herd}", json={"email_privacy": "hemlig"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("email_privacy", resp.get_json()["detail"])
        self.assertEqual(db.Herd.get_by_id(g1.id).email_privacy, "authenticated")

    def test_herd_reads_survive_a_bad_value_already_in_the_table(self):
        """Rows written before this fix: reads treat the value as 'private'."""
        g1 = self.herds[0]
        g1.email_privacy = "hemlig"
        g1.save()
        for user, sees_email in ((self.admin, True), (self.viewer, False)):
            client = self._client_for(user.email)
            resp = self._send(client, "get", f"/api/herd/{g1.herd}")
            self.assertEqual(resp.status_code, 200, user.email)
            self.assertEqual("email" in resp.get_json(), sees_email, user.email)
            resp = self._send(client, "get", f"/api/genebank/{self.genebanks[0].id}")
            self.assertEqual(resp.status_code, 200, user.email)


if __name__ == "__main__":
    unittest.main()
