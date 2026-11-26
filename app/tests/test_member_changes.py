#!/usr/bin/env python3
"""
Tests for step 5's "Dina uppgifter" (spec 5.11, 5.1, 6): the logged-in main member's changes written at Skicka, the
link's changes that wait for the receipt mail's confirmation page, and the status view's "nytt konto" with its undo.
Synthetic herds, members, accounts and addresses only.

isort:skip_file
"""

import dataclasses
import hashlib
import hmac
import json
import re
import threading
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import utils.arsrapport as arsrapport
import utils.data_access as da
import utils.database as db
import utils.mail as mail
import utils.member_changes as member_changes
import utils.report_code as report_code
import utils.settings as settings
from herdbook import APP
from utils.matrikel import set_member_email, swap_main_member
from utils.members import CONSENT_TEXT_VERSION, set_consent

from tests.arsrapport_fixtures import ArsrapportTest

DAY0 = date(2026, 1, 10)
REPORT = "/besattning/{herd}/2025"
ACCOUNT = "8327-4471 5512"
NEW_KONTO = {"typ": "bankkonto", "clearing": "9420", "konto": "4618 0377", "bank": "Nya banken"}
JA = {"ja": True, "utom": [], "text_version": CONSENT_TEXT_VERSION}
NEJ = {"ja": False, "utom": [], "text_version": CONSENT_TEXT_VERSION}
ALL = {"name": True, "phone": True, "email": True, "address": True}
NONE = {"name": False, "phone": False, "email": False, "address": False}


def codes(response):
    return {refusal["code"] for refusal in response.get_json()["refusals"]}


class DetailsTest(ArsrapportTest):
    """G9001 owned by `owner`, whose account is linked to its main member; G9002 another member's."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.multiple(settings.mail, link_secret="test-link-secret", link_hosts=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.at(DAY0)
        self.round_ = self.round(2025)
        self.h = db.Herd.create(genebank=self.gotland, herd="G9001", is_active=True)
        self.h2 = db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True)
        self.owner.add_role("owner", self.h.id)
        self.member = self.main_member(self.h, "g9001@example.invalid")
        self.member2 = self.main_member(self.h2, "g9002@example.invalid")
        for member in (self.member, self.member2):
            db.Member.update(phone="0709-111 222").where(db.Member.id == member.id).execute()
            db.Membership.update(
                address="Gamla vägen 1", postal_code="621 41", city="Slite", bank_account_number=ACCOUNT
            ).where(db.Membership.id == member.membership_id).execute()
        self.rabbits_ = self.rabbits(self.h, 1)
        self.rabbits2 = self.rabbits(self.h2, 1)
        self.tokens = {}

    def link_owner(self):
        db.Member.update(user=self.owner.id).where(db.Member.id == self.member.id).execute()

    def open_link(self, herd=None):
        herd, member = (self.h2, self.member2) if herd == "G9002" else (self.h, self.member)
        code = report_code.issue_code(herd, self.round_, member, now=arsrapport.now())
        response = self.client.post("/api/v2/rapport/oppna", json={"token": mail.link_token("rapport", code.id)})
        self.assertEqual(response.status_code, 200)
        return code

    def skicka(self, herd="G9001", matrikel=None, route="skicka", **fields):
        rabbits = self.rabbits2 if herd == "G9002" else self.rabbits_
        body = self.body(*[self.kvar(rabbit, vikt=2.8) for rabbit in rabbits], **fields)
        if matrikel is not None:
            body["matrikel"] = matrikel
        if fields.get("revision") is None:
            report = db.YearlyHerdReport.get_or_none(
                db.YearlyHerdReport.herd == (self.h2 if herd == "G9002" else self.h),
                db.YearlyHerdReport.status == "submitted",
            )
            body["revision"] = report.revision if report else None
        return self.api("POST", f"{REPORT.format(herd=herd)}/{route}", **body)

    def ok(self, **kwargs):
        response = self.skicka(**kwargs)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        receipt = response.get_json()
        self.tokens[receipt["submission_id"]] = self.mail_token(receipt["submission_id"])  # as the mailbox got it
        return receipt

    def view(self, herd="G9001"):
        return self.api("GET", REPORT.format(herd=herd)).get_json()

    def membership(self, member=None):
        return db.Membership.get_by_id((member or self.member).membership_id)

    def requests(self):
        return list(db.MemberChangeRequest.select().order_by(db.MemberChangeRequest.id))

    def mails(self, kind):
        return list(db.MailMessage.select().where(db.MailMessage.kind == kind).order_by(db.MailMessage.id))

    def rendered(self, row):
        return mail.render(row.kind, mail.MAIL_KINDS[row.kind].build(row.params))

    def mail_token(self, submission_id):
        """The confirmation token in the submission's receipt mail, as it renders now; None without one."""
        (row,) = db.MailMessage.select().where(
            db.MailMessage.kind.in_(("arsrapport.kvitto", "arsrapport.andrad")),
            db.MailMessage.ref_id == submission_id,
        )
        variables = mail.MAIL_KINDS[row.kind].build(row.params)
        found = re.search(r"/rapport/andringar#(\S+)$", mail.render(row.kind, variables)[1], re.M)
        return found[1] if found else None

    def token(self, submission_id):
        """The token the mailbox got when the receipt went, right after Skicka."""
        return self.tokens.get(submission_id) or self.mail_token(submission_id)

    def changes(self, submission_id, route="", **body):
        path = f"/api/v2/rapport/andringar{route}"
        return self.client.post(path, json={"token": self.token(submission_id), **body})


