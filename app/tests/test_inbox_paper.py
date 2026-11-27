"""Hitta pappret: the tilt and the paper on synthetic photos, and the endpoint that changes nothing.

isort:skip_file
"""

import io
import os
import unittest

import numpy as np
import utils.database as db  # noqa: E402
import utils.inbox_paper as inbox_paper  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from playhouse.shortcuts import model_to_dict  # noqa: E402

from tests.inbox_fixtures import InboxTest, encoded  # noqa: E402

DARK = (50, 45, 40)


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
                self.assertEqual(find(image), {"angle": 0.0, "paper": None})

    def test_a_paper_too_small_to_believe_is_no_paper(self):
        self.assertIsNone(find(photographed(paper(700, 900), 6))["paper"])  # 13 % of the photo


class TestEndpoint(InboxTest):
    def setUp(self):
        super().setUp()
        self.login("owner")
        resp = self.upload(("intyg.jpg", encoded(photographed(paper(), 4))), accept_warnings="1")
        self.assertEqual(resp.status_code, 201, resp.get_json())
        self.item = db.InboxItem.get_by_id(resp.get_json()["item"]["id"])
        self.document = self.item.documents.get()

    def find(self, document_id=None):
        url = f"/api/v2/inkorg/{self.item.id}/dokument/{document_id or self.document.id}/hitta-pappret"
        return self.client.post(url)

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
