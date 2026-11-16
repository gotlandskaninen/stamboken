#!/usr/bin/env python3
"""
Tests for "från blankett", the paper path (5.5): a manager or a helper enters a paper form from a taken inbox item
(…/skicka?post=<item>), with the item checked again under its lock, the trace "inlagd från foto av", the receipt
day, "Ej angiven", and the item closed after the entry. Synthetic herds, rabbits and buyers only.

isort:skip_file
"""

import json
import uuid
from datetime import date, datetime, timedelta
from datetime import time as clock
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.inbox as inbox
from herdbook import APP
from utils.individual_policy import Role

from tests.arsrapport_fixtures import ArsrapportTest
from tests.ht_helpers import ht_row
from tests.inbox_fixtures import QUALITY

NOW = datetime.combine(date(2026, 1, 15), clock(12), arsrapport.STOCKHOLM)
BUYER = {"name": "Test Köpare", "town": "Visby"}
WAITS = "Registrera intygen i posten först."
REPORT = "/api/v2/arsrapport/besattning/{herd}/2025"
WRITTEN = (
    db.HerdTracking,
    db.IndividualCommand,
    db.Weight,
    db.Bodyfat,
    db.BuyerContact,
    db.YearlyHerdReport,
    db.YearlyReportSubmission,
    db.InboxOperation,
    db.MailMessage,
)


def codes(response):
    return {refusal["code"] for refusal in response.get_json()["refusals"]}


class BlankettTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        self.at(NOW)
        self.round_ = self.round(2025)
        self.h = db.Herd.create(genebank=self.gotland, herd="G9001", herd_name="Testbesättning", is_active=True)
        self.g9002 = db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.owner.add_role("owner", self.h.id)
        self.main_member(self.h, "g9001@example.invalid")

    def form(self, taker, herd=None, pages=2, others=(), sender=None):
        """
        An upload for `herd` (G9001) with `pages` arsblankett documents, then one document per type in `others`,
        taken by `taker` (None: left "ny").
        """
        herd = herd or self.h
        types = ["arsblankett"] * pages + list(others)
        stored = [(f"inkorg/original/{n}.jpg", f"{herd.id}{n}".rjust(64, "0"), QUALITY) for n in range(len(types))]
        item, documents = inbox.create_upload(sender or self.owner, herd, None, stored)
        for document, doc_type in zip(documents, types, strict=True):
            document.doc_type = doc_type
            document.save()
        if taker is not None:
            inbox.take(item, taker, over=False)
        return db.InboxItem.get_by_id(item.id)

    def documents(self, item, doc_type="arsblankett"):
        query = db.InboxDocument.select().where(db.InboxDocument.item == item.id, db.InboxDocument.doc_type == doc_type)
        return list(query.order_by(db.InboxDocument.id))

    def paper(self, item, *entries, received_on="2026-01-12", **fields):
        """A paper body for `item`; health is left out on paper (5.5)."""
        return self.body(*entries, inbox_item_id=item.id, received_on=received_on, health=None, **fields)

    def skicka(self, item, body, herd="G9001"):
        return self.client.post(f"{REPORT.format(herd=herd)}/skicka?post={item.id}", json=body)

    def ok(self, item, body, herd="G9001"):
        response = self.skicka(item, body, herd)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def logged_in(self, body):
        """The owner's logged-in Skicka; leaves the owner logged in."""
        self.login("owner")
        response = self.client.post(f"{REPORT.format(herd='G9001')}/skicka", json=body)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def counts(self):
        return [model.select().count() for model in WRITTEN]

    def state(self, item):
        return db.InboxItem.get_by_id(item.id).state

    # The entry

    def test_form_and_buyer_items_are_locked_in_one_ascending_pass(self):  # Codex re-review 2: as tilldela does
        (a,) = self.rabbits(self.h, 1)
        gx1 = db.Herd.get(db.Herd.herd == "GX1")
        buyer = db.BuyerContact.create(
            name="Anna Berg", town="Visby", created_by_user=self.admin, purge_at=NOW + timedelta(days=1000)
        )
        sold = {"individual": a, "herd_tracking_date": date(2024, 6, 1), "holder_contact": buyer}
        ht_row("TRANSFER", from_herd=self.h, herd=gx1, **sold)
        ht_row("TRANSFER", from_herd=gx1, herd=self.h, individual=a, herd_tracking_date=date(2024, 8, 1))  # back
        older = self.item()  # an open item with a document of the rabbit, older than the form
        db.InboxDocument.update(individual=a).where(db.InboxDocument.item == older.id).execute()
        item = self.form(self.manager)
        self.assertLess(older.id, item.id)
        self.login("man")
        locks, original = [], db.DATABASE.execute_sql

        def spy(sql, *args, **kwargs):
            if 'FROM "inbox_item"' in sql and "FOR UPDATE" in sql:
                locks.append((" IN (" in sql, "ORDER BY" in sql, list(args[0] if args else kwargs.get("params") or ())))
            return original(sql, *args, **kwargs)

        with mock.patch.object(db.DATABASE, "execute_sql", side_effect=spy):
            self.ok(item, self.paper(item, self.kvar(a, vikt=2.8)))
        self.assertEqual(locks[0], (True, True, [older.id, item.id]))  # one ordered pass, before any other item lock

    def test_manager_enters_a_paper_form(self):
        a, b = self.rabbits(self.h, 2)
        item = self.form(self.manager)
        intyg = self.form(self.manager, pages=0, others=("intyg",))  # another item: its documents stay as they are
        # Case 5 on paper: posted 31 January and here 2 February; the manager gives the receipt day.
        self.at(date(2026, 2, 2))
        self.login("man")
        body = self.paper(item, self.kvar(a, vikt=2.8), self.dod(b, 2025, 11), received_on="2026-01-31")
        receipt = self.ok(item, body)

        report = db.YearlyHerdReport.get_by_id(receipt["report_id"])
        self.assertEqual(
            (report.source, report.entered_by_id, report.inbox_item_id, report.generated_by_id),
            ("paper", self.manager.id, item.id, None),
        )
        self.assertEqual(report.received_at, datetime(2026, 1, 31, tzinfo=arsrapport.STOCKHOLM))  # midnight there
        self.assertTrue(arsrapport.on_time(report, self.round_))
        submission = db.YearlyReportSubmission.get_by_id(receipt["submission_id"])
        self.assertEqual((submission.source, submission.user_id), ("paper", self.manager.id))
        self.assertEqual(submission.data["received_on"], "2026-01-31")

        # "Inlagd från foto av": one trace per operation id, the manager's, on the form's first page
        pages = self.documents(item)
        traces = list(db.InboxOperation.select())
        self.assertEqual(sorted(str(trace.operation_id) for trace in traces), sorted(submission.operation_ids))
        self.assertEqual({(trace.user_id, trace.document_id) for trace in traces}, {(self.manager.id, pages[0].id)})

        # Both pages done, their photo purged once the report can no longer be withdrawn; the item is closed.
        until = submission.created_at + timedelta(days=arsrapport.WITHDRAW_DAYS)
        self.assertEqual([(page.done_at is not None, page.purge_after) for page in pages], [(True, until)] * 2)
        self.assertEqual(self.state(item), "klar")
        self.assertEqual(
            [(d.done_at, d.purge_after) for d in self.documents(intyg, "intyg")], [(None, None)]
        )  # not this item's
        self.assertEqual(self.state(intyg), "tagen")

    def test_paper_needs_a_taken_arsblankett_item(self):
        (a,) = self.rabbits(self.h, 1)
        refused = {
            "ny": self.form(None),
            "taken by another": self.form(self.manager),
            "another herd": self.form(self.helper, herd=self.g9002),
            "no arsblankett": self.form(self.helper, pages=0, others=("intyg",)),
        }
        self.login("hjalp")
        before = self.counts()
        for name, item in refused.items():
            with self.subTest(name):
                self.assertEqual(self.skicka(item, self.paper(item, self.kvar(a, vikt=2.8))).status_code, 403)

        # Rule 1: the body's item is the one in ?post=
        item = self.form(self.helper)
        other = self.form(self.helper)
        response = self.skicka(item, self.paper(other, self.kvar(a, vikt=2.8)))
        self.assertEqual((response.status_code, response.get_json()["field"]), (400, "inbox_item_id"))

        # Under the lock: the item is checked again as report_access read it
        helper = db.User.get_by_id(self.helper.id)
        sub = arsrapport.parse_submission(self.paper(item, self.kvar(a, vikt=2.8)), paper=True)
        access = arsrapport.report_access(helper, self.h, item.id)
        inbox.take(db.InboxItem.get_by_id(item.id), self.manager, over=True)  # taken over meanwhile
        with self.assertRaises(inbox.InboxError) as taken, APP.app_context():  # request_hash reads SECRET_KEY
            arsrapport.submit(self.h, self.round_, access, helper, sub)
        self.assertEqual(taken.exception.status, 409)
        access = arsrapport.report_access(helper, self.h, other.id)
        db.InboxItem.update(state="vantar_uppfodare").where(db.InboxItem.id == other.id).execute()  # waits meanwhile
        sub = arsrapport.parse_submission(self.paper(other, self.kvar(a, vikt=2.8)), paper=True)
        with self.assertRaises(arsrapport.ArsrapportError) as waiting, APP.app_context():
            arsrapport.submit(self.h, self.round_, access, helper, sub)
        self.assertEqual(waiting.exception.status, 409)
        self.assertEqual(self.counts(), before)

    def test_paper_waits_for_the_items_certificates(self):
        (a,) = self.rabbits(self.h, 1)
        item = self.form(self.manager, others=("intyg",))
        (intyg,) = self.documents(item, "intyg")
        self.login("man")
        body = self.paper(item, self.kvar(a, vikt=2.8))
        before = self.counts()
        response = self.skicka(item, body)
        self.assertEqual((response.status_code, response.get_json()["detail"]), (409, WAITS))  # not done

        intyg.done_at, intyg.waiting_for = NOW, ["G9001-2599"]
        intyg.save()
        response = self.skicka(item, body)
        self.assertEqual((response.status_code, response.get_json()["detail"]), (409, WAITS))  # waits for a parent
        self.assertEqual(self.counts(), before)
        self.assertEqual([page.done_at for page in self.documents(item)], [None, None])

        intyg.waiting_for = None
        intyg.save()
        self.ok(item, body)
        self.assertEqual(self.state(item), "klar")
        self.assertIsNone(db.InboxDocument.get_by_id(intyg.id).purge_after)  # only the form's photo goes

    def test_helper_autosaves_and_dry_runs_with_the_item(self):
        (a,) = self.rabbits(self.h, 1)
        item = self.form(self.helper)
        self.login("hjalp")
        path = REPORT.format(herd="G9001")
        draft = {"data": {"rabbits": {}}, "updated_at": None, "submission_key": None, "revision": None}
        body = self.paper(item, self.kvar(a, vikt=2.8))
        response = self.client.put(f"{path}/utkast?post={item.id}", json=draft)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        response = self.client.post(f"{path}/torrkorning?post={item.id}", json=body)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertTrue(response.get_json()["ok"])
        self.assertEqual(self.client.put(f"{path}/utkast", json=draft).status_code, 403)
        self.assertEqual(self.client.post(f"{path}/torrkorning", json=self.body(self.kvar(a, 2.8))).status_code, 403)

        # The dry run checks the body's item and receipt day as Skicka does.
        for field, wrong in (("inbox_item_id", item.id + 1), ("received_on", "2026-01-16")):
            response = self.client.post(f"{path}/torrkorning?post={item.id}", json={**body, field: wrong})
            self.assertEqual((response.status_code, response.get_json()["field"]), (400, field))

    def test_paper_retry_after_the_item_closed(self):  # case 3 on paper
        (a,) = self.rabbits(self.h, 1)
        (b,) = self.rabbits(self.g9002, 1)
        for username, taker, herd, rabbit in (("man", self.manager, self.h, a), ("hjalp", self.helper, self.g9002, b)):
            with self.subTest(username):
                item = self.form(taker, herd=herd)
                self.login(username)
                body = self.paper(item, self.kvar(rabbit, vikt=2.8))
                receipt = self.ok(item, body, herd.herd)
                self.assertEqual(self.state(item), "klar")
                before = self.counts()
                self.assertEqual(self.ok(item, body, herd.herd), receipt)
                self.assertEqual(self.counts(), before)
                # only the retry gets past the closed item
                other = {**body, "submission_key": str(uuid.uuid4())}
                self.assertEqual(self.skicka(item, other, herd.herd).status_code, 403)

    def test_archiving_the_form_closes_only_a_finished_item(self):  # Codex 12
        (a,) = self.rabbits(self.h, 1)
        rid = self.logged_in(self.body(self.kvar(a, vikt=2.8)))["report_id"]

        def report():  # closing the item mails its sender, so the mail queue is left out
            models = (db.HerdTracking, db.IndividualCommand, db.Weight, db.YearlyReportSubmission, db.InboxOperation)
            return db.YearlyHerdReport.get_by_id(rid).revision, [model.select().count() for model in models]

        before = report()
        self.login("man")
        for others, state in ((("intyg",), "tagen"), ((), "klar")):
            with self.subTest(state):
                item = self.form(self.manager, others=others)
                for page in self.documents(item):
                    path = f"/api/v2/inkorg/{item.id}/dokument/{page.id}"
                    response = self.client.patch(path, json={"dismissed": True})
                    self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
                self.assertEqual(self.state(item), state)
                self.assertEqual([d.done_at for d in self.documents(item, "intyg")], [None] * len(others))
        self.assertEqual(report(), before)

    def test_helper_enters_and_sells_directly(self):
        a, b, c = self.rabbits(self.h, 3)
        item = self.form(self.helper)
        self.login("hjalp")
        seen, roles = [], arsrapport.ReportGrant.roles

        def spy(grant, user, individual):
            seen.append(roles(grant, user, individual))
            return seen[-1]

        body = self.paper(
            item,
            self.kvar(a, vikt=2.8),
            self.sald(b, "G9002", 2025, 12, 10),
            self.sald(c, "utanfor", 2025, 12, 12, kopare=BUYER),
        )
        with mock.patch.object(arsrapport.ReportGrant, "roles", spy):
            receipt = self.ok(item, body)
        self.assertTrue(seen)
        self.assertTrue(all(Role.HANDLAGGARE in held for held in seen), seen)  # the item's grant, no role of hers

        sold = db.HerdTracking.select().where(db.HerdTracking.kind == "TRANSFER", db.HerdTracking.from_herd == self.h)
        sales = {row.individual_id: row for row in sold}
        self.assertEqual((sales[b.id].herd.herd, sales[b.id].holder_contact_id), ("G9002", None))
        self.assertEqual(sales[c.id].herd.herd, "GX1")
        buyer = db.BuyerContact.get_by_id(sales[c.id].holder_contact_id)
        self.assertEqual((buyer.name, buyer.town, buyer.created_by_user_id), ("Test Köpare", "Visby", self.helper.id))
        self.assertEqual({command.actor_id for command in db.IndividualCommand.select()}, {self.helper.id})
        operations = db.YearlyReportSubmission.get_by_id(receipt["submission_id"]).operation_ids
        traces = {str(trace.operation_id): trace.user_id for trace in db.InboxOperation.select()}
        self.assertEqual(traces, dict.fromkeys(operations, self.helper.id))
        self.assertEqual(db.YearlyHerdReport.get_by_id(receipt["report_id"]).entered_by_id, self.helper.id)

    def test_helper_cannot_withdraw(self):
        (a,) = self.rabbits(self.h, 1)
        rid = self.logged_in(self.body(self.kvar(a, vikt=2.8)))["report_id"]
        item = self.form(self.helper)
        self.login("hjalp")
        path = REPORT.format(herd="G9001")
        response = self.client.post(f"{path}/dra-tillbaka?post={item.id}", json={"revision": 1, "reason": "Fel"})
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["detail"], "Genbankshjälpare kan inte dra tillbaka en rapport.")
        self.assertEqual(db.YearlyHerdReport.get_by_id(rid).status, "submitted")

    def test_ej_angiven_three_of_twelve(self):  # case 8, the form's half
        rabbits, missing = self.ej_angiven_case(self.h)
        item = self.form(self.manager)
        self.login("man")
        entries = [self.ej_angiven(r) if r in missing else self.kvar(r, vikt=2.8) for r in rabbits]
        receipt = self.ok(item, self.paper(item, *entries, received_on="2026-01-12"))  # before the deadline (U12)
        self.assertEqual(receipt["summary"], {"kvar": 9, "doda": 0, "salda": 0, "vantar": 0, "ej_angivna": 3})
        ids = sorted(r.id for r in missing)
        written = db.HerdTracking.select().where(db.HerdTracking.individual.in_(ids), db.HerdTracking.kind != "BIRTH")
        self.assertEqual((written.count(), db.Weight.select().where(db.Weight.individual.in_(ids)).count()), (0, 0))
        report = db.YearlyHerdReport.get_by_id(receipt["report_id"])
        self.assertEqual(json.loads(report.data)["not_stated"], ids)
        self.assertTrue(arsrapport.on_time(report, self.round_))

    def test_paper_over_a_digital_report_needs_a_reason(self):
        a, b = self.rabbits(self.h, 2)
        rid = self.logged_in(self.body(self.kvar(a, vikt=2.8), self.kvar(b, vikt=2.8)))["report_id"]
        received = db.YearlyHerdReport.get_by_id(rid).received_at
        item = self.form(self.manager)
        self.login("man")
        body = self.paper(item, self.kvar(a, vikt=2.8), self.dod(b, 2025, 11), revision=1)
        response = self.skicka(item, body)
        self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
        self.assertEqual(codes(response), {"orsak_kravs"})

        receipt = self.ok(item, {**body, "reason": "Blanketten kom efter inskicket"})
        report = db.YearlyHerdReport.get_by_id(rid)
        self.assertEqual(
            (report.received_at, report.generated_by_id, report.source, report.entered_by_id, report.inbox_item_id),
            (received, self.owner.id, "paper", self.manager.id, item.id),
        )
        self.assertEqual(report.revision, 2)
        submission = db.YearlyReportSubmission.get_by_id(receipt["submission_id"])
        self.assertEqual(submission.data["reason"], "Blanketten kom efter inskicket")
        self.assertIsNotNone(db.Individual.get_by_id(b.id).death_date)
        # the change's void is traced to the form too
        voided = db.HerdTracking.get(db.HerdTracking.individual == b.id, db.HerdTracking.kind == "ATTESTATION")
        traced = {str(trace.operation_id) for trace in db.InboxOperation.select()}
        self.assertIn(str(voided.voided_operation_id), traced)
        self.assertTrue(set(submission.operation_ids) <= traced)
        self.assertEqual(self.state(item), "klar")

    def test_helper_changes_a_digital_report_through_the_item(self):  # the void and the Undo under her grant
        a, b = self.rabbits(self.h, 2)
        self.logged_in(self.body(self.kvar(a, vikt=2.8), self.dod(b, 2025, 11)))
        item = self.form(self.helper)
        self.login("hjalp")
        body = self.paper(item, self.dod(a, 2025, 11), self.kvar(b, vikt=2.8), revision=1, reason="Blanketten")
        receipt = self.ok(item, body)
        self.assertIsNotNone(db.Individual.get_by_id(a.id).death_date)
        self.assertIsNone(db.Individual.get_by_id(b.id).death_date)  # the report's death undone
        voided = db.HerdTracking.get(db.HerdTracking.individual == a.id, db.HerdTracking.kind == "ATTESTATION")
        undo = db.IndividualCommand.get(db.IndividualCommand.individual == b.id, db.IndividualCommand.command == "Undo")
        self.assertEqual((voided.voided_by_user_id, undo.actor_id), (self.helper.id, self.helper.id))
        operations = db.YearlyReportSubmission.get_by_id(receipt["submission_id"]).operation_ids
        traces = {str(trace.operation_id): trace.user_id for trace in db.InboxOperation.select()}
        for op in (*operations, str(voided.voided_operation_id), str(undo.operation_id)):
            self.assertEqual(traces.get(op), self.helper.id, op)

    def test_received_on_cannot_be_in_the_future(self):
        (a,) = self.rabbits(self.h, 1)
        item = self.form(self.manager)
        self.login("man")
        before = self.counts()
        for field, body in (
            ("received_on", self.paper(item, self.kvar(a, vikt=2.8), received_on="2026-01-16")),
            ("signed_on", self.paper(item, self.kvar(a, vikt=2.8), signed_on="2026-01-13")),  # after received_on
        ):
            response = self.skicka(item, body)
            self.assertEqual((response.status_code, response.get_json()["field"]), (400, field))
        self.assertEqual(self.counts(), before)
        self.ok(item, self.paper(item, self.kvar(a, vikt=2.8), received_on="2026-01-15"))  # today is not the future

    def test_helper_enters_late_but_does_not_change_late(self):  # D11, P39c on Skicka
        (a,) = self.rabbits(self.h, 1)
        item = self.form(self.helper)
        self.at(self.round_.end_date + timedelta(days=1))
        self.login("hjalp")
        body = self.paper(item, self.kvar(a, vikt=2.8), received_on="2026-03-20")
        response = self.skicka(item, body)
        self.assertEqual((response.status_code, codes(response)), (422, {"orsak_kravs"}))
        self.ok(item, {**body, "reason": "Blanketten kom sent"})

        again = self.form(self.helper)
        change = self.paper(again, self.dod(a, 2025, 11), revision=1, reason="Ny blankett", received_on="2026-03-25")
        response = self.skicka(again, change)
        self.assertEqual((response.status_code, codes(response)), (422, {"rundan_stangd"}))
