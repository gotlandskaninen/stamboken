#!/usr/bin/env python3
"""
"Lägg till kanin från intyget" in the report (step 4b, Task 4): the certificate's photo becomes a `kontroll` item, and
the rabbit is registered with the report actor's own right, bound to that photo. By a login and by a link without an
account. Synthetic photos and data only.

isort:skip_file
"""

import io
import os
import re
from datetime import date, datetime, timedelta
from datetime import time as clock
from unittest import mock

import blueprints.arsrapport as report_routes
import pypdfium2
import utils.arsrapport as arsrapport
import utils.database as db
import utils.inbox as inbox
import utils.inbox_interpreter as interpreter
import utils.inbox_purge as inbox_purge
import utils.mail as mail
import utils.report_code as report_code
import utils.settings as settings
from blueprints.individual_v2_create import NO_LITTER_NUMBER_REPORT
from herdbook import APP, limiter
from utils.inbox_proposal import build_proposal

from tests.arsrapport_fixtures import ArsrapportTest
from tests.inbox_fixtures import QUALITY, encoded, pdf, photo

NOW = datetime.combine(date(2026, 1, 15), clock(12), arsrapport.STOCKHOLM)
REPORT = "/besattning/G9001/2025"
OTHER = "/besattning/G9002/2025"


class AddRabbitTest(ArsrapportTest):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.multiple(settings.mail, link_secret="test-link-secret", link_hosts=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.at(NOW)
        self.round_ = self.round(2025)
        self.h = db.Herd.create(genebank=self.gotland, herd="G9001", herd_name="Testbesättning", is_active=True)
        self.h2 = db.Herd.create(genebank=self.gotland, herd="G9002", is_active=True)
        db.Herd.create(genebank=self.gotland, herd="GX1", is_active=True)
        self.owner.add_role("owner", self.h.id)
        self.code = report_code.issue_code(
            self.h, self.round_, self.main_member(self.h, "g9001@example.invalid"), now=arsrapport.now()
        )
        self.code2 = report_code.issue_code(
            self.h2, self.round_, self.main_member(self.h2, "g9002@example.invalid"), now=arsrapport.now()
        )
        self.doe, self.buck, self.doe2 = self.rabbits(self.h, 3)  # female, male, female
        self.other_doe = self.rabbits(self.h2, 1)[0]

    def open_link(self, code=None, client=None):
        token = mail.link_token("rapport", (code or self.code).id)
        response = (client or self.client).post("/api/v2/rapport/oppna", json={"token": token})
        self.assertEqual(response.status_code, 200)

    def upload_photo(self, path=REPORT, content=None, client=None, query_string=None):
        data = {"file": (io.BytesIO(content or encoded(photo())), "intyg.jpg")}
        return (client or self.client).post(
            f"/api/v2/arsrapport{path}/foto", data=data, content_type="multipart/form-data", query_string=query_string
        )

    def photo_item(self, path=REPORT, client=None):
        response = self.upload_photo(path, client=client)
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return response.get_json()["item_id"]

    def kit(self, item_id, path=REPORT, client=None, query_string=None, **fields):
        """A kit of doe and buck born in 2025: G9001's first litter of the year, so Stamboken gives G9001-2511."""
        body = {
            "item_id": item_id,
            "mother": self.doe.number,
            "father": self.buck.number,
            "birth_date": "2025-05-10",
            "litter_size": 5,
            "litter_size6w": 4,
            "paper_number": "G9001-2511",
            "paper_certificate": "P-2511",
            "sex": "female",
            "name": "Kulla",
            **fields,
        }
        return (client or self.client).post(f"/api/v2/arsrapport{path}/kanin", json=body, query_string=query_string)

    def kits(self):
        return db.Individual.select().where(db.Individual.origin_herd << [self.h.id, self.h2.id]).count() - 4

    def reload(self, item_id):
        return db.InboxItem.get_by_id(item_id)


class TestPhoto(AddRabbitTest):
    def test_upload_creates_kontroll_item_with_intyg_document(self):
        self.open_link()
        response = self.upload_photo()
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        data = response.get_json()
        item = self.reload(data["item_id"])
        self.assertEqual(
            (item.kind, item.ref_type, item.ref_id, item.herd_id, item.sender_user_id, item.state),
            ("kontroll", "individual", None, self.h.id, None, "ny"),
        )
        (document,) = item.documents
        self.assertEqual((document.id, document.doc_type, document.mime), (data["document_id"], "intyg", "image/jpeg"))
        self.assertTrue(document.original_path)
        (event,) = item.events
        self.assertEqual((event.kind, event.user_id, event.detail["access_code_id"]), ("inkommen", None, self.code.id))
        # the queue's workers hear of it only once its rabbit is registered (bind_report_photo)
        self.assertFalse(db.Notice.select().where(db.Notice.item == item.id).exists())

    def test_the_queue_hears_of_the_photo_when_it_is_bound(self):
        """Codex r4: an unbound photo is no work for the queue; binding it tells its workers, though the link has no
        account."""
        self.open_link()
        item_id = self.photo_item()
        self.assertFalse(db.Notice.select().where(db.Notice.item == item_id).exists())
        self.assertEqual(self.kit(item_id).status_code, 201)
        noticed = [
            row.user_id for row in db.Notice.select().where(db.Notice.item == item_id, db.Notice.kind == "ny_post")
        ]
        self.assertIn(self.helper.id, noticed)
        self.assertEqual(len(noticed), len(set(noticed)))

    def test_demo_mode_cannot_upload_or_send_photos_to_the_production_queue(self):
        self.login("owner")
        self.client.set_cookie("sb_mode", "demo")
        self.assertEqual(self.upload_photo().status_code, 403)
        self.assertEqual(self.client.post(f"/api/v2/arsrapport{REPORT}/kop/inskick", json={}).status_code, 403)
        self.assertFalse(db.InboxItem.select().exists())

    def test_demo_owner_uploads_and_registers_only_for_the_opened_production_link(self):
        db.User.update(v2_prod_access=False).where(db.User.id == self.owner.id).execute()
        self.login("owner")
        self.client.set_cookie("sb_mode", "demo")
        link = {"via": "lank"}
        with mock.patch.object(settings.service, "access_rules", "enforce"):
            self.assertEqual(self.upload_photo(query_string=link).status_code, 401)
            self.open_link(self.code2)
            self.assertEqual(self.upload_photo(query_string=link).status_code, 404)
            self.open_link()
            self.assertEqual(self.client.post("/api/v2/inkorg/upload", query_string=link).status_code, 403)
            self.assertEqual(self.upload_photo().status_code, 403)
            uploaded = self.upload_photo(query_string=link)
            self.assertEqual(uploaded.status_code, 201, uploaded.data)
            item = self.reload(uploaded.get_json()["item_id"])
            self.assertIsNone(item.sender_user_id)
            self.assertEqual(item.events.get().detail["access_code_id"], self.code.id)
            self.assertEqual(self.kit(item.id, query_string=link).status_code, 201)

    def test_a_login_is_the_items_sender(self):
        self.login("owner")
        item = self.reload(self.photo_item())
        self.assertEqual((item.sender_user_id, item.kind), (self.owner.id, "kontroll"))

    def test_the_queues_checks_refuse_what_is_not_a_photo(self):
        self.open_link()
        refused = self.upload_photo(content=b"not an image at all")
        self.assertEqual(refused.status_code, 415)
        self.assertIn("Bara JPEG, PNG, WebP, HEIC och PDF", refused.get_json()["detail"])
        self.assertEqual(self.client.post(f"/api/v2/arsrapport{REPORT}/foto").status_code, 400)  # no file
        self.assertFalse(db.InboxItem.select().exists())

    def test_a_photo_may_be_larger_than_the_apps_limit_but_not_than_one_file(self):
        self.open_link()
        over_app_limit = b"\xff\xd8\xff" + bytes(12 * 1024 * 1024)  # a JPEG by its first bytes, not decodable
        self.assertEqual(self.upload_photo(content=over_app_limit).status_code, 422)  # read, so past 11 MB
        too_big = self.upload_photo(content=b"\xff\xd8\xff" + bytes(27 * 1024 * 1024))
        self.assertEqual((too_big.status_code, too_big.mimetype), (413, "application/problem+json"))
        self.assertFalse(db.InboxItem.select().exists())

    def test_no_photo_without_access(self):
        self.assertEqual(self.upload_photo().status_code, 401)
        self.open_link(self.code2)
        self.assertEqual(self.upload_photo().status_code, 404)  # a code for G9002 does not reach G9001
        self.assertFalse(db.InboxItem.select().exists())

    def test_one_certificate_a_photo(self):
        """A PDF of several pages is refused before anything is stored (mitt val, until several documents follow)."""
        self.open_link()
        refused = self.upload_photo(content=pdf(photo((600, 800)), photo((600, 800), seed=2)))
        self.assertEqual(refused.status_code, 400, refused.get_data(as_text=True))
        self.assertEqual(refused.get_json()["detail"], report_routes.ONE_PAGE)
        self.assertFalse(db.InboxItem.select().exists())
        self.assertEqual(self.upload_photo(content=pdf(photo((600, 800)))).status_code, 201)

    def test_a_pdf_of_several_pages_is_refused_before_page_two_is_rendered(self):
        """Opus L4: the page count is read first; no page of a PDF with more than one is rendered."""
        self.open_link()
        rendered, real = [], pypdfium2.PdfPage.render

        def render(page, *args, **kwargs):
            rendered.append(page)
            return real(page, *args, **kwargs)

        with mock.patch.object(pypdfium2.PdfPage, "render", render):
            refused = self.upload_photo(content=pdf(photo((600, 800)), photo((600, 800), seed=2)))
        self.assertEqual((refused.status_code, refused.get_json()["detail"]), (400, report_routes.ONE_PAGE))
        self.assertEqual(rendered, [])

    def test_no_photo_while_the_round_is_closed(self):
        """Opus L4: the round's rule of the report's other writes: after its last day the owner uploads nothing, and
        neither does anyone in a genebank that has not activated the round (the link has expired with it)."""
        self.login("owner")
        db.YearlyReportRound.update(end_date=date(2026, 1, 10)).where(
            db.YearlyReportRound.id == self.round_.id
        ).execute()
        refused = self.upload_photo()
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (409, "rundan_stangd"))
        mellerud = db.Herd.create(genebank=self.mellerud, herd="M9001", is_active=True)
        self.login("admin")
        refused = self.upload_photo("/besattning/M9001/2025")
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (409, "rundan_stangd"))
        self.assertFalse(db.InboxItem.select().where(db.InboxItem.herd << [self.h.id, mellerud.id]).exists())

    def test_upload_and_registration_ask_the_same_right(self):
        """Opus L4: a caretaker (a herd-access grant) may register in the herd, so may upload for it; whoever may not
        register may not upload either, so no photo is left without its rabbit."""
        caretaker = self.user("skotare")
        db.User.update(v2_prod_access=True).where(db.User.id == caretaker.id).execute()
        person = db.Member.create(
            first_name="Test", last_name="Skötare", membership=self.h.membership, role="skotare", user=caretaker
        )
        db.HerdAccessGrant.create(member=person, herd=self.h, granted_by=self.admin)
        db.User.update(fullname="Mio Test").where(db.User.id == caretaker.id).execute()
        self.login("skotare")
        self.assertEqual(self.api("GET", REPORT).get_json()["access"], "caretaker")
        response = self.kit(self.photo_item())
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        (row,) = db.MailMessage.select().where(db.MailMessage.kind == "arsrapport.ny_kanin")
        self.assertEqual(mail.MAIL_KINDS[row.kind].build(row.params)["namn"], "Mio Test")
        db.User.update(fullname=None).where(db.User.id == caretaker.id).execute()
        self.assertEqual(mail.MAIL_KINDS[row.kind].build(row.params)["namn"], "En skötare")
        self.login("owner")
        with mock.patch("blueprints.individual_v2_create._can_register_in_herd", return_value=False):
            refused = self.upload_photo()
        self.assertEqual((refused.status_code, refused.get_json()["detail"]), (403, report_routes.NO_RIGHT_TO_ADD))
        self.assertEqual(db.InboxItem.select().count(), 1)


