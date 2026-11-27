"""The copy on the rabbit: rotation and black rectangles from the original, and who is served which file.

isort:skip_file
"""

import datetime
import io
import os
from unittest import mock

import utils.database as db  # noqa: E402
import utils.inbox as inbox  # noqa: E402
from PIL import Image  # noqa: E402

from tests.database_test import rewind_migrations  # noqa: E402
from tests.ht_helpers import ht_row  # noqa: E402
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
        resp = self.upload(("intyg.jpg", encoded(red_over_blue())), accept_warnings="1")  # flat colours look blurry
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

    def test_a_frame_crops_the_copy_without_black_boxes_and_a_redo_without_it_keeps_the_whole_photo(self):
        item, document = self.saved_document()
        frame = {"x": 0, "y": 0, "w": 1, "h": 0.5}
        resp = self.mask(item, document, mask_rects=[], copy_frame=frame)  # no no_personal_data: the frame says it
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json()["document"]["copy_frame"], frame)
        copy = self.copy(document)
        self.assertEqual(copy.size, (1200, 800))  # the top half, red: the blue half is not in the copy
        self.assertFalse(any(close(copy.getpixel((x, y)), BLUE) for x in range(0, 1200, 50) for y in range(0, 800, 50)))
        self.login("man")
        resp = self.mask(item, document, mask_rects=[{"x": 0, "y": 0.5, "w": 1, "h": 0.5}])
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertIsNone(db.InboxDocument.get_by_id(document.id).copy_frame)
        self.assertEqual(self.copy(document).size, (1200, 1600))
        events = self.reload(item).events.where(db.InboxEvent.kind == "kopia").order_by(db.InboxEvent.id)
        self.assertEqual([(e.detail["rects"], e.detail["frame"]) for e in events], [(0, True), (1, False)])
        # A frame over the whole photo leaves nothing out: it needs no_personal_data as no frame does.
        whole = {"x": 0, "y": 0, "w": 1, "h": 1}
        self.assertEqual(self.mask(item, document, mask_rects=[], copy_frame=whole).status_code, 400)
        resp = self.mask(item, document, mask_rects=[], copy_frame=whole, no_personal_data=True)
        self.assertEqual(resp.status_code, 200, resp.get_json())

    def test_the_frame_crops_the_turned_photo_after_its_boxes_are_painted(self):
        item, document = self.saved_document()
        # Turned clockwise the photo is 1600 × 1200, blue on the left and red on the right. The frame keeps all but
        # its left quarter; the box covers the middle of its right quarter, in fractions of the turned photo.
        frame = {"x": 0.25, "y": 0, "w": 0.75, "h": 1}
        resp = self.mask(
            item, document, rotation=90, mask_rects=[{"x": 0.75, "y": 0.25, "w": 0.25, "h": 0.5}], copy_frame=frame
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        copy = self.copy(document)
        self.assertEqual(copy.size, (1200, 1200))
        self.assertTrue(close(copy.getpixel((200, 600)), BLUE))  # x 400-800 of the turned photo
        self.assertTrue(close(copy.getpixel((600, 600)), RED))
        for x in (850, 1000, 1150):  # the box, x 1200-1600 of the turned photo
            self.assertTrue(close(copy.getpixel((x, 600)), (0, 0, 0)))
        self.assertTrue(close(copy.getpixel((1000, 100)), RED))  # above the box

    def test_the_frame_is_rounded_inwards_so_no_pixel_partly_outside_it_is_kept(self):
        item, document = self.saved_document()
        frame = {"x": 0.0004, "y": 0.0003, "w": 0.5, "h": 0.5}  # 0.48 px in from the left and top of 1200 x 1600
        resp = self.mask(item, document, mask_rects=[], copy_frame=frame)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(self.copy(document).size, (599, 799))  # columns 1-599, rows 1-799

    def test_a_frame_with_no_whole_pixel_inside_is_refused(self):
        item, document = self.saved_document()
        Image.new("RGB", (4, 4), (200, 0, 0)).save(self.stored(document), "JPEG")  # a photo of a few pixels
        resp = self.mask(item, document, mask_rects=[], copy_frame={"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1})
        self.assertEqual(resp.status_code, 400, resp.get_json())
        self.assertIsNone(db.InboxDocument.get_by_id(document.id).public_path)

    def test_only_a_handwritten_certificate_without_a_frame_or_boxes_is_offered_its_frame(self):
        _, document = self.saved_document()
        document = db.InboxDocument.get_by_id(document.id)
        frame = {"x": 0, "y": 0, "w": 1, "h": 0.5}
        for changes, suggestion in (
            ({"cert_format": "handskrivet"}, inbox.HANDWRITTEN_FRAME),
            ({"cert_format": "handskrivet", "mask_rects": []}, None),  # confirmed with nothing to hide
            ({"cert_format": "handskrivet", "mask_rects": [frame]}, None),
            ({"cert_format": "handskrivet", "copy_frame": frame}, None),
            ({"cert_format": "datorskrivet"}, None),
            ({"cert_format": None}, None),
        ):
            with self.subTest(changes):
                document.cert_format, document.mask_rects, document.copy_frame = None, None, None
                for key, value in changes.items():
                    setattr(document, key, value)
                body = inbox.documents_json([document])[0]
                self.assertEqual(body["frame_suggestion"], suggestion)
                self.assertEqual(body["copy_frame"], changes.get("copy_frame"))
                self.assertNotIn("mask_suggestion", body)

    def test_migration_58_adds_the_frame_and_replays(self):
        self.addCleanup(db.check_migrations)
        db.DATABASE.execute_sql("ALTER TABLE inbox_document DROP COLUMN copy_frame")
        for _ in range(2):  # replay-safe
            rewind_migrations(58)
            db.check_migrations()
        self.assertIn("copy_frame", {c.name for c in db.DATABASE.get_columns("inbox_document")})

    def test_a_copy_checked_against_the_registry_gives_the_rabbit_a_badge_everyone_sees(self):
        item, document = self.saved_document()
        rects = [{"x": 0, "y": 0.5, "w": 1, "h": 0.5}]
        for wrong in ("ja", 1):
            self.assertEqual(self.mask(item, document, mask_rects=rects, matches_registry=wrong).status_code, 400)
        resp = self.mask(item, document, mask_rects=rects, matches_registry=True)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        stored = db.InboxDocument.get_by_id(document.id)
        self.assertEqual(resp.get_json()["document"]["verified_at"], stored.verified_at.isoformat())
        self.assertEqual((stored.verified_by_id, stored.saved_certificate), (self.helper.id, "P-1"))

        self.login("spec")  # a viewer: sees the badge, not the copy
        rabbit = self.client.get("/api/v2/individual/G1-2112").get_json()
        self.assertEqual(rabbit["paper_certificate_checked"], stored.verified_at.isoformat())
        self.assertEqual(self.client.get("/api/v2/individual/G1-2112/paper-certificate").status_code, 403)

        # Another certificate on the rabbit since: not the one checked.
        db.Individual.update(certificate="P-2").where(db.Individual.number == "G1-2112").execute()
        self.assertIsNone(self.client.get("/api/v2/individual/G1-2112").get_json()["paper_certificate_checked"])
        db.Individual.update(certificate="P-1").where(db.Individual.number == "G1-2112").execute()

        self.login("man")  # made again without the check: the badge goes with it, and the old file after the commit
        old = stored.public_path
        self.assertEqual(self.mask(item, document, mask_rects=rects).status_code, 200)
        again = db.InboxDocument.get_by_id(document.id)
        self.assertIsNone(again.verified_at)
        self.assertNotEqual(again.public_path, old)
        self.assertFalse(os.path.exists(os.path.join(self.folder, old)))
        self.assertIsNone(self.client.get("/api/v2/individual/G1-2112").get_json()["paper_certificate_checked"])

    def test_an_old_certificate_linked_masked_and_checked_shows_its_badge_to_a_member(self):
        # The case the feature is for: G1-2111 has had certificate "12" since the old registry.
        self.login("owner")
        resp = self.upload(("intyg.jpg", encoded(red_over_blue())), accept_warnings="1")
        item = db.InboxItem.get_by_id(resp.get_json()["item"]["id"])
        document = item.documents.get()
        self.login("hjalp")
        self.post(f"/{item.id}/ta")
        body = {"action": "pappersintyg", "individual": "G1-2111", "paper_certificate": "12", "paper_number": "G1-2111"}
        self.assertEqual(self.post(f"/{item.id}/dokument/{document.id}/spara", **body).status_code, 200)
        self.assertFalse(db.IndividualCommand.select().exists())  # nothing written to the registry
        rects = [{"x": 0, "y": 0.5, "w": 1, "h": 0.5}]
        resp = self.mask(item, document, mask_rects=rects, matches_registry=True)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json()["item"]["state"], "klar")
        self.login("owner")  # a member without a genebank role
        rabbit = self.client.get("/api/v2/individual/G1-2111").get_json()
        self.assertEqual(
            rabbit["paper_certificate_checked"], db.InboxDocument.get_by_id(document.id).verified_at.isoformat()
        )

    def test_removing_the_copy_removes_its_check(self):
        item, document = self.saved_document()
        self.mask(item, document, mask_rects=[{"x": 0, "y": 0.5, "w": 1, "h": 0.5}], matches_registry=True)
        self.login("man")
        resp = self.client.delete(f"/api/v2/inkorg/{item.id}/dokument/{document.id}/kopia")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        stored = db.InboxDocument.get_by_id(document.id)
        self.assertEqual((stored.verified_at, stored.verified_by_id), (None, None))
        self.assertEqual(stored.saved_certificate, "P-1")  # what the photo was saved as stays

    def test_the_check_is_of_the_certificate_the_photo_was_saved_as(self):
        item, document = self.saved_document()  # saved as P-1
        db.Individual.update(certificate="P-2").where(db.Individual.number == "G1-2112").execute()
        rects = [{"x": 0, "y": 0.5, "w": 1, "h": 0.5}]
        resp = self.mask(item, document, mask_rects=rects, matches_registry=True)
        self.assertEqual(resp.status_code, 409, resp.get_json())
        self.assertIsNone(db.InboxDocument.get_by_id(document.id).verified_at)
        self.assertEqual(self.mask(item, document, mask_rects=rects).status_code, 200)  # unchecked, it goes on

    def test_a_rabbit_with_a_digital_certificate_beside_the_paper_number_gets_no_badge(self):
        item, document = self.saved_document()  # saved as P-1
        db.Individual.update(digital_certificate=500000).where(db.Individual.number == "G1-2112").execute()
        rects = [{"x": 0, "y": 0.5, "w": 1, "h": 0.5}]
        self.assertEqual(self.mask(item, document, mask_rects=rects, matches_registry=True).status_code, 409)
        db.InboxDocument.update(verified_at=datetime.datetime.now(datetime.timezone.utc)).where(
            db.InboxDocument.id == document.id
        ).execute()
        self.assertEqual(self.mask(item, document, mask_rects=rects).status_code, 200)
        db.InboxDocument.update(verified_at=datetime.datetime.now(datetime.timezone.utc)).where(
            db.InboxDocument.id == document.id
        ).execute()
        self.login("spec")
        self.assertIsNone(self.client.get("/api/v2/individual/G1-2112").get_json()["paper_certificate_checked"])

    def test_a_rabbit_renumbered_since_the_save_is_not_checked(self):
        item, document = self.saved_document()  # G1-2112, P-1
        db.Individual.update(number="G1-2118").where(db.Individual.number == "G1-2112").execute()
        rects = [{"x": 0, "y": 0.5, "w": 1, "h": 0.5}]
        self.assertEqual(self.mask(item, document, mask_rects=rects, matches_registry=True).status_code, 409)

    def test_a_rabbit_whose_latest_row_has_no_herd_still_has_its_copy_decided(self):
        item, document = self.saved_document()
        rabbit = db.Individual.get(db.Individual.number == "G1-2112")
        ht_row("TRANSFER", individual=rabbit, herd=None, herd_tracking_date=datetime.date.today())
        rects = [{"x": 0, "y": 0.5, "w": 1, "h": 0.5}]
        resp = self.mask(item, document, mask_rects=rects, matches_registry=True)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json()["document"]["individual_genebank_id"], rabbit.origin_herd.genebank_id)

    def test_a_photo_saved_before_the_number_was_kept_is_never_checked(self):
        item, document = self.saved_document()
        db.InboxDocument.update(saved_certificate=None).where(db.InboxDocument.id == document.id).execute()
        rects = [{"x": 0, "y": 0.5, "w": 1, "h": 0.5}]
        resp = self.mask(item, document, mask_rects=rects, matches_registry=True)
        self.assertEqual(resp.status_code, 409, resp.get_json())
        self.assertNotIn("None", resp.get_json()["detail"])

    def test_a_manager_of_another_genebank_who_helps_here_cannot_redo_a_closed_copy(self):
        item, document = self.saved_document()
        rects = [{"x": 0, "y": 0.5, "w": 1, "h": 0.5}]
        self.mask(item, document, mask_rects=rects, matches_registry=True)
        db.InboxItem.update(genebank=None).where(db.InboxItem.id == item.id).execute()  # any manager "manages" it
        both = self.user("bada", ("manager", self.genebanks[1].id), ("helper", self.genebanks[0].id))
        db.User.update(v2_prod_access=True).where(db.User.id == both.id).execute()
        self.login("bada")
        self.assertEqual(self.mask(item, document, mask_rects=rects).status_code, 409)  # not the handler, closed
        self.assertIsNotNone(db.InboxDocument.get_by_id(document.id).verified_at)

    def test_a_failed_cleanup_does_not_fail_a_committed_redo(self):
        item, document = self.saved_document()
        rects = [{"x": 0, "y": 0.5, "w": 1, "h": 0.5}]
        self.mask(item, document, mask_rects=rects)
        self.login("man")
        with mock.patch("utils.inbox.remove_files", side_effect=PermissionError("read-only")):
            resp = self.mask(item, document, mask_rects=rects, matches_registry=True)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertIsNotNone(db.InboxDocument.get_by_id(document.id).verified_at)

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
            {"mask_rects": []},  # an empty list says nothing without the explicit confirmation or a frame
            {"mask_rects": [], "no_personal_data": "true"},
            {"rotation": 0, "mask_rects": [], "copy_frame": None},
            {"rotation": 0, "mask_rects": [], "copy_frame": {"x": 0.5, "y": 0, "w": 0.6, "h": 1}},  # past the edge
            {"rotation": 0, "mask_rects": [], "copy_frame": {"x": 0, "y": 0, "w": 0.09, "h": 1}},  # under a tenth
            {"rotation": 0, "mask_rects": rects, "copy_frame": {"x": 0, "y": 0.5, "w": 1, "h": 0.05}},
            {"rotation": 0, "mask_rects": rects, "copy_frame": {}},
            {"rotation": 0, "mask_rects": rects, "copy_frame": False},
            {"rotation": 0, "mask_rects": rects, "copy_frame": [{"x": 0, "y": 0, "w": 1, "h": 0.5}]},
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

    def test_head_says_whether_there_is_a_copy_to_show_without_sending_it(self):
        item, document = self.saved_document()
        copy = "/api/v2/individual/G1-2112/paper-certificate"
        self.login("owner")
        self.assertEqual(self.client.head(copy).status_code, 404)  # no copy yet
        self.login("hjalp")
        self.mask(item, document, mask_rects=[], no_personal_data=True)
        for username, status in (("owner", 200), ("spec", 403), ("hjalp", 403)):
            with self.subTest(username):
                self.login(username)
                resp = self.client.head(copy)
                self.assertEqual((resp.status_code, resp.data), (status, b""))
        self.login("owner")
        self.assertEqual(self.client.head("/api/v2/individual/G1-2111/paper-certificate").status_code, 404)

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
        # A sale outside the association needs its buyer (ADR-0016), and from an owner the address.
        buyer = {"name": "Köpare Test", "town": "Visby", "postal_address": "Väg 1"}
        resp = self.post(
            f"/{item.id}/dokument/{document.id}/overlat", individual="G1-2111", herd="GX1", date=today, buyer=buyer
        )
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
        self.assertEqual(self.mask(item, document, mask_rects=rects).status_code, 403)  # not their genebank
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
