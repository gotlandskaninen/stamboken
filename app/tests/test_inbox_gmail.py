"""
The intake queue's Gmail reader (docs/inkorg-gmail.md) against an in-memory Gmail: the client, the startup
guard and the consent command. Synthetic messages and example.org addresses only; nothing reaches Google.

isort:skip_file
"""

import base64
import errno
import io
import os
import time
from datetime import date, timedelta
from email.message import EmailMessage
from email.utils import make_msgid
from unittest import mock

import peewee
import requests
import utils.database as db
import utils.inbox as inbox
import utils.inbox_gmail as inbox_gmail
import utils.inbox_purge as purge
import utils.mail as mail
import utils.settings as settings
from PIL import Image
from utils.gmail import Gmail, HistoryTooOld

from tests.inbox_fixtures import APP, InboxTest, encoded, photo
from tests.test_mail_queue import HOST, MailTest

# Token-shaped values are built from parts so that they are plainly synthetic.
FAKE_SECRET = "-".join(("synthetic", "client", "secret"))
FAKE_TOKEN = "-".join(("synthetic", "refresh", "token"))


class _Response:
    def __init__(self, status, body=None):
        self.status_code, self.body = status, body

    @property
    def content(self):
        return b"{}" if self.body is not None else b""

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class FakeGmail:
    """Gmail's REST API in memory, as utils.gmail calls it: a session whose `request` answers each call."""

    def __init__(self):
        self.messages = {}  # id -> {"raw": bytes, "labelIds": [...], "internalDate": str}
        self.labels = {"INBOX": "INBOX", "TRASH": "TRASH", "SPAM": "SPAM"}  # name -> id
        self.history = []  # (history id, message id), messageAdded to INBOX
        self.history_id = 1000
        self.oldest_history = 0  # a startHistoryId below this is too old: 404
        self.failures = []  # (method, path suffix): the next matching call fails with 500
        self.calls = []

    def deliver(self, message, labels=("INBOX",)):
        """A message arrives; returns its Gmail id."""
        message_id = f"g{len(self.messages) + 1:04d}"
        raw = message if isinstance(message, bytes) else message.as_bytes()
        self.messages[message_id] = {"raw": raw, "labelIds": list(labels), "internalDate": "1763100000000"}
        self.history_id += 1
        if "INBOX" in labels:
            self.history.append((self.history_id, message_id))
        return message_id

    def labelled(self, message_id, name):
        return self.labels.get(name) in self.messages[message_id]["labelIds"]

    def request(self, method, url, params=None, json=None, timeout=None):
        path = url.split("/users/me/", 1)[1]
        self.calls.append((method, path))
        for failure in self.failures:
            if failure[0] == method and path.endswith(failure[1]):
                self.failures.remove(failure)
                return _Response(500, {"error": "fail"})
        params = params or {}
        if path == "profile":
            return _Response(200, {"historyId": str(self.history_id)})
        if path == "history":
            start = int(params["startHistoryId"])
            if start < self.oldest_history:
                return _Response(404, {"error": "too old"})
            added = [{"messagesAdded": [{"message": {"id": m}}]} for h, m in self.history if h > start]
            return _Response(200, {"history": added, "historyId": str(self.history_id)})
        if path == "messages":
            label, hidden = params["labelIds"], {"SPAM", "TRASH"}
            found = [
                m
                for m, f in self.messages.items()
                if label in f.get("labelIds", []) and not hidden & {*f.get("labelIds", [])}
            ]
            return _Response(200, {"messages": [{"id": m} for m in reversed(found)]})  # newest first, as Gmail
        if path == "labels" and method == "GET":
            return _Response(200, {"labels": [{"id": i, "name": n} for n, i in self.labels.items()]})
        if path == "labels":
            self.labels[json["name"]] = f"Label_{len(self.labels)}"  # an id that is not the name
            return _Response(200, {"id": self.labels[json["name"]], "name": json["name"]})
        message_id, _, action = path.removeprefix("messages/").partition("/")
        found = self.messages.get(message_id)
        if found is None:
            return _Response(404, {"error": "not found"})
        if action == "modify":
            found["labelIds"] = [i for i in found["labelIds"] if i not in json["removeLabelIds"]]
            found["labelIds"] += [i for i in json["addLabelIds"] if i not in found["labelIds"]]
            return _Response(200, {"id": message_id})
        if action == "trash":
            found["labelIds"] = [i for i in found["labelIds"] if i != "INBOX"] + ["TRASH"]
            return _Response(200, {"id": message_id})
        raw = base64.urlsafe_b64encode(found["raw"]).rstrip(b"=").decode()  # Gmail leaves out the padding
        return _Response(200, {"id": message_id, **found, "raw": raw})


SENDER = "uppfodare@example.org"
PASS = f"spf=pass (google.com: domain of {SENDER} designates a server as permitted sender) smtp.mailfrom={SENDER}"


def message(
    sender=f"Test Uppfödare <{SENDER}>", subject="Intyg", body="Hej! Här är intygen.", files=(), auth=PASS, **headers
):
    """A synthetic mail as Gmail stores it: the receiving server's Authentication-Results on top."""
    msg = EmailMessage()
    if auth is not None:
        msg["Authentication-Results"] = f"mx.google.com; {auth}"
    msg["From"] = sender
    msg["To"] = "stamboken@example.org"
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="example.org")
    for name, value in headers.items():
        msg[name.replace("_", "-")] = value
    msg.set_content(body)
    for name, mime, data in files:
        maintype, subtype = mime.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg


