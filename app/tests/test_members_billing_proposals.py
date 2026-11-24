"""Review of billing addresses from notes. All examples are fictitious."""

import csv
import os
import stat
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cli.billing_notes import parse_billing_note
from cli.members import members_cli
from cli.proposal_file import read_decisions, write_proposals
from click.testing import CliRunner
from flask.cli import ScriptInfo
from herdbook import APP
from peewee import DatabaseError
from utils.database import MatrikelAudit, Member, Membership
from utils.matrikel import REDACTED_VALUE, redact_household_from_audits, write_matrikel_audit

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
        fields = {**BILLING, "billing_reference": "K-77", "billing_email": "kassa@example.invalid"}
        for details in (
            ", ref: K-77., e-post: kassa@example.invalid.",
            ", e-post: kassa@example.invalid, ref: K-77",
            "\r\nreferens: K-77\ne-post: kassa@example.invalid",
            ", \n e-post: kassa@example.invalid; \r\n ref: K-77",
            "; \r\n e-post: kassa@example.invalid, \n ref: K-77",
        ):
            with self.subTest(details=details):
                excerpt = NOTE + details
                self.assertEqual(parse_billing_note(f"{excerpt} \t\nannan uppgift"), (fields, excerpt))

    def test_detail_after_a_blank_line_is_not_taken(self):
        for separator in ("\n\n", ", \n \n", "; \r\n \r\n"):
            with self.subTest(separator=separator):
                self.assertEqual(parse_billing_note(f"{NOTE}{separator}ref: K-77"), (BILLING, NOTE))

    def test_box_and_multiword_city(self):
        excerpt = "Fakt. Låtsasgården; Box 17; 98765 Östra Sagoby"
        fields = {**BILLING, "billing_address": "Box 17", "billing_city": "Östra Sagoby"}
        self.assertEqual(parse_billing_note(f"{excerpt}; annan uppgift"), (fields, excerpt))

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
            f"{NOTE}; alternativ fakturamottagare: Annat bolag",
            f"{NOTE}, gäller ej längre",
            f"{NOTE}; ny fakturaadress: Annat bolag, Box 2, 23456 Provby",
            f"GÄLLER INTE; {NOTE}",
            f"{NOTE}, gäller ej",
            f"{NOTE}; inte längre aktuell",
            f"Ej längre aktuell; {NOTE}",
            f"{NOTE}; ANVÄND POSTADRESSEN",
            f"{NOTE}; använd inte denna adress",
            f"{NOTE}; använd ej denna adress",
            f"{NOTE}; återkallad",
            f"{NOTE}; återkallas",
            f"{NOTE}; ska inte användas",
            f"{NOTE}; får ej användas",
            f"{NOTE}, ref:  ; ring senare",
            f"{NOTE}, ref: K-77. Ring senare för besked",
            "Byt fakturamejl till ny@example.invalid; Faktura: Provbolaget, Box 1, 12345 Sagoby, "
            "e-post: gammal@example.invalid",
            "Faktura: Provbolaget, Box 1, 12345 Sagoby;\ne-post: privat@example.invalid, endast för medlemsbrev",
            f"{NOTE}, e-post: kassa@example.invalid, ref: K-77; annan uppgift",
            f"{NOTE}, e-post: ett@example.invalid, tva@example.invalid",
            f"{NOTE}, e-post: ett@example.invalid/tva@example.invalid",
            f"{NOTE}\n\ne-post: annan@example.invalid",
            f"{NOTE}; kontakt: annan@example.invalid",
        ):
            with self.subTest(note=note):
                self.assertIsNone(parse_billing_note(note))


