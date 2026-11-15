#!/usr/bin/env python3
"""
Tests for the yearly report's rounds, their activation per genebank, and report_access.

isort:skip_file
"""

from datetime import date, datetime, timezone

import utils.arsrapport as arsrapport
import utils.database as db
import utils.inbox as inbox

from tests.arsrapport_fixtures import ArsrapportTest


class RundorTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        self.at(date(2026, 11, 15))

    def test_create_round_defaults(self):
        self.login("man")
        r = self.api("PUT", "/rundor/2026")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        expected = {
            "year": 2026,
            "start_date": "2026-12-31",
            "deadline": "2027-01-31",
            "end_date": "2027-03-30",
            "is_active": False,
            "genebanks": [],
        }
        self.assertEqual(r.json, expected)
        # Again with one date moved: only that date changes.
        r = self.api("PUT", "/rundor/2026", deadline="2027-02-02")
        self.assertEqual(r.json, {**expected, "deadline": "2027-02-02"})
        self.assertEqual(db.YearlyReportRound.select().count(), 1)

    def test_round_dates_must_be_ordered(self):
        self.login("man")
        for year, body in (
            (2026, {"deadline": "2026-12-30"}),  # before the default start
            (2026, {"start_date": "2027-02-01"}),  # after the default deadline
            (2026, {"end_date": "2027-01-30"}),  # before the default deadline
            (2026, {"start_date": "31/12/2026"}),
            (2029, {}),  # the Stockholm year is 2026
            (2024, {}),
        ):
            r = self.api("PUT", f"/rundor/{year}", **body)
            self.assertEqual(r.status_code, 400, (year, body, r.get_data(as_text=True)))
            self.assertEqual(r.headers["Content-Type"], "application/problem+json")
        self.assertEqual(db.YearlyReportRound.select().count(), 0)
        self.assertEqual(self.api("PUT", "/rundor/2025").status_code, 200)
        self.assertEqual(self.api("PUT", "/rundor/2027").status_code, 200)

    def test_legacy_round_without_deadline(self):
        legacy = db.YearlyReportRound.create(
            report_year=2025,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            is_active=True,
            created_by=self.admin,
        )
        self.login("hjalp")  # helpers read the rounds
        r = self.api("GET", "/rundor")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        legacy_json = {
            "year": 2025,
            "start_date": "2026-01-01",
            "deadline": None,
            "end_date": "2026-03-31",
            "is_active": False,  # no genebank activated it (P5), whatever legacy's column says
            "genebanks": [],
        }
        self.assertEqual(r.json, {"rounds": [legacy_json]})

        self.login("man")
        r = self.api("PUT", "/rundor/2025")
        self.assertEqual(r.json, {**legacy_json, "deadline": "2026-01-31"})
        self.assertTrue(db.YearlyReportRound.get_by_id(legacy.id).is_active)  # legacy's column is never written

    def test_owner_cannot_manage_rounds(self):
        self.round(2026, activate=())
        self.login("owner")
        self.assertEqual(self.api("GET", "/rundor").status_code, 403)
        self.assertEqual(self.api("PUT", "/rundor/2026").status_code, 403)
        self.assertEqual(self.api("POST", f"/rundor/2026/genbanker/{self.gotland.id}/aktivera").status_code, 403)

    def test_activate_per_genebank(self):
        round_ = self.round(2026, activate=())
        self.login("man")
        first = self.api("POST", f"/rundor/2026/genbanker/{self.gotland.id}/aktivera")
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        self.assertTrue(first.json["is_active"])
        [gotland] = first.json["genebanks"]
        self.assertEqual(gotland["genebank_id"], self.gotland.id)
        self.assertEqual(gotland["activated_by"]["id"], self.manager.id)
        self.assertEqual(gotland["activated_by"]["name"], inbox.person_names([self.manager.id])[self.manager.id])
        self.assertEqual((gotland["send_at"], gotland["sent_at"]), ("2026-12-31", None))  # the round's start

        again = self.api("POST", f"/rundor/2026/genbanker/{self.gotland.id}/aktivera", send_at="2026-12-20")
        self.assertEqual((again.status_code, again.json), (200, first.json))  # the same row, unchanged
        self.assertEqual(db.YearlyReportRoundGenebank.select().count(), 1)

        r = self.api("POST", f"/rundor/2026/genbanker/{self.mellerud.id}/aktivera")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(db.YearlyReportRound.get_by_id(round_.id).is_active)  # legacy's column (D3)
        self.assertFalse(
            db.YearlyReportRoundGenebank.select().where(db.YearlyReportRoundGenebank.genebank == self.mellerud).exists()
        )

        self.login("hjalp")
        r = self.api("POST", f"/rundor/2026/genbanker/{self.gotland.id}/aktivera")
        self.assertEqual(r.status_code, 403)

    def test_activate_send_at_and_unknown(self):
        self.round(2026, activate=())
        self.login("admin")
        r = self.api("POST", f"/rundor/2026/genbanker/{self.mellerud.id}/aktivera", send_at="2026-12-20")
        self.assertEqual(r.json["genebanks"][0]["send_at"], "2026-12-20")
        r = self.api("POST", f"/rundor/2026/genbanker/{self.gotland.id}/aktivera", send_at="x")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.api("POST", f"/rundor/2027/genbanker/{self.gotland.id}/aktivera").status_code, 404)
        self.assertEqual(self.api("POST", "/rundor/2026/genbanker/999/aktivera").status_code, 404)

    def test_round_open(self):
        round_ = self.round(2025)
        is_open = arsrapport.round_open
        self.assertFalse(is_open(round_, self.gotland.id, date(2025, 12, 30)))
        self.assertTrue(is_open(round_, self.gotland.id, date(2025, 12, 31)))
        self.assertTrue(is_open(round_, self.gotland.id, date(2026, 3, 30)))
        self.assertFalse(is_open(round_, self.gotland.id, date(2026, 3, 31)))
        self.assertFalse(is_open(round_, self.mellerud.id, date(2026, 1, 15)))  # not activated

        legacy = db.YearlyReportRound.create(report_year=2024, created_by=self.admin)  # no dates at all
        arsrapport.activate(legacy, self.gotland.id, self.admin)
        self.assertFalse(is_open(legacy, self.gotland.id, date(2025, 1, 15)))

        # Today is Stockholm's: 23:30 UTC on 30 December is already 31 December there.
        self.at(datetime(2025, 12, 30, 23, 30, tzinfo=timezone.utc))
        self.assertEqual(arsrapport.today(), date(2025, 12, 31))

    def form(self, user, herd=0, sender=None):
        """An upload with an arsblankett document for self.herds[herd], taken by `user`."""
        item = self.item(herd, sender=sender)
        db.InboxDocument.update(doc_type="arsblankett").where(db.InboxDocument.item == item.id).execute()
        inbox.take(item, user, over=False)
        return item

    def test_report_access_matrix(self):
        herd = self.herds[0]  # G1, Gotland
        owner = self.user("agare")
        main = self.main_member(herd)
        main.user = owner
        main.save()
        caretaker = self.user("skotare")
        person = db.Member.create(
            first_name="Test", last_name="Skötare", membership=main.membership, role="skotare", user=caretaker
        )
        db.HerdAccessGrant.create(member=person, herd=herd, granted_by=self.admin)
        mellerud_manager = self.user("mman", ("manager", self.mellerud.id))
        nobody = self.user("ingen")  # is_manager and is_helper are None

        def role(user, item_id=None, of=herd):
            access = arsrapport.report_access(user, of, item_id)
            return access and access.role

        for user, expected in (
            (owner, "owner"),
            (caretaker, "caretaker"),
            (self.manager, "manager"),
            (mellerud_manager, None),
            (self.admin, "admin"),
            (self.helper, None),  # a helper reports only on paper
            (nobody, None),
        ):
            self.assertEqual(role(user), expected, user.username)
        self.assertEqual(arsrapport.report_access(owner, herd).source, "login")
        self.assertTrue(arsrapport.report_access(owner, herd).can_sell)
        self.assertFalse(arsrapport.report_access(caretaker, herd).can_sell)
        self.assertTrue(arsrapport.report_access(self.manager, herd).editor)
        self.assertFalse(arsrapport.report_access(owner, herd).editor)

        # On paper: the caller's taken item for the herd, with an arsblankett document.
        item = self.form(self.helper)
        access = arsrapport.report_access(self.helper, herd, item.id)
        self.assertEqual((access.role, access.source, access.item.id), ("helper", "paper", item.id))
        self.assertFalse(access.editor)
        self.assertEqual(role(self.manager, self.form(self.manager).id), "manager")
        self.assertEqual(role(self.admin, self.form(self.admin).id), "admin")

        self.assertIsNone(role(self.helper, self.form(self.manager).id))  # taken by someone else
        self.assertIsNone(role(self.helper, self.form(self.helper, herd=1).id))  # another herd's item
        intyg = self.item(0)
        inbox.take(intyg, self.helper, over=False)
        self.assertIsNone(role(self.helper, intyg.id))  # no arsblankett document
        waiting = self.form(self.helper)
        db.InboxItem.update(state="vantar_uppfodare").where(db.InboxItem.id == waiting.id).execute()
        self.assertIsNone(role(self.helper, waiting.id))  # not "tagen"
        elsewhere = self.form(self.helper)
        db.InboxItem.update(ref_type="kontroll", ref_id=1).where(db.InboxItem.id == elsewhere.id).execute()
        self.assertIsNone(role(self.helper, elsewhere.id))  # decided in another feature
        self.assertIsNone(role(self.mellerud_helper, self.form(self.mellerud_helper).id))  # another genebank
        self.assertIsNone(role(nobody, self.form(nobody).id))
        self.assertIsNone(role(self.helper, 999999))

        # A helper's own upload is decided by someone else (P24), as take and InboxGrant say; a manager decides his.
        own = self.item(0, sender=self.helper)
        db.InboxDocument.update(doc_type="arsblankett").where(db.InboxDocument.item == own.id).execute()
        db.InboxItem.update(state="tagen", assigned_to=self.helper).where(db.InboxItem.id == own.id).execute()
        self.assertTrue(inbox.own_upload(db.InboxItem.get_by_id(own.id), self.helper))
        self.assertIsNone(role(self.helper, own.id))
        self.assertEqual(role(self.manager, self.form(self.manager, sender=self.manager).id), "manager")

        gx1 = db.Herd.create(genebank=self.gotland, herd="GX1")
        self.assertIsNone(role(self.admin, of=gx1))
