"""Workspace review and application through the CLI, with fictitious accounts and people."""

import csv
import logging
import stat
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cli.members import members_cli
from click.testing import CliRunner
from flask.cli import ScriptInfo
from herdbook import APP
from peewee import DatabaseError
from utils.database import MatrikelAudit, Member, Membership
from utils.matrikel import ANONYMIZED_FIRST_NAME, ANONYMIZED_LAST_NAME

from tests.database_test import DatabaseTest

EMAIL = "sagofro@gotlandskaninen.se"
GOOGLE = [
    "Org Unit Path [Required]",
    "Last Name [Required]",
    "Password [Required]",
    " First NAME [Required] ",
    "Email Address [Required]",
    "Status [READ ONLY]",
    "Last Sign In [READ ONLY]",
    "Recovery Email",
]


class TestMembersWorkspaceProposals(DatabaseTest):
    def setUp(self):
        super().setUp()
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.source = Path(tmp.name) / "google.csv"
        self.path = Path(tmp.name) / "review.csv"

    def person(self, nr=901, first="Sagofrö", status="active", **fields):
        ms = Membership.create(member_number=nr, membership_status=status)
        return Member.create(membership=ms, first_name=first, last_name="Exempelkvist", **fields)

    def run_cli(self, *args):
        with self.assertNoLogs("peewee", level="DEBUG"):
            result = CliRunner().invoke(
                members_cli, ["workspace-proposals", *args], obj=ScriptInfo(create_app=lambda: APP)
            )
        for private in ("Sagofrö", "Exempelkvist", "sagofro", "@", "Hemlig cell", "/Styrelse"):
            self.assertNotIn(private, result.output)
        return result

    def export(self, *accounts):
        with self.source.open("w", encoding="utf-8-sig", newline="") as dest:
            writer = csv.writer(dest, lineterminator="\r\n")
            writer.writerow(GOOGLE)
            for account in accounts or ({},):
                writer.writerow(
                    [
                        "/Styrelse",
                        "Exempelkvist",
                        "Hemlig cell",
                        account.get("first", "Sagofrö"),
                        account.get("email", EMAIL),
                        "Suspended",
                        "Never",
                        account.get("recovery", ""),
                    ]
                )
        result = self.run_cli(str(self.source), "--out", str(self.path))
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        with self.path.open(encoding="utf-8-sig", newline="") as source:
            self.rows = list(csv.DictReader(source))
        return self.rows

    def review(self, *edits):
        with self.path.open("w", encoding="utf-8", newline="") as dest:
            writer = csv.DictWriter(dest, fieldnames=list(self.rows[0]))
            writer.writeheader()
            for row, edit in zip(self.rows, edits, strict=True):
                writer.writerow({**row, **edit})

    def apply(self, *edits):
        if edits:
            self.review(*edits)
        result = self.run_cli("--apply", str(self.path), "--actor-user-id", str(self.admin.id))
        self.assertEqual(result.exit_code, 0, result.output)
        return result.output

    def test_approve_audit_and_replay(self):
        person = self.person()
        (row,) = self.export()
        self.assertEqual((row["utfall"], row["skal"]), ("förslag", "namn lika"))
        self.assertEqual(
            (row["ws_status"], row["ws_senast_inloggad"], row["ws_org_enhet"]), ("Suspended", "Never", "/Styrelse")
        )
        self.assertEqual(row["proposed_person_id"], str(person.id))
        for gone in ("konto_id", "konto_atgard", "besattningar", "roll"):
            self.assertNotIn(gone, row)
        self.assertNotIn("Hemlig cell", self.path.read_text(encoding="utf-8-sig"))
        self.assertIn("hoppa över (beslut): 1", self.apply())
        self.assertIsNone(Member.get_by_id(person.id).workspace_email)
        self.assertIn("Skrivna: 1", self.apply({"beslut": "godkänn"}))
        person = Member.get_by_id(person.id)
        self.assertEqual((person.workspace_email, person.user_id), (EMAIL, None))
        update = MatrikelAudit.get(MatrikelAudit.action == "person_updated")
        self.assertEqual((update.actor_id, update.membership_id), (self.admin.id, person.membership_id))
        self.assertEqual(
            update.payload,
            {"person_id": person.id, "before": {"workspace_email": None}, "after": {"workspace_email": EMAIL}},
        )
        self.assertEqual(MatrikelAudit.select().count(), 1)
        self.assertIn("underlaget har ändrats: 1", self.apply())
        self.assertEqual(MatrikelAudit.select().count(), 1)
        self.path = self.path.with_name("second.csv")
        self.assertEqual(self.export()[0]["utfall"], "redan klar")

    def test_namesakes_and_overlapping_candidates_all_need_review(self):
        one, two = self.person(), self.person(902, email="privat@example.invalid")
        ambiguous, single = self.export(
            {}, {"first": "Annan", "email": "annan@gotlandskaninen.se", "recovery": two.email}
        )
        self.assertEqual([ambiguous["utfall"], single["utfall"]], ["granska", "granska"])
        for person in (one, two):
            self.assertIn(f"person {person.id} i nr {person.membership.member_number}", ambiguous["kandidater"])
        self.assertIn("återställningsadressen är matrikelns e-post", single["skal"])
        self.apply({"beslut": "godkänn"}, {"beslut": "godkänn"})
        self.assertEqual(MatrikelAudit.select().count(), 0)

    def test_new_namesake_after_the_export_skips_an_approved_row(self):
        person = self.person()
        self.export()
        self.person(902)  # same name, added after the export
        self.assertIn("underlaget har ändrats: 1", self.apply({"beslut": "godkänn"}))
        self.assertIsNone(Member.get_by_id(person.id).workspace_email)
        self.assertEqual(MatrikelAudit.select().count(), 0)

    def test_duplicate_addresses_need_review_and_are_named_at_apply(self):
        self.person()
        rows = self.export({}, {"email": EMAIL.upper()})
        self.assertTrue(all(row["utfall"] == "granska" for row in rows))
        self.assertIn("adressen förekommer flera gånger", rows[0]["skal"])
        self.assertIn(
            "adressen förekommer flera gånger i filen: 2", self.apply({"beslut": "ändra"}, {"beslut": "ändra"})
        )
        self.assertEqual(MatrikelAudit.select().count(), 0)

    def test_redirect_to_existing_person_and_invalid_targets(self):
        self.person()
        target, ended, anonymous = self.person(902, "Första"), self.person(903, "Avslutad"), self.person(904, "Tredje")
        ended.end_date = date.today()
        ended.save()
        Member.update(first_name=ANONYMIZED_FIRST_NAME, last_name=ANONYMIZED_LAST_NAME).where(
            Member.id == anonymous.id
        ).execute()
        (row,) = self.export({"first": "Okänd"})
        self.assertEqual(row["utfall"], "ingen träff")
        output = self.apply({"beslut": "ändra", "proposed_person_id": "ny", "proposed_member_number": 901})
        self.assertIn("ogiltigt mål: 1", output)
        for person in (ended, anonymous):
            self.assertIn(
                "ogiltigt mål: 1",
                self.apply(
                    {
                        "beslut": "ändra",
                        "proposed_person_id": person.id,
                        "proposed_member_number": person.membership.member_number,
                    }
                ),
            )
        self.assertEqual(MatrikelAudit.select().count(), 0)
        self.assertIn(
            "Skrivna: 1",
            self.apply({"beslut": "ändra", "proposed_person_id": target.id, "proposed_member_number": 902}),
        )
        self.assertEqual(Member.get_by_id(target.id).workspace_email, EMAIL)

    def test_stale_person_and_email_collision_skip(self):
        ended, collision = self.person(), self.person(902, "Krock")
        other = self.person(903, "Annan")
        self.export({}, {"first": collision.first_name, "email": "krock@gotlandskaninen.se"})
        ended.end_date = date.today()
        ended.save()
        other.workspace_email = "KROCK@gotlandskaninen.se"
        other.save()
        self.assertIn("underlaget har ändrats: 2", self.apply(*[{"beslut": "godkänn"}] * 2))
        self.assertEqual(MatrikelAudit.select().count(), 0)

    def test_decision_does_not_authorize_changes_to_workspace_cells_or_export(self):
        self.person()
        self.export()
        self.assertIn(
            "ändrad rad utan beslutet ändra: 1", self.apply({"beslut": "godkänn", "proposed_member_number": 111})
        )
        for key in ("workspace_email", "ws_fornamn", "ws_status", "ws_org_enhet", "exporterat_person_id", "underlag"):
            with self.subTest(key=key):
                self.assertIn("underlaget har ändrats: 1", self.apply({"beslut": "ändra", key: "123"}))
        self.assertEqual(MatrikelAudit.select().count(), 0)

    def test_domain_status_and_historical_matches(self):
        self.person()
        for nr, status in enumerate(("friexemplar", "pending", "inactive"), 902):
            self.person(nr, status, status=status)
        ended = self.person(905, "Avslutad", end_date=date.today())
        Member.create(membership=ended.membership, first_name="Kvar", last_name="Exempelkvist", role="familjemedlem")
        names = ["friexemplar", "pending", "inactive", "Avslutad", "Kvar"]
        outside, *rows = self.export(
            {"email": "privat@example.invalid"},
            *[{"first": name, "email": f"prov{i}@gotlandskaninen.se"} for i, name in enumerate(names)],
        )
        self.assertEqual(outside["utfall"], "granska")
        self.assertIn("inte föreningens domän", outside["skal"])
        self.assertEqual([row["utfall"] for row in rows], ["granska"] * 3 + ["ingen träff"] * 2)
        for row in rows[-2:]:
            self.assertIn("bara i avslutat medlemskap nr 905", row["skal"])
        self.apply(*[{"beslut": "ändra"}] * 6)
        self.assertEqual(MatrikelAudit.select().count(), 0)

    def test_broken_csv_is_private_names_the_column_and_skips_blank_lines(self):
        for data, message in [
            ("Last Name,Privat rubrik\r\n", "saknar kolumnen first name"),
            ('first name,last name,email address\r\n"Hemlig cell', "kunde inte läsas"),
        ]:
            self.source.write_text(data, encoding="utf-8")
            result = self.run_cli(str(self.source), "--out", str(self.path))
            self.assertEqual(result.exit_code, 1)
            self.assertIn(message, result.output)
            self.assertNotIn("Privat rubrik", result.output)
            self.assertFalse(self.path.exists())
        self.person()
        self.source.write_text(
            f"first name,last name,email address\r\nSagofrö,Exempelkvist,{EMAIL}\r\n\r\n,,\r\n", encoding="utf-8"
        )
        result = self.run_cli(str(self.source), "--out", str(self.path))
        self.assertEqual(
            (result.exit_code, result.output), (0, "förslag: 1, redan klar: 0, granska: 0, ingen träff: 0\n")
        )

    def test_database_errors_roll_back_and_keep_diagnostics_private(self):
        person = self.person()
        self.export()
        self.review({"beslut": "godkänn"})
        with patch("cli.members.write_matrikel_audit", side_effect=DatabaseError("Hemlig cell")):
            result = self.run_cli("--apply", str(self.path), "--actor-user-id", str(self.admin.id))
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Skrivna: 0", result.output)
        self.assertIsNone(Member.get_by_id(person.id).workspace_email)

    def test_only_peewee_logging_is_silenced_during_a_run(self):
        self.person()
        self.export()
        self.assertFalse(logging.getLogger("peewee").disabled)
        self.assertFalse(logging.getLogger("cli.members").disabled)
        self.assertEqual(logging.root.manager.disable, 0)

    def test_generic_local_part_does_not_match_and_local_part_does(self):
        main = self.person(first="Huvud", email="styrelsen@example.invalid")
        family = Member.create(
            membership=main.membership,
            first_name="Annan",
            last_name="Familj",
            role="familjemedlem",
            email="sagofro@example.invalid",
        )
        extra = self.person(902, "Exakt", email="exakt@gotlandskaninen.se")
        local, generic, exact = self.export(
            {"first": "Ingen"},
            {"first": "Ingen", "email": "styrelsen@gotlandskaninen.se"},
            {"first": "Okänd", "email": extra.email},
        )
        self.assertEqual((local["utfall"], local["proposed_person_id"]), ("förslag", str(family.id)))
        self.assertEqual(local["skal"], "lokaldel lika")
        self.assertNotIn(family.email, self.path.read_text(encoding="utf-8-sig"))
        self.assertEqual((generic["utfall"], exact["skal"]), ("ingen träff", "e-post lika"))

    def test_unique_index_conflict_rolls_back_one_row_and_continues(self):
        first, other, last = self.person(), self.person(902, "Annan"), self.person(903, "Sista")
        self.export({}, {"first": last.first_name, "email": "sista@gotlandskaninen.se"})
        save = Member.save

        def collision_before_save(person, *args, **kwargs):
            if person.id == first.id:
                Member.update(workspace_email=EMAIL.upper()).where(Member.id == other.id).execute()
            return save(person, *args, **kwargs)

        with patch.object(Member, "save", collision_before_save):
            output = self.apply({"beslut": "godkänn"}, {"beslut": "godkänn"})
        self.assertIn("adressen är satt på en annan person: 1", output)
        self.assertEqual(Member.get_by_id(last.id).workspace_email, "sista@gotlandskaninen.se")
        self.assertIsNone(Member.get_by_id(first.id).workspace_email)
        self.assertEqual(MatrikelAudit.select().count(), 1)

    def test_apply_requires_actor_and_cannot_take_a_second_input(self):
        self.person()
        self.export()
        self.review({"beslut": "godkänn"})
        for args in (
            (),
            (str(self.source),),
            ("--apply", str(self.path)),
            ("--apply", str(self.path), "--actor-user-id", str(self.manager.id)),
            (str(self.source), "--apply", str(self.path), "--actor-user-id", str(self.admin.id)),
            (str(self.source), "--apply", str(self.path), "--out", str(self.path)),
        ):
            self.assertEqual(self.run_cli(*args).exit_code, 2)
        self.assertEqual(MatrikelAudit.select().count(), 0)
