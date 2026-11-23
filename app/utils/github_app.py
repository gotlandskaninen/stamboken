"""
The GitHub app behind "Tyck till" (docs/tyck-till.md): finds and creates the issue and adds it to the project.
Authorised as the app's installation (a JWT signed with the app's key, exchanged for a token). The mode `logg`
is a fake that succeeds, for development, CI and e2e.
"""

import base64
import functools
import itertools
import json
import logging
import time
from collections import namedtuple
from datetime import datetime, timedelta, timezone

import requests
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from requests import RequestException

import utils.settings as settings

logger = logging.getLogger(__name__)

API = "https://api.github.com"
Issue = namedtuple("Issue", "number node_id url")
_PROJECT_MUTATION = (
    "mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}"
)
_token_cache = {}  # token and expires: the installation token, kept until five minutes before it expires
_fake_numbers = itertools.count(1)


class GitHubError(Exception):
    """GitHub failed, or its outcome is not known."""


def _github_errors(func):
    """An answer that is not the JSON we expect is a GitHub failure, not a 500."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise GitHubError(type(exc).__name__) from exc

    return wrapper


def configured():
    github = settings.tyck_till
    if github.github == "logg":
        return True
    return github.github == "app" and bool(github.app_id and github.installation_id and github.key_path.is_file())


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def _jwt():
    now = int(time.time())
    head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = {"iat": now - 60, "exp": now + 540, "iss": settings.tyck_till.app_id}
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    key = load_pem_private_key(settings.tyck_till.key_path.read_bytes(), password=None)
    signature = key.sign(head + b"." + body, padding.PKCS1v15(), hashes.SHA256())
    return (head + b"." + body + b"." + _b64(signature)).decode()


def _call(method, url, deadline, token=None, **kwargs):
    remaining = deadline - time.monotonic()
    if remaining < 1:
        raise GitHubError("no time left")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    try:
        headers["Authorization"] = f"Bearer {token or _jwt()}"
        # shortcut: the read timeout holds between received bytes, so a call can overrun by one such gap
        response = requests.request(method, url, headers=headers, timeout=(3, remaining), **kwargs)
    except (RequestException, OSError, ValueError, TypeError, UnsupportedAlgorithm) as exc:  # the key file and the PEM
        raise GitHubError(type(exc).__name__) from exc
    if response.status_code >= 400:
        raise GitHubError(f"HTTP {response.status_code}")
    return response


@_github_errors
def _installation_token(deadline):
    if _token_cache.get("expires", 0) > time.time():
        return _token_cache["token"]
    answer = _call(
        "POST", f"{API}/app/installations/{settings.tyck_till.installation_id}/access_tokens", deadline
    ).json()
    expires = datetime.fromisoformat(answer["expires_at"].replace("Z", "+00:00")).timestamp()
    _token_cache.update(token=answer["token"], expires=expires - 300)
    return answer["token"]


def _last_line(body):
    lines = [line.strip() for line in (body or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


@_github_errors
def find_issue(repo, ref, deadline):
    """The issue labelled `tyck till`, open or closed and updated since yesterday, whose body ends with the line `Referens: <ref>`; else None."""
    if settings.tyck_till.github == "logg":
        return None
    token = _installation_token(deadline)
    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url, params = f"{API}/repos/{repo}/issues", {"state": "all", "labels": "tyck till", "since": since, "per_page": 100}
    while url:
        response = _call("GET", url, deadline, token, params=params)
        for item in response.json():
            if "pull_request" not in item and _last_line(item.get("body")) == f"Referens: {ref}":
                return Issue(item["number"], item["node_id"], item["html_url"])
        url, params = response.links.get("next", {}).get("url"), None
    return None


@_github_errors
def create_issue(repo, title, body, labels, deadline):
    if settings.tyck_till.github == "logg":
        number = next(_fake_numbers)
        logger.info("tyck till (fake): %s, %r, %s", repo, title, labels)  # never the body
        return Issue(number, "", f"https://github.com/{repo}/issues/{number}")
    token = _installation_token(deadline)
    item = _call(
        "POST", f"{API}/repos/{repo}/issues", deadline, token, json={"title": title, "body": body, "labels": labels}
    ).json()
    return Issue(item["number"], item["node_id"], item["html_url"])


def add_to_project(node_id, deadline):
    """True when the issue is on the project board; False when it could not be added (the caller notes it)."""
    if settings.tyck_till.github == "logg":
        return True
    try:
        token = _installation_token(deadline)
        answer = _call(
            "POST",
            f"{API}/graphql",
            deadline,
            token,
            json={"query": _PROJECT_MUTATION, "variables": {"p": settings.tyck_till.project_id, "c": node_id}},
        ).json()
    except (GitHubError, ValueError):
        logger.warning("tyck till: adding to the project failed")
        return False
    return isinstance(answer, dict) and not answer.get("errors")