class TestUploadLimit(AddRabbitTest):
    def setUp(self):
        super().setUp()
        limiter.reset()
        limiter.enabled = True
        self.addCleanup(limiter.reset)
        self.addCleanup(setattr, limiter, "enabled", False)

    def test_upload_limit_60_per_hour_per_code(self):
        self.assertEqual(self.upload_photo().status_code, 401)  # nobody's: spends no herd's hour
        self.open_link()
        before = datetime.now(arsrapport.STOCKHOLM)
        self.assertEqual(self.upload_photo().status_code, 201)
        empty = [self.client.post(f"/api/v2/arsrapport{REPORT}/foto").status_code for _ in range(59)]
        self.assertEqual(empty, [400] * 59)  # refused ones count: the file was on its way all the same
        refused = self.upload_photo()
        after = datetime.now(arsrapport.STOCKHOLM)
        self.assertEqual((refused.status_code, refused.mimetype), (429, "application/problem+json"))
        detail = refused.get_json()["detail"]
        found = re.fullmatch(
            r"Du har laddat upp 60 foton den senaste timmen\. Det är gränsen, ett skydd mot missbruk\. "
            r"Du kan fortsätta efter kl\. (\d\d)\.(\d\d)\. "
            r"Det du skrivit är sparat\.",
            detail,
        )
        self.assertIsNotNone(found, detail)
        at = (int(found[1]), int(found[2]))
        bounds = [(t + timedelta(hours=1, minutes=extra)) for t in (before, after) for extra in (0, 1)]
        self.assertIn(at, {(t.hour, t.minute) for t in bounds})
        self.assertEqual(db.InboxItem.select().count(), 1)
        # the owner, in the same browser, has an hour of their own
        self.login("owner")
        self.assertEqual(self.upload_photo().status_code, 201)


