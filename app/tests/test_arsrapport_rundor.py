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

    def test_activation_waits_for_the_running_round(self):
        """#264: a genebank activates next year's round only once its running round has closed."""
        self.round(2026)  # activated for Gotland, open 2026-12-31 to 2027-03-30
        self.at(date(2027, 1, 15))
        self.round(2027, activate=())
        self.login("admin")
        r = self.api("POST", f"/rundor/2027/genbanker/{self.gotland.id}/aktivera")
        self.assertEqual(r.status_code, 409, r.get_data(as_text=True))
        self.assertIn("Rundan 2026 är aktiverad för genbanken och stänger 30 mars 2027", r.json["detail"])
        # The running round itself again, and another genebank, are not refused.
        self.assertEqual(self.api("POST", f"/rundor/2026/genbanker/{self.gotland.id}/aktivera").status_code, 200)
        self.assertEqual(self.api("POST", f"/rundor/2027/genbanker/{self.mellerud.id}/aktivera").status_code, 200)

        self.at(date(2027, 3, 30))  # its last day
        self.assertEqual(self.api("POST", f"/rundor/2027/genbanker/{self.gotland.id}/aktivera").status_code, 409)
        self.at(date(2027, 3, 31))
        self.assertEqual(self.api("POST", f"/rundor/2027/genbanker/{self.gotland.id}/aktivera").status_code, 200)

    def test_activation_reads_the_dates_under_its_lock(self):
        """A round object read before a save_round moved its start still schedules the invitations on the new day."""
        stale = self.round(2026, activate=())
        arsrapport.save_round(2026, self.admin, start_date=date(2027, 1, 5))
        activation = arsrapport.activate(stale, self.gotland.id, self.admin)
        self.assertEqual(activation.send_at, date(2027, 1, 5))

    def test_an_older_round_is_not_activated_after_a_newer_one(self):
        self.round(2026, activate=())
        self.round(2027, activate=("Mellerudskanin",))
        self.at(date(2027, 1, 15))
        self.login("admin")
        r = self.api("POST", f"/rundor/2026/genbanker/{self.mellerud.id}/aktivera")
        self.assertEqual(r.status_code, 409, r.get_data(as_text=True))
        self.assertIn("Rundan 2027 är redan aktiverad för genbanken, så en äldre runda kan inte", r.json["detail"])

    def test_activation_ignores_a_round_without_both_dates(self):
        self.at(date(2026, 11, 15))
        for dates in ({}, {"end_date": date(2027, 3, 1)}, {"start_date": date(2026, 1, 1)}):  # never open
            legacy = db.YearlyReportRound.create(report_year=2024, created_by=self.admin, **dates)
            arsrapport.activate(legacy, self.gotland.id, self.admin)
            arsrapport.activate(self.round(2026, activate=()), self.gotland.id, self.admin)
            self.assertEqual(db.YearlyReportRoundGenebank.select().count(), 2, dates)
            db.YearlyReportRoundGenebank.delete().execute()
            db.YearlyReportRound.delete().execute()

    def test_a_closed_round_is_not_reopened_after_the_next_is_activated(self):
        self.round(2026)
        self.at(date(2027, 4, 1))
        self.round(2027)
        self.login("man")
        r = self.api("PUT", "/rundor/2026", end_date="2027-06-30")
        self.assertEqual(r.status_code, 409, r.get_data(as_text=True))
        self.assertIn("Rundan 2027 är aktiverad för genbanken, så rundan 2026 kan inte", r.json["detail"])
        self.assertEqual(arsrapport.get_round(2026).end_date, date(2027, 3, 30))
        # Its other dates still move, as long as it stays closed.
        self.assertEqual(self.api("PUT", "/rundor/2026", deadline="2027-02-01").status_code, 200)

    def test_rounds_cannot_overlap(self):
        """#264: no two rounds share a day, neighbours or not."""
        db.YearlyReportRound.create(
            report_year=2025,
            start_date=date(2025, 12, 31),
            deadline=date(2026, 1, 31),
            end_date=date(2027, 1, 10),  # moved past the next round's default start
            created_by=self.admin,
        )
        self.login("man")
        r = self.api("PUT", "/rundor/2026")
        self.assertEqual(r.status_code, 400, r.get_data(as_text=True))
        self.assertIn("överlappa rundan 2025 (31 december 2025 – 10 januari 2027)", r.json["detail"])
        self.assertIsNone(arsrapport.get_round(2026))

        self.assertEqual(self.api("PUT", "/rundor/2026", start_date="2027-01-11").status_code, 200)
        r = self.api("PUT", "/rundor/2025", end_date="2027-01-11")  # back into the round now after it
        self.assertEqual(r.status_code, 400, r.get_data(as_text=True))
        self.assertEqual(self.api("PUT", "/rundor/2025", end_date="2027-01-10").status_code, 200)

    def test_rounds_two_years_apart_cannot_overlap(self):
        db.YearlyReportRound.create(
            report_year=2027,
            start_date=date(2027, 1, 1),
            deadline=date(2027, 1, 31),
            end_date=date(2027, 3, 30),
            created_by=self.admin,
        )
        self.round(2025, activate=())
        self.login("man")
        r = self.api("PUT", "/rundor/2025", end_date="2027-01-10")
        self.assertEqual(r.status_code, 400, r.get_data(as_text=True))
        self.assertIn("överlappa rundan 2027", r.json["detail"])

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
        with self.assertRaises(inbox.InboxError):  # another genebank: the queue refuses the take itself (7145d2e)
            self.form(self.mellerud_helper)
        with self.assertRaises(inbox.InboxError):  # no genebank role: the take itself is refused
            self.form(nobody)
        self.assertIsNone(role(self.helper, 999999))

        # A helper decides her own upload, as a manager decides his (Jonas 2026-11-15, the queue's 49e666b).
        own = self.item(0, sender=self.helper)
        db.InboxDocument.update(doc_type="arsblankett").where(db.InboxDocument.item == own.id).execute()
        db.InboxItem.update(state="tagen", assigned_to=self.helper).where(db.InboxItem.id == own.id).execute()
        self.assertEqual(role(self.helper, own.id), "helper")
        self.assertEqual(role(self.manager, self.form(self.manager, sender=self.manager).id), "manager")

        gx1 = db.Herd.create(genebank=self.gotland, herd="GX1")
        self.assertIsNone(role(self.admin, of=gx1))
