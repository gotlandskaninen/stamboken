"""
Migration 58: the support account moves from the herd to its membership, with a type (Jonas 2026-11-18). The move
stops on a conflict instead of guessing, empties the herd's columns without an audit copy, and every reader and
writer uses the membership: on the herd page the last two digits for admin, matrikel_admin, the genebank's manager
and the herd's owners, nothing for a caretaker grant (U2); the whole number only in the yearly report list for admin
and matrikel_admin. Synthetic data only.
"""

import unittest
from datetime import date

import utils.data_access as da
import utils.database as db
from peewee import IntegrityError
from utils.matrikel import anonymize_person

from tests.database_test import _USE_POSTGRES, IsolatedSchemaTest
from tests.inbox_fixtures import InboxTest

ACCOUNT = "8327-4471 5512"  # ends in 12
DIGITS = ("8327", "4471", "5512")
OTHER = "9420-4618 0377"


def _sql(query, params=None):
    return db.DB_PROXY.execute_sql(query, params)


def snapshot():
    """Columns, constraints and triggers of membership and herd, the tables migration 58 changes."""
    tables = ["membership", "herd"]
    return (
        set(
            _sql(
                "SELECT table_name, column_name, data_type, character_maximum_length, is_nullable, "
                "coalesce(column_default, '') FROM information_schema.columns WHERE table_name = ANY(%s)",
                (tables,),
            ).fetchall()
        ),
        set(
            _sql(
                "SELECT c.relname, conname, pg_get_constraintdef(con.oid) FROM pg_constraint con "
                "JOIN pg_class c ON c.oid = con.conrelid WHERE c.relname = ANY(%s)",
                (tables,),
            ).fetchall()
        ),
        set(
            _sql(
                "SELECT c.relname, tgname, pg_get_triggerdef(t.oid), t.tgenabled FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid WHERE c.relname = ANY(%s) AND NOT tgisinternal",
                (tables,),
            ).fetchall()
        ),
    )


