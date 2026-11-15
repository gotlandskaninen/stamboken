"""The mails to a buyer outside the association (utils.buyer_mail). Synthetic data only.

isort:skip_file
"""

import os
import re
import subprocess
import sys
import textwrap
import uuid
from datetime import date, datetime, timezone
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.database as db  # noqa: E402
import utils.mail as mail  # noqa: E402
import utils.settings as settings  # noqa: E402
from herdbook import limiter  # noqa: E402
from utils import buyer_contact, buyer_mail  # noqa: E402
from utils.buyer_mail import ERASE_PURPOSE, queue_buyer_mails  # noqa: E402
from utils.herd_tracking import (  # noqa: E402
    HerdTrackingConflict,
    attach_buyer,
    correct_herd_tracking,
    delete_buyer_contacts,
    record_herd_tracking,
)

from tests.test_buyer_contact import BUYER, NAME, SALE_DATE, BuyerBase  # noqa: E402
from tests.test_inbox_purge import PurgeTest  # noqa: E402
from tests.test_mail_queue import HOST, SECRET, FakeRelay  # noqa: E402

EMAIL = "zelda@example.org"
WITH_EMAIL = {**BUYER, "email": EMAIL, "contact_consent": True}
PDF = b"%PDF-1.7\nsynthetic certificate"