class TestRegister(AddRabbitTest):
    def test_code_without_account_registers_in_its_herd(self):
        self.open_link()
        item_id = self.photo_item()
        response = self.kit(item_id)
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        data = response.get_json()
        self.assertTrue(data["listed"])  # in the herd's list, so the page can set its row
        kit = db.Individual.get_by_id(data["id"])
        self.assertEqual(
            (kit.number, data["number"], kit.origin_herd_id, kit.certificate),
            ("G9001-2511",) * 2
            + (
                self.h.id,
                "P-2511",
            ),
        )
        self.assertEqual((kit.breeding.mother_id, kit.breeding.breeding_herd_id.id), (self.doe.id, self.h.id))
        birth = db.HerdTracking.get(db.HerdTracking.individual == kit.id, db.HerdTracking.kind == "BIRTH")
        self.assertEqual((birth.access_code_id, birth.signature_id), (self.code.id, None))
        item = self.reload(item_id)
        self.assertEqual(item.ref_id, kit.id)
        (document,) = item.documents
        self.assertEqual(document.individual_id, kit.id)
        self.assertFalse(db.MailMessage.select().where(db.MailMessage.kind == "arsrapport.ny_kanin").exists())
        saved = item.events.where(db.InboxEvent.kind == "sparad").get()
        self.assertEqual((saved.user_id, saved.detail["individual"]), (None, "G9001-2511"))

    def test_main_member_receives_a_named_receipt_for_a_managers_rabbit(self):
        db.User.update(fullname="Maja Test").where(db.User.id == self.manager.id).execute()
        self.login("man")
        item_id = self.photo_item()
        self.assertEqual(self.kit(item_id, paper_number="G9001-2521").status_code, 409)  # nothing written, no mail
        self.assertFalse(db.MailMessage.select().where(db.MailMessage.kind == "arsrapport.ny_kanin").exists())
        kit_id = self.kit(item_id).get_json()["id"]
        (row,) = db.MailMessage.select().where(db.MailMessage.kind == "arsrapport.ny_kanin")
        self.assertEqual(
            (
                row.recipient_kind,
                row.recipient_id,
                row.params["individual_id"],
                (row.ref_type, row.ref_id),
                row.priority,
            ),
            ("member", inbox.herd_holder(self.h.id).id, kit_id, ("individual", kit_id), 0),
        )
        self.assertEqual(row.dedupe_key, f"arsrapport.ny_kanin:{kit_id}")
        subject, body = mail.render("arsrapport.ny_kanin", mail.MAIL_KINDS["arsrapport.ny_kanin"].build(row.params))
        self.assertEqual(subject, "Maja Test har lagt till G9001-2511 i G9001")
        self.assertIn(
            "Maja Test har lagt till kaninen G9001-2511 i besättning G9001 i årsrapporten. "
            "Den finns kvar även om du drar tillbaka rapporten.",
            body,
        )
        self.assertIn("Stämmer det inte? Kontakta genbanksansvarig genom att svara på det här mejlet.", body)
        self.assertFalse(db.MailMessage.select().where(db.MailMessage.kind == "arsrapport.ny_kull").exists())
        db.Individual.update(voided=True).where(db.Individual.id == kit_id).execute()
        self.assertIsNone(mail.MAIL_KINDS["arsrapport.ny_kanin"].build(row.params))  # an unpromoted rabbit: cancelled

    def test_owner_registers_with_own_right(self):
        db.Member.update(user=self.owner).where(db.Member.id == self.code.member_id).execute()
        self.login("owner")
        response = self.kit(self.photo_item())
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        birth = db.HerdTracking.get(
            db.HerdTracking.kind == "BIRTH", db.HerdTracking.individual == response.get_json()["id"]
        )
        self.assertEqual((birth.signature_id, birth.access_code_id), (self.owner.id, None))
        self.assertFalse(db.MailMessage.select().where(db.MailMessage.kind == "arsrapport.ny_kanin").exists())

    def test_code_cannot_register_into_owners_other_herd(self):
        """L1: an owner of G9001 logged in, and G9002's link in the same session: the link writes in G9002 only."""
        self.login("owner")
        self.open_link(self.code2)
        item_id = self.photo_item(OTHER)  # by the link: the owner has no right to G9002
        self.assertIsNone(self.reload(item_id).sender_user_id)
        # the kit of the owner's own doe (G9001) through G9002's report: neither the account nor the link lends it
        refused = self.kit(item_id, OTHER)
        self.assertEqual(refused.status_code, 403, refused.get_data(as_text=True))
        litter = db.Breeding.create(
            breeding_herd_id=self.h, mother=self.doe, father=self.buck, birth_date=date(2025, 6, 1), litter_size=3
        )
        self.assertEqual(self.kit(item_id, OTHER, breeding_id=litter.id).status_code, 403)
        # the link's photo is not the account's: the owner's own report does not take it either
        self.assertEqual(self.kit(item_id).status_code, 403)
        self.assertEqual(self.kits(), 0)
        self.assertIsNone(self.reload(item_id).ref_id)
        # the link registers in its own herd
        allowed = self.kit(
            item_id, OTHER, mother=self.other_doe.number, birth_date="2025-06-10", paper_number="G9002-2511"
        )
        self.assertEqual(allowed.status_code, 201, allowed.get_data(as_text=True))
        self.assertEqual(db.Individual.get_by_id(allowed.get_json()["id"]).origin_herd_id, self.h2.id)

    def test_register_from_report_runs_number_check(self):
        """The paper's number is checked before anything is saved: a conflict writes nothing, and Stamboken's
        number once chosen is in the rabbit's change history under the link."""
        self.open_link()
        item_id = self.photo_item()
        conflict = self.kit(item_id, paper_number="G9001-2521")
        self.assertEqual(conflict.status_code, 409, conflict.get_data(as_text=True))
        problem = conflict.get_json()
        self.assertEqual((problem["title"], problem["stamboken_number"]), ("number_conflict", "G9001-2511"))
        self.assertEqual((self.kits(), db.Breeding.select().where(db.Breeding.mother == self.doe).count()), (0, 0))
        self.assertIsNone(self.reload(item_id).ref_id)
        chosen = self.kit(
            item_id,
            paper_number="G9001-2521",
            resolution={"expected_number": "G9001-2511", "choice": "use_stamboken_number"},
        )
        self.assertEqual(chosen.status_code, 201, chosen.get_data(as_text=True))
        command = db.IndividualCommand.get(db.IndividualCommand.command == "UseStambokenNumber")
        self.assertEqual((command.actor_id, command.access_code_id), (None, self.code.id))

    def test_an_empty_count_makes_a_new_litter_preliminary(self):
        """
        Item 4: the count alive at 6 weeks is not always on the certificate. Left empty for a new litter, it is the
        count born, preliminary, as "Lägg till kull" makes it; a count given is not preliminary.
        """
        self.open_link()
        response = self.kit(self.photo_item(), litter_size6w=None)
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        litter = db.Individual.get_by_id(response.get_json()["id"]).breeding
        self.assertEqual((litter.litter_size, litter.litter_size6w, litter.litter_size6w_preliminary), (5, 5, True))
        listed = {row["id"]: row for row in arsrapport.report_litters(self.h, 2025)}[litter.id]
        self.assertEqual((listed["litter_size6w"], listed["preliminary"]), (5, True))
        given = self.kit(
            self.photo_item(), birth_date="2025-08-10", paper_number="G9001-2521", paper_certificate="P-2521"
        )
        self.assertEqual(given.status_code, 201, given.get_data(as_text=True))
        litter = db.Individual.get_by_id(given.get_json()["id"]).breeding
        self.assertEqual((litter.litter_size6w, litter.litter_size6w_preliminary), (4, False))

    def test_an_old_unnumbered_litter_is_refused_in_swedish(self):
        """
        Option 1: a litter without a number that already has rabbits keeps its refusal, but the report's member reads
        it in Swedish at the birth date, from the registration and the suggestion alike. Nothing is written. The other
        routes keep NO_LITTER_NUMBER (test_register_litter).
        """
        self.open_link()
        litter = db.Breeding.create(
            breeding_herd_id=self.h,
            mother=self.doe,
            father=self.buck,
            birth_date=date(2025, 5, 10),
            litter_size=5,
            litter_size6w=5,
        )
        db.Individual.create(origin_herd=self.h, breeding=litter, number="G9001-2599")
        item_id = self.photo_item()
        response = self.kit(item_id)
        problem = response.get_json()
        self.assertEqual(
            (response.status_code, problem["detail"], problem["field"]),
            (400, NO_LITTER_NUMBER_REPORT, "birth_date"),
        )
        self.assertNotIn("litter_number", problem["detail"])
        self.assertEqual((self.kits(), db.Breeding.get_by_id(litter.id).litter_number), (1, None))
        self.assertIsNone(self.reload(item_id).ref_id)
        suggestion = self.client.get(f"/api/v2/arsrapport{REPORT}/nummerforslag?breeding_id={litter.id}")
        self.assertEqual((suggestion.status_code, suggestion.get_json()["detail"]), (400, NO_LITTER_NUMBER_REPORT))

    def test_number_routes_for_a_code_session(self):
        """FC1: the number check and the suggestion answer a link for its own herd, and refuse another herd's litter."""
        self.open_link()
        litter = {"mother": self.doe.number, "father": self.buck.number, "birth_date": "2025-05-10"}
        suggestion = self.client.get(f"/api/v2/arsrapport{REPORT}/nummerforslag", query_string=litter)
        self.assertEqual(suggestion.status_code, 200, suggestion.get_data(as_text=True))
        self.assertEqual(suggestion.get_json()["suggested"], "G9001-2511")
        check = self.api("POST", f"{REPORT}/nummerkontroll", paper_number="G9001-2521", **litter)
        self.assertEqual(check.status_code, 200, check.get_data(as_text=True))
        self.assertEqual((check.get_json()["status"], check.get_json()["stamboken_number"]), ("conflict", "G9001-2511"))
        self.open_link(self.code2)
        refused = self.api("POST", f"{OTHER}/nummerkontroll", paper_number="G9001-2511", **litter)
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(
            self.client.get(f"/api/v2/arsrapport{OTHER}/nummerforslag", query_string=litter).status_code, 403
        )

    def test_rabbit_survives_withdraw(self):
        """Spec 5.8: a rabbit registered from the report stays when the report is withdrawn."""
        self.open_link()
        response = self.kit(self.photo_item())
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        kit = db.Individual.get_by_id(response.get_json()["id"])
        listed = [row["id"] for row in arsrapport.report_list(self.h, 2025)]
        self.assertIn(kit.id, listed)
        body = self.body(*[self.kvar(r, vikt=2.8) for r in (self.doe, self.buck, self.doe2, kit)])
        sent = self.api("POST", f"{REPORT}/skicka", **body)
        self.assertEqual(sent.status_code, 200, sent.get_data(as_text=True))
        report = db.YearlyHerdReport.get()
        out = self.api("POST", f"{REPORT}/dra-tillbaka", revision=report.revision, reason=None)
        self.assertEqual(out.status_code, 200, out.get_data(as_text=True))
        kit = db.Individual.get_by_id(kit.id)
        self.assertFalse(kit.voided)
        self.assertTrue(
            db.HerdTracking.select()
            .where(db.HerdTracking.individual == kit.id, db.HerdTracking.kind == "BIRTH", db.ht_not_voided())
            .exists()
        )


