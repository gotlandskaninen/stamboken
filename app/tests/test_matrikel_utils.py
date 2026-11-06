"""Tests for app/utils/matrikel.py — member-number allocation + audit primitives.

Pure model/util tests (no HTTP) — no limiter import needed. Run in the
isolated pytest stack (PostgreSQL): allocation uses SELECT ... FOR UPDATE,
which SQLite rejects (same limitation as the approve-flow tests in
test_member_application_api.py).
"""

import threading
import time
import unittest
from datetime import date

import utils.data_access as da
import utils.database as db
from utils import matrikel

from tests.database_test import _USE_POSTGRES, DatabaseTest


class MatrikelUtilsTest(DatabaseTest):
    """Normalize the counter row to value=0 regardless of fixture seeding."""

    def setUp(self):
        super().setUp()
        if db.MemberNumberCounter.select().count() == 0:
            db.MemberNumberCounter.create(value=0)
        else:
            db.MemberNumberCounter.update(value=0).execute()


class TestAllocateMemberNumber(MatrikelUtilsTest):
    def test_allocates_sequential_numbers(self):
        with db.DB_PROXY.atomic():
            first = matrikel.allocate_member_number()
            second = matrikel.allocate_member_number()
        self.assertEqual((first, second), (1, 2))
        self.assertEqual(db.MemberNumberCounter.select().first().value, 2)

    def test_requires_open_transaction(self):
        with self.assertRaises(RuntimeError):
            matrikel.allocate_member_number()

    def test_rolls_back_with_enclosing_transaction(self):
        with self.assertRaises(ValueError):
            with db.DB_PROXY.atomic():
                matrikel.allocate_member_number()
                raise ValueError("simulated approval failure")
        self.assertEqual(db.MemberNumberCounter.select().first().value, 0)

    @unittest.skipUnless(_USE_POSTGRES, "FOR UPDATE row-lock serialization needs PostgreSQL")
    def test_concurrent_allocations_serialize_on_for_update(self):
        """Two overlapping transactions must get distinct numbers.

        Each thread owns its own peewee connection (connection state is
        thread-local). The first transaction takes the FOR UPDATE lock and
        holds it while sleeping; the second must wait on the lock instead
        of reading the same counter value. Without FOR UPDATE both would
        read 0 and both would return 1.
        """
        results = []
        errors = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait(timeout=10)
                with db.DB_PROXY.atomic():
                    number = matrikel.allocate_member_number()
                    time.sleep(0.2)  # hold the row lock across the overlap window
                    results.append(number)
            except Exception as exc:
                errors.append(exc)
            finally:
                try:
                    db.DB_PROXY.close()
                except Exception:
                    pass

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), [1, 2])
        self.assertEqual(db.MemberNumberCounter.select().first().value, 2)


class TestCreateGrantConcurrency(MatrikelUtilsTest):
    @unittest.skipUnless(_USE_POSTGRES, "FOR UPDATE row-lock serialization needs PostgreSQL")
    def test_concurrent_create_grant_yields_one_row_and_no_error(self):
        """Two overlapping create_grant calls for the same (member, herd) must
        serialize on the membership lock: one creates, the other re-grants the
        same row. Without the lock both read no-row and the second INSERT
        escapes as IntegrityError."""
        membership = db.Membership.create(member_number=77, membership_status="active")
        person = db.Member.create(
            membership=membership,
            first_name="Sune",
            last_name="Skötarsson",
            role="skotare",
        )
        herd = self.herds[0]
        admin_id = self.admin.id
        errors = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait(timeout=10)
                matrikel.create_grant(
                    db.Member.get_by_id(person.id),
                    herd,
                    None,
                    db.User.get_by_id(admin_id),
                )
                time.sleep(0.1)
            except Exception as exc:
                errors.append(exc)
            finally:
                try:
                    db.DB_PROXY.close()
                except Exception:
                    pass

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        self.assertEqual(errors, [])
        grants = db.HerdAccessGrant.select().where(
            db.HerdAccessGrant.member == person.id,
            db.HerdAccessGrant.herd == herd.id,
        )
        self.assertEqual(grants.count(), 1)
        self.assertIsNone(grants.first().revoked_at)


class TestRaiseCounterTo(MatrikelUtilsTest):
    def setUp(self):
        super().setUp()
        db.MemberNumberCounter.update(value=5).execute()

    def test_raises_mark_when_value_exceeds_it(self):
        with db.DB_PROXY.atomic():
            matrikel.raise_counter_to(10)
        self.assertEqual(db.MemberNumberCounter.select().first().value, 10)

    def test_keeps_mark_when_value_is_lower_or_equal(self):
        with db.DB_PROXY.atomic():
            matrikel.raise_counter_to(3)
        self.assertEqual(db.MemberNumberCounter.select().first().value, 5)
        with db.DB_PROXY.atomic():
            matrikel.raise_counter_to(5)
        self.assertEqual(db.MemberNumberCounter.select().first().value, 5)

    def test_requires_open_transaction(self):
        with self.assertRaises(RuntimeError):
            matrikel.raise_counter_to(10)