class BuyerMailTest(BuyerBase):
    def setUp(self):
        super().setUp()
        for patch in (
            mock.patch.multiple(settings.mail, mode="live", link_secret=SECRET, allowlist=[]),
            mock.patch.object(settings.service, "host", f"https://{HOST}"),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        db.Individual.update(name="Stjärna").where(db.Individual.id == self.rabbit.id).execute()

    def mails(self, kind=None):
        rows = db.MailMessage.select().order_by(db.MailMessage.id)
        return [row for row in rows if kind is None or row.kind == kind]

    def send(self):
        """One sender run against a fake relay; the messages it sent."""
        relay = FakeRelay()
        with mock.patch.object(mail.smtplib, "SMTP", relay):
            mail.send_pending()
        return [msg for msg, _sender, _to in relay.sent]

    def text(self, kind="kopare.information"):
        """(subject, body) of the queued mail as it would go now, without sending it."""
        (row,) = self.mails(kind)
        variables = mail.MAIL_KINDS[kind].build(row.params)
        variables.pop("attachments", None)
        return mail.render(kind, variables)


class TestInformationQueued(BuyerMailTest):
    def test_no_mail_without_an_email(self):
        self._sale({**BUYER, "phone": "070-000 00 00", "contact_consent": True})
        self.assertEqual(self.mails(), [])

    def test_the_sale_queues_it_to_the_buyer(self):
        sale = self._sale(WITH_EMAIL)
        (row,) = self.mails()
        self.assertEqual(
            (row.kind, row.recipient_kind, row.recipient_id, row.genebank_id, row.priority, row.category),
            ("kopare.information", "buyer_contact", sale.holder_contact_id, self.genebanks[0].id, 1, "T"),
        )
        self.assertEqual(row.params, {"buyer_contact_id": sale.holder_contact_id, "individual_id": self.rabbit.id})

    def test_an_address_the_queue_cannot_send_to_is_refused_with_the_sale(self):
        for typed in ("zelda @example.org", "zelda@example.org, per@example.org", "Zelda <zelda@example.org>", "zelda"):
            with self.subTest(typed):
                response = self._sell(buyer={**WITH_EMAIL, "email": typed})
                self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
                self.assertIn("e-postadress", response.get_data(as_text=True))
        self.assertEqual((self.mails(), db.BuyerContact.select().count()), ([], 0))
        self._sale(
            {**WITH_EMAIL, "email": "  Zelda@Example.ORG "}
        )  # spaces around it are the typing's, not the address's

    def test_a_rolled_back_sale_queues_nothing(self):
        with self.assertRaises(RuntimeError), db.DB_PROXY.atomic():
            record_herd_tracking(self.rabbit, self.gx1, SALE_DATE, "TRANSFER", self.owner, buyer=WITH_EMAIL)
            self.assertEqual(len(self.mails()), 1)
            raise RuntimeError("the sale's transaction fails")
        self.assertEqual((self.mails(), db.BuyerContact.select().count()), ([], 0))

    def test_a_late_sale_entered_as_a_correction_mails_its_buyer(self):
        record_herd_tracking(self.rabbit, self.herds[1], "2022-01-01", "TRANSFER", self.manager)
        event = {"kind": "TRANSFER", "date": SALE_DATE, "herd": "GX1", "buyer": WITH_EMAIL}
        (sale,) = correct_herd_tracking(self.rabbit, self.manager, None, [], [event])
        (row,) = self.mails()
        self.assertEqual((row.kind, row.recipient_id), ("kopare.information", sale.holder_contact_id))

    def test_a_corrected_sale_does_not_mail_the_buyer_twice(self):
        sale = self._sale({**WITH_EMAIL, "membership_optin": True})
        contact = db.BuyerContact.get_by_id(sale.holder_contact_id)
        event = {"kind": "TRANSFER", "date": "2021-07-01", "herd": "GX1"}  # no buyer: the sale's own is carried over
        correct_herd_tracking(self.rabbit, self.manager, None, [sale.id], [event], "Fel datum")
        self.assertEqual(self._latest().holder_contact_id, contact.id)  # the correction kept the buyer
        queue_buyer_mails(contact, self._latest())  # and if anything queued again, the dedupe_key holds
        self.assertEqual(
            [(row.kind, row.recipient_id) for row in self.mails()],
            [("kopare.information", contact.id), ("kopare.medlemskap", contact.id)],
        )

    def invitations(self, status=None):
        return [row.recipient_id for row in self.mails("kopare.medlemskap") if status in (None, row.status)]

    def test_a_correction_that_replaces_the_buyer_sends_one_invitation(self):
        optin = {**WITH_EMAIL, "membership_optin": True}
        sale = self._sale(optin)
        event = {"kind": "TRANSFER", "date": "2021-07-01", "herd": "GX1", "buyer": optin}  # the buyer typed again
        (written,) = correct_herd_tracking(self.rabbit, self.manager, None, [sale.id], [event], "Fel datum")
        self.assertIsNone(db.BuyerContact.get_or_none(db.BuyerContact.id == sale.holder_contact_id))
        self.assertEqual(self.invitations("cancelled"), [sale.holder_contact_id])  # the old buyer's, erased with it
        self.assertEqual(self.invitations("queued"), [written.holder_contact_id])
        self.assertEqual(len(self.send()), 2)  # the new buyer's notice and invitation

    def test_two_sales_to_one_address_each_hold_an_invitation_and_one_goes(self):
        optin = {**WITH_EMAIL, "membership_optin": True}
        first = self._sale(optin)
        second = record_herd_tracking(self.individuals[1], self.gx1, SALE_DATE, "TRANSFER", self.manager, buyer=optin)
        self.assertEqual(self.invitations("queued"), [first.holder_contact_id, second.holder_contact_id])
        subjects = [msg["Subject"] for msg in self.send()]
        self.assertEqual(len([s for s in subjects if s.startswith("Välkommen")]), 1)
        self.assertEqual(len(subjects), 3)  # a notice for each sale
        self.assertEqual(sorted(row.status for row in self.mails("kopare.medlemskap")), ["cancelled", "sent"])

    def test_one_buyer_going_leaves_the_other_sales_invitation(self):
        optin = {**WITH_EMAIL, "membership_optin": True}
        first = self._sale(optin)
        second = record_herd_tracking(self.individuals[1], self.gx1, SALE_DATE, "TRANSFER", self.manager, buyer=optin)
        delete_buyer_contacts([first.holder_contact_id], "forsaljning_ogiltig", None)
        self.assertEqual(self.invitations("queued"), [second.holder_contact_id])
        self.assertEqual(len(self.send()), 2)  # the second sale's notice and the invitation

    def test_a_corrected_address_leaves_the_other_sales_invitation(self):
        optin = {**WITH_EMAIL, "membership_optin": True}
        first = self._sale(optin)
        second = record_herd_tracking(self.individuals[1], self.gx1, SALE_DATE, "TRANSFER", self.manager, buyer=optin)
        event = {"kind": "TRANSFER", "date": "2021-07-01", "herd": "GX1", "buyer": {**optin, "email": "ny@example.org"}}
        (written,) = correct_herd_tracking(self.rabbit, self.manager, None, [first.id], [event], "Fel adress")
        self.assertEqual(self.invitations("queued"), [second.holder_contact_id, written.holder_contact_id])

    def test_a_correction_while_the_invitation_is_being_sent_sends_the_new_buyers(self):
        optin = {**WITH_EMAIL, "membership_optin": True}
        sale = self._sale(optin)
        claimed = db.MailMessage.update(status="sending", claim_token=uuid.uuid4())
        claimed.where(db.MailMessage.kind == "kopare.medlemskap").execute()
        event = {"kind": "TRANSFER", "date": "2021-07-01", "herd": "GX1", "buyer": optin}
        (written,) = correct_herd_tracking(self.rabbit, self.manager, None, [sale.id], [event], "Fel datum")
        self.assertEqual(self.invitations("cancelled"), [sale.holder_contact_id])  # lost its claim: not sent
        self.assertEqual(self.invitations("queued"), [written.holder_contact_id])

    def test_a_buyer_typed_again_after_the_invitation_went_is_a_new_buyer(self):
        """The erased buyer's mails forget the address (forget_recipient), so nothing says it has had one."""
        optin = {**WITH_EMAIL, "membership_optin": True}
        sale = self._sale(optin)
        self.assertEqual(len(self.send()), 2)
        event = {"kind": "TRANSFER", "date": "2021-07-01", "herd": "GX1", "buyer": optin}
        correct_herd_tracking(self.rabbit, self.manager, None, [sale.id], [event], "Fel datum")
        self.assertEqual(len(self.send()), 2)  # both mails again, as for any new buyer

    def test_a_correction_never_mails_a_buyer_who_was_removed(self):
        sale = self._sale(WITH_EMAIL)
        delete_buyer_contacts([sale.holder_contact_id], "invandning", None)
        mails = len(self.mails())
        event = {"kind": "TRANSFER", "date": "2021-07-01", "herd": "GX1", "buyer": WITH_EMAIL}
        with self.assertRaises(HerdTrackingConflict):
            correct_herd_tracking(self.rabbit, self.manager, None, [sale.id], [event], "Fel datum")
        self.assertEqual((len(self.mails()), db.BuyerContact.select().count()), (mails, 0))

    def test_a_buyer_a_proof_adds_to_a_sale_registered_without_one_is_mailed(self):
        sale = record_herd_tracking(self.rabbit, self.gx1, SALE_DATE, "TRANSFER", self.manager)  # the legacy form
        with db.DB_PROXY.atomic():
            contact = attach_buyer(sale, {**WITH_EMAIL, "membership_optin": True}, self.manager)
        self.assertEqual(
            [(row.kind, row.recipient_id) for row in self.mails()],
            [("kopare.information", contact.id), ("kopare.medlemskap", contact.id)],
        )

    def test_the_dedupe_key_holds_no_address(self):
        self._sale({**WITH_EMAIL, "membership_optin": True})
        for row in self.mails():
            self.assertNotIn("@", row.dedupe_key)
            self.assertNotIn(mail.address_hash(EMAIL), row.dedupe_key)


class TestInformationSent(BuyerMailTest):
    def setUp(self):
        super().setUp()
        self.contact_id = self._sale(WITH_EMAIL).holder_contact_id

    def certificate(self):
        """A current v2 certificate with a synthetic PDF where the download route reads it."""
        relative = f"certifikat/v2/{uuid.uuid4()}.pdf"
        path = os.path.join("uppladdningar", relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as out:
            out.write(PDF)
        self.addCleanup(os.remove, path)
        db.DigitalCertificateV2.create(individual=self.rabbit, issued_by=self.admin, file_path=relative, checksum="0")

    def test_with_the_certificate_as_a_pdf_and_the_erase_link(self):
        self.certificate()
        (msg,) = self.send()
        self.assertEqual(msg["To"], EMAIL)
        self.assertEqual(msg["Subject"], "Din kanin Stjärna (G1-2111) är registrerad hos Föreningen Gotlandskaninen")
        body = msg.get_body(("plain",)).get_content()
        self.assertTrue(body.startswith(f"Hej {NAME},\n\ndu har köpt kaninen Stjärna, G1-2111. Säljaren"), body)
        self.assertIn("föreningens register över genbankens kaniner. Kaninens genbanksintyg ligger som bilaga.\n", body)
        (pdf,) = msg.iter_attachments()
        self.assertEqual(
            (pdf.get_filename(), pdf.get_content_type(), pdf.get_content()),
            ("genbanksintyg-G1-2111.pdf", "application/pdf", PDF),
        )
        link = re.search(r"även namn och ort: https://stambok\.example\.org/kopare/ta-bort#(\S+)\n", body)
        self.assertEqual(mail.verify_link(ERASE_PURPOSE, link.group(1)), self.contact_id)
        self.assertIn("Du kan också skriva till dataskydd@gotlandskaninen.se.\n\nHälsningar\n", body)
        self.assertEqual(self.mails()[0].status, "sent")

    def test_without_a_digital_certificate_no_attachment_and_no_word_of_one(self):
        (msg,) = self.send()
        body = msg.get_body(("plain",)).get_content()
        self.assertIn("föreningens register över genbankens kaniner.\n\nFöreningen Gotlandskaninen sparar", body)
        self.assertNotIn("bilaga", body)
        self.assertEqual(list(msg.iter_attachments()), [])

    def test_a_certificate_that_cannot_be_fetched_is_tried_again_not_left_out(self):
        db.Individual.update(digital_certificate=9001).where(db.Individual.id == self.rabbit.id).execute()
        with mock.patch("utils.cert_acess.download_certificate_s3", side_effect=OSError("S3 is down")):
            self.assertEqual(self.send(), [])
        (row,) = self.mails()
        self.assertEqual((row.status, row.attempts), ("queued", 1))
        self.assertIn("bygget misslyckades", row.last_error)

    def test_the_third_attempt_sends_without_a_certificate_it_cannot_fetch(self):
        db.Individual.update(digital_certificate=9001).where(db.Individual.id == self.rabbit.id).execute()
        with mock.patch("utils.cert_acess.download_certificate_s3", side_effect=OSError("S3 is down")):
            self.assertEqual(self.send(), [])  # attempt 1
            db.MailMessage.update(attempts=1, next_attempt_at=datetime(2000, 1, 1)).execute()
            self.assertEqual(self.send(), [])  # attempt 2: still tried again
            self.assertEqual(self.mails()[0].status, "queued")
            db.MailMessage.update(attempts=2, next_attempt_at=datetime(2000, 1, 1)).execute()
            (msg,) = self.send()  # attempt 3
        body = msg.get_body(("plain",)).get_content()
        self.assertNotIn("bilaga", body)
        self.assertIn("föreningens register över genbankens kaniner.\n\nFöreningen Gotlandskaninen sparar", body)
        self.assertEqual(list(msg.iter_attachments()), [])
        (row,) = self.mails()
        self.assertEqual(
            (row.status, row.attempts, row.last_error), ("sent", 3, "skickat utan bilaga: intyget kunde inte hämtas")
        )

    def test_log_mode_keeps_the_note_about_a_missing_certificate(self):
        db.Individual.update(digital_certificate=9001).where(db.Individual.id == self.rabbit.id).execute()
        db.MailMessage.update(attempts=2).execute()
        with (
            mock.patch.object(settings.mail, "mode", "log"),
            mock.patch("utils.cert_acess.download_certificate_s3", side_effect=OSError("S3 is down")),
        ):
            mail.send_pending()
        (row,) = self.mails()
        self.assertEqual((row.status, row.last_error), ("logged", "skickat utan bilaga: intyget kunde inte hämtas"))

    def test_a_certificate_that_works_leaves_last_error_empty_on_a_late_attempt(self):
        self.certificate()
        db.MailMessage.update(attempts=2).execute()
        (msg,) = self.send()
        self.assertEqual(len(list(msg.iter_attachments())), 1)
        (row,) = self.mails()
        self.assertEqual((row.status, row.last_error), ("sent", None))

    def test_the_date_is_the_rows_purge_at_in_stockholm(self):
        cases = (
            (datetime(2031, 11, 13, 23, 30, tzinfo=timezone.utc), "14 november 2031"),  # after midnight in Sweden
            (datetime(2030, 3, 1, 10, 0, tzinfo=timezone.utc), "1 mars 2030"),
        )
        for purge_at, shown in cases:
            with self.subTest(shown=shown):
                db.BuyerContact.update(purge_at=purge_at).where(db.BuyerContact.id == self.contact_id).execute()
                self.assertIn(f"sparar ditt namn och din ort till och med {shown}. Då vet vi", self.text()[1])

    def test_a_rabbit_without_a_name_goes_by_its_number(self):
        db.Individual.update(name=None).where(db.Individual.id == self.rabbit.id).execute()
        subject, body = self.text()
        self.assertEqual(subject, "Din kanin G1-2111 är registrerad hos Föreningen Gotlandskaninen")
        self.assertIn("du har köpt kaninen G1-2111. Säljaren", body)

    def test_the_retention_sentence_follows_the_consent_the_address_was_given_under(self):
        consent = "sparar vi bara för att du har sagt ja till det, och bara tills kaninen byter ägare igen."
        membership = (
            "sparar vi bara för att du har sagt ja till att vi hör av oss om medlemskap, och i högst 12 månader."
        )
        both = "E-postadress och telefon kan vi ändå spara för att höra av oss om medlemskap, i högst 12 månader från"
        takeback = "Ditt ja kan du ta tillbaka när du vill."
        now = datetime.now(timezone.utc)
        cases = (  # consent_at, membership_at, sentences that are there, sentences that are not
            (now, None, [consent, takeback], [membership, both]),
            (
                None,
                now,
                [f"Din e-postadress, och telefon om du har lämnat den, {membership}"],
                [consent, both, takeback],
            ),
            (now, now, [consent, both, takeback], [membership]),
        )
        for consent_at, membership_at, there, absent in cases:
            with self.subTest(consent=consent_at is not None, membership=membership_at is not None):
                db.BuyerContact.update(contact_consent_at=consent_at, membership_optin_at=membership_at).where(
                    db.BuyerContact.id == self.contact_id
                ).execute()
                body = self.text()[1]
                for sentence in there:
                    self.assertIn(sentence, body)
                for sentence in absent:
                    self.assertNotIn(sentence, body)

    def test_names_from_the_seller_stay_on_one_line(self):
        link = "https://phish.example.org/x"
        db.Individual.update(name=f"Stjärna\n{link}\r\n  igen").where(db.Individual.id == self.rabbit.id).execute()
        db.BuyerContact.update(name=f"Zelda\n\n{link}\tEfternamn").where(
            db.BuyerContact.id == self.contact_id
        ).execute()
        subject, body = self.text()
        self.assertEqual(
            subject, f"Din kanin Stjärna {link} igen (G1-2111) är registrerad hos Föreningen Gotlandskaninen"
        )
        self.assertIn(f"Hej Zelda {link} Efternamn,\n\ndu har köpt kaninen Stjärna {link} igen, G1-2111.", body)
        self.assertNotIn(f"\n{link}", body)

    def test_not_sent_once_the_buyer_is_erased(self):
        buyer_contact.erase_buyer_contact(self.contact_id, self.admin)
        self.assertEqual(self.send(), [])
        self.assertEqual(self.mails()[0].status, "cancelled")


class TestMembership(BuyerMailTest):
    def test_only_with_the_yes_to_membership_contact(self):
        self._sale(WITH_EMAIL)
        self.assertEqual(self.mails("kopare.medlemskap"), [])

    def test_the_welcome_with_the_yes_alone(self):
        contact_id = self._sale({**BUYER, "email": EMAIL, "membership_optin": True}).holder_contact_id
        # The notice goes too: the e-mail given for membership alone still reaches the buyer with the erase link.
        self.assertEqual([row.kind for row in self.mails()], ["kopare.information", "kopare.medlemskap"])
        (row,) = self.mails("kopare.medlemskap")
        self.assertEqual((row.recipient_kind, row.recipient_id, row.category), ("buyer_contact", contact_id, "T"))
        subject, body = self.text("kopare.medlemskap")
        self.assertEqual(subject, "Välkommen att bli medlem i Föreningen Gotlandskaninen")
        self.assertTrue(body.startswith(f"Hej {NAME},\n\nnär du köpte Stjärna sa du att"), body)
        self.assertIn("Läs mer och ansök på gotlandskaninen.se/ansok.\n\nVi sparar ditt ja", body)

    def test_names_from_the_seller_stay_on_one_line(self):
        link = "https://phish.example.org/x"
        contact_id = self._sale({**WITH_EMAIL, "membership_optin": True}).holder_contact_id
        db.Individual.update(name=f"Stjärna\n{link}").where(db.Individual.id == self.rabbit.id).execute()
        db.BuyerContact.update(name=f"Zelda\n{link}").where(db.BuyerContact.id == contact_id).execute()
        body = self.text("kopare.medlemskap")[1]
        self.assertTrue(body.startswith(f"Hej Zelda {link},\n\nnär du köpte Stjärna {link} sa du"), body)

    def test_not_sent_once_the_yes_is_gone(self):
        contact_id = self._sale({**WITH_EMAIL, "membership_optin": True}).holder_contact_id
        db.BuyerContact.update(membership_optin_at=None).where(db.BuyerContact.id == contact_id).execute()
        self.assertEqual(
            [msg["Subject"] for msg in self.send()],
            ["Din kanin Stjärna (G1-2111) är registrerad hos Föreningen Gotlandskaninen"],
        )
        self.assertEqual(self.mails("kopare.medlemskap")[0].status, "cancelled")


ERASE_URL = "/api/v2/kopare/ta-bort"


class TestEraseLink(PurgeTest):
    """POST /api/v2/kopare/ta-bort, the link in kopare.information, with the sale's proof in the intake queue."""

    def setUp(self):
        super().setUp()
        patch = mock.patch.multiple(settings.mail, mode="log", link_secret=SECRET)
        patch.start()
        self.addCleanup(patch.stop)
        gx1 = db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför genbanken")
        rabbit = db.Individual.get(db.Individual.number == "G1-2112")
        self.sale = record_herd_tracking(rabbit, gx1, "2026-01-01", "TRANSFER", self.manager, buyer=WITH_EMAIL)
        self.contact_id = self.sale.holder_contact_id
        self.proof = self.document(self.make(doc_type="bevis"))
        db.InboxDocument.update(herd_tracking_id=self.sale.id).where(db.InboxDocument.id == self.proof.id).execute()
        db.MailMessage.update(status="sent", address_hash="0" * 64).execute()  # the mail went
        self.token = mail.link_token(ERASE_PURPOSE, self.contact_id)

    def erase(self, token, **kwargs):
        return self.client.post(ERASE_URL, json={"token": token}, **kwargs)

    def deletions(self):
        rows = db.AuditLog.select().where(
            (db.AuditLog.table_name == "buyer_contact") & (db.AuditLog.operation == "DELETE")
        )
        return [(row.record_id, row.new_data, row.changed_by) for row in rows]

    def assertPrivate(self, response):  # pylint: disable=invalid-name
        self.assertEqual(
            (response.headers["Cache-Control"], response.headers["Referrer-Policy"]), ("no-store", "no-referrer")
        )

    def test_a_genuine_link_erases_the_buyer_as_an_objection(self):
        with mock.patch("utils.herd_tracking.delete_buyer_contacts", wraps=delete_buyer_contacts) as erasure:
            response = self.erase(self.token)
        self.assertEqual((response.status_code, response.get_json()), (200, {"result": "removed"}))
        self.assertPrivate(response)
        erasure.assert_called_once_with([self.contact_id], "invandning", whole_items=True)
        self.assertIsNone(db.BuyerContact.get_or_none(db.BuyerContact.id == self.contact_id))
        sale = db.HerdTracking.get_by_id(self.sale.id)
        self.assertEqual((sale.voided_at, sale.holder_contact_id, sale.herd.herd), (None, None, "GX1"))
        self.assertIsNone(db.InboxDocument.get_by_id(self.proof.id).original_path)  # the proof's original
        self.assertFalse(self.exists(self.proof.original_path))
        (sent,) = db.MailMessage.select()
        self.assertEqual((sent.address_hash, sent.dedupe_key), (None, None))  # forget_recipient
        self.assertEqual(self.deletions(), [(str(self.contact_id), {"action": "invandning"}, None)])

    def test_a_second_visit_says_it_is_already_done(self):
        self.erase(self.token)
        response = self.erase(self.token)
        self.assertEqual((response.status_code, response.get_json()), (200, {"result": "already_removed"}))
        self.assertEqual(len(self.deletions()), 1)

    def test_the_link_erases_every_contact_with_the_same_address(self):
        def contact(email):
            return db.BuyerContact.create(
                name="Zelda", town="Visby", email=email, contact_consent_at=datetime.now(timezone.utc),
                created_by_user=self.manager, purge_at=db.BuyerContact.purge_at_for(date.today()),
            ).id  # fmt: skip

        same, other = contact(" Zelda@Example.ORG "), contact("link@example.org")
        response = self.erase(self.token)
        self.assertEqual((response.status_code, response.get_json()), (200, {"result": "removed"}))
        self.assertEqual([row.id for row in db.BuyerContact.select()], [other])
        self.assertEqual(sorted(row[0] for row in self.deletions()), sorted([str(self.contact_id), str(same)]))
        self.assertEqual(self.erase(self.token).get_json(), {"result": "already_removed"})
        self.assertEqual([row.id for row in db.BuyerContact.select()], [other])

    def test_the_link_finds_the_other_contacts_after_its_own_address_was_purged(self):
        """The rabbit was sold on, so purge_sold_on took the linked contact's e-mail; the sent mail knows it."""
        consent = {"contact_consent_at": datetime.now(timezone.utc), "created_by_user": self.manager}
        purge_at = db.BuyerContact.purge_at_for(date.today())
        same = db.BuyerContact.create(name="Zelda", town="Visby", email=EMAIL, purge_at=purge_at, **consent).id
        other = db.BuyerContact.create(
            name="Per", town="Visby", email="per@example.org", purge_at=purge_at, **consent
        ).id
        db.MailMessage.update(address_hash=mail.address_hash(EMAIL)).execute()
        db.BuyerContact.update(email=None).where(db.BuyerContact.id == self.contact_id).execute()
        self.assertEqual(self.erase(self.token).get_json(), {"result": "removed"})
        self.assertEqual([row.id for row in db.BuyerContact.select()], [other])
        self.assertEqual(sorted(row[0] for row in self.deletions()), sorted([str(self.contact_id), str(same)]))

    def test_a_sale_that_appears_while_the_locks_are_taken_stops_the_erasure(self):
        """A new sale to the address, of a rabbit this erasure has not locked: nothing goes; the buyer tries again."""
        late = db.Individual.get(db.Individual.number != "G1-2112")
        gx1 = db.Herd.get(db.Herd.herd == "GX1")
        real = buyer_mail._same_buyer
        calls = []

        def meanwhile(contact_id):
            if calls:  # between the two reads, as if it committed while the erasure waited for its locks
                record_herd_tracking(late, gx1, "2026-01-02", "TRANSFER", self.manager, buyer=WITH_EMAIL)
            calls.append(contact_id)
            return real(contact_id)

        with mock.patch.object(buyer_mail, "_same_buyer", meanwhile):
            response = self.erase(self.token)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.deletions(), [])
        self.assertEqual(db.BuyerContact.select().count(), 1)  # the late sale rolled back with the erasure

    def test_any_other_token_changes_nothing_and_answers_alike(self):
        mac = self.token.split(".")[1]
        tokens = {
            "forged, the buyer's id": f"{self.contact_id}." + "A" * 22,
            "forged, an unknown id": "9001." + "A" * 22,
            "another buyer's mac": f"{self.contact_id + 1}.{mac}",
            "another purpose": mail.link_token("annat_syfte", self.contact_id),
            "trailing space": self.token + " ",
            "no mac": f"{self.contact_id}.",
            "empty": "",
            "a number": self.contact_id,
            "missing": None,
        }
        answers = {name: self.erase(token) for name, token in tokens.items()}
        answers["no json"] = self.client.post(ERASE_URL, data=self.token)
        answers["a list"] = self.client.post(ERASE_URL, json=[self.token])
        for name, response in answers.items():
            with self.subTest(name):
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.get_data(), answers["forged, an unknown id"].get_data())
                self.assertPrivate(response)
        self.assertEqual(
            answers["empty"].get_json()["detail"], "Länken gäller inte längre. Skriv till dataskydd@gotlandskaninen.se."
        )
        self.assertIsNotNone(db.BuyerContact.get_or_none(db.BuyerContact.id == self.contact_id))
        self.assertEqual(self.deletions(), [])

    def test_a_get_never_erases(self):
        for url in (ERASE_URL, f"{ERASE_URL}?token={self.token}"):
            self.client.get(url)  # the route takes POST only; a GET falls through to the app's catch-all
        self.assertIsNotNone(db.BuyerContact.get_or_none(db.BuyerContact.id == self.contact_id))
        self.assertEqual(self.deletions(), [])

    def test_at_most_ten_tries_an_hour_from_one_address(self):
        limiter.reset()
        limiter.enabled = True
        self.addCleanup(setattr, limiter, "enabled", False)
        for _ in range(10):
            self.assertEqual(self.erase("1." + "A" * 22).status_code, 404)
        blocked = self.erase(self.token)
        self.assertEqual(blocked.status_code, 429)
        self.assertPrivate(blocked)
        self.assertIsNotNone(db.BuyerContact.get_or_none(db.BuyerContact.id == self.contact_id))
        elsewhere = self.erase(self.token, environ_overrides={"REMOTE_ADDR": "127.0.0.2"})
        self.assertEqual(elsewhere.status_code, 200)


