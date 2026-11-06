"""The deferred trigger bumps one global version once per transaction."""

import threading
from datetime import date

import psycopg2
import utils.database as db

from tests.database_test import DatabaseTest
from tests.ht_helpers import _void, ht_row


def _connect():
    return psycopg2.connect(database=db.DATABASE.database, **db.DATABASE.connect_params)


class TestGeneticsVersion(DatabaseTest):
    def v(self):
        return db.read_genetics_version()

    def test_relevant_save_bumps_irrelevant_save_does_not(self):
        ind = self.individuals[0]
        before = self.v()
        ind.notes = "bara en anteckning"
        ind.save()  # peewee writes every column
        self.assertEqual(self.v(), before)
        ind.castration_date = date(2026, 1, 1)
        ind.save()
        self.assertEqual(self.v(), before + 1)

    def test_breeding_parent_change_bumps(self):
        b = self.individuals[0].breeding
        before = self.v()
        b.birth_notes = "x"
        b.save()
        self.assertEqual(self.v(), before)
        other = next(p for p in self.parents if p.id not in (b.father_id, b.mother_id))
        b.father = other
        b.save()
        self.assertEqual(db.Breeding.get_by_id(b.id).father_id, other.id)
        self.assertEqual(self.v(), before + 1)

    def test_once_per_transaction_savepoint_and_rollback(self):
        before = self.v()
        with db.DATABASE.atomic():
            for ind in self.individuals[:3]:
                ind.death_date = date(2026, 2, 1)
                ind.save()
            with db.DATABASE.atomic():  # savepoint, released
                self.individuals[3].sex = "male" if self.individuals[3].sex != "male" else "female"
                self.individuals[3].save()
        self.assertEqual(self.v(), before + 1)
        try:
            with db.DATABASE.atomic():
                self.individuals[4].death_date = date(2026, 2, 2)
                self.individuals[4].save()
                raise RuntimeError
        except RuntimeError:
            pass
        self.assertEqual(self.v(), before + 1)

    def test_herd_tracking_insert_and_void_bump(self):
        before = self.v()
        row = ht_row(
            "TRANSFER", individual=self.individuals[0], herd=self.herds[0], herd_tracking_date=date(2026, 1, 2)
        )
        self.assertEqual(self.v(), before + 1)
        _void(row, self.admin)
        self.assertEqual(self.v(), before + 2)

    def test_consecutive_autocommit_statements_each_bump(self):
        before = self.v()
        self.assertFalse(db.Herd.get_by_id(self.herds[0].id).is_active)  # Herd.is_active defaults to False
        db.Herd.update(is_active=True).where(db.Herd.id == self.herds[0].id).execute()
        db.Herd.update(is_active=False).where(db.Herd.id == self.herds[0].id).execute()
        self.assertEqual(self.v(), before + 2)

    def test_round_end_date_bumps(self):
        before = self.v()
        db.YearlyReportRound.create(report_year=2031, end_date=date(2032, 3, 30), created_by=self.admin)
        self.assertEqual(self.v(), before + 1)

    def test_version_lock_is_taken_at_commit_not_at_first_write(self):
        """A long transaction (e.g. PDF signing) does not block others until it commits."""
        written = threading.Event()
        release = threading.Event()
        errors = []

        def slow_writer():
            conn = _connect()
            try:
                cur = conn.cursor()
                cur.execute("UPDATE individual SET sex = 'male' WHERE individual_id = %s", (self.individuals[1].id,))
                written.set()
                release.wait(5)
                conn.commit()
            except Exception as exc:  # surfaced below
                errors.append(exc)
            finally:
                conn.close()

        before = self.v()
        t = threading.Thread(target=slow_writer)
        t.start()
        self.assertTrue(written.wait(5))
        other = _connect()
        try:
            cur = other.cursor()
            cur.execute("SET lock_timeout = '500ms'")
            cur.execute("UPDATE individual SET sex = 'female' WHERE individual_id = %s", (self.individuals[2].id,))
            other.commit()  # would time out if the first writer already held the version row
        finally:
            other.close()
        release.set()
        t.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(self.v(), before + 2)

    def test_version_bump_cannot_deadlock_with_breeding_lock(self):
        """A holds an individual write and then wants Breeding; B holds Breeding and writes another individual.

        With an immediate trigger A would hold the version row while waiting for Breeding and B
        would wait for the version row while holding Breeding: a deadlock. Deferred, B never
        touches the version row before its commit, so both commit.
        """
        b = self.individuals[0].breeding
        x, y = self.individuals[0].id, self.individuals[1].id
        a_written = threading.Event()
        b_locked = threading.Event()
        errors = []

        def session_a():
            conn = _connect()
            try:
                cur = conn.cursor()
                cur.execute("SET lock_timeout = '3s'")
                cur.execute("UPDATE individual SET death_date = '2026-03-01' WHERE individual_id = %s", (x,))
                a_written.set()
                if not b_locked.wait(5):
                    raise RuntimeError("B never locked breeding")
                cur.execute("SELECT 1 FROM breeding WHERE breeding_id = %s FOR UPDATE", (b.id,))
                conn.commit()
            except Exception as exc:  # surfaced below
                errors.append(exc)
                a_written.set()
            finally:
                conn.close()

        def session_b():
            conn = _connect()
            try:
                cur = conn.cursor()
                cur.execute("SET lock_timeout = '3s'")
                if not a_written.wait(5):
                    raise RuntimeError("A never wrote")
                cur.execute("SELECT 1 FROM breeding WHERE breeding_id = %s FOR UPDATE", (b.id,))
                b_locked.set()
                cur.execute("UPDATE individual SET death_date = '2026-03-01' WHERE individual_id = %s", (y,))
                conn.commit()
            except Exception as exc:  # surfaced below
                errors.append(exc)
                b_locked.set()
            finally:
                conn.close()

        before = self.v()
        threads = [threading.Thread(target=session_a), threading.Thread(target=session_b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(errors, [])
        self.assertEqual(self.v(), before + 2)

    def test_triggers_and_row_exist(self):
        rows = db.DATABASE.execute_sql("SELECT tgname FROM pg_trigger WHERE tgname LIKE 'genetics_change_%%'")
        names = {r[0] for r in rows}
        tables = ("individual", "breeding", "herd", "herd_tracking", "yearlyreportround")
        expected = {f"genetics_change_{t}_iud" for t in tables}
        expected |= {f"genetics_change_{t}_upd" for t in tables if t != "herd_tracking"}
        self.assertEqual(names, expected)
        self.assertEqual(db.DATABASE.execute_sql("SELECT count(*) FROM genetics_version").fetchone()[0], 1)

    def test_init_keeps_existing_triggers(self):
        """init() on an existing database creates only missing triggers: no drop, no gap without bumps."""
        query = "SELECT tgname, oid FROM pg_trigger WHERE tgname LIKE 'genetics_change_%%'"
        before = dict(db.DATABASE.execute_sql(query).fetchall())
        db.init()
        self.assertEqual(dict(db.DATABASE.execute_sql(query).fetchall()), before)
