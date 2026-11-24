#!/usr/bin/env python3
"""
The nightly anonymization of persons whose membership ended 12 calendar months ago (#70).

Only runs on PostgreSQL (interval arithmetic). Names and addresses are made up; e-mail uses example.invalid.
"""

import os
import threading
import time
import unittest
from datetime import date, datetime, timezone
from unittest import mock

import herdbook
import utils.data_access as da
import utils.database as db
import utils.matrikel as matrikel

from tests.database_test import DatabaseTest

_USE_POSTGRES = bool(os.getenv("POSTGRES_HOST")) and bool(os.getenv("POSTGRES_DB"))

NOW = datetime(2026, 11, 16, 3, 55, tzinfo=timezone.utc)
OLD = date(2025, 11, 1)  # more than 12 calendar months before NOW
YOUNG = date(2025, 12, 1)  # less than 12 calendar months before NOW


def _membership(number, status="inactive"):
    return db.Membership.create(
        member_number=number,
        membership_status=status,
        address="Exempelvägen 1",
        postal_code="12345",
        city="Exempelby",
        organization_name="Testföreningen",
        organization_number="552222-0002",
    )


def _person(membership, end_date=None, role="familjemedlem", user=None):
    return db.Member.create(
        membership=membership,
        first_name="Test",
        last_name=f"Person{db.Member.select().count()}",
        email="person@example.invalid",
        role=role,
        end_date=end_date,
        user=user,
    )


def _erased(person):
    return matrikel.is_anonymized(db.Member.get_by_id(person.id))


def _address_and_organization(membership):
    row = db.Membership.get_by_id(membership.id)
    return row.address, row.organization_name, row.organization_number


