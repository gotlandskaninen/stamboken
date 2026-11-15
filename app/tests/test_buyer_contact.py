"""The buyer outside the association (ADR-0016): storage, registration, visibility, retention and erasure.

isort:skip_file
"""

import os
from datetime import date, datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.inbox as inbox  # noqa: E402
import utils.inbox_purge as purge  # noqa: E402
from herdbook import APP, limiter  # noqa: E402
from peewee import IntegrityError  # noqa: E402
from utils import buyer_contact  # noqa: E402
from utils.herd_tracking import (  # noqa: E402
    HerdTrackingConflict,
    HerdTrackingInvalid,
    correct_herd_tracking,
    herd_tracking_history,
    new_operation_id,
    record_herd_tracking,
    undo_herd_tracking_operation,
    void_all_for_unpromote,
    void_herd_tracking,
)
from utils.individual_commands import RecordAttestation, Undo, execute, record_sale  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402
from tests.test_bunny_v2_api import _old_litter, _promote_without_certificate
from tests.test_herd_tracking_locks import capture_sql
from tests.test_inbox_erasure import ErasureTest
from tests.test_inbox_purge import NOW as PURGE_NOW  # noqa: E402
from tests.test_inbox_purge import PurgeTest

limiter.enabled = False

RABBIT = "G1-2111"  # registered, born 2021-02-01, in G1 since birth
SALE_DATE = "2021-06-01"
NAME = "Zelda Uniquebuyer"  # ASCII, so a text search of audit_log finds every trace
BUYER = {"name": NAME, "town": "Visby"}
OTHER = {"name": "Other Buyer", "town": "Slite"}
NOW = datetime.now(timezone.utc)
PURGE = NOW + timedelta(days=5 * 365)


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

    def test_purge_at_is_five_years_after_a_backdated_sale(self):
        contact = self._contact(self._sale().holder_contact_id)  # sold on SALE_DATE, entered today
        self.assertEqual(contact.purge_at, datetime(2026, 6, 1, tzinfo=ZoneInfo("Europe/Stockholm")))
        self.assertEqual(db.BuyerContact.purge_at_for("2024-02-29").date(), date(2029, 2, 28))

    def test_address_needs_the_contact_consent(self):
        with self.assertRaises(IntegrityError), db.DATABASE.atomic():
            db.BuyerContact.create(
                name=NAME, town="Visby", purge_at=PURGE, postal_address="Väg 1", created_by_user=self.owner
            )
        with self.assertRaises(IntegrityError), db.DATABASE.atomic():
            db.BuyerContact.create(
                name=NAME,
                town="Visby",
                postal_address="Väg 1",
                membership_optin_at=NOW,
                created_by_user=self.owner,
                purge_at=PURGE,
            )
        db.BuyerContact.create(
            name=NAME,
            town="Visby",
            postal_address="Väg 1",
            contact_consent_at=NOW,
            created_by_user=self.owner,
            purge_at=PURGE,
        )

    def test_email_and_phone_need_a_consent_or_the_membership_optin(self):
        for field in ("email", "phone"):
            with self.subTest(field=field):
                with self.assertRaises(IntegrityError), db.DATABASE.atomic():
                    db.BuyerContact.create(
                        name=NAME, town="Visby", purge_at=PURGE, created_by_user=self.owner, **{field: "x"}
                    )
                db.BuyerContact.create(
                    name=NAME,
                    town="Visby",
                    membership_optin_at=NOW,
                    created_by_user=self.owner,
                    purge_at=PURGE,
                    **{field: "x"},
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

    def test_the_new_buyer_must_be_another_person(self):
        same = {"name": NAME.upper(), "town": " visby "}
        with self.assertRaises(HerdTrackingConflict):
            record_herd_tracking(self.rabbit, self.gx1, "2022-01-01", "TRANSFER", self.manager, buyer=same)
        self.assertEqual(self._latest().id, self.first.id)
        self.assertEqual(db.BuyerContact.select().count(), 1)

    def test_a_resale_whose_buyer_is_erased_tolerates_later_writes(self):
        second = record_herd_tracking(self.rabbit, self.gx1, "2022-01-01", "TRANSFER", self.manager, buyer=OTHER)
        buyer_contact.erase_buyer_contact(second.holder_contact_id, self.admin)  # now a buyerless GX1 to GX1
        buyback = record_herd_tracking(self.rabbit, self.herds[1], "2022-02-01", "TRANSFER", self.manager)
        self.assertEqual(self._latest().id, buyback.id)

    def test_a_voided_resale_is_not_restored_without_its_buyer_nor_offered_for_it(self):
        second = record_herd_tracking(self.rabbit, self.gx1, "2022-01-01", "TRANSFER", self.manager, buyer=OTHER)
        void_herd_tracking(second.id, self.manager, "Fel rad")  # deletes its buyer
        void_op = db.HerdTracking.get_by_id(second.id).voided_operation_id
        history = herd_tracking_history(db.Individual.get_by_id(self.rabbit.id), self.manager)
        (row,) = [r for r in history["rows"] if r["id"] == second.id]
        self.assertFalse(row["can_undo_operation"])  # the hint runs the same I4 check
        with self.assertRaises(HerdTrackingConflict):
            undo_herd_tracking_operation(void_op, self.manager, "Ångra")

    def test_a_buyerless_move_cannot_go_in_before_a_sale_into_the_same_herd(self):
        event = {"kind": "TRANSFER", "date": "2021-05-01", "herd": "GX1"}
        with self.assertRaises(HerdTrackingConflict) as raised:
            correct_herd_tracking(self.rabbit, self.manager, None, [], [event])
        self.assertIn("utan köpare", raised.exception.detail)
        self.assertEqual(self._latest().id, self.first.id)

    def test_a_correction_cannot_write_it(self):
        event = {"kind": "TRANSFER", "date": "2022-01-01", "herd": "GX1"}
        with self.assertRaises(HerdTrackingConflict):
            correct_herd_tracking(self.rabbit, self.manager, None, [], [event])
        self.assertEqual(self._latest().id, self.first.id)

    def test_the_resale_stays_valid_after_both_buyers_are_erased(self):
        second = record_herd_tracking(self.rabbit, self.gx1, "2022-01-01", "TRANSFER", self.admin, buyer=OTHER)
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
        # Name and town only: the address, e-mail and phone the buyer gave never reach the history.
        expected = {"id": self.sale.holder_contact_id, "name": NAME, "town": "Visby"}
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
        inbox.assert_called_once_with(self.sale.id, False)
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

    def test_a_correction_of_the_sale_keeps_the_buyer_and_moves_its_purge_date(self):
        _op, (written,) = self._correct_date()  # the dialog sends no buyer: the server carries it over
        self.assertEqual(written.holder_contact_id, self.contact_id)
        self.assertEqual(self._contact(self.contact_id).purge_at, db.BuyerContact.purge_at_for("2021-07-01"))
        self.assertEqual(self._buyer_log(self.contact_id, "DELETE"), [])

    def test_undoing_that_correction_restores_the_old_sale_with_its_buyer(self):
        op, _written = self._correct_date()
        undo_herd_tracking_operation(op, self.manager, "Rätt datum ändå")
        self.assertEqual(self._latest().id, self.sale.id)
        self.assertEqual(self._latest().holder_contact_id, self.contact_id)
        self.assertIsNotNone(self._contact(self.contact_id))

    def test_a_correction_that_moves_the_sale_elsewhere_deletes_the_buyer(self):
        self._correct_date(herd="G2")
        self.assertIsNone(self._contact(self.contact_id))

    def test_a_correction_event_may_take_the_buyer(self):
        (written,) = self._correct_date(kind="CORRECTION")[1]
        self.assertEqual(written.holder_contact_id, self.contact_id)

    def test_two_buyers_for_one_event_are_refused(self):
        second = record_herd_tracking(self.rabbit, self.gx1, "2022-01-01", "TRANSFER", self.manager, buyer=OTHER)
        event = {"kind": "TRANSFER", "date": "2021-07-01", "herd": "GX1"}
        with self.assertRaises(HerdTrackingConflict) as raised:
            correct_herd_tracking(self.rabbit, self.manager, None, [self.sale.id, second.id], [event], "Fel")
        self.assertEqual(
            raised.exception.detail, "Rättelsen gäller flera försäljningar utanför genbanken. Rätta en i taget."
        )
        self.assertEqual(db.BuyerContact.select().count(), 2)

    def test_the_event_api_takes_no_holder_contact_id(self):
        event = {"kind": "TRANSFER", "date": "2021-07-01", "herd": "G2", "holder_contact_id": self.contact_id}
        (written,) = correct_herd_tracking(self.rabbit, self.manager, None, [self.sale.id], [event], "Fel köpare")
        self.assertIsNone(written.holder_contact_id)

    def test_the_reason_never_names_the_buyer(self):
        with self.assertRaises(HerdTrackingInvalid):
            void_herd_tracking(self.sale.id, self.owner, f"Såld till {NAME.upper()} av misstag")
        self.assertIsNotNone(self._contact(self.contact_id))

    def test_the_name_guard_takes_whole_words_of_typed_text_only(self):
        db.BuyerContact.update(name="Anna de Berg").where(db.BuyerContact.id == self.contact_id).execute()
        for reason in ("Såld till Anna", "Annas kanin", "såld till anna de berg"):
            with self.subTest(reason=reason), self.assertRaises(HerdTrackingInvalid):
                void_herd_tracking(self.sale.id, self.owner, reason)
        event = {"kind": "TRANSFER", "date": "2021-07-01", "herd": "GX1", "notes": "köpt av anna"}
        with self.assertRaises(HerdTrackingInvalid):  # a correction's notes too
            correct_herd_tracking(self.rabbit, self.manager, None, [self.sale.id], [event], "Fel datum")
        op, _written = self._correct_date()
        with self.assertRaises(HerdTrackingInvalid):  # and an undo's reason
            undo_herd_tracking_operation(op, self.manager, "Anna ville inte")
        with self.assertRaises(HerdTrackingInvalid):  # and a sale's note, such as a genebank change's reason
            record_herd_tracking(self.rabbit, self.herds[2], "2022-01-01", "TRANSFER", self.admin, notes="Bergs fel")
        # "annan" is no "Anna", and "de" alone is too short to be a name.
        latest = self._latest().id
        void_herd_tracking(latest, self.manager, "Såld till annan köpare, de ville inte")
        self.assertIsNotNone(db.HerdTracking.get_by_id(latest).voided_at)

    def test_a_hyphenated_name_is_matched_as_written(self):
        db.BuyerContact.update(name="Li-Bo").where(db.BuyerContact.id == self.contact_id).execute()
        for reason in ("Såld till Li-Bo", "Li-Bos kanin", "li bo"):
            with self.subTest(reason=reason), self.assertRaises(HerdTrackingInvalid):
                void_herd_tracking(self.sale.id, self.owner, reason)

    def test_the_undo_commands_own_reason_is_never_checked(self):
        db.BuyerContact.update(name="Van Den Berg").where(db.BuyerContact.id == self.contact_id).execute()
        attest = execute(self.manager, self.rabbit.id, lambda ctx: [RecordAttestation("GX1", "2021-07-01")])
        op = db.IndividualCommand.get(
            (db.IndividualCommand.individual == attest.id) & (db.IndividualCommand.command == "RecordAttestation")
        ).operation_id
        # "Ångrad av den som registrerade den": "den" is a word of the buyer's name, but the text is the system's.
        execute(self.manager, self.rabbit.id, lambda ctx: [Undo(op)])
        self.assertEqual(self._latest().id, self.sale.id)
        with self.assertRaises(HerdTrackingInvalid):  # typed by a user, the same word is refused
            void_herd_tracking(self.sale.id, self.owner, "den köparen ångrade sig")

    def test_a_system_reason_is_never_checked(self):
        db.BuyerContact.update(name="Avpromoverad").where(db.BuyerContact.id == self.contact_id).execute()
        void_all_for_unpromote(db.Individual.get_by_id(self.rabbit.id), self.admin)
        self.assertIsNone(self._latest())


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
        inbox.assert_called_once_with(self.sale.id, True)
        forget.assert_called_once_with("buyer_contact", self.contact_id)
        self.assertIsNone(self._contact(self.contact_id))
        sale = db.HerdTracking.get_by_id(self.sale.id)
        self.assertEqual((sale.voided_at, sale.holder_contact_id, sale.herd.herd), (None, None, "GX1"))
        log = self._buyer_log(self.contact_id, "DELETE")
        self.assertEqual([(r.new_data, r.changed_by) for r in log], [({"action": "radering"}, "man")])
        self.assertEqual(self._erase("man").status_code, 404)

    def test_only_admin_or_a_manager_of_the_genebank_holding_the_buyer(self):
        other = da.register_user("othermgr", "pass")
        other.add_role("manager", self.genebanks[1].id)
        helper = da.register_user("helper", "pass")
        helper.add_role("helper", self.genebanks[0].id)
        # 404 for who may not see the buyer, 403 for a helper who may.
        for username, status in (("owner", 404), ("othermgr", 404), ("helper", 403)):
            with self.subTest(username=username):
                self.assertEqual(self._erase(username).status_code, status)
        self.assertIsNotNone(self._contact(self.contact_id))
        self.assertEqual(self._erase("admin").status_code, 204)

    def test_the_manager_reads_every_kept_field_and_the_read_is_logged(self):
        helper = da.register_user("helper", "pass")
        helper.add_role("helper", self.genebanks[0].id)
        self._login("helper")
        self.assertEqual(self.client.get(f"/api/v2/buyer-contacts/{self.contact_id}").status_code, 403)
        self._login("owner")
        self.assertEqual(self.client.get(f"/api/v2/buyer-contacts/{self.contact_id}").status_code, 404)
        self._login("man")
        resp = self.client.get(f"/api/v2/buyer-contacts/{self.contact_id}")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        body = resp.get_json()
        self.assertEqual((body["name"], body["town"], body["email"]), (NAME, "Visby", "z@example.org"))
        self.assertIsNotNone(body["contact_consent_at"])
        self.assertEqual([r.changed_by for r in self._buyer_log(self.contact_id, "READ")], ["man"])

    def test_the_row_holding_the_buyer_decides_not_the_current_herd(self):
        record_herd_tracking(self.rabbit, self.herds[2], "2022-01-01", "TRANSFER", self.admin)  # now in Mellerud
        other = da.register_user("othermgr", "pass")
        other.add_role("manager", self.genebanks[1].id)
        self.assertEqual(self._erase("othermgr").status_code, 404)
        self.assertEqual(self._erase("man").status_code, 204)


class TestRetention(BuyerBase):
    def setUp(self):
        super().setUp()
        self.sale = self._sale(
            {**BUYER, "postal_address": "Väg 1", "phone": "070123", "contact_consent": True, "membership_optin": True}
        )
        self.contact_id = self.sale.holder_contact_id

    def test_five_years_after_the_sale_the_buyer_goes(self):
        purge_at = db.BuyerContact.purge_at_for(SALE_DATE)  # a sale entered late goes five years after its date
        self.assertEqual(buyer_contact.purge_expired(purge_at - timedelta(minutes=1)), 0)
        with mock.patch("utils.inbox_purge.erase_buyer_from_inbox", return_value=[]) as inbox:
            self.assertEqual(buyer_contact.purge_expired(purge_at), 1)
        inbox.assert_called_once_with(self.sale.id, False)
        self.assertIsNone(self._contact(self.contact_id))
        self.assertIsNone(db.HerdTracking.get_by_id(self.sale.id).holder_contact_id)
        self.assertEqual(
            [r.new_data for r in self._buyer_log(self.contact_id, "DELETE")], [{"action": "gallring_fem_ar"}]
        )

    def test_the_buyer_goes_when_the_rabbit_is_dead(self):
        self.assertEqual(buyer_contact.purge_dead(NOW), 0)
        db.Individual.update(death_date="2022-06-01").where(db.Individual.id == self.rabbit.id).execute()
        self.assertEqual(buyer_contact.purge_dead(NOW), 1)
        self.assertIsNone(self._contact(self.contact_id))
        self.assertIsNotNone(db.HerdTracking.get_by_id(self.sale.id))  # the sale stays
        self.assertEqual([r.new_data for r in self._buyer_log(self.contact_id, "DELETE")], [{"action": "gallring_dod"}])
        self.assertEqual(buyer_contact.purge_dead(NOW), 0)

    def test_the_contact_consent_goes_when_the_rabbit_is_sold_on(self):
        self.assertEqual(buyer_contact.purge_sold_on(NOW), 0)
        record_herd_tracking(self.rabbit, self.herds[1], "2022-01-01", "TRANSFER", self.manager)  # buyback
        self.assertEqual(buyer_contact.purge_sold_on(NOW), 1)
        contact = self._contact(self.contact_id)
        self.assertEqual((contact.name, contact.town), (NAME, "Visby"))
        self.assertEqual((contact.postal_address, contact.contact_consent_at), (None, None))
        self.assertEqual(contact.phone, "070123")  # kept while the membership yes holds
        self.assertIsNotNone(contact.membership_optin_at)
        self.assertEqual(buyer_contact.purge_sold_on(NOW), 0)  # one audit row, not one a night
        (log,) = self._buyer_log(self.contact_id, "UPDATE")
        self.assertEqual(sorted(log.changed_fields), ["contact_consent_at", "postal_address"])  # not the phone kept
        buyer_contact.purge_membership_optin(NOW + timedelta(days=366))
        contact = self._contact(self.contact_id)
        self.assertEqual((contact.phone, contact.membership_optin_at), (None, None))

    def test_without_the_membership_yes_e_mail_and_phone_go_and_the_queue_forgets_the_address(self):
        db.BuyerContact.update(membership_optin_at=None, email="z@example.org").where(
            db.BuyerContact.id == self.contact_id
        ).execute()
        record_herd_tracking(self.rabbit, self.herds[1], "2022-01-01", "TRANSFER", self.manager)
        with mock.patch("utils.buyer_contact.forget_recipient") as forget:
            buyer_contact.purge_sold_on(NOW)
        forget.assert_called_once_with("buyer_contact", self.contact_id)
        contact = self._contact(self.contact_id)
        self.assertEqual((contact.email, contact.phone), (None, None))

    def test_a_correction_moving_the_rabbit_on_counts_as_sold_on(self):
        event = {"kind": "CORRECTION", "date": "2022-01-01", "herd": "G2"}
        correct_herd_tracking(self.rabbit, self.manager, None, [], [event])
        self.assertEqual(buyer_contact.purge_sold_on(NOW), 1)

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
        buyer = {**BUYER, "email": "z@example.org", "contact_consent": True, "membership_optin": True}
        today = date.today()
        response = self._sell(buyer=buyer, date=(today - timedelta(days=20)).isoformat())  # within five years
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        sale = self._latest()
        self._login("man")
        self.client.get(f"/api/v2/individual/{RABBIT}/herd-tracking")
        record_herd_tracking(self.rabbit, self.herds[1], today - timedelta(days=10), "TRANSFER", self.manager)
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
        self.rabbit = db.Individual.get(db.Individual.number == "G1-2112")
        self.sale = record_herd_tracking(self.rabbit, gx1, "2026-01-01", "TRANSFER", self.manager, buyer=BUYER)
        self.item = self.make(documents=4)
        db.InboxItem.update(message=f"Köpare {NAME}").where(db.InboxItem.id == self.item.id).execute()
        self.certificate, self.proof, self.other, self.photo = list(self.item.documents.order_by(db.InboxDocument.id))
        reading = {"kopare": NAME}
        db.InboxDocument.update(interpretation=reading, proposal={"fields": reading}).where(
            db.InboxDocument.id != self.other.id
        ).execute()
        db.InboxDocument.update(  # the certificate the sale was registered from, with its masked copy
            herd_tracking_id=self.sale.id,
            individual=self.rabbit,
            public_path=self.write(f"inkorg/kopia/{self.certificate.id}.jpg"),
            mask_rects=[],
        ).where(db.InboxDocument.id == self.certificate.id).execute()
        # Another photo linked to the sale, a proof of the rabbit never linked to it, another rabbit's certificate.
        db.InboxDocument.update(herd_tracking_id=self.sale.id, doc_type="annat").where(
            db.InboxDocument.id == self.photo.id
        ).execute()
        db.InboxDocument.update(doc_type="bevis", individual=self.rabbit).where(
            db.InboxDocument.id == self.proof.id
        ).execute()
        db.InboxDocument.update(individual=db.Individual.get(db.Individual.number == "G1-2111")).where(
            db.InboxDocument.id == self.other.id
        ).execute()
        self.certificate = db.InboxDocument.get_by_id(self.certificate.id)

    def assertScrubbed(self, scrubbed, kept):  # pylint: disable=invalid-name
        for before in scrubbed:
            document = db.InboxDocument.get_by_id(before.id)
            self.assertEqual((document.original_path, document.interpretation, document.proposal), (None,) * 3)
            self.assertFalse(self.exists(before.original_path))  # removed after the commit
        for before in kept:
            self.assertEqual(db.InboxDocument.get_by_id(before.id).original_path, before.original_path)
            self.assertTrue(self.exists(before.original_path))
        certificate = db.InboxDocument.get_by_id(self.certificate.id)
        self.assertEqual(certificate.public_path, self.certificate.public_path)  # only the masked copy is left
        self.assertTrue(self.exists(certificate.public_path))
        self.assertNotIn(NAME, self.text(self.item))

    def test_an_erasure_takes_the_buyers_name_out_of_the_items(self):
        buyer_contact.erase_buyer_contact(self.sale.holder_contact_id, self.manager)
        self.assertScrubbed([self.certificate, self.photo, self.proof], [self.other])
        found = db.DATABASE.execute_sql(
            "SELECT count(*) FROM inbox_document d WHERE d::text ILIKE %s", (f"%{NAME}%",)
        ).fetchone()[0]
        self.assertEqual(found, 0)

    def test_a_void_clears_the_documents_linked_to_the_sale(self):
        void_herd_tracking(self.sale.id, self.manager, "Fel kanin")
        self.assertScrubbed([self.certificate, self.photo], [self.proof, self.other])

    def test_the_rabbits_death_clears_them_too(self):
        db.Individual.update(death_date=date(2026, 6, 1)).where(db.Individual.id == self.rabbit.id).execute()
        self.assertEqual(buyer_contact.purge_dead(NOW), 1)
        self.assertScrubbed([self.certificate, self.photo], [self.proof, self.other])

    def test_the_five_year_purge_too(self):
        buyer_contact.purge_expired(NOW + timedelta(days=5 * 366))
        self.assertScrubbed([self.certificate, self.photo], [self.proof, self.other])

    def test_after_the_originals_purge_only_what_is_left_is_cleared(self):
        purge.purge_originals(PURGE_NOW + timedelta(days=400))  # certificates and proofs, not other photos
        before = {d.id: d for d in db.InboxDocument.select()}
        self.assertEqual(buyer_contact.purge_expired(NOW + timedelta(days=5 * 366)), 1)
        after = {d.id: d for d in db.InboxDocument.select()}
        self.assertIsNotNone(before[self.photo.id].original_path)
        self.assertIsNone(after[self.photo.id].original_path)
        for document_id in (self.certificate.id, self.proof.id, self.other.id):
            self.assertEqual(after[document_id].original_path, before[document_id].original_path)

    def test_a_proof_of_a_buyerless_sale_goes_when_a_buyer_resells_in_the_same_herd(self):
        db.InboxDocument.update(herd_tracking_id=self.sale.id).where(db.InboxDocument.id == self.proof.id).execute()
        db.BuyerContact.delete().where(db.BuyerContact.id == self.sale.holder_contact_id).execute()  # erased later
        gx1 = db.Herd.get(db.Herd.herd == "GX1")
        record_herd_tracking(self.rabbit, gx1, "2026-02-01", "TRANSFER", self.manager, buyer=OTHER)
        purge.purge_sold_proofs(NOW)
        self.assertIsNone(db.InboxDocument.get_by_id(self.proof.id).original_path)

    def test_a_proof_of_a_corrected_sale_goes_when_the_rabbit_is_sold_on(self):
        db.InboxDocument.update(herd_tracking_id=self.sale.id).where(db.InboxDocument.id == self.proof.id).execute()
        event = {"kind": "TRANSFER", "date": "2026-01-02", "herd": "GX1"}
        (carried,) = correct_herd_tracking(self.rabbit, self.manager, None, [self.sale.id], [event], "Fel datum")
        self.assertEqual(carried.holder_contact_id, self.sale.holder_contact_id)  # the buyer went over
        purge.purge_sold_proofs(NOW)
        self.assertIsNotNone(db.InboxDocument.get_by_id(self.proof.id).original_path)
        record_herd_tracking(self.rabbit, self.herds[1], "2026-02-01", "TRANSFER", self.manager)
        purge.purge_sold_proofs(NOW)
        proof = db.InboxDocument.get_by_id(self.proof.id)
        self.assertIsNone(proof.original_path)
        self.assertEqual(proof.herd_tracking_id, self.sale.id)  # the provenance link stays

    def test_a_proof_goes_when_a_correction_moves_the_rabbit_on(self):
        db.InboxDocument.update(herd_tracking_id=self.sale.id).where(db.InboxDocument.id == self.proof.id).execute()
        purge.purge_sold_proofs(NOW)
        self.assertIsNotNone(db.InboxDocument.get_by_id(self.proof.id).original_path)
        correct_herd_tracking(
            self.rabbit, self.manager, None, [], [{"kind": "CORRECTION", "date": "2026-02-01", "herd": "G2"}]
        )
        purge.purge_sold_proofs(NOW)
        self.assertIsNone(db.InboxDocument.get_by_id(self.proof.id).original_path)


class TestQueueSale(ErasureTest):
    """POST …/overlat with the buyer outside the association (docs/inkorg.md)."""

    def setUp(self):
        super().setUp()
        db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför genbanken")
        self.item, document = self.uploaded()
        self.client.patch(f"/api/v2/inkorg/{self.item.id}/dokument/{document.id}", json={"doc_type": "bevis"})
        self.document = document

    def _sale(self, herd="GX1", buyer=BUYER):
        return self.post(
            f"/{self.item.id}/dokument/{self.document.id}/overlat",
            individual="G1-2111",
            herd=herd,
            date="2021-06-01",
            buyer=buyer,
        )

    def test_the_helper_registers_the_buyer_with_the_sale(self):
        resp = self._sale(buyer={**BUYER, "email": "z@example.org", "membership_optin": True})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        sale = db.HerdTracking.get_by_id(resp.get_json()["herd_tracking_id"])
        contact = db.BuyerContact.get_by_id(sale.holder_contact_id)
        self.assertEqual((contact.name, contact.town, contact.email), (NAME, "Visby", "z@example.org"))
        self.assertEqual(contact.created_by_user_id, self.helper.id)
        self.assertEqual(db.InboxDocument.get_by_id(self.document.id).herd_tracking_id, sale.id)

    def test_contact_details_without_the_yes_are_400_and_nothing_is_written(self):
        resp = self._sale(buyer={**BUYER, "postal_address": "Väg 1"})
        self.assertEqual(resp.status_code, 400, resp.get_json())
        self.assertIn("kryssat ja", resp.get_json()["detail"])
        self.assertEqual(db.BuyerContact.select().count(), 0)
        self.assertIsNone(db.InboxDocument.get_by_id(self.document.id).herd_tracking_id)

    def test_a_new_sale_outside_without_a_buyer_is_400(self):
        resp = self._sale(buyer=None)
        self.assertEqual(resp.status_code, 400, resp.get_json())
        self.assertIn("köparens namn och ort", resp.get_json()["detail"])
        self.assertIsNone(db.InboxDocument.get_by_id(self.document.id).herd_tracking_id)

    def test_a_buyer_for_a_herd_in_the_association_is_400(self):
        resp = self._sale(herd="G2")
        self.assertEqual(resp.status_code, 400, resp.get_json())
        self.assertEqual(db.BuyerContact.select().count(), 0)

    def test_a_late_sale_entered_as_a_correction_gets_its_buyer(self):
        rabbit = db.Individual.get(db.Individual.number == "G1-2111")
        record_herd_tracking(rabbit, self.herds[1], "2022-01-01", "TRANSFER", self.manager)
        self.login("man")
        self.post(f"/{self.item.id}/ta-over")
        resp = self._sale()
        self.assertEqual(resp.status_code, 200, resp.get_json())
        sale = db.HerdTracking.get_by_id(resp.get_json()["herd_tracking_id"])
        self.assertEqual(db.BuyerContact.get_by_id(sale.holder_contact_id).name, NAME)


class TestQueueProofOfARegisteredSale(ErasureTest):
    def test_linking_a_proof_to_a_sale_with_a_buyer_reads_no_buyer(self):
        db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför genbanken")
        item = self.item(0, documents=2)
        inbox.take(item, self.helper, over=False)
        certificate, proof = list(item.documents.order_by(db.InboxDocument.id))
        self.login("hjalp")
        sale = {"individual": "G1-2111", "herd": "GX1", "date": "2021-06-01"}
        resp = self.post(f"/{item.id}/dokument/{certificate.id}/overlat", **sale, buyer=BUYER)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        sale_id = resp.get_json()["herd_tracking_id"]
        self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{proof.id}", json={"doc_type": "bevis"})

        resp = self.post(f"/{item.id}/dokument/{proof.id}/overlat", **sale, buyer=OTHER)

        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json()["herd_tracking_id"], sale_id)
        self.assertEqual(db.InboxDocument.get_by_id(proof.id).herd_tracking_id, sale_id)
        self.assertEqual([c.name for c in db.BuyerContact.select()], [NAME])


