"""
The outgoing mail queue (mejlkön) against Postgres, with SMTP replaced by a fake relay.

Covers the queue's checks: no mail on rollback, the three modes and the startup guard, the retry ladder and
the error classes, two senders at once and a reclaimed claim, cancelling builders, dedupe, scrubbed errors,
erasure, retention, bounces by Message-ID, and that no row holds an address. Synthetic data only.
"""

import json
import os
import re
import smtplib
import subprocess
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import utils.database as db
import utils.mail as mail
import utils.settings as settings
from jinja2 import DictLoader, Environment, StrictUndefined

from tests.database_test import _USE_POSTGRES, DatabaseTest

SECRET = "test-link-secret"
HOST = "stambok.example.org"


class FakeRelay:
    """Stands in for smtplib.SMTP. `replies` holds one exception (or None for 250) per send, in order."""

    def __init__(self, replies=(), starttls=True, refuse=None, gate=None):
        self.replies = list(replies)
        self.starttls = starttls
        self.refuse = refuse
        self.gate = gate
        self.sent = []
        self.opened = []
        self.tls = False
        self.lock = threading.Lock()
        self.cut = threading.Event()  # set when the sender shuts the socket down

    def __call__(self, host="", port=0, local_hostname=None, timeout=None):
        conn = _FakeConnection(self, local_hostname, timeout)
        if host:  # like smtplib.SMTP: a host connects at once
            conn.connect(host, port)
        return conn


class _FakeSocket:
    def __init__(self, relay):
        self.relay = relay

    def shutdown(self, how):
        self.relay.cut.set()


class _FakeConnection:
    def __init__(self, relay, local_hostname, timeout):
        self.relay = relay
        self.local_hostname, self.timeout = local_hostname, timeout
        self.sock = None

    def connect(self, host, port):
        if self.relay.refuse:
            raise self.relay.refuse
        self.relay.opened.append((host, port, self.local_hostname, self.timeout))
        self.sock = _FakeSocket(self.relay)
        return 220, b"ready"

    def ehlo(self):
        return 250, b"ok"

    def has_extn(self, name):
        return name == "starttls" and self.relay.starttls

    def starttls(self, context=None):
        self.relay.tls = True

    def send_message(self, msg, from_addr=None, to_addrs=None):
        if self.relay.gate:
            self.relay.gate(msg)
        with self.relay.lock:
            reply = self.relay.replies.pop(0) if self.relay.replies else None
            if reply is None:
                self.relay.sent.append((msg, from_addr, to_addrs))
        if reply is not None:
            raise reply

    def quit(self):
        pass

    def close(self):
        pass


def _row_id(msg):
    return int(re.match(r"<mail-(\d+)\.", msg["Message-ID"]).group(1))


def _refused(code, text, address="sokande@example.org"):
    return smtplib.SMTPRecipientsRefused({address: (code, text.encode())})


