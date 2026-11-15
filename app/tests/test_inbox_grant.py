"""Writes on rabbits through the queue: InboxGrant in execute, …/spara, …/overlat, the trace, the waiting parent.

isort:skip_file
"""

import threading
from datetime import date, timedelta
from unittest import mock

import herdbook  # noqa: E402
import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.inbox as inbox  # noqa: E402
from utils.herd_tracking import HerdTrackingConflict  # noqa: E402
from utils.individual_commands import (  # noqa: E402
    AssignPaperCertificate,
    EditDescription,
    IndividualRefused,
    TransferIndividual,
    execute,
    roles_for,
)
from utils.individual_policy import Role  # noqa: E402

from tests.ht_helpers import ht_row  # noqa: E402
from tests.inbox_fixtures import InboxTest  # noqa: E402

# G1-1911 is a G1 doe and G2-1711 a Gotland buck; the paper agrees with Stamboken (the year's first litter).
NEW_RABBIT = {
    "action": "ny_kanin",
    "mother": "G1-1911",
    "father": "G2-1711",
    "birth_date": "2025-05-10",
    "litter_size": 5,
    "litter_size6w": 4,
    "sex": "female",
    "color": "bleighe",
    "paper_certificate": "SC-1",
    "paper_number": "G1-2511",
}


class GrantTest(InboxTest):
    def taken(self, user, herd=0):
        item = self.item(herd)
        inbox.take(item, user, over=False)
        return item, item.documents.get()

    def rabbit(self, number):
        return db.Individual.get(db.Individual.number == number)

    def certify(self, user, item, document, number="G1-2112", certificate="P-77"):
        grant = inbox.InboxGrant(item, user, document)
        with db.DB_PROXY.atomic():
            inbox.lock_item(item.id)
            return execute(
                user, self.rabbit(number).id, lambda ctx: [AssignPaperCertificate(certificate, number)], grant=grant
            )

    def save(self, item, document, **body):
        return self.post(f"/{item.id}/dokument/{document.id}/spara", **body)

    def transfer(self, item, document, **body):
        return self.post(f"/{item.id}/dokument/{document.id}/overlat", **body)


class TestExecuteWithGrant(GrantTest):
    def test_without_a_grant_nothing_changes(self):
        rabbit = self.rabbit("G1-2112")
        self.assertEqual(roles_for(self.helper, rabbit), frozenset())
        self.assertEqual(roles_for(self.owner, rabbit, None), roles_for(self.owner, rabbit))
        with self.assertRaises(IndividualRefused) as refused:
            execute(self.helper, rabbit.id, lambda ctx: [EditDescription({"name": "Stina"})])
        self.assertEqual(refused.exception.envelope["message"], "Forbidden")

    def test_a_helper_writes_through_an_item_they_hold_and_leaves_the_trace(self):
        item, document = self.taken(self.helper)
        self.assertEqual(
            roles_for(self.helper, self.rabbit("G1-2112"), inbox.InboxGrant(item, self.helper)), {Role.HANDLAGGARE}
        )
        self.certify(self.helper, item, document)
        self.assertEqual(self.rabbit("G1-2112").certificate, "P-77")
        command = db.IndividualCommand.get(db.IndividualCommand.command == "AssignPaperCertificate")
        trace = db.InboxOperation.get()
        self.assertEqual((command.actor_id, trace.operation_id), (self.helper.id, command.operation_id))
        self.assertEqual((trace.user_id, trace.document_id), (self.helper.id, document.id))

    def test_a_helper_without_a_taken_item_is_refused(self):
        item = self.item(0)
        document = item.documents.get()
        cases = {"untaken": lambda: None}

        def taken_by_manager():
            inbox.take(item, self.manager, over=False)

        def waiting():
            inbox.take(item, self.helper, over=True)
            item.state = "vantar_foralder"
            item.save()

        def pointing_elsewhere():
            item.state, item.ref_type, item.ref_id = "tagen", "arsrapport", 1
            item.save()

        cases.update(taken_by_manager=taken_by_manager, waiting=waiting, pointing_elsewhere=pointing_elsewhere)
        for name, arrange in cases.items():
            with self.subTest(name):
                arrange()
                with self.assertRaises(IndividualRefused):
                    self.certify(self.helper, self.reload(item), document)
                self.assertIsNone(self.rabbit("G1-2112").certificate)
        self.assertFalse(db.InboxOperation.select().exists())

    def test_a_helper_of_the_other_genebank_is_refused(self):
        item, document = self.taken(self.mellerud_helper)  # an item may hold rabbits of any herd
        with self.assertRaises(IndividualRefused):
            self.certify(self.mellerud_helper, item, document)
        with self.assertRaises(IndividualRefused):  # nor a grant made out to someone else
            self.certify(self.helper, item, document)

    def test_a_helper_cannot_correct_but_a_manager_can(self):
        # The buyer's yearly report came in first: the sale goes before the rabbit's latest row.
        rabbit = self.rabbit("G1-2111")
        ht_row(
            "ATTESTATION", herd=self.herds[1], individual=rabbit, herd_tracking_date=date.today() - timedelta(days=5)
        )
        earlier = (date.today() - timedelta(days=10)).isoformat()
        item, document = self.taken(self.helper)
        grant = inbox.InboxGrant(item, self.helper, document)
        with self.assertRaises(HerdTrackingConflict):  # date before the latest row: a correction
            with db.DB_PROXY.atomic():
                inbox.lock_item(item.id)
                execute(self.helper, rabbit.id, lambda ctx: [TransferIndividual("G2", earlier)], grant=grant)
        self.login("hjalp")
        resp = self.transfer(item, document, individual="G1-2111", herd="G2", date=earlier)
        self.assertEqual(resp.status_code, 400, resp.get_json())

        self.login("man")
        self.post(f"/{item.id}/ta-over")
        resp = self.transfer(item, document, individual="G1-2111", herd="G2", date=earlier)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        row = db.HerdTracking.get_by_id(resp.get_json()["herd_tracking_id"])
        self.assertEqual((row.kind, row.herd.herd, row.herd_tracking_date.isoformat()), ("TRANSFER", "G2", earlier))
        self.assertEqual(db.InboxOperation.get().operation_id, row.operation_id)

    def test_a_manager_writes_with_their_own_roles_and_the_grant_only_traces(self):
        item, document = self.taken(self.manager)
        self.certify(self.manager, item, document)
        self.assertEqual(db.InboxOperation.get().user_id, self.manager.id)


