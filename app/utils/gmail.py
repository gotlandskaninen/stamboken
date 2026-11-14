"""
The association's Gmail mailbox through Gmail's REST API (docs/inkorg-gmail.md): only the calls the intake
queue's reader makes. Authorised with a refresh token for the scope gmail.modify (flask gmail consent).
"""

import base64

import requests
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

import utils.settings as settings

API = "https://gmail.googleapis.com/gmail/v1/users/me"
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/gmail.modify"
TIMEOUT = 60  # seconds per call


class HistoryTooOld(Exception):
    """Gmail no longer has the history since the stored historyId: the whole inbox has to be read."""


class Gmail:
    """`session` is a requests-like session that authorises its calls (an AuthorizedSession, or a fake in tests)."""

    def __init__(self, session):
        self.session = session
        self._labels = {}

    @classmethod
    def from_settings(cls):
        credentials = Credentials(
            None,
            refresh_token=settings.gmail.refresh_token,
            client_id=settings.gmail.client_id,
            client_secret=settings.gmail.client_secret,
            token_uri=TOKEN_URI,
            scopes=[SCOPE],
        )
        return cls(AuthorizedSession(credentials))

    def _call(self, method, path, missing_ok=False, **kwargs):
        response = self.session.request(method, f"{API}/{path}", timeout=TIMEOUT, **kwargs)
        if missing_ok and response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json() if response.content else {}

    def _pages(self, path, params):
        token = None
        while True:
            page = self._call("GET", path, params={**params, **({"pageToken": token} if token else {})})
            yield page
            token = page.get("nextPageToken")
            if not token:
                return

    def history_id(self):
        """The mailbox's current historyId."""
        return self._call("GET", "profile")["historyId"]

    def added_since(self, history_id):
        """(ids of the messages added to INBOX since `history_id`, oldest first; the newest historyId)."""
        params = {"startHistoryId": history_id, "historyTypes": "messageAdded", "labelId": "INBOX"}
        ids, newest = [], history_id
        try:
            for page in self._pages("history", params):
                newest = page.get("historyId", newest)
                for record in page.get("history", []):
                    ids += [added["message"]["id"] for added in record.get("messagesAdded", [])]
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                raise HistoryTooOld(history_id) from exc
            raise
        return list(dict.fromkeys(ids)), newest

    def labelled(self, label_id="INBOX"):
        """The ids of every message with the label (never in SPAM or the trash), oldest first."""
        ids = []
        for page in self._pages("messages", {"labelIds": label_id, "maxResults": 500}):
            ids += [message["id"] for message in page.get("messages", [])]
        return ids[::-1]

    def message(self, message_id):
        """{"raw": the RFC 822 bytes, "labelIds": [...], "internalDate": ms}, or None when it is gone."""
        found = self._call("GET", f"messages/{message_id}", missing_ok=True, params={"format": "raw"})
        if found is None:
            return None
        raw = found["raw"]
        found["raw"] = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        return found

    def label(self, name):
        """The id of the user label `name`, created when missing."""
        if name not in self._labels:
            found = {label["name"]: label["id"] for label in self._call("GET", "labels").get("labels", [])}
            self._labels[name] = found.get(name) or self._call("POST", "labels", json={"name": name})["id"]
        return self._labels[name]

    def modify(self, message_id, add=(), remove=()):
        self._call(
            "POST", f"messages/{message_id}/modify", json={"addLabelIds": list(add), "removeLabelIds": list(remove)}
        )

    def trash(self, message_id):
        self._call("POST", f"messages/{message_id}/trash")
