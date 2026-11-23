"""
The member's own change of address (PATCH /api/v2/members/me/contact, then POST .../contact/verifiera): the address is
written only after a code to the new one, in the same browser; the answer is the same when another person holds the
address; the change ends the account's sessions. Synthetic data only.

isort:skip_file
"""

import json
import os
import threading
from unittest import mock

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.login_code as lc  # noqa: E402
import utils.settings as settings  # noqa: E402
from blueprints import members as members_routes  # noqa: E402
from herdbook import APP  # noqa: E402

from tests.test_member_api import MatrikelApiTest, _mk_membership, _mk_person  # noqa: E402

NEW = "ny@example.org"


class MyEmailTest(MatrikelApiTest):
    def setUp(self):
        super().setUp()
        patch = mock.patch.multiple(settings.mail, mode="live", link_secret="test-link-secret", allowlist=[])
        patch.start()
        self.addCleanup(patch.stop)
        self.user = da.register_user("a@example.org", "pass", username="medlemmen")
        self.person = _mk_person(_mk_membership(number=8), "Maja", "Medlem", "a@example.org", user=self.user)
        self.login("medlemmen")

    def patch_contact(self, body, client=None):
        return (client or self.client).patch(
            "/api/v2/members/me/contact", data=json.dumps(body), content_type="application/json"
        )

    def verify(self, code, client=None):
        return (client or self.client).post(
            "/api/v2/members/me/contact/verifiera", data=json.dumps({"code": code}), content_type="application/json"
        )

    def code(self):
        return lc.code(db.LoginCode.select().order_by(db.LoginCode.id.desc()).get())

    def code_mails(self):
        return list(db.MailMessage.select().where(db.MailMessage.kind == "konto.kod"))

    def email(self):
        return db.Member.get_by_id(self.person.id).email


class TestRequest(MyEmailTest):
    def test_the_same_address_in_another_case_sends_no_code(self):
        resp = self.patch_contact({"email": "A@Example.org ", "phone": "0701"})
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(resp.get_json()["email_code_sent"])
        self.assertEqual((self.email(), db.Member.get_by_id(self.person.id).phone), ("a@example.org", "0701"))
        self.assertFalse(db.LoginCode.select().exists())

    def test_a_new_address_gets_a_code_and_is_not_written(self):
        resp = self.patch_contact({"email": NEW, "phone": "0701"})
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.get_json()["email_code_sent"])
        self.assertEqual(resp.get_json()["email"], "a@example.org")
        self.assertEqual(self.email(), "a@example.org")
        self.assertEqual(db.Member.get_by_id(self.person.id).phone, "0701")
        (row,) = db.LoginCode.select()
        self.assertEqual((row.purpose, row.new_address, row.user_id), ("ny_adress", NEW, self.user.id))
        (queued,) = self.code_mails()
        self.assertEqual((queued.recipient_kind, queued.recipient_id, queued.priority), ("login_code", row.id, 0))

    def test_an_address_another_person_holds_gets_the_same_answer_and_no_mail(self):
        _mk_person(_mk_membership(number=9), "Bo", "Other", NEW)
        resp = self.patch_contact({"email": NEW})
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.get_json()["email_code_sent"])
        self.assertEqual(self.code_mails(), [])
        # It spends one of her five a day like a code that went: the limit tells her nothing either.
        for n in range(4):
            self.patch_contact({"email": f"egen{n}@example.org"})
        self.assertEqual(len(self.code_mails()), 4)
        self.patch_contact({"email": "egen5@example.org"})
        self.assertEqual(len(self.code_mails()), 4)
        self.assertEqual(self.verify(self.code()).status_code, 400)  # the sixth made no code either

    def test_an_address_the_sender_cannot_mail_is_refused_like_a_malformed_one(self):
        resp = self.patch_contact({"email": "o'berg@example.org"})
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.get_json()["title"], "Ogiltig e-postadress")
        self.assertFalse(db.LoginCode.select().exists())  # none of the day's five spent

    def test_no_code_without_link_secret_or_in_production_in_log_mode(self):
        with mock.patch.object(settings.mail, "link_secret", ""):
            self.assertEqual(self.patch_contact({"email": NEW}).status_code, 503)
            self.assertEqual(self.patch_contact({"email": "a@example.org", "phone": "0701"}).status_code, 200)
        with mock.patch.object(settings.mail, "mode", "log"), mock.patch.dict(os.environ, {"FLASK_ENV": "production"}):
            self.assertEqual(self.patch_contact({"email": NEW}).status_code, 503)
        self.assertFalse(db.LoginCode.select().exists())

    def test_the_demo_refuses_the_change_and_saves_the_rest(self):
        """The demo never replaces an account's mark, so the change could not end the sessions as it says."""
        with mock.patch.object(settings.service, "demo_instance", True):
            resp = self.patch_contact({"email": NEW, "phone": "0701"})
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.get_json()
        self.assertEqual(data["email_refused"], "E-postadressen kan inte bytas i testmiljön.")
        self.assertFalse(data["email_code_sent"])
        self.assertEqual((self.email(), db.Member.get_by_id(self.person.id).phone), ("a@example.org", "0701"))
        self.assertFalse(db.LoginCode.select().exists())