class TestSaveEndpoint(GrantTest):
    def test_a_new_rabbit_from_the_certificate(self):
        item, document = self.taken(self.helper)
        self.login("hjalp")
        resp = self.save(item, document, **NEW_RABBIT)
        self.assertEqual(resp.status_code, 201, resp.get_json())
        body = resp.get_json()
        self.assertEqual((body["individual"]["number"], body["individual"]["certificate"]), ("G1-2511", "SC-1"))
        self.assertTrue(body["breeding"]["created"])
        self.assertEqual((body["document"]["individual"], body["document"]["status"]), ("G1-2511", "sparad"))
        birth = db.HerdTracking.get(
            (db.HerdTracking.individual == body["individual"]["id"]) & (db.HerdTracking.kind == "BIRTH")
        )
        trace = db.InboxOperation.get()
        self.assertEqual(
            (trace.operation_id, trace.user_id, trace.document_id), (birth.operation_id, self.helper.id, document.id)
        )
        self.assertEqual(
            db.InboxEvent.select().where(db.InboxEvent.kind == "sparad").get().detail["individual"], "G1-2511"
        )
        self.assertEqual(self.save(item, document, **NEW_RABBIT).status_code, 409)  # saved once

    def test_the_registration_rules_still_apply(self):
        item, document = self.taken(self.helper)
        self.login("hjalp")
        for name, body, status in [
            ("no parents", {**NEW_RABBIT, "mother": None, "father": None}, 400),
            ("paper number conflict", {**NEW_RABBIT, "paper_number": "G1-2531"}, 409),
            ("no paper number", {**NEW_RABBIT, "paper_number": None}, 400),
            ("unknown action", {**NEW_RABBIT, "action": "radera"}, 400),
        ]:
            with self.subTest(name):
                resp = self.save(item, document, **body)
                self.assertEqual(resp.status_code, status, resp.get_json())
        self.assertFalse(db.Individual.select().where(db.Individual.number.startswith("G1-25")).exists())
        self.assertFalse(db.InboxOperation.select().exists())
        self.assertIsNone(self.reload(item).documents.get().individual_id)

    def test_refused_without_the_item_or_in_the_other_genebank(self):
        item = self.item(0)
        document = item.documents.get()
        self.login("hjalp")
        self.assertEqual(self.save(item, document, **NEW_RABBIT).status_code, 409)  # not taken
        self.login("mhjalp")
        self.post(f"/{item.id}/ta")
        self.assertEqual(self.save(item, document, **NEW_RABBIT).status_code, 403)  # a Gotland rabbit
        self.login("owner")
        self.assertEqual(self.save(item, document, **NEW_RABBIT).status_code, 403)  # not in the queue
        self.assertFalse(db.Individual.select().where(db.Individual.number == "G1-2511").exists())

    def test_an_item_pointing_elsewhere_cannot_be_saved(self):
        item, document = self.taken(self.manager)
        item.ref_type, item.ref_id = "arsrapport_forslag", 7
        item.save()
        self.login("man")
        self.assertEqual(self.save(item, document, **NEW_RABBIT).status_code, 409)
        resp = self.transfer(item, document, individual="G1-2111", herd="G2", date=date.today().isoformat())
        self.assertEqual(resp.status_code, 409)

    def test_the_paper_certificate_on_a_rabbit_that_exists(self):
        item, document = self.taken(self.helper)
        self.login("hjalp")
        body = {
            "action": "pappersintyg",
            "individual": "G1-2112",
            "paper_certificate": "P-9",
            "paper_number": "G1-2112",
        }
        resp = self.save(item, document, **body)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(self.rabbit("G1-2112").certificate, "P-9")
        item2, document2 = self.taken(self.helper)
        # Already certified: a manager's change.
        certified = {**body, "individual": "G1-2111", "paper_certificate": "P-10", "paper_number": "G1-2111"}
        self.assertEqual(self.save(item2, document2, **certified).status_code, 403)

    def test_a_save_that_changes_nothing_is_refused_and_links_nothing(self):
        held = self.rabbit("G1-2111")
        item, document = self.taken(self.manager)
        self.login("man")
        body = {
            "action": "pappersintyg",
            "individual": held.number,
            "paper_certificate": held.certificate,
            "paper_number": held.number,
        }
        resp = self.save(item, document, **body)
        self.assertEqual((resp.status_code, resp.get_json()["detail"][:13]), (409, "Ingen ändring"))
        self.assertIsNone(db.InboxDocument.get_by_id(document.id).individual_id)
        self.assertFalse(db.InboxEvent.select().where(db.InboxEvent.kind == "sparad").exists())
        self.assertFalse(db.InboxOperation.select().exists())

    def test_a_number_conflict_on_an_existing_rabbit_is_not_resolved_by_resolution(self):
        item, document = self.taken(self.helper)
        db.Breeding.update(litter_number=1).where(db.Breeding.id == self.rabbit("G1-2112").breeding_id).execute()
        self.login("hjalp")
        body = {
            "action": "pappersintyg",
            "individual": "G1-2112",
            "paper_certificate": "P-9",
            "paper_number": "G1-2113",
        }
        for resolution in (None, {"expected_number": "G1-2112", "choice": "use_stamboken_number"}):
            with self.subTest(resolution=resolution):
                resp = self.save(item, document, **body, **({"resolution": resolution} if resolution else {}))
                self.assertEqual(resp.status_code, 409, resp.get_json())
                self.assertEqual(
                    (resp.get_json()["title"], resp.get_json()["field"]), ("number_conflict", "paper_number")
                )
                self.assertIsNone(self.rabbit("G1-2112").certificate)

    def test_errors_name_the_request_field_they_concern(self):
        item, document = self.taken(self.helper)
        self.login("hjalp")
        for name, body, field in [
            ("no certificate number", {**NEW_RABBIT, "paper_certificate": ""}, "paper_certificate"),
            ("no paper number", {**NEW_RABBIT, "paper_number": "x"}, "paper_number"),
            ("unknown mother", {**NEW_RABBIT, "mother": "G1-9999"}, "mother"),
            ("no litter size", {**NEW_RABBIT, "litter_size": None}, "litter_size"),
            ("the paper disagrees", {**NEW_RABBIT, "paper_number": "G1-2521"}, "paper_number"),
        ]:
            with self.subTest(name):
                resp = self.save(item, document, **body)
                self.assertGreaterEqual(resp.status_code, 400)
                self.assertEqual(resp.get_json().get("field"), field, resp.get_json())
        resp = self.save(item, document, action="pappersintyg", individual="G1-9999", paper_certificate="P-1")
        self.assertEqual(resp.get_json().get("field"), "individual", resp.get_json())
        resp = self.save(item, document, action="okand")
        self.assertNotIn("field", resp.get_json())

    def test_the_trace_outlives_the_item(self):
        item, document = self.taken(self.helper)
        self.certify(self.helper, item, document)
        item.delete_instance()
        trace = db.InboxOperation.get()
        self.assertEqual((trace.document_id, trace.user_id), (None, self.helper.id))
        self.assertFalse(db.InboxDocument.select().exists())