class GmailTest(InboxTest, MailTest):
    def setUp(self):
        super().setUp()
        self.fake = FakeGmail()
        self.gmail = Gmail(self.fake)

    def read(self):
        with APP.app_context():  # as the scheduler's job runs it
            inbox_gmail.run(self.gmail)

    def items(self):
        return list(db.InboxItem.select().order_by(db.InboxItem.id))

    def done(self, gmail_id):
        """Labelled "Inläst" and in the trash."""
        labels = self.fake.messages[gmail_id]["labelIds"]
        return self.fake.labelled(gmail_id, "Inläst") and "TRASH" in labels and "INBOX" not in labels

    def sync(self):
        return db.GmailSync.get_by_id(1)

    def holder(self, herd, address=SENDER, first_name="Test"):
        """The herd's holder in the member register: the main member of the membership that owns it."""
        membership = db.Membership.create(member_number=900 + herd.id)
        member = db.Member.create(first_name=first_name, last_name="Innehavare", email=address, membership=membership)
        db.Herd.update(membership=membership).where(db.Herd.id == herd.id).execute()
        return member

    def our_mail(self, item, kind="inlasning.klar"):
        """The Message-ID of a mail of ours about the item, as a reply's In-Reply-To carries it."""
        row_id = mail.enqueue_mail(kind, "user", self.owner.id, {"item_id": item.id}, ref=("inbox_item", item.id))
        return mail.message_id(row_id)

    def waiting(self):
        """An upload of G1 that the helper asked its breeder about."""
        item = self.item(0)
        inbox.take(item, self.helper, over=False)
        inbox._set_state(item, "vantar_uppfodare")
        item.save()
        return item


REPORT = """\
From: Mail Delivery Subsystem <mailer-daemon@example.org>
To: stamboken@example.org
Subject: Delivery Status Notification (Failure)
Auto-Submitted: auto-replied
MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status; boundary="gr"

--gr
Content-Type: text/plain; charset="utf-8"

Mejlet till mottagare@example.org kom inte fram.

--gr
Content-Type: message/delivery-status

Reporting-MTA: dns; relay.example.org

Final-Recipient: rfc822; mottagare@example.org
Action: failed
Status: 5.1.1
Diagnostic-Code: smtp; 550 5.1.1 <mottagare@example.org>: user unknown

--gr
Content-Type: {part}

Message-ID: {message_id}
From: stamboken@example.org
To: mottagare@example.org
Subject: Vi har fått dina bilder

{body}
--gr--
"""


def report(message_id, part="message/rfc822"):
    body = "Hej!\n" if part == "message/rfc822" else ""
    return REPORT.format(part=part, message_id=message_id, body=body).replace("\n", "\r\n").encode()


