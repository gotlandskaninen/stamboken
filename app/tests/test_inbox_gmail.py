"""
The intake queue's Gmail reader (docs/inkorg-gmail.md) against an in-memory Gmail: the client, the startup
guard and the consent command. Synthetic messages and example.org addresses only; nothing reaches Google.

isort:skip_file
"""

import base64
from unittest import mock

import requests
import utils.settings as settings
from utils.gmail import Gmail, HistoryTooOld

from tests.inbox_fixtures import APP, InboxTest

# Token-shaped values are built from parts so that they are plainly synthetic.
FAKE_SECRET = "-".join(("synthetic", "client", "secret"))
FAKE_TOKEN = "-".join(("synthetic", "refresh", "token"))


class _Response:
    def __init__(self, status, body=None):
        self.status_code, self.body = status, body

    @property
    def content(self):
        return b"{}" if self.body is not None else b""

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class FakeGmail:
    """Gmail's REST API in memory, as utils.gmail calls it: a session whose `request` answers each call."""

    def __init__(self):
        self.messages = {}  # id -> {"raw": bytes, "labelIds": [...], "internalDate": str}
        self.labels = {"INBOX": "INBOX", "TRASH": "TRASH", "SPAM": "SPAM"}  # name -> id
        self.history = []  # (history id, message id), messageAdded to INBOX
        self.history_id = 1000
        self.oldest_history = 0  # a startHistoryId below this is too old: 404
        self.failures = []  # (method, path suffix): the next matching call fails with 500
        self.calls = []

    def deliver(self, message, labels=("INBOX",)):
        """A message arrives; returns its Gmail id."""
        message_id = f"g{len(self.messages) + 1:04d}"
        raw = message if isinstance(message, bytes) else message.as_bytes()
        self.messages[message_id] = {"raw": raw, "labelIds": list(labels), "internalDate": "1763100000000"}
        self.history_id += 1
        if "INBOX" in labels:
            self.history.append((self.history_id, message_id))
        return message_id

    def labelled(self, message_id, name):
        return self.labels.get(name) in self.messages[message_id]["labelIds"]

    def request(self, method, url, params=None, json=None, timeout=None):
        path = url.split("/users/me/", 1)[1]
        self.calls.append((method, path))
        for failure in self.failures:
            if failure[0] == method and path.endswith(failure[1]):
                self.failures.remove(failure)
                return _Response(500, {"error": "fail"})
        params = params or {}
        if path == "profile":
            return _Response(200, {"historyId": str(self.history_id)})
        if path == "history":
            start = int(params["startHistoryId"])
            if start < self.oldest_history:
                return _Response(404, {"error": "too old"})
            added = [{"messagesAdded": [{"message": {"id": m}}]} for h, m in self.history if h > start]
            return _Response(200, {"history": added, "historyId": str(self.history_id)})
        if path == "messages":
            inbox = [m for m, found in self.messages.items() if "INBOX" in found["labelIds"]]
            return _Response(200, {"messages": [{"id": m} for m in reversed(inbox)]})  # newest first, as Gmail
        if path == "labels" and method == "GET":
            return _Response(200, {"labels": [{"id": i, "name": n} for n, i in self.labels.items()]})
        if path == "labels":
            self.labels[json["name"]] = f"Label_{len(self.labels)}"  # an id that is not the name
            return _Response(200, {"id": self.labels[json["name"]], "name": json["name"]})
        message_id, _, action = path.removeprefix("messages/").partition("/")
        found = self.messages.get(message_id)
        if found is None:
            return _Response(404, {"error": "not found"})
        if action == "modify":
            found["labelIds"] = [i for i in found["labelIds"] if i not in json["removeLabelIds"]]
            found["labelIds"] += [i for i in json["addLabelIds"] if i not in found["labelIds"]]
            return _Response(200, {"id": message_id})
        if action == "trash":
            found["labelIds"] = [i for i in found["labelIds"] if i != "INBOX"] + ["TRASH"]
            return _Response(200, {"id": message_id})
        raw = base64.urlsafe_b64encode(found["raw"]).rstrip(b"=").decode()  # Gmail leaves out the padding
        return _Response(200, {"id": message_id, **found, "raw": raw})


