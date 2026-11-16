#!/usr/bin/env python3
"""
Tests for the report link's exchange (step 3, Task 2): the POST route, the code session, the headers and the logs.
Synthetic herds, addresses and tokens only.

isort:skip_file
"""

import json
import logging
from datetime import date, datetime, timedelta
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.mail as mail
import utils.report_code as report_code
import utils.settings as settings
from herdbook import APP, limiter
from utils.log_masking import TokenMaskFilter

from tests.arsrapport_fixtures import ArsrapportTest

DAY = date(2026, 1, 15)
EXCHANGE = "/api/v2/rapport/oppna"


class RapportLinkTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.multiple(settings.mail, link_secret="test-link-secret", link_hosts=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.at(DAY)
        self.round_ = self.round(2025)
        self.herd, self.code, self.token = self.new_code("G9001")
        # The app's own handlers, with the filters herdbook.py put on them: handle() runs the filter, then emit.
        self.lines = []
        real = [
            handler
            for logger in (APP.logger, logging.getLogger())
            for handler in logger.handlers
            if any(isinstance(f, TokenMaskFilter) for f in handler.filters)
        ]
        self.assertTrue(real, "herdbook.py puts TokenMaskFilter on the app's log handlers")
        for handler in real:
            patcher = mock.patch.object(handler, "emit", lambda record, h=handler: self.lines.append(h.format(record)))
            patcher.start()
            self.addCleanup(patcher.stop)

    def new_code(self, name):
        herd = db.Herd.create(genebank=self.gotland, herd=name, herd_name=f"Besättning {name}", is_active=True)
        member = self.main_member(herd, f"{name.lower()}@example.invalid")
        code = report_code.issue_code(herd, self.round_, member, now=arsrapport.now())
        return herd, code, mail.link_token("rapport", code.id)

    def exchange(self, token=None, client=None):
        return (client or self.client).post(EXCHANGE, json={"token": token or self.token})

    def session(self, client=None):
        with (client or self.client).session_transaction() as session:
            return dict(session)

    def mac(self, token=None):
        return (token or self.token).split(".")[1]

    def test_valid_token_sets_session(self):
        response = self.exchange()
        self.assertEqual((response.status_code, response.get_json()), (200, {"herd": "G9001", "year": 2025}))
        self.assertIsNotNone(db.ReportAccessCode.get_by_id(self.code.id).last_opened_at)
        session = self.session()
        self.assertEqual(session["rapport"], [[self.code.id, "prod"]])
        self.assertIn("rapport_seen", session)

    def refused(self, response):
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "lank_ogiltig"))

    def test_failures_are_lank_ogiltig(self):
        _, revoked, revoked_token = self.new_code("G9002")
        report_code.revoke(revoked, now=arsrapport.now())
        _, _, expired_token = self.new_code("G9003")
        forged = f"{self.code.id}.{'A' * 22}"
        unknown = f"{self.code.id + 999}.{self.mac()}"
        no_row = mail.link_token("rapport", self.code.id + 999)  # a valid mac for an id with no row
        for token in (forged, unknown, no_row, revoked_token, "abc", self.token[:-3], self.token + "x", None, 5):
            with self.subTest(token=str(token)[:6]):
                self.refused(self.exchange(token) if token is not None else self.client.post(EXCHANGE, json={}))
        self.at(date(2026, 4, 1))  # after the round's end
        self.refused(self.exchange(expired_token))
        self.assertNotIn("rapport", self.session())

    def test_not_json_is_415(self):
        for kwargs in ({"data": f"token={self.token}"}, {"data": json.dumps({"token": self.token})}):
            response = self.client.post(EXCHANGE, content_type="text/plain", **kwargs)
            self.assertEqual(response.status_code, 415)
        self.assertEqual(self.client.post(EXCHANGE, data={"token": self.token}).status_code, 415)
        self.assertIn(self.client.get(EXCHANGE).status_code, (404, 405))  # no GET exchange
        self.assertNotIn("rapport", self.session())

    def test_headers_no_store(self):
        for response in (self.exchange(), self.exchange(f"{self.code.id}.{'A' * 22}"), self.client.post(EXCHANGE)):
            self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_token_never_logged_or_answered(self):
        _, revoked, revoked_token = self.new_code("G9002")
        report_code.revoke(revoked, now=arsrapport.now())
        forged = f"{self.code.id}.{self.mac()[:-1]}{'A' if self.mac()[-1] != 'A' else 'B'}"
        unknown = f"{self.code.id + 999}.{self.mac()}"
        bodies = [self.exchange(token).get_data(as_text=True) for token in (self.token, forged, unknown, revoked_token)]
        with mock.patch.object(report_code, "resolve", side_effect=RuntimeError("boom")):
            bodies.append(self.exchange().get_data(as_text=True))
        for token in (self.token, forged, revoked_token):
            for text in bodies + self.lines:
                self.assertNotIn(self.mac(token), text)
        self.assertTrue(any("Report link exchange failed: RuntimeError" in line for line in self.lines))

    def test_the_token_is_in_no_url(self):
        """The token travels in the body: the request line a server logs has none."""
        self.exchange()
        text = "\n".join(self.lines)
        self.assertNotIn(self.mac(), text)

    def test_idle_two_hours(self):
        self.exchange()
        with self.client.session_transaction() as session:
            session["rapport_seen"] = (arsrapport.now() - timedelta(minutes=121)).isoformat()
        response = self.client.get("/api/v2/rapport/mina")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["code"], "session_ute")
        self.assertNotIn("rapport", self.session())
        self.assertEqual(self.client.get("/api/v2/rapport/mina").get_json(), [])

    def test_mina_lists_valid_codes_and_keeps_the_session_alive(self):
        self.exchange()
        with self.client.session_transaction() as session:
            session["rapport_seen"] = (arsrapport.now() - timedelta(minutes=119)).isoformat()
        rows = self.client.get("/api/v2/rapport/mina").get_json()
        self.assertEqual(
            rows, [{"code_id": self.code.id, "herd": "G9001", "herd_name": "Besättning G9001", "year": 2025}]
        )
        seen = datetime.fromisoformat(self.session()["rapport_seen"])
        self.assertLess(arsrapport.now() - seen, timedelta(minutes=1))
        report_code.revoke(self.code, now=arsrapport.now())
        self.assertEqual(self.client.get("/api/v2/rapport/mina").get_json(), [])

    def test_idle_codes_are_not_revived_by_a_new_link(self):
        """M1: an idle session loses its codes before the next link joins; the other herd stays closed."""
        self.exchange()
        with self.client.session_transaction() as session:
            session["rapport_seen"] = (arsrapport.now() - timedelta(hours=3)).isoformat()
        _, other, token = self.new_code("G9002")
        self.exchange(token)
        self.assertEqual([entry[0] for entry in self.session()["rapport"]], [other.id])
        rows = self.client.get("/api/v2/rapport/mina").get_json()
        self.assertEqual([row["herd"] for row in rows], ["G9002"])

    def test_at_most_four_codes(self):
        codes = [self.code.id]
        self.exchange()
        for name in ("G9002", "G9003", "G9004", "G9005"):
            _, code, token = self.new_code(name)
            codes.append(code.id)
            self.exchange(token)
        self.assertEqual([entry[0] for entry in self.session()["rapport"]], codes[1:])

    def test_rate_limited(self):
        limiter.enabled = True
        self.addCleanup(setattr, limiter, "enabled", False)
        limiter.reset()
        self.addCleanup(limiter.reset)
        statuses = [self.exchange().status_code for _ in range(21)]
        self.assertEqual(statuses[:20], [200] * 20)
        self.assertEqual(statuses[20], 429)

    def test_user_session_survives_exchange(self):
        self.login("owner")
        before = self.session()["user_id"]
        self.exchange()
        self.assertEqual(self.session()["user_id"], before)
        self.assertEqual(self.client.get("/api/user").status_code, 200)

    def test_exchange_rotates_session_id(self):
        with self.client.session_transaction() as session:
            session["planted"] = 1
        old = self.client.get_cookie("session").value
        self.exchange()
        self.assertNotEqual(self.client.get_cookie("session").value, old)
        other = APP.test_client(use_cookies=True)
        other.set_cookie("session", old)
        self.assertEqual(other.get("/api/v2/rapport/mina").get_json(), [])
        self.assertNotIn("rapport", self.session(other))

    def test_failed_rotation_grants_nothing_under_the_old_id(self):
        with self.client.session_transaction() as session:
            session["planted"] = 1
        old = self.client.get_cookie("session").value
        with mock.patch.object(APP.session_interface, "regenerate", side_effect=RuntimeError("redis down")):
            response = self.exchange()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(self.token.split(".")[1], response.get_data(as_text=True))
        other = APP.test_client(use_cookies=True)
        other.set_cookie("session", old)
        self.assertEqual(other.get("/api/v2/rapport/mina").get_json(), [])
        self.assertNotIn("rapport", self.session(other))
        self.assertNotIn("rapport", self.session())

    def test_only_application_json_is_accepted(self):
        for content_type in ("application/problem+json", "application/vnd.api+json"):
            response = self.client.post(EXCHANGE, data=json.dumps({"token": self.token}), content_type=content_type)
            self.assertEqual(response.status_code, 415, content_type)
        self.assertNotIn("rapport", self.session())
        self.assertEqual(self.exchange().status_code, 200)

    def test_demo_refuses_exchange_and_ignores_codes(self):
        with mock.patch.object(settings.service, "demo_instance", True):
            self.refused(self.exchange())
            self.assertNotIn("rapport", self.session())
        self.exchange()
        with mock.patch.object(settings.service, "demo_instance", True):
            self.assertEqual(self.client.get("/api/v2/rapport/mina").get_json(), [])
        with self.client.session_transaction() as session:  # an entry made in the demo, read in production
            session["rapport"] = [[self.code.id, "demo"]]
        self.assertEqual(self.client.get("/api/v2/rapport/mina").get_json(), [])

    def test_contacts_are_public(self):
        self.assertEqual(self.client.get("/api/v2/rapport/kontakt").get_json(), [])
        row = {"ras": "Gotlandskanin", "namn": "Test Kontakt", "telefon": "0700-000000"}
        with mock.patch.object(settings.arsrapport, "kontakt", [row]):
            self.assertEqual(self.client.get("/api/v2/rapport/kontakt").get_json(), [row])
        self.assertEqual(settings._contacts("not json"), [])  # pylint: disable=protected-access
        self.assertEqual(settings._contacts('[{"ras": "x"}]'), [])  # pylint: disable=protected-access
        self.assertEqual(settings._contacts(json.dumps([row])), [row])  # pylint: disable=protected-access
