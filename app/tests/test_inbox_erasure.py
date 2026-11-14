"""Erasure in the intake queue: who a document shows, erase_person_from_inbox, anonymize_person, …/radera-original.

isort:skip_file
"""

import os
from datetime import date

import utils.database as db  # noqa: E402
import utils.inbox as inbox  # noqa: E402
import utils.inbox_purge as purge  # noqa: E402
import utils.matrikel as matrikel  # noqa: E402

from tests.test_inbox_purge import PHONE, PurgeTest  # noqa: E402


class ErasureTest(PurgeTest):
    def setUp(self):
        super().setUp()
        self.seller = self.holder(self.herds[0], "Saljare")
        self.buyer = self.holder(self.herds[1], "Kopare")

    def holder(self, herd, first_name):
        """The herd's holder in the member register (synthetic)."""
        membership = db.Membership.create(member_number=900 + herd.id)
        db.Herd.update(membership=membership).where(db.Herd.id == herd.id).execute()
        return db.Member.create(
            first_name=first_name,
            last_name="Test",
            email=f"{first_name.lower()}@example.org",
            role="huvudmedlem",
            membership=membership,
        )

    def uploaded(self):
        """The owner's upload of one certificate, with PHONE in its message and in a question, taken by the helper."""
        self.login("owner")
        resp = self.upload(message=f"Ring mig på {PHONE}")
        item = db.InboxItem.get_by_id(resp.get_json()["item"]["id"])
        inbox.log_event(item, self.manager, "fraga", text=f"Står det {PHONE}?")
        self.login("hjalp")
        self.post(f"/{item.id}/ta")
        return item, item.documents.get()

    def certified(self):
        """The upload saved as G1-2112's paper certificate and masked: the copy is on the rabbit."""
        item, document = self.uploaded()
        body = {
            "action": "pappersintyg",
            "individual": "G1-2112",
            "paper_certificate": "P-1",
            "paper_number": "G1-2112",
        }
        resp = self.post(f"/{item.id}/dokument/{document.id}/spara", **body)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        resp = self.post(
            f"/{item.id}/dokument/{document.id}/maskning", mask_rects=[{"x": 0, "y": 0.5, "w": 1, "h": 0.5}]
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        return item, db.InboxDocument.get_by_id(document.id)

    def proof(self, herd="G2"):
        """The upload as a proof of G1-2111's sale to `herd`."""
        item, document = self.uploaded()
        self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{document.id}", json={"doc_type": "bevis"})
        resp = self.post(
            f"/{item.id}/dokument/{document.id}/overlat", individual="G1-2111", herd=herd, date=date.today().isoformat()
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        return item, db.InboxDocument.get_by_id(document.id)

    def certificate_served(self):
        self.login("man")
        resp = self.client.get("/api/v2/individual/G1-2112/paper-certificate")
        return resp.status_code


class TestWhoADocumentShows(ErasureTest):
    def test_a_saved_certificate_shows_the_holder_of_the_rabbits_herd(self):
        _, document = self.certified()
        self.assertEqual((document.seller_member_id, document.buyer_member_id), (self.seller.id, None))

    def test_a_sale_shows_its_seller_and_a_members_buyer(self):
        _, document = self.proof()
        self.assertEqual((document.seller_member_id, document.buyer_member_id), (self.seller.id, self.buyer.id))

    def test_a_buyer_outside_the_association_is_no_member(self):
        db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför genbanken")
        _, document = self.proof("GX1")
        self.assertEqual((document.seller_member_id, document.buyer_member_id), (self.seller.id, None))


class TestErasePerson(ErasureTest):
    def test_the_original_is_replaced_by_the_copy_and_the_text_goes(self):
        item, document = self.certified()
        other, other_document = self.uploaded()  # shows nobody recorded

        with db.DB_PROXY.atomic():
            paths = purge.erase_person_from_inbox(self.seller)
        self.assertTrue(self.exists(document.original_path))  # the file waits for the commit
        purge.remove_originals(paths)

        erased = db.InboxDocument.get_by_id(document.id)
        self.assertIsNone(erased.original_path)
        self.assertFalse(self.exists(document.original_path))
        self.assertEqual(erased.public_path, document.public_path)
        self.assertTrue(self.exists(document.public_path))  # only the masked copy is left
        self.assertEqual(self.certificate_served(), 200)
        self.assertNotIn(PHONE, self.text(item))
        self.assertIn(PHONE, self.text(other))
        self.assertTrue(self.exists(other_document.original_path))

        with db.DB_PROXY.atomic():
            self.assertEqual(purge.erase_person_from_inbox(self.seller), [])

    def test_without_a_copy_the_original_is_deleted(self):
        item, document = self.proof()
        with db.DB_PROXY.atomic():
            paths = purge.erase_person_from_inbox(self.buyer)
        purge.remove_originals(paths)
        self.assertIsNone(db.InboxDocument.get_by_id(document.id).original_path)
        self.assertFalse(self.exists(document.original_path))
        self.assertNotIn(PHONE, self.text(item))
        self.assertEqual(db.InboxDocument.get_by_id(document.id).herd_tracking_id, document.herd_tracking_id)

    def test_anonymizing_the_member_erases_it(self):
        item, document = self.certified()
        matrikel.anonymize_person(self.seller, self.admin)
        self.assertIsNone(db.InboxDocument.get_by_id(document.id).original_path)
        self.assertFalse(self.exists(document.original_path))
        self.assertTrue(self.exists(document.public_path))
        self.assertNotIn(PHONE, self.text(item))


class TestEraseEndpoint(ErasureTest):
    def erase(self, item, document):
        return self.post(f"/{item.id}/dokument/{document.id}/radera-original")

    def test_a_manager_erases_one_original_on_request(self):
        item, document = self.certified()
        self.login("man")
        resp = self.erase(item, document)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        body = resp.get_json()
        self.assertEqual((body["document"]["has_original"], body["document"]["has_copy"]), (False, True))
        self.assertFalse(body["item"]["has_message"])
        self.assertFalse(self.exists(document.original_path))
        self.assertTrue(self.exists(document.public_path))
        self.assertNotIn(PHONE, self.text(item))
        (event,) = self.reload(item).events.where(db.InboxEvent.kind == "original_raderat")
        self.assertEqual((event.user_id, event.detail), (self.manager.id, {"document": document.id}))

        resp = self.client.get(f"/api/v2/inkorg/{item.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(PHONE, resp.get_data(as_text=True))
        resp = self.client.get(f"/api/v2/inkorg/{item.id}/dokument/{document.id}/original")
        self.assertEqual((resp.status_code, resp.get_json()["detail"]), (404, "Originalet är raderat."))
        self.assertEqual(self.certificate_served(), 200)
        self.login("man")
        self.assertEqual(self.erase(item, document).status_code, 200)  # again: nothing left to do

    def test_refused_to_a_helper_and_to_someone_outside_the_queue(self):
        item, document = self.certified()
        for username in ("hjalp", "owner"):
            with self.subTest(username):
                self.login(username)
                self.assertEqual(self.erase(item, document).status_code, 403)
        self.assertTrue(os.path.exists(os.path.join(self.folder, document.original_path)))
        self.assertIn(PHONE, self.text(item))
