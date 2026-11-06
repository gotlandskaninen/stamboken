"""
Characterization tests for the legacy individual write path (PATCH/POST /api/individual).

They pin what `update_individual`, `form_to_individual` and `add_individual` answer today,
quirks included, so the rewrite to commands can be checked against them. IR-xx are rule ids
from the design notes for the individual commands (not in this repo).

isort:skip_file
"""

import os
from datetime import datetime

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from herdbook import APP  # noqa: E402
from utils.pedigree_guard import CYCLE_PROBLEM  # noqa: E402

from tests.ht_helpers import ht_row  # noqa: E402
from tests.test_legacy_api_contracts import FlaskTest  # noqa: E402

UPDATED = {"status": "success", "message": "Individual Updated", "digital_certificate": None}
GENEBANK_FORBIDDEN = {
    "status": "error",
    "message": "Bara administratör kan flytta en individ till en annan genbank.",
    "problem_status": 403,
    "title": "Åtkomst nekad",
    "rows": [],
}
GENERIC_FAILURE = "Kunde inte uppdatera individ."


def error(message):
    return {"status": "error", "message": message}


class TestLegacyIndividualWriteCharacterization(FlaskTest):
    # self.individuals[0] = G1-2111 (paper certificate "12"), [3] = G1-2112 (no certificate), both in G1.

    def _client(self, user):
        client = APP.test_client(use_cookies=True)
        self.login(client, user)
        return client

    def _send(self, method, user, body):
        return getattr(self._client(user), method)("/api/individual", json=body)

    def _patch(self, user, body):
        return self._send("patch", user, body)

    def _body(self, individual, **fields):
        return {"id": individual.id, "number": individual.number, "herd": "G1", **fields}

    def _assert_response(self, response, status, body):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.get_json(), body)

    def _assert_patch(self, user, body, expected, status=200):
        self._assert_response(self._patch(user, body), status, expected)

    def _name_user(self, user):
        """The fixture users have no username, which the CSV log lines start with."""
        user.username = user.email
        user.save()

    def _row(self, individual):
        """The stored row without `updated_at`, which every successful update touches."""
        row = db.Individual.select().where(db.Individual.id == individual.id).dicts().get()
        row.pop("updated_at")
        return row

    def _count(self, model, individual):
        return model.select().where(model.individual == individual.id).count()

    def _active_rows(self, individual):
        return list(db.HerdTracking.select().where(db.HerdTracking.individual == individual.id, db.ht_not_voided()))

    def _caretaker(self):
        """A caretaker of G1: may edit its rabbits but never sell or move them."""
        membership = db.Membership.create(member_number=6, membership_status="active")
        self.herds[0].membership = membership
        self.herds[0].save()
        user = da.register_user("sune@example.com", "pass", username="sune")
        member = db.Member.create(
            membership=membership,
            first_name="Sune",
            last_name="Skötarsson",
            email="sune@example.com",
            role="skotare",
            user=user,
        )
        db.HerdAccessGrant.create(member=member, herd=self.herds[0], granted_by=self.admin)
        return user

    def _own_breeding_individual(self):
        """A certified rabbit alone in its litter, with a BIRTH row (as in test_individual_sell_v2)."""
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

    def _origin_body(self, individual, breeding, **fields):
        # `breeding` is needed: the "origin_herd more inds" count reads form["breeding"] (IR-27).
        return self._body(individual, origin_herd={"herd": "M3"}, breeding=breeding.id, **fields)

    def _get_object(self, user, number):
        response = self._client(user).get(f"/api/individual/{number}")
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    # --- whole-object echo -------------------------------------------------------------------

    def test_whole_object_echo_on_certified_rabbit_stores_only_is_active(self):
        ind = self.individuals[0]
        body = self._get_object(self.owner, ind.number)
        self.assertIsInstance(body["herd"], dict)
        before = self._row(ind)
        counts = [self._count(model, ind) for model in (db.HerdTracking, db.Weight, db.Bodyfat)]
        self._assert_patch(self.owner, body, UPDATED)
        # The GET object carries the computed `is_active` (database.py:767), and the echo stores it.
        self.assertTrue(before.pop("is_active"))
        after = self._row(ind)
        self.assertFalse(after.pop("is_active"))
        self.assertEqual(after, before)
        self.assertEqual([self._count(model, ind) for model in (db.HerdTracking, db.Weight, db.Bodyfat)], counts)

    def test_founder_whole_object_echo(self):
        founder = self.parents[0]  # G1-1911: in a litter without parents, so mother/father come back as nulls
        body = self._get_object(self.owner, founder.number)
        self.assertEqual(body["mother"], {"id": None, "name": None, "number": None})
        self._assert_patch(self.owner, body, error("Invalid parents"))

    # --- error order -------------------------------------------------------------------------

    def test_error_order_number_exists_before_manager_only(self):
        ind = self.individuals[0]
        body = {"id": ind.id, "number": self.individuals[1].number, "herd": "G1"}
        self._assert_patch(self.owner, body, error("Individual number already exists"))
        self.assertEqual(db.Individual.get_by_id(ind.id).number, "G1-2111")

    def test_error_order_manager_only_number_before_certificate(self):
        ind = self.individuals[0]
        body = {"id": ind.id, "number": "G1-2999", "herd": "G1", "certificate": "77"}
        self._assert_patch(self.owner, body, error("Bara managers kan uppdatera number"))
        stored = db.Individual.get_by_id(ind.id)
        self.assertEqual((stored.number, stored.certificate), ("G1-2111", "12"))

    def test_error_order_certificate_before_color(self):
        ind = self.individuals[0]
        body = self._body(ind, certificate="77", color="finns-inte")
        self._assert_patch(self.owner, body, error("Bara managers kan uppdatera certificate"))

    def test_error_order_color_before_parents(self):
        ind = self.individuals[3]
        body = self._body(ind, color="finns-inte", mother={"number": "X9-0000"})
        self._assert_patch(self.owner, body, error("Unknown color: 'finns-inte''"))

    def test_error_order_cycle_before_origin_auth(self):
        ind = self.individuals[3]
        litter = db.Breeding.create(
            breed_date=datetime(2022, 1, 1),
            birth_date=datetime(2022, 2, 1),
            mother=ind,
            father=self.parents[1],
            litter_size=1,
            litter_size6w=1,
            breeding_herd_id=self.herds[0],
        )
        # One kit in the litter, or "origin_herd more inds" (IR-27) answers first.
        db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2301")
        body = self._body(ind, breeding=litter.id, origin_herd={"herd": "G2"})
        self._assert_patch(self.owner, body, dict(CYCLE_PROBLEM))
        self.assertEqual(db.Individual.get_by_id(ind.id).breeding_id, self.breeding[0].id)

    # --- missing and invalid input -----------------------------------------------------------

    def _assert_server_error(self, response):
        self.assertEqual(response.status_code, 500)
        body = response.get_json()
        self.assertEqual(set(body), {"status", "message"})
        self.assertEqual(body["status"], "error")
        self.assertTrue(body["message"].startswith("Be Admin kolla server loggarna"), body["message"])

    def test_missing_herd_answers_500(self):
        ind = self.individuals[3]
        self._assert_server_error(self._patch(self.admin, {"id": ind.id, "number": ind.number}))

    def test_unknown_origin_herd_answers_500(self):
        self._assert_server_error(self._patch(self.admin, self._body(self.individuals[3], origin_herd={"herd": "Q9"})))

    def test_missing_number_answers_500(self):
        self._assert_server_error(self._patch(self.admin, {"id": self.individuals[3].id, "herd": "G1"}))

    def test_invalid_bodyfat_level_is_dropped(self):
        ind = self.individuals[3]
        body = self._body(ind, bodyfat=[{"date": "2024-01-01", "bodyfat": "fet"}])
        self._assert_patch(self.owner, body, UPDATED)
        self.assertEqual(self._count(db.Bodyfat, ind), 0)

    def test_null_is_skip_in_legacy(self):
        ind = self.individuals[3]
        ind.death_date = datetime(2024, 3, 1).date()
        ind.save()
        self._assert_patch(self.owner, self._body(ind, death_date=None), UPDATED)
        self.assertEqual(db.Individual.get_by_id(ind.id).death_date, datetime(2024, 3, 1).date())

    def test_selling_date_to_same_herd_is_attestation(self):
        ind = self.individuals[3]
        before = self._count(db.HerdTracking, ind)
        self._assert_patch(self.owner, self._body(ind, selling_date="2021-06-01"), UPDATED)
        self.assertEqual(self._count(db.HerdTracking, ind), before + 1)
        newest = (
            db.HerdTracking.select().where(db.HerdTracking.individual == ind.id).order_by(db.HerdTracking.id.desc())
        )
        self.assertEqual(newest.get().kind, "ATTESTATION")

    def test_post_with_death_date_answers_500(self):
        body = {"number": "G1-9902", "herd": "G1", "birth_date": "2024-01-01", "death_date": "2024-05-01"}
        self._assert_server_error(self._send("post", self.owner, body))
        self.assertFalse(db.Individual.select().where(db.Individual.number == "G1-9902").exists())

    def test_post_with_weights_answers_500(self):
        body = {
            "number": "G1-9903",
            "herd": "G1",
            "birth_date": "2024-01-01",
            "weights": [{"date": "2024-02-01", "weight": 2.5}],
        }
        self._assert_server_error(self._send("post", self.owner, body))
        self.assertFalse(db.Individual.select().where(db.Individual.number == "G1-9903").exists())

    # --- null in the manager-only checks -----------------------------------------------------

    def test_null_certificate_on_certified_refused_for_owner(self):
        ind = self.individuals[0]
        self._assert_patch(
            self.owner, self._body(ind, certificate=None), error("Bara managers kan uppdatera certificate")
        )
        self.assertEqual(db.Individual.get_by_id(ind.id).certificate, "12")

    def test_null_certificate_on_certified_is_noop_for_manager(self):
        ind = self.individuals[0]
        self._assert_patch(self.manager, self._body(ind, certificate=None), UPDATED)
        self.assertEqual(db.Individual.get_by_id(ind.id).certificate, "12")

    def test_null_digital_before_certificate(self):
        ind = self.individuals[3]
        db.Individual.update(digital_certificate=100000).where(db.Individual.id == ind.id).execute()
        body = self._body(ind, digital_certificate=None, certificate="77")
        self._assert_patch(self.owner, body, error("Bara managers kan uppdatera digital_certificate"))
        stored = db.Individual.get_by_id(ind.id)
        self.assertEqual((stored.certificate, stored.digital_certificate), (None, 100000))

    def test_null_breeding_is_unknown_breeding_event(self):
        ind = self.individuals[3]
        self._assert_patch(self.owner, self._body(ind, breeding=None), error("Unknown breeding event: 'None''"))
        self.assertEqual(db.Individual.get_by_id(ind.id).breeding_id, self.breeding[0].id)

    def test_null_origin_herd_is_generic_error(self):
        self._assert_patch(self.owner, self._body(self.individuals[3], origin_herd=None), error(GENERIC_FAILURE))

    def test_null_mother_is_generic_error(self):
        self._assert_patch(self.owner, self._body(self.individuals[3], mother=None), error(GENERIC_FAILURE))

    def test_null_weights_is_generic_error(self):
        self._assert_patch(self.owner, self._body(self.individuals[3], weights=None), error(GENERIC_FAILURE))

    # --- litter and number quirks ------------------------------------------------------------

    def test_bad_selling_date_before_transfer_refusal(self):
        ind = self.individuals[3]
        before = self._count(db.HerdTracking, ind)
        body = self._body(ind, herd="G2", selling_date="31/12")
        self._assert_patch(self._caretaker(), body, error(GENERIC_FAILURE))
        self.assertEqual(self._count(db.HerdTracking, ind), before)

    def test_rabbit_without_litter_cannot_be_updated(self):
        ind = db.Individual.create(origin_herd=self.herds[0], number="G1-2120", notes="orörd")
        ht_row("BIRTH", herd=self.herds[0], individual=ind, herd_tracking_date=datetime(2021, 2, 1))
        self._assert_patch(self.owner, self._body(ind, notes="ny"), error(GENERIC_FAILURE))
        self.assertEqual(db.Individual.get_by_id(ind.id).notes, "orörd")

    def test_v2_rabbit_without_litter_fails_before_the_update(self):
        ind = db.Individual.create(origin_herd=self.herds[0], number="G1-2120", notes="orörd")
        ht_row("BIRTH", herd=self.herds[0], individual=ind, herd_tracking_date=datetime(2021, 2, 1))
        # v2 never reaches update_individual: its get_individual -> as_dict reads breeding.birth_date.
        with self.assertRaises(AttributeError):
            self._client(self.owner).patch(f"/api/individual/{ind.number}", json={"notes": "ny"})
        self.assertEqual(db.Individual.get_by_id(ind.id).notes, "orörd")

    def test_move_from_litter_without_birth_date(self):
        undated = db.Breeding.create(
            breed_date=datetime(2021, 1, 1),
            mother=self.parents[0],
            father=self.parents[1],
            breeding_herd_id=self.herds[0],
        )
        ind = db.Individual.create(origin_herd=self.herds[0], breeding=undated, number="G1-2121")
        ht_row("BIRTH", herd=self.herds[0], individual=ind, herd_tracking_date=datetime(2021, 2, 1))
        body = self._body(ind, breeding=self.breeding[0].id)
        self._assert_patch(self.manager, body, error(GENERIC_FAILURE))
        self.assertEqual(db.Individual.get_by_id(ind.id).breeding_id, undated.id)

    def test_numeric_certificate_echo_is_a_collision(self):
        ind = self.individuals[0]
        self._assert_patch(
            self.manager, self._body(ind, certificate=12), error("Individual certificate already exists")
        )
        self.assertEqual(db.Individual.get_by_id(ind.id).certificate, "12")

    def test_null_or_empty_number_is_noop(self):
        ind = self.individuals[3]
        for number in (None, ""):
            with self.subTest(number=number):
                self._assert_patch(self.owner, {"id": ind.id, "number": number, "herd": "G1"}, UPDATED)
                self.assertEqual(db.Individual.get_by_id(ind.id).number, "G1-2112")

    def test_certified_owner_echoes_breeding(self):
        ind = self.individuals[0]
        self._assert_patch(self.owner, self._body(ind, breeding=ind.breeding_id), UPDATED)
        self.assertEqual(db.Individual.get_by_id(ind.id).breeding_id, ind.breeding_id)

    def test_certified_owner_null_breeding(self):
        ind = self.individuals[0]
        self._assert_patch(self.owner, self._body(ind, breeding=None), error("Unknown breeding event: 'None''"))

    # --- herd tracking and genebank changes --------------------------------------------------

    def test_caretaker_to_unknown_herd_is_400(self):
        ind = self.individuals[3]
        before = self._count(db.HerdTracking, ind)
        body = self._body(ind, herd="Q9", selling_date="2021-06-01")
        expected = {
            "status": "error",
            "message": "Okänd besättning: Q9.",
            "problem_status": 400,
            "title": "Ogiltig begäran",
            "rows": [],
        }
        self._assert_patch(self._caretaker(), body, expected)
        self.assertEqual(self._count(db.HerdTracking, ind), before)

    def test_date_csv_line(self):
        ind = self.individuals[3]
        self._name_user(self.owner)
        with self.assertLogs("Gotland_update", level="INFO") as logs:
            self._assert_patch(self.owner, self._body(ind, death_date="2024-05-01"), UPDATED)
        self.assertEqual(logs.output, ["INFO:Gotland_update:owner,G1-2112,death_date,2024-05-01,2024-05-01,"])

    def _cross_genebank_sale_body(self):
        return self._body(self.individuals[3], herd="M3", selling_date="2021-06-01")

    def _assert_no_transfer(self, individual):
        kinds = [row.kind for row in self._active_rows(individual)]
        self.assertNotIn("TRANSFER", kinds)

    def test_owner_cross_genebank_sale_admin_only(self):
        ind = self.individuals[3]
        self._assert_patch(self.owner, self._cross_genebank_sale_body(), GENEBANK_FORBIDDEN)
        self._assert_no_transfer(ind)

    def test_error_order_can_transfer_before_genebank(self):
        ind = self.individuals[3]
        expected = {
            "status": "error",
            "message": "Du får inte sälja eller flytta individen till den besättningen.",
            "problem_status": 403,
            "title": "Åtkomst nekad",
            "rows": [],
        }
        self._assert_patch(self._caretaker(), self._cross_genebank_sale_body(), expected)
        self._assert_no_transfer(ind)

    def test_admin_cross_genebank_sale_fixed_note(self):
        ind = self.individuals[3]
        self._assert_patch(self.admin, self._cross_genebank_sale_body(), UPDATED)
        transfers = [row for row in self._active_rows(ind) if row.kind == "TRANSFER"]
        self.assertEqual(
            [(row.herd.herd, row.notes) for row in transfers], [("M3", "Genbanksbyte av admin via legacy")]
        )

    def test_manager_cross_genebank_origin_admin_only(self):
        ind, litter = self._own_breeding_individual()
        before = self._row(ind)
        self._assert_patch(self.manager, self._origin_body(ind, litter), GENEBANK_FORBIDDEN)
        self.assertEqual(self._row(ind), before)

    def test_error_order_origin_genebank_before_weights(self):
        ind, litter = self._own_breeding_individual()
        body = self._origin_body(ind, litter, weights=[{"date": "2024-01-01", "weight": 2.5}])
        self._assert_patch(self.manager, body, GENEBANK_FORBIDDEN)
        self.assertEqual(self._count(db.Weight, ind), 0)

    def test_admin_cross_genebank_origin_of_moved_rabbit_409(self):
        ind, litter = self._own_breeding_individual()
        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[1],
            signature=self.manager,
            individual=ind,
            herd_tracking_date=datetime(2021, 6, 1),
        )
        expected = {
            "status": "error",
            "message": "Kaninen har flyttats. Rätta besättningshistoriken innan ursprungsbesättningen byts "
            "till en annan genbank.",
            "problem_status": 409,
            "title": "Konflikt",
            "rows": [],
        }
        self._name_user(self.admin)
        with self.assertLogs("Gotland_update", level="INFO") as logs:
            self._assert_patch(self.admin, self._origin_body(ind, litter), expected)
        self.assertIn("INFO:Gotland_update:admin,G1-2113,new_origin_herd,G1,M3,", logs.output)
        birth = [row for row in self._active_rows(ind) if row.kind == "BIRTH"]
        self.assertEqual([row.herd.herd for row in birth], ["G1"])
        self.assertEqual(db.Individual.get_by_id(ind.id).origin_herd_id, self.herds[0].id)

    # --- first certificate in a roster litter ------------------------------------------------

    def test_roster_alive_exceeds_6w_envelope(self):
        litter = db.Breeding.create(
            breed_date=datetime(2024, 12, 10),
            birth_date=datetime(2025, 1, 10),
            litter_number=1,
            litter_size=3,
            litter_size6w=2,
            mother=self.parents[0],
            father=self.parents[1],
            breeding_herd_id=self.herds[0],
        )
        ind = db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2511")
        db.Bunny.create(breeding=litter, slot_order=1, fate="registered", individual=ind)
        db.Bunny.create(breeding=litter, slot_order=2)
        db.Bunny.create(breeding=litter, slot_order=3)
        body = self._body(ind, certificate="P2")
        self._assert_patch(self.owner, body, {**error("roster_alive_exceeds_6w"), "must_mark_dead": 1})
        self.assertIsNone(db.Individual.get_by_id(ind.id).certificate)

    # --- v2 ----------------------------------------------------------------------------------

    def test_v2_unknown_origin_herd_answers_400(self):
        response = self._client(self.admin).patch("/api/individual/G1-2112", json={"origin_herd": {"herd": "Q9"}})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {"type": "about:blank", "title": "Update failed", "status": 400, "detail": "Unknown origin herd: 'Q9''"},
        )
