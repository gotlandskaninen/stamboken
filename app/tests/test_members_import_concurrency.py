"""Races between `flask members import` and matrikel writes.

The importer looks up the membership it is about to reconcile (and the one it
adopts) before it holds any lock on it. Without a re-read FOR UPDATE inside the
group's transaction, the save writes that stale instance back in full and
silently undoes an admin deactivation or a member's consent withdrawal that
committed in between. Needs PostgreSQL row locks — SQLite cannot express it.
"""

import os
import tempfile
import threading
import unittest
from unittest.mock import patch

import cli.members as members_cli_module
import utils.database as db
from cli.members import members_cli
from click.testing import CliRunner
from flask.cli import ScriptInfo
from herdbook import APP

from tests.database_test import _USE_POSTGRES, DatabaseTest
from tests.test_members_import import HEADER, _row


@unittest.skipUnless(_USE_POSTGRES, "the importer's FOR UPDATE re-read needs PostgreSQL")
class TestImportRaces(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.runner = CliRunner()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.csv_dir = tmp.name

    def _csv_path(self, content: str) -> str:
        """Write the CSV from the main thread and hand the worker an absolute
        path — CliRunner.isolated_filesystem() chdirs the whole process, which
        is not safe while a second thread is running."""
        path = os.path.join(self.csv_dir, "matrikel.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def _import_thread(self, csv_path: str, results: list, failures: list) -> threading.Thread:
        def run():
            try:
                results.append(
                    self.runner.invoke(
                        members_cli,
                        ["import", csv_path],
                        obj=ScriptInfo(create_app=lambda: APP),
                    )
                )
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(exc)
            finally:
                try:
                    db.DB_PROXY.close()
                except Exception:  # pylint: disable=broad-except
                    pass

        return threading.Thread(target=run)

    def _deactivate_and_withdraw(self, membership_id: int, deactivate: bool = True) -> None:
        """What the matrikel admin and the member do while the import reads:
        deactivate the membership and withdraw the e-post consent."""
        row = db.Membership.get_by_id(membership_id)
        if deactivate:
            row.membership_status = "inactive"
        row.publication_consent = {"email": False}
        row.save(
            only=[
                db.Membership.membership_status,
                db.Membership.publication_consent,
                db.Membership.updated_at,
            ]
        )

    def _run_released(self, thread, entered, release, membership_id, where: str, deactivate: bool = True):
        thread.start()
        self.assertTrue(entered.wait(timeout=10), f"the import never reached {where}")
        self._deactivate_and_withdraw(membership_id, deactivate)
        release.set()
        thread.join(timeout=20)
        self.assertFalse(
            thread.is_alive(), "the import is still blocked after the join timeout — a lock never released"
        )

    def _reconcile_race(self, deactivate: bool):
        """Merge rule 1 (reconcile): the paused import holds a pre-transaction
        read of an active membership with e-post consent. The member withdraws
        consent, and the admin deactivates the membership if `deactivate`;
        returns the membership and the import's result after the release."""
        ms = db.Membership.create(
            member_number=6,
            membership_status="active",
            publication_consent={"email": True},
        )
        db.Member.create(
            membership=ms,
            role="huvudmedlem",
            first_name="Anna",
            last_name="Svensson",
            email="anna@example.com",
        )
        ms_id = ms.id
        csv_path = self._csv_path(
            HEADER + _row(nr="6", name="Anna Svensson", adress="Storgatan 1", epost="anna@example.com")
        )

        entered, release = threading.Event(), threading.Event()
        original_get_or_none = db.Membership.get_or_none
        results, failures = [], []

        def paused_get_or_none(*args, **kwargs):
            row = original_get_or_none(*args, **kwargs)
            # Pause AFTER the pre-transaction lookup — from here on the
            # instance the importer carries is stale.
            if row is not None and row.id == ms_id and not entered.is_set():
                entered.set()
                assert release.wait(timeout=10), "the test never released the paused import"
            return row

        with patch.object(db.Membership, "get_or_none", paused_get_or_none):
            thread = self._import_thread(csv_path, results, failures)
            self._run_released(thread, entered, release, ms_id, "its pre-transaction lookup", deactivate)

        self.assertEqual(failures, [])
        self.assertEqual(results[0].exit_code, 0, results[0].output)
        return db.Membership.get_by_id(ms_id), results[0]

    def test_reimport_vs_consent_withdrawal(self):
        """The released import fills the empty address and leaves the withdrawn
        consent alone."""
        reloaded, _result = self._reconcile_race(deactivate=False)
        self.assertEqual(reloaded.address, "Storgatan 1")
        self.assertEqual(reloaded.membership_status, "active")
        self.assertEqual(reloaded.publication_consent, {"email": False})

    def test_reimport_vs_deactivation_and_consent_withdrawal(self):
        """The deactivation commits between the lookup and the lock. The check on
        the locked row sees it: the group is parked, so nothing is written
        and both the deactivation and the withdrawal stand."""
        reloaded, result = self._reconcile_race(deactivate=True)
        self.assertIsNone(reloaded.address)
        self.assertEqual(reloaded.membership_status, "inactive")
        self.assertEqual(reloaded.publication_consent, {"email": False})
        self.assertIn("inaktivt medlemskap", result.output)

    def test_reimport_vs_renumbering(self):
        """The paused import holds a pre-transaction lookup of
        membership 6. The admin renumbers that row to 7 before the import is
        released. Re-locking by the remembered id would reconcile the Nr 6
        group — address, persons, herd links — onto what is now membership 7;
        resolving by number under the lock finds nothing and the group is
        created as the new membership it now is."""
        ms = db.Membership.create(member_number=6, membership_status="active")
        db.Member.create(
            membership=ms,
            role="huvudmedlem",
            first_name="Anna",
            last_name="Svensson",
            email="anna@example.com",
        )
        ms_id = ms.id
        csv_path = self._csv_path(
            HEADER + _row(nr="6", name="Anna Svensson", adress="Storgatan 1", epost="anna@example.com")
        )

        entered, release = threading.Event(), threading.Event()
        original_get_or_none = db.Membership.get_or_none
        results, failures = [], []

        def paused_get_or_none(*args, **kwargs):
            row = original_get_or_none(*args, **kwargs)
            if row is not None and row.id == ms_id and not entered.is_set():
                entered.set()
                assert release.wait(timeout=10), "the test never released the paused import"
            return row

        with patch.object(db.Membership, "get_or_none", paused_get_or_none):
            thread = self._import_thread(csv_path, results, failures)
            thread.start()
            self.assertTrue(entered.wait(timeout=10), "the import never reached its pre-transaction lookup")
            moved = db.Membership.get_by_id(ms_id)
            moved.member_number = 7
            moved.save(only=[db.Membership.member_number, db.Membership.updated_at])
            release.set()
            thread.join(timeout=20)
        self.assertFalse(
            thread.is_alive(), "the import is still blocked after the join timeout — a lock never released"
        )

        self.assertEqual(failures, [])
        self.assertEqual(results[0].exit_code, 0, results[0].output)
        moved = db.Membership.get_by_id(ms_id)
        self.assertEqual(moved.member_number, 7)
        self.assertIsNone(moved.address)  # the Nr 6 group did not land here
        self.assertEqual(db.Member.select().where(db.Member.membership == moved).count(), 1)
        created = db.Membership.get(db.Membership.member_number == 6)
        self.assertNotEqual(created.id, ms_id)
        self.assertEqual(created.address, "Storgatan 1")
        self.assertEqual(
            [p.role for p in db.Member.select().where(db.Member.membership == created)],
            ["huvudmedlem"],
        )

    def test_adoption_vs_renumbering(self):
        """The paused import has picked Eva Lund's number-less
        active membership for adoption. Before it is released the admin gives
        that membership number 77. The re-check on the locked row must refuse
        the adoption — the CSV number must not overwrite an administrative one
        — and the Nr 12 group is created as the new membership it now is."""
        ms = db.Membership.create(membership_status="active")
        db.Member.create(
            membership=ms,
            role="huvudmedlem",
            first_name="Eva",
            last_name="Lund",
            email="eva@example.com",
        )
        ms_id = ms.id
        csv_path = self._csv_path(HEADER + _row(nr="12", name="Eva Lund", epost="eva@example.com", bet="2026"))

        entered, release = threading.Event(), threading.Event()
        original_find = members_cli_module._find_adoptable_membership
        results, failures = [], []

        def paused_find(main):
            found = original_find(main)
            if found is not None and not entered.is_set():
                entered.set()
                assert release.wait(timeout=10), "the test never released the paused import"
            return found

        with patch.object(members_cli_module, "_find_adoptable_membership", paused_find):
            thread = self._import_thread(csv_path, results, failures)
            thread.start()
            self.assertTrue(entered.wait(timeout=10), "the import never reached the adoption lookup")
            numbered = db.Membership.get_by_id(ms_id)
            numbered.member_number = 77
            numbered.save(only=[db.Membership.member_number, db.Membership.updated_at])
            release.set()
            thread.join(timeout=20)
        self.assertFalse(
            thread.is_alive(), "the import is still blocked after the join timeout — a lock never released"
        )

        self.assertEqual(failures, [])
        self.assertEqual(results[0].exit_code, 0, results[0].output)
        numbered = db.Membership.get_by_id(ms_id)
        self.assertEqual(numbered.member_number, 77)
        self.assertIsNone(numbered.payment_note)  # the Nr 12 group did not land here
        created = db.Membership.get(db.Membership.member_number == 12)
        self.assertNotEqual(created.id, ms_id)
        self.assertEqual(created.payment_note, "2026")
        self.assertEqual(
            [p.role for p in db.Member.select().where(db.Member.membership == created)],
            ["huvudmedlem"],
        )

    def _adoption_race(self, deactivate: bool):
        """Merge rule 2 (adoption): same race on the path that assigns the
        member number. Returns the candidate membership and the import's result."""
        ms = db.Membership.create(membership_status="active", publication_consent={"email": True})
        db.Member.create(
            membership=ms,
            role="huvudmedlem",
            first_name="Eva",
            last_name="Lund",
            email="eva@example.com",
        )
        ms_id = ms.id
        csv_path = self._csv_path(HEADER + _row(nr="12", name="Eva Lund", epost="eva@example.com", bet="2026"))

        entered, release = threading.Event(), threading.Event()
        original_find = members_cli_module._find_adoptable_membership
        results, failures = [], []

        def paused_find(main):
            found = original_find(main)
            if found is not None and not entered.is_set():
                entered.set()
                assert release.wait(timeout=10), "the test never released the paused import"
            return found

        with patch.object(members_cli_module, "_find_adoptable_membership", paused_find):
            thread = self._import_thread(csv_path, results, failures)
            self._run_released(thread, entered, release, ms_id, "the adoption lookup", deactivate)

        self.assertEqual(failures, [])
        self.assertEqual(results[0].exit_code, 0, results[0].output)
        return db.Membership.get_by_id(ms_id), results[0]

    def test_adoption_vs_consent_withdrawal(self):
        """The number lands and the withdrawal stands."""
        adopted, _result = self._adoption_race(deactivate=False)
        self.assertEqual(adopted.member_number, 12)
        self.assertEqual(adopted.payment_note, "2026")
        self.assertEqual(adopted.membership_status, "active")
        self.assertEqual(adopted.publication_consent, {"email": False})

    def test_adoption_vs_deactivation_and_consent_withdrawal(self):
        """The deactivation commits between the lookup and the lock: the import
        parks the candidate (add_person refuses inactive memberships), so
        no number or field is written and both changes stand."""
        adopted, result = self._adoption_race(deactivate=True)
        self.assertIsNone(adopted.member_number)
        self.assertIsNone(adopted.payment_note)
        self.assertEqual(adopted.membership_status, "inactive")
        self.assertEqual(adopted.publication_consent, {"email": False})
        self.assertIn("inaktivt medlemskap", result.output)
