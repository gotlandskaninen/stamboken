#!/usr/bin/env python3
"""
Tests for contact changes from paper (5.5, fråga 25 and 34, D6–D8, D19): whoever enters a form saves its new account,
address, phone and e-mail straight into the matrikel, for that form's membership only, without reading the stored
values; the stored account shows only its last two digits. Every change is logged, and the member gets Å23.
Synthetic herds, members, accounts and addresses only.

isort:skip_file
"""

import json
from datetime import date, datetime, timedelta, timezone
from datetime import time as clock
from unittest import mock

import utils.arsrapport as arsrapport
import utils.data_access as da
import utils.database as db
import utils.inbox as inbox
import utils.inbox_purge as inbox_purge
import utils.mail as mail
from herdbook import APP
from playhouse.shortcuts import model_to_dict
from utils.matrikel import anonymize_person, set_member_email, swap_main_member

from tests.arsrapport_fixtures import ArsrapportTest
from tests.inbox_fixtures import QUALITY

NOW = datetime.combine(date(2026, 1, 15), clock(12), arsrapport.STOCKHOLM)
A23 = "kontakt.andrad_fran_blankett"
REPORT = "/api/v2/arsrapport/besattning/{herd}/2025"
EMAIL, PHONE = "g9001@example.invalid", "0709-111 222"
OLD_ACCOUNT = "8327-4471 5512"  # G9001's, ends in 12
OLD_DIGITS = ("8327", "4471", "5512")
NEW_KONTO = {"clearing": "9420", "konto": "4618 0377", "bank": "Nya banken"}  # stored as 9420-46180377
NEW_PHONE = "0709-777 888"
NEW_ADRESS = {"address": " Nya gatan 2 ", "postal_code": "62355", "city": "Visby"}
NO_MEMBER = "Besättningen saknar huvudmedlem i matrikeln, så ändringen kan inte sparas."
EMAIL_REFUSAL = "E-postadressen kan inte användas. Kontrollera den med medlemmen."
WRITTEN = (
    db.HerdTracking,
    db.Weight,
    db.YearlyHerdReport,
    db.YearlyReportSubmission,
    db.InboxOperation,
    db.InboxEvent,
    db.MatrikelAudit,
    db.MemberChangeRequest,
    db.MailMessage,
)


def matrikel(**fields):
    return {"adress": None, "telefon": None, "epost": None, "konto": None, "publicering": None, **fields}


def codes(response):
    return {refusal["code"] for refusal in response.get_json()["refusals"]}


def later(field):
    return {
        "individual_id": None,
        "code": "senare_andring",
        "message": f"Matrikeln har ändrats efter blankettens datum ({field}). Fråga medlemmen.",
    }


class PaperTest(ArsrapportTest):
    """G9001 with its main member and one rabbit, the clock at NOW, and the helpers to enter a form for it."""

    def setUp(self):
        super().setUp()
        self.at(NOW)
        self.round_ = self.round(2025)
        self.h = db.Herd.create(genebank=self.gotland, herd="G9001", herd_name="Testbesättning", is_active=True)
        self.g9002 = db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.member = self.main_member(self.h, EMAIL)
        self.other = self.main_member(self.g9002, "g9002@example.invalid")
        for member, address, account, bank in (
            (self.member, "Gamla vägen 1", OLD_ACCOUNT, "Gamla banken"),
            (self.other, "Andra vägen 3", "6161-9393 7474", None),
        ):
            db.Member.update(phone=PHONE).where(db.Member.id == member.id).execute()
            db.Membership.update(
                address=address, postal_code="621 41", city="Slite", bank_account_number=account, bank_name=bank
            ).where(db.Membership.id == member.membership_id).execute()
        (self.rabbit,) = self.rabbits(self.h, 1)

    def form(self, taker, herd=None):
        """A taken item for `herd` (G9001) with one arsblankett page; the owner uploaded it."""
        item, documents = inbox.create_upload(
            self.owner, herd or self.h, None, [("inkorg/original/0.jpg", "1".rjust(64, "0"), QUALITY)]
        )
        for document in documents:
            document.doc_type = "arsblankett"
            document.save()
        inbox.take(item, taker, over=False)
        return db.InboxItem.get_by_id(item.id)

    def paper(self, item, contact=None, rabbit=None, received_on="2026-01-12", **fields):
        """A paper body for `item`, the rabbit kvar, with `contact` as its matrikel."""
        return self.body(
            self.kvar(rabbit or self.rabbit, vikt=2.8),
            inbox_item_id=item.id,
            received_on=received_on,
            health=None,
            matrikel=contact,
            **fields,
        )

    def skicka(self, item, body, herd="G9001", route="skicka"):
        return self.client.post(f"{REPORT.format(herd=herd)}/{route}?post={item.id}", json=body)

    def ok(self, item, body, herd="G9001"):
        response = self.skicka(item, body, herd)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def counts(self):
        return [model.select().count() for model in WRITTEN]

    def a23(self):
        return list(db.MailMessage.select().where(db.MailMessage.kind == A23).order_by(db.MailMessage.id))

    def events(self, item):
        query = db.InboxEvent.select().where(db.InboxEvent.item == item.id, db.InboxEvent.kind == "matrikel_andrad")
        return list(query)

    def account(self, member=None):
        """The support account of `member`'s (G9001's) membership: (type, number, bank)."""
        ms = db.Membership.get_by_id(db.Member.get_by_id((member or self.member).id).membership_id)
        return ms.bank_account_type, ms.bank_account_number, ms.bank_name

    def contact_audits(self):
        return list(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "kontakt_andrad"))

    def matrikel_rows(self, member):
        """The rows a contact change may write: the membership, its persons and its herds, and the herds' audit."""
        membership_id = db.Member.get_by_id(member.id).membership_id
        herds = db.Herd.select().where(db.Herd.membership == membership_id).order_by(db.Herd.id)
        persons = db.Member.select().where(db.Member.membership == membership_id).order_by(db.Member.id)
        audits = db.AuditLog.select().where(
            db.AuditLog.table_name == "herd", db.AuditLog.record_id.in_([str(herd.id) for herd in herds])
        )
        return (
            model_to_dict(db.Membership.get_by_id(membership_id), recurse=False),
            [model_to_dict(person, recurse=False) for person in persons],
            [model_to_dict(herd, recurse=False) for herd in herds],
            audits.count(),
        )


