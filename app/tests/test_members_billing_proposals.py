"""Review of billing addresses from notes. All examples are fictitious."""

import csv
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cli.billing_notes import parse_billing_note
from cli.members import members_cli
from cli.proposal_file import read_decisions, write_proposals
from click.testing import CliRunner
from flask.cli import ScriptInfo
from herdbook import APP
from utils.database import MatrikelAudit, Membership

from tests.database_test import DatabaseTest

ADDRESS = "Låtsasgården, Påhittsvägen 7B, 98765 Sagoby"
NOTE = f"Faktura: {ADDRESS}"
BILLING = {
    "billing_name": "Låtsasgården",
    "billing_address": "Påhittsvägen 7B",
    "billing_postal_code": "987 65",
    "billing_city": "Sagoby",
}


class TestBillingNote(unittest.TestCase):
    def test_only_the_labelled_address_is_returned(self):
        for excerpt in (
            NOTE,
            f"FAKTURAADRESS {ADDRESS}",
            "fakt. Låtsasgården, Påhittsvägen 7B 987 65 Sagoby",
            "Faktura till: Låtsasgården, Påhittsvägen 7B, 98765 Sagoby.",
            "Fakturamottagare:\r\nLåtsasgården\r\nPåhittsvägen 7B\r\n987 65 Sagoby",
        ):
            with self.subTest(excerpt=excerpt):
                self.assertEqual(parse_billing_note(f"Annan notering; {excerpt}\nPrivat rad"), (BILLING, excerpt))

    def test_labelled_email_and_reference(self):
        excerpt = f"{NOTE}, ref: K-77, e-post: kassa@example.invalid"
        fields = {**BILLING, "billing_reference": "K-77", "billing_email": "kassa@example.invalid"}
        self.assertEqual(parse_billing_note(f"{excerpt}; annan uppgift"), (fields, excerpt))

    def test_box_and_multiword_city(self):
        excerpt = "Fakt. Låtsasgården; Box 17; 98765 Östra Sagoby"
        fields = {**BILLING, "billing_address": "Box 17", "billing_city": "Östra Sagoby"}
        self.assertEqual(parse_billing_note(excerpt), (fields, excerpt))

    def test_uncertain_or_ambiguous_notes_have_no_proposal(self):
        for note in (
            "",
            ADDRESS,
            f"Skicka inte faktura: {ADDRESS}",
            f"Fakturabetalning: {ADDRESS}",
            "Faktura: Box 123, 12345 Sagoby",
            "Faktura: Låtsasgården, Referens 123, 12345 Sagoby",
            "Faktura: Låtsasgården, Box 123, 1234 Sagoby",
            "Faktura: Låtsasgården, Box 123, 12345",
            "Faktura: Låtsasgården, Box 123, 12345 Sagoby när vi öppnar",
            f"{NOTE}; Fakturaadress: Annat bolag, Box 2, 23456 Provby",
            f"{NOTE}, ref:  ; ring senare",
            f"{NOTE}, ref: K-77. Ring senare för besked",
        ):
            with self.subTest(note=note):
                self.assertIsNone(parse_billing_note(note))


class TestProposalFile(unittest.TestCase):
    def test_spreadsheet_protection_preserves_snapshot_for_comparison(self):
        values = ["=1+1", " =1+1", " redan inledande blanksteg"]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.csv"
            header = ("värde", "beslut")
            write_proposals(path, header, ({"värde": value} for value in values))
            with path.open(encoding="utf-8-sig", newline="") as source:
                self.assertEqual([r["värde"] for r in csv.DictReader(source)], [" " + value for value in values])
            self.assertEqual([r["värde"] for r in read_decisions(path, header)], values)

    def test_private_from_creation_and_never_overwritten(self):
        header = ("utdrag", "beslut")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.csv"

            def rows():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                yield {"utdrag": 'Påhitt, "citat"\noch radbyte', "beslut": "godkänn"}

            write_proposals(path, header, rows())
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_proposals(path, header, [])
            self.assertEqual(path.read_bytes(), original)
            with path.open(encoding="utf-8-sig", newline="") as source:
                self.assertEqual(next(csv.DictReader(source))["beslut"], "")
            self.assertEqual(
                read_decisions(path, header), [{"utdrag": 'Påhitt, "citat"\noch radbyte', "beslut": "hoppa över"}]
            )


