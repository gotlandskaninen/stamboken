"""The mail queue's status API (/api/v2/mail): scoping per genebank, alarms, retry and cancel, no addresses.

isort:skip_file
"""

import os
import smtplib
from datetime import timedelta

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.database as db  # noqa: E402
import utils.mail as mail  # noqa: E402
import utils.settings as settings  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.test_mail_queue import MailTest  # noqa: E402

limiter.enabled = False


class TestStatusApi(MailTest):
    def setUp(self):
        super().setUp()
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        a = self.application()
        params = {"application_id": a.id}
        gotland, mellerud = self.genebanks
        self.gotland = mail.enqueue_mail(
            "ansokan.mottagen", "application", a.id, params, ref=("member_application", a.id), genebank=gotland
        )
        self.mellerud = mail.enqueue_mail("ansokan.mottagen", "application", a.id, params, genebank=mellerud)
        self.nowhere = mail.enqueue_mail("ansokan.mottagen", "application", a.id, params)

    def login(self, username):
        self.client.get("/api/logout")
        self.client.post("/api/login", json={"username": username, "password": "pass"})

    def _ids(self, resp):
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertNotIn("@", resp.get_data(as_text=True))
        return sorted(item["id"] for item in resp.get_json()["items"])

    def test_admin_sees_all_with_alarms(self):
        self.login("admin")
        resp = self.client.get("/api/v2/mail/messages")
        self.assertEqual(self._ids(resp), sorted([self.gotland, self.mellerud, self.nowhere]))
        body = resp.get_json()
        self.assertEqual([a["code"] for a in body["alarms"]], ["queue_stalled"])  # no sender run yet
        self.assertEqual(body["items"][0]["recipient"], "Test Sökande")
        mellerud = self.genebanks[1].id
        self.assertEqual(
            self._ids(self.client.get(f"/api/v2/mail/messages?status=queued&genebank_id={mellerud}")), [self.mellerud]
        )
        self.relay()
        mail.send_pending()
        self.assertEqual(self.client.get("/api/v2/mail/messages").get_json()["alarms"], [])

    def test_manager_sees_only_their_genebank(self):
        self.login("man")
        self.assertEqual(self._ids(self.client.get("/api/v2/mail/messages")), [self.gotland])
        for row_id in (self.mellerud, self.nowhere):
            self.assertEqual(self.client.post(f"/api/v2/mail/messages/{row_id}/cancel").status_code, 404)
        self.assertEqual(self.row(self.mellerud).status, "queued")

    def test_others_are_refused(self):
        for username in ("spec", "owner"):
            self.login(username)
            self.assertEqual(self.client.get("/api/v2/mail/messages").status_code, 403)
            self.assertEqual(
                self.client.get("/api/v2/mail/status?ref_type=member_application&ref_id=1").status_code, 403
            )
        self.client.get("/api/logout")
        self.assertEqual(self.client.get("/api/v2/mail/messages").status_code, 401)

    def test_cancel_and_retry(self):
        self.login("admin")
        resp = self.client.post(f"/api/v2/mail/messages/{self.gotland}/cancel")
        self.assertEqual((resp.status_code, resp.get_json()["status"]), (200, "cancelled"))
        self.assertEqual(self.client.post(f"/api/v2/mail/messages/{self.gotland}/cancel").status_code, 409)
        self.assertEqual(self.client.post(f"/api/v2/mail/messages/{self.mellerud}/retry").status_code, 409)
        db.MailMessage.update(status="failed", attempts=7).where(db.MailMessage.id == self.mellerud).execute()
        resp = self.client.post(f"/api/v2/mail/messages/{self.mellerud}/retry")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual((resp.get_json()["status"], resp.get_json()["attempts"]), ("queued", 0))

    def test_status_gives_the_latest_row_per_kind(self):
        a = db.MemberApplication.get()
        newer = mail.enqueue_mail(
            "ansokan.mottagen", "application", a.id, {"application_id": a.id}, ref=("member_application", a.id)
        )
        self.login("admin")
        url = f"/api/v2/mail/status?ref_type=member_application&ref_id={a.id}"
        self.assertEqual(self._ids(self.client.get(url)), [newer])
        self.login("man")
        self.assertEqual(self._ids(self.client.get(url)), [self.gotland])
        self.assertEqual(self.client.get("/api/v2/mail/status?ref_type=member_application").status_code, 400)


class TestSenderAlarms(MailTest):
    def test_relay_refusing_until_a_mail_goes_out(self):
        self.queue("a@example.org")
        self.queue("b@example.org")
        denied = smtplib.SMTPSenderRefused(550, b"5.7.1 Invalid credentials for relay", settings.mail.sender)
        self.relay(replies=[denied])
        mail.send_pending(self.now)
        self.assertEqual([a["code"] for a in mail.sender_alarms(self.now)["alarms"]], ["relay_refusing"])
        later = self.now + timedelta(minutes=6)
        mail.send_pending(later)
        status = mail.sender_alarms(later)
        self.assertEqual(status["alarms"], [])
        self.assertEqual(status["last_sent_at"], later.isoformat())

    def test_queue_stalled_when_the_sender_has_not_run(self):
        self.assertEqual([a["code"] for a in mail.sender_alarms(self.now)["alarms"]], ["queue_stalled"])
        mail.send_pending(self.now)
        self.assertEqual(mail.sender_alarms(self.now + timedelta(minutes=4))["alarms"], [])
        stalled = mail.sender_alarms(self.now + timedelta(minutes=6))["alarms"]
        self.assertEqual([a["code"] for a in stalled], ["queue_stalled"])