class TestPhotoBinding(AddRabbitTest):
    """FC1: POST kanin binds only a photo this report's actor uploaded in this session, once, under its lock."""

    def test_photo_is_required(self):
        self.open_link()
        missing = self.kit(None)
        self.assertEqual((missing.status_code, missing.get_json()["field"]), (400, "photo"))
        self.assertEqual(self.kits(), 0)

    def test_photo_from_another_session_refused(self):
        self.open_link()
        item_id = self.photo_item()
        other = APP.test_client(use_cookies=True)
        self.open_link(client=other)  # the same link, another browser
        refused = self.kit(item_id, client=other)
        self.assertEqual(refused.status_code, 403, refused.get_data(as_text=True))
        self.assertEqual(self.kits(), 0)

    def test_photo_by_another_actor_in_the_session_refused(self):
        self.open_link()
        item_id = self.photo_item()  # by the link
        self.login("owner")  # the same browser: G9001 is now the account's report
        self.assertEqual(self.kit(item_id).status_code, 403)
        self.assertEqual(self.kits(), 0)

    def test_photo_of_another_herd_refused(self):
        self.owner.add_role("owner", self.h2.id)
        self.login("owner")
        item_id = self.photo_item(OTHER)  # the same account, G9002's report
        self.assertEqual(self.kit(item_id).status_code, 403)
        self.assertEqual(self.kits(), 0)

    def test_a_photo_the_queue_can_no_longer_check_is_refused(self):
        """Opus M2: only a certificate in an open item, its original kept and not done, is bound to the rabbit."""
        self.open_link()
        spoilers = {
            "skrapad": lambda item, doc: db.InboxItem.update(state="skrap", closed_at=inbox.now()).where(
                db.InboxItem.id == item
            ),
            "annan typ": lambda item, doc: db.InboxDocument.update(doc_type="annat").where(db.InboxDocument.id == doc),
            "original raderat": lambda item, doc: db.InboxDocument.update(original_path=None).where(
                db.InboxDocument.id == doc
            ),
            "avfärdad": lambda item, doc: db.InboxDocument.update(done_at=inbox.now()).where(
                db.InboxDocument.id == doc
            ),
        }
        for name, spoil in spoilers.items():
            with self.subTest(name):
                item_id = self.photo_item()
                (document,) = self.reload(item_id).documents
                spoil(item_id, document.id).execute()
                refused = self.kit(item_id)
                problem = refused.get_json()
                self.assertEqual(
                    (refused.status_code, problem["detail"], problem["field"]), (409, arsrapport.PHOTO_GONE, "photo")
                )
                self.assertIsNone(self.reload(item_id).ref_id)
        self.assertEqual(self.kits(), 0)

    def test_no_rabbit_through_a_paper_item(self):
        """Opus L7: ?post= is the paper form's, whose certificates go through the queue: refused as the upload is."""
        stored = [("inkorg/original/form.jpg", "4".rjust(64, "0"), QUALITY)]
        form, (page,) = inbox.create_upload(self.owner, self.h, None, stored)
        page.doc_type = "arsblankett"
        page.save()
        inbox.take(form, self.manager, over=False)
        self.login("man")
        item_id = self.photo_item()  # as the genebank's manager, not through the form
        refused = self.client.post(
            f"/api/v2/arsrapport{REPORT}/kanin?post={form.id}",
            json={"item_id": item_id, "mother": self.doe.number, "father": self.buck.number},
        )
        self.assertEqual((refused.status_code, refused.get_json()["detail"]), (403, report_routes.PAPER_IN_QUEUE))
        self.assertIsNone(self.reload(item_id).ref_id)
        self.assertEqual(self.kits(), 0)

    def test_photo_binds_once(self):
        self.open_link()
        item_id = self.photo_item()
        self.assertEqual(self.kit(item_id).status_code, 201)
        again = self.kit(item_id, name="Tvilling", paper_number="G9001-2512", paper_certificate="P-2512")
        self.assertEqual(again.status_code, 409, again.get_data(as_text=True))
        self.assertEqual(self.kits(), 1)