class TestTransferEndpoint(GrantTest):
    def setUp(self):
        super().setUp()
        db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför genbanken")

    def test_a_sale_without_proof_marks_the_item(self):
        item, document = self.taken(self.helper)
        self.login("hjalp")
        resp = self.transfer(item, document, individual="G1-2111", herd="GX1", date=date.today().isoformat())
        self.assertEqual(resp.status_code, 200, resp.get_json())
        body = resp.get_json()
        self.assertTrue(body["item"]["missing_proof"])
        self.assertEqual(body["document"]["status"], "ny")  # the certificate itself is still to be registered
        row = db.HerdTracking.get_by_id(body["herd_tracking_id"])
        self.assertEqual((row.kind, row.herd.herd, row.signature_id), ("TRANSFER", "GX1", self.helper.id))
        self.assertEqual(db.InboxOperation.get().operation_id, row.operation_id)

    def test_a_proof_is_done_with_the_sale(self):
        item, document = self.taken(self.helper)
        self.login("hjalp")
        self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{document.id}", json={"doc_type": "bevis"})
        resp = self.transfer(item, document, individual="G1-2111", herd="G2", date=date.today().isoformat())
        self.assertEqual(resp.status_code, 200, resp.get_json())
        body = resp.get_json()
        self.assertFalse(body["item"]["missing_proof"])
        self.assertEqual((body["document"]["status"], body["item"]["state"]), ("klar", "klar"))
        self.assertEqual(db.InboxDocument.get_by_id(document.id).herd_tracking_id, body["herd_tracking_id"])

    def test_one_document_one_rabbit_and_one_sale(self):
        item, document = self.taken(self.helper)
        self.login("hjalp")
        today = date.today().isoformat()
        sold = self.transfer(item, document, individual="G1-2111", herd="GX1", date=today)
        self.assertEqual(sold.status_code, 200, sold.get_json())
        for name, resp in (
            ("another sale", self.transfer(item, document, individual="G1-2111", herd="G2", date=today)),
            ("another rabbit sold", self.transfer(item, document, individual="G1-2112", herd="GX1", date=today)),
            ("a new rabbit", self.save(item, document, **NEW_RABBIT)),
            (
                "another rabbit certified",
                self.save(
                    item,
                    document,
                    action="pappersintyg",
                    individual="G1-2112",
                    paper_certificate="P-5",
                    paper_number="G1-2112",
                ),
            ),
        ):
            with self.subTest(name):
                self.assertEqual(resp.status_code, 409, resp.get_json())
        self.assertEqual(db.InboxOperation.select().count(), 1)
        self.assertIsNone(self.rabbit("G1-2112").certificate)

        item, document = self.taken(self.helper)  # certified first: then only that rabbit is sold through it
        body = {
            "action": "pappersintyg",
            "individual": "G1-2112",
            "paper_certificate": "P-6",
            "paper_number": "G1-2112",
        }
        self.assertEqual(self.save(item, document, **body).status_code, 200)
        resp = self.transfer(item, document, individual="G1-2111", herd="GX1", date=today)
        self.assertEqual(resp.status_code, 409, resp.get_json())
        resp = self.transfer(item, document, individual="G1-2112", herd="GX1", date=today)
        self.assertEqual(resp.status_code, 200, resp.get_json())

    def test_a_proof_arriving_later_is_linked_to_the_sale_and_clears_the_missing_proof(self):
        item = self.item(0, documents=2)
        inbox.take(item, self.helper, over=False)
        certificate, proof = list(item.documents.order_by(db.InboxDocument.id))
        self.login("hjalp")
        today = date.today().isoformat()
        resp = self.transfer(item, certificate, individual="G1-2111", herd="G2", date=today)
        self.assertTrue(resp.get_json()["item"]["missing_proof"])
        sale = resp.get_json()["herd_tracking_id"]
        self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{proof.id}", json={"doc_type": "bevis"})
        transfers = db.HerdTracking.select().where(db.HerdTracking.kind == "TRANSFER").count()

        resp = self.transfer(item, proof, individual="G1-2111", herd="G2", date=today)

        self.assertEqual(resp.status_code, 200, resp.get_json())
        body = resp.get_json()
        self.assertEqual((body["herd_tracking_id"], body["item"]["missing_proof"]), (sale, False))
        self.assertEqual((body["document"]["status"], body["document"]["individual"]), ("klar", "G1-2111"))
        self.assertEqual(db.HerdTracking.select().where(db.HerdTracking.kind == "TRANSFER").count(), transfers)
        self.assertEqual(db.InboxOperation.select().count(), 1)  # linking writes nothing on the rabbit
        event = self.reload(item).events.where(db.InboxEvent.kind == "sparad").order_by(db.InboxEvent.id.desc()).get()
        self.assertEqual(event.detail["action"], "bevis")

    def test_a_refused_sale_names_its_field(self):
        item, document = self.taken(self.helper)
        self.login("hjalp")
        today = date.today().isoformat()
        future = (date.today() + timedelta(days=3)).isoformat()
        for name, body, field in [
            ("no date", {"individual": "G1-2111", "herd": "G2"}, "date"),
            ("unknown herd", {"individual": "G1-2111", "herd": "G99", "date": today}, "herd"),
            ("future", {"individual": "G1-2111", "herd": "G2", "date": future}, "date"),
            ("another genebank", {"individual": "G1-2111", "herd": "M3", "date": today}, "herd"),
            ("unknown rabbit", {"individual": "G1-9999", "herd": "G2", "date": today}, "individual"),
        ]:
            with self.subTest(name):
                self.assertEqual(self.transfer(item, document, **body).get_json().get("field"), field)

    def test_the_sale_rules_still_apply(self):
        item, document = self.taken(self.helper)
        self.login("hjalp")
        future = (date.today() + timedelta(days=3)).isoformat()
        for name, body, status in [
            ("future", {"individual": "G1-2111", "herd": "G2", "date": future}, 400),
            ("uncertified into a herd", {"individual": "G1-2112", "herd": "G2", "date": date.today().isoformat()}, 400),
            ("another genebank", {"individual": "G1-2111", "herd": "M3", "date": date.today().isoformat()}, 400),
            ("unknown herd", {"individual": "G1-2111", "herd": "G99", "date": date.today().isoformat()}, 400),
            ("unknown rabbit", {"individual": "G1-9999", "herd": "G2", "date": date.today().isoformat()}, 404),
        ]:
            with self.subTest(name):
                self.assertEqual(self.transfer(item, document, **body).status_code, status)
        self.assertFalse(
            db.HerdTracking.select()
            .where(
                db.HerdTracking.kind == "TRANSFER",
                db.HerdTracking.herd_tracking_date >= date.today() - timedelta(days=1),
            )
            .exists()
        )