class TestClient(InboxTest):
    def setUp(self):
        super().setUp()
        self.fake = FakeGmail()
        self.gmail = Gmail(self.fake)

    def test_history_lists_what_came_to_the_inbox_since_the_id(self):
        first = self.fake.deliver(b"Subject: ett\r\n\r\nett\r\n")
        since = str(self.fake.history_id)
        second = self.fake.deliver(b"Subject: tva\r\n\r\ntva\r\n")
        self.fake.deliver(b"Subject: skrap\r\n\r\nskrap\r\n", labels=("SPAM",))
        self.assertEqual(self.gmail.added_since(since), ([second], str(self.fake.history_id)))
        self.assertEqual(self.gmail.inbox(), [first, second])

    def test_a_history_id_gmail_no_longer_has(self):
        self.fake.oldest_history = 5000
        with self.assertRaises(HistoryTooOld):
            self.gmail.added_since("1000")

    def test_message_decodes_the_raw_bytes_and_a_gone_one_is_none(self):
        raw = b"Subject: x\r\n\r\n" + "räksmörgås".encode() * 7 + b"\r\n"
        message_id = self.fake.deliver(raw)
        self.assertEqual(self.gmail.message(message_id)["raw"], raw)
        self.assertIsNone(self.gmail.message("finns-inte"))

    def test_a_label_is_looked_up_by_name_and_created_once(self):
        label = self.gmail.label("Inläst")
        self.assertNotEqual(label, "Inläst")
        self.assertEqual(Gmail(self.fake).label("Inläst"), label)
        self.assertEqual([c for c in self.fake.calls if c == ("POST", "labels")], [("POST", "labels")])


class TestStartupGuard(InboxTest):
    def test_guard(self):
        full = {"client_id": "id.example.org", "client_secret": FAKE_SECRET, "refresh_token": FAKE_TOKEN}
        empty = {"client_id": "", "client_secret": "", "refresh_token": ""}
        cases = [
            ("on", True, full, "s", True),  # the demo never reads the mailbox
            ("on", False, {**full, "refresh_token": ""}, "s", True),
            ("on", False, empty, "s", True),
            ("on", False, full, "", True),
            ("ja", False, full, "s", True),
            ("on", False, full, "s", False),
            ("off", True, empty, "", False),
        ]
        for mode, demo, credentials, secret, refused in cases:
            with (
                self.subTest(mode=mode, demo=demo, credentials=sorted(k for k, v in credentials.items() if v)),
                mock.patch.multiple(settings.gmail, mode=mode, **credentials),
                mock.patch.object(settings.service, "demo_instance", demo),
                mock.patch.object(settings.mail, "link_secret", secret),
            ):
                if refused:
                    with self.assertRaises(RuntimeError):
                        settings.refuse_unsafe_gmail_settings()
                else:
                    settings.refuse_unsafe_gmail_settings()


class TestConsent(InboxTest):
    def test_prints_the_url_and_only_the_refresh_token_on_stdout(self):
        answer = mock.Mock(ok=True, status_code=200, content=b"{}")
        answer.json.return_value = {"refresh_token": FAKE_TOKEN, "access_token": "x"}
        with (
            mock.patch.multiple(settings.gmail, client_id="id.example.org", client_secret=FAKE_SECRET),
            mock.patch("cli.gmail.requests.post", return_value=answer) as post,
        ):
            result = APP.test_cli_runner().invoke(
                args=["gmail", "consent"], input="http://127.0.0.1:8765/?code=4/syntetisk&scope=x\n"
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stdout.strip(), FAKE_TOKEN)
        self.assertNotIn(FAKE_TOKEN, result.stderr)
        self.assertIn("access_type=offline", result.stderr)
        self.assertIn("gmail.modify", result.stderr)
        sent = post.call_args.kwargs["data"]
        self.assertEqual((sent["code"], sent["grant_type"]), ("4/syntetisk", "authorization_code"))
        self.assertTrue(sent["code_verifier"])

    def test_refuses_without_the_client(self):
        with mock.patch.multiple(settings.gmail, client_id="", client_secret=""):
            result = APP.test_cli_runner().invoke(args=["gmail", "consent"])
        self.assertNotEqual(result.exit_code, 0)