class TestParentLookup(AddRabbitTest):
    """L10: the form's lookup for a code session: the genebank's rabbits, a doe's litters in the herd, 404 otherwise."""

    def search(self, number, path=REPORT):
        return self.client.get(f"/api/v2/arsrapport{path}/kanin-sok", query_string={"nummer": number})

    def test_lookup_for_a_code_session(self):
        self.assertEqual(self.search(self.doe.number).status_code, 401)
        self.open_link()
        db.Breeding.create(
            breeding_herd_id=self.h,
            mother=self.doe,
            father=self.buck,
            birth_date=date(2025, 5, 10),
            breed_date=date(2025, 4, 9),
            litter_size=5,
            litter_size6w=4,
        )
        found = self.search(self.doe.number.lower())
        self.assertEqual(found.status_code, 200, found.get_data(as_text=True))
        data = found.get_json()
        self.assertEqual((data["number"], data["sex"]), (self.doe.number, "female"))
        (litter,) = data["litters"]
        self.assertEqual(
            (litter["birth_date"], litter["father"], litter["litter_size"], litter["litter_size6w"]),
            ("2025-05-10", self.buck.number, 5, 4),
        )
        self.assertEqual(self.search(self.other_doe.number).get_json()["litters"], [])  # the genebank's, as a parent
        mellerud = db.Herd.create(genebank=self.mellerud, herd="M9001", is_active=True)
        self.assertEqual(self.search(self.rabbits(mellerud, 1)[0].number).status_code, 404)
        missing = self.search("G9001-9999")
        self.assertEqual((missing.status_code, missing.get_json()["code"]), (404, "saknas"))
        self.assertNotIn("code", self.search(self.doe.number, OTHER).get_json())  # the herd's 404: not "saknas"

    def test_the_forms_colours_and_actor_for_a_code_session(self):
        db.Color.create(name="viltgrå", genebank=self.gotland)
        db.Color.create(name="svart", genebank=self.mellerud)
        path = f"/api/v2/arsrapport{REPORT}/kanin-formular"
        self.assertEqual(self.client.get(path).status_code, 401)
        self.open_link()
        setup = self.client.get(path).get_json()
        self.assertIn("viltgrå", setup["farger"])
        self.assertNotIn("svart", setup["farger"])
        self.assertEqual(setup["aktor"], f"code-{self.code.id}")  # a draft in the browser is the link's own
        self.login("owner")
        self.assertEqual(self.client.get(path).get_json()["aktor"], f"user-{self.owner.id}")


class TestScope(AddRabbitTest):
    """A link learns nothing outside its genebank: an out-of-scope parent or litter reads exactly as a missing one."""

    def setUp(self):
        super().setUp()
        mellerud = db.Herd.create(genebank=self.mellerud, herd="M9001", is_active=True)
        self.foreign_doe, self.foreign_buck = self.rabbits(mellerud, 2)
        self.foreign_litter = self.foreign_doe.breeding
        self.open_link()

    def test_out_of_genebank_reads_as_missing(self):
        litter = {"mother": self.doe.number, "birth_date": "2025-05-10"}
        cases = {
            "nummerforslag": lambda father: self.client.get(
                f"/api/v2/arsrapport{REPORT}/nummerforslag", query_string={**litter, "father": father}
            ),
            "nummerkontroll": lambda father: self.api(
                "POST", f"{REPORT}/nummerkontroll", paper_number="G9001-2511", father=father, **litter
            ),
            "kanin": lambda father: self.kit(self.photo_item(), father=father),
        }
        for name, send in cases.items():
            with self.subTest(name):
                foreign, missing = send(self.foreign_buck.number), send("M9001-9999")
                self.assertEqual(foreign.status_code, missing.status_code)
                self.assertEqual(foreign.get_json()["detail"], missing.get_json()["detail"])
                self.assertEqual(foreign.status_code, 400)
        by_litter = {
            "nummerforslag": lambda bid: self.client.get(
                f"/api/v2/arsrapport{REPORT}/nummerforslag", query_string={"breeding_id": bid}
            ),
            "nummerkontroll": lambda bid: self.api(
                "POST", f"{REPORT}/nummerkontroll", paper_number="G9001-2511", breeding_id=bid
            ),
            "kanin": lambda bid: self.kit(self.photo_item(), breeding_id=bid),
        }
        absent = db.Breeding.select(db.fn.MAX(db.Breeding.id)).scalar() + 1000
        for name, send in by_litter.items():
            with self.subTest(name, by="breeding_id"):
                foreign, missing = send(self.foreign_litter.id), send(absent)
                self.assertEqual((foreign.status_code, missing.status_code), (404, 404))
                self.assertEqual(
                    foreign.get_json()["detail"].replace(str(self.foreign_litter.id), "<id>"),
                    missing.get_json()["detail"].replace(str(absent), "<id>"),
                )
        self.assertEqual(self.kits(), 0)

    def test_a_foreign_paper_number_reads_alike_held_or_free(self):
        """Codex P2: another genebank's paper number gets one answer whether a rabbit holds it or not, and so does a
        herd that does not exist; nothing is looked up by it."""
        sends = {
            "nummerkontroll": lambda number: self.api(
                "POST",
                f"{REPORT}/nummerkontroll",
                paper_number=number,
                mother=self.doe.number,
                father=self.buck.number,
                birth_date="2025-05-10",
            ),
            "kanin": lambda number: self.kit(self.photo_item(), paper_number=number),
        }
        free = {name: send("M9001-2511") for name, send in sends.items()}
        foreign = {"origin_herd": self.foreign_doe.origin_herd, "breeding": self.foreign_litter}
        db.Individual.create(number="M9001-2511", **foreign)
        for name, send in sends.items():
            with self.subTest(name):
                self.assertEqual(free[name].status_code, 400, free[name].get_data(as_text=True))
                self.assertEqual(free[name].get_json()["field"], "paper_number")
                self.assertEqual(send("M9001-2511").get_json(), free[name].get_json())
                self.assertEqual(send("G9999-2511").get_json(), free[name].get_json())
        self.assertEqual(self.kits(), 0)


