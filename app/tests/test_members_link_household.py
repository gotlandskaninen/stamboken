"""Tests for flask members link-household (herds that several accounts own) and the owner-role guard."""

import csv
import os
import re
from tempfile import TemporaryDirectory
from unittest.mock import patch

import cli.members as members_cli_module
import utils.data_access as da
import utils.database as db
from cli.members import members_cli
from click.testing import CliRunner
from flask.cli import ScriptInfo
from herdbook import APP  # noqa: E402
from utils.matrikel import LinkError

from tests.database_test import DatabaseTest  # noqa: E402

HEADER = [
    "First Name [Required]",
    "Last Name [Required]",
    "Email Address [Required]",
    "Password Hash Function [UPLOAD ONLY]",
    "Recovery Email",
    "Home Secondary Email",
    "Work Secondary Email",
    "Mobile Phone",
]
NOTE = "godkänt av huvudmedlemmen muntligt eller per mejl, inhämtat av matrikelansvarig före 2026-11"


class TestMembersLinkHousehold(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.runner = CliRunner()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = os.path.join(self._tmp.name, "users.csv")
        self.rows = []
        self._n = 0

    def _workspace_row(self, account, first, last, home="", recovery="", work=""):
        self.rows.append([first, last, account, "SHA-1", recovery, home, work, "+46 70 000 00 00"])

    def _run(self, *extra):
        with open(self.workspace, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows([HEADER, *self.rows])
        return self.runner.invoke(
            members_cli,
            ["link-household", "--workspace", self.workspace, *extra],
            obj=ScriptInfo(create_app=lambda: APP),
        )

    def _plan_value(self):
        match = re.search(r"^Kontrollvärde: ([0-9a-f]{16})$", self._run().output, re.M)
        return match.group(1)

    def _apply(self, plan=None):
        plan = plan or self._plan_value()
        return self._run("--apply", "--actor-user-id", str(self.admin.id), "--plan", plan)

    def _household(self, number=901, first="Anna", last="Svensson"):
        membership = db.Membership.create(member_number=number, membership_status="active")
        main = db.Member.create(membership=membership, role="huvudmedlem", first_name=first, last_name=last)
        herd = db.Herd.create(genebank=self.genebanks[0], herd=f"G{number}", membership=membership, is_active=True)
        return membership, main, herd

    def _account(self, fullname, owns=(), email=None, google=None):
        """An `email` is also the account's verified Google address unless `google` says otherwise."""
        self._n += 1
        user = da.register_user(
            email or f"konto{self._n}@example.org", "pass", username=f"k{self._n}", fullname=fullname
        )
        user.google_email = email if google is None else google or None
        user.save()
        for herd in owns:
            user.add_role("owner", herd.id)
        return user

    def _added(self, membership):
        return list(db.Member.select().where(db.Member.membership == membership, db.Member.role == "familjemedlem"))

    def _notices(self):
        return list(db.MailMessage.select().where(db.MailMessage.kind == "medlemskap.tillagd"))

    def test_main_member_linked_and_household_account_added_as_familjemedlem(self):
        membership, main, herd = self._household()
        anna = self._account("Anna Svensson", owns=[herd])
        bo = self._account("Bo", owns=[herd], email="bo@example.org")
        self._workspace_row("BO@example.org ", "Bo", "Svensson", home="bo.hemma@example.net", recovery="x@example.net")

        plan = self._run()
        self.assertEqual(plan.exit_code, 0, plan.output)
        self.assertIn("Att koppla: 2", plan.output)
        self.assertIn("ny familjemedlem i medlemskap", plan.output)
        self.assertIn('"Bo Svensson" "bo.hemma@example.net" (Home Secondary Email)', plan.output)
        self.assertNotIn("SHA-1", plan.output)
        self.assertNotIn("+46", plan.output)
        self.assertEqual(self._added(membership), [])

        result = self._apply()

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Kopplade: 2", result.output)
        self.assertEqual(db.Member.get_by_id(main.id).user_id, anna.id)
        [person] = self._added(membership)
        self.assertEqual(
            (person.first_name, person.last_name, person.email, person.user_id, person.notes),
            ("Bo", "Svensson", "bo.hemma@example.net", bo.id, NOTE),
        )
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "person_added")
        self.assertEqual((audit.payload["person_id"], audit.actor_id), (person.id, self.admin.id))
        [notice] = self._notices()
        self.assertEqual(notice.recipient_id, person.id)

        again = self._run()
        self.assertIn("Att koppla: 0, Redan kopplade: 2, Till granskning: 0", again.output)

    def test_recovery_email_when_home_secondary_is_empty(self):
        membership, _, herd = self._household()
        self._account("Anna Svensson", owns=[herd])
        self._account("Bo Svensson", owns=[herd], email="bo@example.org")
        self._workspace_row("bo@example.org", "Bo", "Svensson", recovery="bo.reserv@example.net", work="w@example.net")

        result = self._apply()

        self.assertEqual(result.exit_code, 0, result.output)
        [person] = self._added(membership)
        self.assertEqual(person.email, "bo.reserv@example.net")

    def test_google_email_finds_the_row(self):
        membership, _, herd = self._household()
        self._account("Anna Svensson", owns=[herd])
        bo = self._account("Bo Svensson", owns=[herd], email="privat@example.org")
        bo.google_email = "bo@gotlandskaninen.se"
        bo.save()
        self._workspace_row("bo@gotlandskaninen.se", "Bo", "Svensson", work="bo.jobb@example.net")

        self.assertEqual(self._apply().exit_code, 0)
        [person] = self._added(membership)
        self.assertEqual((person.email, person.user_id), ("bo.jobb@example.net", bo.id))

    def test_only_the_verified_google_address_identifies_the_row(self):
        membership, _, herd = self._household()
        self._account("Anna Svensson", owns=[herd])
        no_google = self._account("Bo Svensson", owns=[herd], email="bo@gotlandskaninen.se", google="")
        conflict = self._account(
            "Cia Svensson", owns=[herd], email="dan@gotlandskaninen.se", google="cia@gotlandskaninen.se"
        )
        self._workspace_row("bo@gotlandskaninen.se", "Bo", "Svensson", home="bo.hemma@example.net")
        self._workspace_row("cia@gotlandskaninen.se", "Cia", "Svensson", home="cia.hemma@example.net")
        self._workspace_row("dan@gotlandskaninen.se", "Dan", "Svensson", home="dan.hemma@example.net")

        plan = self._run()

        self.assertIn(f"konto {no_google.id}: kontot har ingen verifierad Google-adress", plan.output)
        self.assertIn(f"konto {conflict.id}: kontots e-post och Google-adress hör till olika rader", plan.output)
        self._apply()
        self.assertEqual(self._added(membership), [])

    def test_missing_row_or_secondary_address_is_listed(self):
        membership, main, herd = self._household()
        anna = self._account("Anna Svensson", owns=[herd])
        no_row = self._account("Bo Svensson", owns=[herd], email="bo@example.org")
        no_address = self._account("Cia Svensson", owns=[herd], email="cia@example.org")
        self._workspace_row("cia@example.org", "Cia", "Svensson")

        plan = self._run()
        self.assertIn(f"G901: konto {no_row.id}: kontots Google-adress finns inte i Workspace-exporten", plan.output)
        self.assertIn(f"G901: konto {no_address.id}: Workspace-raden saknar reservadress", plan.output)

        result = self._apply()

        self.assertIn("Kopplade: 1", result.output)  # only the main member's own account
        self.assertEqual(db.Member.get_by_id(main.id).user_id, anna.id)
        self.assertEqual(self._added(membership), [])
        self.assertEqual(self._notices(), [])

    def test_address_another_member_logs_in_with_is_listed(self):
        membership, _, herd = self._household()
        other, _, _ = self._household(902, first="Eva", last="Ek")
        db.Member.update(email="upptagen@example.net").where(db.Member.membership == other).execute()
        self._account("Anna Svensson", owns=[herd])
        bo = self._account("Bo Svensson", owns=[herd], email="bo@example.org")
        self._workspace_row("bo@example.org", "Bo", "Svensson", home="upptagen@example.net")

        plan = self._run()

        self.assertIn(f"konto {bo.id}: ingen reservadress i Workspace-raden går att använda", plan.output)
        self.assertIn("Home Secondary Email: en annan medlem loggar redan in med adressen (AddressTaken)", plan.output)
        self._apply()
        self.assertEqual(self._added(membership), [])

    def test_person_already_in_the_membership_is_not_added_twice(self):
        membership, _, herd = self._household()
        db.Member.create(membership=membership, role="familjemedlem", first_name="Bo", last_name="B", email="Bo@Ex.net")
        self._account("Anna Svensson", owns=[herd])
        bo = self._account("Bo Svensson", owns=[herd], email="bo@example.org")
        self._workspace_row("bo@example.org", "Bo", "Svensson", home=" bo@EX.net ")

        plan = self._run()

        self.assertIn(f"konto {bo.id}: ingen reservadress", plan.output)
        self.assertIn("Home Secondary Email: en person i medlemskapet har adressen", plan.output)

    def test_person_with_the_same_name_is_not_added_twice(self):
        membership, _, herd = self._household()
        db.Member.create(membership=membership, role="familjemedlem", first_name="BO", last_name=" svensson")
        self._account("Anna Svensson", owns=[herd])
        bo = self._account("B S", owns=[herd], email="bo@example.org")  # only the Workspace name is the same
        self._workspace_row("bo@example.org", "Bo", "Svensson", home="bo.hemma@example.net")

        plan = self._run()

        self.assertIn(f"konto {bo.id}: medlemskapet har redan en person med samma namn", plan.output)

    def test_an_address_in_the_associations_domain_is_never_the_login_address(self):
        membership, _, herd = self._household()
        self._account("Anna Svensson", owns=[herd])
        bo = self._account("Bo Svensson", owns=[herd], email="bo@example.org")
        self._workspace_row("bo@example.org", "Bo", "Svensson", home="Bo.S@Gotlandskaninen.se ")

        plan = self._run()

        self.assertIn(f"konto {bo.id}: ingen reservadress", plan.output)
        self.assertIn("Home Secondary Email: föreningens egen adress", plan.output)
        self._apply()
        self.assertEqual(self._added(membership), [])

    def test_the_next_address_column_is_used_when_one_fails_a_check(self):
        membership, _, herd = self._household()
        other, _, _ = self._household(902, first="Eva", last="Ek")
        db.Member.update(email="upptagen@example.net").where(db.Member.membership == other).execute()
        self._account("Anna Svensson", owns=[herd])
        self._account("Bo Svensson", owns=[herd], email="bo@example.org")
        self._workspace_row(
            "bo@example.org", "Bo", "Svensson", home="upptagen@example.net", recovery="ogiltig", work="bo@example.net"
        )

        plan = self._run()
        self.assertIn('"bo@example.net" (Work Secondary Email)', plan.output)
        self._apply()
        [person] = self._added(membership)
        self.assertEqual(person.email, "bo@example.net")

    def test_role_account_and_account_in_two_memberships_are_listed(self):
        membership, _, herd = self._household()
        _, _, other_herd = self._household(902, first="Eva", last="Ek")
        self._account("Anna Svensson", owns=[herd])
        manager = self._account("Bo Svensson", owns=[herd], email="bo@example.org")
        manager.add_role("manager", self.genebanks[0].id)
        two = self._account("Cia Svensson", owns=[herd, other_herd], email="cia@example.org")
        self._workspace_row("bo@example.org", "Bo", "Svensson", home="bo.hemma@example.net")
        self._workspace_row("cia@example.org", "Cia", "Svensson", home="cia.hemma@example.net")

        plan = self._run()

        self.assertIn(f"konto {manager.id}: kontot har en roll", plan.output)
        self.assertIn(f"konto {two.id}: kontot äger besättningar i flera medlemskap", plan.output)
        self._apply()
        self.assertEqual(self._added(membership), [])

    def test_no_account_matching_the_main_member_writes_nothing(self):
        membership, main, herd = self._household()
        self._account("Bo Svensson", owns=[herd], email="bo@example.org")
        self._account("Cia Svensson", owns=[herd], email="cia@example.org")
        self._workspace_row("bo@example.org", "Bo", "Svensson", home="bo.hemma@example.net")

        plan = self._run()

        self.assertIn("G901: inget konto matchar huvudmedlemmen", plan.output)
        self.assertIn("Att koppla: 0", plan.output)

    def test_main_member_match_that_also_matches_another_person_is_listed(self):
        """A weak match on the main member loses to an exact match on a family member (as in link-by-herd)."""
        membership, main, herd = self._household(first="Eva", last="Lund")
        db.Member.update(email="bo.lund@example.org").where(db.Member.id == main.id).execute()
        db.Member.create(
            membership=membership,
            role="familjemedlem",
            first_name="Bo",
            last_name="Lund",
            workspace_email="bo.lund@gotlandskaninen.se",
        )
        self._account("Bo Lund", owns=[herd], email="bo.lund@gotlandskaninen.se")
        self._account("Cia Lund", owns=[herd], email="cia@example.org")
        self._workspace_row("cia@example.org", "Cia", "Lund", home="cia.hemma@example.net")

        plan = self._run()

        self.assertIn("G901: flera möjliga kopplingar", plan.output)
        self.assertIn("Att koppla: 0", plan.output)
        self._apply()
        self.assertIsNone(db.Member.get_by_id(main.id).user_id)
        self.assertEqual(len(self._added(membership)), 1)  # only the family member created above

    def test_account_matching_an_existing_person_is_not_added_again(self):
        membership, _, herd = self._household()
        bo_row = db.Member.create(
            membership=membership, role="familjemedlem", first_name="Bo", last_name="Svensson", email="bo@example.org"
        )
        self._account("Anna Svensson", owns=[herd])
        bo = self._account("Bosse S", owns=[herd], email="bo@example.org")
        self._workspace_row("bo@example.org", "Bosse", "S", home="bo.hemma@example.net")

        plan = self._run()

        self.assertIn(f"konto {bo.id}: kontot matchar en person i medlemskapet", plan.output)
        self._apply()
        self.assertEqual(self._added(membership), [bo_row])

    def test_colliding_candidates_are_all_listed_before_any_write(self):
        membership, _, herd = self._household()
        other, _, other_herd = self._household(902, first="Eva", last="Ek")
        self._account("Anna Svensson", owns=[herd])
        self._account("Eva Ek", owns=[other_herd])
        same_name = [
            self._account("Bo", owns=[herd], email="bo1@example.org"),
            self._account("Bo", owns=[herd], email="bo2@example.org"),
        ]
        same_address = [
            self._account("Cia Svensson", owns=[herd], email="cia@example.org"),
            self._account("Dan Ek", owns=[other_herd], email="dan@example.org"),
        ]
        self._workspace_row("bo1@example.org", "Bo", "Svensson", home="bo1@example.net")
        self._workspace_row("bo2@example.org", "Bo", "Svensson", home="bo2@example.net")
        self._workspace_row("cia@example.org", "Cia", "Svensson", home="delad@example.net")
        self._workspace_row("dan@example.org", "Dan", "Ek", home="delad@example.net")

        plan = self._run()

        for user in same_name:
            self.assertIn(f"konto {user.id}: flera konton i planen får samma namn i medlemskapet", plan.output)
        for user in same_address:
            self.assertIn(f"konto {user.id}: flera konton i planen får samma adress", plan.output)
        self._apply()
        self.assertEqual(self._added(membership) + self._added(other), [])

    def _household_of_two(self):
        membership, main, herd = self._household()
        self._account("Anna Svensson", owns=[herd])
        bo = self._account("Bo Svensson", owns=[herd], email="bo@example.org")
        self._workspace_row("bo@example.org", "Bo", "Svensson", home="bo.hemma@example.net")
        return membership, main, herd, bo

    def _apply_with(self, before_link):
        """Apply, calling before_link(person_id) right before each link_member_user (instead of it, if it raises)."""
        plan = self._plan_value()
        real = members_cli_module.link_member_user

        def link(person_id, user_id, **kwargs):
            before_link(person_id)
            return real(person_id, user_id, **kwargs)

        with patch.object(members_cli_module, "link_member_user", side_effect=link):
            return self._apply(plan=plan)

    def test_refused_main_link_skips_the_household(self):
        membership, main, _, bo = self._household_of_two()

        def refuse_main(person_id):
            if person_id == main.id:
                raise LinkError("Avvisad", "avvisad i testet")

        result = self._apply_with(refuse_main)

        self.assertIn(f"konto {bo.id}: inte tillagt, huvudmedlemmens koppling avvisades", result.output)
        self.assertEqual(self._added(membership), [])
        self.assertEqual(self._notices(), [])

    def test_owner_role_revoked_after_the_plan_stops_the_add(self):
        membership, main, herd, bo = self._household_of_two()

        def revoke(person_id):
            if person_id == main.id:  # an admin takes the owner role away meanwhile
                da.update_role({"action": "remove", "role": "owner", "user": bo.id, "herd": herd.id}, self.admin.uuid)

        result = self._apply_with(revoke)

        self.assertIn("Kontot har inte längre rollen ägare på besättningen", result.output)
        self.assertIsNotNone(db.Member.get_by_id(main.id).user_id)
        self.assertEqual(self._added(membership), [])
        self.assertEqual(self._notices(), [])

    def test_inactive_membership_after_the_plan_stops_the_add(self):
        membership, main, _, _ = self._household_of_two()

        def retire(person_id):
            if person_id == main.id:
                db.Membership.update(membership_status="inactive").where(db.Membership.id == membership.id).execute()

        result = self._apply_with(retire)

        self.assertIn("Medlemskapet är inte längre aktivt", result.output)
        self.assertEqual(self._added(membership), [])

    def test_changed_plan_writes_nothing(self):
        membership, main, herd = self._household()
        self._account("Anna Svensson", owns=[herd])
        self._account("Bo Svensson", owns=[herd], email="bo@example.org")
        self._workspace_row("bo@example.org", "Bo", "Svensson", home="bo.hemma@example.net")
        stale = self._plan_value()
        self.rows[0][5] = "bo.annan@example.net"  # the export changed after the plan was read

        result = self._apply(plan=stale)

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("planen har ändrats", result.output)
        self.assertIsNone(db.Member.get_by_id(main.id).user_id)
        self.assertEqual(self._added(membership), [])
