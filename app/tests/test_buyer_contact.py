"""The buyer outside the association (ADR-0016): storage, registration, visibility, retention and erasure.

isort:skip_file
"""

import os
from datetime import datetime, timedelta, timezone
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.inbox_purge as purge  # noqa: E402
from herdbook import APP, limiter  # noqa: E402
from peewee import IntegrityError  # noqa: E402
from utils import buyer_contact  # noqa: E402
from utils.herd_tracking import (  # noqa: E402
    HerdTrackingConflict,
    HerdTrackingInvalid,
    correct_herd_tracking,
    new_operation_id,
    record_herd_tracking,
    undo_herd_tracking_operation,
    void_herd_tracking,
)
from utils.individual_commands import record_sale  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402
from tests.test_inbox_purge import NOW as PURGE_NOW  # noqa: E402
from tests.test_inbox_purge import PHONE, PurgeTest

limiter.enabled = False

RABBIT = "G1-2111"  # registered, born 2021-02-01, in G1 since birth
SALE_DATE = "2021-06-01"
NAME = "Zelda Uniquebuyer"  # ASCII, so a text search of audit_log finds every trace
BUYER = {"name": NAME, "town": "Visby"}
NOW = datetime.now(timezone.utc)


class BuyerBase(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.gx1 = db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför genbanken")
        self.rabbit = self.individuals[0]

    def _login(self, username, password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.get("/api/logout")
        self.client.post("/api/login", json={"username": username, "password": password})

    def _sell(self, herd="GX1", buyer=None, date=SALE_DATE, username="owner"):
        self._login(username)
        body = {"herd": herd, "selling_date": date}
        if buyer is not None:
            body["buyer"] = buyer
        return self.client.patch(f"/api/individual/{RABBIT}", json=body)

    def _sale(self, buyer=BUYER):
        response = self._sell(buyer=buyer)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return self._latest()

    def _latest(self):
        return (
            db.HerdTracking.select()
            .where(db.HerdTracking.individual == self.rabbit, db.ht_not_voided())
            .order_by(*db.ht_order_desc())
            .first()
        )

    def _contact(self, contact_id):
        return db.BuyerContact.get_or_none(db.BuyerContact.id == contact_id)

    def _buyer_log(self, contact_id, operation=None):
        rows = db.AuditLog.select().where(
            (db.AuditLog.table_name == "buyer_contact") & (db.AuditLog.record_id == str(contact_id))
        )
        return [r for r in rows if operation is None or r.operation == operation]


class TestSchema(BuyerBase):
    def test_migration_creates_the_table_and_the_set_null_fk(self):
        self.addCleanup(db.check_migrations)
        sql = db.DATABASE.execute_sql
        sql('ALTER TABLE herd_tracking DROP CONSTRAINT "herd_tracking_holder_contact_id_fkey"')
        sql('DROP INDEX "herdtracking_holder_contact_id"')
        sql("DROP TABLE buyer_contact")
        db.SchemaHistory.delete().where(db.SchemaHistory.version >= 41).execute()
        if db.SchemaHistory.get_or_none(db.SchemaHistory.version == 40) is None:
            db.SchemaHistory.insert(version=40, comment="test seed", applied=datetime.now()).execute()  # pylint: disable=E1120

        db.check_migrations()

        self.assertEqual(db.SchemaHistory.select(db.fn.MAX(db.SchemaHistory.version)).scalar(), 41)  # pylint: disable=E1120
        self.assertIn("buyer_contact", db.DATABASE.get_tables())
        delete_rule = sql(
            "SELECT confdeltype FROM pg_constraint WHERE conname = 'herd_tracking_holder_contact_id_fkey'"
        ).fetchone()
        self.assertEqual(delete_rule, ("n",))  # ON DELETE SET NULL
        checks = {r[0] for r in sql("SELECT conname FROM pg_constraint WHERE conrelid = 'buyer_contact'::regclass")}
        self.assertTrue({"buyer_contact_address_needs_consent", "buyer_contact_email_phone_need_consent"} <= checks)
        db.check_migrations()  # replay-safe

    def test_purge_at_is_five_years_after_created_at(self):
        contact = db.BuyerContact.create(name=NAME, town="Visby", created_by_user=self.owner)
        contact = self._contact(contact.id)
        self.assertEqual(contact.purge_at.replace(year=contact.purge_at.year - 5), contact.created_at)

    def test_address_needs_the_contact_consent(self):
        with self.assertRaises(IntegrityError), db.DATABASE.atomic():
            db.BuyerContact.create(name=NAME, town="Visby", postal_address="Väg 1", created_by_user=self.owner)
        with self.assertRaises(IntegrityError), db.DATABASE.atomic():
            db.BuyerContact.create(
                name=NAME, town="Visby", postal_address="Väg 1", membership_optin_at=NOW, created_by_user=self.owner
            )
        db.BuyerContact.create(
            name=NAME, town="Visby", postal_address="Väg 1", contact_consent_at=NOW, created_by_user=self.owner
        )

    def test_email_and_phone_need_a_consent_or_the_membership_optin(self):
        for field in ("email", "phone"):
            with self.subTest(field=field):
                with self.assertRaises(IntegrityError), db.DATABASE.atomic():
                    db.BuyerContact.create(name=NAME, town="Visby", created_by_user=self.owner, **{field: "x"})
                db.BuyerContact.create(
                    name=NAME, town="Visby", membership_optin_at=NOW, created_by_user=self.owner, **{field: "x"}
                )

    def test_deleting_a_contact_nulls_the_sale_through_the_herd_tracking_triggers(self):
        triggers = {
            r[0]
            for r in db.DATABASE.execute_sql(
                "SELECT tgname FROM pg_trigger WHERE tgrelid = 'herd_tracking'::regclass AND NOT tgisinternal"
            )
        }
        # No UPDATE whitelist trigger exists: the whitelist is HerdTracking.save() and the two writers.
        self.assertEqual(triggers, {"herd_tracking_no_delete", "audit_trigger", "genetics_change_herd_tracking_iud"})
        sale = self._sale()
        db.BuyerContact.delete().where(db.BuyerContact.id == sale.holder_contact_id).execute()
        self.assertIsNone(db.HerdTracking.get_by_id(sale.id).holder_contact_id)
        audit = db.AuditLog.select().where(
            (db.AuditLog.table_name == "herd_tracking")
            & (db.AuditLog.record_id == str(sale.id))
            & (db.AuditLog.operation == "UPDATE")
        )
        self.assertEqual([a.changed_fields for a in audit], [["holder_contact_id"]])


class TestRegistration(BuyerBase):
    def test_sale_without_buyer_is_unchanged(self):
        sale = self._sale(buyer=None)
        self.assertEqual(sale.herd.herd, "GX1")
        self.assertIsNone(sale.holder_contact_id)
        self.assertEqual(db.BuyerContact.select().count(), 0)

    def test_sale_with_buyer_stores_the_contact_on_the_transfer(self):
        buyer = {
            **BUYER,
            "postal_address": " Väg 1, 621 00 Visby ",
            "email": "z@example.org",
            "phone": "0701234567",
            "contact_consent": True,
            "membership_optin": False,
        }
        sale = self._sale(buyer)
        contact = self._contact(sale.holder_contact_id)
        self.assertEqual(
            (contact.name, contact.town, contact.postal_address, contact.email, contact.phone),
            (NAME, "Visby", "Väg 1, 621 00 Visby", "z@example.org", "0701234567"),
        )
        self.assertIsNotNone(contact.contact_consent_at)
        self.assertIsNone(contact.membership_optin_at)
        self.assertEqual(contact.created_by_user_id, self.owner.id)
        self.assertEqual(sale.kind, "TRANSFER")

    def test_contact_fields_without_the_matching_yes_are_400_and_nothing_is_written(self):
        cases = (
            {**BUYER, "postal_address": "Väg 1", "membership_optin": True},
            {**BUYER, "email": "z@example.org"},
            {**BUYER, "phone": "0701234567", "contact_consent": False},
            {"name": NAME},
            {**BUYER, "contact_consent": "ja"},
        )
        for buyer in cases:
            with self.subTest(buyer=buyer):
                response = self._sell(buyer=buyer)
                self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
                self.assertEqual(self._latest().kind, "BIRTH")
        self.assertIn("kryssat ja", self._sell(buyer={**BUYER, "email": "z@example.org"}).get_json()["detail"])
        self.assertEqual(db.BuyerContact.select().count(), 0)

    def test_membership_optin_alone_keeps_email_and_phone(self):
        sale = self._sale({**BUYER, "email": "z@example.org", "membership_optin": True})
        contact = self._contact(sale.holder_contact_id)
        self.assertEqual(contact.email, "z@example.org")
        self.assertIsNotNone(contact.membership_optin_at)

    def test_a_buyer_for_a_herd_in_the_association_is_an_error(self):
        response = self._sell(herd="G2", buyer=BUYER)
        self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        self.assertIn("utanför genbanken", response.get_json()["detail"])
        self.assertEqual(self._latest().kind, "BIRTH")

    def test_a_buyer_without_a_sale_is_an_error(self):
        self._login("owner")
        response = self.client.patch(f"/api/individual/{RABBIT}", json={"buyer": BUYER})
        self.assertEqual(response.status_code, 400)


class TestOutsideResale(BuyerBase):
    """GX1 to GX1: a buyer outside the association sells to another."""

    def setUp(self):
        super().setUp()
        self.first = self._sale()

    def test_manager_registers_a_new_buyer(self):
        second = {"name": "Other Buyer", "town": "Slite"}
        response = self._sell(buyer=second, date="2022-01-01", username="man")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        latest = self._latest()
        self.assertEqual((latest.kind, latest.from_herd.herd, latest.herd.herd), ("TRANSFER", "GX1", "GX1"))
        self.assertEqual(self._contact(latest.holder_contact_id).name, "Other Buyer")
        self.assertEqual(self._contact(self.first.holder_contact_id).name, NAME)

    def test_the_queue_utility_writes_it_too(self):
        record_sale(self.manager, self.rabbit.id, "GX1", "2022-01-01", buyer={"name": "Other", "town": "Slite"})
        self.assertEqual(self._latest().from_herd.herd, "GX1")

    def test_without_a_new_buyer_it_is_refused(self):
        response = self._sell(date="2022-01-01", username="man")
        self.assertEqual(response.status_code, 400)
        self.assertIn("finns redan", response.get_json()["detail"])
        with self.assertRaises(HerdTrackingConflict):
            record_herd_tracking(self.rabbit, self.gx1, "2022-01-01", "TRANSFER", self.manager)
        self.assertEqual(self._latest().id, self.first.id)

    def test_only_a_manager_or_admin(self):
        with self.assertRaises(HerdTrackingConflict):
            record_herd_tracking(self.rabbit, self.gx1, "2022-01-01", "TRANSFER", self.owner, buyer=BUYER)
        self.assertEqual(self._sell(buyer=BUYER, date="2022-01-01").status_code, 403)  # can_transfer
        self.assertEqual(self._latest().id, self.first.id)

    def test_a_correction_cannot_write_it(self):
        event = {"kind": "TRANSFER", "date": "2022-01-01", "herd": "GX1"}
        with self.assertRaises(HerdTrackingConflict):
            correct_herd_tracking(self.rabbit, self.manager, None, [], [event])
        self.assertEqual(self._latest().id, self.first.id)

    def test_the_resale_stays_valid_after_both_buyers_are_erased(self):
        second = record_herd_tracking(self.rabbit, self.gx1, "2022-01-01", "TRANSFER", self.admin, buyer=BUYER)
        for sale in (self.first, second):
            buyer_contact.erase_buyer_contact(sale.holder_contact_id, self.admin)
        record_herd_tracking(self.rabbit, self.herds[1], "2022-02-01", "TRANSFER", self.manager)  # buyback
        self.assertEqual(self._latest().herd.herd, "G2")


class TestVisibility(BuyerBase):
    def setUp(self):
        super().setUp()
        self.sale = self._sale({**BUYER, "email": "z@example.org", "contact_consent": True})
        self.helper = da.register_user("helper", "pass")
        self.helper.add_role("helper", self.genebanks[0].id)
        self.other = da.register_user("othermgr", "pass")
        self.other.add_role("manager", self.genebanks[1].id)
        self.other.add_role("viewer", self.genebanks[0].id)  # reads the rabbit, not the buyer

    def _buyer_seen_by(self, username):
        self._login(username)
        response = self.client.get(f"/api/v2/individual/{RABBIT}/herd-tracking")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        row = next(r for r in response.get_json()["rows"] if r["id"] == self.sale.id)
        self.assertEqual(row["herd"]["label"], "Såld utanför genbanken")
        return row["buyer"]

    def test_admin_manager_and_helper_see_name_town_and_kept_contact(self):
        expected = {"id": self.sale.holder_contact_id, "name": NAME, "town": "Visby", "email": "z@example.org"}
        for username in ("admin", "man", "helper"):
            with self.subTest(username=username):
                self.assertEqual(self._buyer_seen_by(username), expected)

    def test_everyone_else_sees_only_the_label(self):
        for username in ("owner", "othermgr", "spec"):
            with self.subTest(username=username):
                self.assertIsNone(self._buyer_seen_by(username))
        self.assertEqual(self._buyer_log(self.sale.holder_contact_id, "READ"), [])

    def test_each_read_is_logged_without_personal_data_once_an_hour(self):
        self._buyer_seen_by("man")
        self._buyer_seen_by("man")
        self._buyer_seen_by("helper")
        reads = self._buyer_log(self.sale.holder_contact_id, "READ")
        self.assertEqual(sorted(r.changed_by for r in reads), ["helper", "man"])
        self.assertNotIn(NAME, str([(r.old_data, r.new_data) for r in reads]))
        db.AuditLog.insert(  # an hour-old read does not hold back a new one
            table_name="buyer_contact",
            record_id=str(self.sale.holder_contact_id),
            operation="READ",
            changed_by="admin",
            changed_at=NOW - timedelta(hours=2),
        ).execute()
        self._buyer_seen_by("admin")
        self.assertEqual(len(self._buyer_log(self.sale.holder_contact_id, "READ")), 4)

    def test_the_audit_view_shows_the_contact_only_as_an_id(self):
        self._login("man")
        entries = self.client.get(f"/api/audit-log/herd_tracking/{self.sale.id}").get_json()["data"]
        self.assertTrue(any((e.get("new_data") or {}).get("holder_contact_id") for e in entries))
        self.assertNotIn(NAME, str(entries))


class TestVoid(BuyerBase):
    def setUp(self):
        super().setUp()
        self.sale = self._sale()
        self.contact_id = self.sale.holder_contact_id

    def test_undoing_the_sale_deletes_the_buyer(self):
        with mock.patch("utils.inbox_purge.erase_buyer_from_inbox", return_value=[]) as inbox:
            void_herd_tracking(self.sale.id, self.owner, "Fel kanin")
        inbox.assert_called_once_with(self.sale.id, certificates=False)
        self.assertIsNone(self._contact(self.contact_id))
        self.assertEqual(
            [r.new_data for r in self._buyer_log(self.contact_id, "DELETE")], [{"action": "forsaljning_ogiltig"}]
        )

    def test_undoing_the_operation_deletes_the_buyer(self):
        undo_herd_tracking_operation(self.sale.operation_id, self.manager, "Fel kanin")
        self.assertIsNone(self._contact(self.contact_id))

    def test_a_correction_that_voids_the_sale_deletes_the_buyer(self):
        correct_herd_tracking(self.rabbit, self.manager, None, [self.sale.id], [], "Fel datum")
        self.assertIsNone(self._contact(self.contact_id))

    def _correct_date(self, **event):
        op = new_operation_id()
        sale_event = {"kind": "TRANSFER", "date": "2021-07-01", "herd": "GX1", **event}
        return op, correct_herd_tracking(self.rabbit, self.manager, op, [self.sale.id], [sale_event], "Fel datum")

    def test_a_correction_of_the_sale_keeps_the_buyer_and_its_purge_date(self):
        purge_at = self._contact(self.contact_id).purge_at
        _op, (written,) = self._correct_date(holder_contact_id=self.contact_id)
        self.assertEqual(written.holder_contact_id, self.contact_id)
        self.assertEqual(self._contact(self.contact_id).purge_at, purge_at)
        self.assertEqual(self._buyer_log(self.contact_id, "DELETE"), [])

    def test_undoing_that_correction_restores_the_old_sale_with_its_buyer(self):
        op, _written = self._correct_date(holder_contact_id=self.contact_id)
        undo_herd_tracking_operation(op, self.manager, "Rätt datum ändå")
        self.assertEqual(self._latest().id, self.sale.id)
        self.assertEqual(self._latest().holder_contact_id, self.contact_id)
        self.assertIsNotNone(self._contact(self.contact_id))

    def test_a_correction_without_the_buyer_deletes_it(self):
        self._correct_date()
        self.assertIsNone(self._contact(self.contact_id))

    def test_a_buyer_from_a_row_not_voided_in_the_correction_is_400(self):
        event = {"kind": "TRANSFER", "date": "2022-01-01", "herd": "GX1", "holder_contact_id": self.contact_id}
        with self.assertRaises(HerdTrackingInvalid):
            correct_herd_tracking(self.rabbit, self.manager, None, [], [event])
        with self.assertRaises(HerdTrackingInvalid):  # and only on a sale outside the genebank
            self._correct_date(herd="G2", holder_contact_id=self.contact_id)
        self.assertEqual(self._latest().id, self.sale.id)
        self.assertIsNotNone(self._contact(self.contact_id))

    def test_the_reason_never_names_the_buyer(self):
        with self.assertRaises(HerdTrackingInvalid):
            void_herd_tracking(self.sale.id, self.owner, f"Såld till {NAME.upper()} av misstag")
        self.assertIsNotNone(self._contact(self.contact_id))


class TestErasure(BuyerBase):
    def setUp(self):
        super().setUp()
        self.sale = self._sale({**BUYER, "email": "z@example.org", "contact_consent": True})
        self.contact_id = self.sale.holder_contact_id

    def _erase(self, username):
        self._login(username)
        return self.client.delete(f"/api/v2/buyer-contacts/{self.contact_id}")

    def test_a_manager_erases_the_buyer_and_the_sale_stays(self):
        with (
            mock.patch("utils.inbox_purge.erase_buyer_from_inbox", return_value=[]) as inbox,
            mock.patch("utils.herd_tracking.forget_recipient") as forget,
        ):
            response = self._erase("man")
        self.assertEqual(response.status_code, 204, response.get_data(as_text=True))
        inbox.assert_called_once_with(self.sale.id, certificates=True)
        forget.assert_called_once_with("buyer_contact", self.contact_id)
        self.assertIsNone(self._contact(self.contact_id))
        sale = db.HerdTracking.get_by_id(self.sale.id)
        self.assertEqual((sale.voided_at, sale.holder_contact_id, sale.herd.herd), (None, None, "GX1"))
        log = self._buyer_log(self.contact_id, "DELETE")
        self.assertEqual([(r.new_data, r.changed_by) for r in log], [({"action": "radering"}, "man")])
        self.assertEqual(self._erase("man").status_code, 404)

    def test_only_admin_or_a_manager_of_the_rabbits_genebank(self):
        other = da.register_user("othermgr", "pass")
        other.add_role("manager", self.genebanks[1].id)
        helper = da.register_user("helper", "pass")
        helper.add_role("helper", self.genebanks[0].id)
        for username in ("owner", "helper", "othermgr"):
            with self.subTest(username=username):
                self.assertEqual(self._erase(username).status_code, 403)
        self.assertIsNotNone(self._contact(self.contact_id))
        self.assertEqual(self._erase("admin").status_code, 204)


class TestRetention(BuyerBase):
    def setUp(self):
        super().setUp()
        self.sale = self._sale(
            {**BUYER, "postal_address": "Väg 1", "phone": "070123", "contact_consent": True, "membership_optin": True}
        )
        self.contact_id = self.sale.holder_contact_id

    def test_five_years_after_entry_the_buyer_goes(self):
        self.assertEqual(buyer_contact.purge_expired(NOW), 0)
        with mock.patch("utils.inbox_purge.erase_buyer_from_inbox", return_value=[]) as inbox:
            self.assertEqual(buyer_contact.purge_expired(NOW + timedelta(days=5 * 366)), 1)
        inbox.assert_called_once_with(self.sale.id, certificates=False)
        self.assertIsNone(self._contact(self.contact_id))
        self.assertIsNone(db.HerdTracking.get_by_id(self.sale.id).holder_contact_id)
        self.assertEqual(
            [r.new_data for r in self._buyer_log(self.contact_id, "DELETE")], [{"action": "gallring_fem_ar"}]
        )

    def test_contact_details_go_when_the_rabbit_is_sold_on(self):
        self.assertEqual(buyer_contact.purge_sold_on(NOW), 0)
        record_herd_tracking(self.rabbit, self.herds[1], "2022-01-01", "TRANSFER", self.manager)  # buyback
        self.assertEqual(buyer_contact.purge_sold_on(NOW), 1)
        contact = self._contact(self.contact_id)
        self.assertEqual((contact.name, contact.town), (NAME, "Visby"))
        self.assertEqual(
            (contact.postal_address, contact.email, contact.phone, contact.contact_consent_at), (None, None, None, None)
        )
        self.assertIsNotNone(contact.membership_optin_at)
        self.assertEqual(buyer_contact.purge_sold_on(NOW), 0)  # one audit row, not one a night
        self.assertEqual(len(self._buyer_log(self.contact_id, "UPDATE")), 1)

    def test_a_voided_later_sale_does_not_count(self):
        later = record_herd_tracking(self.rabbit, self.herds[1], "2022-01-01", "TRANSFER", self.manager)
        void_herd_tracking(later.id, self.manager, "Fel")
        self.assertEqual(buyer_contact.purge_sold_on(NOW), 0)

    def test_the_membership_yes_goes_after_12_months(self):
        self.assertEqual(buyer_contact.purge_membership_optin(NOW), 0)
        self.assertEqual(buyer_contact.purge_membership_optin(NOW + timedelta(days=366)), 1)
        contact = self._contact(self.contact_id)
        self.assertIsNone(contact.membership_optin_at)
        self.assertEqual(contact.phone, "070123")  # kept under the contact consent

    def test_e_mail_and_phone_kept_only_for_membership_go_with_it(self):
        db.BuyerContact.update(contact_consent_at=None, postal_address=None).where(
            db.BuyerContact.id == self.contact_id
        ).execute()
        buyer_contact.purge_membership_optin(NOW + timedelta(days=366))
        contact = self._contact(self.contact_id)
        self.assertEqual((contact.phone, contact.membership_optin_at), (None, None))


class TestNoTraceInAuditLog(BuyerBase):
    def test_after_erasure_and_purge_the_name_is_nowhere_in_audit_log(self):
        sale = self._sale({**BUYER, "email": "z@example.org", "contact_consent": True, "membership_optin": True})
        self._login("man")
        self.client.get(f"/api/v2/individual/{RABBIT}/herd-tracking")
        record_herd_tracking(self.rabbit, self.herds[1], "2022-01-01", "TRANSFER", self.manager)
        buyer_contact.run(NOW + timedelta(days=366))
        buyer_contact.erase_buyer_contact(sale.holder_contact_id, self.manager)
        self.assertGreater(len(self._buyer_log(sale.holder_contact_id)), 2)
        for needle in (NAME, "Uniquebuyer", "z@example.org"):
            found = db.DATABASE.execute_sql("SELECT count(*) FROM audit_log a WHERE a::text ILIKE %s", (f"%{needle}%",))
            self.assertEqual(found.fetchone()[0], 0, needle)


class TestQueueDocuments(PurgeTest):
    """The sale's documents in the intake queue when its buyer goes (inbox_purge.erase_buyer_from_inbox)."""

    def setUp(self):
        super().setUp()
        gx1 = db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför genbanken")
        rabbit = db.Individual.get(db.Individual.number == "G1-2112")
        self.sale = record_herd_tracking(rabbit, gx1, "2026-01-01", "TRANSFER", self.manager, buyer=BUYER)
        self.certificate = self.with_copy(self.make())
        self.proof = self.document(self.make(doc_type="bevis"))
        db.InboxDocument.update(herd_tracking_id=self.sale.id).execute()

    def test_an_erasure_leaves_the_certificate_its_copy_and_deletes_the_proof(self):
        buyer_contact.erase_buyer_contact(self.sale.holder_contact_id, self.manager)
        certificate, proof = (db.InboxDocument.get_by_id(d.id) for d in (self.certificate, self.proof))
        self.assertEqual((certificate.original_path, proof.original_path), (None, None))
        self.assertFalse(self.exists(self.certificate.original_path))
        self.assertFalse(self.exists(self.proof.original_path))
        self.assertEqual(certificate.public_path, self.certificate.public_path)
        self.assertTrue(self.exists(certificate.public_path))
        self.assertNotIn(PHONE, self.text(certificate.item))

    def test_a_void_deletes_only_the_proofs_original(self):
        void_herd_tracking(self.sale.id, self.manager, "Fel kanin")
        self.assertIsNone(db.InboxDocument.get_by_id(self.proof.id).original_path)
        self.assertEqual(db.InboxDocument.get_by_id(self.certificate.id).original_path, self.certificate.original_path)
        self.assertTrue(self.exists(self.certificate.original_path))

    def test_nothing_to_do_once_the_originals_are_purged(self):
        purge.purge_originals(PURGE_NOW + timedelta(days=400))
        before = list(db.InboxDocument.select().order_by(db.InboxDocument.id).tuples())
        self.assertEqual(buyer_contact.purge_expired(NOW + timedelta(days=5 * 366)), 1)
        self.assertEqual(list(db.InboxDocument.select().order_by(db.InboxDocument.id).tuples()), before)