@unittest.skipUnless(_USE_POSTGRES, "the sender's claim uses FOR UPDATE SKIP LOCKED")
class MailTest(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc)
        for patch in (
            mock.patch.multiple(settings.mail, mode="live", link_secret=SECRET, allowlist=[]),
            mock.patch.object(settings.service, "host", f"https://{HOST}"),
            mock.patch.object(mail, "_utcnow", return_value=self.now),  # the queue's clock stands still
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def relay(self, **kwargs):
        fake = FakeRelay(**kwargs)
        patch = mock.patch.object(mail.smtplib, "SMTP", fake)
        patch.start()
        self.addCleanup(patch.stop)
        return fake

    def application(self, email="sokande@example.org", status="pending"):
        return db.MemberApplication.create(
            first_name="Test", last_name="Sökande", email=email, gdpr_consented_at=datetime.now(), status=status
        )

    def queue(self, email="sokande@example.org", **kwargs):
        """A receipt to a fresh applicant; returns the row id."""
        a = self.application(email)
        return mail.enqueue_mail("ansokan.mottagen", "application", a.id, {"application_id": a.id}, **kwargs)

    def row(self, row_id):
        return db.MailMessage.get_by_id(row_id)

    def attempts(self, row_id):
        return list(db.MailAttempt.select().where(db.MailAttempt.message == row_id).order_by(db.MailAttempt.id))


class TestEnqueue(MailTest):
    def test_rollback_leaves_no_row(self):
        with self.assertRaises(RuntimeError), db.DB_PROXY.atomic():
            self.queue()
            raise RuntimeError("the write failed")
        self.assertEqual(db.MailMessage.select().count(), 0)

    def test_nested_rollback_takes_only_its_own_mail(self):
        with db.DB_PROXY.atomic():
            kept = self.queue("kvar@example.org")
            with self.assertRaises(RuntimeError), db.DB_PROXY.atomic():
                self.queue("borta@example.org")
                raise RuntimeError("the inner write failed")
        self.assertEqual([r.id for r in db.MailMessage.select()], [kept])

    def test_same_dedupe_key_gives_one_row_and_keeps_the_transaction(self):
        with db.DB_PROXY.atomic():
            first = self.queue(dedupe_key="paminnelse:2027:herd:1")
            second = self.queue(dedupe_key="paminnelse:2027:herd:1")
            db.Genebank.create(name="Efter dubbletten")  # the caller's transaction is still usable
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(db.MailMessage.select().count(), 1)
        self.assertTrue(db.Genebank.select().where(db.Genebank.name == "Efter dubbletten").exists())

    def test_params_take_only_ids_and_flags(self):
        a = self.application()
        for bad in (
            {"email": "sokande@example.org"},
            {"token": "c2VjcmV0"},
            {"ids": [1, 2]},
            {"Herd-Id": 1},
            {"share": 0.5},
        ):
            with self.subTest(params=bad), self.assertRaises(ValueError):
                mail.enqueue_mail("ansokan.mottagen", "application", a.id, bad)
        with self.assertRaises(ValueError):
            mail.enqueue_mail("finns.inte", "application", a.id)
        self.assertEqual(db.MailMessage.select().count(), 0)

    def test_registry_sets_priority_category_and_columns(self):
        a = self.application()
        later = self.now + timedelta(hours=1)
        row_id = mail.enqueue_mail(
            "ansokan.mottagen",
            "user",
            self.admin.id,
            {"application_id": a.id, "example": True},
            ref=("member_application", a.id),
            herd=self.herds[0],
            genebank=self.genebanks[0].id,
            not_before=later,
            created_by=self.manager,
        )
        row = self.row(row_id)
        self.assertEqual((row.kind, row.priority, row.category, row.status), ("ansokan.mottagen", 1, "T", "queued"))
        self.assertEqual((row.ref_type, row.ref_id), ("member_application", a.id))
        self.assertEqual(
            (row.herd_id, row.genebank_id, row.created_by_id), (self.herds[0].id, self.genebanks[0].id, self.manager.id)
        )
        self.assertEqual(row.next_attempt_at, later)
        self.assertEqual(mail.send_pending(self.now), 0)  # not due yet


class TestModes(MailTest):
    def test_log_mode_opens_no_connection(self):
        row_id = self.queue()
        smtp = mock.Mock(side_effect=AssertionError("log mode opened an SMTP connection"))
        with (
            mock.patch.multiple(settings.mail, mode="log", link_secret=""),
            mock.patch.object(mail.smtplib, "SMTP", smtp),
            self.assertLogs("herdbook.mail", "INFO") as logs,
        ):
            self.assertEqual(mail.send_pending(self.now), 1)
        smtp.assert_not_called()
        self.assertEqual(self.row(row_id).status, "logged")
        self.assertEqual(self.attempts(row_id), [])
        self.assertTrue(any("Vi har tagit emot din ansökan" in line for line in logs.output))
        self.assertFalse(any("@" in line for line in logs.output))

    def test_log_mode_masks_link_tokens_in_the_text(self):
        self.queue()
        token = "4711." + "a" * 22  # shaped like link_token; built, so no scanner takes it for a secret
        rendered = (f"Din länk {token}", f"Öppna https://{HOST}/rapport/{token}")
        with (
            mock.patch.multiple(settings.mail, mode="log"),
            mock.patch.object(mail, "render", return_value=rendered),
            self.assertLogs("herdbook.mail", "INFO") as logs,
        ):
            mail.send_pending(self.now)
        text = "\n".join(logs.output)
        self.assertIn(f"Din länk 4711.***\n\nÖppna https://{HOST}/rapport/4711.***", text)
        self.assertNotIn(token, text)

    def test_allowlist_sends_to_listed_and_blocks_the_rest(self):
        domain, named, other = (
            self.queue("a@example.org"),
            self.queue("named@example.net"),
            self.queue("other@example.net"),
        )
        relay = self.relay()
        with mock.patch.multiple(settings.mail, mode="allowlist", allowlist=["@example.org", "named@example.net"]):
            self.assertEqual(mail.send_pending(self.now), 3)
        self.assertEqual(sorted(_row_id(msg) for msg, _, _ in relay.sent), [domain, named])
        self.assertTrue(all(msg["Subject"].startswith("[Demo] ") for msg, _, _ in relay.sent))
        blocked = self.row(other)
        self.assertEqual(blocked.status, "blocked")
        self.assertNotIn("@", blocked.last_error)

    def test_startup_guard(self):
        cases = [
            ("live", True, SECRET, True),
            ("live", False, "", True),
            ("allowlist", True, "", True),
            ("skarpt", False, SECRET, True),
            ("live", False, SECRET, False),
            ("allowlist", True, SECRET, False),
            ("log", True, "", False),
        ]
        for mode, demo, secret, refused in cases:
            with (
                self.subTest(mode=mode, demo=demo, secret=bool(secret)),
                mock.patch.multiple(settings.mail, mode=mode, link_secret=secret),
                mock.patch.object(settings.service, "demo_instance", demo),
            ):
                if refused:
                    with self.assertRaises(RuntimeError):
                        settings.refuse_unsafe_mail_settings()
                else:
                    settings.refuse_unsafe_mail_settings()

    def test_app_import_refuses_live_mail_on_the_demo(self):
        """The guard runs when the app is imported: a demo with MAIL_MODE=live never comes up."""
        env = {**os.environ, "MAIL_MODE": "live", "DEMO_INSTANCE": "true", "LINK_SECRET": "guard-test-only"}
        probe = "import pytest, herdbook\nprint('STARTED')\n"  # pytest loaded: no blocking startup if it imports
        app_dir = Path(__file__).resolve().parent.parent
        p = subprocess.run(
            [sys.executable, "-c", probe], cwd=app_dir, env=env, capture_output=True, text=True, timeout=120
        )
        self.assertNotIn("STARTED", p.stdout)
        self.assertIn("MAIL_MODE=live is refused", p.stderr)


class TestSending(MailTest):
    def test_message_headers_and_body(self):
        row_id = self.queue()
        relay = self.relay()
        self.assertEqual(mail.send_pending(self.now), 1)
        ((msg, envelope_from, envelope_to),) = relay.sent
        sender = settings.mail.sender
        self.assertEqual(msg["From"], f"Stamboken <{sender}>")
        self.assertEqual((msg["Reply-To"], envelope_from, envelope_to), (sender, sender, ["sokande@example.org"]))
        self.assertRegex(msg["Message-ID"], rf"^<mail-{row_id}\.[0-9a-f]{{16}}@{re.escape(HOST)}>$")
        self.assertEqual(msg["Auto-Submitted"], "auto-generated")
        self.assertEqual(msg["Subject"], "Vi har tagit emot din ansökan om medlemskap")
        self.assertTrue(msg.get_content().rstrip().endswith("Stamboken, Föreningen Gotlandskaninen"))
        self.assertTrue(relay.tls)
        self.assertEqual(relay.opened, [(settings.mail.smtp_host, settings.mail.smtp_port, HOST, 60)])
        row = self.row(row_id)
        self.assertEqual((row.status, row.attempts, row.sent_at), ("sent", 1, self.now))
        self.assertEqual(row.address_hash, mail.address_hash("sokande@example.org"))
        self.assertIsNone(row.claim_token)
        self.assertEqual([a.result for a in self.attempts(row_id)], ["sent"])

    def test_one_connection_per_run_and_at_most_thirty(self):
        ids = [self.queue(f"s{i}@example.org") for i in range(mail.MAX_PER_RUN + 2)]
        relay = self.relay()
        self.assertEqual(mail.send_pending(self.now), mail.MAX_PER_RUN)
        self.assertEqual(len(relay.opened), 1)
        self.assertEqual([_row_id(msg) for msg, _, _ in relay.sent], ids[: mail.MAX_PER_RUN])
        self.assertEqual(mail.send_pending(self.now), 2)

    def test_priority_goes_first(self):
        bulk = self.queue("bulk@example.org")
        db.MailMessage.update(priority=2).where(db.MailMessage.id == bulk).execute()
        urgent = self.queue("urgent@example.org")
        db.MailMessage.update(priority=0).where(db.MailMessage.id == urgent).execute()
        relay = self.relay()
        mail.send_pending(self.now)
        self.assertEqual([_row_id(msg) for msg, _, _ in relay.sent], [urgent, bulk])

    def test_subject_cannot_inject_headers(self):
        env = Environment(
            loader=DictLoader(
                {
                    "x.txt": "{% block subject %}Hej {{ name }}{% endblock %}{% block body %}Text{% endblock %}",
                    "_fot.txt": "Fot\n",
                }
            ),
            undefined=StrictUndefined,
        )
        with mock.patch.object(mail, "_TEMPLATES", env):
            subject, body = mail.render("x", {"name": "Anna\r\nBcc: someone@example.net"})
        self.assertNotIn("\n", subject)
        self.assertNotIn("\r", subject)
        self.assertEqual(body, "Text\n\nFot")

    def test_attachments_from_the_builder(self):
        pdf = b"%PDF-1.4 test"
        build = mock.Mock(return_value={"attachments": [("intyg.pdf", "application/pdf", pdf)]})
        row_id = self.queue()
        relay = self.relay()
        with mock.patch.dict(mail.MAIL_KINDS, {"ansokan.mottagen": mail.MailKind(1, "T", build)}):
            mail.send_pending(self.now)
        ((msg, _, _),) = relay.sent
        (part,) = list(msg.iter_attachments())
        self.assertEqual(
            (part.get_filename(), part.get_content_type(), part.get_content()), ("intyg.pdf", "application/pdf", pdf)
        )
        self.assertEqual(self.row(row_id).status, "sent")


class TestErrorClasses(MailTest):
    def test_temporary_failures_follow_the_ladder_then_fail(self):
        row_id = self.queue()
        refusal = _refused(450, "4.2.1 Mailbox busy <sokande@example.org>")
        relay = self.relay(replies=[refusal] * 7)
        now = self.now
        for attempt, delay in enumerate(mail.RETRY_DELAYS, start=1):
            self.assertEqual(mail.send_pending(now), 1)
            row = self.row(row_id)
            self.assertEqual((row.status, row.attempts, row.next_attempt_at), ("queued", attempt, now + delay))
            self.assertEqual(mail.send_pending(row.next_attempt_at - timedelta(seconds=1)), 0)
            now = row.next_attempt_at
        self.assertEqual(mail.send_pending(now), 1)
        row = self.row(row_id)
        self.assertEqual((row.status, row.attempts), ("failed", 7))
        self.assertNotIn("@", row.last_error)
        attempts = self.attempts(row_id)
        self.assertEqual([(a.result, a.smtp_code) for a in attempts], [("temporary", "4.2.1")] * 7)
        self.assertEqual(relay.sent, [])

    def test_unknown_mailbox_fails_at_once(self):
        row_id = self.queue()
        self.relay(replies=[_refused(550, "5.1.1 The account <sokande@example.org> does not exist")])
        mail.send_pending(self.now)
        row = self.row(row_id)
        self.assertEqual((row.status, row.attempts), ("failed", 1))
        self.assertEqual(row.address_hash, mail.address_hash("sokande@example.org"))
        self.assertNotIn("@", row.last_error)
        (attempt,) = self.attempts(row_id)
        self.assertEqual((attempt.result, attempt.smtp_code), ("permanent", "5.1.1"))
        self.assertNotIn("@", attempt.detail)

    def test_relay_denied_is_systemic_and_pauses_the_sender(self):
        first, second = self.queue("a@example.org"), self.queue("b@example.org")
        denied = smtplib.SMTPSenderRefused(550, b"5.7.1 Invalid credentials for relay", settings.mail.sender)
        relay = self.relay(replies=[denied])
        self.assertEqual(mail.send_pending(self.now), 1)  # the run stops at the first
        row = self.row(first)
        self.assertEqual((row.status, row.attempts), ("queued", 0))
        self.assertEqual(self.row(second).status, "queued")
        self.assertEqual([(a.result, a.smtp_code) for a in self.attempts(first)], [("systemic", "5.7.1")])
        self.assertEqual(db.MailSender.get_by_id(1).paused_until, self.now + mail.PAUSE_AFTER_SYSTEMIC)
        self.assertGreater(row.next_attempt_at, self.now + mail.PAUSE_AFTER_SYSTEMIC)

        later = self.now + timedelta(minutes=1)
        self.assertEqual(mail.send_pending(later), 0)  # paused, but the heartbeat still beats
        self.assertEqual(db.MailSender.get_by_id(1).last_run_at, later)

        self.assertEqual(mail.send_pending(self.now + timedelta(minutes=6)), 2)
        self.assertEqual(sorted(_row_id(msg) for msg, _, _ in relay.sent), [first, second])

    def test_refused_sender_is_systemic_whatever_the_code(self):
        """A refused MAIL FROM would fail every mail alike, so it pauses the sender instead."""
        first, second = self.queue("a@example.org"), self.queue("b@example.org")
        refused = smtplib.SMTPSenderRefused(553, b"5.1.8 Sender address rejected", settings.mail.sender)
        relay = self.relay(replies=[refused])
        self.assertEqual(mail.send_pending(self.now), 1)
        row = self.row(first)
        self.assertEqual((row.status, row.attempts, row.address_hash), ("queued", 0, None))
        self.assertEqual([(a.result, a.smtp_code) for a in self.attempts(first)], [("systemic", "5.1.8")])
        self.assertEqual(self.row(second).status, "queued")
        self.assertIsNotNone(db.MailSender.get_by_id(1).paused_until)
        self.assertEqual(relay.sent, [])

    def test_policy_refusal_of_one_recipient_fails_only_that_mail(self):
        """5.7.1 at RCPT is about this recipient, not the relay: the next mail goes out in the same run."""
        first, second = self.queue("a@example.org"), self.queue("b@example.org")
        refusal = _refused(550, "5.7.1 Recipient address rejected by policy <a@example.org>", "a@example.org")
        relay = self.relay(replies=[refusal])
        self.assertEqual(mail.send_pending(self.now), 2)
        self.assertEqual((self.row(first).status, self.row(first).attempts), ("failed", 1))
        self.assertEqual([(a.result, a.smtp_code) for a in self.attempts(first)], [("permanent", "5.7.1")])
        self.assertEqual([_row_id(msg) for msg, _, _ in relay.sent], [second])
        self.assertIsNone(db.MailSender.get_by_id(1).paused_until)

    def test_size_limit_fails_only_that_mail(self):
        """552 at MAIL FROM (smtplib sends SIZE=) or at DATA is this message's own failure."""
        too_big = b"5.3.4 Message size exceeds fixed maximum message size"
        at_mail_from, at_data, fine = (self.queue(f"{x}@example.org") for x in "abc")
        relay = self.relay(
            replies=[smtplib.SMTPSenderRefused(552, too_big, settings.mail.sender), smtplib.SMTPDataError(552, too_big)]
        )
        self.assertEqual(mail.send_pending(self.now), 3)
        for row_id in (at_mail_from, at_data):
            self.assertEqual((self.row(row_id).status, self.row(row_id).attempts), ("failed", 1))
            self.assertEqual([(a.result, a.smtp_code) for a in self.attempts(row_id)], [("permanent", "5.3.4")])
        self.assertEqual([_row_id(msg) for msg, _, _ in relay.sent], [fine])
        self.assertIsNone(db.MailSender.get_by_id(1).paused_until)

    def test_systemic_row_does_not_head_the_queue_after_the_pause(self):
        first, second = self.queue("a@example.org"), self.queue("b@example.org")
        denied = smtplib.SMTPSenderRefused(550, b"5.7.1 Invalid credentials for relay", settings.mail.sender)
        relay = self.relay(replies=[denied])
        mail.send_pending(self.now)
        self.assertEqual(mail.send_pending(db.MailSender.get_by_id(1).paused_until), 1)
        self.assertEqual([_row_id(msg) for msg, _, _ in relay.sent], [second])
        self.assertEqual(self.row(first).status, "queued")

    def test_row_refused_three_times_while_other_mail_goes_through_fails(self):
        stuck = self.queue("stuck@example.org")
        denied = smtplib.SMTPSenderRefused(550, b"5.7.1 Sender rejected", settings.mail.sender)

        def gate(msg):
            if _row_id(msg) == stuck:
                raise denied

        self.relay(gate=gate)
        results = lambda: [a.result for a in self.attempts(stuck)]  # noqa: E731
        for _ in range(3):  # nothing else goes out between the refusals: the relay's fault, never the mail's
            mail.send_pending(self.row(stuck).next_attempt_at)
        self.assertEqual(results(), ["systemic"] * 3)
        for i in range(2):  # now other mail is accepted in between
            other = self.queue(f"other{i}@example.org")
            self.assertEqual(mail.send_pending(db.MailSender.get_by_id(1).paused_until), 1)
            self.assertEqual(self.row(other).status, "sent")
            mail.send_pending(self.row(stuck).next_attempt_at)
        row = self.row(stuck)
        self.assertEqual((row.status, row.attempts), ("failed", 1))
        self.assertEqual(results(), ["systemic"] * 4 + ["permanent"])

        # "Försök igen" starts the count over.
        later = self.attempts(stuck)[-1].at + timedelta(minutes=1)
        db.MailMessage.update(status="queued", attempts=0, next_attempt_at=later).where(
            db.MailMessage.id == stuck
        ).execute()
        mail.send_pending(later)
        self.assertEqual((self.row(stuck).status, results()[-1]), ("queued", "systemic"))

    def test_unexpected_send_error_counts_as_temporary(self):
        first, second = self.queue("a@example.org"), self.queue("b@example.org")
        self.relay(replies=[ValueError("odd reply from the relay")])
        self.assertEqual(mail.send_pending(self.now), 2)
        self.assertEqual((self.row(first).status, self.row(first).attempts), ("queued", 1))
        self.assertEqual(self.row(second).status, "sent")

    def test_connection_failures_are_systemic(self):
        for name, kwargs in (
            ("refused", {"refuse": ConnectionRefusedError("connection refused")}),
            ("no STARTTLS", {"starttls": False}),
            ("421 at connect", {"refuse": smtplib.SMTPConnectError(421, b"4.7.0 Try again later")}),
        ):
            with self.subTest(name):
                db.MailSender.delete().execute()
                row_id = self.queue()
                relay = self.relay(**kwargs)
                self.assertEqual(mail.send_pending(self.now), 1)
                row = self.row(row_id)
                self.assertEqual((row.status, row.attempts), ("queued", 0))
                self.assertEqual(self.attempts(row_id)[-1].result, "systemic")
                self.assertIsNotNone(db.MailSender.get_by_id(1).paused_until)
                self.assertEqual(relay.sent, [])
                db.MailMessage.delete().execute()

    def test_disconnect_counts_as_temporary_and_reconnects(self):
        first, second = self.queue("a@example.org"), self.queue("b@example.org")
        relay = self.relay(replies=[smtplib.SMTPServerDisconnected("Connection unexpectedly closed")])
        self.assertEqual(mail.send_pending(self.now), 2)
        self.assertEqual((self.row(first).status, self.row(first).attempts), ("queued", 1))
        self.assertEqual(self.row(second).status, "sent")
        self.assertEqual(len(relay.opened), 2)

    def test_two_dropped_connections_in_a_row_pause_the_sender(self):
        """A relay that accepts the connection and then drops every transaction must not use up the mails."""
        first, second, third = (self.queue(f"{x}@example.org") for x in "abc")
        drops = [smtplib.SMTPServerDisconnected("Connection unexpectedly closed"), TimeoutError("timed out")]
        relay = self.relay(replies=drops)
        self.assertEqual(mail.send_pending(self.now), 2)
        self.assertEqual((self.row(first).status, self.row(first).attempts), ("queued", 1))
        self.assertEqual((self.row(second).status, self.row(second).attempts), ("queued", 0))
        self.assertEqual([a.result for a in self.attempts(second)], ["systemic"])
        self.assertEqual(self.attempts(third), [])
        self.assertIsNotNone(db.MailSender.get_by_id(1).paused_until)
        self.assertEqual(relay.sent, [])

    def test_same_message_id_on_every_attempt(self):
        self.queue()
        relay = self.relay(replies=[_refused(451, "4.3.0 Temporary failure")])
        failing_id = []
        relay.gate = lambda msg: failing_id.append(msg["Message-ID"])
        mail.send_pending(self.now)
        mail.send_pending(self.now + timedelta(minutes=2))
        self.assertEqual(len(failing_id), 2)
        self.assertEqual(failing_id[0], failing_id[1])


class TestCancel(MailTest):
    def test_builder_returning_none_cancels(self):
        row_id = self.queue()
        with mock.patch.dict(mail.MAIL_KINDS, {"ansokan.mottagen": mail.MailKind(1, "T", lambda params: None)}):
            mail.send_pending(self.now)
        row = self.row(row_id)
        self.assertEqual((row.status, row.last_error), ("cancelled", "mejlet är inte längre aktuellt"))

    def test_unknown_kind_or_recipient_kind_cancels_cleanly(self):
        a = self.application()
        unknown_kind = db.MailMessage.create(
            kind="finns.inte",
            params={},
            recipient_kind="application",
            recipient_id=a.id,
            priority=1,
            category="T",
            next_attempt_at=self.now,
        ).id
        unknown_recipient = mail.enqueue_mail("ansokan.mottagen", "inbox_sender", 1, {"application_id": a.id})
        self.relay()
        mail.send_pending(self.now)
        self.assertEqual(
            (self.row(unknown_kind).status, self.row(unknown_kind).last_error),
            ("cancelled", "okänd mejltyp: finns.inte"),
        )
        self.assertEqual(
            (self.row(unknown_recipient).status, self.row(unknown_recipient).last_error),
            ("cancelled", "okänd mottagartyp: inbox_sender"),
        )

    def test_missing_address_cancels(self):
        a = self.application()
        no_email = db.Member.create(
            membership=db.Membership.create(member_number=9001), first_name="Test", last_name="Utan", email=None
        )
        broken = db.Member.create(
            membership=db.Membership.create(member_number=9002),
            first_name="Test",
            last_name="Trasig",
            email="not an address\r\nBcc: x",
        )
        params = {"application_id": a.id}
        ids = [
            mail.enqueue_mail("ansokan.mottagen", "member", no_email.id, params),
            mail.enqueue_mail("ansokan.mottagen", "member", broken.id, params),
            mail.enqueue_mail("ansokan.mottagen", "member", 999999, params),
        ]
        relay = self.relay()
        mail.send_pending(self.now)
        for row_id in ids:
            self.assertEqual(
                (self.row(row_id).status, self.row(row_id).last_error), ("cancelled", "mottagaren saknar e-post")
            )
        self.assertEqual(relay.sent, [])

    def test_builder_crash_is_a_counted_temporary_failure(self):
        row_id = self.queue()
        build = mock.Mock(side_effect=ValueError("no data for sokande@example.org"))
        with mock.patch.dict(mail.MAIL_KINDS, {"ansokan.mottagen": mail.MailKind(1, "T", build)}):
            mail.send_pending(self.now)
        row = self.row(row_id)
        self.assertEqual((row.status, row.attempts), ("queued", 1))
        self.assertEqual(row.last_error, "bygget misslyckades: ValueError: no data for <adress>")


class TestConcurrentSenders(MailTest):
    def _sender(self, errors, name=None):
        def run():
            try:
                mail.send_pending()
            except Exception as exc:  # pylint: disable=broad-except
                errors.append(exc)
            finally:
                db.DB_PROXY.close()

        return threading.Thread(target=run, name=name)

    def test_two_senders_send_each_row_exactly_once(self):
        ids = [self.queue(f"s{i}@example.org") for i in range(8)]
        both_sending = threading.Barrier(2, timeout=10)
        first_send = threading.local()

        def gate(msg):
            # Each sender's first mail waits until the other is mid-send too: both hold a claim at once.
            if not getattr(first_send, "done", False):
                first_send.done = True
                both_sending.wait()

        relay = self.relay(gate=gate)
        errors = []
        threads = [self._sender(errors) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
        self.assertEqual(errors, [])
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertFalse(both_sending.broken, "the two senders never overlapped")
        self.assertEqual(sorted(_row_id(msg) for msg, _, _ in relay.sent), ids)
        self.assertEqual({r.status for r in db.MailMessage.select()}, {"sent"})
        self.assertEqual(db.MailAttempt.select().count(), len(ids))

    def test_claim_skips_a_row_another_sender_holds(self):
        first, second = self.queue("a@example.org"), self.queue("b@example.org")
        locked, release = threading.Event(), threading.Event()

        def hold():
            try:
                with db.DB_PROXY.atomic():
                    db.DB_PROXY.execute_sql("SELECT id FROM mail_message WHERE id = %s FOR UPDATE", (first,))
                    locked.set()
                    release.wait(timeout=5)  # without SKIP LOCKED the claim waits this out and takes `first`
            finally:
                db.DB_PROXY.close()

        holder = threading.Thread(target=hold)
        holder.start()
        self.assertTrue(locked.wait(timeout=10))
        try:
            claimed = mail._claim(self.now)  # pylint: disable=protected-access
        finally:
            release.set()
            holder.join(timeout=10)
        self.assertEqual(claimed.id, second)
        self.assertEqual(self.row(first).status, "queued")

    def test_sender_stuck_in_smtp_gives_up_long_before_its_row_can_be_reclaimed(self):
        """
        A relay that never answers is cut off at SEND_DEADLINE, counted from the claim's renewal and far below
        RECLAIM_AFTER, so no other sender can take the row while this one may still be talking to the relay.
        """
        row_id = self.queue()

        def gate(msg):  # silent until the sender shuts the socket down; without a deadline it accepts after 10 s
            if relay.cut.wait(timeout=10):
                raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

        relay = self.relay(gate=gate)
        started = time.monotonic()
        with mock.patch.object(mail, "SEND_DEADLINE", 0.2, create=True):
            self.assertEqual(mail.send_pending(), 1)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(relay.sent, [])
        row = self.row(row_id)
        self.assertEqual((row.status, row.attempts), ("queued", 1))
        self.assertIn("TimeoutError", row.last_error)
        self.assertLess(mail.SEND_DEADLINE * 4, mail.RECLAIM_AFTER.total_seconds())

    def test_slow_sender_that_lost_its_claim_neither_sends_nor_writes(self):
        real = mail.MAIL_KINDS["ansokan.mottagen"]
        relay = self.relay()
        for crash in (False, True):  # the slow build returns (the send is skipped) or fails (the write is dropped)
            with self.subTest(crash=crash):
                row_id = self.queue(f"slow{int(crash)}@example.org")
                in_build, release = threading.Event(), threading.Event()

                def build(params, crash=crash, in_build=in_build, release=release):
                    if threading.current_thread().name == "slow":
                        in_build.set()
                        release.wait(timeout=10)
                        if crash:
                            raise RuntimeError("the build failed late")
                    return real.build(params)

                errors = []
                slow = self._sender(errors, name="slow")
                with mock.patch.dict(mail.MAIL_KINDS, {"ansokan.mottagen": real._replace(build=build)}):
                    slow.start()
                    self.assertTrue(in_build.wait(timeout=10))
                    # The slow sender's claim is past the reclaim limit: the next run takes the row over and sends it.
                    db.MailMessage.update(claimed_at=self.now - timedelta(minutes=11)).where(
                        db.MailMessage.id == row_id
                    ).execute()
                    self.assertEqual(mail.send_pending(), 1)
                    with self.assertLogs("herdbook.mail", "WARNING") as logs:
                        release.set()
                        slow.join(timeout=10)
                self.assertEqual(errors, [])
                self.assertTrue(any("reclaimed" in line for line in logs.output))
                self.assertEqual([_row_id(msg) for msg, _, _ in relay.sent].count(row_id), 1)
                row = self.row(row_id)
                self.assertEqual((row.status, row.attempts, row.last_error), ("sent", 1, None))
                self.assertEqual([a.result for a in self.attempts(row_id)], ["sent"])


class TestPrivacy(MailTest):
    def test_last_error_and_detail_never_hold_an_address(self):
        rows = [self.queue(f"p{i}@example.org") for i in range(4)]
        self.relay(
            replies=[
                _refused(550, "5.1.1 <p0@example.org> unknown", "p0@example.org"),
                _refused(452, "4.2.2 <p1@example.org> over quota", "p1@example.org"),
                smtplib.SMTPDataError(554, b"5.6.0 rejected for p2@example.org, contact postmaster@example.net"),
            ]
        )
        mail.send_pending(self.now)
        self.assertTrue(mail.record_bounce(mail.message_id(rows[3]), "550 5.1.1 <p3@example.org> gone"))
        texts = [r.last_error for r in db.MailMessage.select()] + [a.detail for a in db.MailAttempt.select()]
        self.assertEqual(len([t for t in texts if t]), 8)
        for text in texts:
            self.assertNotIn("@", text or "")

    def test_no_row_holds_an_address_or_a_token(self):
        self.queue()
        a = self.application()
        mail.enqueue_mail("ansokan.mottagen", "user", self.admin.id, {"application_id": a.id, "example": True})
        for row in db.MailMessage.select():
            text = json.dumps(row.params)
            self.assertNotIn("@", text)
            self.assertNotIn(mail.link_token("mail", row.id), text)
            self.assertTrue(all(v is None or isinstance(v, int) for v in row.params.values()))

    def test_forget_recipient_clears_the_address_hash(self):
        a, b = self.application("a@example.org"), self.application("b@example.org")
        params = {"application_id": a.id}
        ids = [mail.enqueue_mail("ansokan.mottagen", "application", x.id, params) for x in (a, a, b)]
        self.relay()
        mail.send_pending(self.now)
        self.assertEqual(mail.forget_recipient("application", a.id), 2)
        self.assertEqual([self.row(i).address_hash is None for i in ids], [True, True, False])

    def test_purge_takes_rows_older_than_396_days(self):
        old, edge, fresh = self.queue("old@example.org"), self.queue("edge@example.org"), self.queue()
        db.MailMessage.update(created_at=self.now - timedelta(days=397)).where(db.MailMessage.id == old).execute()
        db.MailMessage.update(created_at=self.now - timedelta(days=395)).where(db.MailMessage.id == edge).execute()
        db.MailAttempt.create(message=old, at=self.now, source="smtp", result="sent")
        self.assertEqual(mail.purge_old_mail(self.now), 1)
        self.assertEqual(sorted(r.id for r in db.MailMessage.select()), [edge, fresh])
        self.assertEqual(db.MailAttempt.select().count(), 0)


class TestBounces(MailTest):
    def _sent(self):
        row_id = self.queue()
        relay = self.relay()
        mail.send_pending(self.now)
        ((msg, _, _),) = relay.sent
        return row_id, msg["Message-ID"]

    def test_bounce_found_by_message_id(self):
        row_id, message_id = self._sent()
        self.assertTrue(mail.record_bounce(message_id, "550 5.1.1 <sokande@example.org>: user unknown"))
        row = self.row(row_id)
        self.assertEqual(row.status, "bounced")
        self.assertNotIn("@", row.last_error)
        bounce = self.attempts(row_id)[-1]
        self.assertEqual((bounce.source, bounce.result, bounce.smtp_code), ("bounce", "bounce", "5.1.1"))

    def test_other_environment_or_forged_id_touches_nothing(self):
        row_id, message_id = self._sent()
        mac = re.match(r"<mail-\d+\.([0-9a-f]{16})@", message_id).group(1)
        for other in (
            message_id.replace(f"@{HOST}>", "@demo.example.org>"),
            message_id.replace(mac, "0" * 16),
            f"<mail-{row_id + 1}.{mac}@{HOST}>",
            "<CAF00@mail.example.net>",
            "",
        ):
            with self.subTest(other=other):
                self.assertFalse(mail.record_bounce(other, "550 5.1.1 user unknown"))
        self.assertEqual(self.row(row_id).status, "sent")
        self.assertEqual([a.source for a in self.attempts(row_id)], ["smtp"])

    def test_only_a_sent_row_can_bounce(self):
        row_id, message_id = self._sent()
        for status in ("queued", "sending", "failed", "cancelled", "logged", "blocked", "bounced"):
            with self.subTest(status=status):
                db.MailMessage.update(status=status, last_error="före").where(db.MailMessage.id == row_id).execute()
                self.assertFalse(mail.record_bounce(message_id, "550 5.1.1 user unknown"))
                self.assertEqual((self.row(row_id).status, self.row(row_id).last_error), (status, "före"))
        self.assertEqual([a.source for a in self.attempts(row_id)], ["smtp"])


class TestLinks(MailTest):
    def test_token_shape(self):
        token = mail.link_token("test", 7)
        self.assertRegex(token, r"^7\.[A-Za-z0-9_-]{22}$")  # 128-bit mac, base64url, no padding
        self.assertEqual(token, mail.link_token("test", 7))
        self.assertNotEqual(token.split(".")[1], mail.link_token("test", 8).split(".")[1])
        self.assertNotEqual(token, mail.link_token("other", 7))
        with mock.patch.object(settings.mail, "link_secret", ""), self.assertRaises(RuntimeError):
            mail.link_token("test", 7)

    def test_verify_link(self):
        token = mail.link_token("test", 42)
        self.assertEqual(mail.verify_link("test", token), 42)
        mac = token.split(".")[1]
        for bad in (
            f"43.{mac}",  # another row's id with this row's mac
            f"42.{mac[:-1]}{'A' if mac[-1] != 'A' else 'B'}",
            mail.link_token("other", 42),
            f"042.{mac}",
            f"42.{mac}.x",
            "42",
            "",
            None,
            42,
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(mail.verify_link("test", bad))
        with mock.patch.object(settings.mail, "link_secret", "another-secret"):
            self.assertIsNone(mail.verify_link("test", token))  # a new LINK_SECRET invalidates every link
        with mock.patch.object(settings.mail, "link_secret", ""):
            self.assertIsNone(mail.verify_link("test", token))
