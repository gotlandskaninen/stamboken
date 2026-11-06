"""Mutations through the real HTTP surface (incl. the v2 PATCH sale)."""

import os
import uuid

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402
from tests.ht_helpers import age_row, ht_row  # noqa: E402

limiter.enabled = False
REGISTERED = "G1-2111"  # individuals[0]: born 2021-02-01 in G1, BIRTH row on that date
SALE_DATE = "2021-06-01"


class MutationBase(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.g3 = db.Herd.create(genebank=self.genebanks[0], herd="G3", herd_name="Tre", is_active=True)
        self.gx1 = db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför", is_active=True)

    def _login(self, username, password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client.get("/api/logout")
        self.client.post("/api/login", json={"username": username, "password": password})

    def _sell(self, herd, day=SALE_DATE):
        return self.client.patch(f"/api/individual/{REGISTERED}", json={"herd": herd, "selling_date": day})

    def _history(self):
        return self.client.get(f"/api/v2/individual/{REGISTERED}/herd-tracking").get_json()

    def _void(self, row_id, reason="Fel köpare", operation_id=None):
        body = {"reason": reason, "operation_id": operation_id or str(uuid.uuid4())}
        return self.client.post(f"/api/v2/herd-tracking/{row_id}/void", json=body)


class TestUndoSaleApi(MutationBase):
    def test_sell_undo_sell_again_on_the_same_date(self):
        """Review Focus 2 — the second sale validates against the ACTIVE history."""
        self._login("owner")
        self.assertEqual(self._sell("G2").status_code, 200)
        latest = self._history()["rows"][0]
        self.assertTrue(latest["can_undo_sale"])
        response = self._void(latest["id"])
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["rows"][0]["voided_reason"], "Fel köpare")
        individual = self.client.get(f"/api/v2/individual/{REGISTERED}").get_json()
        self.assertEqual(individual["herd"]["herd"], "G1")
        again = self._sell("G3")
        self.assertEqual(again.status_code, 200, again.get_data(as_text=True))
        v1 = self.client.get(f"/api/v2/individual/{REGISTERED}").get_json()["herd_tracking"]
        self.assertEqual([t["herd"] for t in v1], ["G3", "G1"])

    def test_same_operation_id_twice_is_one_void(self):
        self._login("owner")
        self._sell("G2")
        row_id, op = self._history()["rows"][0]["id"], str(uuid.uuid4())
        self.assertEqual(self._void(row_id, operation_id=op).status_code, 200)
        self.assertEqual(self._void(row_id, operation_id=op).status_code, 200)
        self.assertEqual(db.HerdTracking.select().where(db.HerdTracking.voided_operation_id == op).count(), 1)

    def test_outside_the_window_is_a_403_problem(self):
        self._login("owner")
        self._sell("G2")
        row_id = self._history()["rows"][0]["id"]
        age_row(db.HerdTracking.get_by_id(row_id), 8)
        response = self._void(row_id)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.headers["Content-Type"], "application/problem+json")
        self.assertTrue(response.get_json()["detail"].endswith("Kontakta genbanksansvarig."))

    def test_contact_details_in_the_reason_are_a_400(self):
        self._login("owner")
        self._sell("G2")
        response = self._void(self._history()["rows"][0]["id"], reason="Köparen heter Anna, anna@example.com")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["detail"], "Skriv inte köparens namn eller kontaktuppgifter.")

    def test_inaccessible_row_is_404(self):
        da.register_user("nobody", "pass")
        self._login("nobody")
        self.assertEqual(self._void(self.herd_tracking[0].id).status_code, 404)

    def test_body_must_be_json(self):
        self._login("owner")
        response = self.client.post(f"/api/v2/herd-tracking/{self.herd_tracking[0].id}/void", data="x")
        self.assertEqual(response.status_code, 400)


