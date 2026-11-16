#!/usr/bin/env python3
"""
Tests for the yearly report's first submission (POST …/skicka): the writes per rabbit, the key and its request hash,
the locks under concurrency, the fixed receipt and the receipt mail. Synthetic herds, rabbits and buyers only.

isort:skip_file
"""

import json
import os
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from datetime import time as clock
from unittest import mock

import pytest
import utils.arsrapport as arsrapport
import utils.database as db
import utils.mail as mail
from herdbook import APP
from utils.arsrapport_statistik import innehav
from utils.database import coerce_date
from utils.herd_tracking import DATE_BEFORE_LATEST, HerdTrackingConflict
from utils.individual_commands import IndividualRefused, RecordDeath, execute

from tests.arsrapport_fixtures import ArsrapportTest
from tests.ht_helpers import count_queries, ht_row

LAST = date(2025, 12, 31)
NOW = datetime.combine(date(2026, 1, 15), clock(12), arsrapport.STOCKHOLM)
BUYER = {"name": "Test Köpare", "town": "Visby"}
KEY_TAKEN = "Rapporten är redan skickad med den här nyckeln. Ladda om sidan."
WRITTEN = (
    db.HerdTracking,
    db.IndividualCommand,
    db.Weight,
    db.Bodyfat,
    db.BuyerContact,
    db.YearlyHerdReport,
    db.YearlyReportSubmission,
    db.MailMessage,
)


def attestation(ind):
    return db.HerdTracking.get(db.HerdTracking.individual == ind.id, db.HerdTracking.kind == "ATTESTATION")


def held(genebank, herd):
    return {kanin.individual_id for kanin in innehav(genebank.id, 2025).get(herd.id, [])}


class InskickTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        self.at(NOW)
        self.round_ = self.round(2025)
        self.h = db.Herd.create(genebank=self.gotland, herd="G9001", herd_name="Testbesättning", is_active=True)
        self.g9002 = db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.owner.add_role("owner", self.h.id)
        self.member = self.main_member(self.h, "g9001@example.invalid")
        self.login("owner")

    def herd(self, code):
        """Another herd of the owner's in Gotland."""
        herd = db.Herd.create(genebank=self.gotland, herd=code, is_active=True)
        self.owner.add_role("owner", herd.id)
        return herd

    def skicka(self, body, herd="G9001", client=None):
        return (client or self.client).post(f"/api/v2/arsrapport/besattning/{herd}/2025/skicka", json=body)

    def ok(self, body, herd="G9001"):
        response = self.skicka(body, herd)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def counts(self):
        return [model.select().count() for model in WRITTEN]

    def queries(self, call):
        """The SQL statements one request runs; it must answer 200."""
        with count_queries() as counter:
            response = call()
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return counter["n"]

    def kvitton(self):
        return list(db.MailMessage.select().where(db.MailMessage.kind == "arsrapport.kvitto"))

    def race(self, *requests):
        """Each (herd code, body) POSTed at once by the owner from a client and a connection of its own."""
        clients = []
        for _ in requests:
            client = APP.test_client(use_cookies=True)
            client.post("/api/login", json={"username": "owner", "password": "pass"})
            clients.append(client)
        barrier, results = threading.Barrier(len(requests)), [None] * len(requests)

        def run(i, herd, body):
            try:
                barrier.wait(timeout=10)
                response = self.skicka(body, herd, clients[i])
                results[i] = (response.status_code, response.get_json())
            finally:
                db.DB_PROXY.close()

        threads = [threading.Thread(target=run, args=(i, *request)) for i, request in enumerate(requests)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertFalse(any(thread.is_alive() for thread in threads), "hung threads")
        self.assertNotIn(None, results, "a request raised (500)")
        return results

    # The writes

    def test_kvar_writes_attestation_on_new_years_eve(self):
        (a,) = self.rabbits(self.h, 1)
        rid = self.ok(self.body(self.kvar(a, vikt=2.8)))["report_id"]
        row = attestation(a)
        self.assertEqual(
            (coerce_date(row.herd_tracking_date), row.yearly_herd_report_id, row.herd_id), (LAST, rid, self.h.id)
        )
        self.assertIn(a.id, held(self.gotland, self.h))

    def test_ending_genebank_needs_no_choices(self):  # Jonas 2026-11-15, 5.7
        a, b = self.rabbits(self.h, 2)
        refused = self.skicka(self.body(self.kvar(a, vikt=2.8)))
        self.assertEqual(refused.status_code, 422)
        self.assertEqual([r["code"] for r in refused.get_json()["refusals"]], ["inte_klar"])
        self.ok(self.body(self.kvar(a, vikt=2.8), ending_genbank=True, membership_after_end="kvar_utan_genbank"))
        self.assertIn(a.id, held(self.gotland, self.h))
        self.assertFalse(
            db.HerdTracking.select()
            .where(db.HerdTracking.individual == b.id, db.HerdTracking.kind == "ATTESTATION")
            .exists()
        )

    def test_measurements_are_added_not_replaced(self):
        a, b = self.rabbits(self.h, 2)
        june = db.Weight.create(individual=a, weight=3.1, weight_date=date(2025, 6, 1))
        db.Weight.create(individual=b, weight=2.8, weight_date=LAST)
        db.Bodyfat.create(individual=b, bodyfat="normal", bodyfat_date=LAST)
        self.ok(self.body(self.kvar(a, vikt="2,8", hull="normal"), self.kvar(b, vikt=2.8, hull="normal")))

        weights = {(coerce_date(w.weight_date), round(w.weight, 2)) for w in db.Weight.filter(individual=a)}
        self.assertEqual(weights, {(date(2025, 6, 1), 3.1), (LAST, 2.8)})
        self.assertEqual(round(db.Weight.get_by_id(june.id).weight, 2), 3.1)  # the same row, not written again
        new = db.Weight.get(db.Weight.individual == a.id, db.Weight.weight_date == LAST)
        fat = db.Bodyfat.get(db.Bodyfat.individual == a.id)
        added = sorted(db.YearlyReportSubmission.get().added_measurements, key=lambda m: m["kind"])
        self.assertEqual(
            added,
            [
                {"individual_id": a.id, "kind": "bodyfat", "id": fat.id, "date": "2025-12-31", "value": "normal"},
                {"individual_id": a.id, "kind": "weight", "id": new.id, "date": "2025-12-31", "value": 2.8},
            ],
        )
        # b had the same weight and hull on 31/12 already: nothing added
        self.assertEqual((db.Weight.filter(individual=b).count(), db.Bodyfat.filter(individual=b).count()), (1, 1))

    def test_death_and_december_sale(self):
        dead, sold = self.rabbits(self.h, 2)
        self.ok(self.body(self.dod(dead, 2025, 11, 20, slaktad=True), self.sald(sold, "G9002", 2025, 12)))

        def commands(ind):
            rows = db.IndividualCommand.select().where(db.IndividualCommand.individual == ind.id)
            return [row.command for row in rows.order_by(db.IndividualCommand.id)]

        self.assertEqual(commands(dead), ["RecordDeath"])
        self.assertEqual(commands(sold), ["TransferIndividual"])
        stored = db.Individual.get_by_id(dead.id)
        self.assertEqual((stored.death_date, stored.butchered), (date(2025, 11, 20), True))
        sale = db.HerdTracking.get(db.HerdTracking.individual == sold.id, db.HerdTracking.kind == "TRANSFER")
        self.assertEqual((sale.herd_id, coerce_date(sale.herd_tracking_date)), (self.g9002.id, LAST))
        attested = db.HerdTracking.select().where(
            db.HerdTracking.individual.in_([dead.id, sold.id]), db.HerdTracking.kind == "ATTESTATION"
        )
        self.assertFalse(attested.exists())

    def test_registered_death_is_not_overwritten(self):
        (a,) = self.rabbits(self.h, 1)
        db.Individual.update(death_date=date(2026, 1, 5)).where(db.Individual.id == a.id).execute()
        self.ok(self.body(self.dod(a, 2026, 1)))
        self.assertFalse(db.IndividualCommand.filter(individual=a, command="RecordDeath").exists())
        self.assertEqual(db.Individual.get_by_id(a.id).death_date, date(2026, 1, 5))
        self.assertEqual(coerce_date(attestation(a).herd_tracking_date), LAST)  # it lived on 31/12

    def test_sale_outside_stores_the_buyer(self):  # D1
        (a,) = self.rabbits(self.h, 1)
        self.ok(self.body(self.sald(a, "utanfor", 2025, 11, kopare=BUYER)))
        row = db.HerdTracking.get(db.HerdTracking.individual == a.id, db.HerdTracking.kind == "TRANSFER")
        self.assertEqual(row.herd.herd, "GX1")
        self.assertIsNotNone(row.holder_contact_id)
        contact = db.BuyerContact.get_by_id(row.holder_contact_id)
        self.assertEqual((contact.name, contact.town), (BUYER["name"], BUYER["town"]))
        data = json.dumps(db.YearlyReportSubmission.get().data, ensure_ascii=False)
        view = json.dumps(self.client.get("/api/v2/arsrapport/besattning/G9001/2025").get_json(), ensure_ascii=False)
        for text in (data, view):
            for secret in ("kopare", BUYER["name"], BUYER["town"]):
                self.assertNotIn(secret, text)

    def test_january_sale_is_written_after_the_attestation(self):  # case 6, logged-in owner
        (a,) = self.rabbits(self.h, 1)
        self.ok(self.body(self.sald(a, "G9002", 2026, 1, 3)))
        rows = (
            db.HerdTracking.select()
            .where(db.HerdTracking.individual == a.id, db.HerdTracking.kind.in_(["ATTESTATION", "TRANSFER"]))
            .order_by(db.HerdTracking.id)
        )
        self.assertEqual(
            [(row.kind, coerce_date(row.herd_tracking_date), row.voided_at) for row in rows],
            [("ATTESTATION", LAST, None), ("TRANSFER", date(2026, 1, 3), None)],
        )
        self.assertIn(a.id, held(self.gotland, self.h))

    def test_already_moved_rabbit_counts_via_the_move(self):  # case 6
        moved, other = self.rabbits(self.h, 2)
        ht_row("TRANSFER", from_herd=self.h, herd=self.g9002, individual=moved, herd_tracking_date=date(2026, 1, 10))
        self.ok(self.body(self.kvar(other, vikt=2.8)))
        self.assertFalse(db.HerdTracking.filter(individual=moved, kind="ATTESTATION").exists())
        self.assertEqual(held(self.gotland, self.h), {moved.id, other.id})

    # The key and the request hash

    def test_same_key_same_answer(self):  # case 3
        (a,) = self.rabbits(self.h, 1)
        body = self.body(self.kvar(a, vikt=7.2))
        first = self.ok(body)
        self.assertEqual(self.ok(body), first)
        self.assertEqual(self.ok({**body, "revision": 1}), first)  # an old tab's revision: the same request
        self.assertEqual(
            {key: first[key] for key in ("source", "summary", "matrikel", "warnings")},
            {
                "source": "login",
                "summary": {"kvar": 1, "doda": 0, "salda": 0, "vantar": 0, "ej_angivna": 0},
                "matrikel": [],
                "warnings": [{"individual_id": a.id, "code": "vikt_ovanlig", "message": "Stämmer 7,2 kg?"}],
            },
        )
        self.assertEqual(first["created_at"], NOW.astimezone(timezone.utc).isoformat())
        self.assertEqual(db.YearlyHerdReport.select().count(), 1)
        self.assertEqual(db.YearlyReportSubmission.select().count(), 1)
        self.assertEqual(len(self.kvitton()), 1)

    def test_same_key_other_body_is_409(self):  # Review Focus 2
        a, b = self.rabbits(self.h, 2)
        body = self.body(self.kvar(a, vikt=2.8), self.kvar(b, vikt=2.8))
        self.ok(body)
        before = self.counts()
        changed = {**body, "rabbits": {**body["rabbits"], **dict([self.dod(b, 2025, 11)])}}
        response = self.skicka(changed)
        self.assertEqual((response.status_code, response.get_json()["detail"]), (409, KEY_TAKEN))
        self.assertEqual(self.counts(), before)

        self.herd("G9003")
        self.assertEqual(self.skicka(body, "G9003").status_code, 409)  # another herd
        self.login("man")
        self.assertEqual(self.skicka(body).status_code, 409)  # another user
        self.login("owner")
        db.YearlyHerdReport.update(status="voided", voided_at=NOW, voided_by_user=self.owner.id).execute()
        self.assertEqual(self.skicka(body).status_code, 409)  # a voided report
        self.assertEqual(self.counts(), before)

    def test_same_key_other_buyer_is_409(self):  # D21
        (a,) = self.rabbits(self.h, 1)
        body = self.body(self.sald(a, "utanfor", 2025, 11, kopare=BUYER))
        self.ok(body)
        before = self.counts()
        other = self.body(self.sald(a, "utanfor", 2025, 11, kopare={**BUYER, "town": "Slite"}))
        response = self.skicka({**other, "submission_key": body["submission_key"]})
        self.assertEqual((response.status_code, response.get_json()["detail"]), (409, KEY_TAKEN))
        self.assertEqual(self.counts(), before)
        row = db.YearlyReportSubmission.select().dicts().get()
        self.assertRegex(row["request_hash"], r"^[0-9a-f]{64}$")
        stored = json.dumps(row, default=str, ensure_ascii=False)
        self.assertNotIn(BUYER["name"], stored)
        self.assertNotIn(BUYER["town"], stored)

    def test_concurrent_first_submissions(self):  # case 3
        (a,) = self.rabbits(self.h, 1)
        results = self.race(("G9001", self.body(self.kvar(a, vikt=2.8))), ("G9001", self.body(self.kvar(a, vikt=3.0))))
        statuses = [status for status, _ in results]
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(db.YearlyHerdReport.filter(herd=self.h).count(), 1)

        g3 = self.herd("G9003")
        (b,) = self.rabbits(g3, 1)
        body = self.body(self.kvar(b, vikt=2.8))
        (first, second) = self.race(("G9003", body), ("G9003", body))
        self.assertEqual((first[0], second[0]), (200, 200))
        self.assertEqual(first[1], second[1])
        self.assertEqual(db.YearlyReportSubmission.select().count(), 2)

        g4, g5 = self.herd("G9004"), self.herd("G9005")
        (c,), (d,) = self.rabbits(g4, 1), self.rabbits(g5, 1)
        key = str(uuid.uuid4())
        results = self.race(
            ("G9004", {**self.body(self.kvar(c, vikt=2.8)), "submission_key": key}),
            ("G9005", {**self.body(self.kvar(d, vikt=2.8)), "submission_key": key}),
        )
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        self.assertEqual(db.YearlyHerdReport.filter(db.YearlyHerdReport.herd.in_([g4.id, g5.id])).count(), 1)

    def test_key_taken_by_another_herd_meanwhile_is_409(self):  # the UNIQUE index behind find_submission
        g3 = self.herd("G9003")
        (a,), (b,) = self.rabbits(self.h, 1), self.rabbits(g3, 1)
        body = self.body(self.kvar(a, vikt=2.8))
        self.ok(body)
        before = self.counts()
        other = {**self.body(self.kvar(b, vikt=2.8)), "submission_key": body["submission_key"]}
        with mock.patch.object(arsrapport, "find_submission", return_value=None):
            response = self.skicka(other, "G9003")
        self.assertEqual((response.status_code, response.get_json()["detail"]), (409, KEY_TAKEN))
        self.assertEqual(self.counts(), before)
        self.assertFalse(db.YearlyHerdReport.filter(herd=g3).exists())

    def test_stale_revision_is_409(self):
        (a,) = self.rabbits(self.h, 1)
        self.ok(self.body(self.kvar(a, vikt=2.8)))
        before = self.counts()
        for revision in (None, 5):
            response = self.skicka(self.body(self.kvar(a, vikt=3.0), revision=revision))
            self.assertEqual((response.status_code, response.get_json()["detail"]), (409, "Rapporten har ändrats."))
        self.assertEqual(self.counts(), before)

    def test_retry_is_answered_before_the_access_check(self):  # Fable 5: the access may be gone by the retry
        (a,) = self.rabbits(self.h, 1)
        body = self.body(self.kvar(a, vikt=2.8))
        first = self.ok(body)
        with mock.patch.object(arsrapport, "report_access", return_value=None):
            self.assertEqual(self.ok(body), first)
            self.assertEqual(self.skicka({**body, "submission_key": str(uuid.uuid4())}).status_code, 403)

    def test_stored_body_keeps_only_the_chosen_branch(self):  # I1: nothing unvalidated is stored
        kept, moved = self.rabbits(self.h, 2)
        ht_row("TRANSFER", from_herd=self.h, herd=self.g9002, individual=moved, herd_tracking_date=date(2026, 1, 10))
        phone = "070-123 45 67"
        key, entry = self.kvar(kept, vikt="2,8")
        died = {"ar": 2025, "manad": 5, "dag": None, "slaktad": False, "anteckning": f"Ring {phone}"}
        sold = {"till": "utanfor", "ar": 2025, "manad": 5, "dag": None, "kopare": BUYER}
        body = self.body(
            (key, {**entry, "dod": died, "sald": sold}),  # the details of a choice not taken
            (str(moved.id), {"val": None, "dod": died}),  # no choice: nothing is stored
        )
        self.ok(body)
        data = db.YearlyReportSubmission.get().data
        self.assertEqual(
            data["rabbits"],
            {key: {"val": "kvar", "vikt": 2.8, "ej_vagd": None, "hull": None, "dod": None, "sald": None}},
        )
        view = self.client.get("/api/v2/arsrapport/besattning/G9001/2025").get_json()
        for text in (json.dumps(data, ensure_ascii=False), json.dumps(view, ensure_ascii=False)):
            for secret in (phone, BUYER["name"], "kopare"):
                self.assertNotIn(secret, text)

    def test_oversized_body_is_400(self):  # I1: the draft's cap
        (a,) = self.rabbits(self.h, 1)
        body = self.body(self.kvar(a, vikt=2.8), ("999999", {"val": None, "dod": {"anteckning": "x" * 300_000}}))
        before = self.counts()
        for path in ("torrkorning", "skicka"):
            response = self.client.post(f"/api/v2/arsrapport/besattning/G9001/2025/{path}", json=body)
            self.assertEqual((response.status_code, response.get_json()["detail"]), (400, "Rapporten är för stor."))
        self.assertEqual(self.counts(), before)

    def test_missing_key_is_400(self):
        (a,) = self.rabbits(self.h, 1)
        response = self.skicka(self.body(self.kvar(a, vikt=2.8), submission_key=None))
        self.assertEqual((response.status_code, response.get_json()["field"]), (400, "submission_key"))

    # Refusals and rollback

    def test_rabbit_changed_after_dry_run_is_refused(self):  # Review Focus 1
        a, b = self.rabbits(self.h, 2)
        body = self.body(self.kvar(a, vikt=2.8), self.kvar(b, vikt=2.8))
        dry = self.client.post("/api/v2/arsrapport/besattning/G9001/2025/torrkorning", json=body)
        self.assertTrue(dry.get_json()["ok"], dry.get_data(as_text=True))
        execute(db.User.get_by_id(self.manager.id), b.id, lambda ctx: [RecordDeath({"death_date": "2025-11-10"})])
        before = self.counts()
        response = self.skicka(body)
        self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
        self.assertIn(b.id, [refusal["individual_id"] for refusal in response.get_json()["refusals"]])
        self.assertEqual(self.counts(), before)

    def test_write_refusal_is_422_for_that_rabbit(self):  # U8's codes, as at Ändra
        a, b = self.rabbits(self.h, 2)
        real = arsrapport.execute
        later = "Kaninen har en senare händelse i Stamboken. Genbanksansvarig kan rätta."
        for refused, code, message in (
            (HerdTrackingConflict("Kaninen ändrades samtidigt. Försök igen."), "skrivning_nekad", None),
            (HerdTrackingConflict(DATE_BEFORE_LATEST), "senare_handelse", later),
            (IndividualRefused("Forbidden"), "skrivning_nekad", arsrapport.REFUSALS["skrivning_nekad"]),
        ):

            def flaky(user, individual_id, translate, refused=refused, **kwargs):
                if individual_id == b.id:
                    raise refused
                return real(user, individual_id, translate, **kwargs)

            before = self.counts()
            with mock.patch.object(arsrapport, "execute", side_effect=flaky):
                response = self.skicka(self.body(self.kvar(a, vikt=2.8), self.kvar(b, vikt=2.8)))
            self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
            self.assertEqual(
                response.get_json()["refusals"],
                [{"individual_id": b.id, "code": code, "message": message or str(refused)}],
            )
            self.assertEqual(self.counts(), before)

    def test_queries_per_rabbit(self):  # case 3: an N+1 beyond execute's own fails here, on no clock (I2)
        counts = {}
        for code, n in (("G9003", 10), ("G9004", 20)):
            herd = self.herd(code)
            body = self.body(*[self.kvar(rabbit, vikt=2.8) for rabbit in self.rabbits(herd, n)])  # adults: weights
            path = f"/api/v2/arsrapport/besattning/{code}/2025"
            counts[n] = [
                self.queries(lambda: self.client.post(f"{path}/torrkorning", json=body)),  # noqa: B023
                self.queries(lambda: self.skicka(body, code)),  # noqa: B023
                self.queries(lambda: self.client.get(path)),  # noqa: B023
            ]
        dry, sent, view = ((large - small) / 10 for small, large in zip(counts[10], counts[20], strict=True))
        # Measured 2026-11-15: 3, 56 (about 47 of them inside execute) and 0 per rabbit.
        self.assertLessEqual(dry, 4, counts)
        self.assertLessEqual(sent, 62, counts)
        self.assertEqual(view, 0, counts)

    @pytest.mark.slow
    @pytest.mark.skipif(os.environ.get("RUN_SLOW") != "1", reason="set RUN_SLOW=1 to run measurements")
    def test_183_rabbits(self):  # case 3: a third of SUBMIT_TIMEOUT_MS (30 s) and of fetchApi's default (10 s)
        body = self.body(*[self.kvar(rabbit, vikt=2.8) for rabbit in self.rabbits(self.h, 183)])

        def timed(limit, call):
            start = time.monotonic()
            response = call()
            self.assertLess(time.monotonic() - start, limit, response.request.path)
            return response

        dry = timed(10, lambda: self.client.post("/api/v2/arsrapport/besattning/G9001/2025/torrkorning", json=body))
        self.assertTrue(dry.get_json()["ok"], dry.get_data(as_text=True))
        sent = timed(10, lambda: self.skicka(body))
        self.assertEqual(sent.status_code, 200, sent.get_data(as_text=True))
        self.assertEqual(db.HerdTracking.filter(kind="ATTESTATION").count(), 183)
        view = timed(10 / 3, lambda: self.client.get("/api/v2/arsrapport/besattning/G9001/2025"))
        self.assertEqual(view.status_code, 200)

    def test_failure_after_the_first_rabbit_rolls_back(self):  # Codex 15
        a, b = self.rabbits(self.h, 2)
        key, sold = self.sald(a, "utanfor", 2026, 1, 3, kopare=BUYER)
        body = self.body((key, {**sold, "vikt": 2.8}), self.kvar(b, vikt=2.8))  # a: weight, attestation, sale, buyer
        saved = self.api(
            "PUT",
            "/besattning/G9001/2025/utkast",
            data=arsrapport.stored_body(body),
            updated_at=None,
            submission_key=body["submission_key"],
            revision=None,
        )
        self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
        draft = db.YearlyReportDraft.get()
        real, seen = arsrapport.execute, []

        def flaky(user, individual_id, translate, **kwargs):
            seen.append(individual_id)
            if individual_id == b.id:
                raise RuntimeError("the connection dropped")
            return real(user, individual_id, translate, **kwargs)

        before = self.counts()
        with (
            mock.patch.object(arsrapport, "execute", side_effect=flaky),
            mock.patch.dict(APP.config, {"PROPAGATE_EXCEPTIONS": False}),
        ):
            response = self.skicka(body)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(seen, [a.id, a.id, b.id])  # a's attestation, a's sale, then b
        self.assertEqual(self.counts(), before)
        after = db.YearlyReportDraft.get()
        self.assertEqual((after.updated_at, after.data), (draft.updated_at, draft.data))

    # The receipt mail and the report row

    def test_receipt_goes_to_the_main_member_once(self):
        a, b, c = self.rabbits(self.h, 3)
        body = self.body(self.kvar(a, vikt=2.8), self.dod(b, 2025, 11), self.sald(c, "G9002", 2025, 12, 10))
        receipt = self.ok(body)
        self.ok(body)
        (row,) = self.kvitton()
        sid = receipt["submission_id"]
        self.assertEqual(
            (row.recipient_kind, row.recipient_id, row.params, row.ref_type, row.ref_id),
            ("member", self.member.id, {"submission_id": sid}, "yearly_report_submission", sid),
        )
        self.assertEqual(
            (row.herd_id, row.genebank_id, row.dedupe_key, row.created_by_id, row.priority),
            (self.h.id, self.gotland.id, f"arsrapport.kvitto:{sid}", self.owner.id, 0),
        )
        subject, text = mail.render("arsrapport.kvitto", arsrapport._kvitto(row.params))
        self.assertEqual(subject, "Årsrapporten för G9001 är inskickad")
        for line in (
            "Årsrapporten för besättning G9001 kom in den 2026-01-15. Du rapporterade 1 kanin som finns kvar, "
            "1 död och 1 såld.",
            "Du kan ändra den så länge rundan är öppen, till och med 2026-03-30.",
            "Var det inte du? Kontakta genbanksansvarig genom att svara på det här mejlet.",
        ):
            self.assertIn(line, text)
        _, plural = mail.render(
            "arsrapport.kvitto", {**arsrapport._kvitto(row.params), "kvar": 2, "doda": 0, "salda": 3}
        )
        self.assertIn("Du rapporterade 2 kaniner som finns kvar, 0 döda och 3 sålda.", plural)
        self.assertIsNone(arsrapport._kvitto({"submission_id": sid + 1}))

        # no mail without a main member with an e-mail address
        for code, email in (("G9003", None), ("G9004", "")):
            herd = self.herd(code)
            self.main_member(herd, email)
            (rabbit,) = self.rabbits(herd, 1)
            self.ok(self.body(self.kvar(rabbit, vikt=2.8)), code)
        herd = self.herd("G9005")
        (rabbit,) = self.rabbits(herd, 1)
        self.ok(self.body(self.kvar(rabbit, vikt=2.8)), "G9005")
        self.assertEqual(len(self.kvitton()), 1)

    def test_first_submission_fields(self):
        (a,) = self.rabbits(self.h, 1)
        body = self.body(self.kvar(a, vikt=2.8), message="Allt väl")
        self.api(
            "PUT",
            "/besattning/G9001/2025/utkast",
            data=arsrapport.stored_body(body),
            updated_at=None,
            submission_key=body["submission_key"],
            revision=None,
        )
        receipt = self.ok(body)
        report = db.YearlyHerdReport.get_by_id(receipt["report_id"])
        self.assertEqual(
            (report.status, report.source, report.revision, report.report_date, report.round_id),
            ("submitted", "login", 1, date(2026, 1, 15), self.round_.id),
        )
        self.assertEqual((report.generated_by_id, report.entered_by_id, report.received_at), (self.owner.id, None, NOW))
        self.assertEqual(json.loads(report.data), arsrapport.parse_submission(body, paper=False).report)
        submission = db.YearlyReportSubmission.get_by_id(receipt["submission_id"])
        ops = [str(op) for (op,) in db.IndividualCommand.select(db.IndividualCommand.operation_id).tuples()]
        self.assertEqual(
            (submission.user_id, submission.source, str(submission.submission_key), submission.created_at),
            (self.owner.id, "login", body["submission_key"], NOW),
        )
        self.assertEqual(submission.operation_ids, ops)
        entry = {"val": "kvar", "vikt": 2.8, "ej_vagd": None, "hull": None, "dod": None, "sald": None}
        self.assertEqual(
            submission.data,
            {
                "reason": None,
                "rabbits": {str(a.id): entry},
                "ending_genbank": False,
                "membership_after_end": None,
                "health": "inga",
                "diseases": {},
                "defects": [],
                "message": "Allt väl",
            },
        )
        self.assertEqual(len(ops), 1)  # the attestation; measurements are logged in added_measurements
        self.assertFalse(db.YearlyReportDraft.select().exists())

        # after a voided report: the next revision, and the round's first received_at (5.13)
        g3 = self.herd("G9003")
        (b,) = self.rabbits(g3, 1)
        early = NOW - timedelta(days=10)
        db.YearlyHerdReport.create(
            herd=g3,
            round=self.round_,
            report_date=early.date(),
            data="{}",
            status="voided",
            source="login",
            revision=3,
            received_at=early,
            voided_at=early + timedelta(days=1),
            voided_by_user=self.owner.id,
        )
        report = db.YearlyHerdReport.get_by_id(self.ok(self.body(self.kvar(b, vikt=2.8)), "G9003")["report_id"])
        self.assertEqual((report.revision, report.received_at), (4, early))
