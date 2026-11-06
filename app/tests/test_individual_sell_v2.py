"""Tests for selling / moving an individual between herds (PATCH /api/individual/<number>).

isort:skip_file
"""

import os
import threading
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import _USE_POSTGRES, DatabaseTest  # noqa: E402
from tests.ht_helpers import ht_row  # noqa: E402

limiter.enabled = False

# individuals[0] = G1-2111: registered (certificate), born 2021-02-01, tracked in G1 since birth.
# individuals[3] = G1-2112: no certificate, same birth/tracking.
REGISTERED = "G1-2111"
UNREGISTERED = "G1-2112"
VALID_DATE = "2021-06-01"


class TestSellIndividualV2(DatabaseTest):
    """PATCH /api/individual/<number> with herd + selling_date."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.outside_herd = db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför genbanken")

    def _login(self, username="owner", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post("/api/login", json={"username": username, "password": password})

    def _sell(self, number, herd, selling_date):
        return self.client.patch(f"/api/individual/{number}", json={"herd": herd, "selling_date": selling_date})

    def _assert_unchanged(self, number, herd="G1"):
        ind = db.Individual.get(db.Individual.number == number)
        self.assertEqual(ind.current_herd.herd, herd)

    def test_owner_sells_to_other_herd(self):
        self._login()
        before = db.HerdTracking.select().where(db.HerdTracking.individual == self.individuals[0]).count()
        response = self._sell(REGISTERED, "G2", VALID_DATE)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["herd"]["herd"], "G2")
        rows = db.HerdTracking.select().where(db.HerdTracking.individual == self.individuals[0])
        self.assertEqual(rows.count(), before + 1)
        latest = rows.order_by(db.HerdTracking.herd_tracking_date.desc()).get()
        self.assertEqual(latest.herd.herd, "G2")
        self.assertEqual(latest.from_herd.herd, "G1")
        self.assertEqual(latest.herd_tracking_date.isoformat(), VALID_DATE)
        self.assertEqual(db.Individual.get(db.Individual.number == REGISTERED).current_herd.herd, "G2")

    def test_null_selling_date_is_no_sale(self):
        """`selling_date` is not a column: a null value must not 500 nor move the rabbit."""
        self._login()
        before = db.HerdTracking.select().where(db.HerdTracking.individual == self.individuals[0]).count()
        response = self.client.patch(f"/api/individual/{REGISTERED}", json={"selling_date": None})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        after = db.HerdTracking.select().where(db.HerdTracking.individual == self.individuals[0]).count()
        self.assertEqual(after, before)
        self._assert_unchanged(REGISTERED)

    def test_registered_can_go_outside_genebank(self):
        self._login()
        response = self._sell(REGISTERED, "GX1", VALID_DATE)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self._assert_unchanged(REGISTERED, "GX1")

    def test_manager_can_sell(self):
        self._login("man")
        response = self._sell(REGISTERED, "G2", VALID_DATE)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

    def test_today_is_allowed(self):
        self._login()
        response = self._sell(REGISTERED, "G2", datetime.now().strftime("%Y-%m-%d"))
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

    def test_future_date_rejected(self):
        self._login()
        future = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        response = self._sell(REGISTERED, "G2", future)
        self.assertEqual(response.status_code, 400)
        self.assertIn("framtiden", response.get_json()["detail"])
        self._assert_unchanged(REGISTERED)

    def test_too_early_after_birth_rejected(self):
        """Latest tracking row is the birth row -> birth + 43 days (2021-03-16) at the earliest."""
        self._login()
        response = self._sell(REGISTERED, "G2", "2021-03-15")
        self.assertEqual(response.status_code, 400)
        self.assertIn("2021-03-16", response.get_json()["detail"])
        self._assert_unchanged(REGISTERED)
        self.assertEqual(self._sell(REGISTERED, "G2", "2021-03-16").status_code, 200)

    def test_must_be_after_latest_herd_tracking(self):
        """Not on the birth row -> at least one day after the latest tracking date."""
        self._login("man")
        self.assertEqual(self._sell(REGISTERED, "G2", "2021-06-01").status_code, 200)
        response = self._sell(REGISTERED, "G1", "2021-06-01")
        self.assertEqual(response.status_code, 400)
        self.assertIn("2021-06-02", response.get_json()["detail"])
        self.assertEqual(self._sell(REGISTERED, "G1", "2021-06-02").status_code, 200)

    def test_invalid_date_rejected(self):
        self._login()
        response = self._sell(REGISTERED, "G2", "inte-ett-datum")
        self.assertEqual(response.status_code, 400)

    def test_other_genebank_rejected(self):
        """Only an admin may move a rabbit into another genebank (a correction, see TestTransferPermissionsV2)."""
        self._login("man")
        response = self._sell(REGISTERED, "M3", VALID_DATE)
        self.assertEqual(response.status_code, 400)
        self.assertIn("samma genbank", response.get_json()["detail"])
        self._assert_unchanged(REGISTERED)

    def test_unknown_herd_rejected(self):
        self._login()
        response = self._sell(REGISTERED, "G999", VALID_DATE)
        self.assertEqual(response.status_code, 400)

    def test_same_herd_rejected(self):
        self._login()
        response = self._sell(REGISTERED, "G1", VALID_DATE)
        self.assertEqual(response.status_code, 400)
        self._assert_unchanged(REGISTERED)

    def test_missing_herd_rejected(self):
        self._login()
        response = self.client.patch(f"/api/individual/{REGISTERED}", json={"selling_date": VALID_DATE})
        self.assertEqual(response.status_code, 400)

    def test_unregistered_to_normal_herd_rejected(self):
        self._login()
        response = self._sell(UNREGISTERED, "G2", VALID_DATE)
        self.assertEqual(response.status_code, 400)
        self.assertIn("GX1", response.get_json()["detail"])
        self._assert_unchanged(UNREGISTERED)

    def test_unregistered_to_outside_genebank_allowed(self):
        self._login()
        response = self._sell(UNREGISTERED, "GX1", VALID_DATE)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self._assert_unchanged(UNREGISTERED, "GX1")

    def test_non_owner_forbidden(self):
        """A genebank viewer sees the rabbit but cannot sell it."""
        self._login("spec")
        response = self._sell(REGISTERED, "G2", VALID_DATE)
        self.assertEqual(response.status_code, 403)
        self._assert_unchanged(REGISTERED)

    def test_other_herds_owner_forbidden(self):
        other = db.Herd.get(db.Herd.herd == "G2")
        user = da.register_user("owner2", "pass")
        user.add_role("owner", other.id)
        self._login("owner2")
        response = self._sell(REGISTERED, "G2", VALID_DATE)
        self.assertEqual(response.status_code, 403)
        self._assert_unchanged(REGISTERED)

    def test_requires_login(self):
        response = self._sell(REGISTERED, "G2", VALID_DATE)
        self.assertIn(response.status_code, (302, 401))


class TestTransferPermissionsV2(DatabaseTest):
    """Who may sell/move (huvudmedlem, legacy owner, manager, admin — never a grant holder)."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför genbanken")
        self.membership = db.Membership.create(member_number=6, membership_status="active")
        herd = self.herds[0]
        herd.membership = self.membership
        herd.save()
        self.main_user = da.register_user("maja@example.com", "pass", username="maja")
        self.main = db.Member.create(
            membership=self.membership,
            first_name="Maja",
            last_name="Huvudsson",
            email="maja@example.com",
            role="huvudmedlem",
            user=self.main_user,
        )
        self.caretaker_user = da.register_user("sune@example.com", "pass", username="sune")
        self.caretaker = db.Member.create(
            membership=self.membership,
            first_name="Sune",
            last_name="Skötarsson",
            email="sune@example.com",
            role="skotare",
            user=self.caretaker_user,
        )
        db.HerdAccessGrant.create(member=self.caretaker, herd=herd, granted_by=self.admin)

    def _login(self, username):
        self.client = APP.test_client(use_cookies=True)  # fresh session: logins must not stack
        return self.client.post("/api/login", json={"username": username, "password": "pass"})

    def _patch(self, body, number=REGISTERED):
        return self.client.patch(f"/api/individual/{number}", json=body)

    def _tracking_count(self, individual_index=0):
        return db.HerdTracking.select().where(db.HerdTracking.individual == self.individuals[individual_index]).count()

    def test_caretaker_with_grant_cannot_sell(self):
        self._login("sune")
        before = self._tracking_count()
        response = self._patch({"herd": "G2", "selling_date": VALID_DATE})
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
        self.assertEqual(self._tracking_count(), before)
        self.assertEqual(db.Individual.get(db.Individual.number == REGISTERED).current_herd.herd, "G1")

    def test_caretaker_cannot_move_via_yearly_report_date(self):
        self._login("sune")
        before = self._tracking_count()
        response = self._patch({"herd": "G2", "yearly_report_date": VALID_DATE})
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
        self.assertEqual(self._tracking_count(), before)

    def test_caretaker_can_still_edit_with_current_herd(self):
        """The grant still conveys edit rights; only transfer is blocked."""
        self._login("sune")
        response = self._patch({"herd": "G1", "yearly_report_date": "2021-07-01"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

    def _legacy_patch(self, body):
        return self.client.patch("/api/individual", json={"id": self.individuals[0].id, "number": REGISTERED, **body})

    def test_caretaker_cannot_sell_via_legacy_patch(self):
        """Legacy PATCH gets the same rule; the error envelope rolls back the weights sent with it."""
        self._login("sune")
        before = self._tracking_count()
        for herd in ("G2", "M3"):
            response = self._legacy_patch(
                {"herd": herd, "selling_date": VALID_DATE, "weights": [{"weight": 9.9, "date": "2021-05-01"}]}
            )
            self.assertEqual(response.status_code, 200)
            body = response.get_json()
            self.assertEqual((body["status"], body.get("problem_status")), ("error", 403), body)
        self.assertEqual(db.Individual.get(db.Individual.number == REGISTERED).current_herd.herd, "G1")
        self.assertEqual(self._tracking_count(), before)
        self.assertEqual(db.Weight.select().where(db.Weight.individual == self.individuals[0]).count(), 1)

    def test_legacy_patch_cannot_move_into_other_genebank(self):
        """Even an owner who may sell cannot move a Gotland rabbit into a Mellerud herd.

        Also when `herd` is M3's id: the writer resolves an int by id, so the check must too.
        """
        self._login("owner")
        for herd in ("M3", self.herds[2].id):
            response = self._legacy_patch({"herd": herd, "selling_date": VALID_DATE})
            self.assertEqual(response.get_json().get("problem_status"), 403, (herd, response.get_json()))
            self.assertEqual(db.Individual.get(db.Individual.number == REGISTERED).current_herd.herd, "G1")

    def test_legacy_sale_and_report_still_work(self):
        """Keeps legacy's sale by an owner and the caretaker's yearly report in the current herd."""
        self._login("sune")
        report = self._legacy_patch({"herd": "G1", "yearly_report_date": "2021-07-01"})
        self.assertEqual(report.get_json()["status"], "success", report.get_json())
        self._login("owner")
        sale = self._legacy_patch({"herd": "G2", "selling_date": "2021-08-01"})
        self.assertEqual(sale.get_json()["status"], "success", sale.get_json())
        self.assertEqual(db.Individual.get(db.Individual.number == REGISTERED).current_herd.herd, "G2")

    def test_huvudmedlem_can_sell(self):
        self._login("maja")
        response = self._patch({"herd": "G2", "selling_date": VALID_DATE})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(db.Individual.get(db.Individual.number == REGISTERED).current_herd.herd, "G2")

    def test_huvudmedlem_of_inactive_membership_cannot_sell(self):
        self.membership.membership_status = "inactive"
        self.membership.save()
        self._login("maja")
        response = self._patch({"herd": "G2", "selling_date": VALID_DATE})
        # An inactive membership conveys no herd rights at all: the rabbit is not even visible.
        self.assertEqual(response.status_code, 404, response.get_data(as_text=True))
        self.assertEqual(db.Individual.get(db.Individual.number == REGISTERED).current_herd.herd, "G1")

    def test_legacy_owner_privilege_can_sell(self):
        self._login("owner")
        response = self._patch({"herd": "G2", "selling_date": VALID_DATE})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

    def test_manager_can_move_back_from_outside_genebank(self):
        self._login("man")
        self.assertEqual(self._patch({"herd": "GX1", "selling_date": "2021-06-01"}).status_code, 200)
        response = self._patch({"herd": "G1", "selling_date": "2021-06-02"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(db.Individual.get(db.Individual.number == REGISTERED).current_herd.herd, "G1")

    def test_owner_cannot_move_back_from_outside_genebank(self):
        self._login("man")
        self.assertEqual(self._patch({"herd": "GX1", "selling_date": "2021-06-01"}).status_code, 200)
        self._login("owner")
        response = self._patch({"herd": "G1", "selling_date": "2021-06-02"})
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True))

    def test_yearly_report_date_with_other_herd_rejected(self):
        """The alternate payload must not bypass the sale rules (no selling_date -> no move)."""
        self._login("owner")
        before = self._tracking_count()
        response = self._patch({"herd": "G2", "yearly_report_date": VALID_DATE})
        self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        self.assertIn("försäljningsdatum", response.get_json()["detail"])
        self.assertEqual(self._tracking_count(), before)
        self.assertEqual(db.Individual.get(db.Individual.number == REGISTERED).current_herd.herd, "G1")

    def test_herd_change_without_any_date_rejected(self):
        self._login("owner")
        before = self._tracking_count()
        response = self._patch({"herd": "G2"})
        self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        self.assertEqual(self._tracking_count(), before)

    def test_yearly_report_date_with_current_herd_allowed(self):
        self._login("owner")
        before = self._tracking_count()
        response = self._patch({"herd": "G1", "yearly_report_date": "2021-07-01"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(self._tracking_count(), before + 1)
        self.assertEqual(db.Individual.get(db.Individual.number == REGISTERED).current_herd.herd, "G1")

    def test_sale_on_same_date_as_latest_move_rejected(self):
        """Strict: a second move must be at least a day after the latest herd-tracking row."""
        self._login("man")
        self.assertEqual(self._patch({"herd": "G2", "selling_date": "2021-08-10"}).status_code, 200)
        before = self._tracking_count()
        response = self._patch({"herd": "GX1", "selling_date": "2021-08-10"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("2021-08-11", response.get_json()["detail"])
        self.assertEqual(self._tracking_count(), before)

    def test_concurrent_sale_waits_for_row_lock_and_revalidates(self):
        """A sale queues behind a concurrent move of the same rabbit and is validated against it."""
        self._login("man")
        locked, release = threading.Event(), threading.Event()

        def concurrent_move():
            try:
                with db.DB_PROXY.atomic():
                    db.Individual.select().where(db.Individual.id == self.individuals[0].id).for_update().first()
                    ht_row(
                        "TRANSFER",
                        individual=self.individuals[0],
                        from_herd=self.herds[0],
                        herd=self.herds[1],
                        signature=self.admin,
                        herd_tracking_date=VALID_DATE,
                    )
                    locked.set()
                    release.wait(15)
            finally:
                locked.set()
                db.DB_PROXY.close()

        results = {}

        def sell():
            try:
                results["response"] = self._patch({"herd": "GX1", "selling_date": VALID_DATE})
            finally:
                db.DB_PROXY.close()

        mover = threading.Thread(target=concurrent_move)
        mover.start()
        self.assertTrue(locked.wait(10))
        seller = threading.Thread(target=sell)
        seller.start()
        seller.join(1.5)
        self.assertTrue(seller.is_alive(), "the sale must block on the row lock")
        release.set()
        seller.join(15)
        mover.join(15)
        response = results["response"]
        self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        self.assertIn("2021-06-02", response.get_json()["detail"])

    def _own_breeding_individual(self):
        """An individual alone in its breeding, with a birth tracking row (origin_herd can change)."""
        breeding = db.Breeding.create(
            breed_date=datetime(2021, 1, 1),
            birth_date=datetime(2021, 3, 1),
            mother=self.parents[0],
            father=self.parents[1],
            litter_size=1,
            litter_size6w=1,
            breeding_herd_id=self.herds[0],
        )
        individual = db.Individual.create(
            origin_herd=self.herds[0], breeding=breeding, color=self.colors[0], certificate="99", number="G1-2113"
        )
        ht_row(
            "BIRTH",
            herd=self.herds[0],
            signature=self.manager,
            individual=individual,
            herd_tracking_date=datetime(2021, 3, 1),
        )
        return individual, breeding

    def _origin_payload(self, breeding):
        return {"herd": "G1", "origin_herd": {"herd": "G2"}, "breeding": breeding.id}

    def _assert_origin_unchanged(self, individual):
        self.assertEqual(db.Individual.get_by_id(individual.id).origin_herd.herd, "G1")
        self.assertEqual(db.Individual.get_by_id(individual.id).current_herd.herd, "G1")
        rows = db.HerdTracking.select().where(db.HerdTracking.individual == individual)
        self.assertEqual([r.herd.herd for r in rows], ["G1"])

    def test_owner_cannot_change_origin_herd(self):
        """origin_herd rewrites the birth tracking row, i.e. moves the rabbit without the transfer rules."""
        individual, breeding = self._own_breeding_individual()
        self._login("owner")
        response = self._patch(self._origin_payload(breeding), number=individual.number)
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
        self.assertIn("ursprungsbesättning", response.get_json()["detail"])
        self._assert_origin_unchanged(individual)

    def test_caretaker_cannot_change_origin_herd(self):
        individual, breeding = self._own_breeding_individual()
        self._login("sune")
        response = self._patch(self._origin_payload(breeding), number=individual.number)
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
        self._assert_origin_unchanged(individual)

    def test_manager_can_change_origin_herd(self):
        individual, breeding = self._own_breeding_individual()
        self._login("man")
        response = self._patch(self._origin_payload(breeding), number=individual.number)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        birth_row = db.HerdTracking.get(
            (db.HerdTracking.individual == individual)
            & (db.HerdTracking.kind == "BIRTH")
            & db.HerdTracking.voided_at.is_null(True)
        )
        self.assertEqual(birth_row.herd.herd, "G2")

    def test_origin_change_conflicting_with_history_is_a_409_and_rolls_back(self):
        """M21: a HerdTrackingError surfaces as its problem status with rows; nothing is committed."""
        individual, breeding = self._own_breeding_individual()
        ht_row("ATTESTATION", individual=individual, herd=self.herds[0], herd_tracking_date="2021-06-01")
        self._login("man")
        response = self._patch(self._origin_payload(breeding), number=individual.number)
        self.assertEqual(response.status_code, 409, response.get_data(as_text=True))
        body = response.get_json()
        self.assertEqual(body["status"], 409)
        self.assertTrue(body["rows"])
        self.assertEqual(db.Individual.get_by_id(individual.id).origin_herd.herd, "G1")
        self.assertEqual(db.Individual.get_by_id(individual.id).number, "G1-2113")
        voided = db.HerdTracking.select().where(
            db.HerdTracking.individual == individual, db.HerdTracking.voided_at.is_null(False)
        )
        self.assertEqual(voided.count(), 0)

    def test_owner_may_resend_unchanged_origin_herd(self):
        """Only a CHANGED origin_herd is restricted."""
        self._login("owner")
        response = self._patch({"herd": "G1", "origin_herd": {"herd": "G1"}, "yearly_report_date": "2021-07-01"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

    def test_legacy_origin_herd_change_is_manager_only(self):
        """A new origin herd rewrites BIRTH, i.e. moves the rabbit; every route gets the v2 rule."""
        individual, breeding = self._own_breeding_individual()
        legacy = {"id": individual.id, "number": individual.number, "herd": "G1", "breeding": breeding.id}
        for username, origin in (("sune", "M3"), ("owner", "G2"), ("man", "M3")):
            self._login(username)
            response = self.client.patch("/api/individual", json={**legacy, "origin_herd": {"herd": origin}})
            self.assertEqual(response.get_json().get("problem_status"), 403, (username, response.get_json()))
            self._assert_origin_unchanged(individual)
        self._login("man")
        response = self.client.patch("/api/individual", json={**legacy, "origin_herd": {"herd": "G2"}})
        self.assertEqual(response.get_json()["status"], "success", response.get_json())
        self.assertEqual(db.Individual.get_by_id(individual.id).origin_herd.herd, "G2")

    def _transfer_row(self, individual):
        return (
            db.HerdTracking.select()
            .where(db.HerdTracking.individual == individual, db.HerdTracking.kind == "TRANSFER")
            .order_by(db.HerdTracking.id.desc())
            .first()
        )

    def _replaced_birth(self, individual):
        return db.HerdTracking.get(
            (db.HerdTracking.individual == individual)
            & (db.HerdTracking.kind == "BIRTH")
            & db.HerdTracking.voided_at.is_null(False)
        )

    def test_admin_moves_rabbit_into_other_genebank_with_reason(self):
        """An admin corrects a misregistration by moving a rabbit into another genebank; the v2 reason is the
        TRANSFER row's note in the history. Caretaker, owner and manager stay refused, reason or not."""
        reason = "Felregistrerad i Gotlandsgenbanken"
        body = {"herd": "M3", "selling_date": VALID_DATE, "reason": reason}
        for username, status in (("sune", 403), ("owner", 400), ("man", 400)):
            self._login(username)
            response = self._patch(dict(body))
            self.assertEqual(response.status_code, status, (username, response.get_data(as_text=True)))
        self.assertIsNone(self._transfer_row(self.individuals[0]))
        self._login("admin")
        response = self._patch({**body, "reason": f"  {reason} "})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(db.Individual.get(db.Individual.number == REGISTERED).current_herd.herd, "M3")
        history = self.client.get(f"/api/v2/individual/{REGISTERED}/herd-tracking").get_json()
        transfer = next(row for row in history["rows"] if row["kind"] == "TRANSFER")
        self.assertEqual((transfer["herd"]["herd"], transfer["notes"]), ("M3", reason))

    def test_admin_genebank_change_without_reason_is_refused(self):
        """v2 can carry a reason, so an admin's move into another genebank requires one; nothing is written."""
        individual, breeding = self._own_breeding_individual()
        self._login("admin")
        for body, number in (
            ({"herd": "M3", "selling_date": VALID_DATE}, REGISTERED),
            ({"herd": "M3", "selling_date": VALID_DATE, "reason": "  "}, REGISTERED),
            ({"herd": "G1", "origin_herd": {"herd": "M3"}, "breeding": breeding.id}, individual.number),
        ):
            response = self._patch(body, number=number)
            self.assertEqual(response.status_code, 400, (body, response.get_data(as_text=True)))
            self.assertEqual(response.get_json()["detail"], "Ange en anledning.", body)
        self.assertEqual(db.Individual.get(db.Individual.number == REGISTERED).current_herd.herd, "G1")
        self.assertIsNone(self._transfer_row(self.individuals[0]))
        self._assert_origin_unchanged(individual)

    def test_admin_changes_origin_herd_into_other_genebank_with_reason(self):
        """The reason of an origin-herd correction across genebanks is recorded as the replaced BIRTH's reason."""
        individual, breeding = self._own_breeding_individual()
        body = {"herd": "G1", "origin_herd": {"herd": "M3"}, "breeding": breeding.id, "reason": "Född i M3"}
        self._login("man")
        denied = self._patch(dict(body), number=individual.number)
        self.assertEqual(denied.status_code, 403, denied.get_data(as_text=True))
        self._assert_origin_unchanged(individual)
        self._login("admin")
        response = self._patch(dict(body), number=individual.number)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(db.Individual.get_by_id(individual.id).origin_herd.herd, "M3")
        replaced = self._replaced_birth(individual)
        self.assertEqual(replaced.voided_reason, "Ersatt: ändrad ursprungsbesättning: Född i M3")

    def test_admin_cannot_move_origin_of_a_moved_rabbit_into_other_genebank(self):
        """Its TRANSFER rows would still start in the old genebank, so voiding one would cross genebanks
        unchecked. The history is corrected first; nothing is written."""
        individual, breeding = self._own_breeding_individual()
        ht_row(
            "TRANSFER",
            individual=individual,
            from_herd=self.herds[0],
            herd=self.herds[1],
            signature=self.manager,
            herd_tracking_date=datetime(2021, 6, 1),
        )
        self._login("admin")
        body = {"origin_herd": {"herd": "M3"}, "breeding": breeding.id, "reason": "Född i M3"}
        response = self._patch(body, number=individual.number)
        self.assertEqual(response.status_code, 409, response.get_data(as_text=True))
        self.assertEqual(db.Individual.get_by_id(individual.id).origin_herd.herd, "G1")
        births = db.HerdTracking.select().where(
            db.HerdTracking.individual == individual, db.HerdTracking.kind == "BIRTH"
        )
        self.assertEqual([(b.herd.herd, b.voided_at) for b in births], [("G1", None)])

    def test_admin_cannot_move_and_change_origin_into_other_genebank_at_once(self):
        """Also when the move is written by the same request: refused, and the move rolls back."""
        individual, breeding = self._own_breeding_individual()
        self._login("admin")
        body = {"origin_herd": {"herd": "M3"}, "breeding": breeding.id, "reason": "Felregistrerad"}
        response = self._patch({**body, "herd": "G2", "selling_date": VALID_DATE}, number=individual.number)
        self.assertEqual(response.status_code, 409, response.get_data(as_text=True))
        self._assert_origin_unchanged(individual)

    def test_admin_legacy_genebank_change_records_a_fixed_note(self):
        """Legacy PATCH cannot carry a reason (ADR-0006): an admin's move into another genebank succeeds with a
        fixed note in the history and a log line; the manager stays refused."""
        self._login("man")
        denied = self._legacy_patch({"herd": "M3", "selling_date": VALID_DATE})
        self.assertEqual(denied.get_json().get("problem_status"), 403, denied.get_json())
        self._login("admin")
        with self.assertLogs("herdbook.da", level="WARNING") as logs:
            response = self._legacy_patch({"herd": "M3", "selling_date": VALID_DATE})
        self.assertEqual(response.get_json()["status"], "success", response.get_json())
        transfer = self._transfer_row(self.individuals[0])
        self.assertEqual((transfer.herd.herd, transfer.notes), ("M3", "Genbanksbyte av admin via legacy"))
        self.assertTrue(
            any(all(part in line for part in ("admin", REGISTERED, "Gotland", "Mellerud")) for line in logs.output),
            logs.output,
        )
        individual, breeding = self._own_breeding_individual()
        legacy = {"id": individual.id, "number": individual.number, "herd": "G1", "breeding": breeding.id}
        response = self.client.patch("/api/individual", json={**legacy, "origin_herd": {"herd": "M3"}})
        self.assertEqual(response.get_json()["status"], "success", response.get_json())
        self.assertEqual(db.Individual.get_by_id(individual.id).origin_herd.herd, "M3")
        self.assertEqual(
            self._replaced_birth(individual).voided_reason,
            "Ersatt: ändrad ursprungsbesättning: Genbanksbyte av admin via legacy",
        )

    def test_viewer_null_clearing_is_forbidden_and_writes_nothing(self):
        """Permission is checked before the null-clearing write, not after the transaction."""
        db.Individual.update(death_date=datetime(2024, 1, 1), death_note="Död").where(
            db.Individual.id == self.individuals[0].id
        ).execute()
        self._login("spec")
        response = self._patch({"death_date": None, "death_note": None})
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
        individual = db.Individual.get_by_id(self.individuals[0].id)
        self.assertIsNotNone(individual.death_date)
        self.assertEqual(individual.death_note, "Död")

    def test_failed_update_rolls_back_null_clearing(self):
        """A failure after the null-clearing UPDATE (ClearFields.pre_write) must roll it back."""
        db.Individual.update(death_date=datetime(2024, 1, 1), death_note="Död").where(
            db.Individual.id == self.individuals[0].id
        ).execute()
        self._login("owner")
        with mock.patch("utils.individual_legacy.LegacyFormChecks.after_save", side_effect=RuntimeError("nope")):
            response = self._patch({"death_date": None, "death_note": None})
        self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        individual = db.Individual.get_by_id(self.individuals[0].id)
        self.assertIsNotNone(individual.death_date)
        self.assertEqual(individual.death_note, "Död")

    def test_owner_can_still_undo_death(self):
        db.Individual.update(death_date=datetime(2024, 1, 1), death_note="Död").where(
            db.Individual.id == self.individuals[0].id
        ).execute()
        self._login("owner")
        response = self._patch({"death_date": None, "death_note": None})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        individual = db.Individual.get_by_id(self.individuals[0].id)
        self.assertIsNone(individual.death_date)
        self.assertIsNone(individual.death_note)

    def test_v2_lock_does_not_block_on_concurrent_weight_insert(self):
        """
        A concurrent legacy weight insert holds FOR KEY SHARE on the individual (FK check).
        The v2 lock must be FOR NO KEY UPDATE so it does not wait for that (and cannot deadlock
        with legacy update_weights).
        """
        self._login("owner")
        inserted, release = threading.Event(), threading.Event()

        def weight_insert():
            try:
                with db.DB_PROXY.atomic():
                    db.Weight.create(individual=self.individuals[0], weight=3.3, weight_date=datetime(2021, 5, 1))
                    inserted.set()
                    release.wait(15)
            finally:
                inserted.set()
                db.DB_PROXY.close()

        results = {}

        def patch():
            try:
                results["response"] = self._patch({"herd": "G1", "yearly_report_date": "2021-07-01"})
            finally:
                db.DB_PROXY.close()

        inserter = threading.Thread(target=weight_insert)
        inserter.start()
        self.assertTrue(inserted.wait(10))
        patcher = threading.Thread(target=patch)
        patcher.start()
        patcher.join(5)
        blocked = patcher.is_alive()
        release.set()
        patcher.join(15)
        inserter.join(15)
        self.assertFalse(blocked, "the v2 row lock must not wait for a concurrent weight insert")
        self.assertEqual(results["response"].status_code, 200, results["response"].get_data(as_text=True))

    def test_get_individual_exposes_can_transfer(self):
        expected = {"owner": True, "maja": True, "man": True, "admin": True, "sune": False, "spec": False}
        for username, can_transfer in expected.items():
            self._login(username)
            response = self.client.get(f"/api/v2/individual/{REGISTERED}")
            self.assertEqual(response.status_code, 200, username)
            self.assertIs(response.get_json()["can_transfer"], can_transfer, username)


class TestProtectedFieldsV2(DatabaseTest):
    """PATCH /api/individual/<number> must not write fields that only system flows own."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        super().setUp()

    def _patch_as(self, username, number, body):
        client = APP.test_client(use_cookies=True)
        client.post("/api/login", json={"username": username, "password": "pass"})
        return client.patch(f"/api/individual/{number}", json=body)

    def test_owner_cannot_set_digital_certificate_number(self):
        """Digital numbers come only from issuance (signed PDF + v2 row), never from a PATCH body."""
        target = self.individuals[3]  # G1-2112, uncertified, owner's herd G1
        response = self._patch_as("owner", UNREGISTERED, {"digital_certificate": 2147483647})
        stored = db.Individual.get_by_id(target.id)
        self.assertIsNone(stored.digital_certificate, response.get_data(as_text=True))
        self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        self.assertEqual(db.DigitalCertificateV2.select().count(), 0)

    def test_buyer_cannot_issue_digital_via_patch_flag(self):
        """`issue_digital` is an internal argument of the certificate routes, not a request field."""
        target = self.individuals[0]  # G1-2111, paper certificate "12", bred in G1
        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[1],
            signature=self.manager,
            individual=target,
            herd_tracking_date=datetime(2021, 6, 1),
        )
        buyer = da.register_user("buyer", "pass")
        buyer.add_role("owner", self.herds[1].id)
        self.assertFalse(db.User.get_by_id(buyer.id).can_issue_certificate(db.Individual.get_by_id(target.id)))
        response = self._patch_as("buyer", REGISTERED, {"issue_digital": True})
        stored = db.Individual.get_by_id(target.id)
        self.assertEqual((stored.certificate, stored.digital_certificate), ("12", None), response.get_json())

    def test_owner_cannot_move_rabbit_into_foreign_litter(self):
        """A litter of another genebank (M3) or of a herd the owner cannot edit (G2) is refused."""
        target = self.individuals[3]  # G1-2112, litter breeding[0] (herd G1)
        for foreign in (self.breeding[1], self.breeding[2]):
            response = self._patch_as("owner", UNREGISTERED, {"breeding": foreign.id})
            self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
            self.assertEqual(db.Individual.get_by_id(target.id).breeding_id, self.breeding[0].id)

    def test_fk_aliases_cannot_bypass_the_checks(self):
        """breeding_id/origin_herd_id are not form fields; only the checked canonical keys are written."""
        target = self.individuals[3]
        for body in ({"breeding_id": self.breeding[1].id}, {"origin_herd_id": self.herds[2].id}):
            self._patch_as("owner", UNREGISTERED, body)
            stored = db.Individual.get_by_id(target.id)
            self.assertEqual((stored.breeding_id, stored.origin_herd_id), (self.breeding[0].id, self.herds[0].id), body)

    def test_litter_moves_the_user_may_make_still_work(self):
        """Keeps the owner's move into an own litter and a manager's move within the genebank."""
        own = db.Breeding.create(
            birth_date=datetime(2021, 2, 2),
            mother=self.parents[0],
            father=self.parents[1],
            breeding_herd_id=self.herds[0],
        )
        for username, litter in (("owner", own), ("man", self.breeding[2])):
            response = self._patch_as(username, UNREGISTERED, {"breeding": litter.id})
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            self.assertEqual(db.Individual.get_by_id(self.individuals[3].id).breeding_id, litter.id)


class TestUndoDeathV2(DatabaseTest):
    """PATCH /api/individual/<number> with the death fields sent as null: v2's undo of a death (IR-51)."""

    V4 = {"death_date": None, "death_note": None, "butchered": False}

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.ind = self.individuals[0]  # G1-2111, the owner's herd, born 2021-02-01
        db.Individual.update(death_date=datetime(2024, 1, 1), death_note="Död", butchered=True).where(
            db.Individual.id == self.ind.id
        ).execute()
        self.client.post("/api/login", json={"username": "owner", "password": "pass"})

    def _patch(self, body):
        return self.client.patch(f"/api/individual/{REGISTERED}", json=body)

    def _death(self):
        stored = db.Individual.get_by_id(self.ind.id)
        return stored.death_date, stored.death_note, stored.butchered

    def test_undo_death_v4_body(self):
        response = self._patch(self.V4)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(self._death(), (None, None, False))

    def test_undo_death_butchered_null(self):
        response = self._patch({"death_date": None, "death_note": None, "butchered": None})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(self._death(), (None, None, None))

    @unittest.skipUnless(_USE_POSTGRES, "audit_log is written by PostgreSQL triggers")
    def test_undo_death_audit_rows(self):
        """The clearing is an UPDATE of its own, then `butchered: false` is the save's row."""
        db.DATABASE.execute_sql("TRUNCATE audit_log RESTART IDENTITY")
        response = self._patch(self.V4)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        rows = db.AuditLog.select().where(
            db.AuditLog.table_name == "individual", db.AuditLog.record_id == str(self.ind.id)
        )
        changed = [set(row.changed_fields) for row in rows.order_by(db.AuditLog.id)]
        self.assertEqual(changed, [{"death_date", "death_note"}, {"butchered"}])

    def test_undo_death_rolls_back_with_conflicting_attestation(self):
        """Review Focus 5: the writer's 409 comes after the clearing, which rolls back with the rest."""
        response = self._patch({"death_date": None, "herd": "G1", "yearly_report_date": "2020-01-01"})
        self.assertEqual(response.status_code, 409, response.get_data(as_text=True))
        self.assertEqual(self._death(), (datetime(2024, 1, 1).date(), "Död", True))


class TestGenebankHerdsV2(DatabaseTest):
    """GET /api/v2/genebank/<id>/herds."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="owner", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post("/api/login", json={"username": username, "password": password})

    def test_owner_lists_herds_of_own_genebank_without_contact_data(self):
        self._login()
        response = self.client.get(f"/api/v2/genebank/{self.genebanks[0].id}/herds")
        self.assertEqual(response.status_code, 200)
        herds = response.get_json()["herds"]
        self.assertEqual([h["herd"] for h in herds], ["G1", "G2"])
        for herd in herds:
            self.assertEqual(set(herd), {"herd", "herd_name", "is_active"})

    def test_other_genebank_is_hidden(self):
        self._login()
        response = self.client.get(f"/api/v2/genebank/{self.genebanks[1].id}/herds")
        self.assertEqual(response.status_code, 404)

    def test_requires_login(self):
        response = self.client.get(f"/api/v2/genebank/{self.genebanks[0].id}/herds")
        self.assertIn(response.status_code, (302, 401))
