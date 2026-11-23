"""Tests for flask members link-by-herd (links accounts to the register via herd ownership)."""

import re
from datetime import date
from unittest.mock import patch
from uuid import uuid4

import cli.members as members_cli_module
import utils.data_access as da
import utils.database as db
from cli.members import members_cli
from click.testing import CliRunner
from flask.cli import ScriptInfo
from herdbook import APP  # noqa: E402
from utils.matrikel import LinkError

from tests.database_test import DatabaseTest  # noqa: E402


class TestMembersLinkByHerd(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.runner = CliRunner()
        self._n = 0
        self._memberships = {}

    def _run(self, *extra):
        """Plan only, unless extra says otherwise."""
        return self.runner.invoke(
            members_cli,
            ["link-by-herd", *extra],
            obj=ScriptInfo(create_app=lambda: APP),
        )

    def _plan_value(self):
        match = re.search(r"Kontrollvärde: ([0-9a-f]{16})", self._run().output)
        return match.group(1)

    def _apply(self, plan=None):
        """Apply with the value of the plan as it stands now, unless a (stale) value is given."""
        plan = plan or self._plan_value()
        return self._run("--apply", "--actor-user-id", str(self.admin.id), "--plan", plan)

    def _membership(self, number, first="Anna", last="Svensson", status="active", **member_kwargs):
        membership = db.Membership.create(member_number=number, membership_status=status)
        self._memberships[number] = membership
        person = db.Member.create(
            membership=membership, role="huvudmedlem", first_name=first, last_name=last, **member_kwargs
        )
        return membership, person

    def _herd(self, code, genebank=0, **kwargs):
        """The herd is tied to the membership with its number, as the import does; membership=None unties it."""
        kwargs.setdefault(
            "membership", self._memberships.get(int(code[1:]) if re.fullmatch(r"[GM][1-9][0-9]*", code) else None)
        )
        return db.Herd.create(genebank=self.genebanks[genebank], herd=code, **{"is_active": True, **kwargs})

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

        result = self._apply()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self._linked_user_id(person), user.id)
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "person_user_linked")
        self.assertEqual((audit.payload["source"], audit.payload["person_id"]), ("cli", person.id))
        self.assertEqual(audit.actor_id, self.admin.id)
        self.assertIn("Kopplade: 1", result.output)

    def test_name_match_ignores_case_and_spacing(self):
        _, person = self._membership(901)
        user = self._account(fullname="  anna   SVENSSON ", owns=self._herd("G901"))

        result = self._apply()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self._linked_user_id(person), user.id)

    def test_different_name_is_listed_not_linked(self):
        _, person = self._membership(901)
        self._account(fullname="Eva Svensson", owns=self._herd("G901"))

        result = self._apply()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIn("Kopplade: 0", result.output)
        self.assertIn("Till granskning: 1", result.output)
        self.assertIn("G901", result.output)
        self.assertIn("namnet skiljer sig", result.output)

    def test_only_first_name_matching_is_not_enough(self):
        _, person = self._membership(901)
        self._account(fullname="Anna", owns=self._herd("G901"))

        result = self._apply()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIn("namnet skiljer sig", result.output)

    def test_empty_names_never_match(self):
        _, person = self._membership(901, first="", last="")
        self._account(fullname="", owns=self._herd("G901"))
        _, person2 = self._membership(902)
        self._account(fullname=None, owns=self._herd("G902"))

        result = self._apply()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIsNone(self._linked_user_id(person2))
        self.assertIn("Till granskning: 2", result.output)

    def test_two_owners_link_none_and_are_listed(self):
        _, person = self._membership(901)
        herd = self._herd("G901")
        self._account(owns=herd)
        self._account(owns=herd)

        result = self._apply()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIn("flera konton", result.output)
        self.assertIn("G901", result.output)

    def test_no_owner_is_listed(self):
        _, person = self._membership(901)
        self._herd("G901")

        result = self._apply()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIn("inget konto", result.output)
        self.assertIn("G901", result.output)

    def test_membership_without_main_member_is_listed(self):
        membership = db.Membership.create(member_number=901)
        self._account(owns=self._herd("G901"))

        result = self._apply()

        self.assertEqual(
            db.Member.select().where(db.Member.user.is_null(False), db.Member.membership == membership).count(), 0
        )
        self.assertIn("ingen kvarvarande huvudmedlem", result.output)

    def test_g_and_m_herds_go_to_the_membership_with_their_number(self):
        _, g_person = self._membership(901, first="Gunnar", last="Gran")
        _, m_person = self._membership(902, first="Maja", last="Malm")
        g_user = self._account(fullname="Gunnar Gran", owns=self._herd("G901", genebank=0))
        g_user.add_role("owner", self._herd("M901", genebank=1).id)
        m_user = self._account(fullname="Maja Malm", owns=self._herd("M902", genebank=1))

        result = self._apply()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self._linked_user_id(g_person), g_user.id)
        self.assertEqual(self._linked_user_id(m_person), m_user.id)
        self.assertIn("G901/M901", result.output)

    def test_main_member_already_linked_to_this_account_counts_as_done(self):
        _, person = self._membership(901)
        user = self._account(owns=self._herd("G901"))
        person.user = user
        person.save()

        result = self._apply()

        self.assertIn("Redan kopplade: 1", result.output)
        self.assertIn("Till granskning: 0", result.output)
        self.assertEqual(self._linked_user_id(person), user.id)

    def test_main_member_linked_to_another_account_is_listed_and_unchanged(self):
        _, person = self._membership(901)
        other = self._account()
        person.user = other
        person.save()
        self._account(owns=self._herd("G901"))

        result = self._apply()

        self.assertEqual(self._linked_user_id(person), other.id)
        self.assertIn("redan kopplad till ett annat konto", result.output)

    def test_account_linked_to_another_member_is_listed_and_unchanged(self):
        _, person = self._membership(901)
        user = self._account(owns=self._herd("G901"))
        _, elsewhere = self._membership(902)
        elsewhere.user = user
        elsewhere.save()

        result = self._apply()

        self.assertIsNone(self._linked_user_id(person))
        self.assertEqual(self._linked_user_id(elsewhere), user.id)
        self.assertIn("kontot är redan kopplat till en annan medlem", result.output)

    def test_ended_membership_and_left_member_are_skipped_but_not_silent_with_an_owner(self):
        _, ended = self._membership(901, status="inactive")
        self._herd("G901")
        _, left = self._membership(902, end_date=date(2026, 1, 1))
        self._herd("G902")

        result = self._apply()
        self.assertIsNone(self._linked_user_id(ended))
        self.assertIsNone(self._linked_user_id(left))
        self.assertIn("Kopplade: 0", result.output)
        self.assertIn("Till granskning: 0", result.output)  # no owner account: silent

        self._account(owns=self._herd("G903"))  # owner, no membership 903
        self._account(owns=self._herd("G904", is_active=False))  # inactive herd: silent
        self._membership(905, end_date=date(2026, 1, 1))
        self._account(owns=self._herd("G905"))
        result = self._apply()
        self.assertIn("Till granskning: 2", result.output)
        self.assertIn("G903", result.output)
        self.assertIn("G905", result.output)
        self.assertNotIn("G904", result.output)

    def test_plan_only_run_prints_same_plan_and_writes_nothing(self):
        _, person = self._membership(901)
        self._account(owns=self._herd("G901"))
        self._membership(902)
        self._herd("G902")

        result = self._run()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(self._linked_user_id(person))
        self.assertEqual(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_user_linked").count(), 0)
        self.assertIn("Att koppla: 1", result.output)
        self.assertIn("G902", result.output)
        self.assertIn("endast plan", result.output)

    def test_second_run_changes_nothing(self):
        _, person = self._membership(901)
        user = self._account(owns=self._herd("G901"))
        self._membership(902)
        self._herd("G902")

        self._apply()
        result = self._apply()

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

        result = self._apply()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIn("fler besättningar", result.output)

    def test_apply_without_actor_is_a_usage_error(self):
        _, person = self._membership(901)
        self._account(owns=self._herd("G901"))

        result = self._run("--apply")

        self.assertEqual(result.exit_code, 2, result.output)
        self.assertIn("--actor-user-id", result.output)
        self.assertIsNone(self._linked_user_id(person))

    def test_inactive_or_unprivileged_actor_is_refused(self):
        _, person = self._membership(901)
        self._account(owns=self._herd("G901"))
        plain = self._account()
        inactive = self._account()
        inactive.add_role("admin", None)
        inactive.is_active = False
        inactive.save()

        for actor in (plain, inactive):
            result = self._run("--apply", "--actor-user-id", str(actor.id))
            self.assertEqual(result.exit_code, 2, result.output)
        self.assertIsNone(self._linked_user_id(person))

    def test_owner_entry_without_herd_is_skipped(self):
        _, person = self._membership(901)
        user = self._account(owns=self._herd("G901"))
        broken = self._account()
        broken.privileges = [{"level": "owner"}]
        broken.save()

        result = self._apply()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self._linked_user_id(person), user.id)

    def test_family_member_with_the_owners_name_is_not_the_target(self):
        membership, main = self._membership(901, first="Gunnar", last="Gran")
        family = db.Member.create(membership=membership, role="familjemedlem", first_name="Anna", last_name="Svensson")
        self._account(fullname="Anna Svensson", owns=self._herd("G901"))

        result = self._apply()

        self.assertIsNone(self._linked_user_id(family))
        self.assertIsNone(self._linked_user_id(main))
        self.assertIn("namnet skiljer sig", result.output)

    def test_inactive_sole_owner_is_listed_in_both_modes(self):
        _, person = self._membership(901)
        user = self._account(owns=self._herd("G901"))
        user.is_active = False
        user.save()

        for result in (self._run(), self._apply()):
            self.assertIn("kontot är inaktivt", result.output)
            self.assertIn("Till granskning: 1", result.output)
        self.assertIsNone(self._linked_user_id(person))

    def test_one_account_owning_g_and_m_of_a_membership_gives_one_link(self):
        _, person = self._membership(901)
        user = self._account(owns=self._herd("G901"))
        user.add_role("owner", self._herd("M901", genebank=1).id)

        result = self._apply()

        self.assertEqual(self._linked_user_id(person), user.id)
        self.assertIn("Kopplade: 1", result.output)
        self.assertIn("G901/M901", result.output)
        self.assertEqual(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_user_linked").count(), 1)

    def test_two_accounts_on_g_and_m_with_the_main_members_name_are_both_listed(self):
        _, person = self._membership(901)
        self._account(owns=self._herd("G901"))
        self._account(owns=self._herd("M901", genebank=1))

        result = self._apply()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIn("Kopplade: 0", result.output)
        self.assertEqual(result.output.count("flera möjliga kopplingar"), 2)

    def test_account_sole_owner_in_two_memberships_with_same_main_name_is_listed_for_both(self):
        _, p1 = self._membership(901)
        _, p2 = self._membership(902)
        user = self._account(owns=self._herd("G901"))
        user.add_role("owner", self._herd("G902").id)

        result = self._apply()

        self.assertIsNone(self._linked_user_id(p1))
        self.assertIsNone(self._linked_user_id(p2))
        self.assertEqual(result.output.count("flera möjliga kopplingar"), 2)

    def test_herd_belonging_to_another_membership_is_listed(self):
        _, person = self._membership(901)
        other, _ = self._membership(902)
        self._account(owns=self._herd("G901", membership=other))

        result = self._apply()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIn("tillhör ett annat medlemskap", result.output)

    def test_two_herd_rows_with_the_same_code_are_listed(self):
        _, person = self._membership(901)
        self._account(owns=self._herd("G901"))
        self.genebanks.append(db.Genebank.create(name="Gotland2"))
        db.Herd.create(genebank=self.genebanks[2], herd="G901", is_active=True)

        result = self._apply()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIn("flera besättningar har samma kod", result.output)

    def test_herd_in_the_genebank_the_prefix_does_not_name_is_ignored(self):
        _, person = self._membership(901)
        self._account(owns=self._herd("G901", genebank=1))  # Mellerud holds a G code

        result = self._apply()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIn("Till granskning: 0", result.output)

    def test_herd_id_stored_as_string_counts_as_the_same_herd(self):
        _, person = self._membership(901)
        herd = self._herd("G901")
        a = self._account()
        a.privileges = [{"level": "owner", "herd": herd.id}]
        a.save()
        b = self._account()
        b.privileges = [{"level": "owner", "herd": str(herd.id)}]
        b.save()

        result = self._apply()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIn("flera konton", result.output)

    def test_duplicate_owner_entries_count_one_account_once(self):
        _, person = self._membership(901)
        herd = self._herd("G901")
        user = self._account()
        user.privileges = [{"level": "owner", "herd": herd.id}, {"level": "owner", "herd": herd.id}]
        user.save()

        self._apply()

        self.assertEqual(self._linked_user_id(person), user.id)

    def test_malformed_owner_entry_lists_the_account_and_does_not_stop_the_next(self):
        _, p1 = self._membership(901)
        _, p2 = self._membership(902, first="Eva", last="Lund")
        broken = self._account(owns=self._herd("G901"))
        broken.privileges = broken.privileges + [{"level": "owner"}, {"level": "owner", "herd": "abc"}]
        broken.save()
        good = self._account(fullname="Eva Lund", owns=self._herd("G902"))

        result = self._apply()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(self._linked_user_id(p1))
        self.assertEqual(self._linked_user_id(p2), good.id)
        self.assertIn("ägarroll är ofullständig", result.output)

    def test_plan_lines_and_counts_equal_what_apply_does(self):
        self._membership(901)
        self._account(owns=self._herd("G901"))
        self._membership(902)
        self._account(fullname="Eva Lund", owns=self._herd("G902"))
        self._membership(903)
        self._herd("G903")
        self._membership(904)
        self._account(owns=self._herd("G904"))
        self._membership(905, first="Maja", last="Malm")
        self._account(fullname="Maja Malm", owns=self._herd("M905", genebank=1))

        plan = self._run()
        applied = self._apply()

        self.assertEqual(applied.exit_code, 0, applied.output)
        self.assertEqual(db.Member.select().where(db.Member.user.is_null(False)).count(), 3)

        def lines(output):
            return [x for x in output.splitlines() if x.startswith("  ")]

        self.assertEqual(lines(plan.output), lines(applied.output))
        self.assertIn("Att koppla: 3", plan.output)
        self.assertIn("Kopplade: 3", applied.output)
        self.assertIn("Till granskning: 2", plan.output)
        self.assertIn("Till granskning: 2", applied.output)

    def test_plan_without_apply_lists_every_proposed_pair(self):
        _, person = self._membership(901, email="anna@example.org")
        self._account(owns=self._herd("G901"))

        result = self._run()

        self.assertIn(f"G901: member {person.id}: Anna Svensson <anna@example.org> -> user konto1", result.output)

    def test_sole_owner_in_one_membership_and_co_owner_in_another_is_not_linked(self):
        _, p1 = self._membership(901)
        _, p2 = self._membership(902)
        user = self._account(owns=self._herd("G901"))
        shared = self._herd("G902")
        user.add_role("owner", shared.id)
        self._account(fullname="Someone Else", owns=shared)

        result = self._apply()

        self.assertIsNone(self._linked_user_id(p1))
        self.assertIsNone(self._linked_user_id(p2))
        self.assertIn("flera möjliga kopplingar", result.output)

    def test_herd_code_with_leading_zero_is_not_the_members_herd(self):
        _, person = self._membership(901)
        self._account(owns=self._herd("G0901"))

        result = self._apply()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIn("Till granskning: 0", result.output)

    def test_leading_zero_herd_does_not_disturb_the_real_one(self):
        _, person = self._membership(901)
        user = self._account(owns=self._herd("G901"))
        self._account(owns=self._herd("G0901"))

        self._apply()

        self.assertEqual(self._linked_user_id(person), user.id)

    def test_decimal_herd_id_in_a_role_is_not_ownership(self):
        _, person = self._membership(901)
        herd = self._herd("G901")
        user = self._account()
        user.privileges = [{"level": "owner", "herd": herd.id + 0.75}]
        user.save()

        result = self._apply()

        self.assertIsNone(self._linked_user_id(person))
        self.assertEqual(result.exit_code, 0, result.output)

    def test_role_without_level_marks_the_account_incomplete_and_the_run_goes_on(self):
        _, p1 = self._membership(901)
        _, p2 = self._membership(902, first="Eva", last="Lund")
        broken = self._account(owns=self._herd("G901"))
        broken.privileges = broken.privileges + [{"herd": 5}, "owner"]
        broken.save()
        good = self._account(fullname="Eva Lund", owns=self._herd("G902"))

        result = self._apply()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(self._linked_user_id(p1))
        self.assertEqual(self._linked_user_id(p2), good.id)
        self.assertIn("ägarroll är ofullständig", result.output)

    def test_accounts_sharing_an_address_are_printed_with_their_own_ids(self):
        self._membership(901)
        self._membership(902, first="Eva", last="Lund")
        users = [
            db.User.create(email="delad@example.org", uuid=uuid4(), fullname=name)
            for name in ("Anna Svensson", "Eva Lund")
        ]
        for user, code in zip(users, ("G901", "G902"), strict=True):
            user.add_role("owner", self._herd(code).id)

        result = self._run()

        for user in users:
            self.assertIn(f"- <delad@example.org> (id {user.id})", result.output)

    def test_other_owner_with_a_broken_role_still_blocks_the_link(self):
        _, person = self._membership(901)
        a = self._account(owns=self._herd("G901"))
        b = self._account(owns=self._herd("M901", genebank=1, membership=None))
        b.privileges = b.privileges + [{"level": "owner"}]
        b.save()

        for result in (self._run(), self._apply()):
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("flera möjliga kopplingar", result.output)
        self.assertIsNone(self._linked_user_id(person))
        self.assertIsNone(db.Member.select().where(db.Member.user == a).first())

    def test_other_owner_on_a_duplicated_herd_code_still_blocks_the_link(self):
        _, person = self._membership(901)
        self._account(owns=self._herd("G901"))
        m1 = self._herd("M901", genebank=1, membership=None)
        self._account(owns=m1)
        self.genebanks.append(db.Genebank.create(name="Mellerud2"))
        db.Herd.create(genebank=self.genebanks[2], herd="M901", is_active=True)

        for result in (self._run(), self._apply()):
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("flera möjliga kopplingar", result.output)
        self.assertIsNone(self._linked_user_id(person))

    def test_plan_ends_with_a_checksum_line(self):
        self._membership(901)
        self._account(owns=self._herd("G901"))

        self.assertRegex(self._run().output, r"Kontrollvärde: [0-9a-f]{16}\n")

    def test_apply_without_plan_value_is_a_usage_error(self):
        _, person = self._membership(901)
        self._account(owns=self._herd("G901"))

        result = self._run("--apply", "--actor-user-id", str(self.admin.id))

        self.assertEqual(result.exit_code, 2, result.output)
        self.assertIn("--plan", result.output)
        self.assertIsNone(self._linked_user_id(person))

    def test_apply_with_unchanged_data_and_right_value_links(self):
        _, person = self._membership(901)
        user = self._account(owns=self._herd("G901"))
        value = self._plan_value()

        result = self._run("--apply", "--actor-user-id", str(self.admin.id), "--plan", value)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self._linked_user_id(person), user.id)

    def test_apply_refuses_when_the_sole_owner_was_swapped_after_the_plan(self):
        _, person = self._membership(901)
        herd = self._herd("G901")
        first = self._account(owns=herd)
        stale = self._plan_value()
        first.privileges = []
        first.save()
        self._account(owns=herd)

        result = self._apply(stale)

        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("planen har ändrats", result.output.lower())
        self.assertIn("Kontrollvärde:", result.output)
        self.assertIsNone(self._linked_user_id(person))
        self.assertEqual(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_user_linked").count(), 0)

    def test_apply_refuses_when_an_account_was_renamed_into_a_new_pair(self):
        _, p1 = self._membership(901)
        _, p2 = self._membership(902, first="Eva", last="Lund")
        self._account(owns=self._herd("G901"))
        late = self._account(fullname="Fel Namn", owns=self._herd("G902"))
        stale = self._plan_value()
        late.fullname = "Eva Lund"
        late.save()

        result = self._apply(stale)

        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIsNone(self._linked_user_id(p1))
        self.assertIsNone(self._linked_user_id(p2))
        self.assertEqual(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_user_linked").count(), 0)

    def test_herd_stored_on_another_membership_counts_that_main_member_as_counterpart(self):
        m901, p1 = self._membership(901)
        m902, p2 = self._membership(902)
        g = self._herd("G901", membership=m901)
        user = self._account(owns=g)
        user.add_role("owner", self._herd("M901", genebank=1, membership=m902).id)

        result = self._apply()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(self._linked_user_id(p1))
        self.assertIsNone(self._linked_user_id(p2))
        self.assertIn("Kopplade: 0", result.output)
        self.assertEqual(db.MatrikelAudit.select().where(db.MatrikelAudit.action == "person_user_linked").count(), 0)

    def test_herd_not_tied_to_the_membership_is_listed_not_linked(self):
        _, person = self._membership(901)
        self._account(owns=self._herd("G901", membership=None))

        result = self._apply()

        self.assertIsNone(self._linked_user_id(person))
        self.assertIn("besättningen är inte knuten till medlemskapet", result.output)

    def test_control_characters_in_labels_stay_on_one_visible_line(self):
        self._membership(901, first="Åsa", last="Öberg", email="å\nx@example.org")
        user = db.User.create(
            email="a\nb@example.org\x1b[2K", username="u\rv\u202e", uuid=uuid4(), fullname="Åsa Öberg"
        )
        user.add_role("owner", self._herd("G901").id)

        result = self._run()

        self.assertNotIn("\x1b", result.output)
        self.assertNotIn("\r", result.output)
        self.assertNotIn("\u202e", result.output)  # a right-to-left override would reorder the line on screen
        lines = [line for line in result.output.splitlines() if line.startswith("  G901:")]
        self.assertEqual(len(lines), 1, result.output)
        self.assertIn("\\x1b[2K", lines[0])
        self.assertIn("\\n", lines[0])
        self.assertIn("Åsa Öberg", lines[0])
        self.assertIn("å\\nx@example.org", lines[0])

    def test_a_refused_link_is_listed_with_its_text_and_does_not_stop_the_next(self):
        _, p1 = self._membership(901)
        _, p2 = self._membership(902, first="Eva", last="Lund")
        self._account(owns=self._herd("G901"))
        good = self._account(fullname="Eva Lund", owns=self._herd("G902"))
        real = members_cli_module.link_member_user

        def refuse_first(person_id, user_id, **kwargs):
            if person_id == p1.id:
                raise LinkError("Avvisad", "Kontot är låst\x1b[2K")
            return real(person_id, user_id, **kwargs)

        value = self._plan_value()
        with patch.object(members_cli_module, "link_member_user", refuse_first):
            result = self._run("--apply", "--actor-user-id", str(self.admin.id), "--plan", value)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(self._linked_user_id(p1))
        self.assertEqual(self._linked_user_id(p2), good.id)
        self.assertIn("Kontot är låst\\x1b[2K", result.output)
        self.assertNotIn("\x1b", result.output)
        self.assertIn("Kopplade: 1", result.output)

    def test_family_member_with_the_main_members_name_blocks_the_link(self):
        membership, person = self._membership(901)
        family = db.Member.create(membership=membership, role="familjemedlem", first_name="Anna", last_name="Svensson")
        self._account(owns=self._herd("G901"))

        for result in (self._run(), self._apply()):
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("flera personer i medlemskapet har kontots namn", result.output)
        self.assertIsNone(self._linked_user_id(person))
        self.assertIsNone(self._linked_user_id(family))

    def test_herd_with_an_odd_code_stored_on_another_membership_counts_as_counterpart(self):
        _, p1 = self._membership(901)
        m902, p2 = self._membership(902)
        user = self._account(owns=self._herd("G901"))
        user.add_role("owner", self._herd("GX9", membership=m902).id)

        for result in (self._run(), self._apply()):
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("flera möjliga kopplingar", result.output)
        self.assertIsNone(self._linked_user_id(p1))
        self.assertIsNone(self._linked_user_id(p2))
