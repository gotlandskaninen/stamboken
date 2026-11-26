"""A sale without a försäljningsbevis (#273, förslag 5 b och 6): the buyer's e-mail only for the notice, or
"såld utanför genbanken" with nothing kept. Synthetic data only.

isort:skip_file
"""

import os
from datetime import datetime, timedelta, timezone
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.database as db  # noqa: E402
from peewee import IntegrityError  # noqa: E402
from utils import buyer_contact, herd_tracking, sale_proposal  # noqa: E402
from utils.herd_tracking import (  # noqa: E402
    BEVIS_NOT_YET,
    NOT_RECORDED,
    TRANSITION_OVER,
    HerdTrackingInvalid,
    attach_buyer,
    buyer_contact_fields,
    correct_herd_tracking,
    record_herd_tracking,
)
from utils.individual_commands import record_sale  # noqa: E402
from utils.mail import SALE_WITHDRAWN  # noqa: E402

from tests.database_test import _USE_POSTGRES, rewind_migrations  # noqa: E402
from tests.test_buyer_contact import BUYER  # noqa: E402
from tests.test_buyer_mail import BuyerMailTest  # noqa: E402

DAY = "2026-06-01"  # a sale in 2026, before the bevis; its five years last until 2031
EMAIL = "notis@example.org"
NOTICE = {**BUYER, "email": EMAIL, "notice_only": True}
REAL_BEVIS_FROM = datetime(2027, 1, 1).date()


class NoticeOnlyTest(BuyerMailTest):
    def sale(self, buyer=NOTICE, day=DAY):
        response = self._sell(buyer=buyer, date=day)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return self._latest()

    def contact(self, sale):
        return db.BuyerContact.get_or_none(db.BuyerContact.id == sale.holder_contact_id)

    def notice_status(self, status, created_at=None, last_error=None):
        changes = {"status": status, "last_error": last_error, **({"created_at": created_at} if created_at else {})}
        db.MailMessage.update(**changes).where(db.MailMessage.kind == "kopare.information").execute()

    def purge(self):
        now = datetime.now(timezone.utc)
        buyer_contact.purge_undelivered_notice(now)
        buyer_contact.purge_notice_email(now)


class TestFields(NoticeOnlyTest):
    def test_the_e_mail_needs_name_town_address_and_takes_no_phone_or_yes(self):
        fields = buyer_contact_fields(NOTICE, DAY)
        self.assertEqual((fields["email"], fields["email_notice_only"]), (EMAIL, True))
        self.assertIsNone(fields["contact_consent_at"])
        for buyer in (
            {**NOTICE, "email": None},
            {**NOTICE, "postal_address": ""},
            {**NOTICE, "phone": "070-000 00 00"},
            {**NOTICE, "contact_consent": True},
            {**NOTICE, "membership_optin": True},
            {**NOTICE, "not_recorded": True},
            {**NOTICE, "notice_only": "ja"},
        ):
            with self.subTest(buyer=buyer), self.assertRaises(HerdTrackingInvalid):
                buyer_contact_fields(buyer, DAY)

    def test_sold_outside_keeps_nothing_and_takes_no_details(self):
        self.assertIsNone(buyer_contact_fields(NOT_RECORDED, DAY))
        with self.assertRaises(HerdTrackingInvalid):
            buyer_contact_fields({**NOT_RECORDED, "name": "Någon"}, DAY)

    def test_the_transition_ends_with_2027(self):
        buyer_contact_fields(NOTICE, "2027-12-31")
        for buyer in (NOTICE, NOT_RECORDED):
            with self.subTest(buyer=buyer), self.assertRaisesRegex(HerdTrackingInvalid, TRANSITION_OVER):
                buyer_contact_fields(buyer, "2028-01-01")

    def test_before_2027_a_new_sale_takes_no_buyer_the_bevis_would_inform(self):
        with mock.patch.object(herd_tracking, "BEVIS_FROM", REAL_BEVIS_FROM):
            with self.assertRaisesRegex(HerdTrackingInvalid, BEVIS_NOT_YET):
                buyer_contact_fields(BUYER, "2026-12-31", new_sale=True)
            buyer_contact_fields(BUYER, "2027-01-01", new_sale=True)
            buyer_contact_fields(BUYER, "2026-12-31")  # a correction of a sale already registered
            response = self._sell(buyer=BUYER, date=DAY)
            self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
            self.assertIn(BEVIS_NOT_YET, response.get_json()["detail"])
            legacy = record_herd_tracking(self.rabbit, self.gx1, DAY, "TRANSFER", self.manager)  # no buyer
            with self.assertRaisesRegex(HerdTrackingInvalid, BEVIS_NOT_YET):
                attach_buyer(legacy, BUYER, self.owner)  # an old paper follows the rule too (5 b)
            self.assertEqual(attach_buyer(legacy, NOTICE, self.owner).email_notice_only, True)
        self.assertEqual(db.BuyerContact.select().count(), 1)


