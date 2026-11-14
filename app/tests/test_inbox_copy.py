"""The copy on the rabbit: rotation and black rectangles from the original, and who is served which file.

isort:skip_file
"""

import datetime
import io
import os

import utils.database as db  # noqa: E402
from PIL import Image  # noqa: E402

from tests.inbox_fixtures import InboxTest, encoded  # noqa: E402

RED, BLUE = (220, 30, 30), (30, 30, 220)


def red_over_blue():
    """Asymmetric on purpose: red above, blue below, so a wrong rotation shows."""
    image = Image.new("RGB", (1200, 1600), RED)
    image.paste(BLUE, (0, 800, 1200, 1600))
    return image


def close(pixel, colour, slack=40):
    return all(abs(a - b) <= slack for a, b in zip(pixel, colour, strict=True))


class CopyTest(InboxTest):
    def saved_document(self):
        """An uploaded certificate, taken by the helper and saved as G1-2112's paper certificate."""
        self.login("owner")
        resp = self.upload(("intyg.jpg", encoded(red_over_blue())))
        item = db.InboxItem.get_by_id(resp.get_json()["item"]["id"])
        document = item.documents.get()
        self.login("hjalp")
        self.post(f"/{item.id}/ta")
        body = {
            "action": "pappersintyg",
            "individual": "G1-2112",
            "paper_certificate": "P-1",
            "paper_number": "G1-2112",
        }
        resp = self.post(f"/{item.id}/dokument/{document.id}/spara", **body)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        return item, document

    def mask(self, item, document, rotation=0, **body):
        return self.post(f"/{item.id}/dokument/{document.id}/maskning", rotation=rotation, **body)

    def copy(self, document):
        document = db.InboxDocument.get_by_id(document.id)
        with Image.open(os.path.join(self.folder, document.public_path)) as image:
            return image.convert("RGB")


