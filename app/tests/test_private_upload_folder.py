"""PRIVATE_UPLOAD_FOLDER may not overlap UPLOAD_FOLDER, which nginx serves without login."""

import os
import unittest
from unittest import mock

import utils.settings as settings


class TestPrivateUploadFolder(unittest.TestCase):
    def refuses(self, private, uploads="/app/uppladdningar"):
        with (
            mock.patch.object(settings.service, "private_upload_folder", private),
            mock.patch.dict(os.environ, {"UPLOAD_FOLDER": uploads}),
        ):
            try:
                settings.refuse_private_folder_under_uploads()
            except RuntimeError:
                return True
            return False

    def test_overlap_is_refused(self):
        self.assertTrue(self.refuses("/app/uppladdningar/skyddat"))
        self.assertTrue(self.refuses("/app/uppladdningar"))
        self.assertTrue(self.refuses("/app", uploads="/app/uppladdningar"))
        self.assertFalse(self.refuses("/app/skyddat"))
        self.assertFalse(self.refuses("/app/uppladdningar-skyddat"))