class TestWaitingForAParent(GrantTest):
    def waiting(self, number="G1-2431"):
        item, document = self.taken(self.helper)
        inbox.update_document(item, document, self.helper, {"waiting_for": [number]})
        inbox.change_state(item, self.helper, "vantar_foralder")
        return item

    def test_a_parent_registered_anywhere_wakes_the_item(self):
        item = self.waiting()
        db.Individual.create(number="G1-2431", origin_herd=self.herds[0], breeding=self.breeding[0])
        item = self.reload(item)
        self.assertEqual(item.state, "tagen")
        self.assertIsNone(item.documents.get().waiting_for)
        notice = db.Notice.get(db.Notice.kind == "foralder_inlagd")
        self.assertEqual((notice.user_id, notice.item_id), (self.helper.id, item.id))
        event = db.InboxEvent.get(db.InboxEvent.kind == "foralder_inlagd")
        self.assertEqual((event.user_id, event.detail), (None, {"individual": "G1-2431"}))

    def test_through_the_registration_endpoint_and_rolled_back_with_it(self):
        item = self.waiting("G1-2511")
        with self.assertRaises(RuntimeError):
            with db.DB_PROXY.atomic():
                db.Individual.create(number="G1-2511", origin_herd=self.herds[0], breeding=self.breeding[0])
                raise RuntimeError("rolled back")
        self.assertEqual(self.reload(item).state, "vantar_foralder")
        self.login("owner")
        body = {k: v for k, v in NEW_RABBIT.items() if k != "action"}
        resp = self.client.post("/api/v2/individual", json={**body, "certificate_type": "paper"})
        self.assertEqual(resp.status_code, 201, resp.get_json())
        self.assertEqual(self.reload(item).state, "tagen")

    def test_an_item_waiting_for_two_parents_wakes_with_the_second(self):
        item, document = self.taken(self.helper)
        inbox.update_document(item, document, self.helper, {"waiting_for": ["G1-2431", "G1-2432"]})
        inbox.change_state(item, self.helper, "vantar_foralder")
        db.Individual.create(number="G1-2431", origin_herd=self.herds[0], breeding=self.breeding[0])
        self.assertEqual(
            (self.reload(item).state, db.InboxDocument.get_by_id(document.id).waiting_for),
            ("vantar_foralder", ["G1-2432"]),
        )
        db.Individual.create(number="G1-2432", origin_herd=self.herds[0], breeding=self.breeding[0])
        self.assertEqual(self.reload(item).state, "tagen")

    def test_the_legacy_form_wakes_it_too(self):
        item = self.waiting("G1-1922")
        form = {
            "herd": "G1",
            "origin_herd": {"herd": "G1"},
            "number": "G1-1922",
            "breeding": self.breeding[0].id,
            "birth_date": (date.today() - timedelta(days=30)).isoformat(),
        }
        self.assertEqual(da.add_individual(form, self.admin.uuid)["status"], "success")
        self.assertEqual(self.reload(item).state, "tagen")

    def register(self, number):
        return db.Individual.create(number=number, origin_herd=self.herds[0], breeding=self.breeding[0])

    def test_a_parent_registered_clears_it_on_every_open_item_whatever_its_state(self):
        item, document = self.taken(self.helper)
        inbox.update_document(item, document, self.helper, {"waiting_for": ["G1-2431"]})  # still tagen
        self.register("G1-2431")
        self.assertEqual(
            (self.reload(item).state, db.InboxDocument.get_by_id(document.id).waiting_for), ("tagen", None)
        )
        notice = db.Notice.get(db.Notice.kind == "foralder_inlagd")
        self.assertEqual((notice.user_id, notice.item_id), (self.helper.id, item.id))

    def test_waiting_for_a_rabbit_that_exists_is_refused_and_the_number_cleared(self):
        item, document = self.taken(self.helper)
        db.InboxDocument.update(waiting_for=["G1-2112"]).where(db.InboxDocument.id == document.id).execute()
        self.login("hjalp")
        resp = self.post(f"/{item.id}/lage", state="vantar_foralder")
        self.assertEqual(resp.status_code, 409, resp.get_json())
        self.assertIn("G1-2112 finns redan", resp.get_json()["detail"])
        self.assertIsNone(db.InboxDocument.get_by_id(document.id).waiting_for)  # cleared, and committed
        self.assertEqual(self.reload(item).state, "tagen")
        db.InboxDocument.update(waiting_for=["G1-2112", "G1-2433"]).where(db.InboxDocument.id == document.id).execute()
        resp = self.post(f"/{item.id}/lage", state="vantar_foralder")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(db.InboxDocument.get_by_id(document.id).waiting_for, ["G1-2433"])

    def test_a_locked_item_is_skipped_never_waited_for_and_woken_by_the_sweep(self):
        """The reverse lock order (a save wakes items another transaction holds) must never wait: no deadlock."""
        item = self.waiting()
        held, release = threading.Event(), threading.Event()

        def hold():  # as assigning a herd's items does, in another transaction
            with db.DB_PROXY.atomic():
                db.InboxItem.select().where(db.InboxItem.id == item.id).for_update().first()
                held.set()
                release.wait(10)
            db.DB_PROXY.close()

        holder = threading.Thread(target=hold)
        holder.start()
        self.assertTrue(held.wait(10))
        try:
            with db.DB_PROXY.atomic():
                db.DB_PROXY.execute_sql("SET LOCAL lock_timeout = '2s'")  # waiting would fail here
                self.register("G1-2431")
        finally:
            release.set()
            holder.join()
        self.assertEqual(self.reload(item).state, "vantar_foralder")  # skipped
        self.assertEqual(inbox.wake_waiting(), 1)
        self.assertEqual(self.reload(item).state, "tagen")
        self.assertIsNone(self.reload(item).documents.get().waiting_for)
        self.assertEqual(inbox.wake_waiting(), 0)

    def test_the_sweep_job_closes_its_connection(self):
        with mock.patch.object(herdbook.genetics.ps, "_close_db_connection") as close:
            herdbook._wake_waiting_items()
        close.assert_called_once()

    def test_the_insert_and_the_wake_up_are_one_transaction(self):
        self.waiting()
        with mock.patch.object(inbox, "parent_registered", side_effect=RuntimeError("the wake-up failed")):
            with self.assertRaises(RuntimeError):
                db.Individual.create(number="G1-2431", origin_herd=self.herds[0], breeding=self.breeding[0])
        self.assertFalse(db.Individual.select().where(db.Individual.number == "G1-2431").exists())
