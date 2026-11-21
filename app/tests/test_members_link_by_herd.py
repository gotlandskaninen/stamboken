"""Tests for flask members link-by-herd (links accounts to the register via herd ownership)."""

from datetime import date

import utils.data_access as da
import utils.database as db
from cli.members import members_cli
from click.testing import CliRunner
from flask.cli import ScriptInfo
from herdbook import APP  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402


class TestMembersLinkByHerd(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.runner = CliRunner()
        self._n = 0

    def _run(self, *extra):
        return self.runner.invoke(
            members_cli,
            ["link-by-herd", *extra],
            obj=ScriptInfo(create_app=lambda: APP),
        )

    def _membership(self, number, first="Anna", last="Svensson", status="active", **member_kwargs):
        membership = db.Membership.create(member_number=number, membership_status=status)
        person = db.Member.create(
            membership=membership, role="huvudmedlem", first_name=first, last_name=last, **member_kwargs
        )
        return membership, person

    def _herd(self, code, genebank=0):
        return db.Herd.create(genebank=self.genebanks[genebank], herd=code)

    def _account(self, fullname="Anna Svensson", owns=None):
        self._n += 1
        user = da.register_user(f"konto{self._n}@example.org", "pass", username=f"konto{self._n}", fullname=fullname)
        if owns is not None:
            user.add_role("owner", owns.id)
        return user

    def _linked_user_id(self, person):
        return db.Member.get_by_id(person.id).user_id

    def test_owner_with_matching_name_is_linked_with_mode_cli(self):
        _, person = self._membership(901)
        user = self._account(owns=self._herd("G901"))

        result = self._run()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self._linked_user_id(person), user.id)
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "person_user_linked")
        self.assertEqual((audit.payload["source"], audit.payload["person_id"]), ("cli", person.id))
        self.assertIn("Kopplade: 1", result.output)

    def test_name_match_ignores_case_and_spacing(self):
        _, person = self._membership(901)
        user = self._account(fullname="  anna   SVENSSON ", owns=self._herd("G901"))

        result = self._run()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self._linked_user_id(person), user.id)

    def test_different_name_is_listed_not_linked(self):
        _, person = self._membership(901)
        self._account(fullname="Eva Svensson", owns=self._herd("G901"))

        result = self._run()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIn("Kopplade: 0", result.output)
        self.assertIn("Till granskning: 1", result.output)
        self.assertIn("G901", result.output)
        self.assertIn("namnet skiljer sig", result.output)

    def test_only_first_name_matching_is_not_enough(self):
        _, person = self._membership(901)
        self._account(fullname="Anna", owns=self._herd("G901"))

        result = self._run()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIn("namnet skiljer sig", result.output)

    def test_empty_names_never_match(self):
        _, person = self._membership(901, first="", last="")
        self._account(fullname="", owns=self._herd("G901"))
        _, person2 = self._membership(902)
        self._account(fullname=None, owns=self._herd("G902"))

        result = self._run()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIsNone(self._linked_user_id(person2))
        self.assertIn("Till granskning: 2", result.output)

    def test_two_owners_link_none_and_are_listed(self):
        _, person = self._membership(901)
        herd = self._herd("G901")
        self._account(owns=herd)
        self._account(owns=herd)

        result = self._run()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIn("flera konton", result.output)
        self.assertIn("G901", result.output)

    def test_no_owner_is_listed(self):
        _, person = self._membership(901)
        self._herd("G901")

        result = self._run()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIn("inget konto", result.output)
        self.assertIn("G901", result.output)

    def test_membership_without_main_member_is_listed(self):
        membership = db.Membership.create(member_number=901)
        self._account(owns=self._herd("G901"))

        result = self._run()

        self.assertEqual(db.Member.select().where(db.Member.user.is_null(False), db.Member.membership == membership).count(), 0)
        self.assertIn("saknar huvudmedlem", result.output)

    def test_g_and_m_herds_with_same_number_go_to_their_memberships(self):
        _, g_person = self._membership(901, first="Gunnar", last="Gran")
        _, m_person = self._membership(902, first="Maja", last="Malm")
        # Same number in both genebanks: M901 belongs to membership 901 only through its own code.
        g_user = self._account(fullname="Gunnar Gran", owns=self._herd("G901", genebank=0))
        m_user = self._account(fullname="Maja Malm", owns=self._herd("M902", genebank=1))
        self._account(fullname="Maja Malm", owns=self._herd("M901", genebank=1))

        result = self._run()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self._linked_user_id(g_person), g_user.id)
        self.assertEqual(self._linked_user_id(m_person), m_user.id)
        # M901 has an owner named Maja Malm, but membership 901's main member is Gunnar Gran.
        self.assertIn("M901", result.output)
        self.assertIn("namnet skiljer sig", result.output)

    def test_main_member_already_linked_to_this_account_counts_as_done(self):
        _, person = self._membership(901)
        user = self._account(owns=self._herd("G901"))
        person.user = user
        person.save()

        result = self._run()

        self.assertIn("Redan kopplade: 1", result.output)
        self.assertIn("Till granskning: 0", result.output)
        self.assertEqual(self._linked_user_id(person), user.id)

    def test_main_member_linked_to_another_account_is_listed_and_unchanged(self):
        _, person = self._membership(901)
        other = self._account()
        person.user = other
        person.save()
        self._account(owns=self._herd("G901"))

        result = self._run()

        self.assertEqual(self._linked_user_id(person), other.id)
        self.assertIn("redan kopplad till ett annat konto", result.output)

    def test_account_linked_to_another_member_is_listed_and_unchanged(self):
        _, person = self._membership(901)
        user = self._account(owns=self._herd("G901"))
        _, elsewhere = self._membership(902)
        elsewhere.user = user
        elsewhere.save()

        result = self._run()

        self.assertIsNone(self._linked_user_id(person))
        self.assertEqual(self._linked_user_id(elsewhere), user.id)
        self.assertIn("kontot är redan kopplat till en annan medlem", result.output)

    def test_ended_membership_and_left_member_are_skipped(self):
        _, ended = self._membership(901, status="inactive")
        self._account(owns=self._herd("G901"))
        _, left = self._membership(902, end_date=date(2026, 1, 1))
        self._account(owns=self._herd("G902"))

        result = self._run()

        self.assertIsNone(self._linked_user_id(ended))
        self.assertIsNone(self._linked_user_id(left))
        self.assertIn("Kopplade: 0", result.output)
        self.assertIn("Till granskning: 0", result.output)

    def test_dry_run_prints_same_plan_and_writes_nothing(self):
        _, person = self._membership(901)
        self._account(owns=self._herd("G901"))
        self._membership(902)
        self._herd("G902")

        result = self._run("--dry-run")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(self._linked_user_id(person))
        self.assertEqual(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_user_linked").count(), 0)
        self.assertIn("Kopplade: 1", result.output)
        self.assertIn("G902", result.output)
        self.assertIn("dry-run", result.output)

    def test_second_run_changes_nothing(self):
        _, person = self._membership(901)
        user = self._account(owns=self._herd("G901"))
        self._membership(902)
        self._herd("G902")

        self._run()
        result = self._run()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self._linked_user_id(person), user.id)
        self.assertEqual(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_user_linked").count(), 1)
        self.assertIn("Kopplade: 0", result.output)
        self.assertIn("Redan kopplade: 1", result.output)
        self.assertIn("Till granskning: 1", result.output)

    def test_link_that_would_convey_another_herd_is_listed(self):
        membership, person = self._membership(901)
        g = self._herd("G901")
        g.membership = membership
        g.save()
        m = self._herd("M901", genebank=1)
        m.membership = membership
        m.save()
        self._account(owns=g)

        result = self._run()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIn("fler besättningar", result.output)