class TestWriteMatrikelAudit(MatrikelUtilsTest):
    def test_creates_audit_row(self):
        membership = db.Membership.create()
        row = matrikel.write_matrikel_audit(
            self.admin,
            "membership_status_changed",
            membership,
            {"before": {"membership_status": "active"}, "after": {"membership_status": "inactive"}},
        )
        reloaded = db.MatrikelAudit.get_by_id(row.id)
        self.assertEqual(reloaded.actor_id, self.admin.id)
        self.assertEqual(reloaded.action, "membership_status_changed")
        self.assertEqual(reloaded.membership_id, membership.id)
        self.assertEqual(reloaded.payload["after"]["membership_status"], "inactive")
        self.assertIsNotNone(reloaded.created_at)


class TestRedactPersonFromAudits(MatrikelUtilsTest):
    def setUp(self):
        super().setUp()
        self.membership = db.Membership.create(member_number=7)
        self.person = db.Member.create(
            first_name="Anna",
            last_name="Svensson",
            email="anna@example.com",
            phone="070-111 22 33",
            genebank=self.genebanks[0],
            membership=self.membership,
            role="huvudmedlem",
        )

    def test_redacts_pii_keeps_action_actor_and_ids(self):
        row = matrikel.write_matrikel_audit(
            self.admin,
            "person_added",
            self.membership,
            {
                "person_id": self.person.id,
                "after": {
                    "first_name": "Anna",
                    "last_name": "Svensson",
                    "email": "anna@example.com",
                    "phone": "070-111 22 33",
                    "role": "huvudmedlem",
                },
            },
        )
        touched = matrikel.redact_person_from_audits(self.person)
        self.assertEqual(touched, 1)
        reloaded = db.MatrikelAudit.get_by_id(row.id)
        self.assertEqual(reloaded.action, "person_added")
        self.assertEqual(reloaded.actor_id, self.admin.id)
        self.assertEqual(reloaded.payload["person_id"], self.person.id)
        after = reloaded.payload["after"]
        self.assertEqual(after["first_name"], "[borttagen]")
        self.assertEqual(after["last_name"], "[borttagen]")
        self.assertEqual(after["email"], "[borttagen]")
        self.assertEqual(after["phone"], "[borttagen]")
        self.assertEqual(after["role"], "huvudmedlem")  # non-PII value survives

    def test_other_rows_untouched_and_count_returned(self):
        other_person = db.Member.create(
            first_name="Bertil",
            last_name="Karlsson",
            genebank=self.genebanks[0],
            membership=self.membership,
            role="familjemedlem",
        )
        bertil_row = matrikel.write_matrikel_audit(
            self.admin,
            "person_added",
            self.membership,
            {"person_id": other_person.id, "after": {"first_name": "Bertil"}},
        )
        number_row = matrikel.write_matrikel_audit(
            self.admin,
            "member_number_changed",
            self.membership,
            {"before": {"member_number": None}, "after": {"member_number": 7}},
        )
        anna_row = matrikel.write_matrikel_audit(
            self.admin,
            "person_removed",
            self.membership,
            {"person_id": self.person.id, "before": {"first_name": "Anna", "email": "anna@example.com"}},
        )
        touched = matrikel.redact_person_from_audits(self.person)
        self.assertEqual(touched, 1)
        self.assertEqual(
            db.MatrikelAudit.get_by_id(bertil_row.id).payload["after"]["first_name"],
            "Bertil",
        )
        self.assertEqual(
            db.MatrikelAudit.get_by_id(number_row.id).payload["after"]["member_number"],
            7,
        )
        redacted = db.MatrikelAudit.get_by_id(anna_row.id).payload
        self.assertEqual(redacted["before"]["first_name"], "[borttagen]")
        self.assertEqual(redacted["before"]["email"], "[borttagen]")

    def test_second_redaction_pass_touches_nothing(self):
        matrikel.write_matrikel_audit(
            self.admin,
            "person_added",
            self.membership,
            {"person_id": self.person.id, "after": {"first_name": "Anna"}},
        )
        self.assertEqual(matrikel.redact_person_from_audits(self.person), 1)
        self.assertEqual(matrikel.redact_person_from_audits(self.person), 0)


