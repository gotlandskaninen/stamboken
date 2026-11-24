#!/usr/bin/env python3
"""
Tests for "Köpt i år" and "Anmäl köpet" (step 4a, Task 5): the bought mark on the report's list, the purchase notice
and its kontroll item, matching a seller's sale proposal, and the notice closing once the transfer is registered.
Synthetic herds and rabbits only.

isort:skip_file
"""

import io
import os
import threading
import time
from datetime import date, datetime, timedelta
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.herd_tracking as herd_tracking
import utils.inbox as inbox
import utils.inbox_interpreter as interpreter
import utils.inbox_purge as inbox_purge
import utils.mail as mail
import utils.matrikel as matrikel
import utils.purchase_notice as purchase_notice
import utils.report_code as report_code
import utils.sale_proposal as sale_proposal
import utils.settings as settings
from herdbook import APP, limiter
from utils.arsrapport import Access, ArsrapportError
from utils.report_code import CodeActor

from tests.arsrapport_fixtures import ArsrapportTest
from tests.database_test import _USE_POSTGRES
from tests.ht_helpers import ht_row
from tests.inbox_fixtures import InboxTest, encoded, photo

DAY0 = date(2026, 1, 10)


def notices():
    return list(db.InboxItem.select().where(db.InboxItem.ref_type == "kopanmalan").order_by(db.InboxItem.id))


def until(condition, timeout=5):
    """Polls `condition` until it holds; False after `timeout` seconds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


def lock_waiter():
    """
    A session of this database waits for a lock (pg_locks): the other thread is blocked where the test expects it.
    Another xdist worker's database does not count.
    """
    (count,) = db.DB_PROXY.execute_sql(
        "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
        "WHERE NOT l.granted AND a.datname = current_database()"
    ).fetchone()
    return count > 0


def in_thread(results, key, work):
    """Runs `work` on its own connection; its result, or the exception's repr, goes to results[key]."""

    def run():
        try:
            with APP.app_context():
                results[key] = work()
        except Exception as exc:  # noqa: BLE001  # the test reports any failure, a deadlock included
            results[key] = repr(exc)
        finally:
            db.DB_PROXY.close()

    return threading.Thread(target=run)


def run_all(*threads):
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return not any(thread.is_alive() for thread in threads)


class PurchaseNoticeTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        context = APP.app_context()  # request_hash reads the app's secret key
        context.push()
        self.addCleanup(context.pop)
        patcher = mock.patch.multiple(settings.mail, link_secret="test-link-secret", link_hosts=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.at(DAY0)
        self.round_ = self.round(2025)
        self.h = db.Herd.create(genebank=self.gotland, herd="G9001", herd_name="Köparen", is_active=True)
        self.seller = db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.owner.add_role("owner", self.h.id)
        now = arsrapport.now()
        self.code = report_code.issue_code(self.h, self.round_, self.main_member(self.h, "g1@example.invalid"), now=now)
        member = self.main_member(self.seller, "g2@example.invalid")
        self.seller_code = report_code.issue_code(self.seller, self.round_, member, now=now)
        self.own = self.rabbits(self.h, 1)[0]
        self.a, self.b = self.rabbits(self.seller, 2)

    def notify(self, number=None, from_herd="G9002", when="2025-05-14", herd="G9001", year=2025):
        number = self.a.number if number is None else number
        return self.api("POST", f"/besattning/{herd}/{year}/kop", number=number, from_herd=from_herd, date=when)

    def open_link(self, code):
        response = self.client.post("/api/v2/rapport/oppna", json={"token": mail.link_token("rapport", code.id)})
        self.assertEqual(response.status_code, 200)

    def view(self):
        response = self.api("GET", "/besattning/G9001/2025")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def seller_proposes(self, month=5, day=10, year=2025):
        """G9002's link reports a sold to G9001: a sale proposal (5.9)."""
        access = arsrapport.code_access(self.seller, self.round_, [self.seller_code.id])
        body = self.body(self.sald(self.a, "G9001", year, month, day), self.kvar(self.b, vikt=2.8))
        arsrapport.submit(
            self.seller,
            self.round_,
            access,
            CodeActor(self.seller_code),
            arsrapport.parse_submission(body, paper=False),
        )
        return db.SaleProposal.get(db.SaleProposal.individual == self.a.id)

    def stored_notice(self, rabbit, when):
        """An open notice of the buyer herd as report_purchase writes it, dated `when` (another year's, here)."""
        data = {"number": rabbit.number, "from_herd": "G9002", "date": when.isoformat(), "individual_id": rabbit.id}
        return db.InboxItem.create(
            kind="kontroll", state="ny", genebank=self.gotland, herd=self.h, ref_type="kopanmalan", ref_data=data
        )

    def state(self, item):
        return db.InboxItem.get_by_id(item.id).state

    def kop_anmalt(self):
        self.login("man")
        response = self.client.get(f"/api/v2/arsrapport/2025/status?genebank_id={self.gotland.id}")
        return {row["herd"]: row["flags"]["kop_anmalt"] for row in response.get_json()["rows"]}["G9001"]

    def test_report_list_marks_bought_this_year(self):
        old, new, back = self.rabbits(self.seller, 3)
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=old, herd_tracking_date=date(2024, 6, 1))
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=new, herd_tracking_date=date(2025, 5, 14))
        # bought, sold back and bought again in the year: the latest purchase is the mark
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=back, herd_tracking_date=date(2025, 3, 1))
        ht_row("TRANSFER", from_herd=self.h, herd=self.seller, individual=back, herd_tracking_date=date(2025, 4, 1))
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=back, herd_tracking_date=date(2025, 9, 2))
        rows = {row["number"]: row["kopt"] for row in arsrapport.report_list(self.h, 2025)}
        self.assertEqual(
            rows,
            {
                self.own.number: None,
                old.number: None,
                new.number: {"datum": "2025-05-14", "fran": "G9002"},
                back.number: {"datum": "2025-09-02", "fran": "G9002"},
            },
        )

    def test_purchase_notice_creates_kontroll_item(self):
        self.login("owner")
        response = self.notify()
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        (item,) = notices()
        fields = {"number": self.a.number, "from_herd": "G9002", "date": "2025-05-14"}
        self.assertEqual(response.get_json(), {"id": item.id, **fields, "state": "ny"})
        self.assertEqual(
            (item.kind, item.state, item.herd_id, item.genebank_id, item.sender_user_id, item.ref_id),
            ("kontroll", "ny", self.h.id, self.gotland.id, None, None),
        )
        self.assertEqual(item.ref_data, {**fields, "individual_id": self.a.id})  # no personal data
        (event,) = item.events
        self.assertEqual((event.kind, event.user_id, event.detail), ("inkommen", self.owner.id, None))
        self.assertEqual(self.view()["kopanmalningar"], [{"id": item.id, **fields, "state": "ny"}])
        # the same rabbit again is the open notice, not a second one
        self.assertEqual(self.notify(when="2025-05-20").get_json()["id"], item.id)
        self.assertEqual(len(notices()), 1)
        # "utanfor" is the genebank's GX1, and the typed number is stored as Stamboken has it
        typed = f" {self.b.number.lower()} "
        self.assertEqual(self.notify(number=typed, from_herd="utanfor").get_json()["from_herd"], "GX1")
        self.assertEqual(notices()[1].ref_data["number"], self.b.number)
        self.assertEqual(self.kop_anmalt(), 2)
        self.login("man")
        detail = self.client.get(f"/api/v2/inkorg/{item.id}").get_json()
        self.assertEqual(
            (detail["ref_type"], detail["ref_data"], detail["report_year"]), ("kopanmalan", item.ref_data, None)
        )

    def test_notice_refuses_a_bad_seller_or_date_and_a_rabbit_in_the_herd(self):
        self.login("owner")
        for body, field in (
            ({"from_herd": "G9001"}, "from_herd"),  # the buyer itself
            ({"from_herd": "G0000"}, "from_herd"),
            ({"from_herd": None}, "from_herd"),
            ({"when": "2024-12-31"}, "date"),
            ({"when": "2026-01-02"}, "date"),
            ({"when": None}, "date"),
        ):
            response = self.notify(**body)
            self.assertEqual((response.status_code, response.get_json()["field"]), (400, field), body)
        response = self.notify(number=self.own.number)
        self.assertEqual((response.status_code, response.get_json()["field"]), (409, "number"))
        self.assertEqual(notices(), [])

    def test_number_not_in_stamboken_points_to_certificate_form(self):
        self.login("owner")
        response = self.notify(number="G9001-99999")
        self.assertEqual(response.status_code, 422)
        body = response.get_json()
        self.assertEqual((body["code"], body["field"]), ("inte_i_stamboken", "number"))
        self.assertEqual(body["detail"], purchase_notice.NOT_IN_STAMBOKEN)
        db.Individual.update(voided=True).where(db.Individual.id == self.b.id).execute()  # an unpromoted slot
        self.assertEqual(self.notify(number=self.b.number).status_code, 422)
        self.assertEqual(notices(), [])

    def test_manager_closes_a_notice_by_hand_in_the_queue(self):
        """A notice whose purchase never comes (a typo, a rejected sale) is taken and closed as any item."""
        self.login("owner")
        item_id = self.notify().get_json()["id"]
        self.login("man")
        self.assertEqual(self.client.post(f"/api/v2/inkorg/{item_id}/ta", json={}).status_code, 200)
        response = self.client.post(f"/api/v2/inkorg/{item_id}/lage", json={"state": "klar"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(notices()[0].state, "klar")
        self.assertEqual(self.kop_anmalt(), 0)

    def test_code_session_may_report_purchase_only_for_its_herd(self):
        self.open_link(self.code)
        response = self.notify()
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        (item,) = notices()
        (event,) = item.events
        detail = {"via": "länk G9001/2025", "access_code_id": self.code.id}
        self.assertEqual((item.herd_id, event.user_id, event.detail), (self.h.id, None, detail))
        # another herd, or another year, is not the link's: nothing is written
        self.assertEqual(self.notify(herd="G9002", number=self.own.number, from_herd="G9001").status_code, 404)
        self.assertEqual(self.notify(year=2024).status_code, 404)
        self.assertEqual(len(notices()), 1)
        # a revoked link writes nothing either (E4)
        db.ReportAccessCode.update(revoked_at=arsrapport.now()).where(db.ReportAccessCode.id == self.code.id).execute()
        self.assertEqual(self.notify(number=self.b.number).status_code, 403)
        self.assertEqual(len(notices()), 1)

    def test_notice_matches_seller_proposal_and_one_approval_settles_both(self):
        proposal = self.seller_proposes(5, 10)
        self.open_link(self.code)
        far = self.notify(number=self.b.number, when="2025-01-02").get_json()  # no proposal: the queue's item
        item = notices()[0]
        self.assertEqual(self.notify(when="2025-05-24").status_code, 200)  # 14 days after the sale
        notice = notices()[1]
        self.assertEqual(self.kop_anmalt(), 1)  # the matched one is shown with the sale instead
        self.login("man")
        (row,) = self.client.get("/api/v2/arsrapport/besattning/G9002/2025/forslag").get_json()["forslag"]
        self.assertEqual(row["kopanmalan"], purchase_notice.notice_json(notice))
        self.assertEqual(self.client.get(f"/api/v2/inkorg/{notice.id}").get_json()["report_year"], 2025)
        self.assertIsNone(self.client.get(f"/api/v2/inkorg/{item.id}").get_json()["report_year"])
        self.assertEqual(far["id"], item.id)

        passes, original = [], arsrapport._lock_items

        def spy(*args, **kwargs):  # the notice's item is locked in the one ascending pass, before the rabbit (K4)
            passes.append(original(*args, **kwargs))
            return passes[-1]

        with mock.patch.object(arsrapport, "_lock_items", side_effect=spy):
            response = self.client.post(f"/api/v2/arsrapport/forslag/{proposal.id}/godkann", json={})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(passes, [{proposal.inbox_item_id, notice.id}])
        notice = db.InboxItem.get_by_id(notice.id)
        self.assertEqual(notice.state, "klar")
        closing = notice.events.where(db.InboxEvent.kind == "lage").get()
        self.assertEqual((closing.user_id, closing.detail["note"]), (self.manager.id, "Köpet är registrerat"))
        self.assertEqual(db.InboxItem.get_by_id(item.id).state, "ny")

    def test_notice_fifteen_days_from_the_sale_is_shown_apart_and_stays_open(self):  # M1
        proposal = self.seller_proposes(5, 10)
        self.login("owner")
        self.notify(when="2025-05-25")
        (notice,) = notices()
        self.login("man")
        (row,) = self.client.get("/api/v2/arsrapport/besattning/G9002/2025/forslag").get_json()["forslag"]
        self.assertEqual((row["kopanmalan"], row["kopanmalan_avviker"]), (None, purchase_notice.notice_json(notice)))
        self.client.post(f"/api/v2/arsrapport/forslag/{proposal.id}/godkann", json={})
        # the transfer of 10 May is registered after the notice, but 15 days from its date: no look closes it
        self.assertEqual(self.state(notice), "ny")
        self.assertEqual(self.client.get(f"/api/v2/inkorg/{notice.id}").get_json()["state"], "ny")

    def test_a_notice_and_a_sale_across_new_year_are_not_one_sale(self):  # M1
        proposal = self.seller_proposes(1, 5, year=2026)  # a January sale in the seller's 2025 report
        notice = self.stored_notice(self.a, date(2025, 12, 30))  # the buyer's 2025 notice, six days before
        self.login("man")
        (row,) = self.client.get("/api/v2/arsrapport/besattning/G9002/2025/forslag").get_json()["forslag"]
        self.assertEqual((row["kopanmalan"], row["kopanmalan_avviker"]), (None, purchase_notice.notice_json(notice)))
        response = self.client.post(f"/api/v2/arsrapport/forslag/{proposal.id}/godkann", json={})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(purchase_notice.registered([notice]), set())
        self.assertEqual(self.client.get(f"/api/v2/inkorg/{notice.id}").get_json()["state"], "ny")
        self.assertEqual(self.kop_anmalt(), 1)

    def test_only_a_transfer_within_fourteen_days_and_the_same_year_closes_a_notice(self):  # M1
        before, after, late, new_year = self.rabbits(self.seller, 4)
        self.login("owner")
        dated = ((before, "2025-05-14"), (after, "2025-05-14"), (late, "2025-05-14"), (new_year, "2025-12-20"))
        for rabbit, when in dated:
            self.assertEqual(self.notify(number=rabbit.number, when=when).status_code, 200)
        moved = (
            (before, date(2025, 4, 30)),
            (after, date(2025, 5, 28)),
            (late, date(2025, 5, 29)),
            (new_year, date(2026, 1, 2)),  # 13 days on, in the next year
        )
        for rabbit, day in moved:
            ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=rabbit, herd_tracking_date=day)
        first, second, _, _ = notices()
        self.assertEqual(purchase_notice.registered(notices()), {first.id, second.id})

    def test_notice_closes_when_transfer_registered(self):
        self.login("owner")
        self.notify()
        self.notify(number=self.b.number)
        first, second = notices()
        # registered by another path, the rabbit's own sale dialog
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=self.a, herd_tracking_date=date(2025, 5, 14))
        self.assertEqual(db.InboxItem.get_by_id(first.id).state, "ny")  # no trigger
        shown = {row["id"]: row["state"] for row in self.view()["kopanmalningar"]}
        self.assertEqual(shown, {first.id: "klar", second.id: "ny"})
        self.view()  # idempotent: one closing event
        events = list(db.InboxItem.get_by_id(first.id).events.where(db.InboxEvent.kind == "lage"))
        self.assertEqual(
            [(e.user_id, e.detail) for e in events],
            [(None, {"from": "ny", "to": "klar", "note": "Köpet är registrerat"})],
        )
        # the queue's item view closes too
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=self.b, herd_tracking_date=date(2025, 5, 20))
        self.login("man")
        self.assertEqual(self.client.get(f"/api/v2/inkorg/{second.id}").get_json()["state"], "klar")
        self.assertEqual(self.kop_anmalt(), 0)

    def test_an_earlier_stay_in_the_herd_does_not_close_the_notice(self):
        """The bought-back case: an old TRANSFER into the buyer herd is not this purchase."""
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=self.a, herd_tracking_date=date(2023, 3, 1))
        ht_row("TRANSFER", from_herd=self.h, herd=self.seller, individual=self.a, herd_tracking_date=date(2024, 3, 1))
        self.login("owner")
        self.assertEqual(self.notify().status_code, 200)
        self.assertEqual([row["state"] for row in self.view()["kopanmalningar"]], ["ny"])
        self.assertEqual(self.kop_anmalt(), 1)
        self.assertEqual(purchase_notice.registered(notices()), set())
        # this purchase, registered after the notice with a date within 14 days of it
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=self.a, herd_tracking_date=date(2025, 5, 1))
        self.assertEqual(purchase_notice.registered(notices()), {notices()[0].id})

    def test_another_genebanks_rabbit_or_herd_is_answered_as_missing(self):
        """A Gotland report cannot learn whether a Mellerud number or herd exists (finding 1)."""
        mellerud = db.Herd.create(genebank=self.mellerud, herd="M9001", is_active=True)
        db.Herd.create(genebank=self.mellerud, herd="MX1", is_active=True)
        (foreign,) = self.rabbits(mellerud, 1)
        self.login("owner")

        def answer(**body):
            response = self.notify(**body)
            return response.status_code, response.get_json()

        self.assertEqual(answer(number=foreign.number), answer(number="M9001-99999"))
        self.assertEqual(answer(number=foreign.number)[0], 422)
        missing = answer(from_herd="M0000")
        self.assertEqual(missing[0], 400)
        self.assertEqual(answer(from_herd="M9001"), missing)
        self.assertEqual(answer(from_herd="MX1"), missing)  # another genebank's outside herd too
        self.assertEqual(notices(), [])

    def test_a_stay_that_ended_before_the_purchase_does_not_close_it(self):
        """In 1 May, out 5 May, bought again 10 May: the first stay is not this purchase (finding 2)."""
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=self.a, herd_tracking_date=date(2025, 5, 1))
        ht_row("TRANSFER", from_herd=self.h, herd=self.seller, individual=self.a, herd_tracking_date=date(2025, 5, 5))
        self.login("owner")
        self.notify(when="2025-05-10")
        # the same stay registered after the notice (backfilled) is no more this purchase
        self.notify(number=self.b.number, when="2025-05-10")
        first, second = notices()
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=self.b, herd_tracking_date=date(2025, 5, 1))
        ht_row("TRANSFER", from_herd=self.h, herd=self.seller, individual=self.b, herd_tracking_date=date(2025, 5, 5))
        self.assertEqual(purchase_notice.registered(notices()), set())
        self.assertEqual([row["state"] for row in self.view()["kopanmalningar"]], ["ny", "ny"])
        # the purchase itself, registered on the reported day
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=self.b, herd_tracking_date=date(2025, 5, 10))
        self.assertEqual(purchase_notice.registered(notices()), {second.id})
        self.assertEqual((self.state(first), self.state(second)), ("ny", "ny"))

    def test_two_first_openings_in_the_queue_do_not_deadlock(self):
        """Both log their opening, then close the notice: the item's lock comes before the event (finding 3)."""
        if not _USE_POSTGRES:
            self.skipTest("row locks need PostgreSQL")
        self.login("owner")
        item_id = self.notify().get_json()["id"]
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=self.a, herd_tracking_date=date(2025, 5, 14))
        opened, original, results = [], inbox.open_item, {}

        def opened_then_wait(item, user):
            original(item, user)
            opened.append(user.id)
            # both events are in before either closes it, unless the other waits for the item's lock
            until(lambda: len(opened) == 2 or lock_waiter())

        def look(username):
            def work():
                client = APP.test_client(use_cookies=True)
                client.post("/api/login", json={"username": username, "password": "pass"})
                return client.get(f"/api/v2/inkorg/{item_id}").status_code

            return work

        with mock.patch.object(inbox, "open_item", side_effect=opened_then_wait):
            done = run_all(in_thread(results, "man", look("man")), in_thread(results, "admin", look("admin")))
        self.assertTrue(done, "hung threads")
        self.assertEqual(results, {"man": 200, "admin": 200})
        item = db.InboxItem.get_by_id(item_id)
        self.assertEqual(item.state, "klar")
        self.assertEqual(item.events.where(db.InboxEvent.kind == "lage").count(), 1)

    def test_a_void_of_the_transfer_comes_before_the_closing_or_after(self):
        """The closing reads the transfer again under the rabbit's lock, which the void holds (finding 4)."""
        if not _USE_POSTGRES:
            self.skipTest("row locks need PostgreSQL")
        self.login("owner")
        item_id = self.notify().get_json()["id"]
        move = ht_row(
            "TRANSFER", from_herd=self.seller, herd=self.h, individual=self.a, herd_tracking_date=date(2025, 5, 14)
        )
        voided, original, results = threading.Event(), herd_tracking._assert_no_new_violations, {}

        def void_held_open(*args, **kwargs):
            original(*args, **kwargs)
            voided.set()
            until(lock_waiter)  # the closing waits for the rabbit before the void commits

        def void():
            herd_tracking.void_herd_tracking(move.id, db.User.get_by_id(self.admin.id), "Fel rad", typed=False)
            return "ok"

        def look():
            voided.wait(10)
            client = APP.test_client(use_cookies=True)
            client.post("/api/login", json={"username": "man", "password": "pass"})
            return client.get(f"/api/v2/inkorg/{item_id}").status_code

        with mock.patch.object(herd_tracking, "_assert_no_new_violations", side_effect=void_held_open):
            done = run_all(in_thread(results, "void", void), in_thread(results, "look", look))
        self.assertTrue(done, "hung threads")
        self.assertEqual(results, {"void": "ok", "look": 200})
        self.assertEqual(db.InboxItem.get_by_id(item_id).state, "ny")

    def test_approval_and_a_notice_of_another_year_are_one_after_the_other(self):
        """
        A January sale in the seller's 2025 report and the buyer's 2026 notice of it take no common report lock;
        the purchase's own lock makes "one approval settles both" hold (finding 5).
        """
        if not _USE_POSTGRES:
            self.skipTest("advisory locks need PostgreSQL")
        proposal = self.seller_proposes(1, 8, year=2026)
        round_2026 = self.round(2026)
        self.at(date(2027, 1, 10))  # the 2026 round is open; the 2025 sale is approved after its end_date
        original, results, locked = arsrapport._lock_items, {}, threading.Event()

        def items_after_the_notice_waits(*args, **kwargs):
            locked.set()  # the approval has read the buyer's notices, under the purchase's lock
            until(lock_waiter)  # the notice waits for that lock
            return original(*args, **kwargs)

        def approve():
            sale_proposal.approve(proposal, db.User.get_by_id(self.manager.id), now=arsrapport.now())
            return "ok"

        def report():
            try:
                purchase_notice.report_purchase(
                    self.h,
                    round_2026,
                    Access("owner"),
                    self.owner,
                    number=self.a.number,
                    from_herd="G9002",
                    date=date(2026, 1, 12),
                )
            except ArsrapportError as exc:
                return exc.status, exc.detail
            return "created"

        with mock.patch.object(arsrapport, "_lock_items", side_effect=items_after_the_notice_waits):
            approving = in_thread(results, "approve", approve)
            approving.start()
            locked.wait(10)
            done = run_all(in_thread(results, "notice", report))
            approving.join(timeout=30)
        self.assertTrue(done and not approving.is_alive(), "hung threads")
        self.assertEqual(results, {"approve": "ok", "notice": (409, f"{self.a.number} står redan i din besättning.")})
        self.assertEqual([item.state for item in notices()], [])

    def test_an_open_notice_of_another_year_is_a_409(self):
        """A 2025 link neither gets a 2024 notice back nor makes a second one (finding 6)."""
        old = self.stored_notice(self.a, date(2024, 11, 2))
        self.open_link(self.code)
        response = self.notify()
        self.assertEqual(response.status_code, 409, response.get_data(as_text=True))
        self.assertEqual(
            (response.get_json()["field"], response.get_json()["detail"]),
            ("number", f"Köpet av {self.a.number} är redan anmält för 2024."),
        )
        self.assertEqual(notices(), [old])

    def test_the_report_view_closes_only_its_own_years_notices(self):
        """GET 2025 closes a registered 2025 notice and leaves a registered 2024 one alone (finding 6)."""
        old = self.stored_notice(self.b, date(2024, 11, 2))
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=self.b, herd_tracking_date=date(2024, 11, 2))
        self.login("owner")
        new = self.notify().get_json()
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=self.a, herd_tracking_date=date(2025, 5, 14))
        self.assertEqual(self.view()["kopanmalningar"], [{**new, "state": "klar"}])
        self.assertEqual(self.state(old), "ny")

    def test_a_link_revoked_since_its_check_closes_nothing(self):
        """The view's closing is a write: E4 again under the report's lock (finding 6)."""
        self.open_link(self.code)
        item_id = self.notify().get_json()["id"]
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=self.a, herd_tracking_date=date(2025, 5, 14))
        db.ReportAccessCode.update(revoked_at=arsrapport.now()).where(db.ReportAccessCode.id == self.code.id).execute()
        stale = Access("code", code=db.ReportAccessCode.get_by_id(self.code.id))  # as read before the revoke
        with mock.patch.object(arsrapport, "code_access", return_value=stale):
            response = self.api("GET", "/besattning/G9001/2025")
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "lank_ogiltig"))
        self.assertEqual(db.InboxItem.get_by_id(item_id).state, "ny")

    def test_a_notice_reads_an_end_date_moved_earlier_meanwhile(self):  # Codex round 2, P2
        if not _USE_POSTGRES:
            self.skipTest("row locks need PostgreSQL")
        original, results, moved = arsrapport.follow_end_date, {}, threading.Event()

        def held(round_):
            original(round_)
            moved.set()
            until(lock_waiter)  # the notice waits for the round row
            return None

        def close():  # the round ends on 5 January, before DAY0
            day = date(2026, 1, 5)
            return arsrapport.save_round(2025, db.User.get_by_id(self.admin.id), deadline=day, end_date=day).end_date

        def report():
            moved.wait(10)
            try:
                purchase_notice.report_purchase(
                    self.h,
                    self.round_,
                    Access("owner"),
                    self.owner,
                    number=self.a.number,
                    from_herd="G9002",
                    date=date(2025, 5, 14),
                )
            except ArsrapportError as exc:
                return exc.status, exc.extra.get("code")
            return "created"

        with mock.patch.object(arsrapport, "follow_end_date", side_effect=held):
            done = run_all(in_thread(results, "close", close), in_thread(results, "notice", report))
        self.assertTrue(done, "hung threads")
        self.assertEqual(results, {"close": date(2026, 1, 5), "notice": (409, "rundan_stangd")})
        self.assertEqual(notices(), [])

    def test_a_closed_or_unactivated_round_takes_no_notice(self):
        """The report's own rule for writing, under its lock (finding 7)."""
        self.login("owner")
        self.at(date(2026, 4, 1))  # after end_date: the owner's report is read-only
        response = self.notify()
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "rundan_stangd"))
        self.login("man")  # an editor still writes after end_date, as in the report
        self.assertEqual(self.notify(number=self.b.number).status_code, 200)
        self.at(DAY0)
        db.YearlyReportRoundGenebank.delete().where(db.YearlyReportRoundGenebank.round == self.round_.id).execute()
        self.login("owner")
        response = self.notify()
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "rundan_stangd"))
        self.assertEqual([item.ref_data["individual_id"] for item in notices()], [self.b.id])

    # The photo field (4a Task 5, wired to 4b's report upload): a photo of the transfer proof or the certificate, bound
    # to the notice under the photo's item lock and the session's own uploads, as a rabbit's photo is (FC1)

    def upload(self, client=None, purpose=None):
        data = {"file": (io.BytesIO(encoded(photo((600, 800)))), "bevis.jpg")}
        query = f"?syfte={purpose}" if purpose else ""
        response = (client or self.client).post(
            f"/api/v2/arsrapport/besattning/G9001/2025/foto{query}", data=data, content_type="multipart/form-data"
        )
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return response.get_json()

    def notify_with(self, document_id, doc_type="bevis", number=None, client=None):
        body = {"number": number or self.a.number, "from_herd": "G9002", "date": "2025-05-14"}
        body |= {"document_id": document_id, "doc_type": doc_type}
        return (client or self.client).post("/api/v2/arsrapport/besattning/G9001/2025/kop", json=body)

    @staticmethod
    def heard(item):
        """The queue's workers told of `item` (ny_post), one row per notice."""
        rows = db.Notice.select().where(db.Notice.item == item.id, db.Notice.kind == "ny_post")
        return sorted(row.user_id for row in rows)

    def test_photo_is_bound_to_the_notice_and_the_queue_hears_of_it_once(self):
        self.open_link(self.code)
        uploaded = self.upload()
        response = self.notify_with(uploaded["document_id"])
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        (item,) = notices()
        (document,) = item.documents
        self.assertEqual(
            (document.id, document.doc_type, document.interpretation_status), (uploaded["document_id"], "bevis", "av")
        )
        self.assertFalse(db.InboxItem.select().where(db.InboxItem.id == uploaded["item_id"]).exists())
        (event,) = item.events
        detail = {"via": "länk G9001/2025", "access_code_id": self.code.id, "documents": 1}
        self.assertEqual((event.kind, event.detail), ("inkommen", detail))
        self.assertEqual(item.member_id, self.code.member_id)
        heard = self.heard(item)
        self.assertIn(self.helper.id, heard)
        self.assertEqual(len(heard), len(set(heard)))
        # the same request again, as after a lost answer: the notice, with nothing written or told twice
        again = self.notify_with(uploaded["document_id"])
        self.assertEqual((again.status_code, again.get_json()["id"]), (200, item.id))
        self.assertEqual((self.heard(item), item.documents.count(), item.events.count()), (heard, 1, 1))

    def test_erasing_the_links_member_removes_its_notice_and_photo(self):
        """An erasure of the member the link went to finds the notice sent through it; the photo's file goes too."""
        self.open_link(self.code)
        uploaded = self.upload()
        item_id = self.notify_with(uploaded["document_id"]).get_json()["id"]
        original = os.path.join(self.folder, db.InboxDocument.get_by_id(uploaded["document_id"]).original_path)
        self.assertTrue(os.path.exists(original))
        matrikel.anonymize_person(db.Member.get_by_id(self.code.member_id), self.admin)
        self.assertFalse(db.InboxItem.select().where(db.InboxItem.id == item_id).exists())
        self.assertFalse(db.InboxDocument.select().where(db.InboxDocument.id == uploaded["document_id"]).exists())
        self.assertFalse(os.path.exists(original))

    def test_an_accounts_notice_records_its_person(self):
        holder = db.Member.get_by_id(self.code.member_id)
        db.Member.update(user=self.owner).where(db.Member.id == holder.id).execute()
        self.login("owner")
        item_id = self.notify().get_json()["id"]
        item = db.InboxItem.get_by_id(item_id)
        self.assertEqual((item.member_id, item.events.get().user_id), (holder.id, self.owner.id))

    def test_a_notice_without_a_photo_is_told_with_its_first_photo(self):
        self.login("owner")
        item_id = self.notify().get_json()["id"]
        (item,) = notices()
        self.assertEqual(self.heard(item), [])  # as before the photo field: nobody hears of a notice without one
        first = self.upload()
        self.assertEqual(self.notify_with(first["document_id"], "intyg").get_json()["id"], item_id)
        heard = self.heard(item)
        self.assertIn(self.helper.id, heard)
        (document,) = item.documents
        self.assertEqual((document.doc_type, document.interpretation_status), ("intyg", "av"))  # not read on a notice
        second = self.upload()
        self.assertEqual(self.notify_with(second["document_id"]).get_json()["id"], item_id)
        self.assertEqual(self.heard(item), heard)  # once
        self.assertEqual(item.documents.count(), 2)

    def test_the_photo_must_be_this_sessions_own_and_still_unbound(self):
        self.open_link(self.code)
        theirs = self.upload()  # the link's session
        self.login("owner")  # another actor in the same browser: not its photo (FC1)
        refused = self.notify_with(theirs["document_id"])
        self.assertEqual((refused.status_code, refused.get_json()["field"]), (403, "photo"))
        self.assertEqual(refused.get_json()["detail"], arsrapport.PHOTO_NOT_OURS)
        mine = self.upload()
        missing = self.notify_with(mine["document_id"], doc_type=None)
        self.assertEqual((missing.status_code, missing.get_json()["field"]), (400, "doc_type"))
        gone = self.notify_with(mine["document_id"] + 1000)
        self.assertEqual((gone.status_code, gone.get_json()["detail"]), (403, arsrapport.PHOTO_NOT_OURS))
        self.assertEqual(notices(), [])
        # a photo the queue has scrapped can no longer be bound
        db.InboxItem.update(state="skrap").where(db.InboxItem.id == mine["item_id"]).execute()
        scrapped = self.notify_with(mine["document_id"])
        self.assertEqual((scrapped.status_code, scrapped.get_json()["detail"]), (409, arsrapport.PHOTO_GONE))
        self.assertEqual(notices(), [])

    def test_a_notice_with_a_photo_closes_in_the_queue_once_its_photo_is_dismissed(self):
        """The queue's rule: an item closes by hand once its documents are done; dismissing the photo closes it."""
        self.login("owner")
        uploaded = self.upload()
        item_id = self.notify_with(uploaded["document_id"]).get_json()["id"]
        self.login("man")
        self.assertEqual(self.client.post(f"/api/v2/inkorg/{item_id}/ta", json={}).status_code, 200)
        refused = self.client.post(f"/api/v2/inkorg/{item_id}/lage", json={"state": "klar"})
        self.assertEqual(refused.status_code, 400)  # with a document, "klar" comes from its documents only
        path = f"/api/v2/inkorg/{item_id}/dokument/{uploaded['document_id']}"
        response = self.client.patch(path, json={"dismissed": True})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(self.state(db.InboxItem.get_by_id(item_id)), "klar")
        self.assertEqual(self.kop_anmalt(), 0)

    # A notice's photo is never read by the model, with the image reading on (Codex P1 and P2)

    def reading_on(self):
        """The image reading on, with a model that records what it is given: the list of images read."""
        read = []

        def model(image, schema):
            read.append(image)
            return {"genbanksnr": "G9002", "ar_kull_individ": "2501", "namn": "Läst"}

        for patcher in (
            mock.patch.object(settings.interpretation, "interpreter", "gemma"),
            mock.patch.dict(interpreter.INTERPRETERS, {"gemma": model}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        return read

    def test_a_purchase_upload_is_never_read(self):
        read = self.reading_on()
        self.login("owner")
        uploaded = self.upload(purpose="kop")
        self.assertEqual(db.InboxDocument.get_by_id(uploaded["document_id"]).interpretation_status, "av")
        self.assertIsNone(interpreter.interpret_next())  # not between the upload and the notice either
        self.assertEqual(self.notify_with(uploaded["document_id"], "intyg").status_code, 200)
        self.assertIsNone(interpreter.interpret_next())
        self.assertEqual(read, [])

    def test_a_reading_made_before_the_photo_became_a_notice_goes(self):
        self.reading_on()
        self.login("owner")
        uploaded = self.upload()  # a rabbit's photo
        # uploaded before they were held (item 12): an ordinary one, which waits for the reading
        db.InboxItem.update(ref_data=None).where(db.InboxItem.id == uploaded["item_id"]).execute()
        db.InboxDocument.update(interpretation_status="vantar").where(
            db.InboxDocument.id == uploaded["document_id"]
        ).execute()
        self.assertEqual(interpreter.interpret_next(), uploaded["document_id"])
        self.assertEqual(db.InboxDocument.get_by_id(uploaded["document_id"]).interpretation_status, "klar")
        self.assertEqual(self.notify_with(uploaded["document_id"], "intyg").status_code, 200)
        document = db.InboxDocument.get_by_id(uploaded["document_id"])
        self.assertEqual(
            (document.interpretation_status, document.interpretation, document.proposal, document.interpreted_at),
            ("av", None, None, None),
        )
        self.assertIsNone(interpreter.interpret_next())

    def test_the_queue_never_sends_a_notice_photo_to_be_read(self):
        """Neither a new type, Tolka igen nor a status set to waiting has the worker read a notice's photo."""
        read = self.reading_on()
        self.login("owner")
        uploaded = self.upload(purpose="kop")
        item_id = self.notify_with(uploaded["document_id"], "bevis").get_json()["id"]
        self.login("man")
        self.assertEqual(self.client.post(f"/api/v2/inkorg/{item_id}/ta", json={}).status_code, 200)
        path = f"/api/v2/inkorg/{item_id}/dokument/{uploaded['document_id']}"
        retyped = self.client.patch(path, json={"doc_type": "intyg"})
        self.assertEqual(retyped.status_code, 200, retyped.get_data(as_text=True))
        self.assertEqual(db.InboxDocument.get_by_id(uploaded["document_id"]).interpretation_status, "av")
        again = self.client.post(f"{path}/tolka-igen", json={})
        self.assertEqual((again.status_code, again.get_json()["detail"]), (409, inbox.NOTICE_UNREAD))
        waiting = db.InboxDocument.update(interpretation_status="vantar")
        waiting.where(db.InboxDocument.id == uploaded["document_id"]).execute()
        self.assertIsNone(interpreter.interpret_next())
        self.assertEqual(read, [])

    # S7: a rabbit Stamboken lacks. The buyer sends the photos of its certificate and transfer proof to the queue as an
    # ordinary upload, with the purchase's fields, and the manager registers and transfers it

    NEW = "G9002-25099"  # not in Stamboken

    def send(self, *uploads, number=NEW, types=("intyg", "bevis"), herd="G9001", year=2025, client=None):
        documents = [{"id": u["document_id"], "doc_type": t} for u, t in zip(uploads, types, strict=False)]
        body = {"number": number, "from_herd": "G9002", "date": "2025-05-14", "documents": documents}
        return (client or self.client).post(f"/api/v2/arsrapport/besattning/{herd}/{year}/kop/inskick", json=body)

    @staticmethod
    def uploads():
        return list(db.InboxItem.select().where(db.InboxItem.kind == "upload").order_by(db.InboxItem.id))

    def test_owner_sends_photos_as_an_ordinary_upload(self):
        self.login("owner")
        first, second = self.upload(purpose="inskick"), self.upload(purpose="inskick")
        response = self.send(first, second, number=f" {self.NEW.lower()} ")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        (item,) = self.uploads()
        fields = {"number": self.NEW, "from_herd": "G9002", "date": "2025-05-14"}
        self.assertEqual(response.get_json(), {"id": item.id, **fields, "state": "ny"})
        # the receipt a retry is known by: the photos' own items, and a hash of who sent what for which year
        stored = {**fields, "receipt": {"staged": [first["item_id"], second["item_id"]], "request": mock.ANY}}
        self.assertEqual(
            (item.state, item.herd_id, item.genebank_id, item.sender_user_id, item.ref_type, item.ref_data),
            ("ny", self.h.id, self.gotland.id, self.owner.id, None, stored),
        )
        documents = [(d.id, d.doc_type) for d in item.documents.order_by(db.InboxDocument.id)]
        self.assertEqual(documents, [(first["document_id"], "intyg"), (second["document_id"], "bevis")])
        staged = db.InboxItem.select().where(db.InboxItem.id.in_([first["item_id"], second["item_id"]]))
        self.assertFalse(staged.exists())  # the photos' own items went
        (event,) = item.events
        self.assertEqual((event.kind, event.user_id, event.detail), ("inkommen", self.owner.id, {"documents": 2}))
        heard = self.heard(item)
        self.assertIn(self.helper.id, heard)
        self.assertEqual(len(heard), len(set(heard)))
        # the same request again, as after a lost answer: the item, with nothing written or told twice
        again = self.send(first, second)
        self.assertEqual((again.status_code, again.get_json()["id"]), (200, item.id))
        self.assertEqual((len(self.uploads()), self.heard(item), item.events.count()), (1, heard, 1))
        self.assertEqual(notices(), [])  # not a notice
        # the queue's item view: an upload its workers register from, with the purchase beside it
        self.login("man")
        detail = self.client.get(f"/api/v2/inkorg/{item.id}").get_json()
        self.assertEqual((detail["kind"], detail["ref_type"], detail["ref_data"]), ("upload", None, stored))
        self.assertEqual(self.client.post(f"/api/v2/inkorg/{item.id}/ta", json={}).status_code, 200)
        # registered and transferred while a worker holds it: opening it does not close it under the worker's hands
        rabbit = db.Individual.create(origin_herd=self.seller, number=self.NEW, sex="female")
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=rabbit, herd_tracking_date=date(2025, 5, 20))
        self.assertEqual(self.client.get(f"/api/v2/inkorg/{item.id}").get_json()["state"], "tagen")

    def test_link_sends_photos_and_its_code_is_the_sender(self):
        self.open_link(self.code)
        uploaded = self.upload(purpose="inskick")
        response = self.send(uploaded)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        (item,) = self.uploads()
        self.assertEqual((item.herd_id, item.sender_user_id, item.member_id), (self.h.id, None, self.code.member_id))
        (event,) = item.events
        detail = {"via": "länk G9001/2025", "access_code_id": self.code.id, "documents": 1}
        self.assertEqual((event.user_id, event.detail), (None, detail))
        self.assertIn(self.helper.id, self.heard(item))

    def test_a_link_sent_case_mails_its_member_when_it_is_done(self):
        """Codex P1: the queue's mails about a link's sent photos go to the member the link went to."""
        self.open_link(self.code)
        uploaded = self.upload(purpose="inskick")
        item_id = self.send(uploaded).get_json()["id"]
        self.login("man")
        self.assertEqual(self.client.post(f"/api/v2/inkorg/{item_id}/ta", json={}).status_code, 200)
        path = f"/api/v2/inkorg/{item_id}/dokument/{uploaded['document_id']}"
        self.assertEqual(self.client.patch(path, json={"dismissed": True}).status_code, 200)
        (row,) = db.MailMessage.select().where(db.MailMessage.kind == "inlasning.klar")
        self.assertEqual((row.recipient_kind, row.recipient_id), ("member", self.code.member_id))
        self.assertEqual(mail.RECIPIENT_KINDS["member"](row.recipient_id).address, "g1@example.invalid")
        self.assertEqual(mail.MAIL_KINDS["inlasning.klar"].build(row.params)["account"], False)  # the mail is built

    def test_erasing_the_links_member_removes_its_sent_photos(self):
        """Codex P1: an erasure of the member the link went to finds the photos sent through it, and their files go."""
        self.open_link(self.code)
        uploaded = self.upload(purpose="inskick")
        item_id = self.send(uploaded).get_json()["id"]
        original = os.path.join(self.folder, db.InboxDocument.get_by_id(uploaded["document_id"]).original_path)
        self.assertTrue(os.path.exists(original))
        matrikel.anonymize_person(db.Member.get_by_id(self.code.member_id), self.admin)
        self.assertFalse(db.InboxItem.select().where(db.InboxItem.id == item_id).exists())
        self.assertFalse(os.path.exists(original))

    def test_a_retry_needs_its_receipt_and_reveals_nothing_of_another_case(self):
        """
        Codex P1: sent photos answer with their item only to the same actor, from the session that uploaded them, for
        the same herd, year and payload. A link naming another sender's photos of a 2024 case, with its number, is
        refused like any photo not its own, and learns nothing of that case.
        """
        self.login("owner")
        uploaded = self.upload(purpose="inskick")
        item_id = self.send(uploaded).get_json()["id"]
        case = db.InboxItem.get_by_id(item_id)  # the owner's case, as one sent for 2024
        dated = {**case.ref_data, "date": "2024-11-02"}
        db.InboxItem.update(ref_data=dated).where(db.InboxItem.id == item_id).execute()
        link = APP.test_client(use_cookies=True)
        token = mail.link_token("rapport", self.code.id)
        self.assertEqual(link.post("/api/v2/rapport/oppna", json={"token": token}).status_code, 200)
        elsewhere = APP.test_client(use_cookies=True)  # the owner in another browser: not the uploading session
        elsewhere.post("/api/login", json={"username": "owner", "password": "pass"})
        for client in (link, elsewhere):
            refused = self.send(uploaded, client=client)
            self.assertEqual((refused.status_code, refused.get_json()["detail"]), (403, arsrapport.PHOTO_NOT_OURS))
            self.assertFalse({"id", "number", "from_herd", "date", "state"} & set(refused.get_json()))
            self.assertNotIn("2024-11-02", refused.get_data(as_text=True))
        changed = self.send(uploaded, types=("bevis",))  # the same session, another payload: not the same request
        self.assertEqual(changed.status_code, 403)
        again = self.send(uploaded)  # the same request again: its receipt
        self.assertEqual((again.status_code, again.get_json()["id"]), (200, item_id))
        self.assertEqual(len(self.uploads()), 1)

    def test_sending_photos_is_refused_for_another_herd_year_round_or_photo(self):
        self.open_link(self.code)
        uploaded = self.upload(purpose="inskick")
        self.assertEqual(self.send(uploaded, herd="G9002").status_code, 404)  # not the link's herd
        self.assertEqual(self.send(uploaded, year=2024).status_code, 404)  # nor its year
        known = self.send(uploaded, number=self.a.number)  # a rabbit Stamboken has is a notice
        self.assertEqual((known.status_code, known.get_json()["field"]), (409, "number"))
        none = self.send()
        self.assertEqual((none.status_code, none.get_json()["field"]), (400, "photo"))
        untyped = self.send(uploaded, types=("annat",))
        self.assertEqual((untyped.status_code, untyped.get_json()["field"]), (400, "doc_type"))
        self.login("owner")  # another actor in the same browser: not its photo (FC1)
        theirs = self.send(uploaded)
        self.assertEqual((theirs.status_code, theirs.get_json()["detail"]), (403, arsrapport.PHOTO_NOT_OURS))
        mine = self.upload(purpose="inskick")
        self.at(date(2026, 4, 1))  # after end_date: the owner's report is read-only
        closed = self.send(mine)
        self.assertEqual((closed.status_code, closed.get_json()["code"]), (409, "rundan_stangd"))
        self.assertEqual(self.uploads(), [])
        # a revoked link sends nothing either (E4)
        self.at(DAY0)
        self.client.get("/api/logout")
        self.open_link(self.code)
        db.ReportAccessCode.update(revoked_at=arsrapport.now()).where(db.ReportAccessCode.id == self.code.id).execute()
        self.assertEqual(self.send(uploaded).status_code, 403)
        self.assertEqual(self.uploads(), [])

    def test_sent_photos_are_read_as_an_upload(self):
        read = self.reading_on()
        self.login("owner")
        certificate, proof = self.upload(purpose="inskick"), self.upload(purpose="inskick")
        self.assertIsNone(interpreter.interpret_next())  # not before they are sent
        self.assertEqual(self.send(certificate, proof).status_code, 200)
        self.assertEqual(interpreter.interpret_next(), certificate["document_id"])
        self.assertIsNone(interpreter.interpret_next())  # a transfer proof is not read
        self.assertEqual(len(read), 1)
        self.assertEqual(db.InboxDocument.get_by_id(proof["document_id"]).interpretation_status, "av")

    def test_the_photo_limit_is_the_report_uploads(self):
        limiter.reset()
        limiter.enabled = True
        self.addCleanup(limiter.reset)
        self.addCleanup(setattr, limiter, "enabled", False)
        self.open_link(self.code)
        empty = [self.client.post("/api/v2/arsrapport/besattning/G9001/2025/foto").status_code for _ in range(60)]
        self.assertEqual(empty, [400] * 60)
        data = {"file": (io.BytesIO(encoded(photo((600, 800)))), "intyg.jpg")}
        refused = self.client.post(
            "/api/v2/arsrapport/besattning/G9001/2025/foto?syfte=inskick", data=data, content_type="multipart/form-data"
        )
        self.assertEqual(refused.status_code, 429)

    def test_only_held_photos_can_be_sent(self):
        self.login("owner")
        plain = self.upload()  # a rabbit's photo, held for its registration (item 12), not for sending
        response = self.send(plain)
        self.assertEqual((response.status_code, response.get_json()["detail"]), (409, arsrapport.PHOTO_GONE))
        self.assertEqual(self.uploads(), [])
        self.assertTrue(db.InboxDocument.select().where(db.InboxDocument.id == plain["document_id"]).exists())
        self.assertTrue(db.InboxItem.select().where(db.InboxItem.id == plain["item_id"]).exists())

    def test_number_is_a_rabbit_number(self):
        self.login("owner")
        uploaded = self.upload(purpose="inskick")
        refused = self.send(uploaded, number="Kalle Anka")
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(
            (refused.get_json()["field"], refused.get_json()["detail"]),
            ("number", "Skriv kaninens individnummer, till exempel G1234-2501."),
        )
        self.assertEqual(self.uploads(), [])

    def test_a_held_photo_records_its_member(self):
        self.open_link(self.code)
        uploaded = self.upload(purpose="inskick")
        self.assertEqual(db.InboxItem.get_by_id(uploaded["item_id"]).member_id, self.code.member_id)
        original = os.path.join(self.folder, db.InboxDocument.get_by_id(uploaded["document_id"]).original_path)
        self.assertTrue(os.path.exists(original))
        matrikel.anonymize_person(db.Member.get_by_id(self.code.member_id), self.admin)
        self.assertFalse(db.InboxItem.select().where(db.InboxItem.id == uploaded["item_id"]).exists())
        self.assertFalse(os.path.exists(original))

    def test_a_missing_photo_answers_as_another_actors(self):
        self.login("owner")
        mine = self.upload(purpose="inskick")
        missing = self.send({"document_id": 999999})
        self.client.get("/api/logout")
        self.open_link(self.code)  # the link is not the owner's session
        theirs = self.send(mine)
        self.assertEqual((missing.status_code, theirs.status_code), (403, 403))
        self.assertEqual(missing.get_json(), theirs.get_json())
        # the notice's photo field too
        gone = self.notify_with(999999)
        other = self.notify_with(mine["document_id"])
        self.assertEqual((gone.status_code, gone.get_json()), (other.status_code, other.get_json()))
        self.assertEqual(gone.status_code, 403)

    def test_the_send_limit_is_20_per_hour_and_counts_sends_only(self):
        limiter.reset()
        limiter.enabled = True
        self.addCleanup(limiter.reset)
        self.addCleanup(setattr, limiter, "enabled", False)
        self.login("owner")
        for _ in range(3):  # refused sends spend nothing
            self.assertEqual(self.send(number="Kalle Anka").status_code, 400)
        for n in range(20):
            uploaded = self.upload(purpose="inskick")
            number = f"G9002-25{n + 10:02d}"
            self.assertEqual(self.send(uploaded, number=number).status_code, 200)
        refused = self.send(self.upload(purpose="inskick"))
        self.assertEqual((refused.status_code, refused.mimetype), (429, "application/problem+json"))
        self.assertIn("Du har skickat många köp den senaste timmen", refused.get_json()["detail"])

    def test_sent_photos_show_registered_and_only_the_queue_closes_them(self):
        self.login("owner")
        uploaded = self.upload(purpose="inskick")
        item_id = self.send(uploaded).get_json()["id"]

        def state():
            return {row["id"]: row for row in self.view()["arenden"]}[item_id]["state"]

        expected = {"id": item_id, "what": "kop_saknas", "number": self.NEW, "photos": 1, "state": "vantar"}
        self.assertEqual({row["id"]: row for row in self.view()["arenden"]}[item_id], expected)
        self.assertEqual(self.kop_anmalt(), 1)  # the status view counts it as a purchase reported
        # the manager registers it in its birth herd, takes the item, and transfers the rabbit to the buyer
        rabbit = db.Individual.create(origin_herd=self.seller, number=self.NEW, sex="female")
        ht_row("BIRTH", herd=self.seller, individual=rabbit, herd_tracking_date=date(2024, 5, 1))
        self.assertEqual(self.client.post(f"/api/v2/inkorg/{item_id}/ta", json={}).status_code, 200)
        ht_row("TRANSFER", from_herd=self.seller, herd=self.h, individual=rabbit, herd_tracking_date=date(2025, 5, 20))
        self.assertEqual(self.kop_anmalt(), 0)
        # the member reloads the report while the worker holds the item: it stays open in the worker's hands
        self.login("owner")
        self.assertEqual(state(), "registrerad")
        item = db.InboxItem.get_by_id(item_id)
        self.assertEqual((item.state, item.assigned_to_id), ("tagen", self.manager.id))
        self.assertFalse(item.events.where(db.InboxEvent.kind == "lage").exists())
        # the queue closes it, the way it closes an upload: its last document done
        self.login("man")
        path = f"/api/v2/inkorg/{item_id}/dokument/{uploaded['document_id']}"
        self.assertEqual(self.client.patch(path, json={"dismissed": True}).status_code, 200)
        self.login("owner")
        self.assertEqual(state(), "klart")

    def test_a_held_purchase_photo_is_never_read_before_it_is_sent(self):
        """Codex round 2: a handler who retypes a held photo, or asks for a new reading, has the worker read nothing."""
        read = self.reading_on()
        for purpose in ("kop", "inskick"):
            with self.subTest(purpose=purpose):
                self.login("owner")
                uploaded = self.upload(purpose=purpose)
                self.assertEqual(db.InboxItem.get_by_id(uploaded["item_id"]).ref_data, {"syfte": purpose})
                self.login("man")
                item_path = f"/api/v2/inkorg/{uploaded['item_id']}"
                self.assertEqual(self.client.post(f"{item_path}/ta", json={}).status_code, 200)
                path = f"{item_path}/dokument/{uploaded['document_id']}"
                for doc_type in ("bevis", "intyg"):  # Typ away from Intyg and back
                    retyped = self.client.patch(path, json={"doc_type": doc_type})
                    self.assertEqual(retyped.status_code, 200, retyped.get_data(as_text=True))
                self.assertEqual(db.InboxDocument.get_by_id(uploaded["document_id"]).interpretation_status, "av")
                again = self.client.post(f"{path}/tolka-igen", json={})
                self.assertEqual((again.status_code, again.get_json()["detail"]), (409, inbox.NOTICE_UNREAD))
                waiting = db.InboxDocument.update(interpretation_status="vantar")
                waiting.where(db.InboxDocument.id == uploaded["document_id"]).execute()
                self.assertIsNone(interpreter.interpret_next())
                db.InboxDocument.update(interpretation_status="av").where(
                    db.InboxDocument.id == uploaded["document_id"]
                ).execute()
        self.assertEqual(read, [])
        # sent, the certificate is an ordinary upload's and is read; a held photo's item is gone
        self.login("owner")
        held = self.upload(purpose="inskick")
        self.assertEqual(self.send(held).status_code, 200)
        self.assertEqual(interpreter.interpret_next(), held["document_id"])

    def test_a_held_photo_left_a_day_goes_with_its_file(self):
        """
        Codex P2: a photo held for a purchase whose dialog was left, never sent, taken or bound, goes with its file
        in the nightly purge a day after it came in, as one held for a rabbit (item 12). A sent, bound or fresh one
        stays.
        """
        self.assertIn(inbox_purge.purge_held, inbox_purge.RULES)
        self.login("owner")
        left = [self.upload(purpose="kop"), self.upload(purpose="inskick"), self.upload()]  # the last a rabbit's
        fresh = self.upload(purpose="inskick")
        bound = self.upload(purpose="kop")
        db.InboxItem.update(ref_id=self.own.id, ref_data=None).where(db.InboxItem.id == bound["item_id"]).execute()
        sent_photo = self.upload(purpose="kop")  # a notice's photo, sent with the rabbit Stamboken lacks (S7)
        self.assertEqual(self.send(sent_photo, types=("intyg",)).status_code, 200)
        files = {
            u["document_id"]: os.path.join(self.folder, db.InboxDocument.get_by_id(u["document_id"]).original_path)
            for u in (*left, fresh, bound, sent_photo)
        }
        old = [u["item_id"] for u in (*left, bound)]
        two_days_ago = inbox.now() - timedelta(days=2)
        db.InboxItem.update(received_at=two_days_ago).where(db.InboxItem.id.in_(old)).execute()
        db.InboxItem.update(received_at=two_days_ago).where(db.InboxItem.kind == "upload").execute()
        self.assertEqual(inbox_purge.purge_held(inbox.now()), 3)
        remaining = {d.id for d in db.InboxDocument.select()}
        for document_id, path in files.items():
            gone = document_id in {u["document_id"] for u in left}
            self.assertEqual((document_id in remaining, os.path.exists(path)), (not gone, not gone))
        self.assertEqual(inbox_purge.purge_held(inbox.now()), 0)  # again: nothing

    # S8: "Ärenden hos genbanksansvarig", the queue items that concern the report

    def item(self, kind="upload", state="ny", sender=None, herd=None, closed_days=None, **fields):
        """A queue item of `herd` (the buyer's), closed `closed_days` ago if given."""
        closed = inbox.now() - timedelta(days=closed_days) if closed_days is not None else None
        return db.InboxItem.create(
            kind=kind,
            state=state,
            genebank=self.gotland,
            herd=herd or self.h,
            sender_user=sender,
            message="Hej, mitt telefonnummer är …",
            closed_at=closed,
            **fields,
        )

    def document(self, item, status="av", done=False):
        db.InboxDocument.create(
            item=item,
            original_path="original/x.jpg",
            mime="image/jpeg",
            sha256="0" * 64,
            interpretation_status=status,
            done_at=inbox.now() if done else None,
        )

    def test_report_cases_scope_and_states(self):
        db.Member.update(user=self.owner).where(db.Member.id == self.code.member_id).execute()  # the main member's
        waiting = self.item(sender=self.owner)  # the owner's own upload, its certificate still to be read
        self.document(waiting, status="vantar")
        self.document(waiting, status="klar")
        held = self.item(sender=self.owner, state="tagen")
        asked = self.item(sender=self.owner, state="ofullstandig")
        recent = self.item(sender=self.owner, state="klar", closed_days=13)
        self.item(sender=self.owner, state="klar", closed_days=15)  # closed too long ago
        self.item(sender=self.manager)  # the manager's upload for the herd: another sender
        self.item(sender=self.owner, herd=self.seller)  # the owner's upload for another herd
        self.item(kind="mail")  # a mail, matched to the herd
        notice = self.stored_notice(self.a, date(2025, 5, 14))
        self.stored_notice(self.b, date(2024, 11, 2))  # another year's
        bound = self.item(kind="kontroll", ref_type="individual", ref_id=self.own.id)
        self.item(kind="kontroll", ref_type="individual")  # a photo not yet bound to its rabbit
        self.login("owner")
        rows = self.view()["arenden"]
        self.assertEqual(
            rows,
            [
                {"id": bound.id, "what": "foto", "number": self.own.number, "photos": 0, "state": "vantar"},
                {"id": notice.id, "what": "kopanmalan", "number": self.a.number, "photos": 0, "state": "vantar"},
                {"id": asked.id, "what": "inskick", "number": None, "photos": 0, "state": "arbetar"},
                {"id": held.id, "what": "inskick", "number": None, "photos": 0, "state": "arbetar"},
                {"id": waiting.id, "what": "inskick", "number": None, "photos": 2, "state": "tolkas"},
                {"id": recent.id, "what": "inskick", "number": None, "photos": 0, "state": "klart"},
            ],
        )
        # the link sees the same list
        self.client.get("/api/logout")
        self.open_link(self.code)
        self.assertEqual(self.view()["arenden"], rows)

    def inskick(self):
        """An upload for the buyer herd on the member upload page (Skicka in): its item's id."""
        response = InboxTest.upload(self, herd="G9001")
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return response.get_json()["item"]["id"]

    def test_report_cases_follow_who_sent_an_upload_not_todays_rights(self):
        """
        Codex P2: an ordinary upload is the report's case when the herd's report recipient sent it, as recorded when it
        came in, or for an older upload by the recipient's account. A right to the herd never counts: a grant given
        after a helper's upload does not show it, a revoke hides nothing, and a new main member sees none of the old.
        """
        holder = db.Member.get_by_id(self.code.member_id)
        db.Member.update(user=self.owner).where(db.Member.id == holder.id).execute()
        self.login("hjalp")  # a genebank helper uploads for the herd, as the queue's workers may
        early = self.inskick()
        self.login("owner")
        mine = self.inskick()
        older = self.item(sender=self.owner)  # from before the sender was recorded: by the recipient's account
        self.item(sender=self.helper)  # the helper's, from before: never through a grant

        def listed():
            return sorted(row["id"] for row in purchase_notice.report_cases(self.h, 2025))

        self.assertEqual([db.InboxItem.get_by_id(i).member_id for i in (early, mine)], [None, holder.id])
        self.assertEqual(listed(), sorted([mine, older.id]))
        person = db.Member.create(
            first_name="Test", last_name="Skötare", membership=self.h.membership, role="skotare", user=self.helper
        )
        grant = db.HerdAccessGrant.create(member=person, herd=self.h, granted_by=self.admin)
        self.assertIn(self.h.id, db.User.get_by_id(self.helper.id).effective_herd_ids())
        self.assertEqual(listed(), sorted([mine, older.id]))  # the caretaker's grant shows none of the helper's
        self.login("hjalp")
        cared = self.inskick()  # as a caretaker now: recorded as the caretaker's
        self.assertEqual(db.InboxItem.get_by_id(cared).member_id, person.id)
        self.assertEqual(listed(), sorted([mine, older.id]))
        db.HerdAccessGrant.update(revoked_at=datetime.now()).where(db.HerdAccessGrant.id == grant.id).execute()
        self.assertEqual(listed(), sorted([mine, older.id]))  # a revoke hides nothing
        # a new main member: the herd's report goes to them, and the old one's uploads leave its list
        db.Member.update(end_date=date(2026, 1, 9)).where(db.Member.id == holder.id).execute()
        new = {"first_name": "Test", "last_name": "Ny", "email": "g3@example.invalid", "role": "huvudmedlem"}
        db.Member.create(membership=self.h.membership, **new)
        self.assertEqual(listed(), [])

    def test_the_sellers_report_lists_its_sale_proposal(self):
        self.seller_proposes()
        (row,) = purchase_notice.report_cases(self.seller, 2025)
        self.assertEqual((row["what"], row["number"], row["state"]), ("forsaljning", self.a.number, "vantar"))
        self.assertEqual(purchase_notice.report_cases(self.seller, 2026), [])  # another year's report
        self.assertEqual(purchase_notice.report_cases(self.h, 2025), [])  # not the buyer's