class KontaktTest(PaperTest):
    # Case 9: the account

    def test_helper_saves_a_new_account(self):
        item = self.form(self.helper)
        self.login("hjalp")
        body = self.paper(item, matrikel(konto=NEW_KONTO))
        receipt = self.ok(item, body)
        sid = receipt["submission_id"]

        self.assertEqual(self.account(), ("bankkonto", "9420-46180377", "Nya banken"))
        herd = db.Herd.get_by_id(self.h.id)
        self.assertEqual((herd.bank_account_number, herd.bank_name), (None, None))  # never the herd's (migration 58)
        self.assertEqual((receipt["matrikel"], receipt["warnings"]), (["konto"], []))

        (row,) = self.a23()
        flags = {"konto": 1, "adress": 0, "telefon": 0, "epost": 0, "publicering": 0}
        self.assertEqual(
            (row.recipient_kind, row.recipient_id, row.params, row.ref_type, row.ref_id),
            ("member", self.member.id, {"submission_id": sid, **flags}, "yearly_report_submission", sid),
        )
        self.assertEqual(
            (row.herd_id, row.genebank_id, row.dedupe_key, row.created_by_id, row.priority, row.category),
            (self.h.id, self.gotland.id, f"{A23}:{sid}", self.helper.id, 0, "T"),
        )
        subject, text = mail.render(A23, arsrapport._kontakt_andrad(row.params))
        self.assertEqual(subject, "Dina uppgifter har ändrats från din pappersblankett")
        for line in (
            "Ditt konto för genbanksstödet har ändrats. Det nya kontot slutar på ••77.",
            "Ändringen gjordes när din årsrapport för G9001 matades in. Stämmer det inte? Kontakta genbanksansvarig "
            "genom att svara på det här mejlet.",
        ):
            self.assertIn(line, text)
        for secret in ("9420", "4618", "adress", "telefon", "e-post"):
            self.assertNotIn(secret, text)

        # The log: the helper, the item and the field names, never a value, and no copy in the herd's audit_log.
        (event,) = self.events(item)
        self.assertEqual(
            (event.user_id, event.detail), (self.helper.id, {"falt": ["konto"], "hoppade": [], "submission_id": sid})
        )
        (audit,) = self.contact_audits()
        self.assertEqual(
            (audit.actor_id, audit.payload),
            (
                self.helper.id,
                {
                    "person_id": self.member.id,
                    "fields": ["bank_account_type", "bank_account_number", "bank_name"],
                    "source": "paper",
                    "inbox_item_id": item.id,
                    "submission_id": sid,
                },
            ),
        )
        herd_audit = db.AuditLog.select().where(
            db.AuditLog.table_name == "herd", db.AuditLog.record_id == str(self.h.id), db.AuditLog.operation == "UPDATE"
        )
        self.assertFalse(herd_audit.where(db.AuditLog.changed_fields.contains_any("bank_account_number")).exists())
        self.assertEqual(self.ok(item, body), receipt)  # the retry reads the same back
        self.assertEqual(len(self.a23()), 1)

    def test_bankgiro_and_plusgiro_have_no_clearing_number(self):  # Jonas 2026-11-18, drift #53
        self.login("man")
        for revision, (konto, stored) in enumerate(
            (
                ({"typ": "bankgiro", "konto": "123 4567", "bank": "Banken"}, ("bankgiro", "123-4567", "Banken")),
                ({"typ": "plusgiro", "konto": "12 34 56-7"}, ("plusgiro", "123456-7", None)),
                ({"typ": "bankkonto", **NEW_KONTO}, ("bankkonto", "9420-46180377", "Nya banken")),
            )
        ):
            with self.subTest(konto["typ"]):
                item = self.form(self.manager)
                extra = {"revision": revision, "reason": "Ny blankett"} if revision else {}
                self.assertEqual(self.ok(item, self.paper(item, matrikel(konto=konto), **extra))["matrikel"], ["konto"])
                self.assertEqual(self.account(), stored)

    def test_account_box_rules_are_checked(self):
        item = self.form(self.manager)
        self.login("man")
        for konto in (
            {"typ": "bankgiro", "clearing": "8327", "konto": "1234567"},  # no clearing number for a bankgiro
            {"typ": "plusgiro", "clearing": "8327", "konto": "1234567"},
            {"typ": "bankgiro", "konto": "123456"},  # 7–8 digits
            {"typ": "bankgiro", "konto": "123456789"},
            {"typ": "plusgiro", "konto": "1"},  # 2–8 digits
            {"typ": "plusgiro", "konto": "123456789"},
            {"typ": "bankkonto", "konto": "46180377"},  # a bankkonto needs its clearing number
            {"typ": "swish", "konto": "1234567"},
        ):
            with self.subTest(konto=konto):
                dry = self.skicka(item, self.paper(item, matrikel(konto=konto)), route="torrkorning")
                self.assertEqual(dry.status_code, 200, dry.get_data(as_text=True))
                self.assertEqual(codes(dry), {"konto_ogiltigt"})
        self.assertEqual(self.account(), (None, OLD_ACCOUNT, "Gamla banken"))

    def test_same_digits_as_another_type_is_a_new_account(self):
        """A stored type keeps a bankgiro and a plusgiro of the same digits apart; a stored NULL type does not."""
        db.Membership.update(bank_account_type="plusgiro", bank_account_number="1234567-8").where(
            db.Membership.id == self.member.membership_id
        ).execute()
        item = self.form(self.manager)
        self.login("man")
        receipt = self.ok(item, self.paper(item, matrikel(konto={"typ": "bankgiro", "konto": "1234-5678"})))
        self.assertEqual(receipt["matrikel"], ["konto"])
        self.assertEqual(self.account(), ("bankgiro", "1234-5678", None))

    def test_self_uploaded_item_is_logged(self):  # beslut 4, Fable 1, P24 reversed
        db.Member.update(email=None).where(db.Member.id == self.member.id).execute()
        self.login("hjalp")
        uploaded = self.upload(herd="G9001")
        self.assertEqual(uploaded.status_code, 201, uploaded.get_data(as_text=True))
        item_id, page = uploaded.json["item"]["id"], uploaded.json["documents"][0]["id"]
        self.assertEqual(self.post(f"/{item_id}/ta").status_code, 200)
        typed = self.client.patch(f"/api/v2/inkorg/{item_id}/dokument/{page}", json={"doc_type": "arsblankett"})
        self.assertEqual(typed.status_code, 200, typed.get_data(as_text=True))
        item = db.InboxItem.get_by_id(item_id)
        notices, mails = {n.id for n in db.Notice.select()}, {m.id for m in db.MailMessage.select()}

        self.ok(item, self.paper(item, matrikel(konto=NEW_KONTO, epost="forsta@example.invalid")))
        self.assertEqual(self.account()[1], "9420-46180377")
        self.assertEqual(db.Member.get_by_id(self.member.id).email, "forsta@example.invalid")
        (event,) = self.events(item)
        self.assertEqual((event.user_id, event.detail["falt"]), (self.helper.id, ["konto", "epost"]))
        self.assertEqual(db.MemberChangeRequest.select().count(), 0)

        # No Å23 and no notice of the change: only the queue's own "klar" to the helper (P56), and the receipt,
        # which goes to the first e-mail (P47).
        new_notices = [(n.user_id, n.kind) for n in db.Notice.select() if n.id not in notices]
        self.assertEqual(new_notices, [(self.helper.id, "klar")])
        new_mails = sorted(
            (m.kind, m.recipient_kind, m.recipient_id) for m in db.MailMessage.select() if m.id not in mails
        )
        self.assertEqual(
            new_mails, [("arsrapport.kvitto", "member", self.member.id), ("inlasning.klar", "user", self.helper.id)]
        )

    def test_view_shows_only_the_account_end(self):
        item = self.form(self.helper)
        self.login("hjalp")
        response = self.client.get(f"{REPORT.format(herd='G9001')}?post={item.id}")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.json["item"]["account_end"], "12")
        text = response.get_data(as_text=True)
        for secret in (*OLD_DIGITS, "Gamla vägen", "Slite", "621 41", PHONE, EMAIL, "Gamla banken"):
            self.assertNotIn(secret, text)

    def test_helper_reads_no_other_account(self):
        def keys(node):
            if isinstance(node, dict):
                return set(node) | {key for value in node.values() for key in keys(value)}
            return {key for value in node for key in keys(value)} if isinstance(node, list) else set()

        self.login("hjalp")
        self.assertEqual(self.client.get("/api/v2/members?search=Test").status_code, 403)
        herd = self.client.get("/api/herd/G9002")
        self.assertEqual(herd.status_code, 200, herd.get_data(as_text=True))
        self.assertNotIn("bank_account_number", herd.json or {})
        self.assertNotIn("6161", herd.get_data(as_text=True))

        self.login("man")
        found = self.client.get("/api/v2/members?search=Test")
        self.assertEqual(found.status_code, 200, found.get_data(as_text=True))
        self.assertEqual(found.json["total"], 2)
        self.assertEqual({key for key in keys(found.json) if "bank" in key or "account" in key}, set())
        for secret in (*OLD_DIGITS, "6161", "9393"):
            self.assertNotIn(secret, found.get_data(as_text=True))

    def test_manager_sees_only_the_account_end(self):
        manager = db.User.get_by_id(self.manager.id)
        self.assertEqual(db.Herd.get_by_id(self.h.id).filtered_dict(manager)["bank_account_number"], "••12")

    # Scope, recipients and the log

    def test_only_the_forms_membership_is_written(self):
        item = self.form(self.manager)
        self.login("man")
        others = self.matrikel_rows(self.other)
        contact = matrikel(konto=NEW_KONTO, adress=NEW_ADRESS, telefon=NEW_PHONE, epost="ny@example.invalid")
        receipt = self.ok(item, self.paper(item, contact))
        self.assertEqual(receipt["matrikel"], ["konto", "adress", "telefon", "epost"])
        self.assertEqual(self.matrikel_rows(self.other), others)
        member = db.Member.get_by_id(self.member.id)
        self.assertEqual(
            (member.phone, member.email, self.account()[1]), (NEW_PHONE, "ny@example.invalid", "9420-46180377")
        )

    def test_changed_email_goes_to_the_old_address(self):  # case 9
        item = self.form(self.manager)
        self.login("man")
        receipt = self.ok(item, self.paper(item, matrikel(epost=" Ny@Example.invalid ", telefon=NEW_PHONE)))
        submission = db.YearlyReportSubmission.get_by_id(receipt["submission_id"])
        self.assertEqual(db.Member.get_by_id(self.member.id).email, "ny@example.invalid")

        (request,) = db.MemberChangeRequest.select()
        self.assertEqual(
            (request.member_id, request.submission_id, request.kind, request.value, request.access_code_id),
            (self.member.id, submission.id, "epost", {"old": EMAIL, "new": "ny@example.invalid"}, None),
        )
        self.assertEqual(
            (request.created_at, request.old_confirmed_at, request.confirmed_at, request.expires_at),
            (submission.created_at, submission.created_at, submission.created_at, None),
        )
        (row,) = self.a23()
        self.assertEqual((row.recipient_kind, row.recipient_id), ("email_change_old", request.id))
        self.assertEqual(mail.RECIPIENT_KINDS["email_change_old"](row.recipient_id).address, EMAIL)
        (besked,) = db.MailMessage.select().where(db.MailMessage.kind == "kontakt.epost_besked")
        self.assertEqual(mail.RECIPIENT_KINDS[besked.recipient_kind](besked.recipient_id).address, EMAIL)
        self.assertEqual((row.params["epost"], row.params["telefon"], row.params["konto"]), (0, 1, 0))
        _, text = mail.render(A23, arsrapport._kontakt_andrad(row.params))
        self.assertNotIn("Din e-postadress har ändrats.", text)
        self.assertIn("Ditt telefonnummer har ändrats.", text)
        self.assertNotIn("ny@example.invalid", text)

        self.assertIsNotNone(db.Member.get_by_id(self.member.id).email_login_from)
        previous = db.MemberPreviousAddress.get(db.MemberPreviousAddress.member == self.member.id)
        self.assertEqual(previous.address, EMAIL)
        self.assertIsNotNone(previous.login_until)
        # The matrikel audit keeps the e-mail change and the other fields by name.
        (audit,) = self.contact_audits()
        self.assertEqual((audit.actor_id, audit.membership_id), (self.manager.id, self.member.membership_id))
        self.assertEqual(
            audit.payload,
            {
                "person_id": self.member.id,
                "fields": ["phone", "email"],
                "source": "paper",
                "inbox_item_id": item.id,
                "submission_id": submission.id,
                "before": {"email": EMAIL},
                "after": {"email": "ny@example.invalid"},
            },
        )
        # the receipt reads the address when it goes, so it reaches the new one
        (kvitto,) = db.MailMessage.select().where(db.MailMessage.kind == "arsrapport.kvitto")
        self.assertEqual(mail.RECIPIENT_KINDS["member"](kvitto.recipient_id).address, "ny@example.invalid")

    def test_email_only_uses_the_address_change_notice(self):
        item = self.form(self.helper)
        self.login("hjalp")
        receipt = self.ok(item, self.paper(item, matrikel(epost="ny@example.invalid")))
        self.assertEqual(receipt["matrikel"], ["epost"])
        self.assertEqual(self.a23(), [])
        (besked,) = db.MailMessage.select().where(db.MailMessage.kind == "kontakt.epost_besked")
        self.assertEqual(mail.RECIPIENT_KINDS[besked.recipient_kind](besked.recipient_id).address, EMAIL)

    def test_no_email_no_mail(self):
        db.Member.update(email=None).where(db.Member.id == self.member.id).execute()
        item = self.form(self.manager)
        self.login("man")
        self.ok(item, self.paper(item, matrikel(telefon=NEW_PHONE)))
        (event,) = self.events(item)
        self.assertEqual(event.detail["falt"], ["telefon"])
        self.assertEqual(self.a23(), [])

        # A first e-mail is saved, still without Å23: there is no old address to tell.
        again = self.form(self.manager)
        first = matrikel(epost="forsta@example.invalid")
        self.ok(again, self.paper(again, first, revision=1, reason="Ny blankett"))
        self.assertEqual(db.Member.get_by_id(self.member.id).email, "forsta@example.invalid")
        self.assertEqual(self.events(again)[0].detail["falt"], ["epost"])
        self.assertEqual((self.a23(), db.MemberChangeRequest.select().count()), ([], 0))

    def test_no_change_no_event_and_no_mail(self):
        same = matrikel(
            konto={"clearing": "83 27", "konto": "4471.5512", "bank": "Annan bank"},  # the same digits
            adress={"address": "Gamla vägen 1", "postal_code": "62141", "city": "Slite"},
            telefon=f" {PHONE} ",
            epost="G9001@Example.invalid",
        )
        blank = matrikel(
            konto={"clearing": " ", "konto": "", "bank": "Nya banken"},
            adress={"address": "", "postal_code": None, "city": " "},
            telefon=" ",
            epost="",
        )
        self.login("man")
        for revision, (name, contact) in enumerate((("same", same), ("blank", blank), ("none", None))):
            with self.subTest(name):
                item = self.form(self.manager)
                before = self.matrikel_rows(self.member)
                extra = {"revision": revision, "reason": "Ny blankett"} if revision else {}
                receipt = self.ok(item, self.paper(item, contact, **extra))
                self.assertEqual((receipt["matrikel"], receipt["warnings"]), ([], []))
                self.assertEqual(self.matrikel_rows(self.member), before)
                self.assertEqual((self.events(item), self.a23(), self.contact_audits()), ([], [], []))

    def real_clock(self):
        """Today on the real clock, the round open around it: neither matrikel_audit nor audit_log follows at()."""
        self.at(datetime.now(timezone.utc))
        today = arsrapport.today()
        db.YearlyReportRound.update(
            start_date=today - timedelta(days=30), deadline=today, end_date=today + timedelta(days=30)
        ).where(db.YearlyReportRound.id == self.round_.id).execute()
        return today

    def later_account(self):
        """An account written on the herd page (the legacy herd PATCH), which lands on the membership and its log."""
        return da.update_herd({"id": self.h.id, "bank_account_number": "1111-2222333"}, self.admin.uuid, legacy=True)

    def test_later_herd_audit_from_before_migration_58_still_counts(self):  # D19
        """An account change in a herd's audit_log, from before the account moved to the membership: on any herd of
        the membership, since the account a sibling herd held may be the one the membership got."""
        today = self.real_clock()
        sibling = db.Herd.create(genebank=self.gotland, herd="G9005", membership=self.member.membership_id)
        db.AuditLog.create(
            table_name="herd", record_id=str(sibling.id), operation="UPDATE", changed_fields=["bank_account_number"],
            old_data={}, new_data={},
        )  # fmt: skip
        item = self.form(self.manager)
        self.login("man")
        signed = (today - timedelta(days=10)).isoformat()
        body = self.paper(item, matrikel(konto=NEW_KONTO), received_on=today.isoformat(), signed_on=signed)
        receipt = self.ok(item, body)
        self.assertEqual((receipt["matrikel"], receipt["warnings"]), ([], [later("konto")]))
        self.assertEqual(self.account()[1], OLD_ACCOUNT)

    def test_later_matrikel_change_wins(self):  # Review Focus 5, D19
        today = self.real_clock()  # audit_log cannot be backdated
        # A phone through the profile and an account on the herd page, both now
        db.Member.update(user=self.owner.id).where(db.Member.id == self.member.id).execute()
        self.login("owner")
        patched = self.client.patch("/api/v2/members/me/contact", json={"phone": "0709-555 666"})
        self.assertEqual(patched.status_code, 200, patched.get_data(as_text=True))
        self.assertEqual(self.later_account(), {"status": "updated"})

        item = self.form(self.manager)
        self.login("man")
        contact = matrikel(konto=NEW_KONTO, telefon=NEW_PHONE, adress=NEW_ADRESS)
        signed = (today - timedelta(days=10)).isoformat()
        body = self.paper(item, contact, received_on=today.isoformat(), signed_on=signed)
        receipt = self.ok(item, body)
        self.assertEqual(receipt["matrikel"], ["adress"])
        self.assertEqual(receipt["warnings"], [later("konto"), later("telefon")])
        self.assertEqual(self.events(item)[0].detail["hoppade"], ["konto", "telefon"])
        member = db.Member.get_by_id(self.member.id)
        self.assertEqual((member.phone, self.account()[1]), ("0709-555 666", "1111-2222333"))
        self.assertEqual(db.Membership.get_by_id(self.member.membership_id).address, "Nya gatan 2")
        self.assertEqual([row.params["konto"] for row in self.a23()], [0])

        # A change on the form's own date is not later: a form signed today writes them.
        again = self.form(self.manager)
        body = self.paper(again, contact, received_on=today.isoformat(), revision=1, reason="Ny blankett")
        receipt = self.ok(again, body)
        self.assertEqual((receipt["matrikel"], receipt["warnings"]), (["konto", "telefon"], []))
        member = db.Member.get_by_id(self.member.id)
        self.assertEqual((member.phone, self.account()[1]), (NEW_PHONE, "9420-46180377"))

    def test_change_from_paper_corrects_its_own_typo(self):  # I1
        today = self.real_clock()
        signed, received = (today - timedelta(days=10)).isoformat(), today.isoformat()
        item = self.form(self.manager)
        self.login("man")
        typo = matrikel(konto={**NEW_KONTO, "konto": "4618 0378"}, telefon="0709-777 889")
        first = self.ok(item, self.paper(item, typo, received_on=received, signed_on=signed))
        self.assertEqual(first["matrikel"], ["konto", "telefon"])
        self.assertEqual(self.account()[1], "9420-46180378")

        # Ändra from paper with the same form's date: the report's own writes are no later change.
        again = self.form(self.manager)
        fixed = matrikel(konto=NEW_KONTO, telefon=NEW_PHONE)
        body = self.paper(again, fixed, received_on=received, signed_on=signed, revision=1, reason="Fel konto")
        receipt = self.ok(again, body)
        self.assertEqual((receipt["matrikel"], receipt["warnings"]), (["konto", "telefon"], []))
        member = db.Member.get_by_id(self.member.id)
        self.assertEqual((member.phone, self.account()[1]), (NEW_PHONE, "9420-46180377"))
        self.assertEqual([(row.params["konto"], row.params["telefon"]) for row in self.a23()], [(1, 1), (1, 1)])

        # A change from another source after the form's date still wins.
        self.assertEqual(self.later_account(), {"status": "updated"})
        third = self.form(self.manager)
        body = self.paper(third, typo, received_on=received, signed_on=signed, revision=2, reason="Fel igen")
        receipt = self.ok(third, body)
        self.assertEqual((receipt["matrikel"], receipt["warnings"]), (["telefon"], [later("konto")]))
        self.assertEqual(self.account()[1], "1111-2222333")

    def test_matrikel_is_checked_in_the_dry_run(self):
        item = self.form(self.manager)
        self.login("man")
        bad = matrikel(telefon="1" * 51, epost="a@b", konto={"clearing": "123", "konto": "4567890", "bank": None})
        body = self.paper(item, bad)
        dry = self.skicka(item, body, route="torrkorning")
        self.assertEqual(dry.status_code, 200, dry.get_data(as_text=True))
        self.assertFalse(dry.json["ok"])
        self.assertEqual(codes(dry), {"telefon_ogiltig", "epost_ogiltig", "konto_ogiltigt"})
        before, rows = self.counts(), self.matrikel_rows(self.member)
        response = self.skicka(item, body)
        self.assertEqual(
            (response.status_code, codes(response)), (422, {"telefon_ogiltig", "epost_ogiltig", "konto_ogiltigt"})
        )
        self.assertEqual((self.counts(), self.matrikel_rows(self.member)), (before, rows))

        # The shape is the body's: a 400 that names the field
        for wrong in ({"telefon": 5}, {"konto": "9420-46180377"}, {"adress": {"gata": "x"}}, {"namn": "x"}):
            with self.subTest(wrong=wrong):
                response = self.skicka(item, self.paper(item, wrong), route="torrkorning")
                self.assertEqual((response.status_code, response.json["field"]), (400, "matrikel"))

    def test_unavailable_email_is_a_neutral_dry_run_refusal(self):
        item = self.form(self.helper)
        self.login("hjalp")
        body = self.paper(item, matrikel(epost=self.other.email.upper()))
        before = self.counts()
        dry = self.skicka(item, body, route="torrkorning")
        self.assertEqual(dry.status_code, 200, dry.get_data(as_text=True))
        refusal = {"individual_id": None, "code": "epost_kan_inte_anvandas", "message": EMAIL_REFUSAL}
        self.assertEqual(dry.json, {"ok": False, "refusals": [refusal], "warnings": []})
        self.assertEqual(self.counts(), before)

        # A later change means the paper address will be skipped, so it need not be available.
        db.MatrikelAudit.create(
            membership=self.member.membership_id,
            action="person_updated",
            payload={"fields": ["email"]},
            created_at=datetime(2026, 1, 14, 12),
        )
        self.assertTrue(self.skicka(item, body, route="torrkorning").json["ok"])
        receipt = self.ok(item, body)
        self.assertEqual((receipt["matrikel"], receipt["warnings"]), ([], [later("e-post")]))

    def test_address_claimed_after_dry_run_is_an_email_conflict(self):
        item = self.form(self.helper)
        self.login("hjalp")
        new_email = "ny@example.invalid"
        body = self.paper(item, matrikel(epost=new_email, telefon=NEW_PHONE))
        self.assertTrue(self.skicka(item, body, route="torrkorning").json["ok"])
        set_member_email(self.other, new_email, self.manager, by="matrikel")
        before = self.counts()
        response = self.skicka(item, body)
        self.assertEqual(response.status_code, 409, response.get_data(as_text=True))
        self.assertEqual(
            (response.json["field"], response.json["code"], response.json["detail"]),
            ("epost", "epost_kan_inte_anvandas", EMAIL_REFUSAL),
        )
        self.assertEqual(self.counts(), before)
        member = db.Member.get_by_id(self.member.id)
        self.assertEqual((member.email, member.phone), (EMAIL, PHONE))

    def test_herd_without_main_member(self):
        headless = db.Herd.create(genebank=self.gotland, herd="G9003", is_active=True)
        (rabbit,) = self.rabbits(headless, 1)
        self.login("man")
        for name, herd, rabbit_ in (("none", headless, rabbit), ("anonymized", self.h, self.rabbit)):
            with self.subTest(name):
                if name == "anonymized":
                    anonymize_person(db.Member.get_by_id(self.member.id), db.User.get_by_id(self.admin.id))
                item = self.form(self.manager, herd)
                before = self.counts()
                response = self.skicka(item, self.paper(item, matrikel(telefon=NEW_PHONE), rabbit_), herd.herd)
                self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
                self.assertEqual(
                    response.json["refusals"],
                    [{"individual_id": None, "code": "ingen_huvudmedlem", "message": NO_MEMBER}],
                )
                self.assertEqual(self.counts(), before)
                self.ok(item, self.paper(item, None, rabbit_), herd.herd)

    def test_main_member_is_read_under_the_lock(self):
        membership = db.Membership.get_by_id(self.member.membership_id)
        new_main = db.Member.create(
            first_name="Ny",
            last_name="Huvudmedlem",
            email="ny9001@example.invalid",
            membership=membership,
            role="familjemedlem",
        )
        item = self.form(self.manager)
        self.login("man")
        body = self.paper(item, matrikel(telefon=NEW_PHONE, adress=NEW_ADRESS))
        self.assertTrue(self.skicka(item, body, route="torrkorning").json["ok"])
        swap_main_member(membership, new_main, db.User.get_by_id(self.admin.id))  # between the dry run and Skicka
        receipt = self.ok(item, body)
        # I2: the swap came after the form's date, so its phone may be the old main member's and is skipped; the
        # membership's address is written, and Å23 goes to the main member read under the lock.
        self.assertEqual((receipt["matrikel"], receipt["warnings"]), (["adress"], [later("telefon")]))
        self.assertEqual(
            (db.Member.get_by_id(new_main.id).phone, db.Member.get_by_id(self.member.id).phone), (None, PHONE)
        )
        self.assertEqual(db.Membership.get_by_id(membership.id).address, "Nya gatan 2")
        a23 = [(row.recipient_kind, row.recipient_id, row.params["adress"]) for row in self.a23()]
        self.assertEqual(a23, [("member", new_main.id, 1)])

    def test_herd_is_locked_before_the_account_check(self):  # Opus 5, D19: a later account change still wins
        item = self.form(self.manager)
        self.login("man")
        statements, original = [], db.DATABASE.execute_sql

        def spy(sql, *args, **kwargs):
            statements.append(sql)
            return original(sql, *args, **kwargs)

        with mock.patch.object(db.DATABASE, "execute_sql", side_effect=spy):
            self.assertEqual(self.ok(item, self.paper(item, matrikel(konto=NEW_KONTO)))["matrikel"], ["konto"])

        def first(*parts):
            return next((n for n, sql in enumerate(statements) if all(part in sql for part in parts)), None)

        lock = first('FROM "herd"', "FOR NO KEY UPDATE")
        self.assertIsNotNone(lock)
        self.assertLess(lock, first('FROM "audit_log"'))  # later_fields reads the account's changes under it
        self.assertLess(lock, first('UPDATE "membership"', "bank_account_number"))  # the account is the membership's
        self.assertIsNone(first('UPDATE "herd"'))

    def test_profile_contact_change_is_logged(self):  # D19
        db.Member.update(user=self.owner.id).where(db.Member.id == self.member.id).execute()
        self.login("owner")
        for _ in range(2):  # the second changes nothing and logs nothing
            response = self.client.patch("/api/v2/members/me/contact", json={"phone": "0709-555 666"})
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        (audit,) = self.contact_audits()
        self.assertEqual(
            (audit.actor_id, audit.membership_id, audit.payload),
            (
                self.owner.id,
                self.member.membership_id,
                {"person_id": self.member.id, "fields": ["phone"], "source": "profil"},
            ),
        )

    def test_erasure_deletes_change_requests(self):  # Fable 8
        item = self.form(self.manager)
        self.login("man")
        self.ok(item, self.paper(item, matrikel(epost="ny@example.invalid", telefon=NEW_PHONE)))
        (request,) = db.MemberChangeRequest.select()
        anonymize_person(db.Member.get_by_id(self.member.id), db.User.get_by_id(self.admin.id))
        self.assertEqual(db.MemberChangeRequest.select().count(), 0)
        self.assertIsNone(mail.RECIPIENT_KINDS["email_change_old"](request.id))  # a queued Å23 is cancelled
        (audit,) = self.contact_audits()
        self.assertEqual(
            (audit.payload["before"], audit.payload["after"]), ({"email": "[borttagen]"}, {"email": "[borttagen]"})
        )

    def test_change_request_is_purged_30_days_after_it_was_confirmed(self):  # Opus 7, spec 6
        item = self.form(self.manager)
        self.login("man")
        self.ok(item, self.paper(item, matrikel(epost="ny@example.invalid")))
        (request,) = db.MemberChangeRequest.select()
        self.assertEqual(request.confirmed_at, NOW)
        rule = inbox_purge.purge_change_requests
        self.assertIn(rule, inbox_purge.RULES)  # the nightly inbox_purge runs it
        self.assertEqual(rule(NOW + timedelta(days=30)), 0)
        self.assertEqual(rule(NOW + timedelta(days=30, seconds=1)), 1)
        self.assertFalse(db.MemberChangeRequest.select().exists())

    def test_address_writes_all_three_fields(self):  # Codex 13
        item = self.form(self.manager)
        self.login("man")
        for wrong in ({**NEW_ADRESS, "postal_code": "6235"}, {**NEW_ADRESS, "address": "x" * 201}):
            with self.subTest(wrong=wrong):
                response = self.skicka(item, self.paper(item, matrikel(adress=wrong)), route="torrkorning")
                self.assertEqual(codes(response), {"adress_ogiltig"})
        receipt = self.ok(item, self.paper(item, matrikel(adress=NEW_ADRESS)))
        self.assertEqual(receipt["matrikel"], ["adress"])
        membership = db.Membership.get_by_id(self.member.membership_id)
        self.assertEqual(
            (membership.address, membership.postal_code, membership.city), ("Nya gatan 2", "623 55", "Visby")
        )
        (audit,) = self.contact_audits()
        expected = {"person_id": self.member.id, "fields": ["address", "postal_code", "city"], "source": "paper"}
        ids = {"inbox_item_id": item.id, "submission_id": receipt["submission_id"]}
        self.assertEqual(audit.payload, expected | ids)

    def test_same_key_other_contact_is_409(self):  # D21
        item = self.form(self.manager)
        self.login("man")
        body = self.paper(item, matrikel(konto=NEW_KONTO, telefon=NEW_PHONE))
        self.ok(item, body)
        before = self.counts()
        response = self.skicka(item, {**body, "matrikel": matrikel(konto=NEW_KONTO, telefon="0709-999 000")})
        self.assertEqual((response.status_code, response.json["detail"]), (409, arsrapport.KEY_TAKEN))
        self.assertEqual(self.counts(), before)
        self.assertEqual(db.Member.get_by_id(self.member.id).phone, NEW_PHONE)
        row = json.dumps(db.YearlyReportSubmission.select().dicts().get(), default=str)
        for secret in ("777 888", "46180377", "4618 0377", "999 000"):
            self.assertNotIn(secret, row)

    def test_failure_at_the_contact_mail_rolls_back(self):  # Codex 15
        item = self.form(self.manager)
        self.login("man")
        body = self.paper(item, matrikel(konto=NEW_KONTO, telefon=NEW_PHONE, epost="ny@example.invalid"))
        draft = {"data": arsrapport.stored_body(body), "updated_at": None, "submission_key": body["submission_key"]}
        saved = self.client.put(
            f"{REPORT.format(herd='G9001')}/utkast?post={item.id}", json={**draft, "revision": None}
        )
        self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))

        def everything():
            pages = db.InboxDocument.select().where(db.InboxDocument.item == item.id).order_by(db.InboxDocument.id)
            stored = db.YearlyReportDraft.get()
            return (
                self.counts(),
                self.matrikel_rows(self.member),
                db.InboxItem.get_by_id(item.id).state,
                [(page.done_at, page.purge_after) for page in pages],
                (stored.updated_at, stored.data),
            )

        real, before = arsrapport.enqueue_mail, everything()

        def failing(kind, *args, **kwargs):
            if kind == A23:
                raise RuntimeError("the mail queue is gone")
            return real(kind, *args, **kwargs)

        with (
            mock.patch.object(arsrapport, "enqueue_mail", side_effect=failing),
            mock.patch.dict(APP.config, {"PROPAGATE_EXCEPTIONS": False}),
        ):
            response = self.skicka(item, body)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(everything(), before)
