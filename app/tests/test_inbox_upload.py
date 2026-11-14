"""POST /api/v2/inkorg/upload: validation, conversion to JPEG without metadata, the quality check, the item.

isort:skip_file
"""

import io
import os
from unittest import mock

import utils.database as db  # noqa: E402
import utils.inbox as inbox  # noqa: E402
from herdbook import limiter  # noqa: E402
from PIL import Image  # noqa: E402

from tests.inbox_fixtures import InboxTest, blurry, encoded, pdf, photo  # noqa: E402


class TestUpload(InboxTest):
    def documents(self, item_id):
        return list(db.InboxDocument.select().where(db.InboxDocument.item == item_id).order_by(db.InboxDocument.id))

    def test_owner_upload_makes_an_item_and_notifies_the_genebank(self):
        self.login("owner")
        files = [
            ("a.jpg", encoded(photo())),
            ("b.png", encoded(photo(seed=2), "PNG")),
            ("c.webp", encoded(photo(), "WEBP")),
        ]
        resp = self.upload(*files, message="Tre intyg från i våras")
        self.assertEqual(resp.status_code, 201, resp.get_json())
        body = resp.get_json()
        item = db.InboxItem.get_by_id(body["item"]["id"])
        self.assertEqual((item.kind, item.state, item.herd_id, item.genebank_id), ("upload", "ny", self.herds[0].id, 1))
        self.assertEqual((item.sender_user_id, item.message), (self.owner.id, "Tre intyg från i våras"))
        self.assertEqual(body["item"]["documents"], 3)
        documents = self.documents(item.id)
        self.assertEqual([d["id"] for d in body["documents"]], [d.id for d in documents])
        for document in documents:
            self.assertTrue(document.original_path.startswith("inkorg/original/"))
            with open(self.stored(document), "rb") as stored:
                self.assertEqual(stored.read(3), b"\xff\xd8\xff")
            self.assertIsNone(document.public_path)
        self.assertEqual([e.kind for e in db.InboxEvent.select().where(db.InboxEvent.item == item)], ["inkommen"])
        notified = sorted(n.user_id for n in db.Notice.select().where(db.Notice.kind == "ny_post"))
        self.assertEqual(notified, sorted([self.manager.id, self.helper.id]))  # not Mellerud's helper, not admin

    def test_exif_and_gps_are_gone_and_the_photo_is_upright(self):
        exif = Image.Exif()
        exif[0x0110] = "SecretCam"  # camera model
        exif[0x0112] = 6  # orientation: turn 90 degrees
        exif.get_ifd(0x8825)[2] = (57.0, 30.0, 0.0)  # GPS latitude
        self.login("owner")
        resp = self.upload(("p.jpg", encoded(photo((1600, 1200)), exif=exif)))
        self.assertEqual(resp.status_code, 201, resp.get_json())
        (document,) = self.documents(resp.get_json()["item"]["id"])
        with open(self.stored(document), "rb") as stored:
            data = stored.read()
        self.assertNotIn(b"Exif", data)
        self.assertNotIn(b"SecretCam", data)
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(len(image.getexif()), 0)
            self.assertEqual(image.size, (1200, 1600))

    def test_heic_and_pdf_become_jpeg_page_by_page(self):
        self.login("owner")
        resp = self.upload(("iphone.heic", encoded(photo(), "HEIF")), ("skanning.pdf", pdf(photo(), photo(seed=3))))
        self.assertEqual(resp.status_code, 201, resp.get_json())
        body = resp.get_json()
        self.assertEqual([(d["file"], d["page"]) for d in body["documents"]], [(0, None), (1, 1), (1, 2)])
        for document in self.documents(body["item"]["id"]):
            with Image.open(self.stored(document)) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertGreaterEqual(min(image.size), 1000)

    def test_a_blurry_or_small_photo_gets_a_warning(self):
        self.login("owner")
        files = [
            ("skarp.jpg", encoded(photo())),
            ("suddig.jpg", encoded(blurry())),
            ("liten.jpg", encoded(photo((600, 800)))),
        ]
        resp = self.upload(*files, accept_warnings="1")
        self.assertEqual(resp.status_code, 201, resp.get_json())
        self.assertEqual([d["warnings"] for d in resp.get_json()["documents"]], [[], ["suddig"], ["lag_upplosning"]])
        sharp, soft, _ = self.documents(resp.get_json()["item"]["id"])
        self.assertGreater(sharp.quality["sharpness"], inbox.MIN_SHARPNESS)
        self.assertLess(soft.quality["sharpness"], inbox.MIN_SHARPNESS)

    def test_a_flagged_upload_stores_nothing_until_the_warnings_are_accepted(self):
        self.login("owner")
        files = [("skarp.jpg", encoded(photo())), ("suddig.pdf", pdf(photo(), blurry()))]
        resp = self.upload(*files)
        self.assertEqual((resp.status_code, resp.mimetype), (409, "application/problem+json"))
        self.assertEqual(
            [(d["file"], d["page"], d["warnings"]) for d in resp.get_json()["warnings"]],
            [(0, None, []), (1, 1, []), (1, 2, ["suddig"])],
        )
        self.assertTrue(all("quality" in d and "id" not in d for d in resp.get_json()["warnings"]))
        self.assertFalse(db.InboxItem.select().exists())
        self.assertEqual(os.listdir(self.folder), [])
        resp = self.upload(*files, accept_warnings="1")
        self.assertEqual(resp.status_code, 201, resp.get_json())
        self.assertEqual([d["warnings"] for d in resp.get_json()["documents"]], [[], [], ["suddig"]])
        self.assertEqual(self.upload(dry_run="1").status_code, 201)  # dry_run is gone: an unflagged upload is stored

    def test_an_image_of_a_pixel_or_two_is_measured(self):
        for size in ((1, 1), (2, 900), (900, 2)):
            with self.subTest(size=size):
                quality = inbox.measure(Image.new("RGB", size, (200, 200, 200)))
                self.assertEqual(quality["short_side"], min(size))
        self.login("owner")
        resp = self.upload(("pixel.png", encoded(Image.new("RGB", (1, 1)), "PNG")), accept_warnings="1")
        self.assertNotEqual(resp.status_code, 500)
        self.assertIn("lag_upplosning", resp.get_json()["documents"][0]["warnings"])

    def test_one_decoded_image_at_a_time(self):
        """Ten large images in one request: each is closed before the next is decoded, a PDF page by page too."""
        live, peak = set(), []
        convert, close = Image.Image.convert, Image.Image.close

        def counting_convert(image, mode=None, *args, **kwargs):
            result = convert(image, mode, *args, **kwargs)
            if mode == "RGB":  # the decoded image the pipeline works on
                live.add(id(result))
                peak.append(len(live))
            return result

        def counting_close(image):
            live.discard(id(image))
            return close(image)

        large = [(f"{n}.jpg", encoded(photo((2000, 2600), seed=n), quality=20)) for n in range(10)]
        pages = [("tio.pdf", pdf(*[photo(seed=n) for n in range(10)]))]
        self.login("owner")
        for name, files in (("ten photos", large), ("ten pages", pages)):
            with (
                self.subTest(name),
                mock.patch.object(Image.Image, "convert", counting_convert),
                mock.patch.object(Image.Image, "close", counting_close),
            ):
                live.clear()
                peak.clear()
                resp = self.upload(*files)
                self.assertEqual(resp.status_code, 201, resp.get_json())
                self.assertEqual((len(peak), max(peak)), (10, 1))

    def test_refusals(self):
        self.login("owner")
        too_many_pixels = encoded(Image.new("1", (8000, 6000)), "PNG")
        cases = [
            ("no herd", self.upload(herd=""), 400),
            ("unknown herd", self.upload(herd="G999"), 400),
            ("gif", self.upload(("x.gif", encoded(photo((100, 100)), "GIF"))), 415),
            ("text named jpg", self.upload(("x.jpg", b"not an image at all")), 415),
            ("corrupt", self.upload(("x.jpg", b"\xff\xd8\xff" + bytes(range(256)) * 8)), 422),
            ("over 10 MB", self.upload(("x.jpg", b"\xff\xd8\xff" + bytes(10 * 1024 * 1024))), 413),
            ("40 megapixels", self.upload(("x.png", too_many_pixels)), 413),
            ("11 files", self.upload(*[("x.jpg", encoded(photo((200, 200))))] * 11), 400),
            ("11 pages", self.upload(("x.pdf", pdf(*[photo((200, 200))] * 11))), 400),
        ]
        for name, resp, status in cases:
            with self.subTest(name):
                self.assertEqual(resp.status_code, status, resp.get_json())
        self.assertFalse(db.InboxItem.select().exists())
        self.assertEqual(os.listdir(self.folder), [])

    def test_who_may_upload_for_a_herd(self):
        self.assertEqual(self.upload().status_code, 401)
        for username, herd, status in [
            ("owner", "G2", 403),  # not their herd
            ("spec", "G1", 403),  # a viewer
            ("mhjalp", "G1", 201),  # anyone working in the queue, for any herd
            ("man", "M3", 201),
            ("owner", "G1", 201),
        ]:
            with self.subTest(username=username, herd=herd):
                self.login(username)
                self.assertEqual(self.upload(herd=herd).status_code, status)

    def test_a_body_over_the_app_wide_limit_is_accepted(self):
        noise = Image.frombytes("RGB", (1500, 1500), os.urandom(1500 * 1500 * 3))
        big = encoded(noise, "PNG")
        self.assertGreater(2 * len(big), 11 * 1024 * 1024)  # MAX_CONTENT_LENGTH elsewhere
        self.login("owner")
        resp = self.upload(("a.png", big), ("b.png", big))
        self.assertEqual(resp.status_code, 201, resp.get_json())

    def test_files_are_removed_when_the_item_cannot_be_written(self):
        self.login("owner")
        with mock.patch.object(inbox, "create_upload", side_effect=RuntimeError("database gone")):
            with self.assertRaises(RuntimeError):
                self.upload(("a.jpg", encoded(photo())), ("b.jpg", encoded(photo(seed=2))))
        self.assertEqual(os.listdir(os.path.join(self.folder, "inkorg", "original")), [])


class TestUploadRateLimit(InboxTest):
    def setUp(self):
        super().setUp()
        limiter.reset()  # memory:// counters from earlier tests in this worker
        limiter.enabled = True
        self.addCleanup(limiter.reset)
        self.addCleanup(setattr, limiter, "enabled", False)

    def test_twenty_stored_uploads_an_hour_per_user(self):
        small = ("x.jpg", encoded(photo((200, 200))))  # flagged: low resolution
        self.assertEqual(self.upload(small).status_code, 401)  # anonymous: no limit to count
        self.login("owner")
        self.assertEqual([self.upload(small).status_code for _ in range(25)], [409] * 25)  # refusals spend nothing
        codes = [self.upload(small, accept_warnings="1").status_code for _ in range(21)]
        self.assertEqual(codes, [201] * 20 + [429])
        resp = self.upload(small, accept_warnings="1")
        self.assertEqual((resp.status_code, resp.mimetype), (429, "application/problem+json"))
        self.assertEqual(resp.get_json()["type"], "rate-limit-exceeded")
        self.login("man")  # another user has an hour of their own
        self.assertEqual(self.upload(small, accept_warnings="1").status_code, 201)