class TestCertificateNumberScope(AddRabbitTest):
    """Codex r4 #1: a report actor learns nothing from a certificate number about the rabbits that hold it."""

    def setUp(self):
        super().setUp()
        mellerud = db.Herd.create(genebank=self.mellerud, herd="M9001", is_active=True)
        self.foreign = self.rabbits(mellerud, 1)[0]
        self.open_link()

    def check(self, certificate):
        return self.api(
            "POST",
            f"{REPORT}/nummerkontroll",
            paper_number="G9001-2511",
            paper_certificate=certificate,
            mother=self.doe.number,
            father=self.buck.number,
            birth_date="2025-05-10",
        )

    def test_the_number_check_reads_alike_for_a_taken_and_a_free_certificate(self):
        free = self.check("P-FRI-1")
        self.assertEqual(free.status_code, 200, free.get_data(as_text=True))
        for taken in (self.foreign.certificate, self.doe2.certificate):
            with self.subTest(taken=taken):
                self.assertEqual(self.check(taken).get_json(), free.get_json())

    def test_a_taken_certificate_is_refused_alike_at_registration(self):
        item_id = self.photo_item()
        answers = [
            self.kit(item_id, paper_certificate=taken) for taken in (self.foreign.certificate, self.doe2.certificate)
        ]
        for refused in answers:
            self.assertEqual(refused.status_code, 409, refused.get_data(as_text=True))
            self.assertEqual(refused.get_json()["detail"], "Intygsnumret kan inte användas. Kontakta genbanksansvarig.")
        self.assertEqual(answers[0].get_json(), answers[1].get_json())
        self.assertEqual((self.kits(), self.reload(item_id).ref_id), (0, None))
        self.assertEqual(self.kit(item_id, paper_certificate="P-FRI-1").status_code, 201)


