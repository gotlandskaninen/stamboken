"""Tests for flask members link-same-number."""

import re
from unittest.mock import patch

import utils.data_access as da
import utils.database as db
from cli.members import members_cli
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

    def test_plan_and_apply_an_inactive_herd_and_membership(self):
        herd = self._herd("G7", is_active=False)
        membership = db.Membership.create(member_number=7, membership_status="inactive")

        output, value = self._plan()

        self.assertIn("Att koppla: 1", output)
        self.assertIn(
            f'G7 (id {herd.id}), genbank "Gotland", inaktiv -> '
            f"medlemskap nr 7 (id {membership.id}, inactive) | ingen ägare",
            output,
        )
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
        self.assertEqual(audit.payload, {"herd_id": herd.id, "source": "cli"})
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
        membership = db.Membership.create(member_number=7)
        db.Genebank.create(name="Gotland två")
        self._herd("G7")
        self._herd("M7")  # right number, wrong genebank
        candidate = self._herd("M7", bank=1, is_active=True)

        output, value = self._plan()
        candidates, review = output.split("Till granskning:")
        self.assertIn("Att koppla: 1", candidates)
        self.assertIn(f'M7 (id {candidate.id}), genbank "Mellerud", aktiv', candidates)
        self.assertRegex(review, r"G7 .*G motsvarar 2 genbanker")

        result = self._apply(value)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual([h.id for h in db.Herd.select().where(db.Herd.membership == membership)], [candidate.id])
        self.assertIsNotNone(db.Herd.get_by_id(candidate.id).contact_pending)

    def test_each_owner_relationship_is_shown_without_contact_details(self):
        herd = self._herd("G7")
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
                membership = db.Membership.create(member_number=number, address="Testvägen 7")
                db.Member.create(
                    first_name=name,
                    last_name="Kvistskog",
                    role="familjemedlem",
                    user=user,
                    membership=membership,
                    email=user.email,
                    phone="000-000000",
                )

        output, _ = self._plan()
        line = next(line for line in output.splitlines() if line.startswith("  G7 "))
        for relation in expected:
            self.assertIn(relation, line)
        for private in ("@example.invalid", "Testvägen", "000-000000"):
            self.assertNotIn(private, output)

    def test_changes_to_candidate_or_review_lines_invalidate_the_plan(self):
        herd = self._herd("G7", is_active=True)
        review = self._herd("G8", is_active=True)
        db.Membership.create(member_number=7)
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

    def test_link_refused_under_lock_is_counted_and_not_logged(self):
        herd = self._herd("G7")
        membership = db.Membership.create(member_number=7)
        _, value = self._plan()
        with patch("cli.members.link_herd", return_value=None) as link:
            result = self._apply(value)
        self.assertEqual(result.exit_code, 0, result.output)
        link.assert_called_once_with(herd.id, membership.id, herd_code="G7", genebank_id=herd.genebank_id)
        self.assertIn("Kopplade: 0, Överhoppade: 1", result.output)
        self.assertEqual(db.MatrikelAudit.select().count(), 0)