class TestProposalFile(unittest.TestCase):
    def test_read_requires_private_owned_regular_file_without_following_symlinks(self):
        header = ("beslut",)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.csv"
            path.write_bytes(b"\xff")  # Decoding would fail if a rejected file were read.
            for mode in (0o640, 0o601):
                path.chmod(mode)
                with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "privat, vanlig fil"):
                    read_decisions(path, header)
            path.chmod(0o600)
            with patch("cli.proposal_file.os.geteuid", return_value=path.stat().st_uid + 1):
                with self.assertRaisesRegex(ValueError, "ägs av den körande användaren"):
                    read_decisions(path, header)
            link = Path(tmp) / "link.csv"
            link.symlink_to(path)
            with self.assertRaises(OSError):
                read_decisions(link, header)
            fifo = Path(tmp) / "fifo"
            os.mkfifo(fifo, 0o600)
            with self.assertRaisesRegex(ValueError, "privat, vanlig fil"):
                read_decisions(fifo, header)

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

    def membership(self, **fields):
        ms = Membership.create(**fields)
        Member.create(membership=ms, first_name="Prov", last_name="Exempel")
        return ms

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

    def assert_counts(self, written=0, skipped=0, stale=0, unapproved=0, invalid=0, unchanged=0):
        result = self.apply()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            result.output,
            f"Skrivna: {written}, hoppa över (beslut): {skipped}, underlaget har ändrats: {stale}, "
            f"ändrad rad utan beslutet ändra: {unapproved}, ogiltiga värden: {invalid}, oförändrade: {unchanged}\n",
        )

    def test_export_only_changed_proposals_for_current_memberships_with_whole_note(self):
        membership = self.membership(
            member_number=901, notes=f"Privat detalj; {NOTE}\nAnnan detalj", billing_city="Gammelby"
        )
        Member.create(
            membership=membership,
            first_name="Före",
            last_name="Exempel",
            role="familjemedlem",
            end_date=date(2020, 1, 1),
        )
        ended = self.membership(notes=NOTE)
        Member.update(end_date=date(2020, 1, 1)).where(Member.membership == ended).execute()
        self.membership(notes=NOTE, **BILLING)
        self.membership(notes="Ingen adress här")
        self.membership(notes="")
        self.membership(notes=None)
        self.assertEqual(self.export(), "Med anteckning: 3, med förslag: 1, utan förslag: 2\n")
        self.assertEqual(len(self.rows), 1)
        row = self.rows[0]
        self.assertEqual((row["membership_id"], row["member_number"]), (str(membership.id), "901"))
        self.assertEqual((row["current_billing_city"], row["proposed_billing_city"]), ("Gammelby", "Sagoby"))
        self.assertEqual((row["anteckning"], row["beslut"]), (membership.notes, ""))
        self.assertRegex(row["underlag"], r"^[0-9a-f]{64}$")
        self.assertEqual(Membership.get_by_id(membership.id).billing_city, "Gammelby")
        self.assertEqual(self.run_cli().exit_code, 2)

    def test_ending_main_member_invalidates_proposal_even_with_current_family_member(self):
        ms = self.membership(notes=NOTE)
        Member.create(membership=ms, first_name="Familj", last_name="Exempel", role="familjemedlem")
        self.export()
        self.review({"beslut": "godkänn"})
        Member.update(end_date=date(2020, 1, 1)).where(Member.membership == ms, Member.role == "huvudmedlem").execute()
        self.assert_counts(stale=1)
        self.assertIsNone(Membership.get_by_id(ms.id).billing_name)
        self.path = self.path.with_name("ny-export.csv")
        self.assertEqual(self.export(), "Med anteckning: 0, med förslag: 0, utan förslag: 0\n")
        self.assertEqual(self.rows, [])

    def test_export_proposes_next_line_email_over_current_email(self):
        self.membership(
            notes="Faktura: Namn, Storgatan 1, 12345 Visby\ne-post: ny@example.invalid",
            billing_email="gammal@example.invalid",
        )
        self.export()
        (row,) = self.rows
        self.assertEqual(row["current_billing_email"], "gammal@example.invalid")
        self.assertEqual(row["proposed_billing_email"], "ny@example.invalid")

    def test_export_counts_notes_over_100000_characters_as_without_proposal(self):
        at_limit = (NOTE + "\n").ljust(100_000, "ö")
        self.membership(notes=at_limit)
        self.membership(notes=at_limit + "ö")
        self.assertEqual(self.export(), "Med anteckning: 2, med förslag: 1, utan förslag: 1\n")
        self.assertEqual([row["anteckning"] for row in self.rows], [at_limit])
        self.review({"beslut": "godkänn"})
        self.assert_counts(written=1)

    def test_apply_only_reviewed_rows_and_audit_before_and_after(self):
        members = [
            self.membership(notes=NOTE, billing_reference="Behåll-77", billing_city="Gammelby") for _ in range(4)
        ]
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
        self.assert_counts(written=2, skipped=2)
        approved, edited, skipped, blank = [Membership.get_by_id(ms.id) for ms in members]
        self.assertEqual({k: getattr(approved, k) for k in BILLING}, BILLING)
        self.assertEqual(approved.billing_reference, "Behåll-77")
        self.assertEqual((edited.billing_email, edited.billing_postal_code), ("rattad@example.invalid", "543 21"))
        self.assertIsNone(skipped.billing_name)
        self.assertIsNone(blank.billing_name)
        audits = list(MatrikelAudit.select().order_by(MatrikelAudit.id))
        self.assertEqual([a.membership_id for a in audits], [approved.id, edited.id])
        self.assertTrue(all(a.actor_id == self.admin.id and a.action == "membership_updated" for a in audits))
        before = dict.fromkeys(BILLING) | {"billing_city": "Gammelby"}
        self.assertEqual(audits[0].payload, {"before": before, "after": BILLING})
        self.assert_counts(stale=2, skipped=2)
        self.assertEqual(MatrikelAudit.select().count(), 2)
        self.assertEqual(redact_household_from_audits(approved), 1)
        self.assertEqual(
            MatrikelAudit.get_by_id(audits[0].id).payload,
            {"before": before | {"billing_city": REDACTED_VALUE}, "after": dict.fromkeys(BILLING, REDACTED_VALUE)},
        )

    def test_stale_billing_note_number_or_ended_membership_are_skipped(self):
        stale, corrected, erased, renumbered, ended = [self.membership(notes=NOTE) for _ in range(5)]
        self.export()
        corrected_note = f"{NOTE}, gäller ej längre"
        # Even matching edits to the visible source cells cannot replace the exported proof.
        self.review(
            {"beslut": "godkänn", "current_billing_email": "ny@example.invalid"},
            {"beslut": "godkänn", "anteckning": corrected_note},
            {"beslut": "godkänn"},
            {"beslut": "godkänn", "member_number": "902"},
            {"beslut": "godkänn"},
        )
        Membership.update(billing_email="ny@example.invalid").where(Membership.id == stale.id).execute()
        Membership.update(notes=corrected_note).where(Membership.id == corrected.id).execute()
        Membership.update(notes=None).where(Membership.id == erased.id).execute()
        Membership.update(member_number=902).where(Membership.id == renumbered.id).execute()
        Member.update(end_date=date(2020, 1, 1)).where(Member.membership == ended).execute()
        self.assert_counts(stale=5)
        self.assertEqual(Membership.get_by_id(stale.id).billing_email, "ny@example.invalid")
        self.assertFalse(Membership.select().where(Membership.billing_name.is_null(False)).exists())
        self.assertEqual(MatrikelAudit.select().count(), 0)

    def test_swapped_id_or_edited_exported_values_are_skipped(self):
        first, second = [self.membership(notes=NOTE) for _ in range(2)]
        self.export()
        self.review(
            {"beslut": "godkänn", "membership_id": second.id},
            {"beslut": "ändra", "exporterat_billing_city": "Nyby", "proposed_billing_city": "Nyby"},
        )
        self.assert_counts(stale=2)
        self.assertIsNone(Membership.get_by_id(first.id).billing_city)
        self.assertIsNone(Membership.get_by_id(second.id).billing_city)
        self.assertEqual(MatrikelAudit.select().count(), 0)

    def test_approved_values_must_match_export_before_normalization(self):
        for _ in range(4):
            self.membership(notes=NOTE, billing_reference="=Prov")
        self.export()
        self.review(
            {"beslut": "godkänn", "proposed_billing_postal_code": "98765"},
            {"beslut": "godkänn", "proposed_billing_city": " Sagoby"},
            {"beslut": "godkänn", "proposed_billing_reference": "=Prov"},
            {"beslut": "ändra", **{f"proposed_{key}": "" for key in BILLING}},
        )
        self.assert_counts(unapproved=3, unchanged=1)
        self.assertEqual(MatrikelAudit.select().count(), 0)

    def test_bad_values_count_as_invalid_and_do_not_block_a_valid_row(self):
        for _ in range(3):
            self.membership(notes=NOTE)
        self.export()
        self.review(
            {"beslut": "ändra", "proposed_billing_email": "hemligt"},
            {"beslut": "ändra", "proposed_billing_postal_code": "12"},
            {"beslut": "godkänn"},
        )
        self.assert_counts(written=1, invalid=2)
        self.assertEqual(MatrikelAudit.select().count(), 1)

    def test_database_error_reports_only_committed_count_before_error(self):
        first, second = [self.membership(notes=NOTE) for _ in range(2)]
        self.export()
        self.review({"beslut": "godkänn"}, {"beslut": "godkänn"})

        def fail_second_audit(actor, action, membership, payload):
            if membership.id == second.id:
                raise DatabaseError("Privat detalj")
            return write_matrikel_audit(actor, action, membership, payload)

        with patch("cli.members.write_matrikel_audit", side_effect=fail_second_audit):
            result = self.apply()
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.output, "Skrivna: 1\nError: Databasfel vid hantering av fakturaförslag\n")
        self.assertEqual(Membership.get_by_id(first.id).billing_city, "Sagoby")
        self.assertIsNone(Membership.get_by_id(second.id).billing_city)
        self.assertEqual(MatrikelAudit.select().count(), 1)

    def test_unknown_last_decision_or_wrong_header_rejects_whole_file(self):
        for _ in range(2):
            self.membership(notes=NOTE)
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
        membership = self.membership(notes=NOTE)
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