class TestCopy(CopyTest):
    def test_the_copy_lacks_what_the_rectangles_cover_and_the_original_stays(self):
        item, document = self.saved_document()
        original = open(self.stored(document), "rb").read()
        resp = self.mask(item, document, rotation=90, mask_rects=[{"x": 0, "y": 0, "w": 0.5, "h": 1}])
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json()["document"]["status"], "klar")
        self.assertEqual(resp.get_json()["item"]["state"], "klar")

        copy = self.copy(document)
        self.assertEqual(copy.size, (1600, 1200))  # turned clockwise: red, the top, is now on the right
        self.assertTrue(close(copy.getpixel((1200, 600)), RED))
        self.assertTrue(close(copy.getpixel((400, 600)), (0, 0, 0)))  # blue, the bottom, covered
        self.assertFalse(
            any(close(copy.getpixel((x, y)), BLUE) for x in range(0, 1600, 50) for y in range(0, 1200, 50))
        )
        self.assertTrue(db.InboxDocument.get_by_id(document.id).public_path.startswith("inkorg/kopia/"))
        self.assertEqual(open(self.stored(document), "rb").read(), original)
        with Image.open(os.path.join(self.folder, db.InboxDocument.get_by_id(document.id).public_path)) as image:
            self.assertEqual(len(image.getexif()), 0)

    def test_the_copy_is_made_again_when_the_rectangles_change(self):
        item, document = self.saved_document()
        self.mask(item, document, mask_rects=[{"x": 0, "y": 0.5, "w": 1, "h": 0.5}])
        self.assertTrue(close(self.copy(document).getpixel((600, 1200)), (0, 0, 0)))
        self.login("man")  # the item is closed: a manager makes it again, without reopening it
        resp = self.mask(item, document, mask_rects=[{"x": 0, "y": 0, "w": 1, "h": 0.5}])
        self.assertEqual(resp.status_code, 200, resp.get_json())
        copy = self.copy(document)
        self.assertTrue(close(copy.getpixel((600, 400)), (0, 0, 0)))
        self.assertTrue(close(copy.getpixel((600, 1200)), BLUE))

    def test_masking_needs_a_saved_certificate_and_a_confirmation(self):
        self.login("owner")
        item = db.InboxItem.get_by_id(self.upload().get_json()["item"]["id"])
        document = item.documents.get()
        self.login("hjalp")
        self.post(f"/{item.id}/ta")
        nothing = self.mask(item, document, mask_rects=[], no_personal_data=True)
        self.assertEqual(nothing.status_code, 409)  # nothing saved yet
        item, document = self.saved_document()
        rects = [{"x": 0, "y": 0.5, "w": 1, "h": 0.5}]
        for body in (
            {},  # neither rotation nor rectangles
            {"mask_rects": None},
            {"rotation": None, "mask_rects": rects},
            {"rotation": 45, "mask_rects": rects},
            {"rotation": False, "mask_rects": rects},
            {"mask_rects": []},  # an empty list says nothing without the explicit confirmation
            {"mask_rects": [], "no_personal_data": "true"},
        ):
            with self.subTest(body=body):
                resp = self.post(f"/{item.id}/dokument/{document.id}/maskning", **body)
                self.assertEqual(resp.status_code, 400, resp.get_json())
        self.assertIsNone(db.InboxDocument.get_by_id(document.id).public_path)
        self.assertEqual(self.mask(item, document, mask_rects=[], no_personal_data=True).status_code, 200)

    def test_who_is_served_the_original_and_the_copy(self):
        item, document = self.saved_document()
        self.mask(item, document, mask_rects=[{"x": 0, "y": 0.5, "w": 1, "h": 0.5}])
        original = f"/api/v2/inkorg/{item.id}/dokument/{document.id}/original"
        copy = "/api/v2/individual/G1-2112/paper-certificate"
        expected = {
            # username: (original, copy)
            "owner": (403, 200),  # the rabbit's owner sees its certificate, never the original
            "spec": (403, 403),  # a viewer of the genebank
            "hjalp": (200, 403),  # works in the queue, but is not someone who sees the certificate
            "man": (200, 200),
            "admin": (200, 200),
        }
        for username, (original_status, copy_status) in expected.items():
            with self.subTest(username):
                self.login(username)
                for url, status in ((original, original_status), (copy, copy_status)):
                    resp = self.client.get(url)
                    self.assertEqual(resp.status_code, status, url)
                    if status == 200:
                        self.assertEqual(resp.headers["Cache-Control"], "no-store, private")
                        Image.open(io.BytesIO(resp.data)).verify()
        self.client.get("/api/logout")
        self.assertEqual(self.client.get(original).status_code, 401)
        self.assertEqual(self.client.get(copy).status_code, 401)
        views = db.InboxEvent.select().where(db.InboxEvent.kind == "original_visat")
        self.assertEqual(sorted(e.user_id for e in views), sorted([self.helper.id, self.manager.id, self.admin.id]))
        self.login("man")
        self.assertEqual(self.client.get("/api/v2/individual/G1-2111/paper-certificate").status_code, 404)

    def test_files_are_never_under_the_public_upload_folder(self):
        item, document = self.saved_document()
        self.mask(item, document, mask_rects=[], no_personal_data=True)
        document = db.InboxDocument.get_by_id(document.id)
        for relative in (document.original_path, document.public_path):
            self.assertTrue(os.path.exists(os.path.join(self.folder, relative)))
            self.assertFalse(os.path.exists(os.path.join(os.getenv("UPLOAD_FOLDER", "/app/uppladdningar"), relative)))