@unittest.skipUnless(_USE_POSTGRES, "raw-SQL migration path needs PostgreSQL")
class TestMigration58(IsolatedSchemaTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bootstrapped = snapshot()  # the class's own database, built by init() from nothing

    def setUp(self):
        super().setUp()
        self.a, self.b = db.Membership.create(member_number=901), db.Membership.create(member_number=902)
        g1, g2, m3 = self.herds
        db.Herd.update(membership=self.a).where(db.Herd.id.in_([g1.id, g2.id])).execute()
        db.Herd.update(membership=self.b, is_active=False).where(db.Herd.id == m3.id).execute()
        self.orphan = db.Herd.create(genebank=self.genebanks[0], herd="G4")

    def to_v57(self, accounts, *, drop_columns=True):
        """
        The schema before migration 58, and `accounts` ({herd: (number, name)}) on the herds, written while the
        audit trigger runs as v57 had it. Without `drop_columns` the membership keeps its columns, as on a rerun.
        """
        _sql("ALTER TABLE herd DROP CONSTRAINT ck_herd_no_bank_account")
        if drop_columns:
            _sql("ALTER TABLE membership DROP COLUMN bank_account_type, DROP COLUMN bank_account_number, "
                 "DROP COLUMN bank_name")  # fmt: skip
        for herd, (number, name) in accounts.items():
            _sql("UPDATE herd SET bank_account_number = %s, bank_name = %s WHERE herd_id = %s", (number, name, herd.id))
        db.SchemaHistory.delete().where(db.SchemaHistory.version == 58).execute()

    def account(self, membership):
        return _sql(
            "SELECT bank_account_type, bank_account_number, bank_name FROM membership WHERE membership_id = %s",
            (membership.id,),
        ).fetchone()

    def herd_accounts(self):
        return _sql(
            "SELECT herd_id FROM herd WHERE bank_account_number IS NOT NULL OR bank_name IS NOT NULL"
        ).fetchall()

    def herd_audit_rows(self):
        return _sql("SELECT count(*) FROM audit_log WHERE table_name = 'herd'").fetchone()[0]

    def test_fresh_bootstrap_equals_chain(self):
        with db.DB_PROXY.atomic() as tx:
            self.to_v57({})
            db.migrate_57_to_58()
            self.assertEqual(db.SchemaHistory.get_by_id(58).comment, db.SUPPORT_ACCOUNT_58)
            self.assertEqual(snapshot(), self.bootstrapped)
            tx.rollback()

    def test_moves_one_account_per_membership_without_audit_copies(self):
        g1, g2, m3 = self.herds
        with db.DB_PROXY.atomic() as tx:
            # G2 has the same account written otherwise; M3 (inactive) only a bank name; G4, without a membership,
            # only blanks: tab, newline, no-break space
            self.to_v57({g1: (f" {ACCOUNT} ", "Banken"), g2: ("83274471-5512", " banken\t"), m3: (None, " Bara bank "),
                         self.orphan: ("\t\n", "\u00a0")})  # fmt: skip
            audit_rows = self.herd_audit_rows()
            db.migrate_57_to_58()
            self.assertEqual(self.account(self.a), (None, ACCOUNT, "Banken"))  # the type is not guessed
            self.assertEqual(self.account(self.b), (None, None, "Bara bank"))
            self.assertEqual(self.herd_accounts(), [])
            self.assertEqual(self.herd_audit_rows(), audit_rows)  # emptied without a copy in audit_log
            self.assertEqual(snapshot(), self.bootstrapped)  # the trigger is on again, the CHECKs in place

            db.SchemaHistory.delete().where(db.SchemaHistory.version == 58).execute()
            db.migrate_57_to_58()  # a rerun changes nothing
            self.assertEqual(self.account(self.a), (None, ACCOUNT, "Banken"))
            tx.rollback()

    def test_rerun_never_overwrites_the_membership_account(self):
        g1, g2, _ = self.herds
        db.Membership.update(bank_account_type="bankkonto", bank_account_number=ACCOUNT).where(
            db.Membership.id == self.a.id
        ).execute()
        with db.DB_PROXY.atomic() as tx:
            self.to_v57({g1: ("8327 4471 5512", None)}, drop_columns=False)  # the same account
            db.migrate_57_to_58()
            self.assertEqual(self.account(self.a), ("bankkonto", ACCOUNT, None))
            self.assertEqual(self.herd_accounts(), [])
            tx.rollback()
        with db.DB_PROXY.atomic() as tx:
            self.to_v57({g2: (OTHER, None)}, drop_columns=False)
            with self.assertRaisesRegex(RuntimeError, rf"1 memberships .*\[{self.a.id}\]"):
                db.migrate_57_to_58()
            self.assertEqual(self.account(self.a), ("bankkonto", ACCOUNT, None))
            tx.rollback()

    def test_conflicts_stop_the_migration_without_loss(self):
        g1, g2, m3 = self.herds
        cases = {
            "two accounts": {g1: (ACCOUNT, "Banken"), g2: (OTHER, "Banken")},
            "two banks": {g1: (ACCOUNT, "Banken"), g2: (ACCOUNT, "Andra banken")},
            # never merged into an account no herd held: the bank from one herd, the number from the other
            "number and bank apart": {g1: (ACCOUNT, None), g2: (None, "Banken")},
            "one bank missing": {g1: (ACCOUNT, "Banken"), g2: (ACCOUNT, None)},
            "bankgiro and plusgiro": {g1: ("BG 123-4567", None), g2: ("PG 1234567", None)},
            "a marker on one": {g1: ("1234567", None), g2: ("bg 123-4567", None)},
            "no membership": {m3: (ACCOUNT, None), self.orphan: (OTHER, None)},
        }
        for case, accounts in cases.items():
            with self.subTest(case), db.DB_PROXY.atomic() as tx:
                self.to_v57(accounts)
                audit_rows = self.herd_audit_rows()
                with self.assertRaises(RuntimeError) as stop:
                    db.migrate_57_to_58()
                message = str(stop.exception)
                if case == "no membership":
                    self.assertIn("0 memberships", message)
                    self.assertIn(f"1 herds with an account but no membership (herd_id [{self.orphan.id}])", message)
                else:
                    self.assertIn(f"1 memberships whose herds hold different accounts (membership_id [{self.a.id}])",
                                  message)  # fmt: skip
                for secret in (*DIGITS, "9420", "4618", "Banken", "Andra"):
                    self.assertNotIn(secret, message)
                # all rolled back: the herds keep their values, the membership has no new columns, the trigger is on
                held = _sql("SELECT herd_id, bank_account_number, bank_name FROM herd WHERE bank_account_number "
                            "IS NOT NULL OR bank_name IS NOT NULL")  # fmt: skip
                self.assertEqual({row[0]: row[1:] for row in held.fetchall()}, {h.id: v for h, v in accounts.items()})
                columns = {c.name for c in db.DATABASE.get_columns("membership")}
                self.assertNotIn("bank_account_number", columns)
                enabled = _sql("SELECT tgenabled FROM pg_trigger WHERE tgrelid = 'herd'::regclass "
                               "AND tgname = 'audit_trigger'").fetchone()  # fmt: skip
                self.assertEqual(enabled, ("O",))
                self.assertEqual(self.herd_audit_rows(), audit_rows)
                tx.rollback()

    def test_an_erased_household_gets_no_account(self):
        """U14: a membership whose persons are all anonymised gets nothing, whatever its herds hold, and stops
        nothing; its herds are emptied like the others."""
        person = db.Member.create(first_name="Test", last_name="Person", membership=self.a, role="huvudmedlem")
        anonymize_person(person, db.User.get_by_id(self.admin.id))
        db.Member.create(first_name="Test", last_name="Kvar", membership=self.b, role="huvudmedlem")
        gone = db.Member.create(first_name="Test", last_name="Borta", membership=self.b, role="familjemedlem")
        anonymize_person(gone, db.User.get_by_id(self.admin.id))  # one erased person is not an erased household
        g1, g2, m3 = self.herds
        with db.DB_PROXY.atomic() as tx:
            self.to_v57({g1: (ACCOUNT, "Banken"), g2: (OTHER, None), m3: (OTHER, "Banken")})
            db.migrate_57_to_58()
            self.assertEqual(self.account(self.a), (None, None, None))
            self.assertEqual(self.account(self.b), (None, OTHER, "Banken"))
            self.assertEqual(self.herd_accounts(), [])
            tx.rollback()

    def test_the_herd_columns_and_the_type_are_guarded(self):
        for write in (
            lambda: db.Herd.update(bank_account_number="1234-5").where(db.Herd.id == self.herds[0].id).execute(),
            lambda: db.Herd.update(bank_name="Banken").where(db.Herd.id == self.herds[0].id).execute(),
            lambda: db.Membership.update(bank_account_type="swish").where(db.Membership.id == self.a.id).execute(),
        ):
            with self.assertRaises(IntegrityError), db.DB_PROXY.atomic():
                write()
        for kind in (*db.ACCOUNT_TYPES, None):
            db.Membership.update(bank_account_type=kind).where(db.Membership.id == self.a.id).execute()


class SupportAccountTest(InboxTest):
    """G1 and G2 share a membership whose main member is `main`; `caretaker` holds a grant on G1."""

    def setUp(self):
        super().setUp()
        self.ms = db.Membership.create(
            member_number=42, bank_account_type="bankkonto", bank_account_number=ACCOUNT, bank_name="Banken"
        )
        db.Herd.update(membership=self.ms).where(db.Herd.id.in_([self.herds[0].id, self.herds[1].id])).execute()
        self.main = self.user("main")
        self.person = db.Member.create(
            first_name="Test", last_name="Huvudmedlem", membership=self.ms, role="huvudmedlem", user=self.main
        )
        self.caretaker = self.user("care")
        other = db.Membership.create(member_number=77)
        person = db.Member.create(first_name="Test", last_name="Skötare", membership=other, role="skotare",
                                  user=self.caretaker)  # fmt: skip
        db.HerdAccessGrant.create(member=person, herd=self.herds[0], granted_by=self.admin)
        self.kassor = self.user("kassor", ("matrikel_admin", None))
        self.main, self.caretaker = db.User.get_by_id(self.main.id), db.User.get_by_id(self.caretaker.id)

    def herd(self, index=0):
        return db.Herd.get_by_id(self.herds[index].id)

    def stored(self):
        ms = db.Membership.get_by_id(self.ms.id)
        return ms.bank_account_type, ms.bank_account_number, ms.bank_name

    def audits(self):
        return [(a.action, a.payload) for a in db.MatrikelAudit.select().order_by(db.MatrikelAudit.id)]


class TestReaders(SupportAccountTest):
    def test_bank_visibility_by_actor(self):
        """U2: the herd page shows only the end, to admin and matrikel_admin too (the old app sends back what it read,
        so a whole number there could come back stale); a caretaker grant reads none of it."""
        expected = {
            "admin": ("••12", "Banken"),
            "kassor": ("••12", "Banken"),
            "man": ("••12", "Banken"),
            "main": ("••12", "Banken"),
            "owner": ("••12", "Banken"),  # a legacy owner privilege on G1
            "care": None,
            "spec": None,
        }
        for name, shown in expected.items():
            user = db.User.get(db.User.email == name)
            with self.subTest(name):
                data = self.herd().filtered_dict(user)
                got = (data["bank_account_number"], data["bank_name"]) if "bank_account_number" in data else None
                self.assertEqual(got, shown)
                self.login(name)
                if name != "kassor":  # matrikel_admin has no genebank role
                    body = self.client.get("/api/herd/G1").get_data(as_text=True)
                    self.assertEqual(DIGITS[0] in body, shown is not None and shown[0] == ACCOUNT, body)
                    self.assertEqual("Banken" in body, shown is not None)
        self.assertNotIn("bank_account_number", self.herd().filtered_dict(None))

    def test_genebank_listing_reads_the_membership(self):
        rows = {row["herd"]: row for row in self.genebanks[0].get_herds(db.User.get_by_id(self.manager.id))}
        self.assertEqual((rows["G1"]["bank_account_number"], rows["G2"]["bank_name"]), ("••12", "Banken"))
        rows = {row["herd"]: row for row in self.genebanks[1].get_herds(db.User.get_by_id(self.admin.id))}
        self.assertEqual((rows["M3"]["bank_account_number"], rows["M3"]["bank_name"]), (None, None))  # no membership

    def test_yearly_report_cuts_the_account_unless_full_account(self):
        rnd = db.YearlyReportRound.create(
            report_year=2025, start_date=date(2025, 12, 31), end_date=date(2026, 3, 30), created_by=self.admin
        )
        db.YearlyHerdReport.create(
            herd=self.herds[0], report_date=date(2026, 1, 1), generated_by=self.manager, name="2025", data="{}",
            publish=False, publish_tel=False, publish_email=False, publish_address=False, round=rnd,
        )  # fmt: skip
        gb = self.genebanks[0].id
        self.assertEqual(da.get_yearly_reports(rnd.id, gb)[0]["bank_account"], "••12")
        self.assertEqual(da.get_yearly_reports(rnd.id, gb, True)[0]["bank_account"], ACCOUNT)
        self.assertEqual(da.get_yearly_reports(rnd.id, gb)[0]["bank_name"], "Banken")
        # a manager who is also the main member gets the mask too (U2)
        db.Member.update(user=self.manager.id).where(db.Member.id == self.person.id).execute()
        self.login("man")
        path = f"/api/manage/yearly-reports/{rnd.id}/{gb}"
        self.assertEqual(self.client.get(path).json["reports"][0]["bank_account"], "••12")
        csv_text = self.client.get(f"{path}/export").get_data(as_text=True)
        self.assertIn("••12", csv_text)
        self.assertNotIn(DIGITS[0], csv_text)

    def test_herd_audit_history_is_cut_for_everyone_but_admin_and_kassor(self):
        """Snapshots from before migration 58 hold the account; the herd's own users see only its end (U2)."""
        db.AuditLog.create(
            table_name="herd",
            record_id=str(self.herds[0].id),
            operation="UPDATE",
            changed_fields=["bank_account_number"],
            old_data={"bank_account_number": OTHER},
            new_data={"bank_account_number": ACCOUNT},
        )
        self.main.add_role("manager", self.genebanks[0].id)  # the history needs a manager; she owns G1 too
        for name, whole in (("main", False), ("admin", True)):
            self.login(name)
            response = self.client.get(f"/api/audit-log/herd/{self.herds[0].id}")
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            data = response.json["data"]
            seen = {
                e[k]["bank_account_number"] for e in data for k in ("old_data", "new_data") if e[k] and len(e[k]) == 1
            }
            self.assertEqual(seen, {OTHER, ACCOUNT} if whole else {"••77", "••12"})

    def test_a_short_number_shows_only_that_there_is_one(self):
        """Two digits of a number with few digits would give most of it away: then only the mask, everywhere."""
        for number, shown in (("12-3", "••"), ("123-4", "••"), ("1234-5", "••45")):
            with self.subTest(number):
                self.assertEqual(db.account_end(number), shown)
        db.Membership.update(bank_account_type="plusgiro", bank_account_number="12-3").where(
            db.Membership.id == self.ms.id
        ).execute()
        manager = db.User.get_by_id(self.manager.id)
        form = self.herd().filtered_dict(manager)
        self.assertEqual(form["bank_account_number"], "••")
        rnd = db.YearlyReportRound.create(
            report_year=2025, start_date=date(2025, 12, 31), end_date=date(2026, 3, 30), created_by=self.admin
        )
        db.YearlyHerdReport.create(
            herd=self.herds[0], report_date=date(2026, 1, 1), generated_by=self.manager, name="2025", data="{}",
            publish=False, publish_tel=False, publish_email=False, publish_address=False, round=rnd,
        )  # fmt: skip
        self.assertEqual(da.get_yearly_reports(rnd.id, self.genebanks[0].id)[0]["bank_account"], "••")
        from utils.arsrapport import account_end  # pylint: disable=import-outside-toplevel

        self.assertEqual(account_end(self.herd()), "")  # an account, its end not shown; None is no account
        self.assertEqual(da.update_herd({**form, "herd_name": "Ny"}, manager.uuid, legacy=True), {"status": "updated"})
        self.assertEqual(self.stored(), ("plusgiro", "12-3", "Banken"))

    def test_account_end_reads_the_membership(self):
        from utils.arsrapport import account_end  # pylint: disable=import-outside-toplevel

        self.assertEqual(account_end(self.herd()), "12")
        self.assertIsNone(account_end(self.herd(2)))


class TestLegacyWriters(SupportAccountTest):
    def save(self, user, **fields):
        return da.update_herd({"id": self.herds[0].id, **fields}, user.uuid, legacy=True)

    def test_masked_echo_keeps_the_account_and_a_partial_mask_is_refused(self):
        for user in (self.manager, self.main):
            echoed = self.herd().filtered_dict(db.User.get_by_id(user.id))
            self.assertEqual(echoed["bank_account_number"], "••12")
            self.assertEqual(self.save(user, **echoed), {"status": "updated"})
            for value in ("•12", "••8327", "••1"):
                with self.subTest(value=value):
                    refused = self.save(user, bank_account_number=value)
                    self.assertEqual(refused["status"], "error")
        self.assertEqual(self.stored(), ("bankkonto", ACCOUNT, "Banken"))
        self.assertEqual(self.audits(), [])  # no change, no log

    def test_new_account_goes_to_the_membership_and_is_logged_by_name(self):
        self.assertEqual(self.save(self.main, bank_account_number="1234-567 890"), {"status": "updated"})
        self.assertEqual(self.stored(), (None, "1234-567 890", "Banken"))  # the legacy form has no type
        herd = self.herd()
        self.assertEqual((herd.bank_account_number, herd.bank_name), (None, None))
        payload = {"fields": ["bank_account_number", "bank_account_type"], "source": "herd", "herd_id": herd.id}
        self.assertEqual(self.audits(), [("kontakt_andrad", payload)])
        # the other herd of the membership reads the same account
        self.assertEqual(self.herd(1).filtered_dict(db.User.get_by_id(self.admin.id))["bank_account_number"], "••90")

    def test_same_digits_and_echoes_change_nothing(self):
        admin = db.User.get_by_id(self.admin.id)
        self.assertEqual(self.save(admin, **self.herd().filtered_dict(admin)), {"status": "updated"})
        self.assertEqual(self.save(admin, bank_account_number="83274471 5512", bank_name=" Banken "),
                         {"status": "updated"})  # fmt: skip
        self.assertEqual(self.stored(), ("bankkonto", ACCOUNT, "Banken"))
        self.assertEqual(self.audits(), [])

    def test_no_one_blanks_it_on_the_herd_page(self):
        """Everyone reads the mask there, so a blank is never what was shown: it could be a stale form's."""
        values = {"bank_account_number": ("", None, "45", "abc"), "bank_name": ("", None)}
        for user in (self.manager, self.main, self.admin):
            for field, value in ((field, value) for field, sent in values.items() for value in sent):
                fields = {field: value}
                with self.subTest(user=user.email, fields=fields):
                    self.assertEqual(self.save(user, **fields)["status"], "error")
        self.assertEqual(self.stored(), ("bankkonto", ACCOUNT, "Banken"))

    def test_a_stale_form_never_replaces_a_newer_account(self):
        """The old app sends back the whole herd it read. Meanwhile the account changed through the other herd."""
        admin, manager = db.User.get_by_id(self.admin.id), db.User.get_by_id(self.manager.id)
        db.Membership.update(bank_account_number=None, bank_name=None).where(db.Membership.id == self.ms.id).execute()
        empty_form = self.herd().filtered_dict(admin)  # read while there is no account
        self.assertEqual(da.update_herd({"id": self.herds[1].id, "bank_account_number": ACCOUNT, "bank_name": "Banken"},
                                        manager.uuid, legacy=True), {"status": "updated"})  # fmt: skip
        forms = {"admin": self.herd().filtered_dict(admin), "manager": self.herd().filtered_dict(manager)}
        # then the account changes again, to one ending like the first, with another bank
        self.assertEqual(da.update_herd({"id": self.herds[1].id, "bank_account_number": "9999-112", "bank_name": "Nya"},
                                        manager.uuid, legacy=True), {"status": "updated"})  # fmt: skip
        for name, form in (("empty", empty_form), *forms.items()):
            with self.subTest(name):
                user = manager if name == "manager" else admin
                result = da.update_herd({**form, "herd_name": "Gammal"}, user.uuid, legacy=True)
                self.assertEqual(result["status"], "error", result)
                self.assertEqual(self.stored(), (None, "9999-112", "Nya"))
        self.assertNotEqual(self.herd().herd_name, "Gammal")

    def test_a_paused_main_member_with_a_legacy_owner_role_writes_no_account(self):
        db.Membership.update(membership_status="inactive").where(db.Membership.id == self.ms.id).execute()
        self.main.add_role("owner", self.herds[0].id)
        result = self.save(db.User.get_by_id(self.main.id), bank_account_number=OTHER)
        self.assertEqual(result, {"status": "error", "message": "Forbidden"})
        self.assertEqual(self.stored(), ("bankkonto", ACCOUNT, "Banken"))

    def test_caretaker_and_legacy_owner_change_nothing(self):
        """U2: a grant or a legacy owner privilege is no right to the membership's shared account."""
        caretaker_view = self.herd().filtered_dict(self.caretaker)
        self.assertNotIn("bank_account_number", caretaker_view)
        self.assertEqual(self.save(self.caretaker, herd_name="Ny"), {"status": "updated"})  # other fields still save
        forbidden, updated = {"status": "error", "message": "Forbidden"}, {"status": "updated"}
        # a right guess and a wrong one get the same answer: it never tells what is stored
        guesses = ({"bank_account_number": OTHER}, {"bank_name": "Annan bank"}, {"bank_account_number": ACCOUNT})
        for user, fields, expected in (
            *((self.caretaker, fields, forbidden) for fields in (*guesses, {"bank_name": "Banken"})),
            *((self.owner, fields, forbidden) for fields in guesses),
            (self.owner, {"bank_account_number": "••12", "bank_name": "Banken "}, updated),  # what the owner reads
        ):
            with self.subTest(user=user.email, fields=fields):
                self.assertEqual(self.save(user, **fields), expected)
        # the old app sends a hidden field back empty: an echo, so the caretaker's other changes still save
        for empty in ("", None):
            fields = {"bank_account_number": empty, "bank_name": empty, "herd_name": f"Ny {empty}"}
            self.assertEqual(self.save(self.caretaker, **fields), {"status": "updated"})
        self.assertEqual(self.herd().herd_name, "Ny None")
        self.assertEqual(self.stored(), ("bankkonto", ACCOUNT, "Banken"))
        self.assertEqual(self.audits(), [])

    def test_herd_without_membership_has_no_account_to_change(self):
        m3 = self.herds[2]
        admin = db.User.get_by_id(self.admin.id)
        self.assertEqual(da.update_herd({"id": m3.id, "bank_account_number": None}, admin.uuid), {"status": "updated"})
        refused = da.update_herd({"id": m3.id, "bank_account_number": OTHER}, admin.uuid)
        self.assertEqual(refused["status"], "error")
        self.assertIsNone(db.Herd.get_by_id(m3.id).bank_account_number)

    def test_add_herd_says_a_typed_account_cannot_be_saved(self):
        """A new herd has no membership, so no account: a typed one is refused, not dropped with a success."""
        refused = {
            "status": "error",
            "message": "Kontot för stödet sparas på medlemskapet. Koppla besättningen till ett medlemskap först.",
        }
        for code, bank in (("G77", {"bank_account_number": OTHER}), ("G78", {"bank_name": "B"})):
            form = {"herd": code, "genebank": self.genebanks[0].id, **bank}
            self.assertEqual(da.add_herd(form, self.admin.uuid), refused)
            self.assertFalse(db.Herd.select().where(db.Herd.herd == code).exists())
        # the old app's empty form: blanks are no account
        blank = {"bank_account_number": " \t", "bank_name": None}
        self.assertEqual(da.add_herd({"herd": "G79", "genebank": self.genebanks[0].id, **blank}, self.admin.uuid),
                         {"status": "success"})  # fmt: skip
        herd = db.Herd.get(db.Herd.herd == "G79")
        self.assertEqual((herd.bank_account_number, herd.bank_name), (None, None))


@unittest.skipUnless(_USE_POSTGRES, "audit_log is PostgreSQL-only")
class TestAuditUndo(SupportAccountTest):
    def entry(self, **old):
        return db.AuditLog.create(
            table_name="herd", record_id=str(self.herds[0].id), operation="UPDATE", changed_fields=list(old),
            old_data={"herd_id": self.herds[0].id, **old}, new_data={"herd_id": self.herds[0].id},
        )  # fmt: skip

    def test_revert_and_restore_cannot_recreate_the_herd_account(self):
        old = self.entry(bank_account_number=OTHER, bank_name="Gamla banken", herd_name="Gammal")
        body, status = da.revert_audit_entry(old.id, ["bank_account_number"], is_admin=True)
        self.assertEqual((status, body["message"]), (409, "Kontot för stödet finns nu på medlemskapet och kan inte "
                                                         "ångras eller återställas här."))  # fmt: skip
        body, status = da.restore_record("herd", self.herds[0].id, old.id, is_admin=True)
        self.assertEqual(status, 200, body)
        herd = self.herd()
        self.assertEqual((herd.bank_account_number, herd.bank_name, herd.herd_name), (None, None, "Gammal"))
        self.assertEqual(self.stored(), ("bankkonto", ACCOUNT, "Banken"))


class TestAnonymisation(SupportAccountTest):
    def test_erasing_the_last_person_clears_the_account(self):
        anonymize_person(self.person, db.User.get_by_id(self.admin.id))
        self.assertEqual(self.stored(), (None, None, None))
