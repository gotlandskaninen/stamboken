#!/usr/bin/env python3
"""
Tests for the publication consent from paper and its history (5.5, 5.11, fråga 27 and 33, D9, D19): whoever enters a
form writes its answer straight into the matrikel, a No or fewer details at once and a new Yes only when the matrikel
has no later consent change, and every path that changes the consent logs one publication_consent_change row.
Synthetic herds and members only.

isort:skip_file
"""

import csv
from datetime import date, datetime
from datetime import time as clock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.mail as mail
from utils.matrikel import swap_main_member
from utils.members import CONSENT_KEYS, CONSENT_TEXT_VERSION, effective_consent, stored_consent

from tests.test_arsrapport_kontakt import (
    A23,
    NEW_KONTO,
    NEW_PHONE,
    NO_MEMBER,
    REPORT,
    PaperTest,
    later,
    matrikel,
)

ALL, NONE = dict.fromkeys(CONSENT_KEYS, True), dict.fromkeys(CONSENT_KEYS, False)
JA, NEJ = {"ja": True, "utom": []}, {"ja": False, "utom": []}
JA_UTOM_TELEFON = {"ja": True, "utom": ["phone"]}
NAME_ONLY = {**NONE, "name": True}


def _consent(body):
    """A profile PATCH body: the answer and the version of the text the page showed."""
    return {"text_version": CONSENT_TEXT_VERSION, **body}


KOHAREN = "listan över aktiva besättningar som trycks i Koharen."
LINE = f"Du svarade Ja på blanketten: din besättning får stå med i {KOHAREN} Telefonnummer står inte med."
LINE_NEJ = f"Du svarade Nej på blanketten: din besättning står inte med i {KOHAREN}"


