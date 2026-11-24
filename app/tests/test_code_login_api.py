"""Browser-bound sign-in, using synthetic registry entries and the real outbox."""

import os
import threading
from datetime import date, timedelta
from unittest import mock

import utils.data_access as da
import utils.database as db
import utils.login_code as lc
import utils.settings as settings
from blueprints import code_login
from herdbook import APP, limiter

from tests.test_member_api import MatrikelApiTest, _mk_membership, _mk_person

BASE = "/api/v2/login"
ADDRESS = "member@example.org"


class CodeLoginTest(MatrikelApiTest):
    def setUp(self):
        super().setUp()
        for change in (
            mock.patch.dict(os.environ, KODINLOGGNING="true"),
            mock.patch.multiple(settings.mail, mode="log", link_secret="test-only"),
            mock.patch.object(settings.service, "allow_role_password_login", False),
        ):
            change.start()
            self.addCleanup(change.stop)
        self.user = da.register_user(ADDRESS, "pass")
        self.person = _mk_person(_mk_membership(), "Test", "Member", ADDRESS, user=self.user)

    def ask(self, email=ADDRESS, client=None):
        response = (client or self.client).post(BASE + "/kod", json={"email": email})
        data = response.get_data()
        cookie = response.headers.getlist("Set-Cookie")
        response.close()  # WSGI sends headers and body before doing the registry lookup.
        return response.status_code, data, cookie

    def redeem(self, endpoint, client=None, **fields):
        return (client or self.client).post(BASE + endpoint, json=fields)

    def test_browser_receives_the_whole_response_before_any_lookup(self):
        with mock.patch.object(lc, "login_holder", wraps=lc.login_holder) as lookup:
            response = self.client.post(BASE + "/kod", json={"email": ADDRESS})
            self.assertEqual(response.get_json(), {"message": "Finns adressen i matrikeln har vi skickat en kod dit."})
            self.assertIn("login_request=", response.headers["Set-Cookie"])
            lookup.assert_not_called()
            response.close()
            self.assertTrue(lookup.called)

    def test_request_does_not_disclose_eligibility_or_limits(self):
        replies = [self.ask("unknown@example.org"), *[self.ask() for _ in range(6)]]
        self.assertEqual(db.MailMessage.select().where(db.MailMessage.kind == "konto.kod").count(), 5)
        self.user.add_role("matrikel_admin", None)
        replies.append(self.ask())
        with mock.patch.object(lc, "closed", return_value=True):
            replies.append(self.ask())
        status, body, cookies = replies[0]
        self.assertEqual(status, 200)
        self.assertEqual(len(cookies), 1)
        self.assertTrue(all((s, b) == (status, body) and len(c) == 1 for s, b, c in replies))
        # A fresh secret for every request, with the same shape and attributes.
        self.assertEqual(len({c[0].split(";")[0] for _, _, c in replies}), len(replies))
        for _, _, c in replies:
            self.assertRegex(c[0], r"^login_request=[A-Za-z0-9_-]{43};")
            self.assertIn("HttpOnly", c[0])
            self.assertIn("SameSite=Lax", c[0])

    def test_role_and_unsafe_or_disabled_configuration_send_nothing(self):
        self.user.add_role("manager", 1)
        with mock.patch.object(settings.service, "allow_role_password_login", True):
            self.ask()
        for patch in (
            mock.patch.dict(os.environ, KODINLOGGNING="false"),
            mock.patch.object(settings.mail, "link_secret", ""),
            mock.patch.dict(os.environ, FLASK_ENV="production"),
        ):
            with patch:
                self.assertNotEqual(self.ask()[0], 200)
        self.assertFalse(db.LoginCode.select().exists())

    def test_only_unique_live_address_holders_get_a_code(self):
        _mk_person(self.person.membership, "Family", "Test", ADDRESS, role="familjemedlem")
        self.ask()
        self.assertEqual(db.LoginCode.get().member_id, self.person.id)
        db.Member.update(role="familjemedlem").where(db.Member.id == self.person.id).execute()
        self.ask()
        self.assertEqual(db.LoginCode.select().count(), 2)
        _mk_person(_mk_membership(), "Duplicate", "Test", ADDRESS)
        self.ask()
        self.assertEqual(db.LoginCode.select().count(), 2)
        db.Member.update(end_date=date.today()).execute()
        self.ask()
        self.assertEqual(db.LoginCode.select().count(), 2)

    def test_previous_address_and_seven_day_wait(self):
        from utils.matrikel import set_member_email

        set_member_email(self.person, "new@example.org", self.matrikel_user, by="other")
        self.ask("new@example.org")
        self.assertFalse(db.LoginCode.select().exists())
        self.ask()
        self.assertEqual(self.redeem("/kod/verifiera", code=lc.code(db.LoginCode.get())).status_code, 200)

    def test_code_session_has_the_normal_generation_and_role_rules(self):
        self.ask()
        code = lc.code(db.LoginCode.get())
        self.assertEqual(self.redeem("/kod/verifiera", code=code).status_code, 200)
        with self.client.session_transaction() as session:
            self.assertEqual(session["auth_method"], "kod")
            self.assertTrue(da.session_holds(session))
        self.assertEqual(self.redeem("/kod/verifiera", code=code).status_code, 400)
        self.user.add_role("matrikel_admin", None)
        self.assertEqual(self.client.get("/api/v2/members/me").status_code, 401)

    def test_auth_log_records_only_the_login_result_and_account_id(self):
        self.ask()
        row = db.LoginCode.get()
        with self.assertLogs("herdbook.auth", level="INFO") as logged:
            self.assertEqual(self.redeem("/lank", token=lc.login_link_token(row)).status_code, 200)
            self.assertEqual(self.redeem("/kod/verifiera", code=lc.code(row)).status_code, 400)
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            [f"Login ok: kod, user id={self.user.id}", "Login refused: kod"],
        )

    def test_mass_logout_after_consumption_invalidates_direct_sign_in(self):
        self.ask()
        row = db.LoginCode.get()
        establish = APP.extensions["establish_session"]

        def logout_then_establish(*args, **kwargs):
            self.assertIsNotNone(db.LoginCode.get_by_id(row.id).used_at)
            da.mass_logout_sessions(da.session_redis, "test")
            self.addCleanup(da.session_redis.decr, da.LOGOUT_EPOCH_KEY)
            return establish(*args, **kwargs)

        with mock.patch.dict(APP.extensions, establish_session=logout_then_establish):
            self.assertEqual(self.redeem("/kod/verifiera", code=lc.code(row)).status_code, 200)
        self.assertEqual(self.client.get("/api/user").status_code, 401)

    def test_queue_and_limiter_errors_are_logged_and_alarm_for_one_hour(self):
        start = lc._utcnow()
        alarm = "kodinloggning_kofel"

        def active(at):
            return alarm in [row["code"] for row in lc.alarms(at)]

        with mock.patch.object(lc, "_utcnow", return_value=start), self.assertLogs(code_login.logger, "ERROR") as log:
            with mock.patch.object(code_login, "enqueue_mail", side_effect=ValueError(ADDRESS)):
                self.ask()
                self.ask()
            self.assertFalse(active(start))
            with (
                mock.patch.object(limiter, "enabled", True),
                mock.patch.object(limiter.limiter, "hit", side_effect=RuntimeError(ADDRESS)),
            ):
                self.ask()
        self.assertEqual(
            [record.getMessage() for record in log.records],
            ["Code login queue error: ValueError"] * 2 + ["Code login queue error: RuntimeError"],
        )
        self.assertNotIn(ADDRESS, "".join(log.output))
        self.assertFalse(db.LoginCode.select().exists())
        self.assertTrue(active(start + timedelta(minutes=59)))
        self.assertFalse(active(start + timedelta(hours=1)))

    def test_ten_requests_per_source_including_misses(self):
        with mock.patch.object(limiter, "enabled", True):
            limiter.reset()
            self.addCleanup(limiter.reset)
            for _ in range(9):
                self.ask("unknown@example.org")
            self.assertEqual(self.ask()[0], 200)
            self.assertEqual(db.LoginCode.select().count(), 1)
            self.assertEqual(self.ask()[0], 200)
            self.assertEqual(db.LoginCode.select().count(), 1)

    def test_link_preview_and_wrong_browser_leave_the_row_and_session_alone(self):
        self.ask()
        row = db.LoginCode.get()
        token = lc.login_link_token(row)
        preview = self.redeem("/lank/uppslag", token=token)
        self.assertEqual(preview.get_json(), {"name": "Test Member", "switch_from": None})
        self.assertFalse(preview.headers.getlist("Set-Cookie"))
        other = APP.test_client()
        for with_cookie in (False, True):
            if with_cookie:
                self.ask(client=other)
            for endpoint in ("/lank/uppslag", "/lank"):
                response = self.redeem(endpoint, other, token=token)
                self.assertNotIn("name", response.get_json())
                self.assertEqual(response.status_code, 400)
        self.assertEqual((db.LoginCode.get_by_id(row.id).failed, db.LoginCode.get_by_id(row.id).used_at), (0, None))
        self.assertEqual(self.redeem("/kod/verifiera", code=lc.code(row)).status_code, 200)
        self.assertEqual(self.redeem("/lank/uppslag", token=token).status_code, 400)

    def test_wrong_credentials_take_the_same_checks_without_person_locks(self):
        self.ask()
        row = db.LoginCode.get()
        missing = APP.test_client()
        self.ask("missing@example.org", client=missing)
        wrong = f"{(int(lc.code(row)) + 1) % 10**8:08}"
        for path, body, mac in (
            ("/kod/verifiera", {"code": wrong}, "code"),
            ("/lank/uppslag", {"token": "wrong"}, "login_link_token"),
            ("/lank", {"token": "wrong"}, "login_link_token"),
        ):
            replies = []
            for client in (self.client, missing):
                with (
                    mock.patch.object(lc, "_lock", wraps=lc._lock) as lock,
                    mock.patch.object(lc, mac, wraps=getattr(lc, mac)) as compare,
                    mock.patch.object(code_login, "_lock_for_detach") as person_lock,
                ):
                    response = self.redeem(path, client, **body)
                    replies.append((response.status_code, response.data))
                    lock.assert_called_once()
                    compare.assert_called_once()
                    person_lock.assert_not_called()
            self.assertEqual(replies[0], replies[1])
            self.assertEqual(replies[0][0], 400)
        self.assertEqual(db.LoginCode.get_by_id(row.id).failed, 1)

    def test_unusable_links_disclose_no_name_and_cannot_sign_in(self):
        self.ask()
        row = db.LoginCode.get()
        token = lc.login_link_token(row)
        unknown = self.redeem("/lank/uppslag", token="invalid").get_json()
        for fields in (
            {"failed": lc.TRIES},
            {"created_at": row.created_at - lc.VALID_FOR},
            {"purpose": "ny_adress"},
            {"used_at": row.created_at},
            {"failed": lc.WRONG_AN_HOUR},
        ):
            original = {name: getattr(row, name) for name in fields}
            db.LoginCode.update(**fields).execute()
            self.assertEqual(self.redeem("/lank/uppslag", token=token).get_json(), unknown)
            self.assertEqual(self.redeem("/lank", token=token).status_code, 400)
            db.LoginCode.update(**original).execute()

    def test_changed_address_account_or_role_refuses_code_and_link(self):
        self.ask()
        row = db.LoginCode.get()
        for patch in (
            {db.Member.email: "changed@example.org"},
            {db.Member.user: None},
            {db.Member.user: self.matrikel_user},
        ):
            db.Member.update(patch).where(db.Member.id == self.person.id).execute()
            for endpoint, fields in (
                ("/lank/uppslag", {"token": lc.login_link_token(row)}),
                ("/lank", {"token": lc.login_link_token(row)}),
                ("/kod/verifiera", {"code": lc.code(row)}),
            ):
                self.assertEqual(self.redeem(endpoint, **fields).status_code, 400)
            db.Member.update(email=ADDRESS, user=self.user).where(db.Member.id == self.person.id).execute()
        self.user.add_role("matrikel_admin", None)
        self.assertEqual(self.redeem("/lank", token=lc.login_link_token(row)).status_code, 400)

    def test_link_switch_checks_the_current_account_on_post(self):
        self.ask()
        row = db.LoginCode.get()
        token = lc.login_link_token(row)
        self.assertIsNone(self.redeem("/lank/uppslag", token=token).get_json()["switch_from"])
        self.login("spec")
        for confirmed in (None, self.user.id):
            response = self.redeem("/lank", token=token, confirm_user_id=confirmed)
            self.assertEqual((response.status_code, response.get_json()["switch_from"]), (409, self.viewer.id))
            self.assertEqual(self.client.get("/api/user").get_json()["id"], self.viewer.id)
            self.assertIsNone(db.LoginCode.get().used_at)
            self.assertEqual(db.LoginCode.get().failed, 0)
        self.assertEqual(self.redeem("/lank", token=token, confirm_user_id=self.viewer.id).status_code, 200)
        self.assertEqual(self.client.get("/api/user").get_json()["id"], self.user.id)

    def test_concurrent_link_and_code_sign_in_only_once(self):
        self.ask()
        row = db.LoginCode.get()
        browser = self.client.get_cookie("login_request").value
        start = threading.Barrier(2)
        results = []

        def enter(endpoint, **fields):
            try:
                client = APP.test_client()
                client.set_cookie("login_request", browser)
                start.wait(timeout=5)
                results.append(self.redeem(endpoint, client, **fields).status_code)
            finally:
                db.DB_PROXY.close()

        threads = [
            threading.Thread(target=enter, args=("/lank",), kwargs={"token": lc.login_link_token(row)}),
            threading.Thread(target=enter, args=("/kod/verifiera",), kwargs={"code": lc.code(row)}),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(sorted(results), [200, 400])
