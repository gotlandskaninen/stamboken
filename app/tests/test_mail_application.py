"""The membership application's mails: the receipt and the notice to matrikel admins, in its transaction.

isort:skip_file
"""

import os
from datetime import timedelta
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.mail as mail  # noqa: E402
import utils.settings as settings  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.test_mail_queue import HOST, MailTest  # noqa: E402

limiter.enabled = False


class TestApplicationFlow(MailTest):
    def setUp(self):
        super().setUp()
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        self.matrikel = da.register_user("matrikel@example.org", "pass", fullname="Matrikel Ansvarig")
        self.matrikel.add_role("matrikel_admin")
        retired = da.register_user("tidigare@example.org", "pass")
        retired.add_role("matrikel_admin")
        retired.is_active = False
        retired.save()

    def _apply(self, email="sokande@example.org", **kwargs):
        return self.client.post(
            "/api/v2/member-applications",
            json={"first_name": "Test", "last_name": "Sökande", "email": email, "gdpr_consent": True},
            **kwargs,
        )

    def receipts(self):
        return list(
            db.MailMessage.select().where(db.MailMessage.kind == "ansokan.mottagen").order_by(db.MailMessage.id)
        )

    def test_public_form_is_limited_to_ten_applications_per_client_and_hour(self):
        """The limit that applies: herdbook.py wraps create_application in limiter.limit("10 per hour")."""
        limiter.reset()
        limiter.enabled = True
        self.addCleanup(limiter.reset)
        self.addCleanup(setattr, limiter, "enabled", False)
        client = {"headers": {"X-Forwarded-For": "192.0.2.10"}}  # documentation addresses (RFC 5737)
        codes = [self._apply(f"s{i}@example.org", **client).status_code for i in range(11)]
        self.assertEqual(codes, [201] * 10 + [429])
        self.assertEqual(self._apply(headers={"X-Forwarded-For": "192.0.2.11"}).status_code, 201)

    def test_one_receipt_per_address_and_day(self):
        for email in ("sokande@example.org", "Sokande@Example.org", "annan@example.org"):
            self.assertEqual(self._apply(email).status_code, 201)
        receipts = self.receipts()
        self.assertEqual(
            [r.recipient_id for r in receipts],
            [a.id for a in db.MemberApplication.select().order_by(db.MemberApplication.id)][::2],
        )
        self.assertEqual(db.MailMessage.select().where(db.MailMessage.kind == "ansokan.ny").count(), 3)
        day = self.now.date().isoformat()
        self.assertEqual(receipts[0].dedupe_key, f"ansokan.mottagen:{mail.address_hash('sokande@example.org')}:{day}")
        self.assertNotIn("sokande", receipts[0].dedupe_key)

        with mock.patch.object(mail, "_utcnow", return_value=self.now + timedelta(days=1)):
            self.assertEqual(self._apply().status_code, 201)
        self.assertEqual(len(self.receipts()), 3)  # a new day, a new receipt

        mail.forget_recipient("application", receipts[0].recipient_id)
        self.assertIsNone(self.receipts()[0].dedupe_key)  # the address's HMAC goes with the rest

    def test_receipts_without_link_secret(self):
        """Log mode may run without LINK_SECRET; nothing is sent, so the receipt is queued without the limit."""
        with mock.patch.multiple(settings.mail, mode="log", link_secret=""):
            self.assertEqual([self._apply().status_code for _ in range(2)], [201, 201])
        self.assertEqual(len(self.receipts()), 2)

    def test_application_queues_the_receipt_and_the_notice(self):
        resp = self._apply()
        self.assertEqual(resp.status_code, 201)
        app_id = resp.get_json()["id"]
        rows = [
            (r.kind, r.recipient_kind, r.recipient_id, r.category, r.ref_type, r.ref_id)
            for r in db.MailMessage.select().order_by(db.MailMessage.id)
        ]
        self.assertEqual(
            rows,
            [
                ("ansokan.mottagen", "application", app_id, "T", "member_application", app_id),
                ("ansokan.ny", "user", self.matrikel.id, "N", "member_application", app_id),
            ],
        )
        relay = self.relay()
        self.assertEqual(mail.send_pending(self.now), 2)
        to = {envelope_to[0]: msg for msg, _, envelope_to in relay.sent}
        self.assertEqual(set(to), {"sokande@example.org", "matrikel@example.org"})
        notice = to["matrikel@example.org"].get_content()
        self.assertIn(f"https://{HOST}/medlem/ansokningar", notice)
        self.assertNotIn("Sökande", notice)  # the notice names no applicant

    def test_rolled_back_application_queues_nothing(self):
        real = mail.enqueue_mail

        def notice_fails(kind, *args, **kwargs):
            if kind == "ansokan.ny":
                raise RuntimeError("queue write failed")
            return real(kind, *args, **kwargs)

        with mock.patch.object(mail, "enqueue_mail", notice_fails), self.assertRaises(RuntimeError):
            self._apply()
        self.assertEqual(db.MemberApplication.select().count(), 0)
        self.assertEqual(db.MailMessage.select().count(), 0)

    def test_notice_cancelled_once_the_application_is_handled(self):
        a = self.application(status="approved")
        row_id = mail.enqueue_mail("ansokan.ny", "user", self.admin.id, {"application_id": a.id})
        mail.send_pending(self.now)
        self.assertEqual(self.row(row_id).status, "cancelled")


class TestApprovalMail(MailTest):
    def setUp(self):
        super().setUp()
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        db.MemberNumberCounter.delete().execute()
        db.MemberNumberCounter.create(value=0)
        self.client.post("/api/login", json={"username": "admin", "password": "pass"})

    def _approve(self, application):
        return self.client.post(f"/api/v2/member-applications/{application.id}/approve")

    def test_approval_queues_one_mail_to_the_new_member(self):
        a = self.application()
        resp = self._approve(a)
        self.assertEqual(resp.status_code, 200, resp.data)
        member_id = resp.get_json()["created_member_id"]
        rows = list(db.MailMessage.select().where(db.MailMessage.kind == "ansokan.godkand"))
        self.assertEqual(
            [(r.recipient_kind, r.recipient_id, r.category, r.ref_type, r.ref_id) for r in rows],
            [("member", member_id, "T", "member_application", a.id)],
        )
        relay = self.relay()
        self.assertEqual(mail.send_pending(self.now), 1)
        msg, _, envelope_to = relay.sent[0]
        self.assertEqual(envelope_to, ["sokande@example.org"])
        self.assertIn("godkänd", msg["Subject"])
        self.assertIn("hör av sig", msg.get_content())

    def test_failed_approval_queues_nothing(self):
        a = self.application()
        audit = mock.patch("blueprints.member_applications.write_matrikel_audit", side_effect=RuntimeError("audit"))
        with audit, self.assertRaises(RuntimeError):
            self._approve(a)
        self.assertEqual(db.MemberApplication.get_by_id(a.id).status, "pending")
        self.assertEqual(db.MailMessage.select().where(db.MailMessage.kind == "ansokan.godkand").count(), 0)

    def test_already_handled_application_queues_nothing(self):
        a = self.application(status="rejected")
        self.assertEqual(self._approve(a).status_code, 409)
        self.assertEqual(db.MailMessage.select().count(), 0)