class MatrikelTest(PaperTest):
    def stored(self):
        return stored_consent(db.Membership.get_by_id(self.member.membership_id))

    def changes(self):
        return list(db.PublicationConsentChange.select().order_by(db.PublicationConsentChange.id))

    def export(self):
        self.login("admin")
        response = self.client.get("/api/v2/members/koharen-export")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return {row[0]: row[1:] for row in list(csv.reader(response.get_data(as_text=True).splitlines()))[1:]}

    def swap_holder(self):
        membership = self.member.membership
        self.member = db.Member.create(
            membership=membership,
            first_name="Test",
            last_name="Ny",
            role="familjemedlem",
            email="ny@example.test",
            phone="010-000 00 02",
        )
        swap_main_member(membership, self.member, self.manager)
        midnight = datetime(2026, 1, 5, 0, 15, tzinfo=arsrapport.STOCKHOLM)
        db.MatrikelAudit.update(created_at=midnight.astimezone().replace(tzinfo=None)).where(
            db.MatrikelAudit.membership == membership, db.MatrikelAudit.action == "main_member_changed"
        ).execute()

    def profile(self, on, **consent):
        """The main member's own answer on the profile, dated noon `on`: the route stamps the real clock."""
        db.Member.update(user=self.owner.id).where(db.Member.id == self.member.id).execute()
        self.login("owner")
        response = self.client.patch("/api/v2/members/me/consent", json=_consent(consent))
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        row = self.changes()[-1]
        row.at = datetime.combine(on, clock(12), arsrapport.STOCKHOLM)
        row.save()

    def answer(self, item, publicering, signed_on="2026-01-05", received_on="2026-01-12", **fields):
        if signed_on == received_on:
            fields["signed_on_confirmed"] = True
        return self.ok(
            item,
            self.paper(item, matrikel(publicering=publicering), received_on=received_on, signed_on=signed_on, **fields),
        )

    def test_paper_nej_is_written_directly(self):
        self.login("hjalp")
        for revision, before in enumerate(({}, ALL)):
            with self.subTest(before=before):
                db.Membership.update(publication_consent=before).where(
                    db.Membership.id == self.member.membership_id
                ).execute()
                item = self.form(self.helper)
                extra = {"revision": revision, "reason": "Ny blankett"} if revision else {}
                receipt = self.answer(item, NEJ, **extra)
                rid, sid = receipt["report_id"], receipt["submission_id"]
                ms = db.Membership.get_by_id(self.member.membership_id)
                self.assertEqual(effective_consent(ms), NONE)
                self.assertEqual(stored_consent(ms), NONE)  # answered: no longer "ej angivet"
                self.assertEqual((receipt["matrikel"], receipt["warnings"]), (["publicering"], []))
                change = self.changes()[-1]
                self.assertEqual(
                    (change.membership_id, change.value, change.source, change.text_version),
                    (ms.id, NONE, "paper", "2026-11-20"),
                )
                self.assertEqual(
                    (change.user_id, change.report_id, change.submission_id, change.at),
                    (self.helper.id, rid, sid, db.YearlyReportSubmission.get_by_id(sid).created_at),
                )
                (event,) = self.events(item)
                self.assertEqual(event.detail, {"falt": ["publicering"], "hoppade": [], "submission_id": sid})
                _, text = mail.render(A23, arsrapport._kontakt_andrad(self.a23()[-1].params))
                self.assertIn(LINE_NEJ, text)
                self.assertNotIn("står inte med.", text.replace(LINE_NEJ, ""))
        self.assertEqual(len(self.changes()), 2)
        self.assertEqual(self.contact_audits(), [])  # the consent's log is its own table

    def test_paper_answer_to_an_older_text_is_recorded(self):
        """5.11: the old profile's yes ("profil-2025") is no answer to the list of herds, also when it is dated after
        the form: the form's Ja or Nej is a new answer, written with this text's version, never skipped."""
        membership = self.member.membership_id
        self.login("hjalp")
        for revision, (answer, value) in enumerate(((JA, ALL), (NEJ, NONE))):
            with self.subTest(answer=answer):
                db.Membership.update(publication_consent=ALL).where(db.Membership.id == membership).execute()
                old = {"value": ALL, "text_version": "profil-2025", "source": "profil"}
                db.PublicationConsentChange.create(membership=membership, at=datetime(2026, 2, 1), **old)
                extra = {"revision": revision, "reason": "Ny blankett"} if revision else {}
                receipt = self.answer(self.form(self.helper), answer, **extra)
                self.assertEqual((receipt["matrikel"], receipt["warnings"]), (["publicering"], []))
                change = self.changes()[-1]
                self.assertEqual((self.stored(), change.value, change.source), (value, value, "paper"))
                self.assertEqual(change.text_version, CONSENT_TEXT_VERSION)

    def test_paper_ja_is_written_directly_too(self):
        self.login("hjalp")
        item = self.form(self.helper)
        receipt = self.answer(item, JA_UTOM_TELEFON)
        expected = {"name": True, "phone": False, "email": True, "address": True}
        self.assertEqual((self.stored(), receipt["matrikel"]), (expected, ["publicering"]))
        (change,) = self.changes()
        self.assertEqual(
            (change.value, change.source, change.text_version, change.user_id),
            (expected, "paper", "2026-11-20", self.helper.id),
        )
        (row,) = self.a23()
        self.assertEqual(
            row.params,
            {"submission_id": receipt["submission_id"], "konto": 0, "adress": 0, "telefon": 0, "epost": 0}
            | {"publicering": 1},
        )
        _, text = mail.render(A23, arsrapport._kontakt_andrad(row.params))
        self.assertIn(LINE, text)  # the answer and what it leaves out, never the values themselves
        self.assertNotIn("Nej", text)

    def test_consent_skipped_after_a_later_change(self):  # Review Focus 5, Opus 3
        self.at(date(2026, 1, 20))
        self.profile(date(2026, 1, 10), **NONE)
        self.login("man")
        item = self.form(self.manager)
        receipt = self.answer(item, JA, received_on="2026-01-20")
        self.assertEqual((self.stored(), receipt["matrikel"]), (NONE, []))
        self.assertEqual(receipt["warnings"], [later("publicering")])
        self.assertEqual([change.source for change in self.changes()], ["profil"])
        (event,) = self.events(item)
        self.assertEqual((event.detail["falt"], event.detail["hoppade"]), ([], ["publicering"]))
        self.assertEqual(self.a23(), [])

    def test_same_day_profile_answer_limits_paper_ja(self):
        for revision, current in enumerate((NONE, NAME_ONLY)):
            with self.subTest(current=current):
                self.profile(date(2026, 1, 5), **current)
                self.login("man")
                extra = {"revision": revision, "reason": "Ny blankett"} if revision else {}
                receipt = self.answer(self.form(self.manager), JA, **extra)
                self.assertEqual((receipt["matrikel"], receipt["warnings"]), ([], [later("publicering")]))
                self.assertEqual(self.stored(), current)

    def test_reselected_ja_protects_exclusions_in_profile_and_on_paper(self):
        self.profile(date(2026, 1, 1), **NAME_ONLY)
        self.profile(date(2026, 1, 10), **NAME_ONLY)
        self.assertEqual([row.at.astimezone(arsrapport.STOCKHOLM).day for row in self.changes()], [1, 10])
        self.login("man")
        receipt = self.answer(self.form(self.manager), JA)
        self.assertEqual((self.stored(), receipt["warnings"]), (NAME_ONLY, [later("publicering")]))

        just_name = {"ja": True, "utom": ["phone", "email", "address"]}
        self.answer(self.form(self.manager), just_name, signed_on="2026-01-12", revision=1, reason="Ny blankett")
        self.assertEqual([row.source for row in self.changes()], ["profil", "profil", "paper"])
        receipt = self.answer(self.form(self.manager), JA, signed_on="2026-01-11", revision=2, reason="Äldre blankett")
        self.assertEqual((self.stored(), receipt["warnings"]), (NAME_ONLY, [later("publicering")]))

    def test_historical_paper_ja_needs_a_current_holder_signature(self):
        self.login("man")
        self.at(date(2026, 1, 8))
        receipt = self.answer(self.form(self.manager), JA, signed_on="2026-01-02", received_on="2026-01-08")
        submission = db.YearlyReportSubmission.get_by_id(receipt["submission_id"])
        # Reproduce history written before the guard: the entry on the 8th followed a swap on the 5th.
        start = datetime(2026, 1, 5, 0, 15, tzinfo=arsrapport.STOCKHOLM)
        db.MatrikelAudit.create(
            membership=self.member.membership_id,
            action="main_member_changed",
            payload={},
            created_at=start.astimezone().replace(tzinfo=None),
        )
        for signed, listed in (
            ("2026-01-02", False),
            ("2026-01-05", False),
            (None, False),
            ("2026-01-99", False),
            ("2026-01-08", False),
            ("2026-01-06", True),
        ):
            with self.subTest(signed=signed):
                submission.data = {**submission.data, "signed_on": signed}
                submission.save(only=[db.YearlyReportSubmission.data])
                self.assertEqual("G9001" in self.export(), listed)
        db.PublicationConsentChange.update(submission_id=None).where(
            db.PublicationConsentChange.submission_id == submission.id
        ).execute()
        self.assertNotIn("G9001", self.export())

    def test_undated_form_after_holder_change_cannot_authorize_export(self):
        self.swap_holder()
        for fields in ({}, {"signed_on": "2026-01-12", "revision": 1, "reason": "Äldre formulär"}):
            self.login("man")
            item = self.form(self.manager)
            body = self.paper(item, matrikel(publicering=JA), **fields)
            receipt = self.ok(item, body)
            retry = {**body, "signed_on": "2026-01-12"}
            self.assertEqual(self.ok(item, retry), receipt)
            self.assertEqual(self.skicka(item, {**retry, "signed_on_confirmed": True}).status_code, 409)
            self.assertIsNone(db.YearlyReportSubmission.get_by_id(receipt["submission_id"]).data["signed_on"])
            self.assertEqual((self.stored(), receipt["warnings"]), ({}, [later("publicering")]))
            self.assertNotIn("G9001", self.export())

        # A supplied signature may genuinely be the receipt day, after the swap.
        self.login("man")
        self.answer(self.form(self.manager), JA, signed_on="2026-01-12", revision=2, reason="Datum kontrollerat")
        self.assertIn("G9001", self.export())

    def test_same_day_form_cannot_replace_holder_contact(self):
        self.swap_holder()
        self.profile(date(2026, 1, 5), **ALL)
        self.login("man")
        item = self.form(self.manager)
        contact = matrikel(publicering=NEJ, telefon=NEW_PHONE, epost="tidigare@example.test")
        body = self.paper(item, contact, signed_on="2026-01-05")
        self.assertTrue(self.skicka(item, body, route="torrkorning").json["ok"])
        receipt = self.ok(item, body)
        self.assertEqual(receipt["warnings"], [later("telefon"), later("e-post"), later("publicering")])
        self.assertEqual(receipt["matrikel"], [])
        self.assertEqual(self.export()["G9001"][1:3], [self.member.phone, self.member.email])

    def test_a_form_signed_before_the_holder_changed_never_counts(self):
        """An answer belongs to the holder who gave it: a form signed on or before the day the main member changed is
        the former holder's, so its Ja never reaches the export with the new holder's details (5.11)."""
        self.swap_holder()
        self.login("man")
        receipt = self.answer(self.form(self.manager), JA, received_on="2026-01-12")
        self.assertEqual((self.stored(), receipt["matrikel"], receipt["warnings"]), ({}, [], [later("publicering")]))
        self.assertEqual(self.changes(), [])

    def test_a_repeated_nej_is_recorded_and_wins_over_an_older_ja(self):
        """An explicit Nej always wins over an older Ja: saved again unchanged, from the profile or on paper, it is
        recorded, so a form with a Ja signed before it cannot expand the answer when it is entered later."""
        db.Membership.update(publication_consent=NONE).where(db.Membership.id == self.member.membership_id).execute()
        first = {"value": NONE, "text_version": CONSENT_TEXT_VERSION, "source": "profil"}
        db.PublicationConsentChange.create(membership=self.member.membership_id, at=datetime(2025, 6, 1), **first)
        self.profile(date(2026, 1, 10), **NONE)
        self.assertEqual([change.at.date() for change in self.changes()], [date(2025, 6, 1), date(2026, 1, 10)])
        self.login("man")
        receipt = self.answer(self.form(self.manager), JA, received_on="2026-01-12")
        self.assertEqual((self.stored(), receipt["matrikel"], receipt["warnings"]), (NONE, [], [later("publicering")]))

        # On paper: a Nej signed 12 January is recorded, and a Ja signed on the 11th entered after it waits
        nej = self.answer(self.form(self.manager), NEJ, signed_on="2026-01-12", revision=1, reason="Ny blankett")
        self.assertEqual(nej["matrikel"], ["publicering"])
        receipt = self.answer(self.form(self.manager), JA, signed_on="2026-01-11", revision=2, reason="Äldre blankett")
        self.assertEqual((self.stored(), receipt["warnings"]), (NONE, [later("publicering")]))

    def test_second_herds_nej_survives_a_correction_for_the_first_herd(self):
        db.Herd.update(membership=self.member.membership_id).where(db.Herd.id == self.g9002.id).execute()
        (rabbit,) = self.rabbits(self.g9002, 1)
        self.login("man")
        self.at(date(2026, 1, 10))
        self.answer(self.form(self.manager), NEJ, signed_on="2026-01-01", received_on="2026-01-10")

        self.at(date(2026, 1, 11))
        item = self.form(self.manager, self.g9002)
        body = self.paper(item, matrikel(publicering=NEJ), rabbit, received_on="2026-01-11", signed_on="2026-01-08")
        second = self.ok(item, body, self.g9002.herd)

        self.at(date(2026, 1, 12))
        receipt = self.answer(self.form(self.manager), JA, signed_on="2026-01-05", revision=1, reason="Rättelse")
        self.assertEqual((self.stored(), receipt["warnings"]), (NONE, [later("publicering")]))
        self.assertEqual([row.value for row in self.changes()], [NONE, NONE])
        self.assertEqual(self.changes()[-1].submission_id, second["submission_id"])

    def test_fewer_details_go_at_once_after_a_later_change(self):  # Jonas 2026-11-14, fråga 27
        self.at(date(2026, 1, 20))
        self.profile(date(2026, 1, 10), **ALL)
        self.login("man")
        item = self.form(self.manager)
        receipt = self.answer(item, NEJ, received_on="2026-01-20")
        self.assertEqual((self.stored(), receipt["matrikel"], receipt["warnings"]), (NONE, ["publicering"], []))

        # Fewer and more at once: the fewer go now, the more wait for the member (here: phone off, e-mail not on)
        self.profile(date(2026, 1, 12), name=True, phone=True)
        self.login("man")
        again = self.form(self.manager)
        receipt = self.answer(again, JA_UTOM_TELEFON, received_on="2026-01-20", revision=1, reason="Ny blankett")
        self.assertEqual(self.stored(), {"name": True, "phone": False, "email": False, "address": False})
        self.assertEqual((receipt["matrikel"], receipt["warnings"]), (["publicering"], [later("publicering")]))
        self.assertEqual([change.source for change in self.changes()], ["profil", "paper", "profil", "paper"])

    def test_change_from_paper_corrects_its_own_consent(self):  # I1
        self.login("man")
        item = self.form(self.manager)
        self.assertEqual(self.answer(item, NEJ)["matrikel"], ["publicering"])  # written 2026-01-15, after the form

        # Ändra from paper with the same form's date: the report's own write is no later change
        again = self.form(self.manager)
        receipt = self.answer(again, JA, revision=1, reason="Fel ruta")
        self.assertEqual((self.stored(), receipt["matrikel"], receipt["warnings"]), (ALL, ["publicering"], []))

        # A change from the profile after the form's date still wins
        self.profile(date(2026, 1, 14), **NONE)
        self.login("man")
        third = self.form(self.manager)
        receipt = self.answer(third, JA, revision=2, reason="Fel igen")
        self.assertEqual((self.stored(), receipt["warnings"]), (NONE, [later("publicering")]))

    def both(self, item, publicering, telefon, **fields):
        """A form that answers about Koharen and gives a phone number."""
        body = self.paper(item, matrikel(publicering=publicering, telefon=telefon), **fields)
        return self.ok(item, body)

    def phone(self):
        return db.Member.get_by_id(self.member.id).phone

    def test_older_form_does_not_undo_a_newer_one(self):  # review Important 1, ruling (b)
        self.login("man")
        newer = self.form(self.manager)
        receipt = self.both(newer, NEJ, NEW_PHONE, received_on="2026-01-12", signed_on="2026-01-10")
        self.assertEqual(receipt["matrikel"], ["telefon", "publicering"])

        # Ändra with an older form signed 2 January: the newer form's writes are later changes
        older = self.form(self.manager)
        fields = {"received_on": "2026-01-12", "signed_on": "2026-01-02", "revision": 1, "reason": "Gammal blankett"}
        receipt = self.both(older, JA, "0709-333 444", **fields)
        self.assertEqual((receipt["matrikel"], receipt["warnings"]), ([], [later("telefon"), later("publicering")]))
        self.assertEqual((self.stored(), self.phone()), (NONE, NEW_PHONE))
        self.assertEqual([change.value for change in self.changes()], [NONE])

    def test_typo_fix_with_the_same_date_still_goes_through(self):  # I1 under ruling (b)
        self.login("man")
        first = self.form(self.manager)
        typo = self.both(first, NEJ, "0709-777 889", signed_on="2026-01-05")
        self.assertEqual(typo["matrikel"], ["telefon", "publicering"])

        fixed = self.form(self.manager)
        receipt = self.both(fixed, JA, NEW_PHONE, signed_on="2026-01-05", revision=1, reason="Fel ruta")
        self.assertEqual((receipt["matrikel"], receipt["warnings"]), (["telefon", "publicering"], []))
        self.assertEqual((self.stored(), self.phone()), (ALL, NEW_PHONE))

    def test_a_withdrawn_reports_writes_are_not_its_own(self):  # ruling (b)
        self.login("man")
        first = self.form(self.manager)
        self.assertEqual(self.both(first, NEJ, NEW_PHONE)["matrikel"], ["telefon", "publicering"])
        path = REPORT.format(herd="G9001")
        withdrawn = self.client.post(f"{path}/dra-tillbaka", json={"revision": 1, "reason": "Fel besättning"})
        self.assertEqual(withdrawn.status_code, 200, withdrawn.get_data(as_text=True))

        # A new report with a form of the same date: the withdrawn report's writes count as later changes
        second = self.form(self.manager)
        receipt = self.both(second, JA, "0709-333 444")
        self.assertEqual((receipt["matrikel"], receipt["warnings"]), ([], [later("telefon"), later("publicering")]))
        self.assertEqual((self.stored(), self.phone()), (NONE, NEW_PHONE))

    def test_one_event_and_one_mail_for_the_whole_form(self):
        self.login("man")
        item = self.form(self.manager)
        contact = matrikel(konto=NEW_KONTO, telefon=NEW_PHONE, publicering=JA_UTOM_TELEFON)
        receipt = self.ok(item, self.paper(item, contact))
        self.assertEqual(receipt["matrikel"], ["konto", "telefon", "publicering"])
        (event,) = self.events(item)
        self.assertEqual(event.detail["falt"], ["konto", "telefon", "publicering"])
        (row,) = self.a23()
        flags = {field: row.params[field] for field in arsrapport.PAPER_FIELDS}
        self.assertEqual(flags, {"konto": 1, "adress": 0, "telefon": 1, "epost": 0, "publicering": 1})
        _, text = mail.render(A23, arsrapport._kontakt_andrad(row.params))
        for line in ("Ditt konto för genbanksstödet har ändrats.", "Ditt telefonnummer har ändrats.", LINE):
            self.assertIn(line, text)
        (audit,) = self.contact_audits()  # the contact columns only; the consent has its own row
        self.assertEqual(audit.payload["fields"], ["bank_account_number", "bank_name", "phone"])
        (change,) = self.changes()
        self.assertEqual(change.value, {"name": True, "phone": False, "email": True, "address": True})

    def test_matrikel_is_never_stored_with_the_report(self):
        self.login("man")
        item = self.form(self.manager)
        body = self.paper(item, matrikel(telefon=NEW_PHONE, publicering=NEJ))
        path = REPORT.format(herd="G9001")
        draft = {"data": body, "updated_at": None, "submission_key": body["submission_key"], "revision": None}
        refused = self.client.put(f"{path}/utkast?post={item.id}", json=draft)  # the draft never takes it
        self.assertEqual(refused.status_code, 400, refused.get_data(as_text=True))
        self.assertEqual(db.YearlyReportDraft.select().count(), 0)

        receipt = self.ok(item, body)
        submission = db.YearlyReportSubmission.get_by_id(receipt["submission_id"])
        self.assertNotIn("matrikel", submission.data)
        view = self.client.get(path)
        self.assertEqual(view.status_code, 200, view.get_data(as_text=True))
        self.assertNotIn("matrikel", view.json["report"]["submitted"])
        self.assertEqual(db.YearlyReportDraft.select().count(), 0)

    def test_profile_records_consent_changes(self):  # D9; the profile asks the form's question (5.11)
        db.Member.update(user=self.owner.id).where(db.Member.id == self.member.id).execute()
        self.login("owner")
        for consent in ({"phone": True}, {"phone": True}, {"name": True, "phone": False}):
            response = self.client.patch("/api/v2/members/me/consent", json=_consent(consent))
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        rows = [
            (change.membership_id, change.value, change.source, change.text_version, change.user_id)
            + (change.report_id, change.submission_id)
            for change in self.changes()
        ]
        membership = self.member.membership_id
        self.assertEqual(
            rows,
            [  # the unchanged second answer adds none
                (membership, {"phone": True}, "profil", CONSENT_TEXT_VERSION, self.owner.id, None, None),
                (membership, {"phone": False, "name": True}, "profil", CONSENT_TEXT_VERSION, self.owner.id, None, None),
            ],
        )

    def test_consent_needs_a_main_member(self):
        headless = db.Herd.create(genebank=self.gotland, herd="G9003", is_active=True)
        (rabbit,) = self.rabbits(headless, 1)
        self.login("man")
        item = self.form(self.manager, headless)
        response = self.skicka(item, self.paper(item, matrikel(publicering=NEJ), rabbit), "G9003")
        self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
        self.assertEqual(
            response.json["refusals"], [{"individual_id": None, "code": "ingen_huvudmedlem", "message": NO_MEMBER}]
        )
        self.assertEqual(self.changes(), [])

    def test_answer_shape_is_checked(self):
        self.login("man")
        item = self.form(self.manager)
        for wrong in (
            True,
            {"ja": "ja", "utom": []},
            {"utom": []},
            {"ja": True, "utom": ["name"]},
            {"ja": True, "utom": "phone"},
            {"ja": True, "utom": [{}]},
            {"ja": True, "utom": [], "namn": True},
        ):
            with self.subTest(wrong=wrong):
                response = self.skicka(item, self.paper(item, matrikel(publicering=wrong)), route="torrkorning")
                self.assertEqual((response.status_code, response.json["field"]), (400, "matrikel"))