@unittest.skipUnless(_USE_POSTGRES, "interval arithmetic requires PostgreSQL")
class TestAnonymizeEndedPersons(DatabaseTest):
    def test_membership_ended_over_12_months_ago_is_anonymized(self):
        ended = _membership(101)
        main = _person(ended, OLD, role="huvudmedlem", user=self.viewer)  # viewer is on every account: no hold
        family = _person(ended, OLD)

        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (2, 0, []))

        self.assertTrue(_erased(main) and _erased(family))
        self.assertIsNone(db.Member.get_by_id(main.id).user_id)
        self.assertEqual(_address_and_organization(ended), (None, None, None))
        audit = db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_anonymized")
        self.assertEqual([row.actor_id for row in audit], [None, None])
        # A second night changes nothing.
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, 0, []))

    def test_membership_ended_less_than_12_months_ago_stays(self):
        main = _person(_membership(102), YOUNG, role="huvudmedlem")
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, 0, []))
        self.assertFalse(_erased(main))

    def test_ended_membership_waits_for_its_last_person(self):
        ended = _membership(103)
        family = _person(ended, OLD)
        main = _person(ended, YOUNG, role="huvudmedlem")
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, 0, []))
        self.assertFalse(_erased(family) or _erased(main))
        self.assertEqual(_address_and_organization(ended), ("Exempelvägen 1", "Testföreningen", "552222-0002"))

    def test_exactly_12_calendar_months_across_a_leap_day(self):
        # 12 months before 2028-03-01 is 2027-03-01; 365 days would be 2027-03-02, as 2028 has a February 29.
        due = _person(_membership(115), date(2027, 2, 28), role="huvudmedlem")
        kept = _person(_membership(116), date(2027, 3, 1), role="huvudmedlem")
        household = _membership(119, status="active")
        _person(household, role="huvudmedlem")
        left_due, left_kept = _person(household, date(2027, 2, 28)), _person(household, date(2027, 3, 1))
        now = datetime(2028, 3, 1, 3, 55, tzinfo=timezone.utc)
        self.assertEqual(matrikel.anonymize_ended_persons(now), (2, 0, []))
        self.assertTrue(_erased(due) and _erased(left_due))
        self.assertFalse(_erased(kept) or _erased(left_kept))

    def test_an_anonymized_person_with_the_latest_end_date_still_counts(self):
        ended = _membership(117)
        family = _person(ended, OLD)
        db.Member.create(
            membership=ended,
            first_name=matrikel.ANONYMIZED_FIRST_NAME,
            last_name=matrikel.ANONYMIZED_LAST_NAME,
            role="huvudmedlem",
            end_date=YOUNG,
        )
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, 0, []))
        self.assertFalse(_erased(family))

    def test_each_hold_role_holds_and_viewer_does_not(self):
        for number, level in enumerate(("admin", "matrikel_admin", "manager"), start=120):
            with self.subTest(level=level):
                account = da.register_user(f"konto{number}", "pass")
                account.add_role(level, self.genebanks[0].id if level == "manager" else None)
                ended = _membership(number)
                _person(ended, OLD, role="huvudmedlem", user=account)
                self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, 0, [(ended.id, None, "role")]))
                db.Membership.update(membership_status="active").where(db.Membership.id == ended.id).execute()
                db.Member.update(end_date=None).where(db.Member.membership == ended).execute()

    def test_legacy_owner_holds_a_person_who_left_an_active_household(self):
        active = _membership(118, status="active")
        _person(active, role="huvudmedlem")
        left = _person(active, OLD, user=self.owner)  # owner of herds[0]
        db.Herd.update(is_active=True).where(db.Herd.id == self.herds[0].id).execute()
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, 0, [(active.id, left.id, "active_herd")]))
        self.assertFalse(_erased(left))

    def test_active_herd_holds_the_ended_membership(self):
        ended = _membership(104)
        main = _person(ended, OLD, role="huvudmedlem")
        db.Herd.update(membership=ended, is_active=True).where(db.Herd.id == self.herds[1].id).execute()
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, 0, [(ended.id, None, "active_herd")]))
        self.assertFalse(_erased(main))

    def test_a_role_on_any_person_holds_the_ended_membership(self):
        ended = _membership(105)
        main = _person(ended, OLD, role="huvudmedlem")
        family = _person(ended, OLD, user=self.manager)
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, 0, [(ended.id, None, "role")]))
        self.assertFalse(_erased(main) or _erased(family))

    def test_legacy_owner_entry_holds_only_on_an_active_herd(self):
        ended = _membership(106)
        main = _person(ended, OLD, role="huvudmedlem", user=self.owner)  # owner of herds[0]
        db.Herd.update(is_active=True).where(db.Herd.id == self.herds[0].id).execute()
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, 0, [(ended.id, None, "active_herd")]))
        db.Herd.update(is_active=False).where(db.Herd.id == self.herds[0].id).execute()
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (1, 0, []))
        self.assertTrue(_erased(main))

    def test_active_membership_loses_only_its_long_ended_persons(self):
        active = _membership(107, status="active")
        main = _person(active, role="huvudmedlem")
        gone = _person(active, OLD)
        recent = _person(active, YOUNG)
        held = _person(active, OLD, user=self.manager)
        # The household's herd does not hold a person who left it.
        db.Herd.update(membership=active, is_active=True).where(db.Herd.id == self.herds[1].id).execute()

        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (1, 0, [(active.id, held.id, "role")]))

        self.assertTrue(_erased(gone))
        self.assertFalse(_erased(main) or _erased(recent) or _erased(held))
        membership = db.Membership.get_by_id(active.id)
        self.assertEqual((membership.membership_status, membership.address), ("active", "Exempelvägen 1"))
        self.assertEqual(
            (membership.organization_name, membership.organization_number), ("Testföreningen", "552222-0002")
        )

    def test_only_the_own_application_is_scrubbed_for_a_member_who_came_back(self):
        old = _person(_membership(111), OLD, role="huvudmedlem")
        new = _person(_membership(112, status="active"), role="huvudmedlem")
        db.Member.update(last_name=old.last_name).where(db.Member.id == new.id).execute()

        def application(status, created_member=None):
            return db.MemberApplication.create(
                first_name="Test",
                last_name=old.last_name,
                email="person@example.invalid",
                gdpr_consented_at=datetime(2024, 1, 1),
                status=status,
                created_member=created_member,
            ).id

        own = application("approved", old)
        rejoined = application("approved", new)
        pending = application("pending")

        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (1, 0, []))

        rows = {a.id: a for a in db.MemberApplication.select()}
        self.assertEqual(rows[own].first_name, matrikel.ANONYMIZED_FIRST_NAME)
        self.assertEqual((rows[rejoined].first_name, rows[rejoined].status), ("Test", "approved"))
        self.assertEqual((rows[pending].first_name, rows[pending].status), ("Test", "pending"))
        self.assertFalse(_erased(new))

    def test_a_household_retired_after_the_candidate_query_keeps_its_address(self):
        active = _membership(110, status="active")
        main = _person(active, role="huvudmedlem")
        family = _person(active, OLD)
        candidates = matrikel._memberships_with_ended_persons

        def candidates_then_retire(cutoff):
            found = candidates(cutoff)
            matrikel.retire_membership(active, self.admin)  # the main member's 12 months start today
            return found

        with mock.patch.object(matrikel, "_memberships_with_ended_persons", side_effect=candidates_then_retire):
            self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, 0, []))
        self.assertFalse(_erased(family) or _erased(main))
        self.assertEqual(_address_and_organization(active), ("Exempelvägen 1", "Testföreningen", "552222-0002"))

    def test_a_role_granted_while_the_job_decides_holds_the_membership(self):
        ended = _membership(113)
        main = _person(ended, OLD, role="huvudmedlem", user=self.viewer)
        user_id, genebank_id, locked = self.viewer.id, self.genebanks[0].id, threading.Event()

        def grant_manager_slowly():  # update_role's shape: lock the account, write, commit later
            try:
                with db.DB_PROXY.atomic():
                    user = db.User.select().where(db.User.id == user_id).for_update().get()
                    user.privileges = [*user.privileges, {"level": "manager", "genebank": genebank_id}]
                    user.save(only=[db.User._privileges])
                    locked.set()
                    time.sleep(1)
            finally:
                db.DB_PROXY.close()

        granter = threading.Thread(target=grant_manager_slowly)
        granter.start()
        self.assertTrue(locked.wait(10))
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, 0, [(ended.id, None, "role")]))
        granter.join(15)
        self.assertFalse(_erased(main))

    def test_a_herd_linked_while_the_job_waits_holds_the_membership_without_deadlock(self):
        ended = _membership(114)
        main = _person(ended, OLD, role="huvudmedlem", user=self.viewer)
        user_id, herd_id, locked, errors = self.viewer.id, self.herds[1].id, threading.Event(), []

        def link_herd_while_holding_the_account():  # the job waits on the account while it holds the membership
            try:
                with db.DB_PROXY.atomic():
                    db.User.select().where(db.User.id == user_id).for_update().get()
                    locked.set()
                    time.sleep(1)
                    db.Herd.update(membership=ended.id, is_active=True).where(db.Herd.id == herd_id).execute()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                errors.append(exc)
            finally:
                db.DB_PROXY.close()

        linker = threading.Thread(target=link_herd_while_holding_the_account)
        linker.start()
        self.assertTrue(locked.wait(10))
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, 0, [(ended.id, None, "active_herd")]))
        linker.join(15)
        self.assertEqual(errors, [])
        self.assertFalse(_erased(main))

    def test_a_failure_on_one_membership_does_not_stop_the_rest(self):
        first = _person(_membership(108), OLD, role="huvudmedlem")
        second = _person(_membership(109), OLD, role="huvudmedlem")
        real = matrikel.anonymize_person

        def fail_first(person, actor, deferred_originals=None):
            if person.id == first.id:
                raise RuntimeError("lock timeout")
            return real(person, actor, deferred_originals=deferred_originals)

        with mock.patch.object(matrikel, "anonymize_person", side_effect=fail_first):
            with self.assertLogs(matrikel.logger, "ERROR"):
                self.assertEqual(matrikel.anonymize_ended_persons(NOW), (1, 1, []))
        self.assertFalse(_erased(first))
        self.assertTrue(_erased(second))

    def test_intake_originals_go_only_after_the_membership_commits(self):
        ended = _membership(130)
        first = _person(ended, OLD, role="huvudmedlem")
        _person(ended, OLD)
        real = matrikel.anonymize_person

        def second_fails(person, actor, deferred_originals=None):
            if person.id != first.id:
                raise RuntimeError("lock timeout")
            return real(person, actor, deferred_originals=deferred_originals)

        with (
            mock.patch.object(matrikel, "erase_person_from_inbox", return_value=["inkorg/original/a.jpg"]),
            mock.patch.object(matrikel, "remove_originals") as remove,
        ):
            with mock.patch.object(matrikel, "anonymize_person", side_effect=second_fails):
                with self.assertLogs(matrikel.logger, "ERROR"):
                    self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, 1, []))
            remove.assert_not_called()  # the rollback kept the rows that name the file, so the file stays
            self.assertFalse(_erased(first))
            remove.side_effect = lambda paths: self.assertFalse(db.DB_PROXY.in_transaction())  # after the COMMIT
            self.assertEqual(matrikel.anonymize_ended_persons(NOW), (2, 0, []))
            remove.assert_called_once_with(["inkorg/original/a.jpg", "inkorg/original/a.jpg"])

    def test_job_logs_ids_and_closes_connection(self):
        with (
            mock.patch.object(herdbook, "anonymize_ended_persons", return_value=(2, 1, [(7, None, "role")])) as job,
            mock.patch.object(herdbook.genetics.ps, "_close_db_connection") as close,
        ):
            with self.assertLogs(herdbook.APP.logger, "INFO") as logs:
                herdbook._anonymize_ended_persons()
            self.assertIn("Anonymized 2 persons ended 12 months ago, 1 memberships failed", logs.output[0])
            self.assertIn("membership=7 person=None reason=role", logs.output[1])
            self.assertIsNotNone(job.call_args.args[0].tzinfo)
            job.side_effect = RuntimeError("database gone")
            with self.assertRaises(RuntimeError):
                herdbook._anonymize_ended_persons()
        self.assertEqual(close.call_count, 2)