class TestSorting(GmailTest):
    def test_a_bounce_marks_our_mail_bounced_and_makes_no_item(self):
        for part in ("message/rfc822", "text/rfc822-headers"):
            with self.subTest(part=part):
                row_id = self.queue()
                gmail_id = self.fake.deliver(report(mail.message_id(row_id), part))
                self.read()
                row = self.row(row_id)
                self.assertEqual(row.status, "bounced")
                self.assertIn("5.1.1", row.last_error)
                self.assertNotIn("@", row.last_error)
                self.assertEqual(self.items(), [])
                self.assertEqual(db.GmailProcessed.get_by_id(gmail_id).kind, "bounce")
                self.assertTrue(self.done(gmail_id))

    def test_a_bounce_of_another_environments_mail_touches_nothing(self):
        row_id = self.queue()
        other = mail.message_id(row_id).replace(HOST, "demo.example.org")
        gmail_id = self.fake.deliver(report(other))
        self.read()
        self.assertEqual(self.row(row_id).status, "queued")
        self.assertEqual(self.items(), [])
        self.assertIsNone(db.GmailProcessed.get_or_none(db.GmailProcessed.gmail_message_id == gmail_id))
        self.assertTrue(self.fake.labelled(gmail_id, "Demo"))
        self.assertIn("INBOX", self.fake.messages[gmail_id]["labelIds"])

    def test_a_bounce_on_no_mail_of_ours_becomes_an_item(self):
        gmail_id = self.fake.deliver(report("<CAsomething@mail.example.org>"))
        self.read()
        (item,) = self.items()
        self.assertEqual(item.kind, "meddelande")
        self.assertIn("kom inte fram", item.message)
        self.assertTrue(self.done(gmail_id))

    def test_an_automatic_answer_is_ignored(self):
        for header in ({"Auto-Submitted": "auto-replied"}, {"X-Autoreply": "yes"}, {"Precedence": "auto_reply"}):
            with self.subTest(header=header):
                gmail_id = self.fake.deliver(message(subject="Frånvaro", **header))
                self.read()
                self.assertEqual(self.items(), [])
                self.assertEqual(db.GmailProcessed.get_by_id(gmail_id).kind, "ignored")
                self.assertTrue(self.done(gmail_id))

    def test_a_reply_to_another_environments_mail_is_labelled_demo_and_nothing_else(self):
        item = self.waiting()
        other = self.our_mail(item).replace(HOST, "demo.example.org")
        gmail_id = self.fake.deliver(message(In_Reply_To=other, References=other))
        self.read()
        self.assertEqual(self.items(), [item])
        self.assertTrue(self.fake.labelled(gmail_id, "Demo"))
        self.assertFalse(self.fake.labelled(gmail_id, "Inläst"))
        self.assertIsNone(db.GmailProcessed.get_or_none(db.GmailProcessed.gmail_message_id == gmail_id))

    def test_an_authenticated_reply_from_the_holder_goes_on_the_item(self):
        self.holder(self.herds[0])
        item = self.waiting()
        self.fake.deliver(
            message(subject=f"Re: Fråga (ärende {item.id})", body="Det är G1-2112.", In_Reply_To=self.our_mail(item))
        )
        self.read()
        self.assertEqual(self.items(), [item])
        self.assertEqual(self.reload(item).state, "tagen")
        (event,) = item.events.where(db.InboxEvent.kind == "svar")
        self.assertEqual(event.detail["text"], "Det är G1-2112.")
        (notice,) = db.Notice.select().where(db.Notice.kind == "svar")
        self.assertEqual((notice.user_id, notice.item_id), (self.helper.id, item.id))

    def test_a_reply_to_an_incomplete_item_returns_it_and_restarts_its_year(self):
        self.holder(self.herds[0])
        item = self.item(0)
        inbox.take(item, self.helper, over=False)
        inbox.change_state(item, self.helper, "ofullstandig", note="Pappersintyget saknas")
        year_ago = inbox.now() - inbox.months(13)
        db.InboxItem.update(received_at=year_ago).where(db.InboxItem.id == item.id).execute()
        (asked,) = db.MailMessage.select().where(db.MailMessage.kind == "inlasning.ofullstandig")
        files = [("intyg.jpg", JPEG, encoded(photo()))]
        self.fake.deliver(message(body="Här är det.", files=files, In_Reply_To=mail.message_id(asked.id)))
        self.read()
        self.assertEqual(self.items(), [item])
        self.assertEqual(self.reload(item).state, "tagen")
        (notice,) = db.Notice.select().where(db.Notice.kind == "svar")
        self.assertEqual(notice.user_id, self.helper.id)

        item = self.reload(item)
        inbox.change_state(item, self.helper, "ofullstandig", note="Beviset saknas också")
        self.assertEqual(purge.purge_incomplete(inbox.now()), 0)  # a year from the answer, not from coming in
        self.assertEqual(purge.remind_incomplete(inbox.now()), 0)
        self.assertEqual(len(self.reload(item).documents), 2)  # the photo the sender supplied stays
        later = inbox.now() + inbox.months(12) + timedelta(days=1)
        self.assertEqual(purge.remind_incomplete(later), 1)
        self.assertEqual(purge.purge_incomplete(later), 1)

    def test_a_reply_read_twice_gives_one_event_and_one_notice(self):
        self.holder(self.herds[0])
        item = self.waiting()
        gmail_id = self.fake.deliver(message(In_Reply_To=self.our_mail(item)))
        self.read()
        self.fake.messages[gmail_id]["labelIds"] = ["INBOX"]
        db.GmailSync.update(history_id=None).execute()
        self.read()
        self.assertEqual(item.events.where(db.InboxEvent.kind == "svar").count(), 1)
        self.assertEqual(db.Notice.select().where(db.Notice.kind == "svar").count(), 1)

    def test_a_forged_reply_becomes_a_new_item_pointing_at_the_case(self):
        self.holder(self.herds[0])
        stranger = "annan@example.net"
        cases = {
            "unauthenticated": message(auth="spf=fail smtp.mailfrom=" + SENDER),
            "no results": message(auth=None),
            "unrelated sender": message(
                sender=stranger, auth=f"spf=pass smtp.mailfrom={stranger}; dkim=pass header.i=@example.net"
            ),
            "pass for another domain": message(auth="spf=pass smtp.mailfrom=bounce@example.net"),
        }
        for name, forged in cases.items():
            with self.subTest(name):
                item = self.waiting()
                forged["In-Reply-To"] = self.our_mail(item)
                self.fake.deliver(forged)
                self.read()
                new = self.items()[-1]
                self.assertNotEqual(new.id, item.id)
                self.assertEqual(new.events.get().detail["maybe_item"], item.id)
                self.assertEqual(self.reload(item).state, "vantar_uppfodare")
                self.assertEqual(item.events.where(db.InboxEvent.kind == "svar").count(), 0)

    def test_the_case_number_in_the_subject_counts_only_for_a_related_sender(self):
        self.holder(self.herds[0])
        item = self.waiting()
        stranger = "annan@example.net"
        self.fake.deliver(
            message(sender=stranger, subject=f"Re: (ärende {item.id})", auth=f"spf=pass smtp.mailfrom={stranger}")
        )
        self.fake.deliver(message(subject=f"Re: Fråga om intyget (ärende {item.id})"))
        self.read()
        new = self.items()[-1]
        self.assertEqual(new.events.get().detail["maybe_item"], item.id)
        self.assertEqual(item.events.where(db.InboxEvent.kind == "svar").count(), 1)
        self.assertEqual(self.reload(item).state, "tagen")

    def test_a_reply_to_a_closed_item_becomes_a_new_item(self):
        self.holder(self.herds[0])
        item = self.waiting()
        inbox.change_state(item, self.helper, "skrap")
        self.fake.deliver(message(In_Reply_To=self.our_mail(item)))
        self.read()
        self.assertEqual(self.items()[-1].events.get().detail["maybe_item"], item.id)


JPEG = "image/jpeg"


