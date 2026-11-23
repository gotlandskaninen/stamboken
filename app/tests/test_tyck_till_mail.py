"""The "Tyck till" mail: to the function address, the member's contacts only as chosen, the images as attachments."""

import io
import json
import shutil
import tempfile
import uuid
from unittest import mock

import utils.data_access as da
import utils.database as db
import utils.mail as mail
import utils.settings as settings
import utils.tyck_till as tt
from PIL import Image

from tests.test_mail_queue import MailTest

UUID_IN_PATH = "3f2b9c1e-8a4d-4e6f-9b7a-1c2d3e4f5a6b"


def _jpeg(color):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, "JPEG")
    return buffer.getvalue()


class TestTyckTillMail(MailTest):
    def setUp(self):
        super().setUp()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        for patch in (
            mock.patch.object(settings.service, "private_upload_folder", self.root),
            mock.patch.object(settings.tyck_till, "recipient", "funktion@example.org"),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.id = uuid.uuid4()

    def submit(self, images=(), repo=1, tavla=1, **fields):
        folder = tt.folder(self.id)
        folder.mkdir(parents=True)
        names = []
        for n, data in enumerate(images):
            names.append(f"bild-{n}.jpg")
            (folder / names[-1]).write_bytes(data)
        data = {"kind": "fel", "text": "Knappen syns inte", "path": "/stamboken/kaniner", "pekat": "", "version": "2.13.0",
                "device": "mobil", "email": "", "user_id": None, "contact": False, **fields, "images": names}
        (folder / "inskick.json").write_text(json.dumps(data))
        params = {"inskick": self.id.int, "issue": 45, "repo": repo, "tavla": tavla}
        return mail.enqueue_mail("tyck_till.inskick", "tyck_till", 0, params, dedupe_key=f"tyck-till:{self.id}")

    def send(self):
        relay = self.relay()
        mail.send_pending(self.now)
        return relay.sent

    def test_recipient_is_the_function_address(self):
        self.submit()
        ((_, _, envelope_to),) = self.send()
        self.assertEqual(envelope_to, ["funktion@example.org"])

    def test_subject_has_repo_number_and_reference(self):
        self.submit()
        ((msg, _, _),) = self.send()
        self.assertEqual(msg["Subject"], f"[Tyck till] stamboken-drift#45 {tt.reference(self.id)}")

    def test_public_repo_in_the_subject(self):
        self.submit(repo=0)
        ((msg, _, _),) = self.send()
        self.assertEqual(msg["Subject"], f"[Tyck till] stamboken#45 {tt.reference(self.id)}")

    def test_body_has_text_path_pointed_account_and_contact(self):
        user = da.register_user("medlem@example.org", "pass", fullname="Medlem Test")
        self.submit(
            user_id=user.id, contact=True, pekat=f"knappen {UUID_IN_PATH}", path=f"/stamboken/verifiera/{UUID_IN_PATH}"
        )
        ((msg, _, _),) = self.send()
        body = msg.get_content()
        for part in (
            "Knappen syns inte",
            "Sida: /stamboken/verifiera/[uuid]",
            "Pekade på: knappen [uuid]",
            f"Konto: {user.id}",
            "Svar önskas till: Medlem Test medlem@example.org",
            "https://github.com/gotlandskaninen/stamboken-drift/issues/45",
        ):
            self.assertIn(part, body)
        self.assertNotIn(UUID_IN_PATH, body)
        self.assertNotIn("Inte på tavlan", body)
        self.assertEqual(msg["Reply-To"], "medlem@example.org")

    def test_logged_in_on_a_public_page_replies_to_the_typed_address_only(self):
        user = da.register_user("medlem@example.org", "pass", fullname="Medlem Test")
        self.submit(user_id=user.id, contact=False, email="annan@example.org")
        ((msg, _, _),) = self.send()
        body = msg.get_content()
        self.assertIn("Svar önskas till: annan@example.org", body)
        self.assertIn(f"Konto: {user.id}", body)
        self.assertNotIn("Medlem Test", body)
        self.assertNotIn("medlem@example.org", body)
        self.assertEqual(msg["Reply-To"], "annan@example.org")

    def test_no_contact_gives_only_the_account_id_and_the_default_reply_to(self):
        user = da.register_user("medlem@example.org", "pass", fullname="Medlem Test")
        self.submit(user_id=user.id)
        ((msg, _, _),) = self.send()
        body = msg.get_content()
        self.assertIn(f"Konto: {user.id}", body)
        self.assertNotIn("Svar önskas", body)
        self.assertNotIn("medlem@example.org", body)
        self.assertEqual(msg["Reply-To"], settings.mail.sender)

    def test_not_on_the_board_comes_first(self):
        self.submit(repo=0, tavla=0)
        ((msg, _, _),) = self.send()
        self.assertTrue(msg.get_content().startswith("Inte på tavlan, lägg till den"))

    def test_images_are_attachments_and_reply_to_is_the_member(self):
        first, second = _jpeg("red"), _jpeg("blue")
        self.submit(images=[first, second], email="svar@example.org")
        ((msg, _, _),) = self.send()
        files = [(p.get_filename(), p.get_content_type(), p.get_content()) for p in msg.iter_attachments()]
        self.assertEqual(files, [("bild-0.jpg", "image/jpeg", first), ("bild-1.jpg", "image/jpeg", second)])
        self.assertEqual(msg["Reply-To"], "svar@example.org")
        self.assertIn("Bilder: 2 bifogade", msg.get_body(("plain",)).get_content())

    def test_missing_folder_builds_nothing(self):
        row_id = mail.enqueue_mail(
            "tyck_till.inskick", "tyck_till", 0, {"inskick": self.id.int, "issue": 1, "repo": 0, "tavla": 1}
        )
        self.assertEqual(self.send(), [])
        row = db.MailMessage.get_by_id(row_id)
        self.assertEqual((row.status, row.last_error), ("cancelled", "mejlet är inte längre aktuellt"))
