"""Transaction boundaries for reading herd contact details."""

import unittest
from contextlib import closing

import psycopg2
import utils.database as db
from utils.herd_contact import herd_contact

from tests.database_test import _USE_POSTGRES
from tests.test_herd_contact import HerdContactTest


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
        self.assertEqual(herd_contact(current).rows["email"].value, new_email)

    def test_snapshot_read_preserves_the_outer_transaction(self):
        with db.DB_PROXY.atomic() as outer:
            herd = db.Herd.get_by_id(self.herd.id)
            with db.snapshot_read():
                db.Herd.update(email_privacy="private").where(db.Herd.id == herd.id).execute()
            self.assertEqual(db.Herd.get_by_id(herd.id).email_privacy, "private")
            outer.rollback()

        self.assertEqual(db.Herd.get_by_id(herd.id).email_privacy, herd.email_privacy)
