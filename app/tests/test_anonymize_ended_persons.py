#!/usr/bin/env python3
"""
The nightly anonymization of persons whose membership ended 12 calendar months ago (#70).

Only runs on PostgreSQL (interval arithmetic). Names and addresses are made up; e-mail uses example.invalid.
"""

import os
import unittest
from datetime import date, datetime, timezone
from unittest import mock

import herdbook
import utils.database as db
import utils.matrikel as matrikel

from tests.database_test import DatabaseTest

_USE_POSTGRES = bool(os.getenv("POSTGRES_HOST")) and bool(os.getenv("POSTGRES_DB"))

NOW = datetime(2026, 11, 16, 3, 55, tzinfo=timezone.utc)
OLD = date(2025, 11, 1)  # more than 12 calendar months before NOW
YOUNG = date(2025, 12, 1)  # less than 12 calendar months before NOW


def _membership(number, status="inactive"):
    return db.Membership.create(
        member_number=number, membership_status=status, address="Exempelvägen 1", postal_code="12345", city="Exempelby"
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


def _address(membership):
    return db.Membership.get_by_id(membership.id).address


@unittest.skipUnless(_USE_POSTGRES, "interval arithmetic requires PostgreSQL")
class TestAnonymizeEndedPersons(DatabaseTest):
    def test_membership_ended_over_12_months_ago_is_anonymized(self):
        ended = _membership(101)
        main = _person(ended, OLD, role="huvudmedlem", user=self.viewer)  # viewer is on every account: no hold
        family = _person(ended, OLD)

        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (2, []))

        self.assertTrue(_erased(main) and _erased(family))
        self.assertIsNone(db.Member.get_by_id(main.id).user_id)
        self.assertIsNone(_address(ended))
        audit = db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_anonymized")
        self.assertEqual([row.actor_id for row in audit], [None, None])
        # A second night changes nothing.
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, []))

    def test_membership_ended_less_than_12_months_ago_stays(self):
        main = _person(_membership(102), YOUNG, role="huvudmedlem")
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, []))
        self.assertFalse(_erased(main))

    def test_ended_membership_waits_for_its_last_person(self):
        ended = _membership(103)
        family = _person(ended, OLD)
        main = _person(ended, YOUNG, role="huvudmedlem")
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, []))
        self.assertFalse(_erased(family) or _erased(main))
        self.assertEqual(_address(ended), "Exempelvägen 1")

    def test_active_herd_holds_the_ended_membership(self):
        ended = _membership(104)
        main = _person(ended, OLD, role="huvudmedlem")
        db.Herd.update(membership=ended, is_active=True).where(db.Herd.id == self.herds[1].id).execute()
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, [(ended.id, None, "active_herd")]))
        self.assertFalse(_erased(main))

    def test_a_role_on_any_person_holds_the_ended_membership(self):
        ended = _membership(105)
        main = _person(ended, OLD, role="huvudmedlem")
        family = _person(ended, OLD, user=self.manager)
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, [(ended.id, None, "role")]))
        self.assertFalse(_erased(main) or _erased(family))

    def test_legacy_owner_entry_holds_only_on_an_active_herd(self):
        ended = _membership(106)
        main = _person(ended, OLD, role="huvudmedlem", user=self.owner)  # owner of herds[0]
        db.Herd.update(is_active=True).where(db.Herd.id == self.herds[0].id).execute()
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (0, [(ended.id, None, "active_herd")]))
        db.Herd.update(is_active=False).where(db.Herd.id == self.herds[0].id).execute()
        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (1, []))
        self.assertTrue(_erased(main))

    def test_active_membership_loses_only_its_long_ended_persons(self):
        active = _membership(107, status="active")
        main = _person(active, role="huvudmedlem")
        gone = _person(active, OLD)
        recent = _person(active, YOUNG)
        held = _person(active, OLD, user=self.manager)
        # The household's herd does not hold a person who left it.
        db.Herd.update(membership=active, is_active=True).where(db.Herd.id == self.herds[1].id).execute()

        self.assertEqual(matrikel.anonymize_ended_persons(NOW), (1, [(active.id, held.id, "role")]))

        self.assertTrue(_erased(gone))
        self.assertFalse(_erased(main) or _erased(recent) or _erased(held))
        membership = db.Membership.get_by_id(active.id)
        self.assertEqual((membership.membership_status, membership.address), ("active", "Exempelvägen 1"))

    def test_a_failure_on_one_person_does_not_stop_the_rest(self):
        first = _person(_membership(108), OLD, role="huvudmedlem")
        second = _person(_membership(109), OLD, role="huvudmedlem")
        real = matrikel.anonymize_person

        def fail_first(person, actor):
            if person.id == first.id:
                raise RuntimeError("lock timeout")
            return real(person, actor)

        with mock.patch.object(matrikel, "anonymize_person", side_effect=fail_first):
            with self.assertLogs(matrikel.logger, "ERROR"):
                self.assertEqual(matrikel.anonymize_ended_persons(NOW), (1, []))
        self.assertFalse(_erased(first))
        self.assertTrue(_erased(second))

    def test_job_logs_ids_and_closes_connection(self):
        with (
            mock.patch.object(herdbook, "anonymize_ended_persons", return_value=(2, [(7, None, "role")])) as job,
            mock.patch.object(herdbook.genetics.ps, "_close_db_connection") as close,
        ):
            with self.assertLogs(herdbook.APP.logger, "INFO") as logs:
                herdbook._anonymize_ended_persons()
            self.assertIn("Anonymized 2 persons", logs.output[0])
            self.assertIn("membership=7 person=None reason=role", logs.output[1])
            self.assertIsNotNone(job.call_args.args[0].tzinfo)
            job.side_effect = RuntimeError("database gone")
            with self.assertRaises(RuntimeError):
                herdbook._anonymize_ended_persons()
        self.assertEqual(close.call_count, 2)