class TestVerify(MyEmailTest):
    def test_the_right_code_changes_the_address_and_ends_the_session(self):
        self.patch_contact({"email": NEW})
        resp = self.verify(lc.shown(self.code()))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual((resp.get_json()["email"], self.email()), (NEW, NEW))
        (previous,) = db.MemberPreviousAddress.select()
        self.assertEqual(previous.address, "a@example.org")
        self.assertIsNotNone(previous.login_until)
        (besked,) = db.MailMessage.select().where(db.MailMessage.kind == "kontakt.epost_besked")
        self.assertTrue(besked.params["by_self"])
        self.assertEqual(self.client.get("/api/v2/members/me").status_code, 401)

    def test_a_wrong_code_is_refused_and_counted(self):
        self.patch_contact({"email": NEW})
        wrong = f"{(int(self.code()) + 1) % 10**8:08d}"
        resp = self.verify(wrong)
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.get_json()["title"], "Koden stämmer inte")
        self.assertEqual(self.email(), "a@example.org")
        self.assertEqual(db.LoginCode.get().failed, 1)
        self.assertEqual(self.verify(123).status_code, 400)  # not a string
        self.assertEqual(db.LoginCode.get().failed, 1)

    def test_the_code_works_only_in_the_browser_that_asked(self):
        self.patch_contact({"email": NEW})
        other = APP.test_client(use_cookies=True)
        other.post("/api/login", json={"username": "medlemmen", "password": "pass"})
        resp = self.verify(self.code(), client=other)
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual((self.email(), db.LoginCode.get().failed), ("a@example.org", 0))

    def test_only_the_latest_code_of_the_browser_works(self):
        self.patch_contact({"email": NEW})
        first = self.code()
        self.patch_contact({"email": "annan@example.org"})
        self.assertEqual(self.verify(first).status_code, 400)
        self.assertEqual(self.verify(self.code()).status_code, 200)
        self.assertEqual(self.email(), "annan@example.org")

    def test_an_address_taken_since_answers_like_a_wrong_code_and_uses_the_code(self):
        self.patch_contact({"email": NEW})
        code = self.code()
        _mk_person(_mk_membership(number=9), "Bo", "Other", NEW)
        resp = self.verify(code)
        self.assertEqual((resp.status_code, resp.get_json()["title"]), (400, "Koden stämmer inte"))
        self.assertEqual(self.email(), "a@example.org")
        self.assertIsNotNone(db.LoginCode.get().used_at)
        self.assertFalse(db.MemberPreviousAddress.select().exists())

    def paused_verify(self, code, meanwhile, change_row=None):
        """Runs the verification with a pause after its code check, does `meanwhile`, and returns the response."""
        checked, release, responses = threading.Event(), threading.Event(), []
        original = members_routes.check

        def paused_check(*args, **kwargs):
            row = original(*args, **kwargs)
            if change_row and row is not None:
                change_row(row)
            checked.set()
            assert release.wait(timeout=10), "the test never released the paused request"
            return row

        def run():
            try:
                responses.append(self.verify(code))
            finally:
                db.DATABASE.close()

        with mock.patch.object(members_routes, "check", paused_check):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(checked.wait(timeout=10), "the request never reached the code check")
            meanwhile()
            release.set()
            thread.join(timeout=20)
        self.assertFalse(thread.is_alive())
        return responses[0]

    def test_a_new_request_voids_the_earlier_code(self):
        self.patch_contact({"email": NEW})
        first = db.LoginCode.get()
        self.patch_contact({"email": "annan@example.org"})
        self.assertIsNotNone(db.LoginCode.get_by_id(first.id).used_at)

    def test_a_check_already_past_cannot_use_a_code_a_new_request_replaced(self):
        self.patch_contact({"email": NEW})
        resp = self.paused_verify(self.code(), lambda: self.patch_contact({"email": "annan@example.org"}))
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(self.email(), "a@example.org")

    def test_nothing_is_written_without_a_new_address_on_the_row(self):
        self.patch_contact({"email": NEW})
        resp = self.paused_verify(self.code(), lambda: None, change_row=lambda row: setattr(row, "new_address", None))
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(self.email(), "a@example.org")

    def same_session(self):
        """A second client on this session, as another tab of the same browser."""
        tab = APP.test_client(use_cookies=True)
        name = APP.config["SESSION_COOKIE_NAME"]  # other test classes rename it and leave it so
        tab.set_cookie(name, self.client.get_cookie(name).value)
        return tab

    def test_a_logout_meanwhile_stops_the_change(self):
        """The verification has read its session and waits; the member logs out in another tab, which only deletes
        this session: its pending code goes with it, so the change is not made."""
        self.patch_contact({"email": NEW})
        tab = self.same_session()
        resp = self.paused_verify(self.code(), lambda: self.assertEqual(tab.get("/api/logout").status_code, 200))
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(self.email(), "a@example.org")

    def cancel(self, client=None):
        return (client or self.client).delete("/api/v2/members/me/contact/kod")

    def test_cancelling_voids_the_code(self):
        self.patch_contact({"email": NEW})
        code = self.code()
        self.assertEqual(self.cancel().status_code, 204)
        self.assertEqual(self.verify(code).status_code, 400)
        self.assertEqual(self.email(), "a@example.org")

    def test_cancelling_leaves_a_newer_request_in_another_session(self):
        self.patch_contact({"email": NEW})
        other = APP.test_client(use_cookies=True)
        other.post("/api/login", json={"username": "medlemmen", "password": "pass"})
        self.patch_contact({"email": "annan@example.org"}, client=other)
        newer = self.code()
        self.assertEqual(self.cancel().status_code, 204)
        self.assertEqual(self.verify(newer, client=other).status_code, 200)
        self.assertEqual(self.email(), "annan@example.org")

    def test_a_session_revoked_meanwhile_cannot_finish_the_change(self):
        """Logga ut överallt while the request is past the code check: under the account's lock the session no
        longer holds, so nothing is written and the code is not used."""
        self.patch_contact({"email": NEW})
        resp = self.paused_verify(self.code(), lambda: da.revoke_sessions(self.user.id))
        self.assertEqual(resp.status_code, 401, resp.data)
        self.assertEqual(self.email(), "a@example.org")
        self.assertIsNone(db.LoginCode.get().used_at)
