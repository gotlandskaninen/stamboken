#!/usr/bin/env python3
"""
Tests for a change of a submitted yearly report (Ändra: Skicka on an existing report, which applies the diff of its
effects) and for Dra tillbaka, with their mails Å8 and Å9. Synthetic herds, rabbits and buyers only.

isort:skip_file
"""

import json
import uuid
from datetime import date, datetime, timedelta
from datetime import time as clock
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.mail as mail
from playhouse.shortcuts import model_to_dict
from utils.database import coerce_date
from utils.herd_tracking import (
    DATE_BEFORE_LATEST,
    QUEUE_CHANGED,
    REPORT_LATER_ROW,
    HerdTrackingConflict,
    HerdTrackingForbidden,
    HerdTrackingInvalid,
)
from utils.individual_commands import REPORT_UNDO_REASON, IndividualRefused

from tests.arsrapport_fixtures import ArsrapportTest
from tests.ht_helpers import count_queries, ht_row

LAST = date(2025, 12, 31)
DAY0 = date(2026, 1, 10)
FUTURE = datetime.now().year + 1  # _validate_sale reads the real clock, not the fixture's
BUYER = {"name": "Test Köpare", "town": "Visby", "postal_address": "Testgatan 1"}
OTHER_BUYER = {"name": "Annan Köpare", "town": "Slite", "postal_address": "Testgatan 1"}
KEY_TAKEN = "Rapporten är redan skickad med den här nyckeln. Ladda om sidan."
LATER = "Kaninen har en senare händelse i Stamboken. Genbanksansvarig kan rätta."
NAMED = [{"individual_id": None, "code": "orsak_kopare", "message": "Skriv inte köparens namn i orsaken."}]
WRITTEN = (
    db.HerdTracking,
    db.IndividualCommand,
    db.Weight,
    db.Bodyfat,
    db.BuyerContact,
    db.YearlyHerdReport,
    db.YearlyReportSubmission,
    db.YearlyReportDraft,
    db.MailMessage,
)


def noon(day):
    return datetime.combine(day, clock(12), arsrapport.STOCKHOLM)


def rows_of(ind, kind):
    return list(
        db.HerdTracking.select()
        .where(db.HerdTracking.individual == ind.id, db.HerdTracking.kind == kind)
        .order_by(db.HerdTracking.id)
    )


def footprint(ind):
    """Every row a write on the rabbit leaves: herd tracking, commands, weights and hull."""
    return [
        sorted(row.id for row in model.select().where(model.individual == ind.id))
        for model in (db.HerdTracking, db.IndividualCommand, db.Weight, db.Bodyfat)
    ]


class AndraTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        self.day(0)
        self.round_ = self.round(2025)
        self.h = db.Herd.create(genebank=self.gotland, herd="G9001", herd_name="Testbesättning", is_active=True)
        self.g9002 = db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.owner.add_role("owner", self.h.id)
        self.member = self.main_member(self.h, "g9001@example.invalid")
        self.login("owner")

    def day(self, n):
        self.at(DAY0 + timedelta(days=n))

    def skicka(self, body):
        return self.api("POST", "/besattning/G9001/2025/skicka", **body)

    def ok(self, body):
        response = self.skicka(body)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def withdraw(self, revision, reason=None):
        return self.api("POST", "/besattning/G9001/2025/dra-tillbaka", revision=revision, reason=reason)

    def withdrawn(self, revision, reason=None):
        response = self.withdraw(revision, reason)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def report(self, report_id=None):
        if report_id is not None:
            return db.YearlyHerdReport.get_by_id(report_id)
        return db.YearlyHerdReport.get(db.YearlyHerdReport.herd == self.h.id, db.YearlyHerdReport.status == "submitted")

    def submissions(self, report_id):
        query = db.YearlyReportSubmission.select().where(db.YearlyReportSubmission.report == report_id)
        return list(query.order_by(db.YearlyReportSubmission.id))

    def report_rows(self, report_id):
        """The report's active herd-tracking rows: its attestations and its submissions' operations."""
        ops = [op for submission in self.submissions(report_id) for op in submission.operation_ids]
        return list(
            db.HerdTracking.select().where(
                (db.HerdTracking.yearly_herd_report == report_id) | db.HerdTracking.operation_id.in_(ops),
                db.ht_not_voided(),
            )
        )

    def added(self, report_id, kind="weight"):
        return [m for s in self.submissions(report_id) for m in s.added_measurements if m["kind"] == kind]

    def mail_kinds(self):
        return [row.kind for row in db.MailMessage.select().order_by(db.MailMessage.id)]

    def counts(self):
        return [model.select().count() for model in WRITTEN]

    def caretaker(self):
        """An account with a herd-access grant to G9001 through the membership: the caretaker (skötare)."""
        user = self.user("skotare")
        person = db.Member.create(
            first_name="Test", last_name="Skötare", membership=self.h.membership, role="skotare", user=user
        )
        db.HerdAccessGrant.create(member=person, herd=self.h, granted_by=self.admin)
        return user

    # Case 1: Ändra, then Dra tillbaka

    def ten_and_one_dead(self, change_day):
        """Case 1: ten kvar on day 0, one of them dead on `change_day`; returns (rabbits, report id)."""
        rabbits = self.rabbits(self.h, 10)
        entries = [self.kvar(rabbit, vikt=2.8) for rabbit in rabbits]
        rid = self.ok(self.body(*entries))["report_id"]
        self.day(change_day)
        self.ok(self.body(self.dod(rabbits[0], 2025, 11, 20), *entries[1:], revision=1))
        return rabbits, rid

    def test_change_one_rabbit_to_dead_on_day_5(self):  # case 1, first half
        rabbits = self.rabbits(self.h, 10)
        entries = [self.kvar(rabbit, vikt=2.8) for rabbit in rabbits]
        rid = self.ok(self.body(*entries))["report_id"]
        dead, others = rabbits[0], rabbits[1:]
        (attestation,) = rows_of(dead, "ATTESTATION")
        before = [footprint(rabbit) for rabbit in others]
        self.day(5)
        receipt = self.ok(self.body(self.dod(dead, 2025, 11, 20), *entries[1:], revision=1, message="Ändrad"))

        self.assertEqual(receipt["report_id"], rid)
        voided = db.HerdTracking.get_by_id(attestation.id)
        self.assertIsNotNone(voided.voided_at)
        self.assertEqual((voided.voided_reason, voided.voided_by_user_id), (REPORT_UNDO_REASON, self.owner.id))
        self.assertEqual(db.Individual.get_by_id(dead.id).death_date, date(2025, 11, 20))
        self.assertFalse(db.Weight.filter(individual=dead).exists())  # the 31/12 weight of a dead rabbit goes
        self.assertEqual([footprint(rabbit) for rabbit in others], before)
        self.assertEqual(self.mail_kinds(), ["arsrapport.kvitto", "arsrapport.andrad"])
        report = self.report(rid)
        self.assertEqual((report.revision, report.report_date), (2, DAY0 + timedelta(days=5)))
        self.assertEqual(json.loads(report.data)["message"], "Ändrad")  # the latest submission's report fields
        _, second = self.submissions(rid)
        death_op = db.IndividualCommand.get(individual=dead, command="RecordDeath").operation_id
        self.assertEqual(second.operation_ids, [str(death_op)])
        self.assertEqual(second.added_measurements, [])

    def test_withdraw_on_day_6_backs_out_everything(self):  # case 1
        rabbits, rid = self.ten_and_one_dead(5)
        self.day(6)
        view = self.withdrawn(2)

        self.assertFalse(self.report_rows(rid))
        self.assertIsNone(db.Individual.get_by_id(rabbits[0].id).death_date)
        self.assertFalse(db.Weight.select().where(db.Weight.id.in_([m["id"] for m in self.added(rid)])).exists())
        self.assertEqual(len(self.added(rid)), 10)
        report = self.report(rid)
        self.assertEqual(
            (report.status, report.voided_at, report.voided_by_user_id, report.void_reason, report.revision),
            ("voided", noon(DAY0 + timedelta(days=6)), self.owner.id, None, 2),
        )
        self.assertIsNone(view["report"])
        self.assertIsNotNone(view["draft"])
        self.assertIsNone(view["draft"]["submission_key"])
        latest = {k: v for k, v in self.submissions(rid)[-1].data.items() if k != "litters_added"}
        self.assertEqual(view["draft"]["data"], latest)  # the latest submission's, without the receipt's litters
        self.assertEqual(self.mail_kinds(), ["arsrapport.kvitto", "arsrapport.andrad", "arsrapport.angrad"])
        # no rabbit is held on 31/12 through the report any more: they are all to choose again
        self.assertEqual({row["state"] for row in view["rabbits"]}, {"att_valja"})

    def test_change_on_day_10_then_withdraw_on_day_11_is_refused(self):  # case 1
        rabbits, rid = self.ten_and_one_dead(10)
        (attestation,) = rows_of(rabbits[0], "ATTESTATION")
        self.assertIsNotNone(attestation.voided_at)  # the report's right reaches past the 7-day rule
        self.assertEqual(db.Individual.get_by_id(rabbits[0].id).death_date, date(2025, 11, 20))
        self.day(11)
        before = self.counts()
        response = self.withdraw(2)
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
        until = self.report(rid).received_at + timedelta(days=7)
        self.assertEqual(response.get_json()["withdraw_until"], until.isoformat())
        self.assertEqual(self.counts(), before)

    def test_resubmit_after_withdraw_makes_a_new_report(self):  # Review Focus 2
        rabbits, rid = self.ten_and_one_dead(5)
        self.withdrawn(2)
        draft = db.YearlyReportDraft.get()
        self.assertIsNone(draft.submission_key)
        self.assertNotIn("submission_key", draft.data)
        self.assertNotIn("revision", draft.data)
        body = {**draft.data, "submission_key": self.body()["submission_key"], "revision": None}
        receipt = self.ok(body)
        self.assertNotEqual(receipt["report_id"], rid)
        new = self.report(receipt["report_id"])
        self.assertEqual((new.status, new.revision), ("submitted", 3))
        self.assertEqual((self.report(rid).status, self.report(rid).revision), ("voided", 2))
        self.assertFalse(db.YearlyReportDraft.select().exists())
        self.assertEqual(len(rows_of(rabbits[1], "ATTESTATION")), 2)  # the voided one and the new one

    def test_old_tab_cannot_overwrite_the_new_report(self):
        (a,) = self.rabbits(self.h, 1)
        self.ok(self.body(self.kvar(a, vikt=2.8)))
        self.withdrawn(1)
        self.ok(self.body(self.kvar(a, vikt=2.9)))
        before = self.counts()
        response = self.skicka(self.body(self.kvar(a, vikt=3.0), revision=1))
        self.assertEqual((response.status_code, response.get_json()["detail"]), (409, "Rapporten har ändrats."))
        self.assertEqual(self.withdraw(1).status_code, 409)
        self.assertEqual(self.counts(), before)

    def test_change_with_the_old_key_is_409(self):
        a, b = self.rabbits(self.h, 2)
        body = self.body(self.kvar(a, vikt=2.8), self.kvar(b, vikt=2.8))
        self.ok(body)
        before = self.counts()
        changed = {**body, "revision": 1, "rabbits": {**body["rabbits"], **dict([self.dod(b, 2025, 11)])}}
        response = self.skicka(changed)
        self.assertEqual((response.status_code, response.get_json()["detail"]), (409, KEY_TAKEN))
        self.assertEqual(self.counts(), before)

    def test_caretaker_changes_what_the_owner_submitted(self):
        a, b = self.rabbits(self.h, 2)
        rid = self.ok(self.body(self.kvar(a, vikt=2.8), self.kvar(b, vikt=2.8)))["report_id"]
        caretaker = self.caretaker()
        self.login("skotare")
        self.ok(self.body(self.dod(a, 2025, 11, 20), self.kvar(b, vikt=2.8), revision=1))
        self.assertIsNotNone(rows_of(a, "ATTESTATION")[0].voided_at)
        self.assertEqual(db.Individual.get_by_id(a.id).death_date, date(2025, 11, 20))
        self.assertEqual(self.submissions(rid)[-1].user_id, caretaker.id)
        self.assertEqual(self.report(rid).generated_by_id, self.owner.id)

    def test_manager_withdraws_late_with_a_reason(self):
        (a,) = self.rabbits(self.h, 1)
        rid = self.ok(self.body(self.kvar(a, vikt=2.8)))["report_id"]
        self.day(40)
        self.login("man")
        before = self.counts()
        for reason in (None, "  "):
            response = self.withdraw(1, reason)
            self.assertEqual((response.status_code, response.get_json()["field"]), (400, "reason"))
        response = self.withdraw(1, "Ring 070-123 45 67")  # free text never holds contact details
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.counts(), before)
        self.withdrawn(1, "Fel besättning")
        report = self.report(rid)
        self.assertEqual(
            (report.status, report.voided_by_user_id, report.void_reason), ("voided", self.manager.id, "Fel besättning")
        )
        self.assertEqual(rows_of(a, "ATTESTATION")[0].voided_reason, "Fel besättning")

    def test_withdraw_rights(self):
        (a,) = self.rabbits(self.h, 1)
        self.ok(self.body(self.kvar(a, vikt=2.8)))
        herd, user = self.h, db.User.get_by_id(self.helper.id)
        helper = arsrapport.Access("helper", self.item())
        with self.assertRaises(arsrapport.ArsrapportError) as refused:
            arsrapport.withdraw(herd, self.round_, helper, user, revision=1, reason="Fel")
        self.assertEqual(refused.exception.status, 403)
        # an owner after end_date: 403 with the last day, though within 7 days of the first submission
        owner = arsrapport.Access("owner")
        late = noon(self.round_.end_date + timedelta(days=1))
        with self.assertRaises(arsrapport.ArsrapportError) as refused:
            arsrapport.withdraw(herd, self.round_, owner, db.User.get_by_id(self.owner.id), revision=1, now=late)
        self.assertEqual(refused.exception.status, 403)
        self.assertIn("withdraw_until", refused.exception.extra)
        self.assertEqual(self.report().status, "submitted")

    def test_manager_changes_late_logged_in_with_a_reason(self):
        a, b = self.rabbits(self.h, 2)
        rid = self.ok(self.body(self.kvar(a, vikt=2.8), self.kvar(b, vikt=2.8)))["report_id"]
        late = self.round_.end_date + timedelta(days=2)
        self.at(late)
        body = self.body(self.dod(a, 2025, 11, 20), self.kvar(b, vikt=2.8), revision=1)
        refused = self.skicka(body)
        self.assertEqual(refused.status_code, 422)
        self.assertEqual({r["code"] for r in refused.get_json()["refusals"]}, {"rundan_stangd"})  # the owner
        self.login("man")
        refused = self.skicka(body)
        self.assertEqual(refused.status_code, 422)
        self.assertEqual({r["code"] for r in refused.get_json()["refusals"]}, {"orsak_kravs"})
        self.ok({**body, "reason": "Dödsfallet kom in per telefon"})
        report = self.report(rid)
        self.assertEqual((report.generated_by_id, report.report_date, report.revision), (self.owner.id, late, 2))
        self.assertEqual(self.submissions(rid)[-1].user_id, self.manager.id)
        self.assertEqual(rows_of(a, "ATTESTATION")[0].voided_reason, "Dödsfallet kom in per telefon")

    def test_received_at_stays_after_the_deadline(self):  # case 5
        (a,) = self.rabbits(self.h, 1)
        self.at(date(2026, 1, 30))
        rid = self.ok(self.body(self.kvar(a, vikt=2.8)))["report_id"]
        self.at(date(2026, 2, 2))
        self.ok(self.body(self.kvar(a, vikt=3.0), revision=1))
        self.assertEqual(self.report(rid).received_at, noon(date(2026, 1, 30)))
        view = self.client.get("/api/v2/arsrapport/besattning/G9001/2025").get_json()
        self.assertTrue(view["report"]["on_time"])
        self.withdrawn(2)
        new = self.ok(self.body(self.kvar(a, vikt=3.0)))["report_id"]
        self.assertEqual(self.report(new).received_at, noon(date(2026, 1, 30)))

    def test_on_time_decision_survives_a_resubmit(self):  # Codex 2: the latest decision, a cleared one too
        manager = db.User.get_by_id(self.manager.id)
        g9003 = db.Herd.create(genebank=self.gotland, herd="G9003", is_active=True)
        self.owner.add_role("owner", g9003.id)
        for herd, received, decisions in (
            (self.h, date(2026, 2, 2), (True, None)),
            (g9003, date(2026, 1, 20), (False,)),
        ):
            (a,) = self.rabbits(herd, 1)
            path = f"/besattning/{herd.herd}/2025"
            self.at(received)

            def send(path=path, a=a):
                response = self.api("POST", f"{path}/skicka", **self.body(self.kvar(a, vikt=2.8)))
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
                return self.report(response.get_json()["report_id"])

            report = send()
            for value in decisions:
                arsrapport.set_on_time(report, manager, value)
                response = self.api("POST", f"{path}/dra-tillbaka", revision=report.revision)
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
                report = send()
                self.assertEqual((report.on_time_override, report.on_time_set_by_id), (value, self.manager.id))
                expected = received <= self.round_.deadline if value is None else value
                self.assertEqual(arsrapport.on_time(report, self.round_), expected)

    def test_withdraw_after_a_january_sale(self):  # case 6
        (a,) = self.rabbits(self.h, 1)
        self.ok(self.body(self.sald(a, "G9002", 2026, 1, 3)))
        (attestation,), (sale,) = rows_of(a, "ATTESTATION"), rows_of(a, "TRANSFER")
        self.withdrawn(1)
        attestation, sale = db.HerdTracking.get_by_id(attestation.id), db.HerdTracking.get_by_id(sale.id)
        self.assertIsNotNone(attestation.voided_at)
        self.assertIsNotNone(sale.voided_at)
        self.assertLessEqual(sale.voided_at, attestation.voided_at)  # the sale first, then the attestation

    def test_withdraw_refused_behind_someone_elses_row(self):
        (a,) = self.rabbits(self.h, 1)
        self.ok(self.body(self.kvar(a, vikt=2.8)))
        ht_row("TRANSFER", from_herd=self.h, herd=self.g9002, individual=a, herd_tracking_date=date(2026, 1, 10))
        before = self.counts()
        response = self.withdraw(1)
        self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
        self.assertEqual(
            response.get_json()["refusals"], [{"individual_id": a.id, "code": "senare_handelse", "message": LATER}]
        )
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.report().status, "submitted")

    def test_unchanged_resubmission_writes_nothing(self):
        kept, dead, december, outside, january = self.rabbits(self.h, 5)
        entries = (
            self.kvar(kept, vikt=2.8),
            self.dod(dead, 2025, 11),
            self.sald(december, "G9002", 2025, 12, 10),
            self.sald(outside, "utanfor", 2025, 11, 20, kopare=BUYER),
            self.sald(january, "G9002", 2026, 1),
        )
        rid = self.ok(self.body(*entries))["report_id"]
        weights = sorted(row.id for row in db.Weight.select())
        sales = [
            (row.id, row.voided_at) for row in db.HerdTracking.filter(kind="TRANSFER").order_by(db.HerdTracking.id)
        ]
        self.day(10)
        again = (*entries[:3], self.sald(outside, "utanfor", 2025, 11, 20), entries[4])  # the stored data: no buyer
        dry = self.api("POST", "/besattning/G9001/2025/torrkorning", **self.body(*again, revision=1)).get_json()
        self.assertEqual((dry["ok"], dry["refusals"]), (True, []))
        self.ok(self.body(*again, revision=1))
        last = self.submissions(rid)[-1]
        self.assertEqual((last.operation_ids, last.added_measurements), ([], []))
        self.assertEqual(sorted(row.id for row in db.Weight.select()), weights)
        self.assertEqual(
            [(row.id, row.voided_at) for row in db.HerdTracking.filter(kind="TRANSFER").order_by(db.HerdTracking.id)],
            sales,
        )
        self.assertEqual(self.report(rid).revision, 2)
        self.assertEqual(self.mail_kinds(), ["arsrapport.kvitto", "arsrapport.andrad"])

    def test_dead_back_to_kvar(self):
        (a,) = self.rabbits(self.h, 1)
        self.ok(self.body(self.dod(a, 2025, 11)))
        self.day(2)
        self.ok(self.body(self.kvar(a, vikt=2.8), revision=1))
        self.assertIsNone(db.Individual.get_by_id(a.id).death_date)
        (attestation,) = rows_of(a, "ATTESTATION")
        self.assertEqual((coerce_date(attestation.herd_tracking_date), attestation.voided_at), (LAST, None))
        view = self.client.get("/api/v2/arsrapport/besattning/G9001/2025").get_json()
        self.assertEqual([row["id"] for row in view["rabbits"]], [a.id])

    def test_december_sale_back_to_kvar(self):
        (a,) = self.rabbits(self.h, 1)
        self.ok(self.body(self.sald(a, "G9002", 2025, 12, 10)))
        self.ok(self.body(self.kvar(a, vikt=2.8), revision=1))
        (sale,), (attestation,) = rows_of(a, "TRANSFER"), rows_of(a, "ATTESTATION")
        self.assertIsNotNone(sale.voided_at)
        self.assertEqual((attestation.herd_id, attestation.voided_at), (self.h.id, None))

    def test_weight_change_replaces_only_the_added_weight(self):
        (a,) = self.rabbits(self.h, 1)
        june = db.Weight.create(individual=a, weight=3.1, weight_date=date(2025, 6, 1))
        rid = self.ok(self.body(self.kvar(a, vikt=2.8, hull="normal")))["report_id"]
        (attestation,) = rows_of(a, "ATTESTATION")
        fat = db.Bodyfat.get(individual=a)
        self.ok(self.body(self.kvar(a, vikt=3.0, hull="normal"), revision=1))
        weights = {
            (row.id, coerce_date(row.weight_date), round(row.weight, 2)) for row in db.Weight.filter(individual=a)
        }
        new = db.Weight.get(db.Weight.individual == a.id, db.Weight.weight_date == LAST)
        self.assertEqual(weights, {(june.id, date(2025, 6, 1), 3.1), (new.id, LAST, 3.0)})
        self.assertEqual([row.id for row in db.Bodyfat.filter(individual=a)], [fat.id])
        self.assertEqual(rows_of(a, "ATTESTATION"), [attestation])
        self.assertIsNone(db.HerdTracking.get_by_id(attestation.id).voided_at)
        self.assertEqual(
            self.submissions(rid)[-1].added_measurements,
            [{"individual_id": a.id, "kind": "weight", "id": new.id, "date": "2025-12-31", "value": 3.0}],
        )

    def test_measurement_change_after_a_january_sale(self):  # the sale comes off and goes back after the weight
        (a,) = self.rabbits(self.h, 1)
        key, sold = self.sald(a, "G9002", 2026, 1, 3)
        self.ok(self.body((key, {**sold, "vikt": 2.8})))
        (attestation,) = rows_of(a, "ATTESTATION")
        for revision, change in ((1, {"vikt": 3.0}), (2, {"vikt": 3.0, "hull": "normal"})):  # a weight, then hull
            body = self.body((key, {**sold, **change}), revision=revision)
            dry = self.api("POST", "/besattning/G9001/2025/torrkorning", **body).get_json()
            self.assertEqual((dry["ok"], dry["refusals"]), (True, []))
            self.ok(body)
        sales = rows_of(a, "TRANSFER")
        self.assertEqual([sale.voided_at is None for sale in sales], [False, False, True])
        self.assertEqual(
            (coerce_date(sales[-1].herd_tracking_date), sales[-1].herd_id), (date(2026, 1, 3), self.g9002.id)
        )
        self.assertEqual([(row.id, row.voided_at) for row in rows_of(a, "ATTESTATION")], [(attestation.id, None)])
        weights = [(coerce_date(w.weight_date), round(w.weight, 2)) for w in db.Weight.filter(individual=a)]
        self.assertEqual(weights, [(LAST, 3.0)])
        self.assertEqual([b.bodyfat for b in db.Bodyfat.filter(individual=a)], ["normal"])

    def test_measurement_change_after_a_january_sale_outside(self):  # Opus 2: the sale and its buyer stay
        (a,) = self.rabbits(self.h, 1)
        key, sold = self.sald(a, "utanfor", 2026, 1, 5, kopare=BUYER)
        rid = self.ok(self.body((key, {**sold, "vikt": 2.8})))["report_id"]
        (sale,), (buyer,) = rows_of(a, "TRANSFER"), db.BuyerContact.select()
        stored = {**sold, "sald": {**sold["sald"], "kopare": None}}  # as the submission keeps it: no buyer
        for revision, change in ((1, {"vikt": 3.0}), (2, {"vikt": 3.0, "hull": "normal"})):  # a weight, then hull
            body = self.body((key, {**stored, **change}), revision=revision)
            dry = self.api("POST", "/besattning/G9001/2025/torrkorning", **body).get_json()
            self.assertEqual((dry["ok"], dry["refusals"]), (True, []))
            self.ok(body)
        self.assertEqual([(row.id, row.voided_at) for row in rows_of(a, "TRANSFER")], [(sale.id, None)])
        self.assertEqual(db.HerdTracking.get_by_id(sale.id).holder_contact_id, buyer.id)
        self.assertEqual(
            [model_to_dict(row, recurse=False) for row in db.BuyerContact.select()],
            [model_to_dict(buyer, recurse=False)],
        )
        weights = [(w.id, coerce_date(w.weight_date), round(w.weight, 2)) for w in db.Weight.filter(individual=a)]
        self.assertEqual([weight[1:] for weight in weights], [(LAST, 3.0)])
        self.assertEqual([b.bodyfat for b in db.Bodyfat.filter(individual=a)], ["normal"])
        self.assertEqual([m["id"] for m in self.added(rid)][-1], weights[0][0])  # the report's own, for Dra tillbaka
        self.withdrawn(3)
        self.assertFalse(db.Weight.filter(individual=a).exists() or db.Bodyfat.filter(individual=a).exists())

    def test_refused_write_at_andra_rolls_back(self):  # U8 at Skicka, for what the dry run cannot see
        a, b = self.rabbits(self.h, 2)
        rid = self.ok(self.body(self.kvar(a, vikt=2.8), self.kvar(b, vikt=2.8)))["report_id"]
        (b_attestation,) = rows_of(b, "ATTESTATION")
        real = arsrapport.void_herd_tracking
        for exc, code, message in (
            (HerdTrackingForbidden(REPORT_LATER_ROW), "senare_handelse", LATER),
            (HerdTrackingConflict(DATE_BEFORE_LATEST), "senare_handelse", LATER),
            (HerdTrackingInvalid("Ange en anledning."), "skrivning_nekad", "Ange en anledning."),
            (IndividualRefused("Forbidden"), "skrivning_nekad", arsrapport.REFUSALS["skrivning_nekad"]),
        ):

            def flaky(ht_id, *args, exc=exc, **kwargs):
                if ht_id == b_attestation.id:
                    raise exc
                return real(ht_id, *args, **kwargs)

            before = self.counts()
            body = self.body(self.dod(a, 2025, 11, 20), self.dod(b, 2025, 11, 20), revision=1)
            with mock.patch.object(arsrapport, "void_herd_tracking", side_effect=flaky):
                response = self.skicka({**body, "submission_key": str(uuid.uuid4())})
            self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
            self.assertEqual(
                response.get_json()["refusals"], [{"individual_id": b.id, "code": code, "message": message}]
            )
            self.assertEqual(self.counts(), before)
            self.assertEqual(self.report(rid).revision, 1)
            self.assertIsNone(rows_of(a, "ATTESTATION")[0].voided_at)  # a, changed first, is rolled back

    def test_changed_sale_is_checked_at_andra(self):  # Codex 2
        (a,) = self.rabbits(self.h, 1, born=date(2025, 10, 1))
        self.ok(self.body(self.sald(a, "G9002", 2025, 12, 10)))
        before = self.counts()
        for entry in (self.sald(a, "G9002", FUTURE, 1, 1), self.sald(a, "G9002", 2025, 11, 1)):
            response = self.skicka(self.body(entry, revision=1))
            self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
            self.assertEqual([r["code"] for r in response.get_json()["refusals"]], ["forsaljning"])
        self.assertEqual(self.counts(), before)

    def test_buyer_only_change_replaces_the_sale(self):  # Codex 8
        (a,) = self.rabbits(self.h, 1)
        self.ok(self.body(self.sald(a, "utanfor", 2025, 11, 20, kopare=BUYER)))
        (first,) = rows_of(a, "TRANSFER")
        view = self.api("GET", "/besattning/G9001/2025").json
        self.assertEqual(view["rabbits"][0]["registered_buyer_date"], "2025-11-20")
        corrected = {**OTHER_BUYER, "postal_address": ""}
        self.ok(self.body(self.sald(a, "utanfor", 2025, 11, 20, kopare=corrected), revision=1))
        old, new = rows_of(a, "TRANSFER")
        self.assertEqual(old.id, first.id)
        self.assertIsNotNone(old.voided_at)
        self.assertEqual(
            (coerce_date(new.herd_tracking_date), new.herd.herd, new.voided_at), (date(2025, 11, 20), "GX1", None)
        )
        self.assertEqual([(c.name, c.town) for c in db.BuyerContact.select()], [("Annan Köpare", "Slite")])
        self.assertEqual(new.holder_contact_id, db.BuyerContact.get().id)
        self.assertEqual(new.holder_contact.postal_address, BUYER["postal_address"])
        before = self.counts()
        self.ok(self.body(self.sald(a, "utanfor", 2025, 11, 20), revision=2))  # without kopare: nothing
        self.assertEqual(self.counts()[:5], before[:5])
        # a reason naming the buyer is refused for the report (kopare's privacy rule), in the dry run too (I3); the
        # owner's reason is the system's, so only a role that reads buyers types one
        named = NAMED
        body = self.body(self.kvar(a, vikt=2.8), revision=3, reason="Annan Köpare ångrade sig")
        self.login("man")
        dry = self.api("POST", "/besattning/G9001/2025/torrkorning", **body).get_json()
        self.assertEqual(dry["refusals"], named)
        response = self.skicka(body)
        self.assertEqual((response.status_code, response.get_json()["refusals"]), (422, named))
        response = self.withdraw(3, "Annan Köpare ångrade sig")
        self.assertEqual((response.status_code, response.get_json()["refusals"]), (422, named))
        self.assertEqual(self.counts()[:5], before[:5])

    def test_buyer_items_are_locked_before_the_rabbits(self):  # Codex 4, Opus 3: the queue's lock order
        a, c = self.rabbits(self.h, 2)
        self.ok(
            self.body(
                self.sald(a, "utanfor", 2025, 11, 20, kopare=BUYER),
                self.sald(c, "utanfor", 2025, 11, 20, kopare=OTHER_BUYER),
            )
        )
        item = self.item(documents=2)
        for document, rabbit in zip(item.documents.order_by(db.InboxDocument.id), (a, c), strict=True):
            document.individual = rabbit
            document.save()

        def locks(call):
            """The first table `call` locks of the queue's item and the rabbit, with its result."""
            seen, original = [], db.DATABASE.execute_sql

            def spy(sql, *args, **kwargs):
                if "FOR UPDATE" in sql or "FOR NO KEY UPDATE" in sql:
                    seen.extend(table for table in ("inbox_item", "individual") if f'FROM "{table}"' in sql)
                return original(sql, *args, **kwargs)

            with mock.patch.object(db.DATABASE, "execute_sql", side_effect=spy):
                response = call()
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            return seen[0]

        change = self.body(self.kvar(a, vikt=2.8), self.sald(c, "utanfor", 2025, 11, 20), revision=1)  # voids a's sale
        self.assertEqual(locks(lambda: self.skicka(change)), "inbox_item")
        with mock.patch.object(arsrapport, "buyer_items", return_value={10**9}):  # an item that appeared meanwhile
            response = self.withdraw(2)
        self.assertEqual((response.status_code, response.get_json()["detail"]), (409, QUEUE_CHANGED))
        self.assertEqual(locks(lambda: self.withdraw(2)), "inbox_item")  # voids c's sale
        self.assertTrue(all(row.voided_at for row in rows_of(c, "TRANSFER")))

    def test_reason_naming_a_typed_buyer_is_refused(self):  # Opus 1: the dry run and Skicka alike
        (a,) = self.rabbits(self.h, 1)
        self.ok(self.body(self.kvar(a, vikt=2.8)))
        before = self.counts()
        self.login("man")  # the owner's reason is the system's (without_reason)
        body = self.body(
            self.sald(a, "utanfor", 2025, 11, 20, kopare=BUYER), revision=1, reason="Test Köpare köpte den"
        )
        dry = self.api("POST", "/besattning/G9001/2025/torrkorning", **body).get_json()
        self.assertEqual(dry["refusals"], NAMED)
        response = self.skicka(body)
        self.assertEqual((response.status_code, response.get_json()["refusals"]), (422, NAMED))
        self.assertEqual(self.counts(), before)

    def test_reason_naming_an_earlier_buyer_is_refused_in_the_dry_run(self):  # Opus 4: a void without a buyer
        (a,) = self.rabbits(self.h, 1)
        gx1 = db.Herd.get(db.Herd.herd == "GX1")
        buyer = db.BuyerContact.create(
            name="Anna Berg", town="Visby", created_by_user=self.admin, purge_at=noon(date(2029, 6, 1))
        )
        sold = {"individual": a, "herd_tracking_date": date(2024, 6, 1), "holder_contact": buyer}
        ht_row("TRANSFER", from_herd=self.h, herd=gx1, **sold)
        ht_row("TRANSFER", from_herd=gx1, herd=self.h, individual=a, herd_tracking_date=date(2024, 8, 1))  # back
        self.ok(self.body(self.kvar(a, vikt=2.8)))
        before = self.counts()
        self.login("man")
        body = self.body(self.dod(a, 2025, 11, 20), revision=1, reason="Anna Berg ringde")  # voids the attestation
        dry = self.api("POST", "/besattning/G9001/2025/torrkorning", **body).get_json()
        self.assertEqual(dry["refusals"], NAMED)
        response = self.skicka(body)
        self.assertEqual((response.status_code, response.get_json()["refusals"]), (422, NAMED))
        response = self.withdraw(1, "Anna Berg ringde")
        self.assertEqual((response.status_code, response.get_json()["refusals"]), (422, NAMED))
        self.assertEqual(self.counts(), before)

    def test_receipt_is_fixed_per_submission(self):  # Codex 5
        a, b = self.rabbits(self.h, 2)
        body = self.body(self.kvar(a, vikt=2.8), self.kvar(b, vikt=2.8))
        first = self.ok(body)
        self.day(3)
        self.ok(self.body(self.kvar(a, vikt=2.8), self.dod(b, 2025, 11, 20), revision=1))  # another tab
        self.assertEqual(self.ok(body), first)
        kvitto = arsrapport._kvitto({"submission_id": first["submission_id"]})
        self.assertEqual(
            {key: kvitto[key] for key in ("datum", "kvar", "doda", "salda")},
            {"datum": DAY0.isoformat(), "kvar": 2, "doda": 0, "salda": 0},
        )

    # Rulings and carry-overs

    def test_andra_after_a_later_sale_on_the_rabbit_page(self):  # P39a: D5 wins
        a, b = self.rabbits(self.h, 2)
        self.ok(self.body(self.kvar(a, vikt=2.8), self.kvar(b, vikt=2.8)))
        ht_row("TRANSFER", from_herd=self.h, herd=self.g9002, individual=b, herd_tracking_date=date(2026, 1, 10))
        self.ok(self.body(self.kvar(a, vikt=3.0), self.kvar(b, vikt=2.8), revision=1))
        (attestation,) = rows_of(b, "ATTESTATION")
        self.assertIsNone(attestation.voided_at)

    def test_late_autosave_after_andra_leaves_the_withdraw_alone(self):  # e2e Typ C: only the page's revision is stale
        (a,) = self.rabbits(self.h, 1)
        self.ok(self.body(self.kvar(a, vikt=2.8)))
        self.ok(self.body(self.kvar(a, vikt=3.1), revision=1))
        data = arsrapport.stored_body(self.body(self.kvar(a, vikt=3.1)))
        key = self.body()["submission_key"]
        late = self.api(
            "PUT", "/besattning/G9001/2025/utkast", data=data, updated_at=None, submission_key=key, revision=1
        )
        self.assertEqual((late.status_code, late.get_json()["draft"]), (409, None))
        self.assertEqual((self.report().revision, db.YearlyReportDraft.select().count()), (2, 0))
        self.assertEqual(self.withdraw(1).status_code, 409)  # the revision the change replaced
        self.assertIsNone(self.withdrawn(2)["report"])

    def test_withdraw_keeps_an_autosaved_draft(self):  # P31: "Det du fyllt i finns kvar"
        (a,) = self.rabbits(self.h, 1)
        self.ok(self.body(self.kvar(a, vikt=2.8)))
        data = arsrapport.stored_body(self.body(self.kvar(a, vikt=3.3)))
        key = self.body()["submission_key"]
        saved = self.api(
            "PUT", "/besattning/G9001/2025/utkast", data=data, updated_at=None, submission_key=key, revision=1
        )
        self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
        view = self.withdrawn(1)
        draft = db.YearlyReportDraft.get()
        self.assertEqual((draft.data, draft.submission_key, view["draft"]["data"]), (data, None, data))
        self.assertGreater(draft.updated_at, datetime.fromisoformat(saved.get_json()["updated_at"]))
        stale = self.api(  # an old tab's autosave cannot bring the key back
            "PUT",
            "/besattning/G9001/2025/utkast",
            data=data,
            updated_at=saved.get_json()["updated_at"],
            submission_key=key,
            revision=1,
        )
        self.assertEqual(stale.status_code, 409)

    def test_december_sale_with_a_litter_after_it_is_refused_in_the_dry_run(self):  # Task 6 carry-over
        (a,) = self.rabbits(self.h, 1, sexes=("female",))
        self.ok(self.body(self.sald(a, "G9002", 2025, 12, 10)))
        db.Breeding.create(breeding_herd_id=self.g9002, mother=a, breed_date=date(2026, 1, 2))  # the buyer's
        body = self.body(self.kvar(a, vikt=2.8), revision=1)
        refusal = {
            "individual_id": a.id,
            "code": "skrivning_nekad",
            "message": "Kaninen har en parning eller kull registrerad efter försäljningen. Genbanksansvarig kan rätta.",
        }
        dry = self.api("POST", "/besattning/G9001/2025/torrkorning", **body).get_json()
        self.assertEqual(dry["refusals"], [refusal])
        before = self.counts()
        response = self.skicka(body)
        self.assertEqual((response.status_code, response.get_json()["refusals"]), (422, [refusal]))
        response = self.withdraw(1)
        self.assertEqual((response.status_code, response.get_json()["refusals"]), (422, [refusal]))
        self.assertEqual(self.counts(), before)

    def test_queries_per_changed_rabbit(self):  # case 3: Ändra stays within Skicka's order (U7a)
        counts = {}
        for code, n in (("G9003", 10), ("G9004", 20)):
            herd = db.Herd.create(genebank=self.gotland, herd=code, is_active=True)
            self.owner.add_role("owner", herd.id)
            rabbits = self.rabbits(herd, n)
            entries = [self.kvar(rabbit, vikt=2.8) for rabbit in rabbits]
            path = f"/api/v2/arsrapport/besattning/{code}/2025"
            self.assertEqual(self.client.post(f"{path}/skicka", json=self.body(*entries)).status_code, 200)

            def queries(body, path=path):
                with count_queries() as counter:
                    response = self.client.post(f"{path}/skicka", json=body)
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
                return counter["n"]

            dead = [self.dod(rabbit, 2025, 11, 20) for rabbit in rabbits]
            counts[n] = [queries(self.body(*entries, revision=1)), queries(self.body(*dead, revision=2))]
        unchanged, changed = ((large - small) / 10 for small, large in zip(counts[10], counts[20], strict=True))
        # Measured 2026-11-15: 0 and 61 per rabbit (a void, a delete and a RecordDeath; Skicka's first: 56).
        self.assertEqual(unchanged, 0, counts)
        self.assertLessEqual(changed, 68, counts)

    def test_caretaker_cannot_change_a_sale_and_withdrawing_keeps_it(self):  # I1, D12, FB5: sales are the owner's
        kept, december, outside = self.rabbits(self.h, 3)
        entries = (
            self.kvar(kept, vikt=2.8),
            self.sald(december, "G9002", 2025, 12, 10),
            self.sald(outside, "utanfor", 2025, 11, 20, kopare=BUYER),
        )
        rid = self.ok(self.body(*entries))["report_id"]
        self.caretaker()
        self.login("skotare")
        before = self.counts()
        refused = {
            "code": "forsaljning_skotare",
            "message": "Försäljningen registreras av ägaren eller genbanksansvarig.",
        }
        stored = (*entries[:2], self.sald(outside, "utanfor", 2025, 11, 20))  # as submitted: no buyer
        for changed in (self.kvar(december, vikt=2.8), self.dod(outside, 2025, 11, 10)):  # sald→kvar, sald→dod
            body = self.body(*[changed if changed[0] == e[0] else e for e in stored], revision=1)
            dry = self.api("POST", "/besattning/G9001/2025/torrkorning", **body).get_json()
            self.assertEqual(dry["refusals"], [{"individual_id": int(changed[0]), **refused}])
            response = self.skicka(body)
            self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
            self.assertEqual(response.get_json()["refusals"], [{"individual_id": int(changed[0]), **refused}])
        self.assertEqual(self.counts(), before)
        # a change that leaves the sales alone is still the caretaker's
        self.ok(self.body(self.kvar(kept, vikt=3.0), *stored[1:], revision=1))
        sales = rows_of(december, "TRANSFER") + rows_of(outside, "TRANSFER")
        self.withdrawn(2)  # FB5: the rest backs out, and the owner's sales stay the register's
        self.assertEqual(self.report(rid).status, "voided")
        (attested,) = rows_of(kept, "ATTESTATION")
        self.assertIsNotNone(attested.voided_at)
        self.assertEqual([db.HerdTracking.get_by_id(row.id).voided_at for row in sales], [None, None])
        self.assertEqual([(c.name, c.town) for c in db.BuyerContact.select()], [(BUYER["name"], BUYER["town"])])

    def test_withdraw_window_counts_from_the_rounds_first_submission(self):  # I2: no new 7 days per report row
        (a,) = self.rabbits(self.h, 1)
        self.ok(self.body(self.kvar(a, vikt=2.8)))
        self.day(2)
        self.withdrawn(1)
        self.day(3)
        rid = self.ok(self.body(self.kvar(a, vikt=2.8)))["report_id"]
        until = noon(DAY0) + timedelta(days=7)
        self.assertEqual(self.report(rid).received_at, noon(DAY0))
        view = self.client.get("/api/v2/arsrapport/besattning/G9001/2025").get_json()
        self.assertEqual(datetime.fromisoformat(view["report"]["withdraw_until"]), until)
        self.day(8)
        response = self.withdraw(2)
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
        self.assertEqual(datetime.fromisoformat(response.get_json()["withdraw_until"]), until)
        self.assertEqual(self.report(rid).status, "submitted")

    def test_ej_angiven_still_meets_the_register(self):  # M1: a paper change takes the attestation off
        (a,) = self.rabbits(self.h, 1)
        self.ok(self.body(self.kvar(a, vikt=2.8)))
        ht_row("CORRECTION", herd=self.g9002, individual=a, herd_tracking_date=date(2026, 1, 3))  # not a life sign
        body = self.body(self.ej_angiven(a), revision=1, reason="Blanketten", inbox_item_id=1, received_on="2026-01-12")
        sub = arsrapport.parse_submission(body, paper=True)
        access = arsrapport.Access("manager", self.item())
        refusals, _ = arsrapport.check(self.h, self.round_, access, self.report(), sub, on=DAY0)
        self.assertEqual(refusals, [arsrapport.Refusal(a.id, "senare_handelse", LATER)])

    # The mails

    def test_change_and_withdraw_mails(self):
        a, b, c = self.rabbits(self.h, 3)
        self.ok(self.body(self.kvar(a, vikt=2.8), self.kvar(b, vikt=2.8), self.kvar(c, vikt=2.8)))
        self.day(2)
        change = self.body(
            self.kvar(a, vikt=2.8), self.dod(b, 2025, 11), self.sald(c, "G9002", 2025, 12, 10), revision=1
        )
        receipt = self.ok(change)
        self.assertEqual(self.ok(change), receipt)  # a retry: no second mail
        self.day(3)
        rid, sid = receipt["report_id"], receipt["submission_id"]
        self.withdrawn(2)
        self.assertEqual(self.withdraw(2).status_code, 409)  # a retry after the report is gone: no second mail
        _, andrad, angrad = db.MailMessage.select().order_by(db.MailMessage.id)
        self.assertEqual(
            [(m.kind, m.params, m.ref_type, m.ref_id, m.dedupe_key) for m in (andrad, angrad)],
            [
                (
                    "arsrapport.andrad",
                    {"submission_id": sid},
                    "yearly_report_submission",
                    sid,
                    f"arsrapport.andrad:{sid}",
                ),
                ("arsrapport.angrad", {"report_id": rid}, "yearlyherdreport", rid, f"arsrapport.angrad:{rid}"),
            ],
        )
        for m in (andrad, angrad):
            self.assertEqual(
                (m.recipient_kind, m.recipient_id, m.herd_id, m.genebank_id, m.created_by_id, m.priority),
                ("member", self.member.id, self.h.id, self.gotland.id, self.owner.id, 0),
            )

        subject, text = mail.render("arsrapport.andrad", arsrapport._kvitto(andrad.params))
        self.assertEqual(subject, "Årsrapporten för G9001 är ändrad")
        for line in (
            "Årsrapporten för besättning G9001 ändrades den 2026-01-12. Nu har du rapporterat 1 kanin som finns kvar, "
            "1 död och 1 såld.",
            "Du kan ändra den så länge rundan är öppen, till och med 2026-03-30.",
            "Var det inte du? Kontakta genbanksansvarig genom att svara på det här mejlet.",
        ):
            self.assertIn(line, text)
        subject, text = mail.render("arsrapport.angrad", arsrapport._angrad(angrad.params))
        self.assertEqual(subject, "Årsrapporten för G9001 är tillbakadragen")
        for line in (
            "Årsrapporten för besättning G9001 drogs tillbaka den 2026-01-13.",
            "Kaninerna räknas inte som levande 31 december förrän rapporten skickas igen.",
            "Var det inte du? Kontakta genbanksansvarig genom att svara på det här mejlet.",
        ):
            self.assertIn(line, text)
        self.assertIsNone(arsrapport._angrad({"report_id": rid + 1}))
