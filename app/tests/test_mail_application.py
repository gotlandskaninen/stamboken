"""The membership application's mails: the receipt and the notice to matrikel admins, in its transaction.

isort:skip_file
"""

import os
import smtplib
from datetime import timedelta
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.mail as mail  # noqa: E402
import utils.matrikel as matrikel  # noqa: E402
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
        receipt = to["sokande@example.org"].get_content()
        self.assertIn("200 kr och betalas till Plusgiro 35 03 44-8 eller Swish 123 095 70 50", receipt)  # as the site
        self.assertNotIn("\n\n\n", receipt)

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
        body = " ".join(msg.get_content().split())  # the mail wraps its lines
        self.assertIn("vi har fått din medlemsavgift", body)  # an approved application is a paid one
        number = db.Member.get_by_id(member_id).membership.member_number
        self.assertIn(f"Du har fått medlemsnummer {number}.", body)
        self.assertIn("välkomstbrev som vi sänder via Postnord", body)

    def test_no_welcome_with_the_old_number_once_the_membership_has_ended(self):
        member = db.Member.get_by_id(self._approve(self.application()).get_json()["created_member_id"])
        matrikel.retire_membership(member.membership, self.admin)
        relay = self.relay()
        mail.send_pending(self.now)
        self.assertEqual(relay.sent, [])
        self.assertEqual(db.MailMessage.get(db.MailMessage.kind == "ansokan.godkand").status, "cancelled")

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


