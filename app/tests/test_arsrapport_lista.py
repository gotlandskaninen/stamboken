#!/usr/bin/env python3
"""
Tests for the yearly report's list (spec 5.2), the report view and the server draft.

isort:skip_file
"""

import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.inbox as inbox
from herdbook import APP

from tests.arsrapport_fixtures import ArsrapportTest
from tests.ht_helpers import _void, ht_row

FIRST_SUBMIT = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)


class ListaTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        self.at(date(2026, 1, 15))
        self.round_ = self.round(2025)
        self.g1, self.g2 = self.herds[0], self.herds[1]

    def submitted(self, revision=1, rabbits=(), ops=(), at=FIRST_SUBMIT):
        """A submitted report for G1 2025 with one submission of `rabbits` that wrote `ops`."""
        report = db.YearlyHerdReport.create(
            herd=self.g1,
            round=self.round_,
            report_date=at.date(),
            data="{}",
            status="submitted",
            source="login",
            revision=revision,
            received_at=at,
        )
        db.YearlyReportSubmission.create(
            report=report,
            submission_key=uuid.uuid4(),
            created_at=at,
            source="login",
            user=self.owner,
            operation_ids=[str(op) for op in ops],
            data={"rabbits": {str(ind.id): {"val": "kvar"} for ind in rabbits}},
            request_hash="test",
        )
        return report

    def listed(self, report=None):
        return {row["number"]: row for row in arsrapport.report_list(self.g1, 2025, report)}

    def view(self, herd="G1", year=2025, post=None):
        query = f"?post={post}" if post is not None else ""
        return self.api("GET", f"/besattning/{herd}/{year}{query}")

    def put_draft(self, data=None, updated_at=None, submission_key=None, revision=None, client=None):
        body = {
            "data": {"rabbits": {}, "message": "hej"} if data is None else data,
            "updated_at": updated_at,
            "submission_key": submission_key,
            "revision": revision,
        }
        return (client or self.client).put("/api/v2/arsrapport/besattning/G1/2025/utkast", json=body)

    # The list (5.2)

    def test_list_rule(self):
        # one rabbit per case, in one herd
        no_cert, held_g2, dead_before, dead_after, by_note, attested, moved, corrected = self.rabbits(self.g1, 8)
        db.Individual.update(certificate="").where(db.Individual.id == no_cert.id).execute()
        ht_row("TRANSFER", from_herd=self.g1, herd=self.g2, individual=held_g2, herd_tracking_date=date(2025, 11, 1))
        db.Individual.update(death_date=date(2025, 10, 1)).where(db.Individual.id == dead_before.id).execute()
        db.Individual.update(death_date=date(2026, 1, 5)).where(db.Individual.id == dead_after.id).execute()
        db.Individual.update(death_note="2025 slakt").where(db.Individual.id == by_note.id).execute()
        ht_row("ATTESTATION", herd=self.g1, individual=attested, herd_tracking_date=date(2025, 12, 31))
        ht_row("TRANSFER", from_herd=self.g1, herd=self.g2, individual=moved, herd_tracking_date=date(2026, 1, 3))
        ht_row("CORRECTION", herd=self.g2, individual=corrected, herd_tracking_date=date(2026, 1, 3))

        rows = self.listed()
        self.assertEqual(
            {number: (row["state"], row["later"]) for number, row in rows.items()},
            {
                "G1-2111": ("att_valja", None),  # DatabaseTest's certified rabbit born in G1
                dead_after.number: ("att_valja", None),
                attested.number: ("redan_rapporterad", None),
                moved.number: ("via_flytt", {"kind": "TRANSFER", "date": "2026-01-03"}),
                corrected.number: ("att_valja", None),  # a CORRECTION is not a life sign
            },
        )
        self.assertEqual(list(rows), sorted(rows))  # sorted on number
        self.assertEqual(rows[attested.number]["last_reported"], "2025-12-31")
        self.assertIsNone(rows[moved.number]["last_reported"])
        row = rows[dead_after.number]
        self.assertEqual(
            {key: row[key] for key in ("id", "sex", "color", "birth_date", "castrated", "adult", "death_date")},
            {
                "id": dead_after.id,
                "sex": "male",
                "color": None,
                "birth_date": "2024-05-01",
                "castrated": False,
                "adult": True,
                "death_date": "2026-01-05",
            },
        )
        self.assertEqual(rows["G1-2111"]["color"], "bleighe")

    def test_report_own_writes_keep_the_rabbit(self):
        # D3b: the report's own attestation, December sale, earlier death and January sale do not hide the rabbit.
        own_att, own_dec_sale, own_death, own_jan_sale, other_jan_sale = self.rabbits(self.g1, 5)
        ops = [uuid.uuid4() for _ in range(3)]
        ht_row(
            "ATTESTATION", herd=self.g1, individual=own_att, herd_tracking_date=date(2025, 12, 31), operation_id=ops[0]
        )
        ht_row(
            "TRANSFER",
            from_herd=self.g1,
            herd=self.g2,
            individual=own_dec_sale,
            herd_tracking_date=date(2025, 12, 10),
            operation_id=ops[1],
        )
        db.Individual.update(death_date=date(2025, 11, 1)).where(db.Individual.id == own_death.id).execute()
        ht_row(
            "TRANSFER",
            from_herd=self.g1,
            herd=self.g2,
            individual=own_jan_sale,
            herd_tracking_date=date(2026, 1, 5),
            operation_id=ops[2],
        )
        ht_row(
            "TRANSFER", from_herd=self.g1, herd=self.g2, individual=other_jan_sale, herd_tracking_date=date(2026, 1, 5)
        )
        report = self.submitted(rabbits=(own_att, own_dec_sale, own_death, own_jan_sale), ops=ops)

        self.assertEqual(arsrapport.report_ops(report), {str(op) for op in ops})
        self.assertEqual(arsrapport.current_report(self.g1, self.round_).id, report.id)
        rows = self.listed(report)
        states = {number: row["state"] for number, row in rows.items()}
        self.assertEqual(
            states,
            {
                "G1-2111": "att_valja",
                own_att.number: "att_valja",
                own_dec_sale.number: "att_valja",
                own_death.number: "att_valja",
                own_jan_sale.number: "att_valja",
                other_jan_sale.number: "via_flytt",
            },
        )
        self.assertIsNone(rows[own_death.number]["death_date"])  # the death is before 31/12, not a later one

        without = {number: row["state"] for number, row in self.listed().items()}
        self.assertEqual(without[own_att.number], "redan_rapporterad")
        self.assertEqual(without[own_jan_sale.number], "via_flytt")
        self.assertNotIn(own_dec_sale.number, without)
        self.assertNotIn(own_death.number, without)

    def test_castrated_is_listed_and_marked(self):
        early, eunuch, later = self.rabbits(self.g1, 3, sexes=("male",))
        db.Individual.update(castration_date=date(2025, 6, 1)).where(db.Individual.id == early.id).execute()
        db.Individual.update(sex="eunuch").where(db.Individual.id == eunuch.id).execute()
        db.Individual.update(castration_date=date(2026, 1, 2)).where(db.Individual.id == later.id).execute()
        rows = self.listed()
        self.assertEqual(
            [rows[ind.number]["castrated"] for ind in (early, eunuch, later)],
            [True, True, False],
        )
        self.assertEqual(rows[eunuch.number]["sex"], "eunuch")

    def test_rabbit_without_litter_is_listed_as_adult(self):
        # Review Focus 3
        lone = db.Individual.create(origin_herd=self.g1, number="G1-9001", certificate="C-G1-9001", sex="female")
        ht_row("TRANSFER", herd=self.g1, individual=lone, herd_tracking_date=date(2023, 5, 1))
        [young] = self.rabbits(self.g1, 1, born=date(2025, 1, 1))
        [old] = self.rabbits(self.g1, 1, born=date(2024, 12, 31))
        rows = self.listed()
        row = rows["G1-9001"]
        assert row["adult"] is True and row["birth_date"] is None
        self.assertFalse(rows[young.number]["adult"])
        self.assertTrue(rows[old.number]["adult"])

    # The view

    def test_view_access_and_lookup(self):
        self.user("ingen")
        self.login("ingen")
        self.assertEqual(self.view().status_code, 403)
        self.login("owner")
        self.assertEqual(self.view("G9").status_code, 404)
        self.assertEqual(self.view(year=2024).status_code, 404)  # no round
        db.Herd.create(genebank=self.gotland, herd="GX1")
        self.assertEqual(self.view("GX1").status_code, 404)
        self.assertEqual(self.view(post="x").status_code, 400)

        r = self.view()
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        view = r.json
        self.assertEqual(
            view["herd"],
            {
                "id": self.g1.id,
                "herd": "G1",
                "name": "Gotlandsherd1",
                "genebank_id": self.gotland.id,
                "genebank": "Gotland",
            },
        )
        self.assertEqual(view["year"], 2025)
        self.assertEqual(
            view["round"],
            {
                "start_date": "2025-12-31",
                "deadline": "2026-01-31",
                "end_date": "2026-03-30",
                "activated": True,
                "open": True,
            },
        )
        self.assertEqual((view["access"], view["source"], view["can_sell"]), ("owner", "login", True))
        self.assertEqual((view["report"], view["draft"], view["item"]), (None, None, None))
        self.assertEqual([row["number"] for row in view["rabbits"]], ["G1-2111"])

        # A helper reads it only on paper, through the taken item; the item shows the account's last two digits.
        db.Herd.update(bank_account_number="1234-567 8912").where(db.Herd.id == self.g1.id).execute()
        item = self.item(0)
        db.InboxDocument.update(doc_type="arsblankett").where(db.InboxDocument.item == item.id).execute()
        inbox.take(item, self.helper, over=False)
        self.login("hjalp")
        self.assertEqual(self.view().status_code, 403)
        r = self.view(post=item.id)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual((r.json["access"], r.json["source"], r.json["can_sell"]), ("helper", "paper", True))
        self.assertEqual(r.json["item"]["id"], item.id)
        self.assertEqual((r.json["item"]["state"], r.json["item"]["account_end"]), ("tagen", "12"))
        self.assertEqual(self.view(post=item.id + 1000).status_code, 403)

    def test_view_shows_litters_and_sales_of_the_year(self):
        db.Herd.update(is_active=True).where(db.Herd.id.in_([self.g1.id, self.g2.id])).execute()
        db.Herd.create(genebank=self.gotland, herd="G9", is_active=False)
        gx1 = db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        db.Herd.create(genebank=self.mellerud, herd="M9", is_active=True)
        kits = self.rabbits(self.g1, 4, born=date(2025, 5, 1))
        litter = kits[0].breeding
        db.Breeding.update(mother=self.individuals[0], litter_number=3).where(db.Breeding.id == litter.id).execute()
        self.rabbits(self.g1, 1, born=date(2024, 6, 1))  # last year's litter
        self.rabbits(self.g2, 1, born=date(2025, 6, 1))  # another herd's litter
        ht_row("TRANSFER", from_herd=self.g1, herd=self.g2, individual=kits[0], herd_tracking_date=date(2025, 8, 1))
        ht_row("TRANSFER", from_herd=self.g1, herd=gx1, individual=kits[1], herd_tracking_date=date(2025, 9, 1))
        ht_row("TRANSFER", from_herd=self.g1, herd=self.g2, individual=kits[2], herd_tracking_date=date(2026, 1, 3))
        voided = ht_row(
            "TRANSFER", from_herd=self.g1, herd=self.g2, individual=kits[3], herd_tracking_date=date(2025, 10, 1)
        )
        _void(voided, self.manager)

        self.login("owner")
        view = self.view().json
        self.assertEqual(
            view["litters"],
            [
                {
                    "id": litter.id,
                    "litter_number": 3,
                    "birth_date": "2025-05-01",
                    "mother": "G1-2111",
                    "father": None,
                    "litter_size": 4,
                    "litter_size6w": 4,
                }
            ],
        )
        self.assertEqual(
            view["sales"],
            [
                {"individual_id": kits[0].id, "number": kits[0].number, "to_herd": "G2", "date": "2025-08-01"},
                {"individual_id": kits[1].id, "number": kits[1].number, "to_herd": "GX1", "date": "2025-09-01"},
            ],
        )
        self.assertEqual(view["herds"], ["G2"])  # active, in the genebank, not G1 itself and not GX1

    def test_registered_later_death_is_shown(self):
        [rabbit] = self.rabbits(self.g1, 1)
        db.Individual.update(death_date=date(2026, 1, 5)).where(db.Individual.id == rabbit.id).execute()
        self.login("owner")
        [row] = [row for row in self.view().json["rabbits"] if row["id"] == rabbit.id]
        self.assertEqual((row["death_date"], row["state"]), ("2026-01-05", "att_valja"))

    def test_other_active_herd(self):
        self.main_member(self.g1)
        self.login("owner")
        self.assertFalse(self.view().json["other_active_herd"])  # holds only G1
        db.Herd.update(membership=self.g1.membership, is_active=True).where(db.Herd.id == self.g2.id).execute()
        self.assertTrue(self.view().json["other_active_herd"])
        db.Herd.update(is_active=False).where(db.Herd.id == self.g2.id).execute()
        self.assertFalse(self.view().json["other_active_herd"])

    def test_owner_after_end_date_reads_only(self):
        # fråga 16
        self.submitted()
        self.login("owner")
        report = self.view().json["report"]
        self.assertEqual(report["status"], "submitted")
        self.assertEqual((report["revision"], report["source"], report["on_time"]), (1, "login", True))
        self.assertEqual(report["submitted"], {"rabbits": {}})
        self.assertEqual((report["can_change"], report["can_withdraw"]), (True, True))
        until = datetime.fromisoformat(report["withdraw_until"])
        self.assertEqual(until, FIRST_SUBMIT + timedelta(days=7))

        self.at(until + timedelta(seconds=1))
        report = self.view().json["report"]
        self.assertEqual((report["can_change"], report["can_withdraw"]), (True, False))

        self.at(date(2026, 3, 31))  # the day after end_date
        view = self.view().json
        self.assertFalse(view["round"]["open"])
        self.assertEqual((view["report"]["can_change"], view["report"]["can_withdraw"]), (False, False))

        self.login("man")
        report = self.view().json["report"]
        self.assertEqual((report["can_change"], report["can_withdraw"], report["withdraw_until"]), (True, True, None))

    # The draft

    def test_draft_version_conflict(self):
        self.login("owner")
        key = str(uuid.uuid4())
        first = self.put_draft(submission_key=key)
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        self.assertEqual(first.json["submission_key"], key)
        second = self.put_draft({"message": "två"}, updated_at=first.json["updated_at"], submission_key=key)
        self.assertEqual(second.status_code, 200, second.get_data(as_text=True))
        self.assertNotEqual(second.json["updated_at"], first.json["updated_at"])  # even on a frozen clock

        stale = self.put_draft({"message": "tre"}, updated_at=first.json["updated_at"], submission_key=key)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json["detail"], "Rapporten har ändrats på en annan enhet.")
        current = {"data": {"message": "två"}, "updated_at": second.json["updated_at"], "submission_key": key}
        self.assertEqual(stale.json["draft"], {**current, "own": True})
        self.assertEqual(self.put_draft().status_code, 409)  # a first save over an existing draft

        self.assertEqual(self.view().json["draft"], {**current, "own": True})
        self.login("man")
        self.assertEqual(self.view().json["draft"], {**current, "own": False})  # P59b

    def test_concurrent_first_drafts(self):
        clients = []
        for _ in range(2):
            client = APP.test_client(use_cookies=True)
            client.post("/api/login", json={"username": "owner", "password": "pass"})
            clients.append(client)
        barrier = threading.Barrier(2)
        statuses = []

        def put(client):
            try:
                barrier.wait(timeout=10)
                statuses.append(self.put_draft(client=client).status_code)
            finally:
                db.DB_PROXY.close()

        threads = [threading.Thread(target=put, args=(client,)) for client in clients]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(db.YearlyReportDraft.select().count(), 1)

        # The UNIQUE index behind the lock: a first save that read no draft but meets one is the same 409.
        existing = db.YearlyReportDraft.get()
        self.login("owner")
        with (
            mock.patch.object(arsrapport, "lock_report"),
            mock.patch.object(arsrapport, "_draft", side_effect=[None, existing]),
        ):
            r = self.put_draft()
        self.assertEqual(r.status_code, 409, r.get_data(as_text=True))
        self.assertEqual(r.json["draft"]["updated_at"], existing.updated_at.isoformat())

    def test_late_autosave_after_submit_is_refused(self):
        # Review Focus 4
        self.submitted(revision=1)
        self.login("owner")
        for r in (
            self.put_draft(updated_at=FIRST_SUBMIT.isoformat()),
            self.put_draft(updated_at=None, revision=None),
        ):
            self.assertEqual(r.status_code, 409, r.get_data(as_text=True))
            self.assertEqual((r.json["detail"], r.json["draft"]), ("Rapporten är redan inskickad.", None))
        self.assertEqual(self.put_draft(revision=2).status_code, 409)
        r = self.put_draft(revision=1)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(db.YearlyReportDraft.select().count(), 1)

    def test_draft_refuses_matrikel_and_kopare(self):
        self.login("owner")
        [rabbit] = self.rabbits(self.g1, 1)
        sold = dict([self.sald(rabbit, "utanfor", 2025, 6, kopare={"namn": "Test Köpare", "ort": "Visby"})])
        for data in (
            {"matrikel": {"telefon": "0700000000"}},
            {"rabbits": sold},
            ["inte", "ett", "objekt"],
            {"message": "x" * (256 * 1024)},
        ):
            r = self.put_draft(data)
            self.assertEqual(r.status_code, 400, (data if len(str(data)) < 200 else "big", r.get_data(as_text=True)))
        for body in ({"revision": True}, {"submission_key": "nej"}, {"updated_at": "igår"}):
            r = self.put_draft(**body)
            self.assertEqual(r.status_code, 400, (body, r.get_data(as_text=True)))
        self.assertEqual(db.YearlyReportDraft.select().count(), 0)

        body = self.body(self.sald(rabbit, "utanfor", 2025, 6), self.dod(self.individuals[0], 2025, 3), matrikel=None)
        r = self.put_draft(body, submission_key=body["submission_key"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        data = db.YearlyReportDraft.get().data
        self.assertEqual(data, arsrapport.stored_body(body))
        for key in ("matrikel", "submission_key", "revision"):
            self.assertNotIn(key, data)
        self.assertNotIn("kopare", data["rabbits"][str(rabbit.id)]["sald"])
        self.assertIn("kopare", body["rabbits"][str(rabbit.id)]["sald"])  # stored_body copies, never mutates

    # Mina

    def test_my_reports(self):
        self.login("owner")
        r = self.api("GET", "/mina")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        expected = {
            "herd": "G1",
            "year": 2025,
            "open": True,
            "status": None,
            "deadline": "2026-01-31",
            "end_date": "2026-03-30",
        }
        self.assertEqual(r.json, {"reports": [expected]})
        self.submitted()
        self.assertEqual(self.api("GET", "/mina").json, {"reports": [{**expected, "status": "submitted"}]})

        self.user("m3agare", ("owner", self.herds[2].id))  # Mellerud has not activated the round
        self.login("m3agare")
        self.assertEqual(self.api("GET", "/mina").json, {"reports": []})