class TestItemsFromMail(GmailTest):
    def documents(self, item):
        return list(item.documents.order_by(db.InboxDocument.id))

    def notified(self):
        return sorted(n.user_id for n in db.Notice.select().where(db.Notice.kind == "ny_post"))

    def test_a_mail_with_two_images_is_one_item_with_two_documents_in_the_senders_herd(self):
        holder = self.holder(self.herds[0])
        files = [("a.jpg", JPEG, encoded(photo())), ("b.png", "image/png", encoded(photo(seed=2), "PNG"))]
        self.fake.deliver(message(sender=f"Test Uppfödare <{SENDER.upper()}>", files=files))
        self.read()
        (item,) = self.items()
        self.assertEqual(item.kind, "mail")
        self.assertEqual(
            (item.herd_id, item.genebank_id, item.member_id), (self.herds[0].id, self.genebanks[0].id, holder.id)
        )
        documents = self.documents(item)
        self.assertEqual(len(documents), 2)
        for document in documents:
            with Image.open(self.stored(document)) as image:
                self.assertEqual(image.format, "JPEG")
        self.assertEqual(item.events.get().detail, {"documents": 2})
        self.assertEqual(self.notified(), sorted([self.manager.id, self.helper.id]))  # Gotland's workers

    def test_an_unknown_sender_is_seen_by_every_queue_worker(self):
        self.fake.deliver(message(sender="okand@example.net", body="Var skickar jag intyget?"))
        self.read()
        (item,) = self.items()
        self.assertEqual((item.kind, item.genebank_id, item.herd_id, item.member_id), ("meddelande", None, None, None))
        self.assertEqual(item.message, "Var skickar jag intyget?")
        self.assertEqual(self.notified(), sorted(u.id for u in inbox.queue_workers(None)))
        self.assertIn(self.mellerud_helper.id, self.notified())

    def test_files_too_big_too_many_or_of_another_type_are_named_and_not_stored(self):
        big = encoded(photo()) + b"\0" * (10 * 1024 * 1024)  # a JPEG by its first bytes, over 10 MB
        docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        files = [("stor.jpg", JPEG, big), ("brev.docx", docx, b"PK\x03\x04syntetisk")]
        files += [(f"{n}.jpg", JPEG, encoded(photo((600, 800), seed=n))) for n in range(11)]
        self.fake.deliver(message(files=files))
        self.read()
        (item,) = self.items()
        self.assertEqual(len(self.documents(item)), 10)
        self.assertEqual(item.events.get().detail["not_saved"], ["stor.jpg", "brev.docx", "10.jpg"])

    def test_logos_and_tracking_pixels_are_not_documents(self):
        files = [
            ("pixel.png", "image/png", encoded(Image.new("RGB", (1, 1), (255, 255, 255)), "PNG")),
            ("logo.png", "image/png", encoded(photo((400, 120)), "PNG")),
            ("intyg.jpg", JPEG, encoded(photo())),
        ]
        self.fake.deliver(message(files=files))
        self.read()
        (item,) = self.items()
        self.assertEqual(len(self.documents(item)), 1)
        self.assertEqual(item.events.get().detail["not_saved"], ["pixel.png", "logo.png"])

    def test_exif_is_gone_and_an_inline_photo_counts(self):
        exif = Image.Exif()
        exif[0x0110] = "SecretCam"  # camera model
        exif.get_ifd(0x8825)[2] = (57.0, 30.0, 0.0)  # GPS latitude
        msg = message(body="Se bilden")
        msg.add_attachment(encoded(photo(), exif=exif), maintype="image", subtype="jpeg", disposition="inline")
        self.fake.deliver(msg)
        self.read()
        (document,) = self.documents(self.items()[0])
        with open(self.stored(document), "rb") as stored:
            data = stored.read()
        self.assertNotIn(b"Exif", data)
        self.assertNotIn(b"SecretCam", data)

    def test_an_html_only_mail_becomes_text(self):
        msg = message()
        msg.set_content(
            "<html><head><style>p {color: red}</style></head><body><p>Hej!</p>"
            "<p>Intyget &amp; beviset<br>kommer snart</p><script>x()</script></body></html>",
            subtype="html",
        )
        self.fake.deliver(msg)
        self.read()
        self.assertEqual(self.items()[0].message, "Hej!\nIntyget & beviset\nkommer snart")

    def test_a_hostile_html_body_is_read_in_bounded_time(self):
        for name, body in (
            ("unclosed tags", "<" * 1024 * 1024),
            ("unclosed comments", "<!--" * 256 * 1024),
            ("unclosed script", "<script>" + "x<" * 512 * 1024),
            ("a head left open", "<html><head><title>x</title><body><p>Hej</p>" + "<b>" * 300_000),
        ):
            with self.subTest(name):
                msg = message()
                msg.set_content(body, subtype="html")
                started = time.monotonic()
                text = inbox_gmail._text(msg)
                self.assertLess(time.monotonic() - started, 0.5)
                self.assertLessEqual(len(text or ""), inbox_gmail.MAX_TEXT)
                if name == "a head left open":
                    self.assertEqual(text, "Hej")

    def test_a_reply_brings_its_photos_as_new_documents_on_the_item(self):
        self.holder(self.herds[0])
        item = self.waiting()
        self.fake.deliver(message(files=[("ny.jpg", JPEG, encoded(photo()))], In_Reply_To=self.our_mail(item)))
        self.read()
        self.assertEqual(self.items(), [item])
        added = self.documents(item)[-1]
        self.assertEqual(len(self.documents(item)), 2)
        self.assertEqual(item.events.where(db.InboxEvent.kind == "svar").get().detail["documents"], [added.id])

    def test_a_message_that_fails_leaves_no_files(self):
        self.fake.deliver(message(files=[("a.jpg", JPEG, encoded(photo()))]))
        with mock.patch.object(inbox_gmail, "_processed", side_effect=RuntimeError("fel")):
            self.read()
        self.assertEqual(self.items(), [])
        self.assertEqual([name for _, _, names in os.walk(self.folder) for name in names], [])


class TestReceipt(GmailTest):
    def receipts(self):
        return list(
            db.MailMessage.select().where(db.MailMessage.kind == "inlasning.kvitto").order_by(db.MailMessage.id)
        )

    def photos(self, count=1):
        return [(f"{n}.jpg", JPEG, encoded(photo(seed=n))) for n in range(count)]

    def test_a_mail_with_images_gets_a_receipt_with_the_case_number(self):
        self.fake.deliver(message(files=self.photos(2)))
        self.read()
        (item,) = self.items()
        (row,) = self.receipts()
        self.assertEqual((row.recipient_kind, row.recipient_id), ("inbox_sender", item.id))
        self.assertEqual(row.params, {"item_id": item.id, "images": 2})
        self.assertNotIn("@", row.dedupe_key)
        relay = self.relay()
        mail.send_pending()
        ((msg, _, to),) = relay.sent
        self.assertEqual(to, [SENDER])
        self.assertEqual(msg["Subject"], f"Vi har fått dina bilder (ärende {item.id})")
        self.assertIn("Vi har fått 2 bilder. Genbanksansvarig lägger in dem", msg.get_content())

    def test_no_receipt_without_an_spf_or_dkim_pass_nor_without_images(self):
        self.fake.deliver(message(files=self.photos(), auth=f"spf=softfail smtp.mailfrom={SENDER}"))
        self.fake.deliver(message(files=self.photos(), auth="spf=pass smtp.mailfrom=bounce@example.net"))
        self.fake.deliver(message(body="Bara text"))
        self.read()
        self.assertEqual(len(self.items()), 3)
        self.assertEqual(self.receipts(), [])

    def test_at_most_one_receipt_a_day_to_a_sender(self):
        self.fake.deliver(message(files=self.photos()))
        self.fake.deliver(message(sender=SENDER.upper(), files=self.photos()))
        self.read()
        self.assertEqual(len(self.receipts()), 1)
        tomorrow = inbox.now() + timedelta(days=1)
        self.fake.deliver(message(files=self.photos()))
        with mock.patch.object(inbox, "now", return_value=tomorrow):
            self.read()
        self.assertEqual(len(self.receipts()), 2)


