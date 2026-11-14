"""The copy on the rabbit: rotation and black rectangles from the original, and who is served which file.

isort:skip_file
"""

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


class TestCopy(InboxTest):
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

    def mask(self, item, document, **body):
        return self.post(f"/{item.id}/dokument/{document.id}/maskning", **body)

    def copy(self, document):
        document = db.InboxDocument.get_by_id(document.id)
        with Image.open(os.path.join(self.folder, document.public_path)) as image:
            return image.convert("RGB")

    def test_the_copy_lacks_what_the_rectangles_cover_and_the_original_stays(self):
        item, document = self.saved_document()
        original = open(self.stored(document), "rb").read()
        self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{document.id}", json={"rotation": 90})
        resp = self.mask(item, document, mask_rects=[{"x": 0, "y": 0, "w": 0.5, "h": 1}])
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
        self.login("man")  # the item is closed: a manager reopens it
        self.post(f"/{item.id}/lage", state="tagen")
        resp = self.client.patch(
            f"/api/v2/inkorg/{item.id}/dokument/{document.id}",
            json={"mask_rects": [{"x": 0, "y": 0, "w": 1, "h": 0.5}]},
        )
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
        self.assertEqual(self.mask(item, document, mask_rects=[]).status_code, 409)  # nothing saved yet
        item, document = self.saved_document()
        self.assertEqual(self.mask(item, document).status_code, 400)  # neither stored nor sent
        self.assertEqual(self.mask(item, document, mask_rects=[]).status_code, 200)  # nothing to cover

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
        self.mask(item, document, mask_rects=[])
        document = db.InboxDocument.get_by_id(document.id)
        for relative in (document.original_path, document.public_path):
            self.assertTrue(os.path.exists(os.path.join(self.folder, relative)))
            self.assertFalse(os.path.exists(os.path.join(os.getenv("UPLOAD_FOLDER", "/app/uppladdningar"), relative)))
