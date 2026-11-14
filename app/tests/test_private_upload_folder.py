"""PRIVATE_UPLOAD_FOLDER may not overlap UPLOAD_FOLDER, which nginx serves without login."""

import os
import tempfile
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


class TestUnwritablePrivateFolder(unittest.TestCase):
    def test_one_clear_error_naming_the_folder(self):
        with tempfile.NamedTemporaryFile() as blocker:  # a file where a folder must go: not even root writes there
            folder = os.path.join(blocker.name, "skyddat")
            with (
                mock.patch.object(settings.service, "private_upload_folder", folder),
                self.assertLogs("utils.settings", "ERROR") as logs,
            ):
                self.assertFalse(settings.report_unwritable_private_folder())
        (line,) = logs.output
        self.assertIn(f"PRIVATE_UPLOAD_FOLDER {folder} is not writable", line)

    def test_a_writable_folder_says_nothing(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            mock.patch.object(settings.service, "private_upload_folder", folder),
        ):
            with self.assertNoLogs("utils.settings", "ERROR"):
                self.assertTrue(settings.report_unwritable_private_folder())
