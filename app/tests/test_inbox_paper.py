"""Hitta pappret: the tilt and the paper on synthetic photos, and the endpoint that changes nothing.

isort:skip_file
"""

import io
import os
import unittest
import unittest.mock

import numpy as np
import utils.database as db  # noqa: E402
import utils.inbox_paper as inbox_paper  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from playhouse.shortcuts import model_to_dict  # noqa: E402

from tests.inbox_fixtures import InboxTest, encoded  # noqa: E402

DARK = (50, 45, 40)
GREEN = (30, 200, 30)


def paper(width=1200, height=1600):
    """Light paper with lines of dark writing."""
    image = Image.new("RGB", (width, height), (235, 235, 230))
    draw = ImageDraw.Draw(image)
    for y in range(150, height - 150, 60):
        for x in range(120, width - 120, 90):
            draw.rectangle([x, y, x + 60, y + 14], fill=(40, 40, 40))
    return image


def photographed(image, tilt, background=DARK, size=(1800, 2200)):
    """`image` turned `tilt` degrees counter-clockwise, in the middle of a photo of a table."""
    turned = image.convert("RGBA").rotate(tilt, expand=True, resample=Image.Resampling.BICUBIC)
    photo = Image.new("RGB", size, background)
    photo.paste(turned, ((size[0] - turned.width) // 2, (size[1] - turned.height) // 2), turned)
    return photo


def find(image, rotation=0):
    return inbox_paper.find_paper(io.BytesIO(encoded(image, quality=90)), rotation)


class TestFindPaper(unittest.TestCase):
    def assert_found(self, photo, tilt, rotation=0):
        """The angle straightens the paper, and the box holds it, in fractions of F turned by that angle."""
        found = find(photo, rotation)
        self.assertAlmostEqual(found["angle"], tilt, delta=0.3)
        straightened = inbox_paper.turned(photo, rotation, found["angle"])
        width, height = straightened.size
        middle = straightened.crop((width // 2 - 450, height // 2 - 650, width // 2 + 450, height // 2 + 650))
        self.assertEqual(inbox_paper._tilt(np.asarray(middle.convert("L"))), 0.0)  # pylint: disable=protected-access
        box, x, y = found["paper"], (width - 1200) / 2 / width, (height - 1600) / 2 / height
        self.assertLessEqual(box["x"], x)
        self.assertLessEqual(box["y"], y)
        self.assertGreaterEqual(box["x"] + box["w"], 1 - x)
        self.assertGreaterEqual(box["y"] + box["h"], 1 - y)
        self.assertLess(box["w"] * box["h"] - (1 - 2 * x) * (1 - 2 * y), 0.06)  # the margin, not the table

    def test_a_paper_tilted_4_degrees_on_a_dark_table_is_straightened_and_found(self):
        self.assert_found(photographed(paper(), 4), 4)  # turned 4° counter-clockwise: straightened 4° clockwise
        self.assert_found(photographed(paper(), -4), -4)

    def test_the_tilt_is_of_the_photo_turned_by_its_rotation(self):
        sideways = photographed(paper(), 4).rotate(-90, expand=True)  # stored lying down: 270° stands it up
        self.assert_found(sideways, 4, rotation=270)

    def test_a_large_tilt_is_found_too(self):
        self.assert_found(photographed(paper(), 12), 12)

    def test_a_straight_photo_is_not_tilted(self):
        self.assertEqual(find(photographed(paper(), 0))["angle"], 0.0)
        self.assertIsNotNone(find(photographed(paper(), 0))["paper"])
        for name, image in (
            ("only paper", paper()),
            ("paper on a light table", photographed(paper(), 0, background=(250, 250, 250))),
            ("a dark table", Image.new("RGB", (1800, 2200), DARK)),
            ("a blank page", Image.new("RGB", (1800, 2200), (240, 240, 240))),
        ):
            with self.subTest(name):
                self.assertEqual(find(image), {"angle": 0.0, "paper": None, "paper_tight": None})

    def test_on_a_light_table_the_frame_never_keeps_the_lower_third(self):
        """The table is as light as the paper: either no paper, or a frame (paperFrame) that misses its lower third."""
        certificate = paper()
        # Just inside the seller and buyer block, which starts at 1067 of 1600.
        ImageDraw.Draw(certificate).rectangle([100, 1080, 1099, 1099], fill=GREEN)
        for table, shadow in (
            ((250, 250, 248), None),
            ((215, 210, 200), None),
            ((170, 160, 150), None),
            ((250, 250, 248), "right"),  # the light area runs to three edges of the photo: it is the table
            # Dark only to the right and below: the table's own two edges against it look like the paper's, and
            # the light area runs out to the two other edges, which meet in a corner.
            ((250, 250, 248), "right and below"),
        ):
            with self.subTest(table=table, shadow=shadow):
                photo = Image.new("RGB", (2000, 2400), table)
                if shadow:
                    ImageDraw.Draw(photo).rectangle([1550, 0, 1999, 2399], fill=DARK)
                if shadow == "right and below":  # the paper near the top left, the table on far below it
                    ImageDraw.Draw(photo).rectangle([0, 2100, 1999, 2399], fill=DARK)
                tilted = certificate.convert("RGBA").rotate(5, expand=True, resample=Image.Resampling.BICUBIC)
                photo.paste(tilted, (100, 50) if shadow == "right and below" else (150, 100), tilted)  # off the middle
                found = find(photo)
                if found["paper"] is None:
                    continue
                straightened, box, tight = (
                    inbox_paper.turned(photo, 0, found["angle"]),
                    found["paper"],
                    found["paper_tight"],
                )
                width, height = straightened.size
                kept = straightened.crop(
                    (
                        round(box["x"] * width),
                        round(box["y"] * height),
                        round((box["x"] + box["w"]) * width),
                        round((tight["y"] + tight["h"] * 0.6667) * height),
                    )
                )
                green = (np.abs(np.asarray(kept, np.int16) - GREEN) < 50).all(axis=-1)
                self.assertFalse(green.any())
        self.assertIsNone(find(photographed(paper(), 5, background=(250, 250, 248)))["paper"])

    def test_the_tight_box_is_the_paper_and_the_padded_one_holds_it_with_a_margin(self):
        found = find(photographed(paper(), 0))
        tight, padded = found["paper_tight"], found["paper"]
        x, y = (1800 - 1200) / 2 / 1800, (2200 - 1600) / 2 / 2200  # the paper's edges in the photo
        for got, expected in ((tight["x"], x), (tight["y"], y), (tight["w"], 1200 / 1800), (tight["h"], 1600 / 2200)):
            self.assertAlmostEqual(got, expected, delta=0.004)  # a pixel or so of the copy it was found on
        self.assertAlmostEqual(padded["y"], tight["y"] - inbox_paper.PAPER_MARGIN, places=3)
        self.assertAlmostEqual(padded["h"], tight["h"] + 2 * inbox_paper.PAPER_MARGIN, places=3)

    def test_a_paper_too_small_to_believe_is_no_paper(self):
        self.assertIsNone(find(photographed(paper(700, 900), 6))["paper"])  # 13 % of the photo


class TestTurnedSize(unittest.TestCase):
    # Pillow's sizes, the same as next-app's turnedSize test: the preview and F are the same shape.
    PILLOW = {
        (1200, 1600, 5): (1336, 1700),
        (1200, 1600, -3.7): (1302, 1676),
        (4000, 3000, 102.5): (3796, 4556),
        (3024, 4032, -15): (3966, 4678),
        (401, 301, 7.3): (437, 351),
        (1200, 1600, 270.4): (1610, 1212),
    }

    def test_it_is_the_size_pillow_turns_to(self):
        for (width, height, degrees), size in self.PILLOW.items():
            with self.subTest((width, height, degrees)):
                self.assertEqual(inbox_paper.turned_size(width, height, degrees), size)
                if width * height < 2_000_000:
                    self.assertEqual(Image.new("1", (width, height)).rotate(-degrees, expand=True).size, size)
        for degrees in (0, 90, 180, 270, -90):  # Pillow's quarter turns transpose
            size = Image.new("1", (401, 301)).rotate(-degrees, expand=True).size
            self.assertEqual(inbox_paper.turned_size(401, 301, degrees), size)

    def test_a_long_thin_photo_is_made_smaller_before_it_is_turned(self):
        # 40 MP, the most an upload may have: turned 15° its bounding box would be 440 MP.
        self.assertGreater(
            inbox_paper.turned_size(40_000, 1_000, 15)[0] * inbox_paper.turned_size(40_000, 1_000, 15)[1], 400_000_000
        )
        width, height = inbox_paper.fitted(40_000, 1_000, 15)
        turned_width, turned_height = inbox_paper.turned_size(width, height, 15)
        self.assertLessEqual(turned_width * turned_height, inbox_paper.MAX_PIXELS)
        self.assertGreater(turned_width * turned_height, inbox_paper.MAX_PIXELS * 0.95)
        self.assertAlmostEqual(width / height, 40, delta=0.2)
        self.assertEqual(inbox_paper.fitted(4000, 3000, 15), (4000, 3000))  # an ordinary photo keeps its size

    def test_turned_shrinks_the_photo_it_was_given_to_that_size(self):
        photo = Image.new("RGB", (400, 10), "white")
        with unittest.mock.patch.object(inbox_paper, "MAX_PIXELS", 2_000):
            width, height = inbox_paper.fitted(400, 10, 15)
            self.assertLess(width, 400)
            self.assertEqual(inbox_paper.turned(photo, 0, 15).size, inbox_paper.turned_size(width, height, 15))
        self.assertEqual(inbox_paper.turned(photo, 0, 15).size, inbox_paper.turned_size(400, 10, 15))


class TestEndpoint(InboxTest):
    def setUp(self):
        super().setUp()
        self.login("owner")
        resp = self.upload(("intyg.jpg", encoded(photographed(paper(), 4))), accept_warnings="1")
        self.assertEqual(resp.status_code, 201, resp.get_json())
        self.item = db.InboxItem.get_by_id(resp.get_json()["item"]["id"])
        self.document = self.item.documents.get()

    def find(self, document_id=None, **body):
        url = f"/api/v2/inkorg/{self.item.id}/dokument/{document_id or self.document.id}/hitta-pappret"
        return self.client.post(url, json=body)

    def state(self):
        events = db.InboxEvent.select().where(db.InboxEvent.item == self.item.id).count()
        return model_to_dict(db.InboxDocument.get_by_id(self.document.id), recurse=False), events

    def test_the_handler_gets_the_angle_and_the_paper_and_nothing_changes(self):
        self.login("hjalp")
        self.post(f"/{self.item.id}/ta")
        before = self.state()
        resp = self.find()
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertAlmostEqual(resp.get_json()["angle"], 4, delta=0.3)
        self.assertEqual(set(resp.get_json()["paper"]), {"x", "y", "w", "h"})
        self.assertEqual(self.state(), before)

    def test_with_an_angle_it_is_not_looked_for_and_the_paper_is_found_at_that_angle(self):
        self.login("hjalp")
        self.post(f"/{self.item.id}/ta")
        before = self.state()
        level = self.find(straighten=0).get_json()
        self.assertEqual(level["angle"], 0)  # the photo is tilted 4°, but the angle given is kept
        resp = self.find(straighten=4)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json()["angle"], 4)
        with Image.open(self.stored(self.document)) as photo:
            width, height = inbox_paper.turned(photo, 0, 4).size
        box, x, y = resp.get_json()["paper"], (width - 1200) / 2 / width, (height - 1600) / 2 / height
        self.assertLessEqual(box["x"], x)
        self.assertLessEqual(box["y"], y)
        self.assertGreaterEqual(box["x"] + box["w"], 1 - x)
        self.assertGreaterEqual(box["y"] + box["h"], 1 - y)
        self.assertNotEqual(level["paper"], resp.get_json()["paper"])  # each in its own frame
        for bad in (15.1, True, "4", float("nan")):
            with self.subTest(bad):
                self.assertEqual(self.find(straighten=bad).status_code, 400)
        self.assertEqual(self.state(), before)

    def test_the_turn_the_view_shows_must_be_the_stored_one(self):
        self.login("hjalp")
        self.post(f"/{self.item.id}/ta")
        db.InboxDocument.update(rotation=90).where(db.InboxDocument.id == self.document.id).execute()
        self.assertEqual(self.find(rotation=0).status_code, 409)  # turned in the view, not yet stored
        self.assertEqual(self.find(rotation=45).status_code, 400)
        resp = self.find(rotation=90)
        self.assertEqual(resp.status_code, 200, resp.get_json())

    def test_only_the_handler_of_an_item_with_its_original(self):
        before = self.state()
        self.assertEqual(self.find().status_code, 403)  # the uploader does not work in the queue
        self.login("hjalp")
        self.assertEqual(self.find().status_code, 409)  # not taken
        self.login("mhjalp")
        self.assertEqual(self.find().status_code, 403)  # another genebank
        self.client.get("/api/logout")
        self.assertEqual(self.find().status_code, 401)
        self.assertEqual(self.state(), before)
        self.login("hjalp")
        self.post(f"/{self.item.id}/ta")
        self.assertEqual(self.find(document_id=self.document.id + 1000).status_code, 404)
        os.remove(self.stored(self.document))  # erased on disk while the row still names it
        self.assertEqual(self.find().status_code, 409)
        db.InboxDocument.update(original_path=None).where(db.InboxDocument.id == self.document.id).execute()
        self.assertEqual(self.find().status_code, 409)