def _items_locked_before_the_rabbit(statements):
    """The first lock on inbox_item comes before the first lock on individual (the queue's order)."""
    first = {}
    for index, (sql, _params) in enumerate(statements):
        for table, lock in (("inbox_item", "FOR UPDATE"), ("individual", "FOR NO KEY UPDATE")):
            if f'FROM "{table}"' in sql and lock in sql:
                first.setdefault(table, index)
    return "inbox_item" in first and first["inbox_item"] < first.get("individual", len(statements))


class TestLockOrder(PurgeTest):
    """A void that clears a sale's queue documents locks the items before the rabbit, as the queue does."""

    def setUp(self):
        super().setUp()
        self.gx1 = db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför genbanken")

    def _sale_with_a_document(self, rabbit, date):
        sale = record_herd_tracking(rabbit, self.gx1, date, "TRANSFER", self.manager, buyer=BUYER)
        item = self.make()
        db.InboxDocument.update(herd_tracking_id=sale.id).where(db.InboxDocument.item == item.id).execute()
        return sale, self.document(item)

    def test_void_correction_and_undo(self):
        rabbit = db.Individual.get(db.Individual.number == "G1-2112")
        sale, _document = self._sale_with_a_document(rabbit, "2026-01-01")
        op = new_operation_id()
        event = {"kind": "TRANSFER", "date": "2026-01-02", "herd": "GX1"}
        for name, run in (
            ("correction", lambda: correct_herd_tracking(rabbit, self.manager, op, [sale.id], [event], "Fel datum")),
            ("undo", lambda: undo_herd_tracking_operation(op, self.manager, "Rätt ändå")),
            ("void", lambda: void_herd_tracking(sale.id, self.manager, "Fel kanin")),
        ):
            with self.subTest(name), capture_sql() as statements:
                run()
            self.assertTrue(_items_locked_before_the_rabbit(statements), name)

    def test_unpromote_locks_them_in_its_own_transaction_and_removes_the_files_after_it(self):
        bunny = db.Bunny.create(
            breeding=_old_litter(self.herds[0]), slot_order=1, observed_sex="female", observed_color="bleighe"
        )
        self.login("admin")
        resp = _promote_without_certificate(self.client, bunny.id)
        self.assertEqual(resp.status_code, 201, resp.get_json())
        rabbit = db.Individual.get(db.Individual.number == resp.get_json()["individual"]["number"])
        sale, document = self._sale_with_a_document(rabbit, "2025-04-01")
        self.login("man")
        with capture_sql() as statements:
            resp = self.client.post(f"/api/v2/bunny/{bunny.id}/unpromote")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertTrue(_items_locked_before_the_rabbit(statements))
        self.assertIsNone(db.BuyerContact.get_or_none(db.BuyerContact.id == sale.holder_contact_id))
        self.assertFalse(self.exists(document.original_path))  # removed after the route's commit