class TestSenderAddress(GmailTest):
    def mailed_item(self, **kwargs):
        self.fake.deliver(message(files=[("a.jpg", JPEG, encoded(photo()))], **kwargs))
        self.read()
        return self.items()[-1]

    def test_the_address_stays_until_the_final_mail_is_sent_and_goes_after(self):
        item = self.mailed_item()
        inbox.take(item, self.helper, over=False)
        inbox.update_document(item, item.documents.get(), self.helper, {"dismissed": True})
        self.assertEqual(self.reload(item).state, "klar")
        (done,) = db.MailMessage.select().where(db.MailMessage.kind == "inlasning.klar")
        self.assertEqual((done.recipient_kind, done.recipient_id), ("inbox_sender", item.id))
        inbox_gmail.release_senders()
        self.assertEqual(self.reload(item).sender_address, SENDER)  # the receipt and the final mail still wait
        relay = self.relay()
        mail.send_pending()
        self.assertEqual([to for _, _, to in relay.sent], [[SENDER], [SENDER]])
        self.assertNotIn("/stamboken/inskick", relay.sent[-1][0].get_content())  # no account to see it in
        inbox_gmail.release_senders()
        self.assertIsNone(self.reload(item).sender_address)
        self.assertEqual({r.address_hash for r in db.MailMessage.select()}, {None})  # forgotten

    def test_an_item_closed_with_nothing_on_its_way_drops_it_at_once(self):
        item = self.mailed_item(auth=None)  # no receipt
        inbox.take(item, self.helper, over=False)
        inbox.change_state(item, self.helper, "skrap")
        self.assertIsNone(self.reload(item).sender_address)

    def test_thirty_days_after_closing_it_goes_whatever_waits(self):
        item = self.mailed_item()
        inbox.take(item, self.helper, over=False)
        inbox.change_state(item, self.helper, "skrap")
        self.assertEqual(self.reload(item).sender_address, SENDER)  # the receipt waits
        inbox_gmail.release_senders(at=inbox.now() + timedelta(days=31))
        self.assertIsNone(self.reload(item).sender_address)

    def test_mail_goes_back_only_to_a_sender_gmail_authenticated(self):
        """A forged From must never make the queue mail its victim: no klar, ofullstandig or paminnelse."""
        forged = self.mailed_item(auth=f"spf=fail smtp.mailfrom={SENDER}")
        genuine = self.mailed_item()
        self.login("hjalp")
        for item, expected in ((forged, False), (genuine, True)):
            with self.subTest(authenticated=expected):
                self.assertIs(self.reload(item).sender_authenticated, expected)
                listed = self.client.get(f"/api/v2/inkorg/{item.id}").get_json()
                self.assertIs(listed["sender_authenticated"], expected)
                inbox.take(item, self.helper, over=False)
                inbox.change_state(item, self.helper, "ofullstandig", note="Pappersintyget saknas")
                db.InboxItem.update(received_at=inbox.now() - inbox.months(12)).where(
                    db.InboxItem.id == item.id
                ).execute()
                purge.remind_incomplete(inbox.now())
                inbox.change_state(item, self.helper, "tagen")
                inbox.update_document(item, item.documents.get(), self.helper, {"dismissed": True})
                kinds = {
                    m.kind
                    for m in db.MailMessage.select().where(
                        (db.MailMessage.recipient_kind == "inbox_sender") & (db.MailMessage.recipient_id == item.id)
                    )
                }
                sent_back = {"inlasning.ofullstandig", "inlasning.paminnelse", "inlasning.klar"}
                self.assertEqual(kinds & sent_back, sent_back if expected else set())
        upload = self.item(0)
        self.assertIsNone(self.client.get("/api/v2/inkorg?scope=alla").get_json()["items"][-1]["sender_authenticated"])
        self.assertEqual(self.client.get("/api/v2/inkorg?scope=alla").get_json()["items"][-1]["id"], upload.id)

    def test_an_open_item_keeps_it(self):
        item = self.mailed_item(auth=None)
        inbox_gmail.release_senders(at=inbox.now() + timedelta(days=400))
        self.assertEqual(self.reload(item).sender_address, SENDER)


