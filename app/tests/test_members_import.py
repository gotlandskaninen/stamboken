"""Tests for flask members import CLI (MATR2026 matrikel layout)."""

from datetime import date
from unittest.mock import patch

import cli.members as members_cli_module  # noqa: E402
import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.matrikel as matrikel  # noqa: E402
from cli.members import members_cli  # noqa: E402
from click.testing import CliRunner
from flask.cli import ScriptInfo
from herdbook import APP  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402

HEADER = "G,M,Nr,Namn Efternamn,Adress,Postadress,Telefonnr,e-postadress,Bet senast,Noteringar\n"
HEADER_SPLIT = "G,M,Nr,Namn Efternamn,Adress,Postnummer,Postort,Telefonnr,e-postadress,Bet senast,Noteringar\n"


def _row(g="", m="", nr="", name="", adress="", postadress="", telefon="", epost="", bet="", noteringar=""):
    """One legacy-layout line. Values must not contain commas."""
    return f"{g},{m},{nr},{name},{adress},{postadress},{telefon},{epost},{bet},{noteringar}\n"


def _row_split(
    g="", m="", nr="", name="", adress="", postnummer="", postort="", telefon="", epost="", bet="", noteringar=""
):
    """One split-layout line (Postnummer + Postort)."""
    return f"{g},{m},{nr},{name},{adress},{postnummer},{postort},{telefon},{epost},{bet},{noteringar}\n"