class TestCorrectionApi(MutationBase):
    def _correct(self, body):
        return self.client.post(f"/api/v2/individual/{REGISTERED}/herd-tracking/corrections", json=body)

    def test_manager_corrects_and_gets_the_history(self):
        self._login("man")
        response = self._correct(
            {
                "operation_id": str(uuid.uuid4()),
                "void_ids": [],
                "events": [{"date": "2021-09-30", "herd": "GX1", "kind": "TRANSFER", "notes": "Såld på marknad"}],
            }
        )
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["rows"][0]["herd"]["label"], "Såld utanför genbanken")

    def test_owner_is_403(self):
        self._login("owner")
        response = self._correct({"events": [{"date": "2021-09-30", "herd": "GX1", "kind": "TRANSFER"}]})
        self.assertEqual(response.status_code, 403)

    def test_birth_alone_never_triggers_the_same_day_rule(self):
        """A CORRECTION on the birth date is valid: BIRTH rows sort first and never block (holder G1, G2 differs)."""
        self._login("man")
        response = self._correct({"events": [{"date": "2021-02-01", "herd": "G2", "kind": "CORRECTION"}]})
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))

    def test_same_day_conflict_is_409_with_rows(self):
        self._login("man")
        self._sell("G2", "2021-07-01")
        response = self._correct({"events": [{"date": "2021-07-01", "herd": "G3", "kind": "CORRECTION"}]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["rows"][0]["date"], "2021-07-01")

    def test_malformed_body_is_400(self):
        self._login("man")
        self.assertEqual(self._correct({"events": "nope"}).status_code, 400)
        self.assertEqual(self._correct({"void_ids": ["x"], "events": [], "reason": "r"}).status_code, 400)


class TestUndoOperationApi(MutationBase):
    def test_manager_undoes_a_correction(self):
        self._login("man")
        op = str(uuid.uuid4())
        self.client.post(
            f"/api/v2/individual/{REGISTERED}/herd-tracking/corrections",
            json={"operation_id": op, "events": [{"date": "2021-09-30", "herd": "GX1", "kind": "TRANSFER"}]},
        )
        response = self.client.post(f"/api/v2/herd-tracking/operations/{op}/undo", json={"reason": "Fel kanin"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["individuals"][0]["number"], REGISTERED)
        self.assertEqual(db.Individual.get(db.Individual.number == REGISTERED).current_herd.herd, "G1")

    def test_owner_is_403_and_unknown_is_404(self):
        self._login("owner")
        self.assertEqual(
            self.client.post(f"/api/v2/herd-tracking/operations/{uuid.uuid4()}/undo", json={"reason": "x"}).status_code,
            403,
        )
        self._login("man")
        self.assertEqual(
            self.client.post(f"/api/v2/herd-tracking/operations/{uuid.uuid4()}/undo", json={"reason": "x"}).status_code,
            404,
        )

    def test_later_operation_is_409(self):
        self._login("man")
        op = str(uuid.uuid4())
        self.client.post(
            f"/api/v2/individual/{REGISTERED}/herd-tracking/corrections",
            json={"operation_id": op, "events": [{"date": "2021-09-30", "herd": "G2", "kind": "TRANSFER"}]},
        )
        self._sell("G3", "2021-10-01")
        response = self.client.post(f"/api/v2/herd-tracking/operations/{op}/undo", json={"reason": "Fel"})
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.get_json()["rows"])


class TestGenebankChangeIsAdminOnly(MutationBase):
    """A move into another genebank is an admin correction; reversing one is admin-only too, on every
    herd-tracking route. The others get read access to Mellerud so the M23 gate lets them reach the service."""

    def setUp(self):
        super().setUp()
        da.register_user("man2", "pass").add_role("manager", self.genebanks[1].id)
        self.manager.add_role("viewer", self.genebanks[1].id)
        self.owner.add_role("viewer", self.genebanks[1].id)
        self.move = ht_row(
            "TRANSFER",
            individual=self.individuals[0],
            from_herd=self.herds[0],
            herd=self.herds[2],  # G1 -> M3
            signature=self.admin,
            herd_tracking_date=SALE_DATE,
            notes="Felregistrerad",
        )

    def _assert_still_moved(self):
        self.assertIsNone(db.HerdTracking.get_by_id(self.move.id).voided_at)
        self.assertEqual(db.Individual.get(db.Individual.number == REGISTERED).current_herd.herd, "M3")

    def test_destination_manager_cannot_void_it_but_an_admin_can(self):
        self._login("man2")
        response = self._void(self.move.id)
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
        self._assert_still_moved()
        self._login("admin")
        self.assertEqual(self._void(self.move.id).status_code, 200)
        self.assertEqual(db.Individual.get(db.Individual.number == REGISTERED).current_herd.herd, "G1")

    def test_seller_cannot_undo_it_as_a_sale(self):
        self._login("owner")
        latest = self._history()["rows"][0]
        self.assertEqual((latest["id"], latest["can_void"], latest["can_undo_sale"]), (self.move.id, False, False))
        self.assertEqual(self._void(self.move.id).status_code, 403)
        self._assert_still_moved()

    def test_admin_correction_out_of_the_foreign_genebank_needs_a_note(self):
        """A correction event's herd is in the origin genebank, but from the M3 holder it crosses genebanks:
        an admin correction, whose reason is the row's note."""
        self._login("admin")
        url = f"/api/v2/individual/{REGISTERED}/herd-tracking/corrections"
        event = {"date": "2021-07-01", "herd": "G2", "kind": "TRANSFER"}
        response = self.client.post(url, json={"events": [event]})
        self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        self.assertIn("anledning", response.get_json()["detail"])
        self._assert_still_moved()
        response = self.client.post(url, json={"events": [{**event, "notes": "Tillbaka, fel genbank"}]})
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["rows"][0]["notes"], "Tillbaka, fel genbank")

    def test_a_void_exposing_an_older_holder_in_another_genebank_is_admin_only(self):
        """After the admin voids G1->M3, the remaining M3->M4 looks like a Mellerud move, but voiding or undoing it
        takes the rabbit from M4 back to G1: judged by the holder before and after, not the row alone."""
        self._login("admin")
        self.assertEqual(self._void(self.move.id).status_code, 200)
        m4 = db.Herd.create(genebank=self.genebanks[1], herd="M4", herd_name="Fyra", is_active=True)
        later = ht_row(  # written after the void here, so the undo below is not refused as stale first
            "TRANSFER",
            individual=self.individuals[0],
            from_herd=self.herds[2],
            herd=m4,
            signature=self.admin,
            herd_tracking_date="2021-07-01",
        )
        self._login("man2")
        self.assertEqual(self._void(later.id).status_code, 403)
        self._login("man")
        undo = self.client.post(f"/api/v2/herd-tracking/operations/{later.operation_id}/undo", json={"reason": "x"})
        self.assertEqual(undo.status_code, 403, undo.get_data(as_text=True))
        url = f"/api/v2/individual/{REGISTERED}/herd-tracking/corrections"
        voided = self.client.post(url, json={"void_ids": [later.id], "events": [], "reason": "Fel"})
        self.assertEqual(voided.status_code, 403, voided.get_data(as_text=True))
        self.assertIsNone(db.HerdTracking.get_by_id(later.id).voided_at)
        self.assertEqual(db.Individual.get(db.Individual.number == REGISTERED).current_herd.herd, "M4")

    def test_a_legacy_row_without_from_herd_moves_from_the_holder_before_it(self):
        """Legacy TRANSFER rows have no from_herd: removing a G1->M3 one is a genebank change too."""
        self._login("admin")
        self.assertEqual(self._void(self.move.id).status_code, 200)
        legacy = ht_row("TRANSFER", individual=self.individuals[0], herd=self.herds[2], herd_tracking_date="2021-06-15")
        ht_row(
            "TRANSFER",
            individual=self.individuals[0],
            from_herd=self.herds[2],
            herd=self.herds[1],
            signature=self.admin,
            herd_tracking_date="2021-07-01",
        )
        self._login("man")
        url = f"/api/v2/individual/{REGISTERED}/herd-tracking/corrections"
        response = self.client.post(url, json={"void_ids": [legacy.id], "events": [], "reason": "Fel"})
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
        self.assertIsNone(db.HerdTracking.get_by_id(legacy.id).voided_at)

    def test_origin_manager_cannot_undo_or_correct_it(self):
        self._login("man")
        undo = self.client.post(f"/api/v2/herd-tracking/operations/{self.move.operation_id}/undo", json={"reason": "x"})
        self.assertEqual(undo.status_code, 403, undo.get_data(as_text=True))
        url = f"/api/v2/individual/{REGISTERED}/herd-tracking/corrections"
        voided = self.client.post(url, json={"void_ids": [self.move.id], "events": [], "reason": "Fel"})
        self.assertEqual(voided.status_code, 403, voided.get_data(as_text=True))
        back = self.client.post(url, json={"events": [{"date": "2021-07-01", "herd": "G2", "kind": "TRANSFER"}]})
        self.assertEqual(back.status_code, 403, back.get_data(as_text=True))
        self._assert_still_moved()