class TestAskBreeder(GmailTest):
    ASKED = "innehavare@example.org"

    def setUp(self):
        super().setUp()
        self.asked = self.holder(self.herds[0], address=self.ASKED)
        self.login("owner")
        resp = self.upload()  # one photo, 1200 x 1600
        self.assertEqual(resp.status_code, 201, resp.get_json())
        self.item_id = resp.get_json()["item"]["id"]
        self.document = db.InboxDocument.get(db.InboxDocument.item == self.item_id)
        inbox.take(db.InboxItem.get_by_id(self.item_id), self.helper, over=False)
        self.login("hjalp")

    def ask(self, **body):
        return self.client.post(f"/api/v2/inkorg/{self.item_id}/fraga", json=body)

    def questions(self):
        return list(db.MailMessage.select().where(db.MailMessage.kind == "inlasning.fraga"))

    def test_the_handler_asks_the_holder_with_a_part_of_the_photo_and_the_item_waits(self):
        db.InboxDocument.update(rotation=90).where(db.InboxDocument.id == self.document.id).execute()
        crop = {"x": 0, "y": 0, "w": 0.5, "h": 0.25}
        resp = self.ask(text="  Står det G1-2112 eller G1-2113?  ", document=self.document.id, crop=crop)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json()["state"], "vantar_uppfodare")
        (event,) = db.InboxEvent.select().where(db.InboxEvent.kind == "fraga")
        self.assertEqual(event.user_id, self.helper.id)
        self.assertEqual(
            event.detail,
            {"text": "Står det G1-2112 eller G1-2113?", "document": self.document.id, "rotation": 90, "crop": crop},
        )
        (row,) = self.questions()
        self.assertEqual((row.recipient_kind, row.recipient_id), ("member", self.asked.id))
        self.assertEqual(row.params, {"item_id": self.item_id, "event_id": event.id})
        relay = self.relay()
        mail.send_pending()
        ((msg, _, to),) = relay.sent
        self.assertEqual(to, [self.ASKED])
        self.assertTrue(msg["Subject"].endswith(f"(ärende {self.item_id})"))
        self.assertIn("Står det G1-2112 eller G1-2113?", msg.get_body(("plain",)).get_content())
        (attachment,) = msg.iter_attachments()
        with Image.open(io.BytesIO(attachment.get_content())) as part:
            self.assertEqual((part.format, part.size), ("JPEG", (800, 300)))  # the turned photo is 1600 x 1200

    def test_who_may_ask_and_when(self):
        self.login("man")  # in the queue, but not the item's handler
        self.assertEqual(self.ask(text="Fråga").status_code, 409)
        self.login("owner")  # the uploader does not work in the queue
        self.assertEqual(self.ask(text="Fråga").status_code, 403)
        self.client.get("/api/logout")
        self.assertEqual(self.ask(text="Fråga").status_code, 401)
        self.login("hjalp")
        for body in (
            {},
            {"text": "   "},
            {"text": "x" * 2001},
            {"text": "Fråga", "crop": {"x": 0, "y": 0, "w": 1, "h": 1}},
            {"text": "Fråga", "document": self.document.id, "crop": {"x": 0.5, "y": 0, "w": 0.6, "h": 1}},
        ):
            with self.subTest(body=body):
                self.assertEqual(self.ask(**body).status_code, 400)
        other = self.item(2)
        self.assertEqual(
            self.ask(
                text="Fråga", document=other.documents.get().id, crop={"x": 0, "y": 0, "w": 1, "h": 1}
            ).status_code,
            404,
        )
        db.Herd.update(membership=None).where(db.Herd.id == self.herds[0].id).execute()
        self.assertEqual(self.ask(text="Fråga").status_code, 409)  # no holder to ask
        db.Herd.update(membership=self.asked.membership_id).where(db.Herd.id == self.herds[0].id).execute()
        self.assertEqual(self.ask(text="Fråga").status_code, 200)
        self.assertEqual(self.ask(text="Fråga igen").status_code, 409)  # it already waits
        self.assertEqual(len(self.questions()), 1)
        self.assertEqual(db.InboxItem.get_by_id(self.item_id).state, "vantar_uppfodare")

    def test_the_answer_of_the_one_asked_comes_back_to_the_handler(self):
        self.assertEqual(self.ask(text="Vilken färg har kaninen?").status_code, 200)
        (question,) = self.questions()
        db.Member.update(end_date=date.today()).where(db.Member.id == self.asked.id).execute()  # no longer the holder
        dkim = "dkim=pass header.i=@example.org header.s=s1 header.b=AbC1"
        self.fake.deliver(
            message(sender=self.ASKED, auth=dkim, body="Viltgrå.", In_Reply_To=mail.message_id(question.id))
        )
        self.read()
        item = db.InboxItem.get_by_id(self.item_id)
        self.assertEqual(item.state, "tagen")
        self.assertEqual(item.events.where(db.InboxEvent.kind == "svar").get().detail["text"], "Viltgrå.")
        (notice,) = db.Notice.select().where(db.Notice.kind == "svar")
        self.assertEqual(notice.user_id, self.helper.id)


class TestStatus(GmailTest):
    def status(self):
        resp = self.client.get("/api/v2/inkorg/status")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        return resp.get_json()["gmail"]

    def test_the_alarm_when_the_reader_stopped_or_failed(self):
        self.login("hjalp")
        with mock.patch.object(settings.gmail, "mode", "off"):
            self.assertEqual(self.status(), {"enabled": False, "last_run_at": None, "last_error": None, "alarm": False})
        with mock.patch.object(settings.gmail, "mode", "on"):
            self.assertTrue(self.status()["alarm"])  # never run
            self.read()
            self.assertFalse(self.status()["alarm"])
            self.assertIsNotNone(self.status()["last_run_at"])
            db.GmailSync.update(last_run_at=inbox.now() - timedelta(minutes=21)).execute()
            self.assertTrue(self.status()["alarm"])
            db.GmailSync.update(last_run_at=inbox.now(), last_error="g0001: ValueError").execute()
            self.assertEqual((self.status()["alarm"], self.status()["last_error"]), (True, "g0001: ValueError"))

    def test_only_for_those_working_the_queue(self):
        self.login("owner")
        self.assertEqual(self.client.get("/api/v2/inkorg/status").status_code, 403)


class TestAuthenticationResults(InboxTest):
    def check(self, *headers, sender=SENDER):
        msg = EmailMessage()
        for header in headers:
            msg["Authentication-Results"] = header
        return inbox_gmail.authenticated(msg, sender)

    def test_a_pass_for_the_senders_domain_counts(self):
        self.assertTrue(self.check(f"mx.google.com; {PASS}"))
        self.assertTrue(
            self.check("mx.google.com; dkim=pass header.i=@example.org header.s=s1 header.b=AbC1; spf=none")
        )
        self.assertTrue(self.check("mx.google.com; dkim=pass header.i=@mejl.example.org header.s=s1 header.b=x"))

    def test_only_the_topmost_header_counts(self):
        self.assertFalse(self.check(f"mx.google.com; spf=fail smtp.mailfrom={SENDER}", f"mx.google.com; {PASS}"))

    def test_the_header_must_be_googles(self):
        self.assertFalse(self.check(f"mx.example.org; {PASS}"))

    def test_a_pass_for_another_domain_or_text_in_a_comment_does_not_count(self):
        for header in (
            "mx.google.com; spf=pass smtp.mailfrom=bounce@example.net",
            "mx.google.com; dkim=pass header.i=@example.net header.s=s1; spf=fail smtp.mailfrom=x@example.org",
            "mx.google.com; spf=pass (domain of a smtp.mailfrom=example.org designates) smtp.mailfrom=x@example.net",
            'mx.google.com; spf=pass smtp.mailfrom="a;spf=pass smtp.mailfrom=example.org"@example.net',
            "mx.google.com; dmarc=pass header.from=example.org",
        ):
            with self.subTest(header):
                self.assertFalse(self.check(header))