class TestNoTokenInLogs(BuyerMailTest):
    """
    The first route that takes a link token: the token reaches no app log line on its way in, when the erasure fails
    or succeeds, nor in the mail's own text in log mode. A fresh process, so the handlers are the app's (as in
    test_log_masking): its file handler, pointed at stderr, and the root's stderr handler. The access log is not
    asserted: the token travels in the body, so the logged request line is the bare path whatever the code does.
    """

    PROBE = textwrap.dedent(
        """
        import importlib.util, logging, sys
        from datetime import timedelta
        from types import SimpleNamespace
        from unittest import mock
        import pytest  # no blocking startup
        from gunicorn.config import Config
        from gunicorn.glogging import Logger
        from herdbook import APP
        import utils.mail as mail
        from utils.buyer_mail import ERASE_PURPOSE

        contact_id = int(sys.argv[1])
        for handler in APP.logger.handlers:
            handler.setStream(sys.stderr)
        APP.config["PROPAGATE_EXCEPTIONS"] = False  # log the exception as in production, not re-raise it
        spec = importlib.util.spec_from_file_location("gunicorn_conf", "gunicorn.conf.py")
        conf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(conf)
        config = Config()
        config.set("accesslog", "-")
        access = Logger(config)
        logging.getLogger("gunicorn.access").addFilter(conf._TokenMaskFilter())

        def post(token):
            with APP.test_client() as client:
                response = client.post("/api/v2/kopare/ta-bort", json={"token": token})
            request = response.request
            environ = dict(request.environ, RAW_URI=request.environ["PATH_INFO"])
            sent = SimpleNamespace(status=response.status, headers=list(response.headers.items()), sent=1)
            access.access(sent, SimpleNamespace(headers=list(request.headers.items())), environ, timedelta(0))
            print("answer", response.status_code, file=sys.stderr)

        mail.send_pending()  # kopare.information with the link, in log mode
        token = mail.link_token(ERASE_PURPOSE, contact_id)
        post(f"{contact_id}." + "B" * 22)  # forged
        with mock.patch("utils.herd_tracking.delete_buyer_contacts", side_effect=RuntimeError("database gone")):
            post(token)  # the view raises
        post(token)  # erased
        post(token)  # already erased
        """
    )

    def test_the_token_reaches_no_app_or_mail_log(self):
        contact_id = self._sale(WITH_EMAIL).holder_contact_id
        token = mail.link_token(ERASE_PURPOSE, contact_id)
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = {**os.environ, "MAIL_MODE": "log", "LINK_SECRET": SECRET, "FLASK_ENV": "testing"}
        p = subprocess.run(
            [sys.executable, "-c", self.PROBE, str(contact_id)],
            cwd=app_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        logs = p.stdout + p.stderr
        self.assertEqual(re.findall(r"^answer (\d+)$", logs, re.MULTILINE), ["404", "500", "200", "200"], logs)
        self.assertIn(f"/kopare/ta-bort#{contact_id}.***", logs)  # the mail's text, logged and masked
        self.assertIn("Exception on /api/v2/kopare/ta-bort [POST]", logs)
        self.assertNotIn(token, logs)
        self.assertNotIn(token.split(".")[1], logs)  # nor the mac alone, which the mask would not catch
        self.assertIsNone(db.BuyerContact.get_or_none(db.BuyerContact.id == contact_id))
