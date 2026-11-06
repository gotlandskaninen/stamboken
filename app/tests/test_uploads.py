#!/usr/bin/env python3
"""
Tests for photo upload endpoint v2 (Story 1.4).

isort:skip_file
"""

import io
import os
import shutil
import struct
import tempfile
import unittest
import zlib
from datetime import date
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import blueprints.uploads as uploads  # noqa: E402
import utils.database as db  # noqa: E402
from herdbook import APP, limiter  # noqa: E402
from PIL import Image, ImageFile  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402


def _make_jpeg(width=100, height=100):
    """Create a minimal JPEG in memory and return as BytesIO."""
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color="red")
    img.save(buf, "JPEG")
    buf.seek(0)
    return buf


def _make_png(width=100, height=100):
    """Create a minimal PNG in memory and return as BytesIO."""
    buf = io.BytesIO()
    img = Image.new("RGBA", (width, height), color=(0, 255, 0, 128))
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


def _make_webp(width=100, height=100):
    """Create a minimal WebP in memory and return as BytesIO."""
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color="blue")
    img.save(buf, "WEBP")
    buf.seek(0)
    return buf


def _bomb_png(width=13000, height=13000):
    """Valid 1-bit greyscale PNG of zero pixels, ~20 KB on the wire, built streaming (no big buffer)."""

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    comp = zlib.compressobj(9)
    row = b"\x00" * (1 + (width + 7) // 8)
    idat = b"".join(comp.compress(row) for _ in range(height)) + comp.flush()
    ihdr = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    return io.BytesIO(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


class UploadFlaskTest(DatabaseTest):
    """Base class for upload tests with Flask test client."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        APP.config["SESSION_PERMANENT"] = False
        limiter.enabled = False
        self.client = APP.test_client(use_cookies=True)
        # Use temp dir for uploads so tests don't touch real filesystem
        self._upload_dir = tempfile.mkdtemp()
        os.environ["UPLOAD_FOLDER"] = self._upload_dir
        super().setUp()

    def tearDown(self):
        shutil.rmtree(self._upload_dir, ignore_errors=True)
        super().tearDown()

    def _login_as(self, user):
        """Log in as the given user via session-based login."""
        self.client.post("/api/login", json={"username": user.email, "password": "pass"})

    def _upload(self, individual_number, file_data, filename="photo.jpg"):
        """Helper to POST a file upload to the v2 endpoint."""
        return self.client.post(
            f"/api/v2/upload/photo/{individual_number}",
            data={"file": (file_data, filename)},
            content_type="multipart/form-data",
            headers={"Accept": "application/json"},
        )


class TestUploadPhotoEndpoint(UploadFlaskTest):
    """Test POST /api/v2/upload/photo/<individual_number>."""

    def test_upload_requires_auth(self):
        """Unauthenticated request should return 401."""
        resp = self._upload("G1-2111", _make_jpeg())
        self.assertEqual(resp.status_code, 401)

    def test_upload_rejects_non_owner(self):
        """User without edit rights to the individual should get 403."""
        self._login_as(self.viewer)
        resp = self._upload("G1-2111", _make_jpeg())
        self.assertEqual(resp.status_code, 403)
        body = resp.get_json()
        self.assertIn("status", body)
        self.assertEqual(body["status"], 403)

    def test_upload_accepts_owner(self):
        """Owner of the herd should be able to upload."""
        self._login_as(self.owner)
        resp = self._upload("G1-2111", _make_jpeg())
        self.assertEqual(resp.status_code, 201)
        result = resp.get_json()
        self.assertEqual(result["filename"], "G1-2111.jpg")

    def test_upload_accepts_admin(self):
        """Admin should be able to upload for any individual."""
        self._login_as(self.admin)
        resp = self._upload("G1-2111", _make_jpeg())
        self.assertEqual(resp.status_code, 201)

    def test_upload_rejects_invalid_magic_bytes(self):
        """Non-image file with wrong magic bytes should be rejected."""
        self._login_as(self.owner)
        fake = io.BytesIO(b"this is not an image at all, just text")
        resp = self._upload("G1-2111", fake)
        self.assertEqual(resp.status_code, 415)
        body = resp.get_json()
        self.assertIn("status", body)
        self.assertEqual(body["status"], 415)

    def test_upload_rejects_oversized_file(self):
        """File larger than 10MB should be rejected."""
        self._login_as(self.owner)
        big = io.BytesIO(b"\xff\xd8\xff" + b"\x00" * (10 * 1024 * 1024 + 1))
        resp = self._upload("G1-2111", big, "huge.jpg")
        self.assertEqual(resp.status_code, 413)
        body = resp.get_json()
        self.assertIn("status", body)
        self.assertEqual(body["status"], 413)

    def test_upload_no_file(self):
        """Request without file should return 400."""
        self._login_as(self.owner)
        resp = self.client.post(
            "/api/v2/upload/photo/G1-2111",
            data={},
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertIn("status", body)
        self.assertEqual(body["status"], 400)

    def test_upload_nonexistent_individual(self):
        """Upload for non-existent individual should return 404."""
        self._login_as(self.admin)
        resp = self._upload("G1-9999", _make_jpeg())
        self.assertEqual(resp.status_code, 404)
        body = resp.get_json()
        self.assertIn("status", body)
        self.assertEqual(body["status"], 404)

    def test_upload_creates_files(self):
        """Successful upload should create both main and thumbnail files."""
        self._login_as(self.owner)
        resp = self._upload("G1-2111", _make_jpeg(400, 300))
        self.assertEqual(resp.status_code, 201)

        kaniner_dir = os.path.join(self._upload_dir, "kaniner")
        self.assertTrue(os.path.isfile(os.path.join(kaniner_dir, "G1-2111.jpg")))
        self.assertTrue(os.path.isfile(os.path.join(kaniner_dir, "G1-2111_thumb.jpg")))

        # Verify thumbnail is actually <=200px
        with Image.open(os.path.join(kaniner_dir, "G1-2111_thumb.jpg")) as thumb:
            self.assertLessEqual(thumb.width, 200)
            self.assertLessEqual(thumb.height, 200)

    def test_upload_sets_has_photo(self):
        """Successful upload should set has_photo=True on the individual."""
        import utils.database as db

        self._login_as(self.owner)
        resp = self._upload("G1-2111", _make_jpeg())
        self.assertEqual(resp.status_code, 201)

        individual = db.Individual.get(db.Individual.number == "G1-2111")
        self.assertTrue(individual.has_photo)

    def test_upload_png_converts_to_jpeg(self):
        """PNG upload should be converted to JPEG."""
        self._login_as(self.owner)
        resp = self._upload("G1-2111", _make_png(), "photo.png")
        self.assertEqual(resp.status_code, 201)
        result = resp.get_json()
        self.assertEqual(result["filename"], "G1-2111.jpg")

        kaniner_dir = os.path.join(self._upload_dir, "kaniner")
        with Image.open(os.path.join(kaniner_dir, "G1-2111.jpg")) as img:
            self.assertEqual(img.format, "JPEG")

    def test_upload_webp_converts_to_jpeg(self):
        """WebP upload should be converted to JPEG."""
        self._login_as(self.owner)
        resp = self._upload("G1-2111", _make_webp(), "photo.webp")
        self.assertEqual(resp.status_code, 201)
        result = resp.get_json()
        self.assertEqual(result["filename"], "G1-2111.jpg")

    def test_upload_malformed_image(self):
        """File with valid JPEG magic bytes but corrupt content should return 422."""
        self._login_as(self.owner)
        # Valid JPEG header but garbage body — Pillow will fail on load()
        corrupt = io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        resp = self._upload("G1-2111", corrupt)
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertIn("status", body)
        self.assertEqual(body["status"], 422)

    def test_upload_rejects_pixel_bomb_before_decoding(self):
        """A ~20 KB PNG of 13000x13000 px (169 MP, ~800 MB decoded) is refused before load()."""
        png = _bomb_png()
        self.assertLess(len(png.getvalue()), 100 * 1024)
        decoded = []

        def spy_load(img_self):  # blocks the real decode so the test stays cheap
            decoded.append(img_self.size)
            raise RuntimeError("test blocked the real decode")

        self._login_as(self.owner)
        with mock.patch.object(ImageFile.ImageFile, "load", spy_load):
            resp = self._upload("G1-2111", png, filename="bomb.png")
        self.assertEqual(decoded, [], f"endpoint fully decoded a {decoded} image")
        self.assertEqual(resp.status_code, 413, resp.get_json())
        self.assertFalse(db.Individual.get(db.Individual.number == "G1-2111").has_photo)

    def test_upload_rejects_webp_canvas_bomb_before_opening(self):
        """Pillow's WebP decoder allocates the canvas inside Image.open, so check the header first."""
        width = height = 20000  # 400 MP
        vp8x = b"VP8X" + (10).to_bytes(4, "little") + b"\x10\x00\x00\x00"
        vp8x += (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
        webp = io.BytesIO(b"RIFF" + (4 + len(vp8x)).to_bytes(4, "little") + b"WEBP" + vp8x)
        self._login_as(self.owner)
        with mock.patch.object(uploads.Image, "open", side_effect=RuntimeError("test blocked Image.open")) as opened:
            resp = self._upload("G1-2111", webp, filename="bomb.webp")
        self.assertEqual(opened.call_count, 0, "Image.open (and the WebP decoder) never runs on a 400 MP canvas")
        self.assertEqual(resp.status_code, 413, resp.get_json())

    def test_upload_answers_413_when_pillow_refuses_the_size_itself(self):
        """Above ~179 MP Pillow raises DecompressionBombError in Image.open; that is a size refusal."""
        self._login_as(self.owner)
        resp = self._upload("G1-2111", _bomb_png(20000, 20000), filename="bomb.png")
        self.assertEqual(resp.status_code, 413, resp.get_json())

    def test_upload_does_not_revert_a_concurrent_edit(self):
        """A death recorded while the image is processed survives the upload (no full-row save)."""
        ind_id = db.Individual.get(db.Individual.number == "G1-2111").id
        real_open = uploads.Image.open

        def open_while_manager_records_death(*args, **kwargs):
            # Commits between the endpoint's Individual.get() and its save().
            db.Individual.update(death_date=date(2026, 10, 1), death_note="död").where(
                db.Individual.id == ind_id
            ).execute()
            return real_open(*args, **kwargs)

        self._login_as(self.owner)
        with mock.patch.object(uploads.Image, "open", side_effect=open_while_manager_records_death):
            resp = self._upload("G1-2111", _make_jpeg())
        self.assertEqual(resp.status_code, 201, resp.get_json())
        fresh = db.Individual.get_by_id(ind_id)
        self.assertEqual((fresh.death_date, fresh.death_note), (date(2026, 10, 1), "död"), "concurrent death undone")
        self.assertTrue(fresh.has_photo)

    def test_upload_is_authorized_again_under_the_lock(self):
        """Final review (24a65b0): a sale completing while the image is processed. The former owner may no longer
        edit the rabbit, and must not replace the buyer's photo."""
        from datetime import datetime

        from tests.ht_helpers import ht_row

        ind_id = db.Individual.get(db.Individual.number == "G1-2111").id
        real_open = uploads.Image.open

        def open_while_sold(*args, **kwargs):
            ht_row(
                "TRANSFER",
                from_herd=self.herds[0],
                herd=self.herds[1],
                individual=ind_id,
                herd_tracking_date=datetime.now(),
            )
            return real_open(*args, **kwargs)

        self._login_as(self.owner)
        with mock.patch.object(uploads.Image, "open", side_effect=open_while_sold):
            resp = self._upload("G1-2111", _make_jpeg())
        kaniner = os.path.join(self._upload_dir, "kaniner")
        stored = sorted(os.listdir(kaniner)) if os.path.isdir(kaniner) else []
        self.assertEqual((resp.status_code, stored), (403, []), resp.get_json())
        self.assertFalse(db.Individual.get_by_id(ind_id).has_photo)

    def test_upload_racing_a_renumber_stores_the_photo_under_the_current_number(self):
        """The rabbit is renumbered while its image is processed. The photo must land
        under its new number, not under the old one, which may already belong to another rabbit."""
        ind_id = db.Individual.get(db.Individual.number == "G1-2111").id
        real_open = uploads.Image.open

        def open_while_renumbered(*args, **kwargs):
            db.Individual.update(number="G1-2119").where(db.Individual.id == ind_id).execute()
            return real_open(*args, **kwargs)

        self._login_as(self.owner)
        with mock.patch.object(uploads.Image, "open", side_effect=open_while_renumbered):
            resp = self._upload("G1-2111", _make_jpeg())
        kaniner = os.path.join(self._upload_dir, "kaniner")
        self.assertEqual(sorted(os.listdir(kaniner)), ["G1-2119.jpg", "G1-2119_thumb.jpg"])
        self.assertEqual(resp.status_code, 201, resp.get_json())
        self.assertEqual(resp.get_json()["filename"], "G1-2119.jpg")
        self.assertTrue(db.Individual.get_by_id(ind_id).has_photo)


class TestMagicBytesValidation(unittest.TestCase):
    """Unit tests for _validate_magic_bytes function."""

    def test_jpeg_detected(self):
        from blueprints.uploads import _validate_magic_bytes

        buf = _make_jpeg()
        self.assertEqual(_validate_magic_bytes(buf), "jpeg")

    def test_png_detected(self):
        from blueprints.uploads import _validate_magic_bytes

        buf = _make_png()
        self.assertEqual(_validate_magic_bytes(buf), "png")

    def test_webp_detected(self):
        from blueprints.uploads import _validate_magic_bytes

        buf = _make_webp()
        self.assertEqual(_validate_magic_bytes(buf), "webp")

    def test_text_rejected(self):
        from blueprints.uploads import _validate_magic_bytes

        buf = io.BytesIO(b"Hello world this is plain text")
        self.assertIsNone(_validate_magic_bytes(buf))

    def test_gif_rejected(self):
        from blueprints.uploads import _validate_magic_bytes

        buf = io.BytesIO(b"GIF89a" + b"\x00" * 20)
        self.assertIsNone(_validate_magic_bytes(buf))


if __name__ == "__main__":
    unittest.main()