class TestSync(GmailTest):
    def test_a_message_becomes_an_item_and_goes_to_the_trash(self):
        gmail_id = self.fake.deliver(message())
        self.read()
        (item,) = self.items()
        self.assertEqual((item.gmail_message_id, item.sender_address), (gmail_id, SENDER))
        self.assertEqual(item.message, "Hej! Här är intygen.")
        self.assertTrue(self.done(gmail_id))
        self.assertEqual(db.GmailProcessed.get_by_id(gmail_id).item_id, item.id)
        sync = self.sync()
        self.assertEqual((sync.history_id, sync.last_error), (str(self.fake.history_id), None))
        self.assertIsNotNone(sync.last_run_at)

    def test_the_same_message_read_twice_gives_one_item(self):
        gmail_id = self.fake.deliver(message())
        self.read()
        self.fake.messages[gmail_id]["labelIds"] = ["INBOX"]  # back in the inbox, unlabelled
        db.GmailSync.update(history_id=None).execute()  # and the whole inbox read again
        self.read()
        self.assertEqual(len(self.items()), 1)
        self.assertTrue(self.done(gmail_id))

    def test_a_crash_between_the_commit_and_the_labelling_only_labels_on_the_reread(self):
        gmail_id = self.fake.deliver(message(files=[("a.jpg", JPEG, encoded(photo()))]))
        self.fake.failures.append(("POST", f"messages/{gmail_id}/modify"))
        with self.assertRaises(requests.HTTPError):
            self.read()
        self.assertFalse(self.done(gmail_id))
        self.assertIsNone(self.sync().history_id)  # not moved on: the next run reads the same messages
        self.assertIn("HTTPError", self.sync().last_error)
        tables = (db.InboxItem, db.InboxDocument, db.InboxEvent, db.Notice, db.MailMessage)
        counts = [table.select().count() for table in tables]
        self.assertEqual(counts, [1, 1, 1, 4, 1])  # the item, its photo, "inkommen", all four workers told, a receipt
        self.read()
        self.assertEqual([table.select().count() for table in tables], counts)
        self.assertTrue(self.done(gmail_id))
        self.assertIsNone(self.sync().last_error)

    def test_history_too_old_reads_the_inbox_but_not_what_is_read_nor_spam(self):
        first = self.fake.deliver(message(subject="Först"))
        self.read()
        labelled = self.fake.deliver(message(subject="Redan inläst"))
        self.fake.messages[labelled]["labelIds"].append(self.fake.labels["Inläst"])
        self.fake.deliver(message(subject="Skräp"), labels=("SPAM",))
        new = self.fake.deliver(message(subject="Ny"))
        self.fake.oldest_history = self.fake.history_id + 1
        self.read()
        self.assertEqual([i.gmail_message_id for i in self.items()], [first, new])
        self.assertEqual(self.sync().history_id, str(self.fake.history_id))

    def flaky(self, bad, error):
        """read_message raising `error` for the message `bad`, as a poison message or a broken disk would."""
        real, calls = inbox_gmail.read_message, []

        def read(gmail_id, raw, received_at=None):
            if gmail_id == bad:
                calls.append(gmail_id)
                raise error
            return real(gmail_id, raw, received_at)

        return mock.patch.object(inbox_gmail, "read_message", read), calls

    def test_a_message_that_fails_three_runs_in_a_row_is_set_aside_and_never_stops_the_others(self):
        bad, good = self.fake.deliver(message(subject="Trasig")), self.fake.deliver(message(subject="Hel"))
        poison, calls = self.flaky(bad, ValueError(f"kunde inte läsa {SENDER}"))
        with poison:
            for run in (1, 2):
                self.read()
                self.assertFalse(self.fake.labelled(bad, "Fel vid inläsning"), run)  # not yet: it is read again
                self.assertEqual(db.GmailProcessed.get_by_id(bad).failures, run)
                self.assertEqual(self.sync().history_id, str(self.fake.history_id))  # the others go on
                error = self.sync().last_error
                self.assertIn(bad, error)
                self.assertNotIn("@", error)  # every queue worker sees it
            self.read()
            self.assertTrue(self.fake.labelled(bad, "Fel vid inläsning"))
            self.assertIn("INBOX", self.fake.messages[bad]["labelIds"])
            self.assertEqual((db.GmailProcessed.get_by_id(bad).kind, len(calls)), ("failed", 3))
            self.read()  # set aside: never read again, and the label keeps the alarm on
            self.assertEqual(len(calls), 3)
        self.assertEqual([i.gmail_message_id for i in self.items()], [good])
        self.assertEqual(self.sync().last_error, "1 mejl har etiketten Fel vid inläsning i brevlådan")
        self.fake.messages[bad]["labelIds"].append("TRASH")  # a human dealt with it
        self.read()
        self.assertIsNone(self.sync().last_error)

    def test_a_message_that_fails_once_is_read_by_the_next_run(self):
        gmail_id = self.fake.deliver(message())
        poison, _ = self.flaky(gmail_id, UnicodeError("trasig teckenkodning"))
        with poison:
            self.read()
        self.assertEqual(self.items(), [])
        self.read()  # history has moved on, but the count brings it back
        (item,) = self.items()
        self.assertEqual(db.GmailProcessed.get_by_id(gmail_id).kind, "item")
        self.assertTrue(self.done(gmail_id))

    def test_a_message_without_labels_is_skipped(self):
        bare, good = self.fake.deliver(message(subject="Utan etiketter")), self.fake.deliver(message())
        del self.fake.messages[bare]["labelIds"]  # Gmail leaves the key out
        self.read()
        self.assertEqual([i.gmail_message_id for i in self.items()], [good])
        self.assertEqual(self.sync().history_id, str(self.fake.history_id))

    def test_a_database_or_disk_error_stops_the_run_without_labelling_and_the_next_run_reads_it(self):
        self.read()  # the reader's row, with a history id
        for error in (peewee.OperationalError("server closed the connection"), OSError(errno.ENOSPC, "disk full")):
            with self.subTest(type(error).__name__):
                gmail_id = self.fake.deliver(message())
                before = self.sync().history_id
                broken, _ = self.flaky(gmail_id, error)
                with broken, self.assertRaises(type(error)):
                    self.read()
                self.assertEqual(self.sync().history_id, before)
                self.assertFalse(self.fake.labelled(gmail_id, "Fel vid inläsning"))
                self.assertIsNone(db.GmailProcessed.get_or_none(db.GmailProcessed.gmail_message_id == gmail_id))
                self.read()
                self.assertTrue(self.done(gmail_id))

    def test_a_nul_character_is_never_stored(self):
        files = [("in\x00tyg.docx", "application/octet-stream", b"PK\x03\x04syntetisk")]
        self.fake.deliver(message(body="Hej\x00 där", files=files))
        self.read()
        (item,) = self.items()
        self.assertEqual(item.message, "Hej där")
        self.assertEqual(item.events.get().detail["not_saved"], ["intyg.docx"])

    def test_labelled_read_but_not_trashed_gets_only_the_trash(self):
        gmail_id = self.fake.deliver(message())
        self.fake.failures.append(("POST", f"messages/{gmail_id}/trash"))
        with self.assertRaises(requests.HTTPError):
            self.read()
        self.assertTrue(self.fake.labelled(gmail_id, "Inläst"))
        self.assertIn("INBOX", self.fake.messages[gmail_id]["labelIds"])
        self.read()
        self.assertTrue(self.done(gmail_id))
        self.assertEqual(len(self.items()), 1)
        # Also when its row is long gone (60 days): the label says it was read.
        again = self.fake.deliver(message(subject="Gammal"))
        self.read()
        self.fake.messages[again]["labelIds"] = ["INBOX", self.fake.labels["Inläst"]]
        db.GmailProcessed.delete().execute()
        db.GmailSync.update(history_id=None).execute()
        self.read()
        self.assertTrue(self.done(again))
        self.assertEqual(len(self.items()), 2)