class TestDatabase(NoticeOnlyTest):
    def test_the_database_keeps_an_e_mail_without_a_yes_only_for_the_notice(self):
        if not _USE_POSTGRES:
            self.skipTest("CHECK constraints are tested on PostgreSQL")
        row = {
            "name": "Testköpare",
            "town": "Visby",
            "email": EMAIL,
            "created_by_user": self.owner,
            "purge_at": datetime.now(timezone.utc) + timedelta(days=1),
        }
        for case, extra in (
            ("no yes, no flag", {}),
            ("flag and phone", {"email_notice_only": True, "phone": "070-000 00 00"}),
            ("flag and a yes", {"email_notice_only": True, "contact_consent_at": datetime.now(timezone.utc)}),
        ):
            with self.subTest(case), self.assertRaises(IntegrityError), db.DB_PROXY.atomic():
                db.BuyerContact.create(**row, **extra)
        db.BuyerContact.create(**row, email_notice_only=True)

    def test_migration_57_adds_the_flag_and_both_checks_and_replays(self):
        self.addCleanup(db.check_migrations)
        sql = db.DATABASE.execute_sql
        sql("ALTER TABLE buyer_contact DROP CONSTRAINT buyer_contact_notice_only_no_consent")
        sql("ALTER TABLE buyer_contact DROP CONSTRAINT buyer_contact_email_phone_need_consent")
        sql("ALTER TABLE buyer_contact DROP COLUMN email_notice_only")
        rewind_migrations(57)
        db.check_migrations()
        db.check_migrations()  # replay-safe
        checks = {r[0] for r in sql("SELECT conname FROM pg_constraint WHERE conrelid = 'buyer_contact'::regclass")}
        self.assertLessEqual({"buyer_contact_email_phone_need_consent", "buyer_contact_notice_only_no_consent"}, checks)
        self.assertIn("email_notice_only", {c.name for c in db.DATABASE.get_columns("buyer_contact")})


