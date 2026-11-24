"""Tests for flask members link-same-number."""

import re
from datetime import date
from unittest.mock import patch

import utils.data_access as da
import utils.database as db
from cli.members import _plan_same_number_links, members_cli
from click.testing import CliRunner
from flask.cli import ScriptInfo
from herdbook import APP

from tests.database_test import DatabaseTest


class TestMembersLinkSameNumber(DatabaseTest):
    def _run(self, *args):
        return CliRunner().invoke(members_cli, ["link-same-number", *args], obj=ScriptInfo(create_app=lambda: APP))

    def _plan(self):
        result = self._run()
        self.assertEqual(result.exit_code, 0, result.output)
        match = re.search(r"^Kontrollvärde: ([0-9a-f]{16})$", result.output, re.M)
        self.assertIsNotNone(match, result.output)
        return result.output, match.group(1)

    def _apply(self, value):
        return self._run("--apply", "--actor-user-id", str(self.admin.id), "--plan", value)

    def _herd(self, code, bank=0, **kwargs):
        return db.Herd.create(herd=code, genebank=self.genebanks[bank], **kwargs)

    def _membership(self, number, status="active", **person_fields):
        membership = db.Membership.create(member_number=number, membership_status=status, address="Testvägen 7")
        person = db.Member.create(membership=membership, first_name="Alva", last_name="Kvistskog", **person_fields)
        return membership, person

    def test_plan_and_apply_an_inactive_herd_and_membership(self):
        herd = self._herd("G7", is_active=False)
        membership, main = self._membership(7, "inactive", email="alva@example.invalid", phone="000-000000")

        output, value = self._plan()

        self.assertIn("Att koppla: 1", output)
        self.assertIn(
            f'G7 (id {herd.id}), genbank "Gotland", inaktiv -> '
            f'medlemskap nr 7 (id {membership.id}, inactive) | huvudmedlem {main.id}: "Alva Kvistskog" '
            "(inget konto) | ingen ägare",
            output,
        )
        self.assertNotIn("@example.invalid", output)
        self.assertNotIn("000-000000", output)
        self.assertIsNone(db.Herd.get_by_id(herd.id).membership_id)
        self.assertEqual(db.MatrikelAudit.select().count(), 0)

        result = self._apply(value)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Kopplade: 1, Överhoppade: 0", result.output)
        linked = db.Herd.get_by_id(herd.id)
        self.assertEqual(linked.membership_id, membership.id)
        self.assertIsNone(linked.contact_pending)
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "herd_membership_linked")
        self.assertEqual((audit.actor_id, audit.membership_id), (self.admin.id, membership.id))
        self.assertEqual(audit.payload, {"herd_id": herd.id, "main_member_id": main.id, "source": "cli"})
        self.assertEqual(db.MatrikelAudit.select().count(), 1)

    def test_already_linked_herd_is_omitted_and_missing_membership_goes_to_review(self):
        db.Membership.create(member_number=7)
        other = db.Membership.create(member_number=8)
        linked = self._herd("G7", membership=other)
        unlinked = self._herd("M9", bank=1)

        output, value = self._plan()
        candidates, review = output.split("Till granskning:")
        self.assertNotIn("G7", output)
        self.assertNotIn("M9", candidates)
        self.assertRegex(review, r"M9 .*medlemskap nr 9 saknas")

        result = self._apply(value)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Kopplade: 0", result.output)
        self.assertEqual(db.Herd.get_by_id(linked.id).membership_id, other.id)
        self.assertIsNone(db.Herd.get_by_id(unlinked.id).membership_id)
        self.assertEqual(db.MatrikelAudit.select().count(), 0)

    def test_only_the_unique_genebank_for_the_prefix_qualifies(self):
        membership, _ = self._membership(7)
        db.Genebank.create(name="Gotland två")
        self._herd("G7")
        wrong = self._herd("M7", is_active=True)
        candidate = self._herd("M7", bank=1, is_active=None)

        output, value = self._plan()
        candidates, review = output.split("Till granskning:")
        self.assertIn("Att koppla: 1", candidates)
        self.assertIn(f'M7 (id {candidate.id}), genbank "Mellerud", aktiv', candidates)
        self.assertIn(f'M7 (id {wrong.id}), genbank "Gotland", aktiv | fel genbank för prefixet', review)
        self.assertRegex(review, r"G7 .*G motsvarar 2 genbanker")

        result = self._apply(value)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual([h.id for h in db.Herd.select().where(db.Herd.membership == membership)], [candidate.id])
        self.assertIsNotNone(db.Herd.get_by_id(candidate.id).contact_pending)

    def test_conflicting_owner_is_listed_and_only_the_safe_herd_is_linked(self):
        herd = self._herd("G7")
        safe = self._herd("G9")
        membership, _ = self._membership(9)
        expected = []
        for name, number, relation in (
            ("Alva", 7, "ägaren hör till medlemskapet"),
            ("Liv", 8, "ägaren hör till ett annat medlemskap"),
            ("Vide", None, "ägaren är inte kopplad till matrikeln"),
        ):
            user = da.register_user(f"{name}@example.invalid", "pass")
            user.add_role("owner", herd.id)
            expected.append(f"konto {user.id}: {relation}")
            if number is not None:
                household, _ = self._membership(number)
                db.Member.create(
                    first_name=name,
                    last_name="Kvistskog",
                    role="familjemedlem",
                    user=user,
                    membership=household,
                    email=user.email,
                    phone="000-000000",
                )

        output, value = self._plan()
        candidates, review = output.split("Till granskning:")
        self.assertIn("Att koppla: 1", candidates)
        self.assertIn(f"G9 (id {safe.id})", candidates)
        line = next(line for line in review.splitlines() if line.startswith(f"  G7 (id {herd.id})"))
        for relation in expected:
            self.assertIn(relation, line)
        for private in ("@example.invalid", "Testvägen", "000-000000"):
            self.assertNotIn(private, output)

        result = self._apply(value)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(db.Herd.get_by_id(herd.id).membership_id)
        self.assertEqual(db.Herd.get_by_id(safe.id).membership_id, membership.id)
        self.assertEqual([row.payload["herd_id"] for row in db.MatrikelAudit.select()], [safe.id])

    def test_ended_owner_is_not_linked_to_the_register(self):
        herd = self._herd("G7")
        self._membership(7)
        user = da.register_user("liv@example.invalid", "pass")
        user.add_role("owner", herd.id)
        self._membership(8, "inactive", user=user, end_date=date(2025, 1, 1))

        output, _ = self._plan()
        candidates, _ = output.split("Till granskning:")
        self.assertRegex(candidates, rf"G7 .*konto {user.id}: ägaren är inte kopplad till matrikeln")

    def test_retired_and_headless_memberships_go_to_review(self):
        retired = self._herd("G7")
        self._membership(7, "inactive", end_date=date(2025, 1, 1))
        headless = self._herd("G8")
        self._membership(8, "inactive", role="familjemedlem")

        output, value = self._plan()
        candidates, review = output.split("Till granskning:")
        self.assertIn("Att koppla: 0", candidates)
        self.assertRegex(review, rf"G7 \(id {retired.id}\).*medlemskapet är avslutat")
        self.assertRegex(review, rf"G8 \(id {headless.id}\).*medlemskapet saknar huvudmedlem")
        result = self._apply(value)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(db.Herd.get_by_id(retired.id).membership_id)
        self.assertIsNone(db.Herd.get_by_id(headless.id).membership_id)
        self.assertEqual(db.MatrikelAudit.select().count(), 0)

    def test_owner_with_an_incomplete_role_goes_to_review(self):
        herd = self._herd("G7")
        self._membership(7)
        user = da.register_user("vide@example.invalid", "pass")
        user.add_role("owner", herd.id)
        user.privileges = [*user.privileges, {"level": "owner"}]
        user.save()

        output, _ = self._plan()
        candidates, review = output.split("Till granskning:")
        self.assertIn("Att koppla: 0", candidates)
        self.assertRegex(review, rf"G7 \(id {herd.id}\).*kontots ägarroll är ofullständig")

    def test_changes_to_candidate_or_review_lines_invalidate_the_plan(self):
        herd = self._herd("G7", is_active=True)
        review = self._herd("G8", is_active=True)
        self._membership(7)
        _, value = self._plan()
        self.owner.add_role("owner", herd.id)
        result = self._apply(value)
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("planen har ändrats", result.output)

        _, value = self._plan()
        db.Herd.update(is_active=False).where(db.Herd.id == review.id).execute()
        result = self._apply(value)
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("planen har ändrats", result.output)
        self.assertIsNone(db.Herd.get_by_id(herd.id).membership_id)
        self.assertEqual(db.MatrikelAudit.select().count(), 0)

    def test_plan_checksum_changes_when_the_new_main_has_the_same_name(self):
        self._herd("G7")
        membership, main = self._membership(7)
        _, value = self._plan()
        db.Member.update(role="familjemedlem").where(db.Member.id == main.id).execute()
        db.Member.create(membership=membership, first_name=main.first_name, last_name=main.last_name)

        result = self._apply(value)
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("planen har ändrats", result.output)
        self.assertEqual(db.MatrikelAudit.select().count(), 0)

    def test_an_account_linked_to_the_main_member_after_the_plan_is_skipped(self):
        herd = self._herd("G7")
        _, main = self._membership(7)
        _, value = self._plan()
        account = da.register_user("nytt.konto@example.invalid", "pass", username="nyttkonto", fullname="Ny Person")

        def plan_then_link():
            plan = _plan_same_number_links()
            db.Member.update(user=account.id).where(db.Member.id == main.id).execute()
            return plan

        with patch("cli.members._plan_same_number_links", plan_then_link):
            result = self._apply(value)
        self.assertIn(f"G7 (id {herd.id}): huvudmedlemmen eller huvudmedlemmens konto har ändrats", result.output)
        self.assertIsNone(db.Herd.get_by_id(herd.id).membership_id)
        self.assertEqual(db.MatrikelAudit.select().count(), 0)

    def test_changed_rows_are_skipped_under_lock_and_each_reason_is_printed(self):
        renumbered = self._herd("G7")
        membership, _ = self._membership(7)
        swapped = self._herd("G8")
        other, main = self._membership(8)
        linked = self._herd("G9")
        self._membership(9)
        _, value = self._plan()

        def plan_then_change():
            plan = _plan_same_number_links()
            db.Membership.update(member_number=17).where(db.Membership.id == membership.id).execute()
            db.Member.update(role="familjemedlem").where(db.Member.id == main.id).execute()
            db.Member.create(membership=other, first_name="Lova", last_name="Kvistskog")
            db.Herd.update(membership=other).where(db.Herd.id == linked.id).execute()
            return plan

        with patch("cli.members._plan_same_number_links", plan_then_change):
            result = self._apply(value)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Kopplade: 0, Överhoppade: 3", result.output)
        self.assertIn(f"G7 (id {renumbered.id}): medlemsnumret hör inte längre till medlemskapet", result.output)
        self.assertIn(f"G8 (id {swapped.id}): huvudmedlemmen eller huvudmedlemmens konto har ändrats", result.output)
        self.assertIn(f"G9 (id {linked.id}): besättningen är redan kopplad", result.output)
        self.assertIsNone(db.Herd.get_by_id(renumbered.id).membership_id)
        self.assertIsNone(db.Herd.get_by_id(swapped.id).membership_id)
        self.assertEqual(db.Herd.get_by_id(linked.id).membership_id, other.id)
        self.assertEqual(db.MatrikelAudit.select().count(), 0)
