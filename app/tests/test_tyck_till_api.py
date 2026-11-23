"""POST /api/v2/tyck-till: checks, limits, the order of the steps, retries and the nightly purge. GitHub is a fake."""

import io
import json
import os
import re
import shutil
import threading
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

import blueprints.tyck_till as blueprint
import utils.database as db
import utils.github_app as github_app
import utils.settings as settings
import utils.tyck_till as tt
from herdbook import APP, limiter
from PIL import Image
from utils.github_app import GitHubError, Issue

from tests.inbox_fixtures import InboxTest, encoded, photo

URL = "/api/v2/tyck-till"
REPOS = {v: k for k, v in tt.REPOS.items()}


class FakeGitHub:
    """Counts the calls; `lose_response` creates the issue and then fails, as a lost answer does."""

    def __init__(self):
        self.created, self.projected, self.looked_up = [], [], 0
        self.by_ref = {}
        self.down = self.lose_response = False
        self.project_ok = True
        self.wait = None  # an Event create_issue waits for

    def configured(self):
        return True

    def find_issue(self, repo, ref, deadline):
        self.looked_up += 1
        if self.down:
            raise GitHubError("down")
        return self.by_ref.get((repo, ref))

    def create_issue(self, repo, title, body, labels, deadline):
        if self.wait is not None:
            self.wait.wait(5)
        if self.down:
            raise GitHubError("down")
        number = len(self.created) + 1
        issue = Issue(number, f"N{number}", f"https://github.com/{repo}/issues/{number}")
        self.created.append({"repo": repo, "title": title, "body": body, "labels": labels, "issue": issue})
        self.by_ref[(repo, re.search(r"tt-[0-9a-f]{8}", body).group())] = issue
        if self.lose_response:
            self.lose_response = False
            raise GitHubError("lost")
        return issue

    def add_to_project(self, node_id, deadline):
        self.projected.append(node_id)
        return self.project_ok


class TyckTillTest(InboxTest):
    def setUp(self):
        super().setUp()
        self.github = FakeGitHub()
        patch = mock.patch.multiple(
            github_app,
            configured=self.github.configured,
            find_issue=self.github.find_issue,
            create_issue=self.github.create_issue,
            add_to_project=self.github.add_to_project,
        )
        patch.start()
        self.addCleanup(patch.stop)

    def send(self, files=(), client=None, ip=None, **over):
        data = {
            "typ": "fel",
            "text": "Knappen syns inte",
            "sida": "/stamboken/kaniner",
            "version": "2.13.0",
            "enhet": "mobil",
            "inskick_id": str(uuid.uuid4()),
            "email": "svar@example.org",
            **over,
        }
        data = {k: v for k, v in data.items() if v is not None}
        if files:
            data["bilder"] = [(io.BytesIO(content), name) for name, content in files]
        extra = {"environ_overrides": {"REMOTE_ADDR": ip}} if ip else {}
        return (client or self.client).post(URL, data=data, content_type="multipart/form-data", **extra)

    def folders(self):
        root = tt.root()
        return sorted(os.listdir(root)) if root.is_dir() else []

    def mails(self):
        return list(db.MailMessage.select().where(db.MailMessage.kind == "tyck_till.inskick"))

    def assertNothingSent(self):
        self.assertEqual(self.github.created, [])
        self.assertEqual(self.mails(), [])
        self.assertEqual(self.folders(), [])

    def saved(self, inskick_id):
        return json.loads((tt.folder(inskick_id) / "inskick.json").read_text())

    def limits_on(self):
        limiter.enabled = True
        limiter.reset()
        self.addCleanup(setattr, limiter, "enabled", False)
        self.addCleanup(limiter.reset)