class TestSale(NoticeOnlyTest):
    def test_the_sale_keeps_the_e_mail_for_the_notice_and_mails_it(self):
        contact = self.contact(self.sale())
        self.assertEqual((contact.email, contact.email_notice_only), (EMAIL, True))
        self.assertIsNone(contact.contact_consent_at)
        self.assertEqual([row.kind for row in self.mails()], ["kopare.information"])
        _subject, body = self.text()
        self.assertIn("Säljaren gav oss också din e-postadress.", body)
        self.assertIn("sedan sparar vi den inte", body)
        self.assertIn("för det här köpet", body)
        self.assertNotIn("avtryck", body)
        self.assertNotIn("medlemsinbjudan", body)

    def test_sold_outside_the_genebank_keeps_and_mails_nothing(self):
        response = self._sell(buyer={**NOT_RECORDED, "town": "Visby"}, date=DAY)
        self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        sale = self.sale(NOT_RECORDED)
        self.assertEqual((sale.holder_contact_id, sale.buyer_removed), (None, False))
        self.assertEqual(db.BuyerContact.select().count(), 0)
        self.assertEqual(self.mails(), [])

    def test_a_correction_can_sell_outside_without_a_buyer(self):
        event = {"kind": "TRANSFER", "date": DAY, "herd": "GX1", "buyer": NOT_RECORDED}
        (written,) = correct_herd_tracking(self.rabbit, self.manager, None, [], [event])
        self.assertEqual((written.holder_contact_id, written.buyer_removed), (None, False))

    def test_a_correction_to_sold_outside_does_not_carry_the_buyer_over(self):
        sale = self.sale()
        event = {"kind": "TRANSFER", "date": DAY, "herd": "GX1", "buyer": NOT_RECORDED}
        (written,) = correct_herd_tracking(self.rabbit, self.manager, None, [sale.id], [event], reason="Rättelse")
        self.assertIsNone(written.holder_contact_id)
        self.assertEqual(db.BuyerContact.select().count(), 0)

    def test_a_proposal_takes_either_mode_to_its_approval(self):
        at = datetime.now(timezone.utc)
        self.assertEqual(sale_proposal._stored_buyer(NOT_RECORDED, at, DAY), NOT_RECORDED)  # pylint: disable=protected-access
        stored = sale_proposal._stored_buyer(NOTICE, at, DAY)  # pylint: disable=protected-access
        self.assertEqual((stored["email"], stored["notice_only"]), (EMAIL, True))
        record_sale(self.manager, self.rabbit.id, "GX1", DAY, buyer=stored)  # as the approval does
        self.assertTrue(self.contact(self._latest()).email_notice_only)


class TestPurge(NoticeOnlyTest):
    def test_the_e_mail_goes_once_the_notice_has_gone_and_leaves_no_avtryck(self):
        sale = self.sale()
        self.purge()
        self.assertEqual(self.contact(sale).email, EMAIL)  # the notice still waits
        self.assertEqual([msg["To"] for msg in self.send()], [EMAIL])
        self.purge()
        contact = self.contact(sale)
        self.assertEqual((contact.email, contact.erased_email_hash), (None, None))
        self.assertEqual((contact.name, contact.postal_address), (BUYER["name"], BUYER["postal_address"]))
        self.assertEqual([row.address_hash for row in self.mails()], [None])

    def test_the_e_mail_stays_while_the_notice_can_still_go(self):
        sale = self.sale()
        for status, error in (("sending", None), ("failed", None), ("cancelled", SALE_WITHDRAWN)):
            self.notice_status(status, last_error=error)  # retried, or a withdrawn report sent again
            self.purge()
            with self.subTest(status=status):
                self.assertEqual(self.contact(sale).email, EMAIL)

    def test_a_bounce_removes_the_buyer_also_after_the_e_mail_went(self):
        sale = self.sale()
        self.send()
        self.purge()
        self.notice_status("bounced")
        self.purge()
        self.assertEqual(db.BuyerContact.select().count(), 0)
        sale = db.HerdTracking.get_by_id(sale.id)
        self.assertEqual((sale.holder_contact_id, sale.buyer_removed, sale.voided_at), (None, True, None))

    def test_a_notice_that_can_no_longer_be_retried_removes_the_buyer(self):
        self.sale()
        self.notice_status("failed", datetime.now(timezone.utc) - buyer_contact.FAILED_NOTICE_KEPT - timedelta(1))
        self.purge()
        self.assertEqual(db.BuyerContact.select().count(), 0)

    def test_a_bounce_to_a_buyer_who_said_yes_is_left_as_before(self):
        sale = self._sale({**BUYER, "email": EMAIL, "contact_consent": True})
        self.notice_status("bounced")
        self.purge()
        self.assertEqual(self.contact(sale).email, EMAIL)
