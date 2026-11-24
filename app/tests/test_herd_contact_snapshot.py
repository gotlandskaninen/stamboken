"""Transaction boundaries for reading herd contact details."""

import unittest
from contextlib import closing, contextmanager
from unittest.mock import patch

import psycopg2
import utils.data_access as da
import utils.database as db
import utils.herd_contact as contact
from peewee import DataError

from tests.database_test import _USE_POSTGRES
from tests.test_herd_contact import HerdContactTest
from tests.test_herd_contact_read import HerdContactReadTest


@unittest.skipUnless(_USE_POSTGRES, "transaction isolation needs PostgreSQL")
class TestHerdContactSnapshot(HerdContactTest):
    def test_herd_and_register_share_a_snapshot(self):
        herd_id = self._compare(self.herd, contact=self.main, email_privacy="public").id
        new_email = "updated@example.invalid"

        with db.snapshot_read():
            herd = db.Herd.get_by_id(herd_id)
            self.assertEqual(herd.email_privacy, "public")
            with closing(psycopg2.connect(dbname=db.DATABASE.database, **db.DATABASE.connect_params)) as writer:
                with writer.cursor() as cursor:
                    cursor.execute("UPDATE herd SET email_privacy = 'private' WHERE herd_id = %s", (herd_id,))
                    cursor.execute("UPDATE member SET email = %s WHERE member_id = %s", (new_email, self.main.id))
                writer.commit()

            self.assertEqual(herd.filtered_dict(self.viewer)["email"], self.main.email)
            self.assertEqual(db.DB_PROXY.execute_sql("SHOW transaction_read_only").fetchone()[0], "on")

        current = db.Herd.get_by_id(herd_id)
        self.assertEqual(current.email_privacy, "private")
        self.assertEqual(contact.herd_contact(current).rows["email"].value, new_email)

    def test_snapshot_read_preserves_the_outer_transaction(self):
        with db.DB_PROXY.atomic() as outer:
            herd = db.Herd.get_by_id(self.herd.id)
            with db.snapshot_read():
                db.Herd.update(email_privacy="private").where(db.Herd.id == herd.id).execute()
            self.assertEqual(db.Herd.get_by_id(herd.id).email_privacy, "private")
            outer.rollback()

        self.assertEqual(db.Herd.get_by_id(herd.id).email_privacy, herd.email_privacy)

    def test_sql_error_in_snapshot_allows_outer_write_to_commit(self):
        with db.DB_PROXY.atomic():
            db.Herd.update(email_privacy="private").where(db.Herd.id == self.herd.id).execute()
            with self.assertRaises(DataError), db.snapshot_read():
                db.DB_PROXY.execute_sql("SELECT 1 / 0")

        self.assertEqual(db.Herd.get_by_id(self.herd.id).email_privacy, "private")


@unittest.skipUnless(_USE_POSTGRES, "transaction isolation needs PostgreSQL")
class TestHerdContactReadPaths(HerdContactReadTest):
    @contextmanager
    def assert_repeatable_read(self, module, name):
        original = getattr(module, name)
        levels = []

        def record_isolation(*args, **kwargs):
            levels.append(db.DB_PROXY.execute_sql("SHOW transaction_isolation").fetchone()[0])
            return original(*args, **kwargs)

        with patch.object(module, name, record_isolation):
            yield
        self.assertEqual(levels, ["repeatable read"], name)

    def test_get_herd(self):
        with self.assert_repeatable_read(da, "fetch_user_info"), self.assert_repeatable_read(contact, "herd_contacts"):
            herd = da.get_herd(self.herd.herd, self.manager.uuid)
        self.assertEqual(herd["email"], self.main.email)

    def test_genebank_get_herds(self):
        with self.assert_repeatable_read(contact, "herd_contacts"):
            herds = self.genebanks[0].get_herds(self.manager)
        self.assertIn(self.main.email, [herd.get("email") for herd in herds])

    def test_admin_get_herd(self):
        import herdbook

        with (
            self.assert_repeatable_read(herdbook, "_resolve_admin_herd"),
            self.assert_repeatable_read(herdbook, "check_genebank_manager_access"),
            self.assert_repeatable_read(contact, "herd_contacts"),
        ):
            herd = self._get(self.manager, f"/api/manage/herd/{self.herd.herd}")
        self.assertEqual(herd["email"], self.main.email)
