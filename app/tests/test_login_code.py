"""
One-time codes (utils.login_code) against Postgres: eight digits, ten minutes, once, three tries counted before the
comparison, bound to the browser, the limits per person, per hour and for wrong codes, the refusals, and the purge.
Synthetic data only.

isort:skip_file
"""

import logging
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import herdbook  # noqa: E402
import utils.cache_invalidation as ci  # noqa: E402
import utils.database as db  # noqa: E402
import utils.login_code as lc  # noqa: E402
import utils.mail as mail  # noqa: E402
import utils.settings as settings  # noqa: E402

from tests.database_test import _USE_POSTGRES, DatabaseTest  # noqa: E402
from tests.test_mail_queue import FakeRelay  # noqa: E402

SECRET = "test-link-secret"


def wrong(digits):
    return f"{(int(digits) + 1) % 10**8:08d}"


@unittest.skipUnless(_USE_POSTGRES, "advisory locks and UPDATE ... RETURNING")
class LoginCodeTest(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc)
        for patch in (
            mock.patch.multiple(settings.mail, mode="live", link_secret=SECRET, allowlist=[]),
            mock.patch.object(settings.service, "host", "https://stambok.example.org"),
            mock.patch.object(lc, "_utcnow", side_effect=lambda: self.now),
            mock.patch.object(mail, "_utcnow", side_effect=lambda: self.now),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.person = self.person_row("Anna", "anna@example.org")

    def person_row(self, first, email, **fields):
        membership = db.Membership.create(membership_status="active")
        return db.Member.create(
            membership=membership, first_name=first, last_name="Test", email=email, role="huvudmedlem", **fields
        )

    def issue(self, person=None, browser="webblasare-1", purpose="ny_adress", address="ny@example.org"):
        with db.DB_PROXY.atomic():
            return lc.issue(person or self.person, purpose, browser, address)

    def row(self, row):
        return db.LoginCode.get_by_id(row.id)


class TestCode(LoginCodeTest):
    def test_the_code_is_eight_digits_as_text_and_never_stored(self):
        row = self.issue()
        digits = lc.code(row)
        self.assertRegex(digits, r"^[0-9]{8}$")
        self.assertEqual(lc.shown("04827195"), "0482 7195")
        stored = db.LoginCode.select().where(db.LoginCode.id == row.id).dicts().get()
        self.assertNotIn(digits, " ".join(str(value) for value in stored.values()))

    def test_leading_zeros_are_part_of_the_code(self):
        for n in range(200):
            digits = mail.one_time_code(1, f"nonce-{n}")
            if digits.startswith("0"):
                break
        else:
            self.fail("no code with a leading zero in 200 nonces")
        self.assertEqual(len(digits), 8)

    def test_the_code_depends_on_the_secret_and_the_host(self):
        digits = mail.one_time_code(1, "nonce")
        with mock.patch.object(settings.mail, "link_secret", "another-secret"):
            self.assertNotEqual(mail.one_time_code(1, "nonce"), digits)
        with mock.patch.object(settings.service, "host", "https://demo.example.org"):
            self.assertNotEqual(mail.one_time_code(1, "nonce"), digits)


class TestCheck(LoginCodeTest):
    def test_the_right_code_works_once(self):
        row = self.issue()
        found = lc.check("ny_adress", "webblasare-1", lc.code(row), self.person.id)
        self.assertEqual(found.id, row.id)
        with db.DB_PROXY.atomic():
            self.assertTrue(lc.consume(found))
            self.assertFalse(lc.consume(found))
        self.assertEqual((self.row(row).failed, self.row(row).new_address), (0, None))
        self.assertIsNone(lc.check("ny_adress", "webblasare-1", lc.code(row), self.person.id))

    def test_spaces_and_hyphens_are_ignored(self):
        digits = lc.code(self.issue())
        for entered in (lc.shown(digits), f"{digits[:4]}-{digits[4:]}", f" {digits} "):
            self.assertIsNotNone(lc.check("ny_adress", "webblasare-1", entered), entered)

    def test_a_code_older_than_ten_minutes_is_refused(self):
        row = self.issue()
        self.now += timedelta(minutes=10)
        self.assertIsNone(lc.check("ny_adress", "webblasare-1", lc.code(row)))

    def test_the_fourth_try_is_refused_also_when_right(self):
        row = self.issue()
        for _ in range(3):
            self.assertIsNone(lc.check("ny_adress", "webblasare-1", wrong(lc.code(row))))
        self.assertIsNone(lc.check("ny_adress", "webblasare-1", lc.code(row)))
        self.assertEqual(self.row(row).failed, 3)

    def test_garbage_counts_as_a_wrong_try(self):
        row = self.issue()
        for entered in ("１２３４５６７８", "abc", None, lc.code(row) + "9"):
            self.assertIsNone(lc.check("ny_adress", "webblasare-1", entered))
        self.assertEqual(self.row(row).failed, 3)

    def test_two_fourth_tries_at_once_give_at_most_one_row(self):
        row = self.issue()
        db.LoginCode.update(failed=2).where(db.LoginCode.id == row.id).execute()
        barrier, found = threading.Barrier(2), []

        def attempt():
            try:
                barrier.wait()
                found.append(lc.check("ny_adress", "webblasare-1", lc.code(row)))
            finally:
                db.DATABASE.close()

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(sorted(r is None for r in found), [False, True])
        self.assertEqual(self.row(row).failed, 3)

    def test_the_try_commits_on_its_own(self):
        row = self.issue()
        with self.assertRaises(RuntimeError), db.DB_PROXY.atomic():
            lc.check("ny_adress", "webblasare-1", wrong(lc.code(row)))
        self.assertEqual(self.row(row).failed, 0)  # refused inside a transaction, which could roll the try back
        lc.check("ny_adress", "webblasare-1", wrong(lc.code(row)))
        self.assertEqual(self.row(row).failed, 1)

    def test_a_code_from_another_browser_is_refused_and_leaves_the_row(self):
        row = self.issue()
        self.assertIsNone(lc.check("ny_adress", "webblasare-2", lc.code(row)))
        self.assertEqual(self.row(row).failed, 0)

    def test_another_request_and_its_wrong_tries_leave_the_first_login_code(self):
        first = self.issue(browser="webblasare-1", purpose="login")
        other = self.issue(browser="webblasare-2", purpose="login")
        for _ in range(3):
            lc.check("login", "webblasare-2", wrong(lc.code(other)))
        self.assertIsNotNone(lc.check("login", "webblasare-1", lc.code(first)))

    def test_only_the_persons_and_the_purposes_code(self):
        row = self.issue()
        other = self.person_row("Bo", "bo@example.org")
        self.assertIsNone(lc.check("ny_adress", "webblasare-1", lc.code(row), other.id))
        self.assertIsNone(lc.check("login", "webblasare-1", lc.code(row)))

    def test_a_new_address_code_voids_every_earlier_one_of_the_person(self):
        """Two requests that both carry the old secret (they read the session before either saved it): only the last
        code made stays, whatever browser asked."""
        old = self.issue(browser="gammal")
        first = self.issue(browser="ny-1", purpose="ny_adress")
        with db.DB_PROXY.atomic():
            last = lc.issue(self.person, "ny_adress", "ny-2", "ny@example.org", replaces="gammal")
        self.assertEqual(
            [self.row(r).used_at is None for r in (old, first, last)],
            [False, False, True],
        )

    def test_a_login_code_survives_anothers_request(self):
        first = self.issue(browser="w1", purpose="login")
        self.issue(browser="w2", purpose="login")
        self.assertIsNone(self.row(first).used_at)

    def test_a_voided_code_is_refused(self):
        row = self.issue()
        self.assertEqual(lc.void(self.person.id), 1)
        self.assertIsNone(lc.check("ny_adress", "webblasare-1", lc.code(row)))
        self.assertIsNone(self.row(row).new_address)


class TestLimits(LoginCodeTest):
    def test_five_codes_per_person_and_day(self):
        for n in range(5):
            self.assertIsNotNone(self.issue(browser=f"w{n}"))
        self.assertIsNone(self.issue(browser="w5"))
        self.assertIsNotNone(self.issue(person=self.person_row("Bo", "bo@example.org")))
        self.now += timedelta(days=1, seconds=1)
        self.assertIsNotNone(self.issue(browser="w6"))

    def test_120_codes_an_hour_in_all(self):
        people = [self.person_row(f"P{n}", f"p{n}@example.org") for n in range(25)]
        for n in range(120):
            self.assertIsNotNone(self.issue(person=people[n % 25], browser=f"w{n}"), n)
        self.assertIsNone(self.issue(person=self.person, browser="w120"))
        self.now += timedelta(hours=1, seconds=1)
        self.assertIsNotNone(self.issue(person=self.person, browser="w121"))

    def test_fifty_wrong_codes_close_code_login_and_light_the_alarm(self):
        people = [self.person_row(f"P{n}", f"p{n}@example.org") for n in range(17)]
        rows = [self.issue(person=p, browser=f"w{p.id}") for p in people]
        tries = 0
        for row in rows:
            for _ in range(3):
                if tries < 49:
                    lc.check("ny_adress", f"w{row.member_id}", wrong(lc.code(row)))
                    tries += 1
        self.assertNotIn("kodinloggning_stangd", [a["code"] for a in mail.sender_alarms(self.now)["alarms"]])
        for _ in range(20):  # tries for a browser without a row reach no person: they count for nothing
            lc.check("ny_adress", "okand", "12345678")
        self.assertFalse(lc.closed(self.now))
        last = rows[-1]
        lc.check("ny_adress", f"w{last.member_id}", wrong(lc.code(last)))
        self.assertTrue(lc.closed(self.now))
        self.assertIn("kodinloggning_stangd", [a["code"] for a in mail.sender_alarms(self.now)["alarms"]])
        with self.assertRaises(lc.CodeLoginClosed):
            lc.check("ny_adress", f"w{last.member_id}", lc.code(last))
        self.assertEqual(self.row(last).failed, 2)  # a closed check touches no row
        self.assertIsNone(self.issue(browser="new"))
        self.now += timedelta(hours=1, minutes=10, seconds=1)
        self.assertFalse(lc.closed(self.now))

    def test_a_wrong_code_late_in_its_ten_minutes_counts_for_a_whole_hour(self):
        people = [self.person_row(f"P{n}", f"p{n}@example.org") for n in range(17)]
        made = self.now
        rows = [self.issue(person=p, browser=f"w{p.id}") for p in people]
        self.now = made + timedelta(minutes=9, seconds=59)  # the tries come at the end of the codes' ten minutes
        for n in range(lc.WRONG_AN_HOUR):
            row = rows[n // 3]
            lc.check("ny_adress", f"w{row.member_id}", wrong(lc.code(row)))
        self.assertTrue(lc.closed(self.now))
        self.now = made + timedelta(hours=1, minutes=9)  # 59 minutes after the last wrong code
        self.assertTrue(lc.closed(self.now))
        self.now = made + timedelta(hours=1, minutes=10, seconds=1)
        self.assertFalse(lc.closed(self.now))

    def test_a_right_code_used_is_not_a_wrong_one(self):
        row = self.issue()
        with mock.patch.object(lc, "WRONG_AN_HOUR", 1):
            found = lc.check("ny_adress", "webblasare-1", lc.code(row))
            with db.DB_PROXY.atomic():
                lc.consume(found)
            self.assertFalse(lc.closed(self.now))


class TestRefusals(LoginCodeTest):
    def test_no_code_without_link_secret(self):
        row = self.issue()
        with mock.patch.object(settings.mail, "link_secret", ""):
            with self.assertRaises(lc.CodeRefused):
                self.issue(browser="w2")
            with self.assertRaises(lc.CodeRefused):
                lc.check("ny_adress", "webblasare-1", "00000000")
        self.assertEqual(self.row(row).failed, 0)

    def test_no_code_in_production_in_log_mode(self):
        with (
            mock.patch.dict(os.environ, {"FLASK_ENV": "production"}),
            mock.patch.object(settings.mail, "mode", "log"),
            self.assertRaises(lc.CodeRefused),
        ):
            self.issue()
        with mock.patch.dict(os.environ, {"FLASK_ENV": "production"}):
            self.assertIsNotNone(self.issue())  # live mode
        with mock.patch.object(settings.mail, "mode", "log"):
            self.assertIsNotNone(self.issue(browser="w2"))  # log mode outside production


class TestPurge(LoginCodeTest):
    def test_rows_older_than_a_day_go_with_their_trace_in_the_queue(self):
        old, new = self.issue(browser="w1"), self.issue(browser="w2")
        db.LoginCode.update(created_at=self.now - timedelta(days=1, seconds=1)).where(
            db.LoginCode.id == old.id
        ).execute()
        mail_id = mail.enqueue_mail("ansokan.godkand", "login_code", old.id, {"member_id": self.person.id})
        db.MailMessage.update(status="sent", address_hash="hash", dedupe_key="key").where(
            db.MailMessage.id == mail_id
        ).execute()

        self.assertEqual(lc.purge(self.now), 1)

        self.assertEqual([r.id for r in db.LoginCode.select()], [new.id])
        queued = db.MailMessage.get_by_id(mail_id)
        self.assertEqual((queued.address_hash, queued.dedupe_key), (None, None))

    def test_an_interrupted_purge_leaves_nothing_half_done(self):
        """Deleting a row and forgetting its mail's address are one step: a purge that fails between them is run
        again and finishes, and no address hash is left in the queue for a row that is gone."""
        old = self.issue()
        db.LoginCode.update(created_at=self.now - timedelta(days=2)).where(db.LoginCode.id == old.id).execute()
        mail_id = mail.enqueue_mail("konto.kod", "login_code", old.id, {"code_id": old.id})
        db.MailMessage.update(status="sent", address_hash="hash").where(db.MailMessage.id == mail_id).execute()
        with mock.patch.object(lc, "forget_recipient", side_effect=RuntimeError("database gone")):
            with self.assertRaises(RuntimeError):
                lc.purge(self.now)
        self.assertTrue(db.LoginCode.select().where(db.LoginCode.id == old.id).exists())
        self.assertEqual(lc.purge(self.now), 1)
        self.assertIsNone(db.MailMessage.get_by_id(mail_id).address_hash)

    def test_an_expired_code_keeps_no_new_address(self):
        old, new = self.issue(browser="w1"), self.issue(person=self.person_row("Bo", "bo@example.org"), browser="w2")
        db.LoginCode.update(created_at=self.now - timedelta(minutes=10)).where(db.LoginCode.id == old.id).execute()
        self.assertEqual(lc.expire(self.now), 1)
        self.assertEqual((self.row(old).new_address, self.row(new).new_address), (None, "ny@example.org"))

    def test_the_nightly_job_purges_codes_when_the_mail_purge_fails(self):
        old = self.issue()
        db.LoginCode.update(created_at=datetime.now(timezone.utc) - timedelta(days=2)).where(
            db.LoginCode.id == old.id
        ).execute()
        with (
            mock.patch.object(herdbook, "purge_old_mail", side_effect=RuntimeError("database gone")),
            mock.patch.object(herdbook, "purge_command_free_text", return_value=0),
            mock.patch.object(herdbook.genetics.ps, "_close_db_connection"),
            self.assertLogs(herdbook.APP.logger, "ERROR"),
        ):
            herdbook._purge_command_free_text()
        self.assertFalse(db.LoginCode.select().exists())

    def test_the_leader_expires_codes_every_minute(self):
        lock = os.path.join(tempfile.mkdtemp(), "scheduler.lock")
        with (
            mock.patch.object(herdbook, "SCHEDULER_LOCK_PATH", lock),
            mock.patch.object(ci, "init_redis"),
            mock.patch.object(ci, "start_pubsub_listener"),
            mock.patch.object(ci, "set_cache_and_functions"),
            mock.patch.object(herdbook, "_warm_genetics_in_background"),
            mock.patch.object(herdbook.apscheduler.schedulers.background, "BackgroundScheduler") as scheduler_cls,
        ):
            herdbook.initialize_app()
        calls = scheduler_cls.return_value.add_job.call_args_list
        (job,) = [c for c in calls if herdbook._expire_login_codes in c.args]
        self.assertEqual((job.kwargs["minutes"], job.kwargs["id"]), (1, "login_code_expire"))


class TestMails(LoginCodeTest):
    def setUp(self):
        super().setUp()
        self.fake = FakeRelay()
        patch = mock.patch.object(mail.smtplib, "SMTP", self.fake)
        patch.start()
        self.addCleanup(patch.stop)

    def queue_code(self, **kwargs):
        row = self.issue(**kwargs)
        return row, mail.enqueue_mail("konto.kod", "login_code", row.id, {"code_id": row.id})

    def status(self, mail_id):
        return db.MailMessage.get_by_id(mail_id).status

    def test_the_new_address_gets_the_code_and_no_link(self):
        row, mail_id = self.queue_code()
        mail.send_pending()
        ((msg, _sender, to),) = self.fake.sent
        self.assertEqual(to, ["ny@example.org"])
        self.assertEqual(msg["Subject"], "Din kod för att byta e-postadress i Stamboken")
        body = msg.get_content()
        self.assertIn(f"\n{lc.shown(lc.code(row))}\n", body)
        self.assertIn("Du har bett om att byta e-postadress i Stamboken.", body)
        self.assertNotIn("http", body)
        self.assertEqual(db.MailMessage.get_by_id(mail_id).priority, 0)

    def test_no_mail_once_the_code_is_too_old_used_voided_or_the_account_changed(self):
        old, old_mail = self.queue_code(browser="w1")
        used, used_mail = self.queue_code(browser="w2")
        voided, voided_mail = self.queue_code(person=self.person_row("Bo", "bo@example.org"), browser="w3")
        moved, moved_mail = self.queue_code(person=self.person_row("Cid", "cid@example.org"), browser="w4")
        db.LoginCode.update(created_at=self.now - timedelta(minutes=10)).where(db.LoginCode.id == old.id).execute()
        with db.DB_PROXY.atomic():
            lc.consume(used)
        lc.void(voided.member_id)
        user = herdbook.da.register_user("cid@example.org", "pass", username="cid")
        db.Member.update(user=user.id).where(db.Member.id == moved.member_id).execute()

        mail.send_pending()

        self.assertEqual(self.fake.sent, [])
        for mail_id in (old_mail, used_mail, voided_mail, moved_mail):
            self.assertEqual(self.status(mail_id), "cancelled")

    def test_a_login_code_has_no_mail_yet(self):
        _row, mail_id = self.queue_code(purpose="login")
        mail.send_pending()
        self.assertEqual((self.fake.sent, self.status(mail_id)), ([], "cancelled"))

    def test_a_friexemplar_request_gets_the_unknown_address_result_and_sends_no_code(self):
        person = self.person_row("Frida", "friblad@example.invalid")
        db.Membership.update(membership_status="friexemplar").where(db.Membership.id == person.membership_id).execute()
        for purpose in ("login", "ny_adress"):
            with db.DB_PROXY.atomic():
                self.assertIsNone(lc.issue(None, purpose, "okänd", "okand@example.invalid"))
                self.assertIsNone(lc.issue(person, purpose, "friblad", person.email))
        self.assertFalse(db.LoginCode.select().exists())
        self.assertFalse(db.MailMessage.select().where(db.MailMessage.kind == "konto.kod").exists())
        mail.send_pending()
        self.assertEqual(self.fake.sent, [])

    def test_becoming_friexemplar_stops_pending_mail_and_redemption(self):
        person = self.person_row("Mira", "mira@example.invalid")
        login = self.issue(person=person, purpose="login", address=person.email)
        found = lc.check("login", "webblasare-1", lc.code(login))
        self.assertIsNotNone(found)
        change, mail_id = self.queue_code(person=person, address="ny@example.invalid")
        db.Membership.update(membership_status="friexemplar").where(db.Membership.id == person.membership_id).execute()

        mail.send_pending()
        self.assertEqual((self.fake.sent, self.status(mail_id)), ([], "cancelled"))
        for row in (login, change):
            self.assertIsNone(lc.check(row.purpose, "webblasare-1", lc.code(row)))
        with db.DB_PROXY.atomic():
            self.assertFalse(lc.consume(found))

    def test_the_code_is_in_the_log_in_development_only(self):
        row, _ = self.queue_code(browser="w1")
        with mock.patch.object(settings.mail, "mode", "log"), self.assertLogs(level="DEBUG") as logs:
            mail.send_pending()
        self.assertIn(lc.shown(lc.code(row)), "\n".join(logs.output))

        row, _ = self.queue_code(browser="w2")
        with mock.patch.dict(os.environ, {"FLASK_ENV": "production"}), self.assertLogs(level="DEBUG") as logs:
            mail.send_pending()
            logging.getLogger("tests").info("sent")
        self.assertEqual(len(self.fake.sent), 1)
        logged = "\n".join(logs.output)
        self.assertNotIn(lc.code(row), logged.replace(" ", ""))

    def besked(self, **params):
        previous = db.MemberPreviousAddress.create(
            member=self.person, address="gammal@example.org", login_until=None, purge_at=self.now
        )
        params = {"previous_id": previous.id, "by_self": False, "by_matrikel": False, **params}
        return previous, mail.enqueue_mail("kontakt.epost_besked", "member_previous_address", previous.id, params)

    def test_the_previous_address_hears_who_changed_it_and_never_the_new_one(self):
        for params, said in (
            ({"by_self": True}, "Du bytte den själv."),
            ({"by_matrikel": True}, "Det var matrikelansvarig som bytte den."),
            ({}, "Det var någon annan än du som bytte den."),
        ):
            self.fake.sent.clear()
            self.besked(**params)
            mail.send_pending()
            ((msg, _sender, to),) = self.fake.sent
            self.assertEqual(to, ["gammal@example.org"])
            self.assertEqual(msg["Subject"], "Din e-postadress i Stamboken är bytt")
            body = msg.get_content()
            self.assertIn(said, body)
            self.assertIn("Stämmer det inte? Svara på det här mejlet.", body)
            self.assertNotIn("@", body)  # neither the new address nor any other

    def test_no_besked_once_the_row_is_gone(self):
        previous, mail_id = self.besked(by_self=True)
        previous.delete_instance()
        mail.send_pending()
        self.assertEqual((self.fake.sent, self.status(mail_id)), ([], "cancelled"))
