"""Workspace review and application through the CLI, with fictitious accounts and people."""

import csv
import stat
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from cli.members import members_cli
from click.testing import CliRunner
from flask.cli import ScriptInfo
from herdbook import APP
from peewee import DatabaseError
from utils.database import Herd, MailMessage, MatrikelAudit, Member, Membership, User
from utils.matrikel import ConfirmRequired, LinkError

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

    def user(self, verified=EMAIL, **fields):
        return User.create(
            uuid=uuid4(), email=fields.pop("email", "konto@example.invalid"), google_email=verified, **fields
        )

    def herd(self, ms, code="G901"):
        return Herd.create(genebank=self.genebanks[0], herd=code, membership=ms)

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

    def test_approve_verified_account_audit_and_replay(self):
        person = self.person()
        user = self.user(EMAIL.upper())
        (row,) = self.export()
        self.assertEqual((row["utfall"], row["skal"], row["konto_atgard"]), ("förslag", "namn lika", "koppla"))
        self.assertEqual(
            (row["ws_status"], row["ws_senast_inloggad"], row["ws_org_enhet"]), ("Suspended", "Never", "/Styrelse")
        )
        self.assertEqual((row["proposed_person_id"], row["konto_id"]), (str(person.id), str(user.id)))
        self.assertNotIn("Hemlig cell", self.path.read_text(encoding="utf-8-sig"))
        self.assertIn("hoppa över (beslut): 1", self.apply())
        self.assertIsNone(Member.get_by_id(person.id).workspace_email)
        self.assertIn("Skrivna: 1", self.apply({"beslut": "godkänn"}))
        person = Member.get_by_id(person.id)
        self.assertEqual((person.workspace_email, person.user_id), (EMAIL, user.id))
        update = MatrikelAudit.get(MatrikelAudit.action == "person_updated")
        self.assertEqual((update.actor_id, update.membership_id), (self.admin.id, person.membership_id))
        self.assertEqual(
            update.payload,
            {"person_id": person.id, "before": {"workspace_email": None}, "after": {"workspace_email": EMAIL}},
        )
        link = MatrikelAudit.get(MatrikelAudit.action == "person_user_linked")
        self.assertEqual(link.payload["source"], "cli")
        self.assertIn("underlaget har ändrats: 1", self.apply())
        self.assertEqual(MatrikelAudit.select().count(), 2)
        self.path = self.path.with_name("second.csv")
        self.assertEqual(self.export()[0]["utfall"], "redan klar")

    def test_approve_confirms_exact_reviewed_herds(self):
        person = self.person()
        user = self.user()
        herd = self.herd(person.membership)
        (row,) = self.export()
        self.assertEqual((row["besattningar"], row["exporterat_besattning_ids"]), (herd.herd, str(herd.id)))
        self.apply({"beslut": "godkänn"})
        self.assertEqual(Member.get_by_id(person.id).user_id, user.id)
        audit = MatrikelAudit.get(MatrikelAudit.action == "person_user_linked")
        self.assertEqual((audit.payload["source"], audit.payload["conveys_herd_ids"]), ("admin", [herd.id]))

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

    def test_duplicate_addresses_and_multiple_google_accounts_need_review(self):
        self.person()
        self.user()
        self.user(EMAIL.upper(), email="andra@example.invalid")
        rows = self.export(
            {},
            {"email": EMAIL.upper()},
            {"first": "Ingen", "email": "tom@gotlandskaninen.se"},
            {"first": "Ingen", "email": "tom@gotlandskaninen.se"},
        )
        self.assertTrue(all(row["utfall"] == "granska" for row in rows))
        self.assertIn("flera konton har Google-adressen", rows[0]["skal"])
        self.apply({"beslut": "ändra"}, {"beslut": "ändra"}, {}, {})
        self.assertEqual(MatrikelAudit.select().count(), 0)

    def test_account_linked_elsewhere_and_unverified_email(self):
        target = self.person()
        owner = self.person(902, "Annan", user=self.user())
        unverified = self.user(None, email="annan@gotlandskaninen.se")
        conflict, ignored = self.export({}, {"email": unverified.email, "first": "Obekant"})
        self.assertEqual(conflict["utfall"], "granska")
        self.assertIn(f"person {owner.id}", conflict["kandidater"])
        self.assertIn("kopplat till", conflict["skal"])
        self.assertEqual((ignored["utfall"], ignored["konto_id"]), ("ingen träff", ""))
        self.apply({"beslut": "ändra", "proposed_person_id": target.id, "proposed_member_number": 901}, {})
        self.assertIsNone(Member.get_by_id(target.id).workspace_email)

    def test_owner_only_can_add_family_without_email_mail_or_duplicate(self):
        main = self.person(first="Huvud")
        user = self.user()
        user.add_role("owner", self.herd(main.membership).id)
        (row,) = self.export()
        self.assertEqual(
            (row["utfall"], row["proposed_member_number"], row["proposed_person_id"]), ("granska", "901", "")
        )
        self.assertIn("kontot äger besättning G901 i medlemskap nr 901", row["skal"])
        self.apply({"beslut": "ändra", "proposed_person_id": "ny", "roll": "huvudmedlem"})
        family = Member.get(Member.workspace_email == EMAIL)
        self.assertEqual(
            (family.membership_id, family.role, family.first_name, family.last_name),
            (main.membership_id, "familjemedlem", "Sagofrö", "Exempelkvist"),
        )
        self.assertEqual((family.email, family.user_id), (None, user.id))
        self.assertEqual(MailMessage.select().count(), 0)
        self.apply()
        self.assertEqual(Member.select().where(Member.membership == main.membership).count(), 2)
        self.assertEqual(MatrikelAudit.select().count(), 3)

    def test_redirect_to_existing_person_with_and_without_herd_access(self):
        self.person()
        with_herd, without = self.person(902, "Första"), self.person(903, "Andra")
        self.herd(with_herd.membership, "G902")
        first, second = self.user(), self.user("andra@gotlandskaninen.se", email="andra@example.invalid")
        rows = self.export({}, {"email": second.google_email})
        self.assertEqual([row["utfall"] for row in rows], ["granska", "granska"])
        self.assertTrue(all("flera Workspace-rader" in row["skal"] for row in rows))
        output = self.apply(
            {"beslut": "ändra", "proposed_person_id": with_herd.id, "proposed_member_number": 902},
            {"beslut": "ändra", "proposed_person_id": without.id, "proposed_member_number": 903},
        )
        self.assertIn("konto ej kopplat: ger besättningar, koppla i matrikeln: 1", output)
        with_herd, without = (Member.get_by_id(p.id) for p in (with_herd, without))
        self.assertEqual((with_herd.workspace_email, with_herd.user_id), (first.google_email, None))
        self.assertEqual((without.workspace_email, without.user_id), (second.google_email, second.id))
        Herd.update(membership=None).where(Herd.membership == with_herd.membership).execute()
        self.assertIn("underlaget har ändrats: 2", self.apply())
        self.assertIsNone(Member.get_by_id(with_herd.id).user_id)

    def test_stale_person_email_collision_and_removed_herd_all_skip(self):
        ended, collision, lost_herd = self.person(), self.person(902, "Krock"), self.person(903, "Besättning")
        other = self.person(904, "Annan")
        self.user("flock@gotlandskaninen.se")
        herd = self.herd(lost_herd.membership, "G903")
        self.export(
            {},
            {"first": collision.first_name, "email": "krock@gotlandskaninen.se"},
            {"first": lost_herd.first_name, "email": "flock@gotlandskaninen.se"},
        )
        ended.end_date = date.today()
        ended.save()
        other.workspace_email = "KROCK@gotlandskaninen.se"
        other.save()
        herd.membership = None
        herd.save()
        self.assertIn("underlaget har ändrats: 3", self.apply(*[{"beslut": "godkänn"}] * 3))
        self.assertEqual(MatrikelAudit.select().count(), 0)

    def test_decision_does_not_authorize_changes_to_workspace_cells_or_export(self):
        self.person()
        self.export()
        self.assertIn(
            "ändrad rad utan beslutet ändra: 1", self.apply({"beslut": "godkänn", "proposed_member_number": 111})
        )
        for key in (
            "workspace_email",
            "ws_fornamn",
            "ws_status",
            "ws_org_enhet",
            "exporterat_person_id",
            "konto_atgard",
            "underlag",
        ):
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

    def test_missing_header_or_broken_csv_is_private_and_creates_no_file(self):
        for data, message in [
            ("Last Name,Privat rubrik\r\n", "first name"),
            ('first name,last name,email address\r\n"Hemlig cell', "kunde inte läsas"),
        ]:
            self.source.write_text(data, encoding="utf-8")
            result = self.run_cli(str(self.source), "--out", str(self.path))
            self.assertEqual(result.exit_code, 1)
            self.assertIn(message, result.output)
            self.assertNotIn("Privat rubrik", result.output)
            self.assertFalse(self.path.exists())

    def test_link_errors_roll_back_and_keep_diagnostics_private(self):
        person = self.person()
        self.user()
        self.export()
        for exc, outcome in (
            (ConfirmRequired([]), "underlaget har ändrats"),
            (LinkError("Nekad", "Hemlig cell"), "Nekad"),
        ):
            with patch("cli.members.link_member_user", side_effect=exc):
                self.assertIn(outcome + ": 1", self.apply({"beslut": "godkänn"}))
            self.assertIsNone(Member.get_by_id(person.id).workspace_email)
            self.assertEqual(MatrikelAudit.select().count(), 0)
        with patch("cli.members.write_matrikel_audit", side_effect=DatabaseError("Hemlig cell")):
            result = self.run_cli("--apply", str(self.path), "--actor-user-id", str(self.admin.id))
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Skrivna: 0", result.output)
        self.assertIsNone(Member.get_by_id(person.id).workspace_email)

    def test_only_matching_person_gets_ownership_signal_and_generic_local_does_not_match(self):
        main = self.person(first="Huvud", email="styrelsen@example.invalid")
        family = Member.create(
            membership=main.membership,
            first_name="Annan",
            last_name="Familj",
            role="familjemedlem",
            email="sagofro@example.invalid",
        )
        user = self.user()
        user.add_role("owner", self.herd(main.membership).id)
        extra = self.person(902, "Exakt", email="exakt@gotlandskaninen.se")
        owner, generic, exact = self.export(
            {"recovery": family.email},
            {"first": "Ingen", "email": "styrelsen@gotlandskaninen.se"},
            {"first": "Okänd", "email": extra.email},
        )
        self.assertEqual((owner["utfall"], owner["proposed_person_id"]), ("förslag", str(family.id)))
        for signal in ("lokaldel lika", "återställningsadressen är matrikelns e-post", "kontot äger besättning G901"):
            self.assertIn(signal, owner["skal"])
        self.assertNotIn(family.email, self.path.read_text(encoding="utf-8-sig"))
        self.assertEqual((generic["utfall"], exact["skal"]), ("ingen träff", "e-post lika"))
        # Reassigning the herd invalidates the ownership evidence, even if the access delta is still empty.
        Herd.update(membership=extra.membership).where(Herd.herd == "G901").execute()
        self.assertIn("underlaget har ändrats: 1", self.apply({"beslut": "godkänn"}, {}, {}))
        self.assertIsNone(Member.get_by_id(family.id).workspace_email)

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

    def test_new_person_requires_explicit_number_and_replays_without_a_google_user(self):
        main = self.person(first="Huvud")
        (row,) = self.export({"first": "=Sago"})
        self.assertEqual((row["utfall"], row["ws_fornamn"]), ("ingen träff", " =Sago"))
        self.apply({"beslut": "ändra", "proposed_person_id": "ny"})
        self.assertEqual(MatrikelAudit.select().count(), 0)
        self.apply({"beslut": "ändra", "proposed_member_number": 901, "proposed_person_id": "ny"})
        family = Member.get(Member.workspace_email == EMAIL)
        self.assertEqual((family.first_name, family.membership_id, family.user_id), ("=Sago", main.membership_id, None))
        self.assertIn("underlaget har ändrats: 1", self.apply())
        self.assertEqual(MatrikelAudit.select().count(), 2)

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
