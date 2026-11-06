"""Regression for the Playwright seed's member-row resolution.

`cli/create_test_users.py` links a Member row to test-member and hangs the
familjemedlem fixture off that row's membership. Two ambiguous states used to
pass silently: a row carrying the fixture's contact e-mail while belonging to
another account, and test-member being linked only to an ended (or demoted)
row. Both must exit 1 without creating or relinking anything.
"""

import io
import os
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime
from unittest import mock

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from cli.create_test_users import create_test_users  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402
from tests.ht_helpers import ht_row  # noqa: E402


class TestCreateTestUsersSeed(DatabaseTest):
    def setUp(self):
        super().setUp()
        # The seeder resolves the PRODUCTION genebank names and needs one active
        # herd with individuals — the fixture's G1 has a HerdTracking row.
        db.Genebank.update(name="Gotlandskanin").where(db.Genebank.name == "Gotland").execute()
        db.Genebank.update(name="Mellerudskanin").where(db.Genebank.name == "Mellerud").execute()
        # The seeder only looks at ACTIVE herds (the fixture's default False),
        # and a herd's members are derived from the LATEST HerdTracking row per
        # individual — give G1 one that no other fixture row can outdate.
        db.Herd.update(is_active=True).where(db.Herd.id == self.herds[0].id).execute()
        ht_row(
            "ATTESTATION", herd=self.herds[0], individual=self.individuals[0], herd_tracking_date=datetime(2030, 1, 1)
        )
        self.test_member = da.register_user("test-member@test.local", "test-member-pass", username="test-member")

    def _seed_exits(self):
        """Run the seeder, require exit 1, return what it wrote to stderr."""
        err = io.StringIO()
        with self.assertRaises(SystemExit) as caught, redirect_stderr(err), redirect_stdout(io.StringIO()):
            create_test_users()
        self.assertEqual(caught.exception.code, 1)
        return err.getvalue()

    def test_refuses_in_production(self):
        # Fixture is otherwise seedable, so only the guard stops the public-password accounts.
        with mock.patch.dict(os.environ, {"FLASK_ENV": "production"}):
            self.assertIn("production", self._seed_exits())
        self.assertFalse(db.User.select().where(db.User.email == "test-admin@test.local").exists())

    def _person(self, user=None, role="huvudmedlem", end_date=None, first="Playwright", last="TestMember"):
        membership = db.Membership.create(membership_status="active")
        return db.Member.create(
            membership=membership,
            first_name=first,
            last_name=last,
            email="test-member@test.local",
            role=role,
            end_date=end_date,
            user=user,
        )

    def _family_rows(self):
        return db.Member.select().where(db.Member.email == "test-family@test.local").count()

    def test_crossed_link_exits_naming_both_accounts(self):
        other = da.register_user("other@test.local", "pass", username="other")  # nosemgrep
        own = self._person(user=self.test_member)
        crossed = self._person(user=other, first="Krock", last="Rad")

        message = self._seed_exits()

        self.assertIn(f"member row {crossed.id}", message)
        self.assertIn(f"is linked to user {other.id}", message)
        self.assertIn(f"test-member is user {self.test_member.id}", message)
        # Nothing adopted, nothing relinked, no familjemedlem seeded.
        self.assertEqual(db.Member.get_by_id(crossed.id).user_id, other.id)
        self.assertEqual(db.Member.get_by_id(own.id).user_id, self.test_member.id)
        self.assertEqual(self._family_rows(), 0)

    def test_ended_owner_row_exits_instead_of_seeding_the_family_fixture(self):
        ended = self._person(user=self.test_member, end_date=date(2020, 1, 1))

        message = self._seed_exits()

        self.assertIn(f"member row {ended.id} is linked to test-member@test.local", message)
        self.assertIn("is not an active huvudmedlem", message)
        self.assertIsNotNone(db.Member.get_by_id(ended.id).end_date)
        self.assertEqual(self._family_rows(), 0)

    def test_active_main_row_seeds_the_family_fixture(self):
        own = self._person(user=self.test_member)

        with redirect_stdout(io.StringIO()):
            create_test_users()

        family = db.Member.get(db.Member.email == "test-family@test.local")
        self.assertEqual(family.membership_id, own.membership_id)
        self.assertEqual(family.role, "familjemedlem")
        self.assertEqual(family.user.email, "test-family@test.local")