class TestChecks(TyckTillTest):
    def test_accepted_logged_out_with_an_email(self):
        inskick_id = uuid.uuid4()
        response = self.send(inskick_id=str(inskick_id))
        self.assertEqual(response.status_code, 202, response.get_data(as_text=True))
        self.assertEqual(
            response.get_json(),
            {"issue_url": None, "visibility": "privat", "images": 0, "reply_to": "svar@example.org"},
        )
        (row,) = self.mails()
        self.assertEqual(row.params, {"inskick": inskick_id.int, "issue": 1, "repo": 1, "tavla": 1})
        self.assertEqual(self.github.created[0]["title"], "Tyck till: något fungerar inte")

    def test_validation(self):
        for field, over in (
            ("typ", {"typ": None}),
            ("typ", {"typ": "annat"}),
            ("text", {"text": "   "}),
            ("text", {"text": "x" * 5001}),
            ("inskick_id", {"inskick_id": "inte-ett-uuid"}),
            ("inskick_id", {"inskick_id": None}),
            ("email", {"email": None}),
            ("email", {"email": "inte en adress"}),
        ):
            with self.subTest(over):
                response = self.send(**over)
                self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
                self.assertEqual(response.get_json()["field"], field)
        self.assertNothingSent()

    def test_text_of_exactly_5000_characters_is_accepted(self):
        self.assertEqual(self.send(text="x" * 5000).status_code, 202)

    def test_logged_out_is_always_private(self):
        self.assertEqual(self.send(vem="publik").status_code, 202)
        self.assertEqual(self.github.created[0]["repo"], tt.REPOS["privat"])
        self.assertEqual(self.github.projected, [])

    def test_logged_in_can_choose_public_and_the_board_is_filled(self):
        self.login("hjalp")
        response = self.send(vem="publik", email=None, kontakt="1")
        self.assertEqual(response.status_code, 202, response.get_data(as_text=True))
        self.assertEqual(self.github.created[0]["repo"], tt.REPOS["publik"])
        self.assertEqual(self.github.created[0]["title"], "Tyck till: Knappen syns inte")
        self.assertEqual(self.github.projected, ["N1"])
        self.assertEqual(response.get_json()["issue_url"], "https://github.com/gotlandskaninen/stamboken/issues/1")
        self.assertEqual(self.mails()[0].params["tavla"], 1)

    def test_project_add_fails_still_202_and_tavla_0(self):
        self.github.project_ok = False
        self.login("hjalp")
        self.assertEqual(self.send(vem="publik", email=None).status_code, 202)
        self.assertEqual(self.mails()[0].params["tavla"], 0)

    def test_logged_in_on_public_page_with_email_replies_to_that_address(self):
        self.login("hjalp")
        inskick_id = uuid.uuid4()
        response = self.send(inskick_id=str(inskick_id), email="annan@example.org")
        self.assertEqual(response.get_json()["reply_to"], "annan@example.org")
        saved = self.saved(inskick_id)
        self.assertEqual(
            (saved["email"], saved["contact"], saved["user_id"]), ("annan@example.org", False, self.helper.id)
        )

    def test_logged_in_with_the_contact_box_keeps_no_typed_email(self):
        self.login("hjalp")
        inskick_id = uuid.uuid4()
        self.send(inskick_id=str(inskick_id), email=None, kontakt="1")
        saved = self.saved(inskick_id)
        self.assertEqual((saved["email"], saved["contact"]), ("", True))

    def test_access_rules_enforced_account_without_prod_access_gets_202(self):
        user = self.user("utanprod")
        self.assertFalse(user.is_admin)
        with mock.patch.object(settings.service, "access_rules", "enforce"):
            self.login("utanprod")
            response = self.send(email=None)
        self.assertEqual(response.status_code, 202, response.get_data(as_text=True))

    def test_pdf_refused_before_rendering(self):
        with mock.patch("blueprints.inbox._each_page") as render:
            response = self.send(files=[("a.pdf", b"%PDF-1.4\n" + b"x" * 100)])
        self.assertEqual(response.status_code, 415)
        render.assert_not_called()
        self.assertNothingSent()

    def test_heic_is_accepted(self):
        buffer = io.BytesIO()
        photo((400, 300)).save(buffer, "HEIF")
        response = self.send(files=[("iphone.heic", buffer.getvalue())])
        self.assertEqual(response.status_code, 202, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["images"], 1)

    def test_version_with_newline_and_mention_becomes_okand_in_the_issue(self):
        self.send(version="1\n@jonas")
        body = self.github.created[0]["body"]
        self.assertIn("Version: okänd", body)
        self.assertNotIn("@jonas", body)

    def test_the_issue_never_holds_the_pointed_element_the_email_or_the_account(self):
        self.login("hjalp")
        self.send(vem="publik", email="annan@example.org", pekat="Anna Svensson G123")
        issue = self.github.created[0]
        for private in ("Anna Svensson", "annan@example.org", "hjalp", str(self.helper.id)):
            self.assertNotIn(private, issue["title"] + issue["body"])

    def test_images_are_reencoded_without_exif(self):
        exif = Image.Exif()
        exif[0x010F] = "Kamera"
        exif[0x0132] = "2026:11:23 10:00:00"
        inskick_id = uuid.uuid4()
        response = self.send(
            files=[("a.jpg", encoded(photo((400, 300)), exif=exif.tobytes()))], inskick_id=str(inskick_id)
        )
        self.assertEqual(response.get_json()["images"], 1)
        with Image.open(tt.folder(inskick_id) / "bild-0.jpg") as stored:
            self.assertEqual(dict(stored.getexif()), {})
            self.assertEqual(stored.format, "JPEG")

    def test_five_images_refused(self):
        files = [(f"{n}.jpg", encoded(photo((200, 200), seed=n))) for n in range(5)]
        response = self.send(files=files)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["field"], "bilder")
        self.assertNothingSent()

    def test_small_file_with_huge_dimensions_is_refused_before_decoding(self):
        huge = encoded(Image.new("1", (20000, 20000)), "PNG")
        self.assertLess(len(huge), 1024 * 1024)
        response = self.send(files=[("stor.png", huge)])
        self.assertEqual(response.status_code, 413)
        self.assertIn("pixlar", response.get_json()["detail"])
        self.assertNothingSent()

    def test_body_between_9_and_10_mb_gives_413_without_folder_issue_or_queue_row(self):
        response = self.send(files=[("a.jpg", b"\xff\xd8\xff" + b"x" * int(9.5 * 1024 * 1024))])
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.content_type, "application/problem+json")
        self.assertNothingSent()

    def test_over_9_mb_gives_413_problem_json(self):
        response = self.send(files=[("a.jpg", b"\xff\xd8\xff" + b"x" * (11 * 1024 * 1024))])
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["status"], 413)
        self.assertIn("Bilderna är för stora", response.get_json()["detail"])