class TestLoggedIn(DetailsTest):
    def test_view_mode_follows_d1(self):
        self.link_owner()
        self.login("owner")
        details = self.view()["member_details"]
        self.assertEqual(details["mode"], "main")
        self.assertEqual(details["contact"]["address"], "Gamla vägen 1")
        self.assertEqual((details["konto"], details["publicering"]), ("••••5512", None))
        db.Member.update(user=None).where(db.Member.id == self.member.id).execute()  # an owner who is someone else
        self.assertEqual(self.view()["member_details"], {"mode": "none"})

    def test_a_short_account_shows_fewer_digits(self):  # database.account_end's rule (#278)
        self.link_owner()
        self.login("owner")
        for number, shown in (("1234-5678 90", "••••7890"), ("12345-6", "••56"), ("12-3", "••")):
            db.Membership.update(bank_account_number=number).where(
                db.Membership.id == self.member.membership_id
            ).execute()
            self.assertEqual(self.view()["member_details"]["konto"], shown)

    def test_link_view_holds_no_value(self):
        self.open_link()
        details = self.view()["member_details"]
        self.assertEqual(details, {"mode": "link", "changes": []})

    def test_main_member_changes_are_written_at_skicka(self):
        self.link_owner()
        self.login("owner")
        receipt = self.ok(
            matrikel={
                "telefon": "",
                "adress": {"city": "Visby"},
                "konto": NEW_KONTO,
                "publicering": {**JA, "version": None},  # never answered
            }
        )
        member, ms = db.Member.get_by_id(self.member.id), self.membership()
        self.assertEqual((member.phone, ms.city, ms.address), (None, "Visby", "Gamla vägen 1"))  # "" clears (U9)
        self.assertEqual((ms.bank_account_type, ms.bank_account_number), ("bankkonto", "9420-46180377"))
        self.assertEqual(ms.publication_consent, ALL)
        (consent,) = db.PublicationConsentChange.select()
        self.assertEqual((consent.source, consent.submission_id), ("login", receipt["submission_id"]))
        (audit,) = db.MatrikelAudit.select().where(db.MatrikelAudit.action == "kontakt_andrad")
        self.assertEqual(audit.payload["source"], "login")
        self.assertEqual(
            set(audit.payload["fields"]), {"city", "phone", "bank_account_type", "bank_account_number", "bank_name"}
        )
        self.assertEqual(receipt["matrikel"], ["konto", "adress", "telefon", "publicering"])
        (notice,) = self.mails(arsrapport.ACCOUNT_NOTICE)
        subject, body = self.rendered(notice)
        self.assertEqual(subject, "Kontot för stödet har ändrats")
        self.assertIn("••77", body)
        self.assertEqual(self.requests(), [])

    def test_unchanged_values_write_nothing(self):
        self.link_owner()
        self.login("owner")
        self.ok(matrikel={"telefon": "0709-111 222", "adress": {"address": "Gamla vägen 1"}})
        self.assertFalse(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "kontakt_andrad").exists())

    def test_someone_else_cannot_change_the_details(self):
        self.login("owner")  # owns G9001, but the main member's account is not this one
        before = (self.membership().address, db.Member.get_by_id(self.member.id).phone)
        response = self.skicka(matrikel={"telefon": "0709-999 999"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["detail"], arsrapport.NOT_MAIN)
        self.assertEqual((self.membership().address, db.Member.get_by_id(self.member.id).phone), before)
        self.assertFalse(db.YearlyHerdReport.select().exists())

    def test_email_goes_through_the_code_and_the_text_version_counts(self):
        self.link_owner()
        self.login("owner")
        response = self.skicka(matrikel={"epost": "ny@example.invalid"}, route="torrkorning")
        self.assertEqual(codes(response), {"epost_via_kod"})
        old = {**JA, "text_version": "2026-11-18"}
        response = self.skicka(matrikel={"publicering": old}, route="torrkorning")
        self.assertEqual(codes(response), {"koharen_ny_fraga"})
        self.assertEqual(self.skicka(matrikel={"epost": "ny@example.invalid"}).status_code, 422)
        self.assertEqual(db.Member.get_by_id(self.member.id).email, "g9001@example.invalid")

    def test_a_body_without_details_hashes_as_before(self):
        """A retry made before step 5 still matches its stored hash: no `matrikel` key in the hash."""
        sub = arsrapport.parse_submission(self.body(self.kvar(self.rabbits_[0], vikt=2.8)), paper=False)
        fields = {k: v for k, v in dataclasses.asdict(sub).items() if k not in ("key", "revision", "matrikel")}
        canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        with APP.app_context():
            expected = hmac.new(APP.secret_key.encode(), canonical.encode(), hashlib.sha256).hexdigest()
            self.assertEqual(arsrapport.request_hash(sub), expected)


class TestLink(DetailsTest):
    def submit_changes(self, matrikel, herd="G9001"):
        self.open_link(herd)
        return self.ok(herd=herd, matrikel=matrikel)

    def test_link_changes_wait_and_write_nothing(self):
        before = (self.membership().address, self.membership().bank_account_number, db.Member.get_by_id(self.member.id))
        receipt = self.submit_changes(
            {
                "adress": {"address": "Nya gatan 2"},
                "telefon": "0709-777 888",
                "epost": "ny@example.invalid",
                "konto": NEW_KONTO,
                "publicering": JA,  # never answered: a Ja waits
            }
        )
        rows = self.requests()
        self.assertEqual([row.kind for row in rows], ["kontakt", "kontakt", "konto", "epost", "publicering"])
        last = datetime.combine(DAY0 + timedelta(days=14), datetime.max.time(), arsrapport.STOCKHOLM)
        self.assertTrue(all(row.expires_at == last for row in rows))  # the end of the day the receipt prints
        ms = self.membership()
        self.assertEqual((ms.address, ms.bank_account_number), before[:2])
        self.assertEqual(db.Member.get_by_id(self.member.id).email, "g9001@example.invalid")
        self.assertEqual(ms.publication_consent, {})
        self.assertFalse(db.PublicationConsentChange.select().exists())
        self.assertEqual(receipt["matrikel"], [])
        # the receipt mail: the subject of 5.11 and the confirmation page, to the member's login address
        (kvitto,) = self.mails("arsrapport.kvitto")
        subject, body = self.rendered(kvitto)
        self.assertEqual(subject, "Årsrapporten är inskickad, bekräfta dina ändringar")
        self.assertIn(f"/rapport/andringar#{self.token(receipt['submission_id'])}", body)
        self.assertIn("Kontot ändras först när du också kryssat i kontobytet.", body)
        self.assertEqual(mail.MAIL_KINDS["arsrapport.kvitto"].login_address(kvitto.params), "g9001@example.invalid")
        self.assertEqual(
            [c["falt"] for c in self.view()["member_details"]["changes"]],
            ["adress", "telefon", "konto", "epost", "publicering"],
        )

    def test_a_no_goes_at_once_and_fewer_details_too(self):
        with db.DB_PROXY.atomic():
            set_consent(self.membership(), ALL, source="profil", text_version=CONSENT_TEXT_VERSION)
        self.submit_changes({"publicering": {**JA, "utom": ["phone"]}})
        self.assertEqual(self.membership().publication_consent, {**ALL, "phone": False})
        self.assertEqual([row.kind for row in self.requests()], ["publicering"])  # a Ja always waits (no leak)
        self.ok(matrikel={"publicering": NEJ})
        self.assertEqual(self.membership().publication_consent, NONE)
        self.assertEqual({row.source for row in db.PublicationConsentChange.select()}, {"profil", "link"})

    def test_mixed_answer_narrows_now_and_adds_later(self):
        with db.DB_PROXY.atomic():
            set_consent(self.membership(), {**ALL, "email": False}, source="profil", text_version=CONSENT_TEXT_VERSION)
        receipt = self.submit_changes({"publicering": {**JA, "utom": ["phone"]}})
        self.assertEqual(self.membership().publication_consent, {**ALL, "email": False, "phone": False})
        (row,) = self.requests()
        self.assertEqual(row.value["new"], {**ALL, "phone": False})
        view = self.changes(receipt["submission_id"]).get_json()
        confirmed = self.changes(receipt["submission_id"], "/bekrafta", version=view["version"], konto=False)
        self.assertEqual(confirmed.status_code, 200, confirmed.get_data(as_text=True))
        self.assertEqual(self.membership().publication_consent, {**ALL, "phone": False})

    def test_a_direct_no_revokes_a_waiting_yes_even_unchanged(self):  # 5.11, U5
        with db.DB_PROXY.atomic():
            set_consent(self.membership(), NONE, source="profil", text_version=CONSENT_TEXT_VERSION)
        receipt = self.submit_changes({"publicering": JA})
        self.client.get("/api/logout")
        self.link_owner()
        self.login("owner")
        response = self.client.patch(
            "/api/v2/members/me/consent", json={"name": False, "text_version": CONSENT_TEXT_VERSION}
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        (row,) = self.requests()
        self.assertEqual(row.revoked_reason, "nyare")
        view = self.changes(receipt["submission_id"]).get_json()
        self.assertEqual(view["changes"][0]["state"], "aterkallad")

    def test_confirmation_get_never_writes_and_the_account_needs_its_own_tick(self):
        receipt = self.submit_changes({"telefon": "0709-777 888", "konto": NEW_KONTO})
        response = self.changes(receipt["submission_id"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        view = response.get_json()
        self.assertEqual(
            [(c["falt"], c["state"], c["nu"], c["nytt"]) for c in view["changes"]],
            [("telefon", "vantar", "0709-111 222", "0709-777 888"), ("konto", "vantar", "••••5512", "••••0377")],
        )
        self.assertFalse(any(row.confirmed_at for row in self.requests()))
        done = self.changes(receipt["submission_id"], "/bekrafta", version=view["version"], konto=False).get_json()
        self.assertEqual([c["state"] for c in done["changes"]], ["bekraftad", "vantar"])
        self.assertEqual(db.Member.get_by_id(self.member.id).phone, "0709-777 888")
        self.assertEqual(self.membership().bank_account_number, ACCOUNT)
        self.assertEqual(self.mails(arsrapport.ACCOUNT_NOTICE), [])
        done = self.changes(receipt["submission_id"], "/bekrafta", version=done["version"], konto=True).get_json()
        self.assertEqual([c["state"] for c in done["changes"]], ["bekraftad", "bekraftad"])
        self.assertEqual(self.membership().bank_account_number, "9420-46180377")
        self.assertEqual(len(self.mails(arsrapport.ACCOUNT_NOTICE)), 1)
        (audit, _) = (
            db.MatrikelAudit.select().where(db.MatrikelAudit.action == "kontakt_andrad").order_by(db.MatrikelAudit.id)
        )
        self.assertEqual((audit.actor_id, audit.payload["source"]), (None, "link"))

    def test_a_change_since_the_page_is_a_409(self):  # D6
        receipt = self.submit_changes({"telefon": "0709-777 888"})
        view = self.changes(receipt["submission_id"]).get_json()
        db.Member.update(phone="0709-333 444").where(db.Member.id == self.member.id).execute()
        response = self.changes(receipt["submission_id"], "/bekrafta", version=view["version"], konto=False)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(db.Member.get_by_id(self.member.id).phone, "0709-333 444")

    def test_changes_expire_after_fourteen_days(self):
        receipt = self.submit_changes({"telefon": "0709-777 888"})
        self.at(datetime.combine(DAY0 + timedelta(days=15), datetime.min.time(), arsrapport.STOCKHOLM))
        view = self.changes(receipt["submission_id"]).get_json()
        self.assertEqual(view["changes"][0]["state"], "forfallen")
        self.changes(receipt["submission_id"], "/bekrafta", version=view["version"], konto=False)
        self.assertEqual(db.Member.get_by_id(self.member.id).phone, "0709-111 222")

    def test_not_me_revokes_and_the_status_view_says_so(self):
        receipt = self.submit_changes({"telefon": "0709-777 888", "konto": NEW_KONTO})
        flags = self.status_flags()
        self.assertEqual((flags["andring_vantar"], flags["kontobyte_vantar"], flags["inte_jag"]), (1, True, False))
        view = self.changes(receipt["submission_id"], "/inte-jag").get_json()
        self.assertEqual({c["state"] for c in view["changes"]}, {"inte_jag"})
        self.assertEqual(db.Member.get_by_id(self.member.id).phone, "0709-111 222")
        flags = self.status_flags()
        self.assertEqual((flags["andring_vantar"], flags["kontobyte_vantar"], flags["inte_jag"]), (0, False, True))

    def status_flags(self, herd="G9001"):
        view = arsrapport.status_view(self.round_, self.gotland.id)
        return next(row["flags"] for row in view["rows"] if row["herd"] == herd)

    def test_expired_account_change_flag_and_purge_keeps_it(self):  # U14
        self.submit_changes({"konto": NEW_KONTO})
        self.at(DAY0 + timedelta(days=15))
        self.assertTrue(self.status_flags()["kontobyte_forfoll"])
        import utils.inbox_purge as inbox_purge  # pylint: disable=import-outside-toplevel

        self.assertEqual(inbox_purge.purge_change_requests(datetime.now(timezone.utc) + timedelta(days=60)), 1)
        self.assertEqual(self.requests()[0].value, {})
        self.assertTrue(self.status_flags()["kontobyte_forfoll"])

    def test_newer_confirmed_revokes_older_but_older_then_newer_works(self):  # 5.11, U5
        first = self.submit_changes({"telefon": "0709-000 001"})
        second = self.ok(matrikel={"telefon": "0709-000 002"})
        older = self.changes(first["submission_id"]).get_json()
        self.changes(first["submission_id"], "/bekrafta", version=older["version"], konto=False)
        newer = self.changes(second["submission_id"]).get_json()
        response = self.changes(second["submission_id"], "/bekrafta", version=newer["version"], konto=False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(db.Member.get_by_id(self.member.id).phone, "0709-000 002")
        third = self.ok(matrikel={"telefon": "0709-000 003"})
        fourth = self.ok(matrikel={"telefon": "0709-000 004"})
        newest = self.changes(fourth["submission_id"]).get_json()
        self.changes(fourth["submission_id"], "/bekrafta", version=newest["version"], konto=False)
        stale = self.changes(third["submission_id"]).get_json()
        self.assertEqual(stale["changes"][0]["state"], "aterkallad")
        self.assertEqual(db.Member.get_by_id(self.member.id).phone, "0709-000 004")

    def test_email_is_another_persons_change_with_seven_days_wait(self):  # fråga 10
        receipt = self.submit_changes({"epost": "ny@example.invalid"})
        view = self.changes(receipt["submission_id"]).get_json()
        self.assertEqual(
            (view["changes"][0]["nu"], view["changes"][0]["nytt"]), ("g9001@example.invalid", "ny@example.invalid")
        )
        self.changes(receipt["submission_id"], "/bekrafta", version=view["version"], konto=False)
        member = db.Member.get_by_id(self.member.id)
        self.assertEqual(member.email, "ny@example.invalid")
        self.assertIsNotNone(member.email_login_from)  # by="other": the new address counts after seven days
        self.assertEqual(len(self.mails("kontakt.epost_besked")), 1)  # the old address is told
        # a later receipt still goes to the old address while the new one waits (U8)
        self.ok(matrikel={"telefon": "0709-777 888"})
        later = self.mails("arsrapport.andrad")[-1]
        self.assertEqual(mail.MAIL_KINDS[later.kind].login_address(later.params), "g9001@example.invalid")

    def test_a_taken_address_drops_only_the_email_change(self):
        receipt = self.submit_changes({"epost": "g9002@example.invalid", "telefon": "0709-777 888"})
        view = self.changes(receipt["submission_id"]).get_json()
        response = self.changes(receipt["submission_id"], "/bekrafta", version=view["version"], konto=False)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        states = {c["falt"]: c["state"] for c in response.get_json()["changes"]}
        self.assertEqual(states, {"telefon": "bekraftad", "epost": "aterkallad"})
        member = db.Member.get_by_id(self.member.id)
        self.assertEqual((member.email, member.phone), ("g9001@example.invalid", "0709-777 888"))

    def test_account_notice_goes_to_the_old_address_when_the_email_changes_too(self):  # U8
        receipt = self.submit_changes({"epost": "ny@example.invalid", "konto": NEW_KONTO})
        view = self.changes(receipt["submission_id"]).get_json()
        self.changes(receipt["submission_id"], "/bekrafta", version=view["version"], konto=True)
        self.assertEqual(db.Member.get_by_id(self.member.id).email, "ny@example.invalid")
        (notice,) = self.mails(arsrapport.ACCOUNT_NOTICE)
        self.assertEqual(mail.MAIL_KINDS[notice.kind].login_address(notice.params), "g9001@example.invalid")

    def test_withdraw_revokes_waiting_changes(self):
        self.submit_changes({"telefon": "0709-777 888"})
        report = db.YearlyHerdReport.get()
        response = self.api("POST", f"{REPORT.format(herd='G9001')}/dra-tillbaka", revision=report.revision)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(self.requests()[0].revoked_reason, "tillbaka")

    def test_forwarded_link_in_another_members_browser_writes_only_its_member(self):  # Review Focus 1
        self.link_owner()
        self.login("owner")
        self.open_link("G9002")
        self.ok(herd="G9002", matrikel={"telefon": "0709-777 888"})
        (row,) = self.requests()
        self.assertEqual(row.member_id, self.member2.id)
        self.assertEqual(db.Member.get_by_id(self.member.id).phone, "0709-111 222")

    def test_a_new_main_member_ends_the_confirmation(self):  # D7
        receipt = self.submit_changes({"telefon": "0709-777 888"})
        other = db.Member.create(
            first_name="Ny",
            last_name="Huvudmedlem",
            membership=self.membership(),
            role="familjemedlem",
            email="ny-hm@example.invalid",
        )
        swap_main_member(self.membership(), other, self.admin)
        response = self.changes(receipt["submission_id"])
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "lank_ogiltig"))

    def test_forged_or_demo_token_is_refused(self):
        response = self.client.post("/api/v2/rapport/andringar", json={"token": "1.AAAAAAAAAAAAAAAAAAAAAA"})
        self.assertEqual(response.status_code, 403)
        receipt = self.submit_changes({"telefon": "0709-777 888"})
        with mock.patch.object(settings.service, "demo_instance", True):
            self.assertEqual(self.changes(receipt["submission_id"]).status_code, 403)
        wrong = self.client.post(
            "/api/v2/rapport/andringar", json={"token": mail.link_token("rapport", receipt["submission_id"])}
        )
        self.assertEqual(wrong.status_code, 403)  # a report link's token is no confirmation


class TestLoginReceiptAddress(DetailsTest):
    def test_login_receipt_goes_to_the_current_address(self):  # U8 leaves the login's receipt as it was
        self.link_owner()
        self.login("owner")
        db.Membership.update(membership_status="pending").where(db.Membership.id == self.member.membership_id).execute()
        self.ok()
        (kvitto,) = self.mails("arsrapport.kvitto")
        self.assertEqual(mail.MAIL_KINDS[kvitto.kind].login_address(kvitto.params), "g9001@example.invalid")
        with db.DB_PROXY.atomic():
            set_member_email(db.Member.get_by_id(self.member.id), "ny@example.invalid", self.admin, by="matrikel")
        self.assertEqual(mail.MAIL_KINDS[kvitto.kind].login_address(kvitto.params), "ny@example.invalid")


class TestReviewRound1(DetailsTest):
    """PR #280, review round 1: each test fails without its fix."""

    def submit_changes(self, matrikel, herd="G9001"):
        self.open_link(herd)
        return self.ok(herd=herd, matrikel=matrikel)

    # 1. The link never reveals a stored value
    def test_link_records_every_named_field_and_its_receipt_names_no_write(self):
        with db.DB_PROXY.atomic():
            set_consent(self.membership(), ALL, source="profil", text_version=CONSENT_TEXT_VERSION)
        same = {"telefon": "0709-111 222", "epost": "g9001@example.invalid", "publicering": JA}
        receipt = self.submit_changes(same)
        self.assertEqual([row.kind for row in self.requests()], ["kontakt", "epost", "publicering"])
        self.assertEqual(receipt["matrikel"], [])
        other = self.ok(matrikel={"publicering": NEJ})  # written at once, but the receipt says nothing of it
        self.assertEqual(self.membership().publication_consent, NONE)
        self.assertEqual(other["matrikel"], [])
        view = self.changes(receipt["submission_id"]).get_json()
        done = self.changes(receipt["submission_id"], "/bekrafta", version=view["version"], konto=False).get_json()
        self.assertEqual({c["falt"]: c["state"] for c in done["changes"]}["telefon"], "bekraftad")
        actions = [
            a.payload.get("fields")
            for a in db.MatrikelAudit.select().where(db.MatrikelAudit.action == "kontakt_andrad")
        ]
        self.assertEqual(actions, [])  # the same phone and e-mail write nothing

    # 2. Confirmation is bound to the mailbox the receipt went to
    def test_confirmation_dies_with_the_mailbox_it_went_to(self):
        receipt = self.submit_changes({"telefon": "0709-777 888"})
        token = self.token(receipt["submission_id"])
        with db.DB_PROXY.atomic():  # matrikel staff correct the address: the old one stops counting at once
            set_member_email(db.Member.get_by_id(self.member.id), "ratt@example.invalid", self.admin, by="matrikel")
        response = self.client.post("/api/v2/rapport/andringar", json={"token": token})
        self.assertEqual((response.status_code, response.get_json().get("code")), (403, "lank_ogiltig"))

    # 4. Recipients by the queued member; never an address still waiting
    def test_a_login_receipt_goes_to_its_queued_member(self):
        self.link_owner()
        self.login("owner")
        self.ok()
        (kvitto,) = self.mails("arsrapport.kvitto")
        other = db.Member.create(
            first_name="Ny",
            last_name="Huvudmedlem",
            membership=self.membership(),
            role="familjemedlem",
            email="ny-hm@example.invalid",
        )
        swap_main_member(self.membership(), other, self.admin)
        self.assertEqual(mail.MAIL_KINDS[kvitto.kind].login_address(kvitto.params), "g9001@example.invalid")

    def test_the_account_notice_never_goes_to_a_waiting_address(self):
        db.Membership.update(membership_status="pending").where(db.Membership.id == self.member.membership_id).execute()
        with db.DB_PROXY.atomic():
            set_member_email(db.Member.get_by_id(self.member.id), "vantar@example.invalid", self.admin, by="other")
        resolve = mail.MAIL_KINDS[arsrapport.ACCOUNT_NOTICE].login_address
        params = {"member_id": self.member.id, "membership_id": self.member.membership_id}
        self.assertEqual(resolve(params), "g9001@example.invalid")
        db.MemberPreviousAddress.delete().execute()  # no address counts now: the notice is cancelled
        self.assertIsNone(resolve(params))

    # 3. A direct write revokes an older waiting change of its field; "Det var inte jag" only while waiting
    def test_direct_writes_revoke_older_waiting_link_changes(self):
        self.submit_changes({"telefon": "0709-777 888", "konto": NEW_KONTO, "adress": {"city": "Visby"}})
        self.client.get("/api/logout")
        self.link_owner()
        self.login("owner")
        response = self.client.patch("/api/v2/members/me/contact", json={"phone": "0709-333 444"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.ok(matrikel={"konto": {**NEW_KONTO, "konto": "1111 2222"}})  # logged in, written at once
        states = {member_changes._field(row): (row.revoked_reason, row.confirmed_at) for row in self.requests()}
        self.assertEqual(states["telefon"], ("nyare", None))
        self.assertEqual(states["konto"], ("nyare", None))
        self.assertEqual(states["adress"], (None, None))  # no one wrote the address: it still waits

    def test_not_me_after_expiry_keeps_the_expired_account_status(self):
        receipt = self.submit_changes({"konto": NEW_KONTO})
        token = self.token(receipt["submission_id"])
        self.at(DAY0 + timedelta(days=16))
        self.client.post("/api/v2/rapport/andringar/inte-jag", json={"token": token})
        (row,) = self.requests()
        self.assertIsNone(row.revoked_at)
        flags = next(
            r["flags"] for r in arsrapport.status_view(self.round_, self.gotland.id)["rows"] if r["herd"] == "G9001"
        )
        self.assertEqual((flags["kontobyte_forfoll"], flags["inte_jag"]), (True, False))

    # 5. The version covers the whole account
    def test_an_account_correction_with_the_same_last_digits_is_a_409(self):
        receipt = self.submit_changes({"konto": NEW_KONTO})
        view = self.changes(receipt["submission_id"]).get_json()
        db.Membership.update(bank_account_number="9999-4471 5512").where(
            db.Membership.id == self.member.membership_id
        ).execute()
        response = self.changes(receipt["submission_id"], "/bekrafta", version=view["version"], konto=True)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.membership().bank_account_number, "9999-4471 5512")

    # 6. The confirmation's audit names fields only
    def test_confirmed_email_leaves_no_address_in_the_audit(self):
        receipt = self.submit_changes({"epost": "ny@example.invalid"})
        view = self.changes(receipt["submission_id"]).get_json()
        self.changes(receipt["submission_id"], "/bekrafta", version=view["version"], konto=False)
        (audit,) = db.MatrikelAudit.select().where(db.MatrikelAudit.action == "kontakt_andrad")
        self.assertEqual(audit.payload["fields"], ["email"])
        self.assertNotIn("example.invalid", json.dumps(audit.payload))

    # 8. A change expires at the end of the day the receipt prints
    def test_a_change_holds_to_the_end_of_its_printed_day(self):
        receipt = self.submit_changes({"telefon": "0709-777 888"})
        (kvitto,) = self.mails("arsrapport.kvitto")
        printed = mail.MAIL_KINDS[kvitto.kind].build(kvitto.params)["andringar_senast"]
        self.assertEqual(printed, f"{DAY0 + timedelta(days=14):%Y-%m-%d}")
        token = self.token(receipt["submission_id"])
        self.at(
            datetime.combine(DAY0 + timedelta(days=14), datetime.min.time(), arsrapport.STOCKHOLM)
            + timedelta(hours=23, minutes=59)
        )
        view = self.client.post("/api/v2/rapport/andringar", json={"token": token}).get_json()
        self.assertEqual(view["changes"][0]["state"], "vantar")
        self.at(datetime.combine(DAY0 + timedelta(days=15), datetime.min.time(), arsrapport.STOCKHOLM))
        view = self.client.post("/api/v2/rapport/andringar", json={"token": token}).get_json()
        self.assertEqual(view["changes"][0]["state"], "forfallen")

    # 9. Confirmation never waits for the report row that Dra tillbaka locks
    def test_confirm_does_not_wait_for_the_report_row(self):
        with db.DB_PROXY.atomic():
            set_consent(self.membership(), NONE, source="profil", text_version=CONSENT_TEXT_VERSION)
        receipt = self.submit_changes({"publicering": JA})
        token = self.token(receipt["submission_id"])
        view = self.client.post("/api/v2/rapport/andringar", json={"token": token}).get_json()
        report_id = db.YearlyHerdReport.get().id
        locked, release = threading.Event(), threading.Event()

        def hold():  # as withdraw holds it, FOR UPDATE, until released
            try:
                with db.DB_PROXY.atomic():
                    db.YearlyHerdReport.select().where(db.YearlyHerdReport.id == report_id).for_update().get()
                    locked.set()
                    release.wait(10)
            finally:
                db.DB_PROXY.close()

        holder = threading.Thread(target=hold)
        holder.start()
        self.assertTrue(locked.wait(5))
        try:
            with APP.app_context():
                db.DB_PROXY.execute_sql("SET lock_timeout = '2s'")
                member_changes.confirm(token, account=False, version=view["version"])
        finally:
            db.DB_PROXY.execute_sql("SET lock_timeout = 0")
            release.set()
            holder.join(10)
        self.assertEqual(self.membership().publication_consent, ALL)

    # Review round 2
    def test_a_herd_page_account_fix_revokes_a_waiting_link_change(self):
        sibling = db.Herd.create(genebank=self.gotland, herd="G9003", is_active=True, membership=self.membership())
        self.submit_changes({"konto": NEW_KONTO})
        fix = {"id": sibling.id, "bank_account_number": "5555-1234567", "bank_name": "Rätt bank"}
        self.assertEqual(da.update_herd(fix, self.admin.uuid), {"status": "updated"})  # through the sibling herd
        (row,) = self.requests()
        self.assertEqual(row.revoked_reason, "nyare")

    def test_the_mailbox_is_checked_again_under_the_lock(self):
        receipt = self.submit_changes({"konto": NEW_KONTO})
        token = self.token(receipt["submission_id"])
        view = self.client.post("/api/v2/rapport/andringar", json={"token": token}).get_json()
        lock = arsrapport._lock_matrikel

        def corrected_meanwhile(herd):  # staff replace the address while Bekräfta waits for the lock
            set_member_email(db.Member.get_by_id(self.member.id), "ratt@example.invalid", self.admin, by="matrikel")
            return lock(herd)

        with mock.patch.object(arsrapport, "_lock_matrikel", corrected_meanwhile):
            body = {"token": token, "version": view["version"], "konto": True}
            response = self.client.post("/api/v2/rapport/andringar/bekrafta", json=body)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.membership().bank_account_number, ACCOUNT)

    def test_a_friexemplar_address_gets_no_mail_and_confirms_nothing(self):
        receipt = self.submit_changes({"konto": NEW_KONTO})
        token = self.token(receipt["submission_id"])
        db.Membership.update(membership_status="friexemplar").where(
            db.Membership.id == self.member.membership_id
        ).execute()  # login gives up the address: it is a contact address only
        response = self.client.post("/api/v2/rapport/andringar", json={"token": token})
        self.assertEqual(response.status_code, 403)
        resolve = mail.MAIL_KINDS[arsrapport.ACCOUNT_NOTICE].login_address
        self.assertIsNone(resolve({"member_id": self.member.id, "membership_id": self.member.membership_id}))

    def test_a_receipt_queued_before_the_upgrade_goes_to_its_member(self):
        self.link_owner()
        self.login("owner")
        self.ok()
        (kvitto,) = self.mails("arsrapport.kvitto")
        old = {"submission_id": kvitto.params["submission_id"]}  # as the base branch queued it
        db.MailMessage.update(params=old).where(db.MailMessage.id == kvitto.id).execute()
        other = db.Member.create(
            first_name="Ny",
            last_name="Huvudmedlem",
            membership=self.membership(),
            role="familjemedlem",
            email="ny-hm@example.invalid",
        )
        swap_main_member(self.membership(), other, self.admin)
        db.SchemaHistory.delete().where(db.SchemaHistory.version == 59).execute()
        db.migrate_58_to_59()  # the upgrade names the member the row was queued for
        row = db.MailMessage.get_by_id(kvitto.id)
        self.assertEqual(row.params, {**old, "member_id": self.member.id})
        self.assertEqual(mail.MAIL_KINDS[row.kind].login_address(row.params), "g9001@example.invalid")

    def test_the_report_never_restores_a_withdrawal_made_in_the_profile(self):
        with db.DB_PROXY.atomic():
            set_consent(self.membership(), ALL, source="profil", text_version=CONSENT_TEXT_VERSION)
        self.link_owner()
        self.login("owner")
        self.view()  # the report's tab shows Ja with e-mail
        withdrawn = {"email": False, "text_version": CONSENT_TEXT_VERSION}
        self.assertEqual(self.client.patch("/api/v2/members/me/consent", json=withdrawn).status_code, 200)
        old_tab = {"ja": True, "utom": ["phone"], "text_version": CONSENT_TEXT_VERSION}  # only phone unticked
        response = self.skicka(matrikel={"publicering": old_tab})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(codes(response), {"koharen_andrad"})
        self.assertFalse(self.membership().publication_consent["email"])
        fresh = self.view()["member_details"]["publicering_version"]  # read again, the answer goes
        self.ok(matrikel={"publicering": {**old_tab, "utom": ["phone", "email"], "version": fresh}})
        self.assertEqual(self.membership().publication_consent, {**ALL, "phone": False, "email": False})

    def test_the_details_are_the_authorized_members(self):  # review round 2
        self.link_owner()
        self.login("owner")
        successor = db.Member.create(
            first_name="Ny",
            last_name="Huvudmedlem",
            membership=self.membership(),
            role="familjemedlem",
            email="ny-hm@example.invalid",
            phone="0709-999 999",
        )
        main_member, calls = arsrapport._main_member, []

        def swapped_after_the_first_read(herd):  # the main member is swapped between two reads
            calls.append(herd.id)
            return main_member(herd) if len(calls) == 1 else db.Member.get_by_id(successor.id)

        with mock.patch.object(arsrapport, "_main_member", swapped_after_the_first_read):
            details = self.view()["member_details"]
        self.assertEqual((details["mode"], details["contact"]["phone"]), ("main", "0709-111 222"))
