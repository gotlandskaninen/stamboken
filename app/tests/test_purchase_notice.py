#!/usr/bin/env python3
"""
Tests for "Köpt i år" and "Anmäl köpet" (step 4a, Task 5): the bought mark on the report's list, the purchase notice
and its kontroll item, matching a seller's sale proposal, and the notice closing once the transfer is registered.
Synthetic herds and rabbits only.

isort:skip_file
"""

import threading
import time
from datetime import date
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.herd_tracking as herd_tracking
import utils.inbox as inbox
import utils.mail as mail
import utils.purchase_notice as purchase_notice
import utils.report_code as report_code
import utils.sale_proposal as sale_proposal
import utils.settings as settings
from herdbook import APP
from utils.arsrapport import Access, ArsrapportError
from utils.report_code import CodeActor

from tests.arsrapport_fixtures import ArsrapportTest
from tests.database_test import _USE_POSTGRES
from tests.ht_helpers import ht_row

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
        self.assertEqual(self.notify(number=f" {self.b.number} ", from_herd="utanfor").get_json()["from_herd"], "GX1")
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
        self.assertEqual(body["detail"], "Finns kaninen inte i Stamboken? Lägg till den från intyget.")
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
        self.assertEqual((item.herd_id, event.user_id, event.detail), (self.h.id, None, {"via": "länk G9001/2025"}))
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