class TestLimits(TyckTillTest):
    def test_logged_in_limit_is_five_per_account(self):
        self.limits_on()
        self.login("hjalp")
        codes = [self.send(email=None).status_code for _ in range(6)]
        self.assertEqual(codes, [202] * 5 + [429])
        refused = self.send(email=None)
        self.assertEqual(refused.content_type, "application/problem+json")
        self.assertEqual(refused.get_json()["type"], "rate-limit-exceeded")

    def test_logged_out_limit_is_three_per_ip_and_thirty_in_all(self):
        self.limits_on()
        self.assertEqual([self.send(ip="10.0.0.1").status_code for _ in range(4)], [202, 202, 202, 429])
        for n in range(2, 11):  # nine more addresses, three each: 30 in all counting the first
            self.assertEqual([self.send(ip=f"10.0.0.{n}").status_code for _ in range(3)], [202] * 3)
        response = self.send(ip="10.0.1.1")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.get_json()["type"], "rate-limit-exceeded")

    def test_refusals_do_not_use_the_quota_but_each_call_past_the_lock_counts(self):
        self.limits_on()
        self.github.down = True
        self.assertEqual([self.send(ip="10.0.0.1").status_code for _ in range(3)], [503] * 3)
        self.github.down = False
        self.assertEqual(self.send(ip="10.0.0.1").status_code, 202)
        self.assertEqual(self.send(ip="10.0.0.1").status_code, 202)  # 5 calls past the lock, 2 of them counted
        bad = [("a.png", b"inte en bild")]
        codes = [self.send(files=bad, ip="10.0.0.2").status_code for _ in range(21)]
        self.assertEqual(codes[:20], [415] * 20)
        self.assertEqual(codes[20], 429)

    def test_honeypot_gives_202_creates_nothing_and_counts_against_the_limit(self):
        self.limits_on()
        for _ in range(3):
            response = self.send(webbplats="https://example.org", ip="10.0.0.1")
            self.assertEqual(response.status_code, 202)
        self.assertNothingSent()
        self.assertEqual(self.send(ip="10.0.0.1").status_code, 429)

    def test_limiter_storage_down_gives_503_and_no_calls(self):
        self.limits_on()
        with mock.patch.object(limiter.limiter, "hit", side_effect=ConnectionError("redis")):
            response = self.send()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.github.looked_up, 0)
        self.assertNothingSent()

    def test_not_configured_gives_503(self):
        with mock.patch.object(github_app, "configured", lambda: False):  # app mode without the key or ids
            response = self.send()
        self.assertEqual(response.status_code, 503)
        self.assertNothingSent()

    def test_early_refusal_leaves_no_folder(self):
        self.limits_on()
        self.send(ip="10.0.0.1", webbplats="x")  # the honeypot
        self.assertEqual(self.folders(), [])
        for _ in range(3):
            self.send(ip="10.0.0.1")
        before = self.folders()
        self.assertEqual(self.send(ip="10.0.0.1").status_code, 429)
        self.assertEqual(self.folders(), before)
        with mock.patch.object(limiter.limiter, "hit", side_effect=ConnectionError("redis")):
            self.send(ip="10.0.0.2")
        self.assertEqual(self.folders(), before)