class TestReportPhotoReading(AddRabbitTest):
    """G5: the photo is read after its rabbit is saved, and the queue gets the reading beside the registration."""

    READING = {"genbanksnr": "G9001", "ar_kull_individ": "2511", "namn": "Kulla"}

    def setUp(self):
        super().setUp()
        for patcher in (
            mock.patch.object(settings.interpretation, "interpreter", "gemma"),
            mock.patch.dict(interpreter.INTERPRETERS, {"gemma": lambda image, schema: dict(self.READING)}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def registered(self):
        """A queue upload bound to a rabbit first (older), then the report's photo of the kit, registered."""
        stored = [("inkorg/original/q.jpg", "1".rjust(64, "0"), QUALITY)]
        queued, (queued_doc,) = inbox.create_upload(self.owner, self.h, None, stored)
        queued_doc.individual = self.doe
        queued_doc.save()
        self.open_link()
        item_id = self.photo_item()
        self.assertEqual(self.kit(item_id).status_code, 201)
        item = self.reload(item_id)
        (document,) = item.documents
        return queued, queued_doc, item, document

    def test_registered_photo_is_read_and_set_beside_the_rabbit(self):
        queued, queued_doc, item, document = self.registered()
        self.assertEqual((document.individual_id is not None, document.interpretation_status), (True, "vantar"))
        self.assertEqual(interpreter.interpret_next(), document.id)  # not the older, saved queue upload
        self.assertIsNone(interpreter.interpret_next())
        read = db.InboxDocument.get_by_id(document.id)
        self.assertEqual(read.interpretation_status, "klar")
        self.assertIn("fields", read.proposal)
        self.assertEqual(db.InboxDocument.get_by_id(queued_doc.id).interpretation_status, "vantar")
        detail = inbox.item_detail(item, self.helper)
        self.assertEqual(
            {key: detail["registered"][key] for key in ("paper_number", "paper_certificate", "mother", "name")},
            {"paper_number": "G9001-2511", "paper_certificate": "P-2511", "mother": self.doe.number, "name": "Kulla"},
        )
        self.assertEqual(detail["documents"][0]["proposal"], read.proposal)
        self.assertIsNone(inbox.item_detail(queued, self.helper)["registered"])

    def test_a_photo_too_small_waits_for_tolka_igen_once_registered(self):
        self.open_link()
        item_id = self.reload(self.photo_item()).id
        db.InboxDocument.update(quality={"short_side": 600, "sharpness": 900.0, "brightness": 200.0}).where(
            db.InboxDocument.item == item_id
        ).execute()
        self.assertEqual(self.kit(item_id).status_code, 201)
        (document,) = self.reload(item_id).documents
        self.assertEqual(document.interpretation_status, "for_litet")
        self.assertIsNone(interpreter.interpret_next())

    def test_a_photo_uploaded_for_a_purchase_is_read_once_a_rabbit_is_registered_from_it(self):
        """The purpose is the client's word: a rabbit's photo is read whatever it was uploaded for (G5)."""
        self.open_link()
        data = {"file": (io.BytesIO(encoded(photo())), "intyg.jpg")}
        response = self.client.post(
            f"/api/v2/arsrapport{REPORT}/foto?syfte=kop", data=data, content_type="multipart/form-data"
        )
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        item_id, document_id = response.get_json()["item_id"], response.get_json()["document_id"]
        self.assertEqual(db.InboxDocument.get_by_id(document_id).interpretation_status, "av")
        self.assertIsNone(interpreter.interpret_next())
        self.assertEqual(self.kit(item_id).status_code, 201)
        self.assertEqual(db.InboxDocument.get_by_id(document_id).interpretation_status, "vantar")
        self.assertEqual(interpreter.interpret_next(), document_id)

    def read_registered(self, **reading):
        """The report photo of the kit, registered first and then read as `reading` says."""
        self.READING = reading
        _, _, _, document = self.registered()
        self.assertEqual(interpreter.interpret_next(), document.id)
        return db.InboxDocument.get_by_id(document.id).proposal

    @staticmethod
    def parent(rabbit):
        return {"genbanksnr": "G9001", "ar_kull_individ": rabbit.number.split("-")[1], "namn": ""}

    def test_every_field_beside_the_registered_rabbit(self):
        """Codex P2: a photo read after its rabbit is saved gets every field of the form compared with that rabbit,
        with what differs or is unsure kept, and the checks."""
        proposal = self.read_registered(
            genbanksnr="G9001",
            ar_kull_individ="2511",
            intygsnummer="P-2511",
            fodelsedatum="250510",
            kon="Hona",
            namn="Bella",
            farg="",
            fodda_i_kullen="5",
            levande_efter_6_veckor="fyra",
            mor=self.parent(self.doe),
            far=self.parent(self.buck),
        )
        fields = {key: (field["source"], field["value"]) for key, field in proposal["fields"].items()}
        self.assertEqual(
            fields,
            {
                "paper_number": ("läst", "G9001-2511"),
                "paper_certificate": ("läst", "P-2511"),
                "name": ("avviker", None),
                "sex": ("läst", "female"),
                "birth_date": ("läst", "2025-05-10"),
                "mother": ("läst", self.doe.number),
                "father": ("läst", self.buck.number),
                "litter_size": ("läst", 5),
                "litter_size6w": ("osäker", None),
            },
        )
        name = proposal["fields"]["name"]
        self.assertEqual((name["read"], name["registry"]), ("Bella", "Kulla"))
        self.assertEqual(proposal["fields"]["litter_size6w"]["read"], "fyra")
        self.assertIn(
            {"ok": False, "text": "Namnet på intyget är inte registrets för G9001-2511 (Kulla)."}, proposal["checks"]
        )

    def test_another_rabbits_number_deviates_from_the_registered_one(self):
        """Another rabbit's number read is not taken as that rabbit's certificate: it deviates from the kit's."""
        proposal = self.read_registered(genbanksnr="G9001", ar_kull_individ=self.doe2.number.split("-")[1])
        field = proposal["fields"]["paper_number"]
        self.assertEqual((field["source"], field["value"], field["registry"]), ("avviker", None, "G9001-2511"))
        self.assertNotIn("individual", proposal["fields"])  # not the littermate's own comparison

    def test_a_number_not_read_is_unsure_beside_the_registered_one(self):
        proposal = self.read_registered(genbanksnr="G9001", ar_kull_individ="25?1", mor=self.parent(self.doe))
        self.assertEqual(proposal["fields"]["paper_number"], {"value": None, "source": "osäker", "read": "G9001 25?1"})
        self.assertEqual(proposal["fields"]["mother"]["source"], "läst")

    def test_a_reading_made_before_the_rabbit_is_set_beside_it_when_bound(self):
        """Codex r4: the photo read before its rabbit is saved gets every field compared with that rabbit when it is
        bound, from the stored reading: no new reading, and no comparison left at the fields read without it."""
        db.Color.create(name="viltgrå", genebank=self.gotland)
        self.READING = {
            "genbanksnr": "G9001",
            "ar_kull_individ": "2511",
            "intygsnummer": "P-2511",
            "fodelsedatum": "250510",
            "kon": "Hona",
            "namn": "Kulla",
            "farg": "viltgrå",
            "fodda_i_kullen": "5",
            "levande_efter_6_veckor": "4",
            "mor": self.parent(self.doe),
            "far": self.parent(self.buck),
        }
        self.open_link()
        item_id = self.photo_item()
        # a photo uploaded before they were held (item 12): an ordinary one, read while nothing is registered from it
        db.InboxItem.update(ref_data=None).where(db.InboxItem.id == item_id).execute()
        (document,) = self.reload(item_id).documents
        db.InboxDocument.update(interpretation_status="vantar").where(db.InboxDocument.id == document.id).execute()
        self.assertEqual(interpreter.interpret_next(), document.id)
        self.assertEqual(db.InboxDocument.get_by_id(document.id).interpretation_status, "klar")
        response = self.kit(item_id, color="viltgrå")
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        read = db.InboxDocument.get_by_id(document.id)
        kit = db.Individual.get_by_id(response.get_json()["id"])
        self.assertEqual(read.proposal, build_proposal(read.interpretation, self.gotland.id, self.h.id, kit))
        self.assertEqual(
            set(read.proposal["fields"]),
            {
                "paper_number",
                "paper_certificate",
                "name",
                "sex",
                "birth_date",
                "color",
                "mother",
                "father",
                "litter_size",
                "litter_size6w",
            },
        )
        self.assertEqual({field["source"] for field in read.proposal["fields"].values()}, {"läst"})
        self.assertEqual(read.interpretation_status, "klar")
        self.assertIsNone(interpreter.interpret_next())  # nothing read again

    def test_tolka_igen_on_a_registered_report_photo(self):
        queued, queued_doc, item, document = self.registered()
        interpreter.interpret_next()
        inbox.take(item, self.helper, over=False)
        inbox.reinterpret(item, db.InboxDocument.get_by_id(document.id), self.helper)
        self.assertEqual(db.InboxDocument.get_by_id(document.id).interpretation_status, "vantar")
        inbox.take(queued, self.helper, over=False)
        with self.assertRaises(inbox.InboxError):  # an ordinary saved certificate stays as it was
            inbox.reinterpret(queued, queued_doc, self.helper)


class TestHeldPhoto(TestReportPhotoReading):
    """
    Item 12: the photo of "Lägg till kanin" is held (inbox.HELD_RABBIT) until Spara registers the rabbit: not read and
    not the queue's work meanwhile, purged a day after it came in if nothing was saved, and an ordinary item once its
    rabbit is registered. One item per rabbit, as before.
    """

    def listed(self):
        """The ids and the count of new items the queue lists for a manager of the genebank."""
        client = APP.test_client(use_cookies=True)  # not the link's session, which holds its photos
        client.post("/api/login", json={"username": "man", "password": "pass"})
        body = client.get("/api/v2/inkorg?scope=alla&state=alla").get_json()
        return {item["id"] for item in body["items"]}, body["counts"].get("ny", 0)

    def test_a_held_photo_is_neither_read_nor_the_queues_work(self):
        self.open_link()
        item_id = self.photo_item()
        item = self.reload(item_id)
        (document,) = item.documents
        self.assertEqual((item.ref_data, document.interpretation_status), ({"syfte": "kanin"}, "av"))
        self.assertTrue(inbox.unread(item))
        db.InboxDocument.update(interpretation_status="vantar").where(db.InboxDocument.id == document.id).execute()
        self.assertIsNone(interpreter.interpret_next())  # held: not read whatever its status says
        db.InboxDocument.update(interpretation_status="av").where(db.InboxDocument.id == document.id).execute()
        self.assertEqual(self.listed(), (set(), 0))
        self.assertFalse(db.Notice.select().where(db.Notice.item == item_id).exists())

    def test_spara_makes_it_an_ordinary_item_that_is_read(self):
        self.open_link()
        first, second = self.photo_item(), self.photo_item()
        self.assertEqual(self.kit(first).status_code, 201)
        item = self.reload(first)
        (document,) = item.documents
        self.assertEqual((item.ref_data, item.ref_id is not None), (None, True))
        self.assertFalse(inbox.unread(item))
        self.assertEqual(db.InboxDocument.get_by_id(document.id).interpretation_status, "vantar")
        self.assertEqual(interpreter.interpret_next(), document.id)
        self.assertEqual(self.listed(), ({first}, 1))  # the other rabbit's photo is still held
        kit2 = self.kit(second, paper_number="G9001-2512", paper_certificate="P-2512")
        self.assertEqual(kit2.status_code, 201, kit2.get_data(as_text=True))
        self.assertEqual(self.listed(), ({first, second}, 2))  # one item per rabbit

    def test_a_held_photo_left_a_day_is_purged_with_its_file(self):
        self.open_link()
        left, fresh, bound = self.photo_item(), self.photo_item(), self.photo_item()
        self.assertEqual(self.kit(bound).status_code, 201)
        files = {i: os.path.join(self.folder, self.reload(i).documents[0].original_path) for i in (left, fresh, bound)}
        two_days_ago = inbox.now() - timedelta(days=2)
        db.InboxItem.update(received_at=two_days_ago).where(db.InboxItem.id.in_([left, bound])).execute()
        self.assertEqual(inbox_purge.purge_held(inbox.now()), 1)
        remaining = {row.id for row in db.InboxItem.select()}
        self.assertEqual(
            {i: (i in remaining, os.path.exists(path)) for i, path in files.items()},
            {left: (False, False), fresh: (True, True), bound: (True, True)},
        )
        # the dialog still open on the purged photo: Spara asks for the photo again, at the photo field
        refused = self.kit(left, paper_number="G9001-2512", paper_certificate="P-2512")
        self.assertEqual(
            (refused.status_code, refused.get_json()["detail"], refused.get_json()["field"]),
            (409, arsrapport.PHOTO_GONE, "photo"),
        )


class TestReportPhotoCheck(AddRabbitTest):
    """A report photo is closed in the queue: a worker of its genebank takes it, compares and closes it."""

    def setUp(self):
        super().setUp()
        self.open_link()
        self.item_id = self.photo_item()
        self.assertEqual(self.kit(self.item_id).status_code, 201)
        (self.document,) = self.reload(self.item_id).documents
        self.client.get("/api/logout")

    def queue(self, path, **body):
        return self.client.post(f"/api/v2/inkorg/{self.item_id}{path}", json=body)

    def check(self, outcome):
        return self.queue(f"/dokument/{self.document.id}/kontrollerad", outcome=outcome)

    def test_a_helper_takes_it_and_closes_it_as_stammer(self):
        self.login("hjalp")
        self.assertEqual(self.queue("/ta").status_code, 200)
        response = self.check("stammer")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        item = self.reload(self.item_id)
        self.assertEqual((item.state, item.ref_id is not None), ("klar", True))
        self.assertIsNotNone(db.InboxDocument.get_by_id(self.document.id).done_at)
        self.assertEqual(response.get_json()["document"]["status"], "klar")  # checked, not dismissed
        self.assertEqual(inbox.item_detail(item, self.helper)["documents"][0]["status"], "klar")
        checked = item.events.where(db.InboxEvent.kind == "kontrollerad").get()
        self.assertEqual((checked.user_id, checked.detail["outcome"]), (self.helper.id, "stammer"))
        closed = item.events.where(db.InboxEvent.kind == "lage").order_by(db.InboxEvent.id.desc()).first()
        self.assertEqual((closed.detail["from"], closed.detail["to"]), ("tagen", "klar"))
        self.assertEqual(self.check("stammer").status_code, 409)  # closed: once

    def test_rattat_and_nothing_else(self):
        self.login("man")
        self.assertEqual(self.queue("/ta").status_code, 200)
        self.assertEqual(self.check("annat").status_code, 400)
        self.assertEqual(self.check("rattat").status_code, 200)
        checked = self.reload(self.item_id).events.where(db.InboxEvent.kind == "kontrollerad").get()
        self.assertEqual(checked.detail["outcome"], "rattat")

    def test_only_its_handler_and_only_a_worker_of_its_genebank(self):
        self.login("hjalp")
        self.assertEqual(self.check("stammer").status_code, 409)  # not taken
        self.login("mhjalp")  # a helper of Mellerud
        self.assertEqual(self.queue("/ta").status_code, 403)
        self.assertEqual(self.check("stammer").status_code, 403)
        self.assertEqual(self.reload(self.item_id).state, "ny")

    def test_tolka_igen_for_its_handler(self):
        self.login("hjalp")
        self.assertEqual(self.queue("/ta").status_code, 200)
        with mock.patch.object(settings.interpretation, "interpreter", "gemma"):
            response = self.queue(f"/dokument/{self.document.id}/tolka-igen")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(db.InboxDocument.get_by_id(self.document.id).interpretation_status, "vantar")

    def test_reopening_opens_the_check_again(self):
        """Codex r4: "Öppna igen" on a checked photo brings its check back, and turning it does not close it again."""
        self.login("man")
        self.assertEqual(self.queue("/ta").status_code, 200)
        self.assertEqual(self.check("stammer").status_code, 200)
        self.assertEqual(self.reload(self.item_id).state, "klar")
        self.assertEqual(self.queue("/lage", state="tagen").status_code, 200)
        shown = inbox.item_detail(self.reload(self.item_id), self.manager)["documents"][0]
        self.assertEqual((shown["status"], shown["done_at"]), ("sparad", None))  # Stämmer and Rättat are back
        turned = self.client.patch(f"/api/v2/inkorg/{self.item_id}/dokument/{self.document.id}", json={"rotation": 90})
        self.assertEqual(turned.status_code, 200, turned.get_data(as_text=True))
        self.assertEqual(self.reload(self.item_id).state, "tagen")
        with mock.patch.object(settings.interpretation, "interpreter", "gemma"):
            self.assertEqual(self.queue(f"/dokument/{self.document.id}/tolka-igen").status_code, 200)
        self.assertEqual(self.check("rattat").status_code, 200)
        item = self.reload(self.item_id)
        self.assertEqual(item.state, "klar")
        outcomes = [e.detail["outcome"] for e in item.events.where(db.InboxEvent.kind == "kontrollerad")]
        self.assertEqual(outcomes, ["stammer", "rattat"])

    def test_only_the_bound_rabbit_is_checked(self):
        """Codex r4: a photo that registered no rabbit, or another than the item's, cannot be checked."""
        stored = [("inkorg/original/u.jpg", "3".rjust(64, "0"), QUALITY)]
        unbound, (loose,) = inbox.create_upload(
            None, self.h, None, stored, kind="kontroll", ref_type="individual", access_code_id=self.code.id
        )
        db.InboxItem.update(ref_id=self.doe.id).where(db.InboxItem.id == self.item_id).execute()  # not its rabbit
        self.login("hjalp")
        for item_id, document_id in ((unbound.id, loose.id), (self.item_id, self.document.id)):
            with self.subTest(item=item_id):
                self.assertEqual(self.client.post(f"/api/v2/inkorg/{item_id}/ta").status_code, 200)
                refused = self.client.post(
                    f"/api/v2/inkorg/{item_id}/dokument/{document_id}/kontrollerad", json={"outcome": "stammer"}
                )
                self.assertEqual(refused.status_code, 409, refused.get_data(as_text=True))
                self.assertIsNone(db.InboxDocument.get_by_id(document_id).done_at)

    def test_an_ordinary_item_is_not_closed_so(self):
        stored = [("inkorg/original/q.jpg", "2".rjust(64, "0"), QUALITY)]
        ordinary, (document,) = inbox.create_upload(self.owner, self.h, None, stored)
        self.login("hjalp")
        self.assertEqual(self.client.post(f"/api/v2/inkorg/{ordinary.id}/ta").status_code, 200)
        refused = self.client.post(
            f"/api/v2/inkorg/{ordinary.id}/dokument/{document.id}/kontrollerad", json={"outcome": "stammer"}
        )
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(db.InboxItem.get_by_id(ordinary.id).state, "tagen")
