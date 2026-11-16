#!/usr/bin/env python3
"""
Tests for the report link's exchange (step 3, Task 2): the route, the code session, the headers, the logs and the
nginx routing. Synthetic herds, addresses and tokens only.

isort:skip_file
"""

import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
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
EXCHANGE = "/api/v2/rapport/oppna/"
INVALID = "/rapport/ogiltig"
NGINX = Path(__file__).resolve().parents[2] / "nginx"


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
        return (client or self.client).get(EXCHANGE + (token or self.token))

    def session(self, client=None):
        with (client or self.client).session_transaction() as session:
            return dict(session)

    def mac(self, token=None):
        return (token or self.token).split(".")[1]

    def test_valid_token_sets_session_and_redirects(self):
        response = self.exchange()
        self.assertEqual((response.status_code, response.headers["Location"]), (303, f"/rapport?kod={self.code.id}"))
        self.assertIsNotNone(db.ReportAccessCode.get_by_id(self.code.id).last_opened_at)
        session = self.session()
        self.assertEqual(session["rapport"], [[self.code.id, "prod"]])
        self.assertIn("rapport_seen", session)

    def test_failures_redirect_to_ogiltig(self):
        _, revoked, revoked_token = self.new_code("G9002")
        report_code.revoke(revoked, now=arsrapport.now())
        _, _, expired_token = self.new_code("G9003")
        forged = f"{self.code.id}.{'A' * 22}"
        unknown = f"{self.code.id + 999}.{self.mac()}"
        no_row = mail.link_token("rapport", self.code.id + 999)  # L8: a valid mac for an id with no row
        for token in (forged, unknown, no_row, revoked_token):
            with self.subTest(token=token.split(".")[0]):
                response = self.exchange(token)
                self.assertEqual((response.status_code, response.headers["Location"]), (303, INVALID))
        self.at(date(2026, 4, 1))  # after the round's end
        self.assertEqual(self.exchange(expired_token).headers["Location"], INVALID)
        self.assertNotIn("rapport", self.session())

    def test_headers_no_store_no_referrer(self):
        for token in (self.token, f"{self.code.id}.{'A' * 22}"):
            headers = self.exchange(token).headers
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(headers["Referrer-Policy"], "no-referrer")

    def test_token_never_logged(self):
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

    def test_prefix_mask_on_429_and_500(self):
        APP.config["PROPAGATE_EXCEPTIONS"] = False
        self.addCleanup(APP.config.update, PROPAGATE_EXCEPTIONS=None)
        with mock.patch.object(arsrapport, "now", side_effect=RuntimeError("boom")):
            self.assertEqual(self.exchange().status_code, 500)
        limiter.enabled = True
        self.addCleanup(setattr, limiter, "enabled", False)
        limiter.reset()
        self.addCleanup(limiter.reset)
        for _ in range(21):
            last = self.exchange(f"{self.code.id}.{'A' * 22}")
        self.assertEqual(last.status_code, 429)
        text = "\n".join(self.lines)
        self.assertIn("/api/v2/rapport/oppna/***", text)
        self.assertNotIn(self.mac(), text)
        self.assertNotIn("A" * 22, text)

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
        self.assertEqual(statuses[:20], [303] * 20)
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

    def test_demo_refuses_exchange_and_ignores_codes(self):
        with mock.patch.object(settings.service, "demo_instance", True):
            self.assertEqual(self.exchange().headers["Location"], INVALID)
            self.assertNotIn("rapport", self.session())
        self.exchange()
        with mock.patch.object(settings.service, "demo_instance", True):
            self.assertEqual(self.client.get("/api/v2/rapport/mina").get_json(), [])
        with self.client.session_transaction() as session:  # an entry made in the demo, read in production
            session["rapport"] = [[self.code.id, "demo"]]
        self.assertEqual(self.client.get("/api/v2/rapport/mina").get_json(), [])

    def test_truncated_token_goes_to_ogiltig(self):
        for tail in (
            self.token[:-3],
            self.token + "x",
            self.token.split(".")[0],
            "abc",
            self.token.replace(".", "%252E"),
        ):
            with self.subTest(tail=tail.split(".")[0]):
                response = self.client.get(EXCHANGE + tail)
                self.assertEqual((response.status_code, response.headers["Location"]), (303, INVALID))
        self.assertNotIn("rapport", self.session())

    def test_contacts_are_public(self):
        self.assertEqual(self.client.get("/api/v2/rapport/kontakt").get_json(), [])
        row = {"ras": "Gotlandskanin", "namn": "Test Kontakt", "telefon": "0700-000000"}
        with mock.patch.object(settings.arsrapport, "kontakt", [row]):
            self.assertEqual(self.client.get("/api/v2/rapport/kontakt").get_json(), [row])
        self.assertEqual(settings._contacts("not json"), [])  # pylint: disable=protected-access
        self.assertEqual(settings._contacts('[{"ras": "x"}]'), [])  # pylint: disable=protected-access
        self.assertEqual(settings._contacts(json.dumps([row])), [row])  # pylint: disable=protected-access

    def test_nginx_routes_token_to_api(self):
        """Every path under /rapport/ but /rapport/ogiltig goes to the exchange, and its logs are masked (R6, FA6).

        The conf is checked as text here, and by running nginx in scripts/tests/test-nginx-rapport.sh.
        """
        if not NGINX.is_dir():
            self.skipTest("nginx/ is not mounted in this container")
        for name, upstream in (
            ("herdbook.conf", "http://api:9090"),
            ("herdbook-local-production.conf", "http://api_prod"),
            ("production/herdbook-production.conf", "http://api_prod"),
        ):
            text = (NGINX / name).read_text()
            with self.subTest(file=name):
                exact = re.search(r"location = /rapport/ogiltig \{(.*?)\n    \}", text, re.S).group(1)
                self.assertIn("rapport_masked", exact)
                self.assertIn("return 303 /rapport/ogiltig;", exact)  # /rapport/<token>/..%2Fogiltig, without the token
                block = re.search(r"location ~\* \^/rapport/ \{(.*?)\n    \}", text, re.S).group(1)
                self.assertIn('rewrite "(?i)^/rapport/(.*)$" /api/v2/rapport/oppna/$1 break;', block)
                self.assertIn(f"proxy_pass {upstream};", block)
                self.assertIn("access_log /var/log/nginx/access.log rapport_masked;", block)
                self.assertIn("error_log /dev/null crit;", block)
                self.assertNotRegex(block, r"\$request_uri|\$request\b")
                direct = re.search(
                    r"location ~\* \^/api\(-test\)\?/v2/rapport/oppna/ \{(.*?)\n    \}", text, re.S
                ).group(1)
                self.assertIn("rapport_masked", direct)
                self.assertIn("return 404;", direct)
                self.assertIn("~*^/api(-test)?/v2/rapport/oppna/ 1;", text)
                self.assertRegex(text, r"log_format rapport_masked .*\$log_uri")
                # every server block that proxies /api/ to the api has the link rules or the refusal before it
                servers = re.split(r"\n(?=server \{)", text)
                for server in [x for x in servers if re.search(r"^    location /api/ \{", x, re.M)]:
                    self.assertIn("rapport_masked", server)