class TestRetries(TyckTillTest):
    def test_github_down_gives_503_no_mail_no_folder(self):
        self.github.down = True
        response = self.send(files=[("a.jpg", encoded(photo((200, 200))))])
        self.assertEqual(response.status_code, 503)
        self.assertIn("Texten finns kvar", response.get_json()["detail"])
        self.assertNothingSent()

    def test_same_id_twice_returns_the_saved_answer(self):
        inskick_id = str(uuid.uuid4())
        first = self.send(inskick_id=inskick_id, files=[("a.jpg", encoded(photo((200, 200))))])
        second = self.send(inskick_id=inskick_id)
        self.assertEqual((first.status_code, second.status_code), (202, 202))
        self.assertEqual(first.get_json(), second.get_json())
        self.assertEqual(len(self.github.created), 1)
        self.assertEqual(len(self.mails()), 1)

    def test_same_id_twice_spends_no_quota(self):
        self.limits_on()
        inskick_id = str(uuid.uuid4())
        for _ in range(5):
            self.assertEqual(self.send(inskick_id=inskick_id, ip="10.0.0.1").status_code, 202)
        self.assertEqual([self.send(ip="10.0.0.1").status_code for _ in range(3)], [202, 202, 429])

    def test_lost_response_in_public_then_retry_choosing_private_gives_the_public_issue(self):
        self.login("hjalp")
        self.github.lose_response = True
        inskick_id = str(uuid.uuid4())
        self.assertEqual(self.send(inskick_id=inskick_id, vem="publik", email=None).status_code, 503)
        response = self.send(inskick_id=inskick_id, vem="privat", email=None)
        self.assertEqual(response.status_code, 202, response.get_data(as_text=True))
        self.assertEqual(len(self.github.created), 1)
        self.assertEqual(response.get_json()["visibility"], "publik")
        self.assertEqual(response.get_json()["issue_url"], "https://github.com/gotlandskaninen/stamboken/issues/1")
        self.assertEqual(self.mails()[0].params["repo"], 0)
        self.assertEqual(self.github.projected, ["N1"])

    def test_lock_file_replaced_while_waiting_gives_409(self):
        inskick_id = uuid.uuid4()
        real_flock = blueprint.fcntl.flock

        def swap_then_lock(fd, how):
            folder = tt.folder(inskick_id)
            shutil.rmtree(folder)
            folder.mkdir()
            (folder / "lock").touch()
            real_flock(fd, how)

        with mock.patch.object(blueprint.fcntl, "flock", swap_then_lock):
            response = self.send(inskick_id=str(inskick_id))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.github.created, [])

    def test_lost_response_then_retry_finds_the_issue(self):
        self.github.lose_response = True
        inskick_id = str(uuid.uuid4())
        self.assertEqual(self.send(inskick_id=inskick_id).status_code, 503)
        self.assertEqual(self.folders(), [])
        self.assertEqual(self.send(inskick_id=inskick_id).status_code, 202)
        self.assertEqual(len(self.github.created), 1)
        self.assertEqual(len(self.mails()), 1)

    def test_process_died_after_queue_then_retry_with_github_down_keeps_folder(self):
        inskick_id = uuid.uuid4()
        self.send(inskick_id=str(inskick_id), files=[("a.jpg", encoded(photo((200, 200))))])
        (tt.folder(inskick_id) / "svar.json").unlink()
        self.github.down = True
        looked = self.github.looked_up
        response = self.send(inskick_id=str(inskick_id))
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["images"], 1)
        self.assertEqual(self.github.looked_up, looked)
        self.assertEqual(self.folders(), [str(inskick_id)])
        self.assertTrue((tt.folder(inskick_id) / "bild-0.jpg").exists())

    def test_concurrent_same_id_one_issue_one_mail(self):
        self.limits_on()
        inskick_id = str(uuid.uuid4())
        self.github.wait = threading.Event()
        results = []

        def attempt():
            results.append(self.send(client=APP.test_client(), inskick_id=inskick_id, ip="10.0.0.1").status_code)

        first = threading.Thread(target=attempt)
        first.start()
        deadline = time.monotonic() + 5
        while not self.folders() and time.monotonic() < deadline:
            time.sleep(0.01)
        second = threading.Thread(target=attempt)
        second.start()
        second.join(5)
        self.github.wait.set()
        first.join(10)
        self.assertEqual(sorted(results), [202, 409])
        self.assertEqual(len(self.github.created), 1)
        self.assertEqual(len(self.mails()), 1)
        self.assertEqual([self.send(ip="10.0.0.1").status_code for _ in range(3)], [202, 202, 429])

    def test_slow_github_gives_503_within_10_seconds_while_another_endpoint_answers(self):
        self.github.wait = threading.Event()
        self.github.down = True  # the wait ends with GitHub failing, as the deadline would end it
        results = []
        first = threading.Thread(target=lambda: results.append(self.send(client=APP.test_client()).status_code))
        first.start()
        time.sleep(0.3)
        other = APP.test_client().get("/api/v2/genebanks/public")
        self.assertEqual(other.status_code, 200, other.get_data(as_text=True))
        busy = self.send(client=APP.test_client())  # a second one in the same process is turned away
        self.assertEqual(busy.status_code, 503)
        self.github.wait.set()
        first.join(10)
        self.assertEqual(results, [503])
        self.assertNothingSent()


