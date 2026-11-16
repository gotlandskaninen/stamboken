#!/usr/bin/env python3
"""
"Lägg till kanin från intyget" in the report (step 4b, Task 4): the certificate's photo becomes a `kontroll` item, and
the rabbit is registered with the report actor's own right, bound to that photo. By a login and by a link without an
account. Synthetic photos and data only.

isort:skip_file
"""

import io
import re
from datetime import date, datetime, timedelta
from datetime import time as clock
from unittest import mock

import blueprints.arsrapport as report_routes
import utils.arsrapport as arsrapport
import utils.database as db
import utils.inbox as inbox
import utils.inbox_interpreter as interpreter
import utils.mail as mail
import utils.report_code as report_code
import utils.settings as settings
from herdbook import APP, limiter

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

    def upload_photo(self, path=REPORT, content=None, client=None):
        data = {"file": (io.BytesIO(content or encoded(photo((600, 800)))), "intyg.jpg")}
        return (client or self.client).post(
            f"/api/v2/arsrapport{path}/foto", data=data, content_type="multipart/form-data"
        )

    def photo_item(self, path=REPORT, client=None):
        response = self.upload_photo(path, client=client)
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return response.get_json()["item_id"]

    def kit(self, item_id, path=REPORT, client=None, **fields):
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
        return (client or self.client).post(f"/api/v2/arsrapport{path}/kanin", json=body)

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
        # the queue's workers hear of it, though the sender has no account
        noticed = {row.user_id for row in db.Notice.select().where(db.Notice.item == item.id)}
        self.assertIn(self.helper.id, noticed)

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
            r"Du har laddat upp många foton den senaste timmen\. Fortsätt efter kl\. (\d\d)\.(\d\d)\. "
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
        saved = item.events.where(db.InboxEvent.kind == "sparad").get()
        self.assertEqual((saved.user_id, saved.detail["individual"]), (None, "G9001-2511"))

    def test_owner_registers_with_own_right(self):
        self.login("owner")
        response = self.kit(self.photo_item())
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        birth = db.HerdTracking.get(
            db.HerdTracking.kind == "BIRTH", db.HerdTracking.individual == response.get_json()["id"]
        )
        self.assertEqual((birth.signature_id, birth.access_code_id), (self.owner.id, None))

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
        detail = inbox.item_detail(item)
        self.assertEqual(
            {key: detail["registered"][key] for key in ("paper_number", "paper_certificate", "mother", "name")},
            {"paper_number": "G9001-2511", "paper_certificate": "P-2511", "mother": self.doe.number, "name": "Kulla"},
        )
        self.assertEqual(detail["documents"][0]["proposal"], read.proposal)
        self.assertIsNone(inbox.item_detail(queued)["registered"])

    def test_tolka_igen_on_a_registered_report_photo(self):
        queued, queued_doc, item, document = self.registered()
        interpreter.interpret_next()
        inbox.take(item, self.helper, over=False)
        inbox.reinterpret(item, db.InboxDocument.get_by_id(document.id), self.helper)
        self.assertEqual(db.InboxDocument.get_by_id(document.id).interpretation_status, "vantar")
        inbox.take(queued, self.helper, over=False)
        with self.assertRaises(inbox.InboxError):  # an ordinary saved certificate stays as it was
            inbox.reinterpret(queued, queued_doc, self.helper)


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
        self.assertEqual(inbox.item_detail(item)["documents"][0]["status"], "klar")
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