class TestCopyIsFixed(CopyTest):
    """Once the copy is made, nothing but …/maskning changes what it shows, and it shows exactly the pair it got."""

    def patch(self, item, document, **body):
        return self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{document.id}", json=body)

    def test_patch_refuses_the_rotation_the_rectangles_and_the_type_once_the_copy_is_made(self):
        item, document = self.saved_document()
        self.login("man")
        self.post(f"/{item.id}/ta-over")
        resp = self.mask(item, document, mask_rects=[{"x": 0, "y": 0.5, "w": 1, "h": 0.5}])
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.post(f"/{item.id}/lage", state="tagen")  # reopened: its handler again
        before = open(os.path.join(self.folder, db.InboxDocument.get_by_id(document.id).public_path), "rb").read()
        for body in ({"rotation": 90}, {"mask_rects": None}, {"mask_rects": []}, {"doc_type": "bevis"}):
            with self.subTest(body=body):
                self.assertEqual(self.patch(item, document, **body).status_code, 409)
        stored = db.InboxDocument.get_by_id(document.id)
        self.assertEqual((stored.rotation, stored.mask_rects), (0, [{"x": 0, "y": 0.5, "w": 1, "h": 0.5}]))
        self.assertEqual(open(os.path.join(self.folder, stored.public_path), "rb").read(), before)
        self.assertTrue(close(self.copy(document).getpixel((600, 1200)), (0, 0, 0)))  # still masked

    def test_the_copy_is_made_from_the_pair_it_was_given(self):
        item, document = self.saved_document()
        self.patch(item, document, rotation=90)  # stored, but the masking names its own
        resp = self.mask(item, document, rotation=0, mask_rects=[{"x": 0, "y": 0.5, "w": 1, "h": 0.5}])
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json()["document"]["rotation"], 0)
        copy = self.copy(document)
        self.assertEqual(copy.size, (1200, 1600))
        self.assertTrue(close(copy.getpixel((600, 1200)), (0, 0, 0)))
        self.assertTrue(close(copy.getpixel((600, 400)), RED))

    def test_a_finished_proof_cannot_become_a_certificate(self):
        db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför genbanken")
        self.login("owner")
        item = db.InboxItem.get_by_id(self.upload().get_json()["item"]["id"])
        document = item.documents.get()
        self.login("hjalp")
        self.post(f"/{item.id}/ta")
        self.patch(item, document, doc_type="bevis")
        today = datetime.date.today().isoformat()
        resp = self.post(f"/{item.id}/dokument/{document.id}/overlat", individual="G1-2111", herd="GX1", date=today)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.login("man")
        self.post(f"/{item.id}/lage", state="tagen")
        self.assertEqual(self.patch(item, document, doc_type="intyg").status_code, 409)
        self.assertEqual(self.mask(item, document, mask_rects=[], no_personal_data=True).status_code, 409)
        self.assertIsNone(db.InboxDocument.get_by_id(document.id).public_path)

    def test_who_may_make_the_copy_again(self):
        item, document = self.saved_document()
        rects = [{"x": 0, "y": 0.5, "w": 1, "h": 0.5}]
        self.assertEqual(self.mask(item, document, mask_rects=rects).status_code, 200)  # the helper, its handler
        self.assertEqual(self.reload(item).state, "klar")
        self.assertEqual(self.mask(item, document, mask_rects=rects).status_code, 409)  # closed: no longer hers
        self.login("mhjalp")
        self.assertEqual(self.mask(item, document, mask_rects=rects).status_code, 409)
        for username in ("man", "admin"):
            with self.subTest(username):
                self.login(username)
                resp = self.mask(item, document, rotation=180, mask_rects=[{"x": 0, "y": 0, "w": 1, "h": 0.5}])
                self.assertEqual(resp.status_code, 200, resp.get_json())
                copy = self.copy(document)
                self.assertTrue(close(copy.getpixel((600, 400)), (0, 0, 0)))  # turned: blue on top, covered
                self.assertTrue(close(copy.getpixel((600, 1200)), RED))
        events = self.reload(item).events.where(db.InboxEvent.kind == "kopia").order_by(db.InboxEvent.id)
        self.assertEqual(
            [(e.user_id, e.detail["rotation"]) for e in events],
            [(self.helper.id, 0), (self.manager.id, 180), (self.admin.id, 180)],
        )
        self.assertEqual(self.reload(item).state, "klar")