class TestParsePostalFields(MatrikelUtilsTest):
    def test_split_keys(self):
        self.assertEqual(
            matrikel.parse_postal_fields({"postal_code": "62355", "city": " Visby "}),
            {"postal_code": "623 55", "city": "Visby"},
        )
        self.assertEqual(matrikel.parse_postal_fields({"postal_code": None}), {"postal_code": None})
        self.assertEqual(matrikel.parse_postal_fields({"city": ""}), {"city": None})
        self.assertEqual(matrikel.parse_postal_fields({"phone": "x"}), {})

    def test_alias(self):
        self.assertEqual(
            matrikel.parse_postal_fields({"postal_address": "62355 Visby"}),
            {"postal_code": "623 55", "city": "Visby"},
        )
        self.assertEqual(
            matrikel.parse_postal_fields({"postal_address": None}),
            {"postal_code": None, "city": None},
        )

    def test_errors(self):
        with self.assertRaises(matrikel.AddressValidationError) as ctx:
            matrikel.parse_postal_fields({"postal_address": "x", "city": "y"})
        self.assertEqual(ctx.exception.detail, "Ange antingen postal_address eller postal_code/city")
        with self.assertRaises(matrikel.AddressValidationError) as ctx:
            matrikel.parse_postal_fields({"postal_code": "123"})
        self.assertEqual(
            (ctx.exception.title, ctx.exception.detail),
            ("Ogiltigt postnummer", "Postnummer ska vara fem siffror"),
        )
        with self.assertRaises(matrikel.AddressValidationError) as ctx:
            matrikel.parse_postal_fields({"city": "c" * 101})
        self.assertEqual(ctx.exception.detail, "Postort får vara högst 100 tecken")
        with self.assertRaises(matrikel.AddressValidationError) as ctx:
            # A non-parsing alias lands whole in city — the cap still applies.
            matrikel.parse_postal_fields({"postal_address": "Box " + "x" * 100})
        self.assertEqual(ctx.exception.detail, "Postort får vara högst 100 tecken")
        with self.assertRaises(matrikel.AddressValidationError):
            matrikel.parse_postal_fields({"postal_code": 12345})


class TestLinkAccessDelta(MatrikelUtilsTest):
    """link_access_delta() is the REAL access delta — the same
    rules as User.effective_herd_ids(), minus what the account already has."""

    def setUp(self):
        super().setUp()
        self.ms = db.Membership.create(member_number=41, membership_status="active")
        self.herds[0].membership = self.ms
        self.herds[0].save()
        self.main = db.Member.create(membership=self.ms, first_name="Anna", last_name="Lind", role="huvudmedlem")
        self.family = db.Member.create(membership=self.ms, first_name="Erik", last_name="Lind", role="familjemedlem")
        self.skotare = db.Member.create(membership=self.ms, first_name="Maja", last_name="Berg", role="skotare")
        self.account = da.register_user("delta@example.com", "pass", username="delta")

    def test_huvudmedlem_on_active_membership_conveys_the_membership_herds(self):
        self.assertEqual(
            matrikel.link_access_delta(self.main, self.account),
            [
                {
                    "id": self.herds[0].id,
                    "herd": "G1",
                    "herd_name": "Gotlandsherd1",
                    "genebank_id": self.genebanks[0].id,
                }
            ],
        )

    def test_familjemedlem_with_grant_conveys_the_grant_herd_only(self):
        # A grant may point at a herd OUTSIDE the membership (herds[1] is not
        # the membership's) — the delta is not a subset of the membership herds.
        matrikel.create_grant(self.family, self.herds[1], None, self.admin)
        self.assertEqual(
            [h["id"] for h in matrikel.link_access_delta(self.family, self.account)],
            [self.herds[1].id],
        )

    def test_skotare_without_grants_conveys_nothing(self):
        self.assertEqual(matrikel.link_access_delta(self.skotare, self.account), [])

    def test_non_active_membership_conveys_nothing(self):
        matrikel.create_grant(self.family, self.herds[1], None, self.admin)
        for status in ("pending", "inactive", "friexemplar"):
            self.ms.membership_status = status
            self.ms.save()
            self.assertEqual(matrikel.link_access_delta(db.Member.get_by_id(self.main.id), self.account), [], status)
            self.assertEqual(matrikel.link_access_delta(db.Member.get_by_id(self.family.id), self.account), [], status)

    def test_herds_the_account_already_has_are_excluded(self):
        self.account.add_role("owner", self.herds[0].id)
        self.assertEqual(matrikel.link_access_delta(self.main, db.User.get_by_id(self.account.id)), [])

    def test_ended_person_conveys_nothing(self):
        matrikel.create_grant(self.family, self.herds[1], None, self.admin)
        self.family.end_date = date.today()
        self.family.save()
        self.assertEqual(matrikel.link_access_delta(self.family, self.account), [])