class TestMembersBillingProposals(DatabaseTest):
    def setUp(self):
        super().setUp()
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "review.csv"

    def run_cli(self, *args):
        return CliRunner().invoke(members_cli, ["billing-proposals", *args], obj=ScriptInfo(create_app=lambda: APP))

    def export(self):
        result = self.run_cli("--out", str(self.path))
        self.assertEqual(result.exit_code, 0, result.output)
        with self.path.open(encoding="utf-8-sig", newline="") as source:
            self.rows = list(csv.DictReader(source))
        return result.output

    def review(self, *edits):
        with self.path.open("w", encoding="utf-8", newline="") as dest:
            writer = csv.DictWriter(dest, fieldnames=list(self.rows[0]))
            writer.writeheader()
            for row, edit in zip(self.rows, edits, strict=True):
                writer.writerow({**row, **edit})

    def apply(self, actor=None):
        return self.run_cli("--apply", str(self.path), "--actor-user-id", str((actor or self.admin).id))

    def test_export_only_counts_and_the_supporting_excerpt(self):
        membership = Membership.create(
            member_number=901, notes=f"Privat detalj; {NOTE}\nAnnan detalj", billing_city="Gammelby"
        )
        Membership.create(notes="Ingen adress här")
        Membership.create(notes="")
        Membership.create(notes=None)
        self.assertEqual(self.export(), "Med anteckning: 2, med förslag: 1, utan förslag: 1\n")
        self.assertEqual(len(self.rows), 1)
        row = self.rows[0]
        self.assertEqual((row["membership_id"], row["member_number"]), (str(membership.id), "901"))
        self.assertEqual((row["current_billing_city"], row["proposed_billing_city"]), ("Gammelby", "Sagoby"))
        self.assertEqual((row["anteckningsutdrag"], row["beslut"]), (NOTE, ""))
        self.assertEqual(Membership.get_by_id(membership.id).billing_city, "Gammelby")
        self.assertEqual(self.run_cli().exit_code, 2)

    def test_apply_only_reviewed_rows_and_audit_only_field_names(self):
        members = [Membership.create(notes=NOTE, billing_reference="Behåll-77") for _ in range(4)]
        self.export()
        self.review(
            {"beslut": "godkänn"},
            {
                "beslut": "ändra",
                "proposed_billing_email": "rattad@example.invalid",
                "proposed_billing_postal_code": "54321",
            },
            {"beslut": "hoppa över"},
            {},
        )
        result = self.apply()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.output, "Skrivna: 2, överhoppade: 2, ogiltiga: 0\n")
        approved, edited, skipped, blank = [Membership.get_by_id(ms.id) for ms in members]
        self.assertEqual({k: getattr(approved, k) for k in BILLING}, BILLING)
        self.assertEqual(approved.billing_reference, "Behåll-77")
        self.assertEqual((edited.billing_email, edited.billing_postal_code), ("rattad@example.invalid", "543 21"))
        self.assertIsNone(skipped.billing_name)
        self.assertIsNone(blank.billing_name)
        audits = list(MatrikelAudit.select().order_by(MatrikelAudit.id))
        self.assertEqual([a.membership_id for a in audits], [approved.id, edited.id])
        self.assertTrue(all(a.actor_id == self.admin.id and a.action == "membership_updated" for a in audits))
        self.assertEqual(audits[0].payload, {"changed_fields": list(BILLING)})
        self.assertEqual(self.apply().output, "Skrivna: 0, överhoppade: 4, ogiltiga: 0\n")
        self.assertEqual(MatrikelAudit.select().count(), 2)

    def test_stale_snapshot_and_erased_note_are_skipped(self):
        stale = Membership.create(notes=NOTE)
        erased = Membership.create(notes=NOTE)
        self.export()
        self.review({"beslut": "godkänn"}, {"beslut": "godkänn"})
        Membership.update(billing_email="ny@example.invalid").where(Membership.id == stale.id).execute()
        Membership.update(notes=None).where(Membership.id == erased.id).execute()
        self.assertEqual(self.apply().output, "Skrivna: 0, överhoppade: 2, ogiltiga: 0\n")
        self.assertEqual(Membership.get_by_id(stale.id).billing_email, "ny@example.invalid")
        self.assertFalse(Membership.select().where(Membership.billing_name.is_null(False)).exists())
        self.assertEqual(MatrikelAudit.select().count(), 0)

    def test_bad_values_count_as_invalid_and_do_not_block_a_valid_row(self):
        for _ in range(3):
            Membership.create(notes=NOTE)
        self.export()
        self.review(
            {"beslut": "ändra", "proposed_billing_email": "hemligt"},
            {"beslut": "ändra", "proposed_billing_postal_code": "12"},
            {"beslut": "godkänn"},
        )
        result = self.apply()
        self.assertEqual(result.output, "Skrivna: 1, överhoppade: 0, ogiltiga: 2\n")
        self.assertEqual(MatrikelAudit.select().count(), 1)

    def test_unknown_last_decision_or_wrong_header_rejects_whole_file(self):
        for _ in range(2):
            Membership.create(notes=NOTE)
        self.export()
        self.review({"beslut": "godkänn"}, {"beslut": "Privat beslut"})
        for bad_header in (False, True):
            with self.subTest(bad_header=bad_header):
                if bad_header:
                    self.review({"beslut": "godkänn"}, {"beslut": "godkänn"})
                    self.path.write_bytes(self.path.read_bytes().replace(b"member_number", b"Privat rubrik", 1))
                result = self.apply()
                self.assertEqual(result.exit_code, 1, result.output)
                self.assertIn("Fel rubrikrad" if bad_header else "Okänt beslut", result.output)
                self.assertNotIn("Privat", result.output)
                self.assertNotIn("Låtsasgården", result.output)
                self.assertFalse(Membership.select().where(Membership.billing_name.is_null(False)).exists())
                self.assertEqual(MatrikelAudit.select().count(), 0)

    def test_apply_requires_active_matrikel_admin_or_admin(self):
        membership = Membership.create(notes=NOTE)
        self.export()
        self.review({"beslut": "godkänn"})
        self.admin.is_active = False
        self.admin.save()
        for result in (
            self.run_cli("--apply", str(self.path)),
            self.run_cli("--apply", str(self.path), "--actor-user-id", "Privat namn"),
            self.apply(),
            self.apply(self.manager),
        ):
            self.assertEqual(result.exit_code, 2, result.output)
            self.assertIn("--actor-user-id", result.output)
            self.assertNotIn("Privat namn", result.output)
        self.assertIsNone(Membership.get_by_id(membership.id).billing_name)
        self.assertEqual(MatrikelAudit.select().count(), 0)
        self.manager.add_role("matrikel_admin", None)
        self.assertEqual(self.apply(self.manager).exit_code, 0)
        self.assertEqual(MatrikelAudit.get().actor_id, self.manager.id)