class TestAccessGateBeforeServices(MutationBase):
    """M23: no access to the genebank => 404 on real ids, even for an already-voided row."""

    def setUp(self):
        super().setUp()
        self.stranger = da.register_user("stranger", "pass")
        self.other_manager = da.register_user("man2", "pass")
        self.other_manager.add_role("manager", self.genebanks[1].id)

    def _owner_sells_and_voids(self):
        self._login("owner")
        self._sell("G2")
        row_id = self._history()["rows"][0]["id"]
        self.assertEqual(self._void(row_id).status_code, 200)
        return row_id

    def test_void_of_already_voided_row_is_404_for_a_stranger(self):
        row_id = self._owner_sells_and_voids()
        self._login("stranger")
        response = self._void(row_id)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("Fel köpare", response.get_data(as_text=True))

    def test_unknown_row_is_the_same_404(self):
        self._login("stranger")
        self.assertEqual(self._void(10**9).status_code, 404)

    def test_correction_for_other_genebank_manager_is_404(self):
        self._login("man2")
        response = self.client.post(
            f"/api/v2/individual/{REGISTERED}/herd-tracking/corrections",
            json={"events": [{"date": "2021-09-30", "herd": "GX1", "kind": "TRANSFER"}]},
        )
        self.assertEqual(response.status_code, 404)

    def test_undo_for_other_genebank_manager_is_404(self):
        self._login("man")
        op = str(uuid.uuid4())
        self.client.post(
            f"/api/v2/individual/{REGISTERED}/herd-tracking/corrections",
            json={"operation_id": op, "events": [{"date": "2021-09-30", "herd": "GX1", "kind": "TRANSFER"}]},
        )
        self._login("man2")
        response = self.client.post(f"/api/v2/herd-tracking/operations/{op}/undo", json={"reason": "x"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(db.Individual.get(db.Individual.number == REGISTERED).current_herd.herd, "GX1")


class TestFieldTypesAndUndoEdges(MutationBase):
    def _correct_op(self):
        op = str(uuid.uuid4())
        self.client.post(
            f"/api/v2/individual/{REGISTERED}/herd-tracking/corrections",
            json={"operation_id": op, "events": [{"date": "2021-09-30", "herd": "GX1", "kind": "TRANSFER"}]},
        )
        return op

    def test_non_string_reason_on_void_is_400(self):
        self._login("owner")
        self._sell("G2")
        response = self._void(self._history()["rows"][0]["id"], reason=123)
        self.assertEqual(response.status_code, 400)

    def test_non_string_reason_on_undo_is_400(self):
        self._login("man")
        op = self._correct_op()
        response = self.client.post(f"/api/v2/herd-tracking/operations/{op}/undo", json={"reason": 123})
        self.assertEqual(response.status_code, 400)

    def test_non_string_notes_in_correction_is_400(self):
        self._login("man")
        response = self.client.post(
            f"/api/v2/individual/{REGISTERED}/herd-tracking/corrections",
            json={"events": [{"date": "2021-09-30", "herd": "GX1", "kind": "TRANSFER", "notes": 5}]},
        )
        self.assertEqual(response.status_code, 400)

    def test_undo_with_invalid_operation_id_is_400(self):
        self._login("man")
        response = self.client.post("/api/v2/herd-tracking/operations/not-a-uuid/undo", json={"reason": "x"})
        self.assertEqual(response.status_code, 400)

    def test_undo_with_non_object_body_is_400(self):
        self._login("man")
        op = self._correct_op()
        response = self.client.post(f"/api/v2/herd-tracking/operations/{op}/undo", json=["x"])
        self.assertEqual(response.status_code, 400)

    def test_undo_of_an_unpromoted_rabbit_is_the_services_409_not_404(self):
        self._login("man")
        op = self._correct_op()
        db.Individual.update(voided=True).where(db.Individual.number == REGISTERED).execute()
        response = self.client.post(f"/api/v2/herd-tracking/operations/{op}/undo", json={"reason": "Fel"})
        self.assertEqual(response.status_code, 409, response.get_data(as_text=True))
        self.assertIn("avpromoverad", response.get_json()["detail"])
