"""The mails to a buyer outside the association (utils.buyer_mail). Synthetic data only.

isort:skip_file
"""

import os
import re
import uuid
from datetime import datetime, timezone
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.database as db  # noqa: E402
import utils.mail as mail  # noqa: E402
import utils.settings as settings  # noqa: E402
from utils import buyer_contact  # noqa: E402
from utils.buyer_mail import ERASE_PURPOSE, queue_buyer_mails  # noqa: E402
from utils.herd_tracking import correct_herd_tracking, record_herd_tracking  # noqa: E402

from tests.test_buyer_contact import BUYER, NAME, SALE_DATE, BuyerBase  # noqa: E402
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
        sale = self._sale(WITH_EMAIL)
        contact = db.BuyerContact.get_by_id(sale.holder_contact_id)
        event = {"kind": "TRANSFER", "date": "2021-07-01", "herd": "GX1", "holder_contact_id": contact.id}
        correct_herd_tracking(self.rabbit, self.manager, None, [sale.id], [event], "Fel datum")
        queue_buyer_mails(contact, self._latest())  # and if anything queued again, the dedupe_key holds
        self.assertEqual([row.recipient_id for row in self.mails()], [contact.id])


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

    def test_not_sent_once_the_buyer_is_erased(self):
        buyer_contact.erase_buyer_contact(self.contact_id, self.admin)
        self.assertEqual(self.send(), [])
        self.assertEqual(self.mails()[0].status, "cancelled")
