"""Shared setup for the intake queue's tests: users, a private folder of its own, and synthetic photos.

No real certificates: the photos are drawn with Pillow.

isort:skip_file
"""

import io
import os
import random
import shutil
import tempfile
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
import utils.settings as settings  # noqa: E402
from herdbook import APP, limiter  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402

limiter.enabled = False


def photo(size=(1200, 1600), seed=1):
    """A synthetic certificate: dark marks on pale paper, sharp enough to pass the quality check."""
    rnd = random.Random(seed)
    image = Image.new("RGB", size, (235, 240, 225))
    draw = ImageDraw.Draw(image)
    for _ in range(size[0] * size[1] // 4800):
        x, y = rnd.randrange(size[0] - 60), rnd.randrange(size[1] - 20)
        draw.rectangle([x, y, x + rnd.randrange(5, 60), y + rnd.randrange(2, 14)], fill=(20, 20, 30))
    return image


def blurry(size=(1200, 1600)):
    return photo(size).filter(ImageFilter.GaussianBlur(8))


def encoded(image, fmt="JPEG", **options):
    buffer = io.BytesIO()
    image.save(buffer, fmt, **options)
    return buffer.getvalue()


def pdf(*pages):
    return encoded(pages[0], "PDF", save_all=True, append_images=list(pages[1:]), resolution=150)


class InboxTest(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        patcher = mock.patch.object(settings.service, "private_upload_folder", self.folder)
        patcher.start()
        self.addCleanup(patcher.stop)
        gotland, mellerud = self.genebanks
        self.helper = self.user("hjalp", ("helper", gotland.id))
        self.mellerud_helper = self.user("mhjalp", ("helper", mellerud.id))

    def user(self, name, *roles):
        user = da.register_user(name, "pass")
        for level, target in roles:
            user.add_role(level, target)
        return db.User.get_by_id(user.id)

    def login(self, username):
        self.client.get("/api/logout")
        resp = self.client.post("/api/login", json={"username": username, "password": "pass"})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))

    def upload(self, *files, herd="G1", **form):
        """POST /inkorg/upload with (filename, bytes) pairs; the default is one sharp JPEG."""
        files = files or [("intyg.jpg", encoded(photo()))]
        data = {"herd": herd, "files": [(io.BytesIO(content), name) for name, content in files], **form}
        return self.client.post("/api/v2/inkorg/upload", data=data, content_type="multipart/form-data")

    def stored(self, document):
        return os.path.join(self.folder, document.original_path)
