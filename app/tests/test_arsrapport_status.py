#!/usr/bin/env python3
"""
Tests for the yearly report's status view, the manager's "i tid" override, villkor in the ReportView and the blank
form. Synthetic herds, rabbits and addresses only.

isort:skip_file
"""

import os
from datetime import date, datetime, timedelta
from datetime import time as clock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.inbox as inbox
from utils.arsrapport_statistik import innehav, statistik

from tests.arsrapport_fixtures import ArsrapportTest
from tests.ht_helpers import count_queries
from tests.inbox_fixtures import QUALITY

LAST = date(2025, 12, 31)
NOW = datetime.combine(date(2026, 1, 15), clock(12), arsrapport.STOCKHOLM)
GOOD = {"hane": True, "hona": True, "kull": True, "i_tid": True}


class StatusTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        self.at(NOW)
        self.round_ = self.round(2025)
        self.h = self.herd("G9001")
        self.owner.add_role("owner", self.h.id)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.mellerud_manager = self.user("mman", ("manager", self.mellerud.id))

    def herd(self, code, email="x@example.invalid"):
        herd = db.Herd.create(genebank=self.gotland, herd=code, herd_name=f"Besättning {code}", is_active=True)
        if email:
            self.main_member(herd, email)
        return herd

    def breeders(self, herd, sexes=("female", "male"), litter=3, born=date(2025, 5, 2)):
        """Rabbits of `herd` reported kvar in a submitted, in-time report, and a 2025 litter of `litter` kits."""
        rabbits = self.rabbits(herd, len(sexes), sexes=sexes)
        if litter is not None:
            db.Breeding.create(
                breeding_herd_id=herd, breed_date=born - timedelta(days=31), birth_date=born, litter_size=litter
            )
        return rabbits, self.reported(herd, *(self.kvar(r, vikt=2.8) for r in rabbits))

    def status(self, user="man", genebank=None):
        self.login(user)
        return self.client.get(f"/api/v2/arsrapport/2025/status?genebank_id={(genebank or self.gotland).id}")

    def rows(self, user="man"):
        response = self.status(user)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return {row["herd"]: row for row in response.get_json()["rows"]}

    def form_item(self, herd, state):
        stored = [("inkorg/original/0.jpg", f"{herd.id}0".rjust(64, "0"), QUALITY)]
        item, (document,) = inbox.create_upload(self.owner, herd, None, stored)
        document.doc_type = "arsblankett"
        document.save()
        db.InboxItem.update(state=state).where(db.InboxItem.id == item.id).execute()
        return item

    def test_state_precedence(self):
        ending = self.herd("G9101")
        self.reported(ending, ending_genbank=True, membership_after_end="kvar_utan_genbank")
        self.reported(self.h)
        asking, arrived = self.herd("G9102"), self.herd("G9103")
        self.form_item(asking, "vantar_uppfodare")
        self.form_item(arrived, "ny")
        started = self.herd("G9104")
        self.herd("G9105", email=None)
        self.herd("G9106")
        db.YearlyReportDraft.create(herd=started, round=self.round_, data={}, updated_at=NOW)
        # a draft does not beat an item, and a report beats both
        self.form_item(self.h, "ny")
        db.YearlyReportDraft.create(herd=arrived, round=self.round_, data={}, updated_at=NOW)
        rows = self.rows()
        self.assertEqual(
            {code: row["state"] for code, row in rows.items()},
            {
                "G9001": "inskickad",
                "G9101": "avslutar",
                "G9102": "blankett_vantar",
                "G9103": "blankett_inkommen",
                "G9104": "paborjad",
                "G9105": "ingen_epost",
                "G9106": "ej_rapporterad",
            },
        )
        self.assertNotIn("GX1", rows)
        self.assertEqual(rows["G9101"]["membership_after_end"], "kvar_utan_genbank")
        counts = self.status().get_json()["counts"]
        self.assertEqual((counts["inskickad"], counts["avslutar"], counts["ej_rapporterad"]), (1, 1, 1))

    def test_inactive_herd_with_a_report_gets_a_row(self):
        old = self.herd("G9107")
        self.reported(old)
        db.Herd.update(is_active=False).where(db.Herd.id == old.id).execute()
        self.herd("G9108")
        db.Herd.update(is_active=False).where(db.Herd.herd == "G9108").execute()
        self.assertEqual({"G9107", "G9001"} & set(self.rows()), {"G9107", "G9001"})
        self.assertNotIn("G9108", self.rows())

    def test_inactive_herd_with_only_a_withdrawn_report_gets_a_row(self):
        old = self.herd("G9109")
        report = self.reported(old)
        db.YearlyHerdReport.update(status="voided", voided_at=NOW, voided_by_user=self.owner.id).where(
            db.YearlyHerdReport.id == report.id
        ).execute()
        db.Herd.update(is_active=False).where(db.Herd.id == old.id).execute()
        row = self.rows()["G9109"]
        self.assertEqual((row["state"], row["source"], row["received_at"]), ("ej_rapporterad", None, None))

    def test_support_conditions(self):
        a, b = self.rabbits(self.h, 2)
        cases = {}
        report = self.reported(self.h, self.kvar(a, vikt=2.8), self.kvar(b, vikt=2.8))
        db.Breeding.create(
            breeding_herd_id=self.h, breed_date=date(2025, 4, 1), birth_date=date(2025, 5, 2), litter_size=3
        )
        self.assertEqual(self.rows()["G9001"]["villkor"], GOOD)
        db.Individual.update(castration_date=date(2025, 6, 1)).where(db.Individual.id == b.id).execute()
        cases["castrated male"] = self.rows()["G9001"]["villkor"]
        self.assertEqual(cases["castrated male"], {**GOOD, "hane": False})
        db.Individual.update(castration_date=None).where(db.Individual.id == b.id).execute()
        db.Breeding.update(litter_size=0).where(
            db.Breeding.breeding_herd_id == self.h.id, db.Breeding.birth_date > LAST - timedelta(days=300)
        ).execute()
        self.assertEqual(self.rows()["G9001"]["villkor"], {**GOOD, "kull": False})
        db.Breeding.update(litter_size=3).where(
            db.Breeding.breeding_herd_id == self.h.id, db.Breeding.birth_date > LAST - timedelta(days=300)
        ).execute()
        report.received_at = datetime.combine(date(2026, 2, 1), clock(12), arsrapport.STOCKHOLM)
        report.save()
        self.assertEqual(self.rows()["G9001"]["villkor"], {**GOOD, "i_tid": False})
        report.received_at = datetime.combine(date(2026, 1, 31), clock(23, 30), arsrapport.STOCKHOLM)
        report.save()
        self.assertTrue(self.rows()["G9001"]["villkor"]["i_tid"])  # the Stockholm date, not UTC
        report.received_at = datetime.combine(date(2026, 2, 1), clock(0, 30), arsrapport.STOCKHOLM)  # 31 Jan in UTC
        report.save()
        self.assertFalse(self.rows()["G9001"]["villkor"]["i_tid"])  # the Swedish day is 1 February
        report.on_time_override = True
        report.save()
        self.assertTrue(self.rows()["G9001"]["villkor"]["i_tid"])

    def test_pending_sale_proposal_does_not_count(self):
        (female, male), report = self.breeders(self.h)
        db.SaleProposal.create(
            report=report,
            submission=db.YearlyReportSubmission.get(db.YearlyReportSubmission.report == report.id),
            individual=male,
            sale_date=date(2025, 12, 20),
        )
        self.assertEqual(self.rows()["G9001"]["villkor"], {**GOOD, "hane": False})
        db.SaleProposal.update(state="avvisad").execute()
        self.assertTrue(self.rows()["G9001"]["villkor"]["hane"])

    def test_one_herd_matches_the_genebank_rule(self):
        self.breeders(self.h)
        other = self.herd("G9002")
        self.breeders(other, sexes=("female",), litter=None)
        for herd in (self.h, other):
            report = arsrapport.current_report(herd, self.round_)
            held = innehav(self.gotland.id, 2025).get(herd.id, [])
            expected = arsrapport.support_conditions(
                held, statistik(self.gotland.id, 2025).get(herd.id), report, self.round_.deadline
            )
            self.assertEqual(arsrapport.herd_conditions(herd, self.round_, report), expected)
            self.assertEqual(self.rows()[herd.herd]["villkor"], expected)
        self.assertEqual(self.rows()["G9002"]["villkor"], {**GOOD, "hane": False, "kull": False})

    def test_view_carries_villkor(self):
        self.breeders(self.h)
        self.login("owner")
        view = self.client.get("/api/v2/arsrapport/besattning/G9001/2025").get_json()
        self.assertEqual(view["report"]["villkor"], GOOD)

    def test_receipt_has_no_villkor(self):
        a, b = self.rabbits(self.h, 2)
        self.login("owner")
        response = self.client.post(
            "/api/v2/arsrapport/besattning/G9001/2025/skicka",
            json=self.body(self.kvar(a, vikt=2.8), self.kvar(b, vikt=2.8)),
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertNotIn("villkor", response.get_json())

    def test_not_stated_marks_the_support(self):  # case 8, status half
        rabbits, missing = self.ej_angiven_case(self.h)
        entries = [self.ej_angiven(r) if r in missing else self.kvar(r, vikt=2.8) for r in rabbits]
        self.reported(self.h, *entries, source="paper")
        row = self.rows()["G9001"]
        self.assertEqual(row["flags"], {"ej_angivna": 3, "ej_angivna_paverkar": True})
        self.assertFalse(row["villkor"]["hane"])
        self.assertEqual((row["villkor"]["kull"], row["villkor"]["i_tid"], row["source"]), (True, True, "paper"))

    def test_not_stated_does_not_mark_when_another_condition_fails(self):  # U12: all four conditions
        rabbits, missing = self.ej_angiven_case(self.h)
        entries = [self.ej_angiven(r) if r in missing else self.kvar(r, vikt=2.8) for r in rabbits]
        report = self.reported(self.h, *entries)
        report.received_at = datetime.combine(date(2026, 3, 1), clock(12), arsrapport.STOCKHOLM)
        report.save()
        self.assertEqual(self.rows()["G9001"]["flags"], {"ej_angivna": 3, "ej_angivna_paverkar": False})
        report.on_time_override = True
        report.save()
        self.assertTrue(self.rows()["G9001"]["flags"]["ej_angivna_paverkar"])

    def test_owner_change_clears_the_not_stated_flag(self):  # case 8, the owner's Ändra
        rabbits, missing = self.ej_angiven_case(self.h)
        entries = [self.ej_angiven(r) if r in missing else self.kvar(r, vikt=2.8) for r in rabbits]
        report = self.reported(self.h, *entries)
        received = db.YearlyHerdReport.get_by_id(report.id).received_at
        self.login("owner")
        self.at(datetime.combine(date(2026, 1, 20), clock(12), arsrapport.STOCKHOLM))
        response = self.client.post(
            "/api/v2/arsrapport/besattning/G9001/2025/skicka",
            json=self.body(*(self.kvar(r, vikt=2.8) for r in rabbits), revision=1),
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        row = self.rows()["G9001"]
        self.assertEqual(row["flags"], {"ej_angivna": 0, "ej_angivna_paverkar": False})
        self.assertTrue(row["villkor"]["hane"])
        self.assertEqual(db.YearlyHerdReport.get_by_id(report.id).received_at, received)

    def test_status_access(self):
        self.reported(self.h)
        self.assertEqual(self.status("man").status_code, 200)
        self.assertEqual(self.status("hjalp").status_code, 200)
        self.assertEqual(self.status("admin").status_code, 200)
        self.assertEqual(self.status("mman").status_code, 403)  # Mellerud manager, Gotland's view
        self.assertEqual(self.status("mhjalp").status_code, 403)
        self.assertEqual(self.status("owner").status_code, 403)
        self.assertEqual(self.status("man", genebank=self.mellerud).status_code, 403)
        self.assertEqual(self.client.get("/api/v2/arsrapport/2025/status").status_code, 400)
        self.assertEqual(
            self.client.get(f"/api/v2/arsrapport/2024/status?genebank_id={self.gotland.id}").status_code, 404
        )
        self.login("hjalp")
        denied = self.client.post("/api/v2/arsrapport/besattning/G9001/2025/i-tid", json={"on_time": True})
        self.assertEqual(denied.status_code, 403)
        self.login("owner")
        denied = self.client.post("/api/v2/arsrapport/besattning/G9001/2025/i-tid", json={"on_time": True})
        self.assertEqual(denied.status_code, 403)
        self.assertIsNone(db.YearlyHerdReport.get(db.YearlyHerdReport.herd == self.h.id).on_time_override)

    def test_phone_only_for_the_manager(self):
        db.Member.update(phone="070-000 00 00").where(db.Member.membership == self.h.membership).execute()
        other = self.herd("G9002")  # a main member without a phone
        self.assertEqual(self.rows("man")["G9001"]["telefon"], "070-000 00 00")
        self.assertEqual(self.rows("admin")["G9001"]["telefon"], "070-000 00 00")
        self.assertIsNone(self.rows("man")[other.herd]["telefon"])
        for row in self.rows("hjalp").values():
            self.assertNotIn("telefon", row)

    def test_status_row_does_not_expose_the_account(self):
        db.Herd.update(bank_account_number="12345678901").where(db.Herd.id == self.h.id).execute()
        self.reported(self.h)
        self.assertNotIn("12345678901", self.status().get_data(as_text=True))

    def test_on_time_override(self):  # case 5
        report = self.reported(self.h)
        self.login("man")
        path = "/api/v2/arsrapport/besattning/G9001/2025/i-tid"
        response = self.client.post(path, json={"on_time": True})
        self.assertEqual((response.status_code, response.get_json()), (200, {"on_time_override": True}))
        self.assertEqual(db.YearlyHerdReport.get_by_id(report.id).on_time_set_by_id, self.manager.id)
        self.assertEqual(self.rows()["G9001"]["on_time_override"], True)
        response = self.client.post(path, json={"on_time": None})
        self.assertEqual(response.get_json(), {"on_time_override": None})
        self.assertEqual(self.client.post(path, json={"on_time": "ja"}).status_code, 400)
        self.assertEqual(self.client.post(path, json={}).status_code, 400)  # a missing key never clears
        self.assertEqual(self.client.post("/api/v2/arsrapport/besattning/G9002/2025/i-tid", json={}).status_code, 404)

    def test_on_time_holds_after_a_late_change(self):  # case 5
        rabbits, _ = self.ej_angiven_case(self.h)
        report = self.reported(self.h, *(self.kvar(r, vikt=2.8) for r in rabbits))
        self.at(datetime.combine(date(2026, 1, 30), clock(12), arsrapport.STOCKHOLM))
        db.YearlyHerdReport.update(received_at=arsrapport.now()).where(db.YearlyHerdReport.id == report.id).execute()
        self.assertTrue(self.rows()["G9001"]["villkor"]["i_tid"])
        self.login("owner")
        self.at(datetime.combine(date(2026, 2, 2), clock(12), arsrapport.STOCKHOLM))
        response = self.client.post(
            "/api/v2/arsrapport/besattning/G9001/2025/skicka",
            json=self.body(*(self.kvar(r, vikt=2.8) for r in rabbits), revision=1, message="Ändrad"),
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        row = self.rows()["G9001"]
        self.assertTrue(row["villkor"]["i_tid"])
        self.assertTrue(row["received_at"].startswith("2026-01-30"))

    def test_blank_form(self):
        url = "/api/v2/arsrapport/blankett.pdf"
        self.client.get("/api/logout")
        self.assertEqual(self.client.get(url).status_code, 401)
        self.login("owner")
        missing = self.client.get(url)
        self.assertEqual(
            (missing.status_code, missing.get_json()["detail"]), (404, "Blanketten finns inte på servern än.")
        )
        os.makedirs(os.path.dirname(inbox.private_path(arsrapport.BLANK_FORM)))
        with open(inbox.private_path(arsrapport.BLANK_FORM), "wb") as out:
            out.write(b"%PDF-1.4 test")
        response = self.client.get(url)
        self.assertEqual((response.status_code, response.mimetype), (200, "application/pdf"))
        self.assertEqual(response.get_data(), b"%PDF-1.4 test")

    def test_status_queries_do_not_grow_with_herds(self):
        def queries():
            self.login("man")
            with count_queries() as counter:
                response = self.client.get(f"/api/v2/arsrapport/2025/status?genebank_id={self.gotland.id}")
            self.assertEqual(response.status_code, 200)
            return counter["n"]

        for n in range(5):
            herd = self.herd(f"G91{n:02d}")
            self.breeders(herd)
        few = queries()
        for n in range(5, 40):
            herd = self.herd(f"G91{n:02d}")
            self.breeders(herd)
            if n % 3 == 0:
                self.form_item(herd, "ny")
        self.assertEqual(queries(), few)
