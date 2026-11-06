"""GET history API: projected periods and the visibility of external sales."""

import os
from datetime import date, timedelta
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from herdbook import APP, limiter  # noqa: E402
from utils.herd_tracking import (
    HerdTrackingInvalid,
    can_see_buyer,
    herd_tracking_history,
    record_herd_tracking,
    void_herd_tracking,
)  # noqa: E402

from tests.database_test import _USE_POSTGRES, DatabaseTest  # noqa: E402
from tests.ht_helpers import count_queries, ht_row, make_individual  # noqa: E402

limiter.enabled = False

ROW_KEYS = {
    "id",
    "date",
    "kind",
    "herd",
    "from_herd",
    "voided_at",
    "voided_reason",
    "voided_operation_id",
    "operation_id",
    "created_at",
    "confirmed",
    "notes",
    "buyer",
    "can_void",
    "can_undo_sale",
    "can_undo_operation",
}


class HistoryBase(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.g1, self.g2 = self.herds[0], self.herds[1]
        self.gx1 = db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför", is_active=True)
        self.rabbit = make_individual(self.g1, "G1-2401", date(2024, 1, 1))
        ht_row("BIRTH", individual=self.rabbit, herd=self.g1, herd_tracking_date=date(2024, 1, 1))
        self.report1 = record_herd_tracking(self.rabbit, self.g1, date(2024, 6, 1), "ATTESTATION", self.owner)
        self.sale = record_herd_tracking(self.rabbit, self.g2, date.today() - timedelta(days=1), "TRANSFER", self.owner)

    def _login(self, username, password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.get("/api/logout")
        self.client.post("/api/login", json={"username": username, "password": password})

    def _history(self, query=""):
        return self.client.get(f"/api/v2/individual/{self.rabbit.number}/herd-tracking{query}")


class TestHistoryEndpoint(HistoryBase):
    def test_rows_in_server_order_with_the_spec_fields_and_periods(self):
        self._login("owner")
        response = self._history()
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        body = response.get_json()
        self.assertEqual([r["kind"] for r in body["rows"]], ["TRANSFER", "ATTESTATION", "BIRTH"])
        self.assertEqual(set(body["rows"][0]), ROW_KEYS)
        self.assertEqual(
            [(p["herd"]["herd"], p["start_kind"], p["to_date"], p["attestation_ids"]) for p in body["periods"]],
            [
                ("G1", "BIRTH", self.sale.herd_tracking_date.isoformat(), [self.report1.id]),
                ("G2", "TRANSFER", None, []),
            ],
        )
        self.assertFalse(body["viewer"]["can_manage"])

    def test_same_day_replaced_birth_keeps_server_order(self):
        twin = make_individual(self.g1, "G1-2402", date(2024, 3, 1))
        ht_row("TRANSFER", individual=twin, herd=self.g2, from_herd=self.g1, herd_tracking_date=date(2024, 3, 1))
        ht_row("BIRTH", individual=twin, herd=self.g1, herd_tracking_date=date(2024, 3, 1))
        self._login("man")
        body = self.client.get(f"/api/v2/individual/{twin.number}/herd-tracking").get_json()
        self.assertEqual([r["kind"] for r in body["rows"]], ["TRANSFER", "BIRTH"])
        self.assertEqual([p["herd"]["herd"] for p in body["periods"]], ["G1", "G2"])

    def test_q8_voided_rows_default_off_for_owners_on_for_managers(self):
        void_herd_tracking(self.sale.id, self.owner, "Fel köpare")
        self._login("owner")
        self.assertNotIn(self.sale.id, [r["id"] for r in self._history().get_json()["rows"]])
        voided = [r for r in self._history("?include_voided=1").get_json()["rows"] if r["id"] == self.sale.id]
        self.assertEqual(voided[0]["voided_reason"], "Fel köpare")
        self._login("man")
        self.assertIn(self.sale.id, [r["id"] for r in self._history().get_json()["rows"]])
        self.assertNotIn(self.sale.id, [r["id"] for r in self._history("?include_voided=0").get_json()["rows"]])

    def test_permission_flags_per_viewer(self):
        buyer = da.register_user("buyer", "pass")
        buyer.add_role("owner", self.g2.id)
        flags = {}
        for username in ("owner", "buyer", "man"):
            self._login(username)
            latest = self._history().get_json()["rows"][0]
            flags[username] = (latest["can_void"], latest["can_undo_sale"])
        self.assertEqual(flags, {"owner": (True, True), "buyer": (False, False), "man": (True, True)})

    def test_outside_genebank_label_and_no_buyer(self):
        out = make_individual(self.g1, "G1-2403", date(2024, 1, 1))
        ht_row("BIRTH", individual=out, herd=self.g1, herd_tracking_date=date(2024, 1, 1))
        record_herd_tracking(out, self.gx1, date(2024, 9, 30), "TRANSFER", self.owner)
        self._login("man")
        latest = self.client.get(f"/api/v2/individual/{out.number}/herd-tracking").get_json()["rows"][0]
        self.assertEqual(
            (latest["herd"]["label"], latest["herd"]["outside_genebank"]), ("Såld utanför genbanken", True)
        )
        self.assertIsNone(latest["buyer"])

    def test_unknown_or_inaccessible_is_404_and_anonymous_is_401(self):
        self.assertEqual(self._history().status_code, 401)
        da.register_user("nobody", "pass")
        self._login("nobody")
        self.assertEqual(self._history().status_code, 404)
        self._login("man")
        self.assertEqual(self.client.get("/api/v2/individual/G1-0000/herd-tracking").status_code, 404)


class TestBuyerVisibility(HistoryBase):
    """Dormant until Phase 10 (holder_contact_id is NULL), but the rule is enforced now."""

    def setUp(self):
        super().setUp()
        self.out = make_individual(self.g1, "G1-2404", date(2024, 1, 1))
        ht_row("BIRTH", individual=self.out, herd=self.g1, herd_tracking_date=date(2024, 1, 1))
        self.out_row = record_herd_tracking(self.out, self.gx1, date(2024, 9, 30), "TRANSFER", self.owner)
        # Test-only: Phase 10's inlösen is the one production path that sets holder_contact_id.
        db.HerdTracking.update(holder_contact_id=7).where(db.HerdTracking.id == self.out_row.id).execute()

    def _buyer_seen_by(self, username, consent):
        contact = {"name": "Anna Köpare", "contact": "anna@example.com", "manager_disclosure_consent": consent}
        self._login(username)
        with mock.patch("utils.herd_tracking._load_buyer_contact", return_value=contact):
            rows = self.client.get(f"/api/v2/individual/{self.out.number}/herd-tracking").get_json()["rows"]
        return next(r for r in rows if r["id"] == self.out_row.id)["buyer"]

    def test_manager_sees_buyer_only_with_consent(self):
        self.assertIsNone(self._buyer_seen_by("man", consent=False))
        self.assertEqual(self._buyer_seen_by("man", consent=True)["name"], "Anna Köpare")

    def test_owner_never_sees_buyer(self):
        self.assertIsNone(self._buyer_seen_by("owner", consent=True))

    def test_manager_of_another_genebank_never_sees_buyer(self):
        other = da.register_user("othermgr", "pass")
        other.add_role("manager", self.genebanks[1].id)
        self.assertFalse(can_see_buyer(db.User.get_by_id(other.id), self.genebanks[0].id, True))
        self.assertTrue(can_see_buyer(self.manager, self.genebanks[0].id, True))
        self.assertFalse(can_see_buyer(self.manager, self.genebanks[0].id, False))

    def test_v1_never_carries_buyer_fields(self):
        data = db.Individual.get_by_id(self.out.id).as_dict()
        for entry in data["herd_tracking"]:
            self.assertEqual(set(entry), {"herd_id", "herd", "herd_name", "date", "kind"})

    @mock.patch("utils.herd_tracking._load_buyer_contact", return_value={"name": "Anna Köpare"})
    def test_audit_view_shows_holder_contact_id_only_as_an_id(self, _loader):  # M20
        if not _USE_POSTGRES:
            self.skipTest("audit_log needs PostgreSQL")
        self._login("man")
        response = self.client.get(f"/api/audit-log/herd_tracking/{self.out_row.id}")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        entries = response.get_json()["data"]
        self.assertTrue(any((e.get("new_data") or {}).get("holder_contact_id") == 7 for e in entries))
        _loader.assert_not_called()  # the audit view never resolves the contact to a name


class TestOperationUndoHint(HistoryBase):
    def test_single_row_operation_hides_undo_whole_operation(self):
        """M3: one written row and nothing voided -> plain Ångra has the same effect."""
        self._login("man")
        latest = self._history().get_json()["rows"][0]
        self.assertEqual(latest["id"], self.sale.id)
        self.assertFalse(latest["can_undo_operation"])

    def test_multi_row_operation_offers_undo_whole_operation(self):
        from utils.herd_tracking import correct_herd_tracking, new_operation_id

        op = new_operation_id()
        correct_herd_tracking(
            self.rabbit,
            self.manager,
            op,
            [self.sale.id],
            [{"kind": "TRANSFER", "date": (date.today() - timedelta(days=2)).isoformat(), "herd": self.g2.herd}],
            "Fel datum",
        )
        self._login("man")
        rows = self._history().get_json()["rows"]
        written = next(r for r in rows if r["operation_id"] == str(op) and r["voided_at"] is None)
        self.assertTrue(written["can_undo_operation"])


class TestVoidOnlyOperationUndo(HistoryBase):
    """A voided row offers undo of the operation that voided it (void-only corrections included)."""

    def _void_only_correction(self):
        from utils.herd_tracking import correct_herd_tracking, new_operation_id

        op = new_operation_id()
        correct_herd_tracking(self.rabbit, self.manager, op, [self.sale.id], [], "Fel försäljning")
        return op

    def _sale_row(self):
        return next(r for r in self._history().get_json()["rows"] if r["id"] == self.sale.id)

    def test_manager_can_undo_a_void_only_correction_from_the_voided_row(self):
        op = self._void_only_correction()
        self._login("man")
        row = self._sale_row()
        self.assertEqual(row["voided_operation_id"], str(op))
        self.assertTrue(row["can_undo_operation"])
        response = self.client.post(f"/api/v2/herd-tracking/operations/{op}/undo", json={"reason": "Fel"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertIsNone(self._sale_row()["voided_at"])

    def test_owner_never_gets_the_operation_undo(self):
        self._void_only_correction()
        self._login("owner")
        row = next(r for r in self._history("?include_voided=true").get_json()["rows"] if r["id"] == self.sale.id)
        self.assertFalse(row["can_undo_operation"])

    def test_active_rows_carry_no_voided_operation_id(self):
        self._login("man")
        self.assertIsNone(self._sale_row()["voided_operation_id"])

    def test_undo_of_an_undo_is_offered_on_the_rows_it_voided(self):
        from utils.herd_tracking import correct_herd_tracking, new_operation_id, undo_herd_tracking_operation

        (fixed,) = correct_herd_tracking(
            self.rabbit,
            self.manager,
            new_operation_id(),
            [self.sale.id],
            [{"kind": "TRANSFER", "date": (date.today() - timedelta(days=2)).isoformat(), "herd": self.g2.herd}],
            "Fel datum",
        )
        undo = undo_herd_tracking_operation(fixed.operation_id, self.manager, "Fel")
        self._login("man")
        row = next(r for r in self._history().get_json()["rows"] if r["id"] == fixed.id)
        self.assertEqual(row["voided_operation_id"], undo["undo_operation_id"])
        self.assertTrue(row["can_undo_operation"])


class TestFixRound1(HistoryBase):
    def _extend(self, rabbit, start, n):
        """n more alternating TRANSFER rows (G1<->G2) plus an ATTESTATION each, ending on G1."""
        for i in range(n):
            day = start + timedelta(days=2 * i)
            ht_row("TRANSFER", individual=rabbit, herd=self.g1, from_herd=self.g2, herd_tracking_date=day)
            ht_row("ATTESTATION", individual=rabbit, herd=self.g1, herd_tracking_date=day)
            ht_row("TRANSFER", individual=rabbit, herd=self.g2, from_herd=self.g1, herd_tracking_date=day)

    def test_owner_history_query_count_does_not_grow_with_rows(self):
        rabbit = make_individual(self.g1, "G1-2410", date(2023, 1, 1))
        ht_row("BIRTH", individual=rabbit, herd=self.g1, herd_tracking_date=date(2023, 1, 1))
        ht_row("TRANSFER", individual=rabbit, herd=self.g2, from_herd=self.g1, herd_tracking_date=date(2023, 2, 1))

        def measure():
            owner = db.User.get_by_id(self.owner.id)
            ind = db.Individual.get_by_id(rabbit.id)
            with count_queries() as counter:
                herd_tracking_history(ind, owner)
            return counter["n"]

        few = measure()
        self._extend(rabbit, date(2023, 3, 1), 5)
        self.assertEqual(measure(), few)

    def test_can_void_false_when_the_api_would_refuse_for_invariants(self):
        # G1 -> TRANSFER(G2) -> ATTESTATION(G2): voiding the TRANSFER would orphan the attestation (I2).
        rabbit = make_individual(self.g1, "G1-2411", date(2024, 1, 1))
        ht_row("BIRTH", individual=rabbit, herd=self.g1, herd_tracking_date=date(2024, 1, 1))
        transfer = ht_row(
            "TRANSFER", individual=rabbit, herd=self.g2, from_herd=self.g1, herd_tracking_date=date(2024, 2, 1)
        )
        ht_row("ATTESTATION", individual=rabbit, herd=self.g2, herd_tracking_date=date(2024, 3, 1))
        self._login("man")
        rows = self.client.get(f"/api/v2/individual/{rabbit.number}/herd-tracking").get_json()["rows"]
        self.assertFalse(next(r for r in rows if r["id"] == transfer.id)["can_void"])

    def test_outside_herd_name_is_not_exposed(self):
        out = make_individual(self.g1, "G1-2412", date(2024, 1, 1))
        ht_row("BIRTH", individual=out, herd=self.g1, herd_tracking_date=date(2024, 1, 1))
        record_herd_tracking(out, self.gx1, date(2024, 9, 30), "TRANSFER", self.owner)
        self._login("owner")
        latest = self.client.get(f"/api/v2/individual/{out.number}/herd-tracking").get_json()["rows"][0]
        self.assertIsNone(latest["herd"]["herd_name"])
        self.assertNotIn("Utanför", str(latest))

    def test_record_rejects_contact_details_in_notes(self):
        with self.assertRaises(HerdTrackingInvalid):
            record_herd_tracking(
                self.rabbit, self.g1, date.today(), "ATTESTATION", self.owner, notes="ring anna@example.com"
            )

    def test_correction_row_starts_a_period_and_voided_rows_leave_periods(self):
        rabbit = make_individual(self.g1, "G1-2413", date(2024, 1, 1))
        ht_row("BIRTH", individual=rabbit, herd=self.g1, herd_tracking_date=date(2024, 1, 1))
        ht_row("CORRECTION", individual=rabbit, herd=self.g2, from_herd=self.g1, herd_tracking_date=date(2024, 2, 1))
        gone = ht_row(
            "TRANSFER", individual=rabbit, herd=self.g1, from_herd=self.g2, herd_tracking_date=date(2024, 3, 1)
        )
        _void = __import__("tests.ht_helpers", fromlist=["_void"])._void
        _void(gone, self.manager)
        self._login("man")
        body = self.client.get(f"/api/v2/individual/{rabbit.number}/herd-tracking").get_json()
        self.assertEqual(
            [(p["herd"]["herd"], p["start_kind"]) for p in body["periods"]], [("G1", "BIRTH"), ("G2", "CORRECTION")]
        )
        self.assertIsNone(body["periods"][-1]["to_date"])

    def test_undo_hint_false_when_a_later_operation_exists(self):
        from utils.herd_tracking import correct_herd_tracking, new_operation_id

        op = new_operation_id()
        correct_herd_tracking(
            self.rabbit,
            self.manager,
            op,
            [self.sale.id],
            [{"kind": "TRANSFER", "date": (date.today() - timedelta(days=2)).isoformat(), "herd": self.g2.herd}],
            "Fel datum",
        )
        record_herd_tracking(self.rabbit, self.g2, date.today(), "ATTESTATION", self.manager)
        self._login("man")
        rows = self._history().get_json()["rows"]
        written = next(r for r in rows if r["operation_id"] == str(op) and r["voided_at"] is None)
        self.assertFalse(written["can_undo_operation"])

    def test_viewer_from_another_genebank_gets_404(self):
        other = da.register_user("othergb", "pass")
        other.add_role("manager", self.genebanks[1].id)
        self._login("othergb")
        self.assertEqual(self._history().status_code, 404)