class TestClient(InboxTest):
    def setUp(self):
        super().setUp()
        self.fake = FakeGmail()
        self.gmail = Gmail(self.fake)

    def test_history_lists_what_came_to_the_inbox_since_the_id(self):
        first = self.fake.deliver(b"Subject: ett\r\n\r\nett\r\n")
        since = str(self.fake.history_id)
        second = self.fake.deliver(b"Subject: tva\r\n\r\ntva\r\n")
        self.fake.deliver(b"Subject: skrap\r\n\r\nskrap\r\n", labels=("SPAM",))
        self.assertEqual(self.gmail.added_since(since), ([second], str(self.fake.history_id)))
        self.assertEqual(self.gmail.labelled(), [first, second])

    def test_a_history_id_gmail_no_longer_has(self):
        self.fake.oldest_history = 5000
        with self.assertRaises(HistoryTooOld):
            self.gmail.added_since("1000")

    def test_message_decodes_the_raw_bytes_and_a_gone_one_is_none(self):
        raw = b"Subject: x\r\n\r\n" + "räksmörgås".encode() * 7 + b"\r\n"
        message_id = self.fake.deliver(raw)
        self.assertEqual(self.gmail.message(message_id)["raw"], raw)
        self.assertIsNone(self.gmail.message("finns-inte"))

    def test_a_label_is_looked_up_by_name_and_created_once(self):
        label = self.gmail.label("Inläst")
        self.assertNotEqual(label, "Inläst")
        self.assertEqual(Gmail(self.fake).label("Inläst"), label)
        self.assertEqual([c for c in self.fake.calls if c == ("POST", "labels")], [("POST", "labels")])


class TestStartupGuard(InboxTest):
    def test_guard(self):
        full = {"client_id": "id.example.org", "client_secret": FAKE_SECRET, "refresh_token": FAKE_TOKEN}
        empty = {"client_id": "", "client_secret": "", "refresh_token": ""}
        cases = [
            ("on", True, full, "s", True),  # the demo never reads the mailbox
            ("on", False, {**full, "refresh_token": ""}, "s", True),
            ("on", False, empty, "s", True),
            ("on", False, full, "", True),
            ("ja", False, full, "s", True),
            ("on", False, full, "s", False),
            ("off", True, empty, "", False),
        ]
        for mode, demo, credentials, secret, refused in cases:
            with (
                self.subTest(mode=mode, demo=demo, credentials=sorted(k for k, v in credentials.items() if v)),
                mock.patch.multiple(settings.gmail, mode=mode, **credentials),
                mock.patch.object(settings.service, "demo_instance", demo),
                mock.patch.object(settings.mail, "link_secret", secret),
            ):
                if refused:
                    with self.assertRaises(RuntimeError):
                        settings.refuse_unsafe_gmail_settings()
                else:
                    settings.refuse_unsafe_gmail_settings()


class TestConsent(InboxTest):
    def test_prints_the_url_and_only_the_refresh_token_on_stdout(self):
        answer = mock.Mock(ok=True, status_code=200, content=b"{}")
        answer.json.return_value = {"refresh_token": FAKE_TOKEN, "access_token": "x"}
        with (
            mock.patch.multiple(settings.gmail, client_id="id.example.org", client_secret=FAKE_SECRET),
            mock.patch("cli.gmail.requests.post", return_value=answer) as post,
        ):
            result = APP.test_cli_runner().invoke(
                args=["gmail", "consent"], input="http://127.0.0.1:8765/?code=4/syntetisk&scope=x\n"
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stdout.strip(), FAKE_TOKEN)
        self.assertNotIn(FAKE_TOKEN, result.stderr)
        self.assertIn("access_type=offline", result.stderr)
        self.assertIn("gmail.modify", result.stderr)
        sent = post.call_args.kwargs["data"]
        self.assertEqual((sent["code"], sent["grant_type"]), ("4/syntetisk", "authorization_code"))
        self.assertTrue(sent["code_verifier"])

    def test_refuses_without_the_client(self):
        with mock.patch.multiple(settings.gmail, client_id="", client_secret=""):
            result = APP.test_cli_runner().invoke(args=["gmail", "consent"])
        self.assertNotEqual(result.exit_code, 0)