class TestMembersImport(DatabaseTest):
    def setUp(self):
        super().setUp()
        self.runner = CliRunner()

    def _run_import(self, csv_content: str, extra_args: list[str] | None = None):
        with self.runner.isolated_filesystem():
            with open("matrikel.csv", "w", encoding="utf-8") as f:
                f.write(csv_content)
            return self.runner.invoke(
                members_cli,
                ["import", "matrikel.csv", *(extra_args or [])],
                # AppGroup commands run with_appcontext — CliRunner has no
                # Flask app discovery, so hand it ours explicitly.
                obj=ScriptInfo(create_app=lambda: APP),
            )

    def test_genebank_flag_removed(self):
        """v2 drops all genebank scoping — the old --genebank flag must be gone."""
        csv = HEADER + _row(nr="6", name="Anna Svensson")
        result = self._run_import(csv, ["--genebank", "Gotlandskaninen"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("no such option", result.output.lower())

    def test_creates_membership_with_main_person(self):
        csv = HEADER + _row(
            nr="6",
            name="Anna Svensson",
            adress="Storgatan 1",
            postadress="12345 Visby",
            telefon="070-1234567",
            epost="Anna@Example.com",
            bet="2026",
            noteringar="Betald via swish",
        )
        result = self._run_import(csv)
        self.assertEqual(result.exit_code, 0, result.output)
        membership = db.Membership.get(db.Membership.member_number == 6)
        self.assertEqual(membership.membership_status, "active")
        self.assertEqual(membership.address, "Storgatan 1")
        self.assertEqual((membership.postal_code, membership.city), ("123 45", "Visby"))
        self.assertEqual(membership.payment_note, "2026")
        self.assertEqual(membership.notes, "Betald via swish")
        person = db.Member.get(db.Member.membership == membership)
        self.assertEqual(person.role, "huvudmedlem")
        self.assertEqual(person.first_name, "Anna")
        self.assertEqual(person.last_name, "Svensson")
        self.assertEqual(person.email, "anna@example.com")
        self.assertEqual(person.phone, "070-1234567")

    def test_rows_sharing_nr_group_into_one_membership(self):
        rows = [
            _row(nr="6", name="Anna Svensson", epost="anna@example.com"),
            _row(nr="6", name="Bo Svensson"),
        ]
        csv = HEADER + "".join(rows)
        result = self._run_import(csv)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(db.Membership.select().count(), 1)
        membership = db.Membership.get(db.Membership.member_number == 6)
        persons = list(db.Member.select().where(db.Member.membership == membership).order_by(db.Member.id))
        self.assertEqual(len(persons), 2)
        self.assertEqual(persons[0].role, "huvudmedlem")
        self.assertEqual(persons[0].first_name, "Anna")
        self.assertEqual(persons[1].role, "familjemedlem")
        self.assertEqual(persons[1].first_name, "Bo")

    def test_nr_zero_creates_friexemplar(self):
        csv = HEADER + _row(nr="0", name="Kaninklubben Väst", adress="Boxgatan 2")
        result = self._run_import(csv)
        self.assertEqual(result.exit_code, 0, result.output)
        membership = db.Membership.select().first()
        self.assertIsNotNone(membership)
        self.assertEqual(membership.membership_status, "friexemplar")
        self.assertIsNone(membership.member_number)
        self.assertEqual(membership.address, "Boxgatan 2")
        person = db.Member.get(db.Member.membership == membership)
        # Org heuristic: Nr=0 names go whole into last_name.
        self.assertEqual(person.first_name, "")
        self.assertEqual(person.last_name, "Kaninklubben Väst")

    def test_nr_zero_identical_duplicates_collapse_with_note(self):
        row = _row(nr="0", name="Tidskriftsbyte Nord")
        csv = HEADER + row + row
        result = self._run_import(csv)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(db.Membership.select().count(), 1)
        membership = db.Membership.select().first()
        self.assertIn("2 identiska rader", membership.notes)

    def test_nr_zero_conflicting_rows_import_first_and_report(self):
        """Same Nr=0 name but DIFFERENT fields (a common paper-matrikel case:
        one recipient, several distinct contact persons) must not synthesize
        a combined row — import the first verbatim, report the rest."""
        rows = [
            _row(nr="0", name="Jordbruksverket", adress="Vallgatan 8", epost="a@sjv.se"),
            _row(nr="0", name="Jordbruksverket", adress="Kungsgatan 1", epost="b@sjv.se"),
        ]
        csv = HEADER + "".join(rows)
        result = self._run_import(csv)
        self.assertEqual(result.exit_code, 0, result.output)
        # One membership, from the FIRST row verbatim (no field mixing).
        self.assertEqual(db.Membership.select().count(), 1)
        membership = db.Membership.select().first()
        self.assertEqual(membership.address, "Vallgatan 8")
        person = db.Member.get(db.Member.membership == membership)
        self.assertEqual(person.email, "a@sjv.se")
        self.assertNotIn("identiska rader", membership.notes or "")
        self.assertIn("olika uppgifter", membership.notes)
        self.assertIn("need review", result.output)

    def test_gm_flags_link_herd_membership(self):
        # insert_default() seeds herds G1 (Gotland) and M3 (Mellerud).
        rows = [
            _row(g="x", nr="1", name="Anna Svensson"),
            _row(m="x", nr="3", name="Cesar Ek"),
        ]
        csv = HEADER + "".join(rows)
        result = self._run_import(csv)
        self.assertEqual(result.exit_code, 0, result.output)
        herd_g1 = db.Herd.get(db.Herd.herd == "G1")
        herd_m3 = db.Herd.get(db.Herd.herd == "M3")
        m1 = db.Membership.get(db.Membership.member_number == 1)
        m3 = db.Membership.get(db.Membership.member_number == 3)
        self.assertEqual(herd_g1.membership_id, m1.id)
        self.assertEqual(herd_m3.membership_id, m3.id)

    def test_missing_flag_herd_warns_but_creates_membership(self):
        csv = HEADER + _row(g="x", nr="7", name="Doris Al")
        result = self._run_import(csv)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("herd G7 not found", result.output)
        self.assertTrue(db.Membership.select().where(db.Membership.member_number == 7).exists())

    def test_name_split_heuristics(self):
        rows = [
            _row(nr="8", name="Anna Maria Svensson"),
            _row(nr="9", name="Madonna"),
            _row(nr="0", name="Studieförbundet Vuxenskolan"),
        ]
        csv = HEADER + "".join(rows)
        result = self._run_import(csv)
        self.assertEqual(result.exit_code, 0, result.output)
        p8 = db.Member.get(db.Member.last_name == "Svensson")
        self.assertEqual(p8.first_name, "Anna Maria")
        p9 = db.Member.get(db.Member.last_name == "Madonna")
        self.assertEqual(p9.first_name, "")
        org = db.Member.get(db.Member.last_name == "Studieförbundet Vuxenskolan")
        self.assertEqual(org.first_name, "")

    def test_merge_adopts_numberless_membership_and_sets_number(self):
        existing = db.Membership.create(membership_status="active")
        db.Member.create(
            membership=existing,
            role="huvudmedlem",
            first_name="Eva",
            last_name="Lund",
            email="eva@example.com",
        )
        csv = HEADER + _row(nr="12", name="Eva Lund", epost="EVA@example.com", bet="2026")
        result = self._run_import(csv)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(db.Membership.select().count(), 1)
        adopted = db.Membership.get_by_id(existing.id)
        self.assertEqual(adopted.member_number, 12)
        self.assertEqual(adopted.payment_note, "2026")
        self.assertEqual(db.Member.select().count(), 1)
        self.assertIn("Merges", result.output)

    def test_leftover_numberless_memberships_reported(self):
        leftover = db.Membership.create(membership_status="active")
        db.Member.create(
            membership=leftover,
            role="huvudmedlem",
            first_name="Ulla",
            last_name="Berg",
        )
        csv = HEADER + _row(nr="5", name="Nils Nord")
        result = self._run_import(csv)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("manual reconciliation", result.output)
        self.assertIn("Ulla Berg", result.output)

    def test_reimport_is_idempotent(self):
        rows = [
            _row(g="x", nr="1", name="Anna Svensson", epost="anna@example.com"),
            _row(nr="1", name="Bo Svensson"),
            _row(nr="0", name="Föreningen X"),
        ]
        csv = HEADER + "".join(rows)
        first = self._run_import(csv)
        self.assertEqual(first.exit_code, 0, first.output)
        second = self._run_import(csv)
        self.assertEqual(second.exit_code, 0, second.output)
        self.assertEqual(db.Membership.select().count(), 2)
        self.assertEqual(db.Member.select().count(), 3)
        self.assertIn("Matched existing (skipped): 2", second.output)
        herd = db.Herd.get(db.Herd.herd == "G1")
        m1 = db.Membership.get(db.Membership.member_number == 1)
        self.assertEqual(herd.membership_id, m1.id)

    def test_reimport_adds_missing_family_row(self):
        """Re-import is reconciliation, not a skip: a family row absent from
        an earlier (interrupted) run is created on the second run."""
        csv1 = HEADER + _row(nr="20", name="Karin Ek", epost="karin@example.com")
        first = self._run_import(csv1)
        self.assertEqual(first.exit_code, 0, first.output)
        self.assertEqual(db.Member.select().count(), 1)

        csv2 = HEADER + _row(nr="20", name="Karin Ek", epost="karin@example.com") + _row(nr="20", name="Lars Ek")
        second = self._run_import(csv2)
        self.assertEqual(second.exit_code, 0, second.output)
        m20 = db.Membership.get(db.Membership.member_number == 20)
        persons = list(db.Member.select().where(db.Member.membership == m20))
        self.assertEqual(len(persons), 2)
        self.assertTrue(any(p.first_name == "Lars" and p.last_name == "Ek" for p in persons))

    def _persons(self, nr):
        """(first, last, role, ended) of every person on membership `nr`, oldest first."""
        ms = db.Membership.get(db.Membership.member_number == nr)
        rows = db.Member.select().where(db.Member.membership == ms).order_by(db.Member.id)
        return [(p.first_name, p.last_name, p.role, p.end_date is not None) for p in rows]

    def test_reimport_does_not_resurrect_erased_or_removed_persons(self):
        """Anonymize and soft-delete work by setting end_date, so a re-import of
        the same spreadsheet used to bring both people back with their original PII."""
        csv = (
            HEADER
            + _row(nr="20", name="Karin Ek", epost="karin@example.se", telefon="070111")
            + _row(nr="20", name="Lars Ek")
        )
        first = self._run_import(csv)
        self.assertEqual(first.exit_code, 0, first.output)
        karin = db.Member.get(db.Member.first_name == "Karin")
        lars = db.Member.get(db.Member.first_name == "Lars")

        matrikel.soft_delete_person(lars, self.admin)
        matrikel.anonymize_person(karin, self.admin)

        second = self._run_import(csv)
        self.assertEqual(second.exit_code, 0, second.output)

        restored = [
            (p.id, p.first_name, p.email, p.role, p.end_date)
            for p in db.Member.select().where(db.Member.email == "karin@example.se")
        ]
        self.assertEqual(restored, [], f"erased huvudmedlem re-created by re-import: {restored}")
        lars_active = [
            (p.id, p.first_name, p.role)
            for p in db.Member.select().where(db.Member.first_name == "Lars", db.Member.end_date.is_null(True))
        ]
        self.assertEqual(lars_active, [], f"soft-deleted familjemedlem re-added by re-import: {lars_active}")
        self.assertEqual(db.Member.select().count(), 2)
        self.assertIn("Nr 20 -> membership", second.output)  # reported for manual review, not an error

    def test_reimport_does_not_recreate_an_anonymized_familjemedlem(self):
        """The placeholder name defeats any name-based dedupe, so the group
        is parked on the ended person instead."""
        csv = (
            HEADER
            + _row(nr="21", name="Maj Ek", epost="maj@example.se")
            + _row(nr="21", name="Nils Ek", epost="nils@example.se", telefon="070222")
        )
        self.assertEqual(self._run_import(csv).exit_code, 0)
        matrikel.anonymize_person(db.Member.get(db.Member.first_name == "Nils"), self.admin)

        second = self._run_import(csv)

        self.assertEqual(second.exit_code, 0, second.output)
        self.assertEqual(
            self._persons(21), [("Maj", "Ek", "huvudmedlem", False), ("Borttagen", "person", "familjemedlem", True)]
        )
        self.assertFalse(db.Member.select().where(db.Member.email == "nils@example.se").exists())
        self.assertIn("Nr 21 -> membership", second.output)

    def test_reimport_does_not_touch_a_retired_membership(self):
        """A retired membership (inactive, every person ended) takes neither
        the old main member nor a new family row from the CSV; dry-run says so too."""
        csv = HEADER + _row(nr="22", name="Olof Ek", epost="olof@example.se")
        self.assertEqual(self._run_import(csv).exit_code, 0)
        matrikel.retire_membership(db.Membership.get(db.Membership.member_number == 22), self.admin)
        csv = csv + _row(nr="22", name="Pia Ek", adress="Storgatan 1")

        dry = self._run_import(csv, ["--dry-run"])
        self.assertEqual(dry.exit_code, 0, dry.output)
        self.assertIn("Nr 22 -> membership", dry.output)

        second = self._run_import(csv)

        self.assertEqual(second.exit_code, 0, second.output)
        ms = db.Membership.get(db.Membership.member_number == 22)
        self.assertEqual((ms.membership_status, ms.address), ("inactive", None))
        self.assertEqual(self._persons(22), [("Olof", "Ek", "huvudmedlem", True)])
        self.assertIn("Nr 22 -> membership", second.output)

    def test_reimport_does_not_refill_an_erased_household_address(self):
        """Erasing the only person clears the household address; the
        old spreadsheet must not put it (or the person) back."""
        csv = HEADER + _row(
            nr="23", name="Anna Lind", adress="Storgatan 1", postadress="623 55 Visby", epost="anna@example.se"
        )
        self.assertEqual(self._run_import(csv).exit_code, 0)
        matrikel.anonymize_person(db.Member.get(db.Member.first_name == "Anna"), self.admin)
        ms = db.Membership.get(db.Membership.member_number == 23)
        self.assertEqual((ms.address, ms.postal_code, ms.city), (None, None, None), "precondition (R085)")

        second = self._run_import(csv)

        self.assertEqual(second.exit_code, 0, second.output)
        ms = db.Membership.get(db.Membership.member_number == 23)
        self.assertEqual((ms.address, ms.postal_code, ms.city), (None, None, None))
        self.assertEqual(self._persons(23), [("Borttagen", "person", "huvudmedlem", True)])
        self.assertFalse(db.Member.select().where(db.Member.email == "anna@example.se").exists())

    def test_reimport_leaves_an_inactive_membership_alone(self):
        """add_person refuses an inactive membership, so the importer may not add people
        or fill fields there either."""
        ms = db.Membership.create(member_number=6, membership_status="inactive", publication_consent={"email": False})
        db.Member.create(
            membership=ms, role="huvudmedlem", first_name="Anna", last_name="Svensson", email="anna@example.se"
        )
        csv = (
            HEADER
            + _row(nr="6", name="Anna Svensson", adress="Storgatan 1", epost="anna@example.se")
            + _row(nr="6", name="Bo Svensson")
        )

        written, spy = self._membership_saves()
        with spy:
            result = self._run_import(csv)

        self.assertEqual(result.exit_code, 0, result.output)
        reloaded = db.Membership.get_by_id(ms.id)
        self.assertEqual((reloaded.address, reloaded.membership_status), (None, "inactive"))
        self.assertEqual(reloaded.publication_consent, {"email": False})
        self.assertEqual(written, [])
        self.assertEqual(self._persons(6), [("Anna", "Svensson", "huvudmedlem", False)])
        self.assertIn("inaktivt medlemskap", result.output)

    def test_adoption_is_parked_when_the_candidate_has_an_ended_person(self):
        """The adopting import would add the CSV's family row, bringing back a
        person who was removed from the numberless membership."""
        existing = db.Membership.create(membership_status="active")
        db.Member.create(
            membership=existing, role="huvudmedlem", first_name="Eva", last_name="Lund", email="eva@example.se"
        )
        db.Member.create(
            membership=existing,
            role="familjemedlem",
            first_name="Gustav",
            last_name="Lund",
            end_date=date(2025, 1, 1),
        )
        csv = HEADER + _row(nr="12", name="Eva Lund", epost="eva@example.se") + _row(nr="12", name="Gustav Lund")

        result = self._run_import(csv)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(db.Membership.get_by_id(existing.id).member_number)
        self.assertEqual(db.Membership.select().count(), 1)
        self.assertEqual(db.Member.select().where(db.Member.membership == existing).count(), 2)
        self.assertIn("Nr 12 -> membership", result.output)

    def test_adoption_candidate_erased_between_lookup_and_lock_is_parked(self):
        """The candidate's main person is erased after the lookup. Discarding the
        candidate would let the creation branch build a new household from the CSV."""
        existing = db.Membership.create(membership_status="active")
        main = db.Member.create(
            membership=existing, role="huvudmedlem", first_name="Eva", last_name="Lund", email="eva@example.se"
        )
        original_find = members_cli_module._find_adoptable_membership

        def erase_after_lookup(row):
            found = original_find(row)
            matrikel.anonymize_person(main, self.admin)
            return found

        csv = HEADER + _row(nr="12", name="Eva Lund", epost="eva@example.se", telefon="070444")
        with patch.object(members_cli_module, "_find_adoptable_membership", erase_after_lookup):
            result = self._run_import(csv)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(db.Membership.select().count(), 1)
        self.assertFalse(db.Member.select().where(db.Member.phone == "070444").exists())
        self.assertIn("Nr 12 -> membership", result.output)

    def test_reimport_does_not_recreate_an_anonymized_friexemplar(self):
        """An erased friexemplar contact has no number and no name left to find it
        by, so a Nr=0 row that matches nothing is parked rather than created."""
        csv = HEADER + _row(nr="0", name="Per Olsson", adress="Storgatan 4", telefon="070333")
        self.assertEqual(self._run_import(csv).exit_code, 0)
        matrikel.anonymize_person(db.Member.get(), self.admin)

        second = self._run_import(csv)

        self.assertEqual(second.exit_code, 0, second.output)
        self.assertEqual(db.Membership.select().count(), 1)
        self.assertFalse(db.Member.select().where(db.Member.phone == "070333").exists())
        self.assertIn("friexemplar Per Olsson -> membership -:", second.output)

    def _erased_friexemplar_then_reimport(self, **change):
        """Import one Nr=0 row, change its membership, erase its contact, import again."""
        csv = HEADER + _row(nr="0", name="Per Olsson", adress="Storgatan 4", telefon="070333")
        self.assertEqual(self._run_import(csv).exit_code, 0)
        db.Membership.update(**change).execute()
        matrikel.anonymize_person(db.Member.get(), self.admin)
        second = self._run_import(csv)
        self.assertEqual(second.exit_code, 0, second.output)
        self.assertEqual(db.Membership.select().count(), 1)
        self.assertFalse(db.Member.select().where(db.Member.phone == "070333").exists())
        self.assertIn("friexemplar Per Olsson -> membership -:", second.output)

    def test_reimport_does_not_recreate_a_friexemplar_activated_before_erasure(self):
        self._erased_friexemplar_then_reimport(membership_status="active")

    def test_reimport_does_not_recreate_a_friexemplar_numbered_before_erasure(self):
        self._erased_friexemplar_then_reimport(member_number=77)

    def test_reimport_does_not_recreate_a_retired_friexemplar(self):
        csv = HEADER + _row(nr="0", name="Föreningen X")
        self.assertEqual(self._run_import(csv).exit_code, 0)
        matrikel.retire_membership(db.Membership.get(), self.admin)

        second = self._run_import(csv)

        self.assertEqual(second.exit_code, 0, second.output)
        self.assertEqual(db.Membership.select().count(), 1)
        self.assertEqual(db.Member.select().count(), 1)
        self.assertIn("friexemplar Föreningen X -> membership", second.output)

    def test_reimport_links_herd_created_later(self):
        """A G/M flag whose herd did not exist at first import must link on
        re-import once the herd is created (the early return used to make the
        idempotent link logic unreachable)."""
        csv = HEADER + _row(g="x", nr="50", name="Sena Herden", epost="sena@example.com")
        first = self._run_import(csv)
        self.assertEqual(first.exit_code, 0, first.output)
        self.assertIn("herd G50 not found", first.output)

        # The herd is created afterwards (a manager approves the herd).
        gotland = db.Herd.get(db.Herd.herd == "G1").genebank
        db.Herd.create(herd="G50", genebank=gotland, herd_name="Sena")

        second = self._run_import(csv)
        self.assertEqual(second.exit_code, 0, second.output)
        herd = db.Herd.get(db.Herd.herd == "G50")
        m50 = db.Membership.get(db.Membership.member_number == 50)
        self.assertEqual(herd.membership_id, m50.id)

    def test_counter_raised_to_max_imported_number(self):
        csv = HEADER + _row(nr="6", name="Anna Svensson") + _row(nr="41", name="Nils Nord")
        result = self._run_import(csv)
        self.assertEqual(result.exit_code, 0, result.output)
        counter = db.MemberNumberCounter.select().first()
        self.assertIsNotNone(counter)
        self.assertGreaterEqual(counter.value, 41)

    def test_gdpr_consented_at_never_fabricated(self):
        """MATR2026 has no consent column — imported persons must have NULL."""
        csv = HEADER + _row(nr="6", name="Anna Svensson", epost="anna@example.com")
        result = self._run_import(csv)
        self.assertEqual(result.exit_code, 0, result.output)
        person = db.Member.get(db.Member.email == "anna@example.com")
        self.assertIsNone(person.gdpr_consented_at)

    def test_bom_and_header_case_insensitivity(self):
        # Explicit escape — a literal BOM character survives copy-paste badly.
        header = "\ufeffg,m,NR,NAMN EFTERNAMN,ADRESS,POSTADRESS,TELEFONNR,E-POSTADRESS,BET SENAST,NOTERINGAR\n"
        csv = header + _row(nr="6", name="Zeta Zorn", epost="z@z.example.com")
        result = self._run_import(csv)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(db.Membership.select().where(db.Membership.member_number == 6).exists())

    def test_raw_export_preamble_and_footer_rows(self):
        """The raw MATR2026 export surrounds the data with junk: title/legend/
        count rows before the header, year-statistics rows (only Nr filled)
        after — both must be skipped, not errored."""
        csv = (
            '"Föreningen Gotlandskaninen, medlemmar 2026, fr.o.m 1 april",,,,,,,,,,\n'
            '"G betyder genbank för gotlandskanin, M genbank för mellerudskanin",,,,,,,,,,\n'
            "207,56,,,,,,,,,\n"
            + HEADER
            + _row(nr="6", name="Anna Svensson", epost="anna@example.com")
            + _row(nr="0", name="Almedalsbiblioteket Gotlandica")
            + ",,2025,,,,,,,,\n"
            + ",,2026,,,,,,,,\n"
        )
        result = self._run_import(csv)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(db.Membership.select().where(db.Membership.member_number == 6).exists())
        # Footer year rows must not become errors or memberships.
        self.assertEqual(db.Membership.select().count(), 2)

    def test_row_with_data_but_no_name_still_errors(self):
        """Only filler rows are skipped — a row carrying real data without a
        name is corruption and must surface as an error."""
        csv = HEADER + _row(nr="8", adress="Storgatan 1", epost="x@y.example.com")
        result = self._run_import(csv)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Namn Efternamn", result.output)

    def test_missing_header_row_fails_clearly(self):
        csv = '"bara en rubrik",,,,,,,,,,\n' + _row(nr="6", name="Anna Svensson")
        result = self._run_import(csv)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("rubrikrad", result.output)

    def test_dry_run_writes_nothing_and_prints_full_report(self):
        leftover = db.Membership.create(membership_status="active")
        db.Member.create(
            membership=leftover,
            role="huvudmedlem",
            first_name="Ulla",
            last_name="Berg",
        )
        csv = HEADER + _row(g="x", nr="7", name="Anna Maria Svensson", epost="anna@example.com")
        result = self._run_import(csv, ["--dry-run"])
        self.assertEqual(result.exit_code, 0, result.output)
        # No writes: only the pre-existing membership/person remain.
        self.assertEqual(db.Membership.select().count(), 1)
        self.assertEqual(db.Member.select().count(), 1)
        self.assertEqual(db.Herd.select().where(db.Herd.membership.is_null(False)).count(), 0)
        # Full report: name splits, odd herd codes, leftovers, summary, dry-run marker.
        self.assertIn("Name splits", result.output)
        self.assertIn("Anna Maria Svensson", result.output)
        self.assertIn("herd G7 not found", result.output)
        self.assertIn("Ulla Berg", result.output)
        self.assertIn("Memberships created: 1", result.output)
        self.assertIn("(dry-run — no writes performed)", result.output)

    def test_import_never_auto_links_user(self):
        """Per design spec: import does not auto-link. OAuth login does."""
        # Real registration path — hand-rolled uuid strings are rejected by
        # the PostgreSQL uuid column (see Test Conventions).
        da.register_user("link@example.com", "pass", username="link")
        csv = HEADER + _row(nr="6", name="Link Me", epost="link@example.com")
        result = self._run_import(csv)
        self.assertEqual(result.exit_code, 0, result.output)
        person = db.Member.get(db.Member.email == "link@example.com")
        self.assertIsNone(person.user_id)

    def _counter(self):
        return db.MemberNumberCounter.select().first().value

    def test_legacy_layout_splits_postadress(self):
        result = self._run_import(HEADER + _row(nr="6", name="Anna Svensson", postadress="62355 Visby"))
        self.assertEqual(result.exit_code, 0, result.output)
        ms = db.Membership.get(db.Membership.member_number == 6)
        self.assertEqual((ms.postal_code, ms.city), ("623 55", "Visby"))

    def test_legacy_non_parsing_postadress_lands_in_city_and_report(self):
        result = self._run_import(HEADER + _row(nr="6", name="Anna Svensson", postadress="Box 12 Visby"))
        self.assertEqual(result.exit_code, 0, result.output)
        ms = db.Membership.get(db.Membership.member_number == 6)
        self.assertEqual((ms.postal_code, ms.city), (None, "Box 12 Visby"))
        self.assertIn("Postadress kräver granskning", result.output)
        self.assertIn("Nr 6", result.output)

    def test_split_layout_normalises_postnummer(self):
        result = self._run_import(
            HEADER_SPLIT + _row_split(nr="6", name="Anna Svensson", postnummer="62355", postort="Visby")
        )
        self.assertEqual(result.exit_code, 0, result.output)
        ms = db.Membership.get(db.Membership.member_number == 6)
        self.assertEqual((ms.postal_code, ms.city), ("623 55", "Visby"))

    def test_split_layout_invalid_postnummer_is_row_error(self):
        result = self._run_import(
            HEADER_SPLIT + _row_split(nr="6", name="Anna Svensson", postnummer="62-355", postort="Visby")
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("ogiltigt postnummer", result.output.lower())
        self.assertFalse(db.Membership.select().where(db.Membership.member_number == 6).exists())

    def test_split_layout_city_too_long_fails_without_moving_counter(self):
        before = self._counter()
        result = self._run_import(
            HEADER_SPLIT + _row_split(nr="6", name="Anna Svensson", postnummer="62355", postort="x" * 101)
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Postort får vara högst 100 tecken", result.output)
        self.assertEqual(self._counter(), before)
        self.assertEqual(db.Membership.select().count(), 0)

    def test_legacy_overlong_non_parsing_postadress_is_row_error(self):
        # Legacy layout: "Box xxxx…" does not match the regex, so the whole value would become city.
        before = self._counter()
        result = self._run_import(HEADER + _row(nr="6", name="Anna Svensson", postadress="Box " + "x" * 100))
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Postort får vara högst 100 tecken", result.output)
        self.assertEqual(self._counter(), before)
        self.assertEqual(db.Membership.select().count(), 0)

    def test_mixed_header_set_is_file_level_error(self):
        header = (
            "G,M,Nr,Namn Efternamn,Adress,Postadress,Postnummer,Postort,Telefonnr,e-postadress,Bet senast,Noteringar\n"
        )
        before = self._counter()
        result = self._run_import(header + "G,,6,Anna Svensson,Gata,62355 Visby,62355,Visby,,,,\n")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("postadress", result.output.lower())
        self.assertIn("postnummer", result.output.lower())
        self.assertEqual(db.Membership.select().count(), 0)
        self.assertEqual(db.Member.select().count(), 0)
        self.assertEqual(self._counter(), before)

    def test_lone_postnummer_column_is_file_level_error(self):
        header = "G,M,Nr,Namn Efternamn,Adress,Postnummer,Telefonnr,e-postadress,Bet senast,Noteringar\n"
        result = self._run_import(header + "G,,6,Anna Svensson,Gata,62355,,,,\n")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("postort", result.output.lower())
        self.assertEqual(db.Membership.select().count(), 0)

    def test_duplicate_headers_are_file_level_errors(self):
        before = self._counter()
        for header in (
            "G,M,Nr,Namn Efternamn,Adress,Postnummer,Postort,Postnummer,Telefonnr,e-postadress,Bet senast,Noteringar\n",
            "G,M,Nr,Namn Efternamn,Adress,Postnummer,Postort,Postort,Telefonnr,e-postadress,Bet senast,Noteringar\n",
            "G,M,Nr,Namn Efternamn,Adress,Postadress,Postadress,Telefonnr,e-postadress,Bet senast,Noteringar\n",
            "G,M,Nr,Namn Efternamn,Adress,Postnummer,Post-ort,Postort,Telefonnr,e-postadress,Bet senast,Noteringar\n",
        ):
            with self.subTest(header=header):
                result = self._run_import(header + "G,,6,Anna Svensson,Gata,x,y,z,,,,\n")
                self.assertNotEqual(result.exit_code, 0)
                self.assertIn("dubblettkolumn", result.output.lower())
                self.assertIn("kolumn", result.output.lower())
                self.assertEqual(db.Membership.select().count(), 0)
                self.assertEqual(db.Member.select().count(), 0)
                self.assertEqual(self._counter(), before)

    def test_nr_zero_rows_with_compact_and_spaced_postnummer_collapse(self):
        csv = (
            HEADER_SPLIT
            + _row_split(nr="0", name="Biblioteket", postnummer="62355", postort="Visby")
            + _row_split(nr="0", name="Biblioteket", postnummer="623 55", postort="Visby")
        )
        result = self._run_import(csv)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("2 rows -> 1 membership", result.output)
        self.assertEqual(db.Membership.select().where(db.Membership.membership_status == "friexemplar").count(), 1)

    def test_reimport_treats_compact_and_spaced_postnummer_as_equal(self):
        self._run_import(HEADER_SPLIT + _row_split(nr="6", name="Anna Svensson", postnummer="62355", postort="Visby"))
        result = self._run_import(
            HEADER_SPLIT + _row_split(nr="6", name="Anna Svensson", postnummer="623 55", postort="Visby")
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Matched existing (skipped): 1", result.output)
        self.assertEqual(db.Membership.select().count(), 1)

    def _membership_saves(self):
        """Record the `only=` field set of every Membership.save() during an import.

        None means a full-row save — the bug: the reconcile
        and the adoption path both wrote back every column of an instance read
        before the transaction, undoing a concurrent deactivation or consent
        withdrawal.
        """
        written = []
        original_save = db.Membership.save

        def spy_save(row, *args, **kwargs):
            only = kwargs.get("only")
            written.append(None if only is None else {field.name for field in only})
            return original_save(row, *args, **kwargs)

        return written, patch.object(db.Membership, "save", spy_save)

    def test_reimport_writes_only_the_fields_it_filled(self):
        """Re-import fills the still-empty address and touches nothing else:
        the status and a withdrawn consent stay as they were, because neither
        column is ever in the written set. (An inactive membership is not
        reconciled at all, see test_reimport_leaves_an_inactive_membership_alone.)"""
        ms = db.Membership.create(
            member_number=6,
            membership_status="active",
            publication_consent={"email": False},
        )
        db.Member.create(
            membership=ms,
            role="huvudmedlem",
            first_name="Anna",
            last_name="Svensson",
            email="anna@example.com",
        )
        csv = HEADER + _row(nr="6", name="Anna Svensson", adress="Storgatan 1", epost="anna@example.com")

        written, spy = self._membership_saves()
        with spy:
            result = self._run_import(csv)

        self.assertEqual(result.exit_code, 0, result.output)
        reloaded = db.Membership.get_by_id(ms.id)
        self.assertEqual(reloaded.address, "Storgatan 1")
        self.assertEqual(reloaded.membership_status, "active")
        self.assertEqual(reloaded.publication_consent, {"email": False})
        self.assertEqual(written, [{"address", "updated_at"}])

    def test_reimport_without_changes_writes_nothing(self):
        """Nothing left to fill → no UPDATE at all (an empty `only` set would
        still bump updated_at and take a write lock for no reason)."""
        csv = HEADER + _row(nr="6", name="Anna Svensson", adress="Storgatan 1", epost="anna@example.com")
        first = self._run_import(csv)
        self.assertEqual(first.exit_code, 0, first.output)

        written, spy = self._membership_saves()
        with spy:
            second = self._run_import(csv)

        self.assertEqual(second.exit_code, 0, second.output)
        self.assertEqual(written, [])

    def test_merge_adoption_writes_only_number_and_changed_fields(self):
        """The adoption path assigns the member number with the same rule —
        the number and the fields the CSV actually changes, never the status
        or the publication consent stored on the adopted membership."""
        existing = db.Membership.create(membership_status="active", publication_consent={"email": False})
        db.Member.create(
            membership=existing,
            role="huvudmedlem",
            first_name="Eva",
            last_name="Lund",
            email="eva@example.com",
        )
        csv = HEADER + _row(nr="12", name="Eva Lund", epost="EVA@example.com", bet="2026")

        written, spy = self._membership_saves()
        with spy:
            result = self._run_import(csv)

        self.assertEqual(result.exit_code, 0, result.output)
        adopted = db.Membership.get_by_id(existing.id)
        self.assertEqual(adopted.member_number, 12)
        self.assertEqual(adopted.payment_note, "2026")
        self.assertEqual(adopted.publication_consent, {"email": False})
        self.assertEqual(written, [{"member_number", "payment_note", "updated_at"}])


class TestMembersLinkUsers(DatabaseTest):
    """flask members link-users — manual follow-up to the import's NULL user."""

    def setUp(self):
        super().setUp()
        self.runner = CliRunner()

    def _run_link(self, extra_args: list[str] | None = None):
        return self.runner.invoke(
            members_cli,
            ["link-users", *(extra_args or [])],
            obj=ScriptInfo(create_app=lambda: APP),
        )

    def _person(self, email, first="Anna", last="Svensson", **kwargs):
        """One active huvudmedlem on its own membership (as import creates them)."""
        membership = db.Membership.create(membership_status="active")
        return db.Member.create(
            membership=membership,
            role="huvudmedlem",
            first_name=first,
            last_name=last,
            email=email,
            **kwargs,
        )

    def test_apply_links_user_to_member_on_contact_email(self):
        """Case-insensitive: import lowercases the CSV email, the account may not."""
        user = da.register_user("Anna@X.EXAMPLE.COM", "pass", username="anna")
        person = self._person("anna@x.example.com")

        result = self._run_link(["--apply", "--actor-user-id", str(self.admin.id)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(db.Member.get_by_id(person.id).user_id, user.id)
        self.assertIn(f"member {person.id}", result.output)
        self.assertIn("-> user anna", result.output)
        self.assertIn("Linked: 1", result.output)

    def test_dry_run_prints_plan_without_writing(self):
        da.register_user("anna@x.example.com", "pass", username="anna")
        person = self._person("anna@x.example.com")

        result = self._run_link()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(db.Member.get_by_id(person.id).user_id)
        self.assertIn("DRY-RUN", result.output)
        self.assertIn("Would link", result.output)
        self.assertIn(f"member {person.id}", result.output)
        self.assertIn("Linked: 1", result.output)
        self.assertIn("(dry-run — no writes performed; re-run with --apply)", result.output)

    def test_herd_owning_membership_needs_existing_owner_privilege(self):
        """The spreadsheet email is unverified — it must never convey herd
        access the account does not already have (link_access_delta). Once
        the account holds the legacy owner privilege the delta is empty and
        the same match links."""
        user = da.register_user("owner@x.example.com", "pass", username="ownerx")
        person = self._person("owner@x.example.com")
        herd = db.Herd.create(genebank=self.genebanks[0], herd="G901", membership=person.membership)

        result = self._run_link(["--apply", "--actor-user-id", str(self.admin.id)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(db.Member.get_by_id(person.id).user_id)
        self.assertIn("Needs review: 1", result.output)
        self.assertIn("G901", result.output)

        user.add_role("owner", herd.id)
        result = self._run_link(["--apply", "--actor-user-id", str(self.admin.id)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(db.Member.get_by_id(person.id).user_id, user.id)
        self.assertIn("Linked: 1", result.output)

    def test_ambiguous_email_links_nothing_and_reports_both_rows(self):
        da.register_user("anna@x.example.com", "pass", username="anna")
        first = self._person("anna@x.example.com", first="Anna", last="Svensson")
        second = self._person("anna@x.example.com", first="Anna", last="Berg")

        result = self._run_link(["--apply", "--actor-user-id", str(self.admin.id)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(db.Member.get_by_id(first.id).user_id)
        self.assertIsNone(db.Member.get_by_id(second.id).user_id)
        self.assertIn("Ambiguous", result.output)
        self.assertIn(f"member {first.id}", result.output)
        self.assertIn(f"member {second.id}", result.output)
        self.assertIn("Anna Berg", result.output)
        self.assertIn("Linked: 0", result.output)
        self.assertIn("Ambiguous: 1 (2 member rows)", result.output)

    def test_existing_link_is_never_overwritten(self):
        user = da.register_user("anna@x.example.com", "pass", username="anna")
        linked = self._person("anna@x.example.com", first="Anna", last="Old", user=user)
        candidate = self._person("anna@x.example.com", first="Anna", last="New")

        result = self._run_link(["--apply", "--actor-user-id", str(self.admin.id)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(db.Member.get_by_id(linked.id).user_id, user.id)
        self.assertIsNone(db.Member.get_by_id(candidate.id).user_id)
        self.assertIn("Already linked", result.output)
        self.assertIn(f"already linked to member {linked.id}", result.output)
        self.assertIn("Linked: 0", result.output)

    def test_null_email_and_ended_rows_are_not_candidates(self):
        da.register_user("anna@x.example.com", "pass", username="anna")
        da.register_user("bo@x.example.com", "pass", username="bo")
        ended = self._person("anna@x.example.com", end_date=date(2020, 1, 1))
        no_email = self._person(None, first="Bo", last="Berg")

        result = self._run_link(["--apply", "--actor-user-id", str(self.admin.id)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(db.Member.get_by_id(ended.id).user_id)
        self.assertIsNone(db.Member.get_by_id(no_email.id).user_id)
        self.assertIn("Linked: 0", result.output)

    def test_apply_never_invalidates_caches_during_apply(self):
        """mode="cli" never conveys, so --apply never invalidates a genebank cache."""
        da.register_user("cache@x.example.com", "pass", username="cache")
        self._person("cache@x.example.com")
        with patch("utils.matrikel.trigger_invalidation") as invalidate:
            result = self._run_link(["--apply", "--actor-user-id", str(self.admin.id)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Linked: 1", result.output)
        invalidate.assert_not_called()

    def test_apply_requires_valid_actor(self):
        da.register_user("anna@x.example.com", "pass", username="anna")
        self._person("anna@x.example.com")
        result = self._run_link(["--apply"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--actor-user-id", result.output)
        plain = da.register_user("plain@x.example.com", "pass", username="plain")
        result = self._run_link(["--apply", "--actor-user-id", str(plain.id)])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("admin eller matrikel_admin", result.output)

    def test_apply_audits_actor_and_source(self):
        user = da.register_user("anna@x.example.com", "pass", username="anna")
        person = self._person("anna@x.example.com")
        result = self._run_link(["--apply", "--actor-user-id", str(self.admin.id)])
        self.assertEqual(result.exit_code, 0, result.output)
        audit = db.MatrikelAudit.get(db.MatrikelAudit.action == "person_user_linked")
        self.assertEqual(
            (audit.actor_id, audit.payload["source"], audit.payload["person_id"], audit.payload["user_id"]),
            (self.admin.id, "cli", person.id, user.id),
        )

    def test_huvudmedlem_conveying_two_herds_is_parked_until_account_owns_both(self):
        user = da.register_user("two@x.example.com", "pass", username="two")
        person = self._person("two@x.example.com")
        h1 = db.Herd.create(genebank=self.genebanks[0], herd="G901", membership=person.membership)
        h2 = db.Herd.create(genebank=self.genebanks[0], herd="G902", membership=person.membership)
        user.add_role("owner", h1.id)
        result = self._run_link(["--apply", "--actor-user-id", str(self.admin.id)])
        self.assertIn("Needs review: 1", result.output)
        self.assertIn("G902", result.output)
        self.assertIsNone(db.Member.get_by_id(person.id).user_id)
        user.add_role("owner", h2.id)
        result = self._run_link(["--apply", "--actor-user-id", str(self.admin.id)])
        self.assertIn("Linked: 1", result.output)
        self.assertEqual(db.Member.get_by_id(person.id).user_id, user.id)

    def test_raced_candidate_does_not_block_later_candidates(self):
        """An IntegrityError on one candidate must not abort the run."""
        raced_user = da.register_user("raced@x.example.com", "pass", username="raced")
        raced_person = self._person("raced@x.example.com", first="Aa")
        ok_user = da.register_user("zz@x.example.com", "pass", username="zz")
        ok_person = self._person("zz@x.example.com", first="Zz")
        # Simulate the concurrent writer: link raced_user elsewhere after the plan is built.
        original = members_cli_module._plan_user_links

        def plan_then_race():
            report = original()
            db.Member.create(first_name="X", last_name="X", membership=db.Membership.create(), user=raced_user)
            return report

        with patch.object(members_cli_module, "_plan_user_links", plan_then_race):
            result = self._run_link(["--apply", "--actor-user-id", str(self.admin.id)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(db.Member.get_by_id(raced_person.id).user_id)
        self.assertEqual(db.Member.get_by_id(ok_person.id).user_id, ok_user.id)
        self.assertIn("Skipped (changed since the plan was made", result.output)