class TestMemberAdded(MailTest):
    """medlemskap.tillagd: to a person someone else put into a membership, in that transaction."""

    def setUp(self):
        super().setUp()
        self.actor = da.register_user("matrikel@example.org", "pass")
        self.membership = db.Membership.create(membership_status="active")
        db.Member.create(
            membership=self.membership, first_name="Huvud", last_name="Medlem\nRad två", role="huvudmedlem"
        )

    def add(self, **data):
        fields = {"first_name": "Ny", "last_name": "Person", "email": "ny@example.org", **data}
        return matrikel.add_person(self.membership, fields, self.actor)

    def mails(self):
        return list(db.MailMessage.select().where(db.MailMessage.kind == "medlemskap.tillagd"))

    def test_a_family_member_with_an_address_is_told(self):
        person = self.add(phone="070-000 00 00")
        (row,) = self.mails()
        self.assertEqual(
            (row.recipient_kind, row.recipient_id, row.category, row.ref_type, row.ref_id, row.params),
            ("member", person.id, "T", "membership", self.membership.id, {"member_id": person.id}),
        )
        relay = self.relay()
        self.assertEqual(mail.send_pending(self.now), 1)
        msg, _, envelope_to = relay.sent[0]
        body = msg.get_content()
        self.assertEqual(envelope_to, ["ny@example.org"])
        self.assertIn("lagts in som familjemedlem", body)
        self.assertIn("Huvudmedlem är Huvud Medlem Rad två.", body)  # the name on one line
        self.assertIn("och ditt telefonnummer", body)
        self.assertIn(f"https://{HOST}/dataskydd", body)
        self.assertIn("dataskydd@gotlandskaninen.se", body)

    def test_a_keeper_is_told_as_a_keeper_and_no_phone_is_named_without_one(self):
        self.add(role="skotare")
        relay = self.relay()
        mail.send_pending(self.now)
        body = relay.sent[0][0].get_content()
        self.assertIn("lagts in som skötare", body)
        self.assertNotIn("telefonnummer", body)

    def test_no_mail_without_an_address_or_to_a_main_member(self):
        self.add(email=None)
        other = db.Membership.create(membership_status="active")
        matrikel.add_person(
            other,
            {"first_name": "Ny", "last_name": "Huvud", "email": "h@example.org", "role": "huvudmedlem"},
            self.actor,
        )
        self.assertEqual(self.mails(), [])

    def test_a_rolled_back_addition_queues_nothing(self):
        with self.assertRaises(RuntimeError), db.DB_PROXY.atomic():
            self.add()
            self.assertEqual(len(self.mails()), 1)
            raise RuntimeError("the request fails after the person was added")
        self.assertEqual(self.mails(), [])

    def test_not_sent_once_the_person_has_left_the_membership(self):
        person = self.add()
        db.Member.update(end_date=self.now.date()).where(db.Member.id == person.id).execute()
        relay = self.relay()
        mail.send_pending(self.now)
        self.assertEqual((relay.sent, self.mails()[0].status), ([], "cancelled"))

    def test_not_sent_once_the_person_is_main_member(self):
        person = self.add()
        matrikel.swap_main_member(self.membership, person, self.actor)
        relay = self.relay()
        mail.send_pending(self.now)
        self.assertEqual((relay.sent, self.mails()[0].status), ([], "cancelled"))

    def test_a_removal_while_the_sender_connects_stops_the_mail(self):
        person = self.add()
        relay = self.relay()
        connect = mail._connect

        def removed_meanwhile(conn):  # after the build, while the connection and its TLS come up
            connect(conn)
            matrikel.soft_delete_person(db.Member.get_by_id(person.id), self.actor)

        with mock.patch.object(mail, "_connect", removed_meanwhile):
            mail.send_pending(self.now)
        (row,) = self.mails()
        self.assertEqual((relay.sent, row.status, row.claim_token), ([], "cancelled", None))

    def test_a_retired_membership_stops_its_peoples_mails(self):
        self.add()
        matrikel.retire_membership(self.membership, self.actor)
        self.assertEqual(self.mails()[0].status, "cancelled")

    def sent_to(self, **kwargs):
        relay = self.relay(**kwargs)
        mail.send_pending(self.now)
        return [envelope_to[0] for _msg, _sender, envelope_to in relay.sent]

    def later(self, **delta):
        self.now += timedelta(**delta)
        mail._utcnow.return_value = self.now  # pylint: disable=no-member  # MailTest's mock

    def waiting(self):
        return [(row.attempts, row.last_error) for row in self.mails() if row.status == "queued"]

    def test_an_address_gets_at_most_three_a_day_also_when_changed_to_and_the_rest_the_next_day(self):
        for n in range(4):
            self.add(first_name=f"Nummer {n}", email=f"person{n}@example.org")
        db.Member.update(email=" Samma@Example.ORG ").where(db.Member.role == "familjemedlem").execute()
        self.assertEqual(self.sent_to(), ["samma@example.org"] * mail.ADDED_TO_AN_ADDRESS_A_DAY)
        self.assertEqual(self.waiting(), [(0, "uppskjutet: adressens gräns per dygn")])
        self.assertNotIn("example.org", "".join(row.dedupe_key for row in self.mails()))
        self.later(hours=23)
        self.assertEqual(self.sent_to(), [])
        self.later(hours=1, seconds=1)
        self.assertEqual(self.sent_to(), ["samma@example.org"])

    def test_a_notice_held_by_the_address_limit_goes_before_newer_ones(self):
        for n in range(3):
            self.add(first_name=f"Nummer {n}", email="samma@example.org")
        self.sent_to()
        self.later(hours=12)
        held = self.add(first_name="Fyra", email="samma@example.org")
        self.sent_to()
        self.later(hours=12, seconds=1)  # the first three are a day old: three places, the oldest waiting first
        newer = [self.add(first_name=f"Ny {n}", email="samma@example.org") for n in range(3)]
        self.sent_to()
        sent = {row.recipient_id for row in self.mails() if row.status == "sent"}
        self.assertEqual((held.id in sent, newer[-1].id in sent), (True, False))

    def test_log_mode_without_a_link_secret_logs_the_mail(self):
        self.add()
        with mock.patch.multiple(settings.mail, mode="log", link_secret=""):
            mail.send_pending(self.now)
        (row,) = self.mails()
        self.assertEqual((row.status, row.attempts, row.last_error), ("logged", 0, None))

    def test_a_person_removed_and_added_again_the_same_day_is_told(self):
        first = self.add()
        matrikel.soft_delete_person(first, self.actor)  # before the sender ran: nothing went
        self.add()
        self.assertEqual(self.sent_to(), ["ny@example.org"])

    def test_a_promotion_while_the_sender_connects_stops_the_mail(self):
        person = self.add()
        relay = self.relay()
        connect = mail._connect

        def promoted_meanwhile(conn):
            connect(conn)
            matrikel.swap_main_member(self.membership, db.Member.get_by_id(person.id), self.actor)

        with mock.patch.object(mail, "_connect", promoted_meanwhile):
            mail.send_pending(self.now)
        (row,) = self.mails()
        self.assertEqual((relay.sent, row.status, row.claim_token), ([], "cancelled", None))

    def test_a_membership_spreads_its_notices_ten_a_day_in_order(self):
        for n in range(mail.ADDED_A_DAY + 2):
            self.add(first_name=f"Nummer {n}", email=f"person{n}@example.org")
        other = db.Membership.create(membership_status="active")  # another membership is not held back
        matrikel.add_person(other, {"first_name": "Ny", "last_name": "Person", "email": "x@example.org"}, self.actor)
        self.assertEqual(len(self.mails()), mail.ADDED_A_DAY + 3)  # every one is queued, none dropped
        self.assertEqual(len(self.sent_to()), mail.ADDED_A_DAY + 1)
        self.later(days=1)
        self.assertEqual(self.sent_to(), ["person10@example.org", "person11@example.org"])

    def test_no_day_holds_more_than_ten_of_a_membership_s_notices(self):
        for group, hours in enumerate((0, 23.98, 0.04)):  # ten at 10.00, ten the next day at 09.59 and at 10.01
            self.later(hours=hours)
            for n in range(mail.ADDED_A_DAY):
                self.add(first_name=f"Nummer {group} {n}", email=f"person{group}-{n}@example.org")
        due = sorted(row.next_attempt_at for row in self.mails())
        self.assertTrue(all(b - a >= timedelta(days=1) for a, b in zip(due, due[mail.ADDED_A_DAY :], strict=False)))

    def test_a_claim_taken_away_before_the_sender_reads_its_row_is_not_sent(self):
        person = self.add()
        relay = self.relay()
        read = db.MailMessage.get_by_id

        def meanwhile(row_id):  # between the claim and its read: a new address queues the row again, then "Stoppa"
            matrikel.set_member_email(db.Member.get_by_id(person.id), "annan@example.org", self.actor, by="matrikel")
            stopped = {"status": "cancelled", "last_error": "stoppat i statusvyn"}
            db.MailMessage.update(**stopped).where(db.MailMessage.status == "queued").execute()
            return read(row_id)

        with mock.patch.object(db.MailMessage, "get_by_id", side_effect=meanwhile):
            mail.send_pending(self.now)
        self.assertEqual((relay.sent, self.mails()[0].status), ([], "cancelled"))

    def test_a_refused_notice_uses_a_place_of_the_membership_s_day(self):
        refusal = smtplib.SMTPRecipientsRefused({"x": (550, b"5.1.1 no such user")})
        for n in range(mail.ADDED_A_DAY):
            self.add(first_name=f"Nummer {n}", email=f"person{n}@example.org")
        self.assertEqual(len(self.sent_to(replies=[refusal, None] * 5)), 5)
        self.add(first_name="Elva", email="elva@example.org")
        self.assertEqual(self.sent_to(), [])

    def test_a_person_given_an_address_later_is_told_once(self):
        person = self.add(email=None)
        self.assertEqual(self.mails(), [])
        matrikel.set_member_email(person, "senare@example.org", self.actor, by="matrikel")
        self.assertEqual(self.sent_to(), ["senare@example.org"])
        matrikel.set_member_email(person, "annan@example.org", self.actor, by="matrikel")
        self.assertEqual((len(self.mails()), self.sent_to()), (1, []))

    def test_an_address_given_later_to_someone_nobody_else_put_in_queues_nothing(self):
        imported = db.Member.create(  # as the register import writes it
            membership=self.membership, first_name="Från", last_name="Matrikeln", role="familjemedlem"
        )
        other = db.Membership.create(membership_status="active")
        was_main = matrikel.add_person(
            other,
            {"first_name": "Var", "last_name": "Huvud", "email": "var@example.org", "role": "huvudmedlem"},
            self.actor,
        )
        matrikel.swap_main_member(
            other, matrikel.add_person(other, {"first_name": "Ny", "last_name": "Huvud"}, self.actor), self.actor
        )
        for n, person in enumerate((imported, was_main)):
            matrikel.set_member_email(
                db.Member.get_by_id(person.id), f"senare{n}@example.org", self.actor, by="matrikel"
            )
        self.assertEqual(db.Member.get_by_id(was_main.id).role, "familjemedlem")
        self.assertEqual(self.mails(), [])

    def test_a_notice_that_never_reached_the_person_goes_to_the_next_address(self):
        stopped = self.add()
        refused = self.add(first_name="Andra", email="fel@example.org")
        bounced = self.add(first_name="Tredje", email="studs@example.org")
        matrikel.set_member_email(stopped, None, self.actor, by="matrikel")  # before the sender ran
        refusal = smtplib.SMTPRecipientsRefused({"fel@example.org": (550, b"5.1.1 no such user")})
        self.assertEqual(self.sent_to(replies=[refusal, None]), ["studs@example.org"])
        (row,) = [row for row in self.mails() if row.recipient_id == bounced.id]
        self.assertTrue(mail.record_bounce(mail.message_id(row.id), "550 5.1.1 user unknown"))
        self.assertEqual(sorted(row.status for row in self.mails()), ["bounced", "cancelled", "failed"])
        for n, person in enumerate((stopped, refused, bounced)):
            matrikel.set_member_email(person, f"ratt{n}@example.org", self.actor, by="matrikel")
        self.assertEqual(sorted(self.sent_to()), ["ratt0@example.org", "ratt1@example.org", "ratt2@example.org"])
        self.assertEqual([(row.status, row.attempts) for row in self.mails()], [("sent", 1)] * 3)

    def test_a_notice_stopped_by_hand_stays_stopped(self):
        person = self.add()
        db.MailMessage.update(status="cancelled", last_error="stoppat i statusvyn").execute()  # as "Stoppa" does
        matrikel.set_member_email(person, "annan@example.org", self.actor, by="matrikel")
        self.assertEqual([(row.status, row.last_error) for row in self.mails()], [("cancelled", "stoppat i statusvyn")])

    def test_an_address_changed_while_the_sender_connects_is_the_one_told(self):
        person = self.add()
        relay = self.relay()
        connect = mail._connect

        def changed_meanwhile(conn):  # the sender has read the old address and built the mail
            connect(conn)
            matrikel.set_member_email(db.Member.get_by_id(person.id), "ratt@example.org", self.actor, by="matrikel")

        with mock.patch.object(mail, "_connect", changed_meanwhile):
            mail.send_pending(self.now)
        self.assertEqual([envelope_to for _msg, _sender, envelope_to in relay.sent], [["ratt@example.org"]])
        self.assertEqual([row.status for row in self.mails()], ["sent"])

    def test_an_address_given_to_someone_who_left_queues_nothing(self):
        person = self.add(email=None)
        matrikel.soft_delete_person(person, self.actor)
        matrikel.set_member_email(person, "senare@example.org", self.actor, by="matrikel")
        self.assertEqual(self.mails(), [])

    def test_the_register_import_does_not_go_through_add_person(self):
        """The import writes its rows itself: the people in the register gave their details themselves."""
        source = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "cli", "members.py"), encoding="utf-8"
        ).read()
        self.assertNotIn("add_person(", source)
