"""The GitHub app's client behind "Tyck till": JWT, token cache, issue lookup, creation and the project board."""

import base64
import json
import time
import unittest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from unittest import mock

import requests
import utils.github_app as github_app
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from utils.github_app import GitHubError, Issue

REPO = "example-org/example-repo"


def _response(body, status=200, links=None):
    return mock.Mock(status_code=status, json=mock.Mock(return_value=body), links=links or {})


def _token_answer(expires_in=3600):
    expires = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    return _response({"token": "inst-token", "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ")}, 201)


def _issue(number, body="", **extra):
    return {"number": number, "node_id": f"N{number}", "html_url": f"https://github.com/{REPO}/issues/{number}", "body": body, **extra}


class GitHubAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.tmp = __import__("tempfile").TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = __import__("pathlib").Path(self.tmp.name) / "key.pem"
        path.write_bytes(
            self.key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        settings = Namespace(github="app", app_id="12345", installation_id="678", key_path=path, project_id="PVT_x")
        for patcher in (
            mock.patch("utils.github_app.settings.tyck_till", settings),
            mock.patch("utils.github_app.requests"),
            mock.patch.dict(github_app._token_cache, clear=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.requests = github_app.requests
        self.deadline = time.monotonic() + 10

    def _answers(self, *answers):
        self.requests.request.side_effect = list(answers)

    def _calls(self):
        return [(c.args[0], c.args[1], c.kwargs) for c in self.requests.request.call_args_list]

    def test_jwt_is_rs256_signed_by_the_app_key(self):
        head, body, signature = github_app._jwt().split(".")

        def decode(part):
            return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))

        self.assertEqual(json.loads(decode(head)), {"alg": "RS256", "typ": "JWT"})
        claims = json.loads(decode(body))
        self.assertEqual(claims["iss"], "12345")
        self.assertLessEqual(claims["exp"] - claims["iat"], 600)
        self.key.public_key().verify(
            decode(signature), f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256()
        )

    def test_installation_token_is_cached_until_five_minutes_before_expiry(self):
        self._answers(_token_answer(), _response(_issue(1), 201), _response(_issue(2), 201))
        github_app.create_issue(REPO, "t", "b", [], self.deadline)
        github_app.create_issue(REPO, "t", "b", [], self.deadline)
        self.assertEqual([c[1].endswith("/access_tokens") for c in self._calls()], [True, False, False])
        github_app._token_cache["expires"] = time.time() - 1  # five minutes before expiry has passed
        self._answers(_token_answer(), _response(_issue(3), 201))
        self.requests.request.reset_mock()
        github_app.create_issue(REPO, "t", "b", [], self.deadline)
        self.assertEqual(self.requests.request.call_count, 2)

    def test_create_issue_returns_number_node_id_and_url(self):
        self._answers(_token_answer(), _response(_issue(7), 201))
        issue = github_app.create_issue(REPO, "Titel", "Text", ["tyck till", "bug"], self.deadline)
        self.assertEqual(issue, Issue(7, "N7", f"https://github.com/{REPO}/issues/7"))
        method, url, kwargs = self._calls()[1]
        self.assertEqual((method, url), ("POST", f"https://api.github.com/repos/{REPO}/issues"))
        self.assertEqual(kwargs["json"], {"title": "Titel", "body": "Text", "labels": ["tyck till", "bug"]})
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer inst-token")
        self.assertEqual(kwargs["headers"]["X-GitHub-Api-Version"], "2022-11-28")

    def test_find_issue_lists_open_and_closed_with_the_label_since_yesterday(self):
        self._answers(
            _token_answer(),
            _response([_issue(1, "tt-aaaaaaaa", pull_request={}), _issue(2, "tt-bbbbbbbb"), _issue(3, None)]),
        )
        found = github_app.find_issue(REPO, "tt-bbbbbbbb", self.deadline)
        self.assertEqual(found.number, 2)
        _, url, kwargs = self._calls()[1]
        self.assertEqual(url, f"https://api.github.com/repos/{REPO}/issues")
        params = kwargs["params"]
        self.assertEqual((params["state"], params["labels"], params["per_page"]), ("all", "tyck till", 100))
        since = datetime.strptime(params["since"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        self.assertAlmostEqual(since.timestamp(), (datetime.now(timezone.utc) - timedelta(days=1)).timestamp(), delta=60)

    def test_find_issue_skips_pull_requests(self):
        self._answers(_token_answer(), _response([_issue(1, "tt-aaaaaaaa", pull_request={})]))
        self.assertIsNone(github_app.find_issue(REPO, "tt-aaaaaaaa", self.deadline))

    def test_find_issue_on_page_two(self):
        next_url = f"https://api.github.com/repos/{REPO}/issues?page=2"
        self._answers(
            _token_answer(), _response([_issue(1)], links={"next": {"url": next_url}}), _response([_issue(2, "tt-cccccccc")])
        )
        self.assertEqual(github_app.find_issue(REPO, "tt-cccccccc", self.deadline).number, 2)
        self.assertEqual(self._calls()[2][1], next_url)

    def test_find_issue_runs_out_of_time_during_the_lookup(self):
        with mock.patch("utils.github_app.time.monotonic", side_effect=[0, 5, 9.5, 9.5]):
            self._answers(_token_answer(), _response([_issue(1)], links={"next": {"url": "https://x"}}))
            with self.assertRaises(GitHubError):
                github_app.find_issue(REPO, "tt-zzzzzzzz", 10)

    def test_timeout_and_5xx_raise_github_error(self):
        self.requests.request.side_effect = requests.Timeout()
        with self.assertRaises(GitHubError):
            github_app.create_issue(REPO, "t", "b", [], self.deadline)
        self._answers(_token_answer(), _response({}, 502))
        with self.assertRaises(GitHubError):
            github_app.create_issue(REPO, "t", "b", [], self.deadline)

    def test_deadline_passed_raises_without_request(self):
        with self.assertRaises(GitHubError):
            github_app.create_issue(REPO, "t", "b", [], time.monotonic() + 0.5)
        self.requests.request.assert_not_called()

    def test_timeout_is_what_is_left_of_the_deadline(self):
        self._answers(_token_answer(), _response(_issue(1), 201))
        github_app.create_issue(REPO, "t", "b", [], time.monotonic() + 8)
        connect, read = self._calls()[0][2]["timeout"]
        self.assertEqual(connect, 3)
        self.assertLessEqual(read, 8)

    def test_add_to_project_posts_add_project_v2_item_by_id_and_returns_false_on_error(self):
        self._answers(_token_answer(), _response({"data": {}}))
        self.assertTrue(github_app.add_to_project("N7", self.deadline))
        _, url, kwargs = self._calls()[1]
        self.assertEqual(url, "https://api.github.com/graphql")
        self.assertIn("addProjectV2ItemById", kwargs["json"]["query"])
        self.assertEqual(kwargs["json"]["variables"], {"p": "PVT_x", "c": "N7"})
        self._answers(_response({"errors": [{"message": "no"}]}))
        self.assertFalse(github_app.add_to_project("N7", self.deadline))
        self._answers(_response({}, 500))
        self.assertFalse(github_app.add_to_project("N7", self.deadline))

    def test_configured(self):
        self.assertTrue(github_app.configured())
        github_app.settings.tyck_till.key_path = github_app.settings.tyck_till.key_path.parent / "missing.pem"
        self.assertFalse(github_app.configured())


class LoggModeTest(unittest.TestCase):
    def test_logg_mode_makes_no_requests(self):
        settings = Namespace(github="logg", app_id="", installation_id="", key_path=None, project_id="")
        with (
            mock.patch("utils.github_app.settings.tyck_till", settings),
            mock.patch("utils.github_app.requests") as requests_mock,
            mock.patch("utils.github_app._fake_numbers", iter(range(1, 10))),
            self.assertLogs("utils.github_app", "INFO") as logs,
        ):
            issue = github_app.create_issue(REPO, "Rubrik", "hemlig text", ["tyck till"], time.monotonic() + 10)
            self.assertEqual(issue, Issue(1, "", f"https://github.com/{REPO}/issues/1"))
            self.assertIsNone(github_app.find_issue(REPO, "tt-aaaaaaaa", 0))
            self.assertTrue(github_app.add_to_project("", 0))
            self.assertTrue(github_app.configured())
            requests_mock.request.assert_not_called()
        text = " ".join(logs.output)
        self.assertIn(REPO, text)
        self.assertIn("Rubrik", text)
        self.assertNotIn("hemlig text", text)