class TestPurge(TyckTillTest):
    def make(self, age, queued=False):
        inskick_id = uuid.uuid4()
        folder = tt.folder(inskick_id)
        folder.mkdir(parents=True)
        (folder / "inskick.json").write_text("{}")
        os.utime(folder, (time.time() - age, time.time() - age))
        if queued:
            db.MailMessage.insert(
                kind="tyck_till.inskick", recipient_kind="tyck_till", recipient_id=0, priority=1, category="N",
                dedupe_key=f"tyck-till:{inskick_id}", next_attempt_at=datetime.now(timezone.utc),
            ).execute()  # fmt: skip
        return folder

    def test_purge(self):
        day = 24 * 3600
        old_queued, young_queued = self.make(31 * day, True), self.make(29 * day, True)
        abandoned, fresh = self.make(2 * day), self.make(3600)
        not_a_submission = tt.root() / "annat"
        not_a_submission.mkdir()
        os.utime(not_a_submission, (0, 0))
        elsewhere = tt.root().parent / "tyck-till-annat"
        elsewhere.mkdir()
        link = tt.root() / str(uuid.uuid4())
        link.symlink_to(elsewhere)
        os.utime(elsewhere, (0, 0))
        self.assertEqual(tt.purge(datetime.now(timezone.utc)), 2)
        self.assertFalse(old_queued.exists() or abandoned.exists())
        self.assertTrue(young_queued.exists() and fresh.exists() and not_a_submission.exists())
        self.assertTrue(link.is_symlink() and elsewhere.exists())

    def test_purge_without_a_folder_is_nothing(self):
        self.assertEqual(tt.purge(datetime.now(timezone.utc) + timedelta(days=99)), 0)


if __name__ == "__main__":
    unittest.main()
