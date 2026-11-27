"""The image reading as a job: one document a run, two attempts, no transaction while the model reads, "Tolka igen".

The interpreter is a fake that returns canned dicts; no model runs.

isort:skip_file
"""

from datetime import date
from unittest import mock

import utils.database as db  # noqa: E402
import utils.inbox as inbox  # noqa: E402
import utils.inbox_interpreter as interpreter  # noqa: E402
import utils.inbox_purge as inbox_purge  # noqa: E402
import utils.settings as settings  # noqa: E402

from tests.inbox_fixtures import InboxTest, encoded, photo  # noqa: E402

READING = {"genbanksnr": "G1", "ar_kull_individ": "2111", "namn": "Testa"}
# The seller and buyer at the bottom, as the second reading answers (made-up names, a reserved domain).
SALE = {
    "saljare_besattning": "G1",
    "kopare_namn": "Köpa Testsson",
    "kopare_epost": "kopa@example.com",
    "datum": "240601",
}


class InterpretationTest(InboxTest):
    def setUp(self):
        super().setUp()
        self.calls, self.sale_calls = [], []
        self.answer, self.sale = READING, {}
        for patcher in (
            mock.patch.object(settings.interpretation, "interpreter", "gemma"),
            mock.patch.dict(interpreter.INTERPRETERS, {"gemma": self.fake}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake(self, image, schema):
        """
        The model: records the call, checks that nothing of the database is held, and answers. The reading of the
        seller and buyer (any other schema) is recorded and answered on its own.
        """
        self.assertTrue(db.DB_PROXY.is_closed(), "a connection is open while the model reads")
        main = schema is interpreter.SCHEMA
        (self.calls if main else self.sale_calls).append((image, schema))
        answer = self.answer if main else self.sale
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def uploaded(self, files=1):
        self.login("owner")
        resp = self.upload(*[(f"intyg{n}.jpg", encoded(photo(seed=n))) for n in range(files)])
        self.assertEqual(resp.status_code, 201, resp.get_json())
        item = db.InboxItem.get_by_id(resp.get_json()["item"]["id"])
        return item, list(item.documents.order_by(db.InboxDocument.id))

    def doc(self, document):
        return db.InboxDocument.get_by_id(document.id)


class TestJob(InterpretationTest):
    def test_one_document_a_run_oldest_first(self):
        _, (first, second) = self.uploaded(files=2)
        self.assertEqual({self.doc(first).interpretation_status, self.doc(second).interpretation_status}, {"vantar"})
        self.assertEqual(interpreter.interpret_next(), first.id)
        self.assertEqual(len(self.calls), 1)
        done = self.doc(first)
        self.assertEqual((done.interpretation_status, done.attempts, done.interpreter), ("klar", 1, "gemma"))
        self.assertEqual(done.interpretation, READING)
        self.assertIn("fields", done.proposal)
        self.assertIsNotNone(done.interpreted_at)
        self.assertEqual(self.doc(second).interpretation_status, "vantar")
        self.assertEqual(interpreter.interpret_next(), second.id)
        self.assertIsNone(interpreter.interpret_next())
        self.assertEqual(len(self.calls), 2)

    def test_the_model_gets_the_prepared_photo_and_the_schema(self):
        self.uploaded()
        interpreter.interpret_next()
        image, schema = self.calls[0]
        self.assertTrue(image.startswith(b"\xff\xd8"))  # a JPEG
        self.assertEqual(schema, interpreter.SCHEMA)

    def test_two_attempts_then_failed(self):
        _, (document,) = self.uploaded()
        self.answer = interpreter.InterpretationError("Ollama svarar inte")
        interpreter.interpret_next()
        self.assertEqual((self.doc(document).interpretation_status, self.doc(document).attempts), ("vantar", 1))
        interpreter.interpret_next()
        failed = self.doc(document)
        self.assertEqual((failed.interpretation_status, failed.attempts, failed.proposal), ("misslyckad", 2, None))
        self.assertIsNotNone(failed.interpreted_at)
        self.assertIsNone(interpreter.interpret_next())
        self.assertEqual(len(self.calls), 2)

    def test_a_run_that_died_counts(self):
        _, (document,) = self.uploaded()
        db.InboxDocument.update(attempts=2).where(db.InboxDocument.id == document.id).execute()
        interpreter.interpret_next()
        self.assertEqual(self.doc(document).interpretation_status, "misslyckad")
        self.assertEqual(self.calls, [])

    def test_no_transaction_while_the_model_reads(self):
        self.uploaded()
        with mock.patch.object(interpreter, "build_proposal", wraps=interpreter.build_proposal) as build:
            interpreter.interpret_next()
        self.assertEqual(len(self.calls), 1)  # fake() asserted the connection was closed
        build.assert_called_once()
        self.assertFalse(db.DB_PROXY.in_transaction())

    def test_a_document_requeued_while_the_model_reads_keeps_waiting(self):
        _, (document,) = self.uploaded()

        def requeued_meanwhile(image, schema):
            db.InboxDocument.update(attempts=0, rotation=90).where(db.InboxDocument.id == document.id).execute()
            return READING

        with mock.patch.dict(interpreter.INTERPRETERS, {"gemma": requeued_meanwhile}):
            interpreter.interpret_next()
        stale = self.doc(document)
        self.assertEqual((stale.interpretation_status, stale.proposal), ("vantar", None))

    def test_the_photo_is_read_straightened_and_a_reading_straightened_meanwhile_is_dropped(self):
        _, (document,) = self.uploaded()
        db.InboxDocument.update(straighten=2.5).where(db.InboxDocument.id == document.id).execute()

        def straightened_meanwhile(image, schema):  # nothing else changes: the turn and the attempts stay
            db.InboxDocument.update(straighten=3).where(db.InboxDocument.id == document.id).execute()
            return READING

        with mock.patch.object(interpreter, "prepare_image", wraps=interpreter.prepare_image) as prepare:
            with mock.patch.dict(interpreter.INTERPRETERS, {"gemma": straightened_meanwhile}):
                interpreter.interpret_next()
            stale = self.doc(document)
            self.assertEqual((stale.interpretation_status, stale.proposal), ("vantar", None))
            interpreter.interpret_next()
        self.assertEqual(self.doc(document).interpretation_status, "klar")
        self.assertEqual([call.args[1:] for call in prepare.call_args_list], [(0, 2.5), (0, 3)])

    def test_a_turn_while_the_last_attempt_reads_is_no_attempt_and_the_new_angle_is_read(self):
        item, (document,) = self.uploaded()
        inbox.take(item, self.helper, over=False)
        self.login("hjalp")
        self.answer = interpreter.InterpretationError("slut på minne")
        interpreter.interpret_next()
        self.assertEqual(self.doc(document).attempts, 1)

        def straightened_meanwhile(image, schema):  # the last attempt: the handler straightens the photo
            resp = self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{document.id}", json={"straighten": 3})
            self.assertEqual(resp.status_code, 200, resp.get_json())
            return READING

        self.answer = READING
        with mock.patch.object(interpreter, "prepare_image", wraps=interpreter.prepare_image) as prepare:
            with mock.patch.dict(interpreter.INTERPRETERS, {"gemma": straightened_meanwhile}):
                interpreter.interpret_next()
            waiting = self.doc(document)
            self.assertEqual((waiting.interpretation_status, waiting.attempts, waiting.proposal), ("vantar", 0, None))
            interpreter.interpret_next()
        done = self.doc(document)
        self.assertEqual((done.interpretation_status, done.attempts), ("klar", 1))
        self.assertEqual([call.args[1:] for call in prepare.call_args_list], [(0, 0), (0, 3)])

    def test_off_reads_nothing(self):
        with mock.patch.object(settings.interpretation, "interpreter", "av"):
            _, (document,) = self.uploaded()
            self.assertEqual(self.doc(document).interpretation_status, "av")
            self.assertIsNone(interpreter.interpret_next())
        self.assertIsNone(interpreter.interpret_next())  # on again: an "av" document does not wait
        self.assertEqual(self.calls, [])

    def test_only_open_certificates_wait(self):
        item, (proof, dismissed) = self.uploaded(files=2)
        inbox.take(item, self.helper, over=False)
        self.login("hjalp")
        self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{proof.id}", json={"doc_type": "bevis"})
        self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{dismissed.id}", json={"dismissed": True})
        self.assertEqual(self.doc(proof).interpretation_status, "av")
        self.assertIsNone(interpreter.interpret_next())
        self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{proof.id}", json={"doc_type": "intyg"})
        self.assertEqual(self.doc(proof).interpretation_status, "vantar")
        self.assertEqual(interpreter.interpret_next(), proof.id)


class TestReinterpret(InterpretationTest):
    def reinterpret(self, item, document):
        return self.client.post(f"/api/v2/inkorg/{item.id}/dokument/{document.id}/tolka-igen")

    def test_the_handler_requeues_after_a_turn(self):
        item, (document,) = self.uploaded()
        interpreter.interpret_next()
        inbox.take(item, self.helper, over=False)
        self.login("hjalp")
        self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{document.id}", json={"rotation": 90})
        resp = self.reinterpret(item, document)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        body = resp.get_json()["document"]
        self.assertEqual((body["interpretation_status"], body["proposal"]), ("vantar", None))
        self.assertEqual(self.doc(document).attempts, 0)
        self.assertTrue(db.InboxEvent.select().where(db.InboxEvent.kind == "tolka_igen").exists())
        interpreter.interpret_next()
        self.assertEqual(self.doc(document).interpretation_status, "klar")

    def test_refused_for_anyone_but_the_handler(self):
        item, (document,) = self.uploaded()
        inbox.take(item, self.helper, over=False)
        self.login("mhjalp")
        self.assertEqual(self.reinterpret(item, document).status_code, 403)  # not their genebank
        self.login("man")
        self.assertEqual(self.reinterpret(item, document).status_code, 409)  # their genebank, held by another
        self.login("owner")
        self.assertEqual(self.reinterpret(item, document).status_code, 403)
        self.assertEqual(self.doc(document).attempts, 0)
        self.assertFalse(db.InboxEvent.select().where(db.InboxEvent.kind == "tolka_igen").exists())

    def test_refused_when_off_or_not_a_certificate(self):
        item, (document,) = self.uploaded()
        inbox.take(item, self.helper, over=False)
        self.login("hjalp")
        with mock.patch.object(settings.interpretation, "interpreter", "av"):
            self.assertEqual(self.reinterpret(item, document).status_code, 409)
        self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{document.id}", json={"doc_type": "bevis"})
        self.assertEqual(self.reinterpret(item, document).status_code, 409)


class TestSaleReading(InterpretationTest):
    """Rule 5 b (Jonas 2026-11-27): a queue certificate's seller and buyer are read in a second call of their own."""

    def test_a_queue_certificate_is_read_twice_and_both_readings_are_kept(self):
        _, (document,) = self.uploaded()
        self.sale = {**SALE, "kopare_telefon": "0701234567"}  # never asked for: dropped like any unknown key
        interpreter.interpret_next()
        (main_image, _), (sale_image, schema) = self.calls[0], self.sale_calls[0]
        self.assertEqual((sale_image, schema), (main_image, interpreter.SALE_SCHEMA))
        self.assertEqual(self.doc(document).interpretation, {**READING, "forsaljning": SALE})
        sale = self.doc(document).proposal["sale"]  # the seller and buyer for the sale panel (inbox_proposal)
        self.assertEqual((sale["buyer"]["name"], sale["date"]), ("Köpa Testsson", "2024-06-01"))

    def test_a_report_photo_is_read_once(self):
        item, (document,) = self.uploaded()
        db.InboxItem.update(kind="kontroll", ref_type="individual").where(db.InboxItem.id == item.id).execute()
        self.sale = SALE
        self.assertEqual(interpreter.interpret_next(), document.id)
        self.assertEqual((len(self.calls), self.sale_calls), (1, []))
        self.assertEqual(self.doc(document).interpretation, READING)

    def test_a_failed_or_empty_second_reading_leaves_the_first(self):
        _, documents = self.uploaded(files=3)
        answers = (interpreter.InterpretationError("slut på tid"), {"kopare_namn": "  "}, ["inget objekt"])
        for n, (document, answer) in enumerate(zip(documents, answers, strict=True)):
            with self.subTest(n=n):
                self.sale = answer
                self.assertEqual(interpreter.interpret_next(), document.id)
                done = self.doc(document)
                self.assertEqual((done.interpretation_status, done.interpretation), ("klar", READING))
        self.assertEqual(len(self.sale_calls), 3)

    def test_no_sale_reading_lands_on_a_document_finished_while_the_model_read(self):
        item, (dismissed, sold, closed) = self.uploaded(files=3)
        meanwhile = {
            dismissed.id: db.InboxDocument.update(done_at=inbox.now()).where(db.InboxDocument.id == dismissed.id),
            sold.id: db.InboxDocument.update(herd_tracking_id=1).where(db.InboxDocument.id == sold.id),
            closed.id: db.InboxItem.update(closed_at=inbox.now()).where(db.InboxItem.id == item.id),
        }
        for document in (dismissed, sold, closed):
            with self.subTest(document=document.id):

                def finished_meanwhile(image, schema, document=document):
                    if schema is interpreter.SCHEMA:
                        return READING
                    meanwhile[document.id].execute()
                    return SALE

                with mock.patch.dict(interpreter.INTERPRETERS, {"gemma": finished_meanwhile}):
                    self.assertEqual(interpreter.interpret_next(), document.id)
                self.assertEqual(self.doc(document).interpretation, READING)

    def test_contact_fields_that_are_not_what_they_say_are_dropped(self):
        _, (wrong, right) = self.uploaded(files=2)
        answers = (
            {
                "kopare_namn": "Köpa Testsson",
                "kopare_utdelningsadress": "Väg 1 070-123 45 67",  # a phone number after the street
                "kopare_postnummer": "6235",
                "kopare_ort": "Visby",
                "kopare_epost": "070 123 45 67",
            },
            {"kopare_utdelningsadress": "Väg 1", "kopare_postnummer": "62355", "kopare_epost": "kopa@example.com"},
        )
        for document, answer in zip((wrong, right), answers, strict=True):
            self.sale = answer
            self.assertEqual(interpreter.interpret_next(), document.id)
        self.assertEqual(
            self.doc(wrong).interpretation["forsaljning"], {"kopare_namn": "Köpa Testsson", "kopare_ort": "Visby"}
        )
        self.assertEqual(self.doc(right).interpretation["forsaljning"], answers[1])

    def test_a_phone_number_in_any_shape_is_dropped(self):
        _, (document,) = self.uploaded()
        self.sale = {
            "kopare_namn": "Köpa Testsson",
            "kopare_utdelningsadress": "Väg 1 0046 70 123 45 67",  # international, after the street
            "kopare_ort": "Visby 070\u2010123\u00a045\u00a067",  # a Unicode hyphen and no-break spaces
            "kopare_besattning": "070\u2212123 45 67",  # a minus sign
        }
        interpreter.interpret_next()
        self.assertEqual(self.doc(document).interpretation["forsaljning"], {"kopare_namn": "Köpa Testsson"})

    def test_a_seller_herd_that_is_no_herd_number_is_dropped(self):
        _, (kept, dropped) = self.uploaded(files=2)
        for document, herd in ((kept, " g 9002 "), (dropped, "Testgården")):
            self.sale = {"kopare_namn": "Köpa Testsson", "saljare_besattning": herd}
            self.assertEqual(interpreter.interpret_next(), document.id)
        self.assertEqual(self.doc(kept).interpretation["forsaljning"]["saljare_besattning"], " g 9002 ")
        self.assertNotIn("saljare_besattning", self.doc(dropped).interpretation["forsaljning"])

    def test_an_item_closed_before_the_claims_lock_is_not_claimed(self):
        item, (document,) = self.uploaded()
        real, closed = interpreter._locked, []  # pylint: disable=protected-access

        def closed_first(document_id, item_id):  # the claim read the queue before it took the lock
            if not closed:
                closed.append(True)
                db.InboxItem.update(state="skrap", closed_at=inbox.now()).where(db.InboxItem.id == item.id).execute()
            return real(document_id, item_id)

        with mock.patch.object(interpreter, "_locked", closed_first):
            self.assertIsNone(interpreter.interpret_next())
        self.assertEqual((self.calls, self.doc(document).attempts, self.doc(document).interpretation), ([], 0, None))

    def test_a_close_logged_right_after_the_claim_is_seen_after_a_reopen(self):
        item, (document,) = self.uploaded()
        inbox.take(item, self.helper, over=False)
        closed = []

        def close_once():
            if not closed:
                closed.append(True)
                with db.DB_PROXY.atomic():
                    inbox.change_state(inbox.lock_item(item.id), self.helper, "skrap")

        real_now, real_close = interpreter.datetime.now, db.DB_PROXY.obj.close

        class Clock(interpreter.datetime):  # the first thing after the claim's unlock: its clock, or closing
            @classmethod
            def now(cls, tz=None):
                if not db.DB_PROXY.in_transaction():
                    close_once()
                return real_now(tz)

        def close_then_disconnect(*args, **kwargs):
            close_once()
            return real_close(*args, **kwargs)

        def reopened_while_reading(image, schema):
            if schema is interpreter.SCHEMA:
                with db.DB_PROXY.atomic():
                    inbox.change_state(inbox.lock_item(item.id), self.manager, "tagen")  # "Öppna igen"
                return READING
            return SALE

        with (
            mock.patch.object(interpreter, "datetime", Clock),
            mock.patch.object(db.DB_PROXY.obj, "close", close_then_disconnect),
            mock.patch.dict(interpreter.INTERPRETERS, {"gemma": reopened_while_reading}),
        ):
            self.assertEqual(interpreter.interpret_next(), document.id)
        self.assertEqual((closed, self.reload(item).state), ([True], "tagen"))
        self.assertEqual(self.doc(document).interpretation, READING)

    def test_an_erasure_during_the_sale_reading_ends_the_job_quietly(self):
        item, (document,) = self.uploaded()

        def erased_meanwhile(image, schema):
            if schema is interpreter.SCHEMA:
                return READING
            with db.DB_PROXY.atomic():
                erased = db.InboxDocument.get_by_id(document.id)
                inbox_purge.erase_document(inbox.lock_item(item.id), erased, self.manager)
            return SALE

        with mock.patch.dict(interpreter.INTERPRETERS, {"gemma": erased_meanwhile}):
            self.assertEqual(interpreter.interpret_next(), document.id)
        gone = self.doc(document)
        self.assertEqual((gone.original_path, gone.interpretation, gone.proposal), (None, None, None))

    def test_a_sale_filled_from_a_reading_that_is_gone_is_refused(self):
        item, (gone, kept) = self.uploaded(files=2)
        self.sale = SALE
        interpreter.interpret_next()
        inbox.take(item, self.manager, over=False)
        self.login("man")
        self.assertEqual(self.post(f"/{item.id}/lage", state="skrap").status_code, 200)
        self.assertEqual(self.post(f"/{item.id}/lage", state="tagen").status_code, 200)  # gone with the close
        interpreter.interpret_next()  # the other document, read after the reopen, keeps its seller and buyer
        self.assertIn("sale", self.doc(kept).proposal)
        body = {"individual": "G1-2111", "herd": "G2", "date": date.today().isoformat(), "from_photo": True}
        resp = self.post(f"/{item.id}/dokument/{gone.id}/overlat", **body)
        self.assertEqual(resp.status_code, 409, resp.get_json())
        self.assertEqual(resp.get_json()["detail"], "Läsningen har ändrats, fyll i köparen igen.")
        self.assertIsNone(self.doc(gone).herd_tracking_id)
        resp = self.post(f"/{item.id}/dokument/{gone.id}/overlat", **{**body, "from_photo": False})  # no check
        self.assertEqual(resp.status_code, 200, resp.get_json())
        body.update(individual="G2-2011", herd="G1")  # a sale from the document whose reading is still there
        resp = self.post(f"/{item.id}/dokument/{kept.id}/overlat", **body)
        self.assertEqual(resp.status_code, 200, resp.get_json())

    def test_a_worker_dying_in_the_second_reading_keeps_the_first(self):
        _, (document,) = self.uploaded()
        self.sale = SystemExit("the worker stopped")
        with self.assertRaises(SystemExit):
            interpreter.interpret_next()
        kept = self.doc(document)
        self.assertEqual((kept.interpretation_status, kept.attempts, kept.interpretation), ("klar", 1, READING))
        self.assertIsNone(interpreter.interpret_next())  # read: it does not wait again

    def test_a_reading_in_flight_over_a_close_and_a_reopen_brings_no_buyer_back(self):
        item, (document,) = self.uploaded()
        inbox.take(item, self.helper, over=False)

        def closed_and_reopened(image, schema):
            if schema is interpreter.SCHEMA:
                return READING
            with db.DB_PROXY.atomic():
                inbox.change_state(inbox.lock_item(item.id), self.helper, "skrap")
            with db.DB_PROXY.atomic():
                inbox.change_state(inbox.lock_item(item.id), self.manager, "tagen")  # "Öppna igen"
            return SALE

        with mock.patch.dict(interpreter.INTERPRETERS, {"gemma": closed_and_reopened}):
            self.assertEqual(interpreter.interpret_next(), document.id)
        self.assertEqual(self.reload(item).state, "tagen")
        self.assertEqual(self.doc(document).interpretation, READING)

    def test_tolka_igen_after_a_sale_reads_only_the_rabbit(self):
        item, (document,) = self.uploaded()
        self.sale = SALE
        interpreter.interpret_next()
        inbox.take(item, self.manager, over=False)
        self.login("man")
        body = {"individual": "G1-2111", "herd": "G2", "date": date.today().isoformat()}
        resp = self.client.post(f"/api/v2/inkorg/{item.id}/dokument/{document.id}/overlat", json=body)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        resp = self.client.post(f"/api/v2/inkorg/{item.id}/dokument/{document.id}/tolka-igen")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        interpreter.interpret_next()
        self.assertEqual((len(self.calls), len(self.sale_calls)), (2, 1))
        self.assertEqual(self.doc(document).interpretation, READING)

    def test_tolka_igen_reads_both_again(self):
        item, (document,) = self.uploaded()
        self.sale = SALE
        interpreter.interpret_next()
        inbox.take(item, self.helper, over=False)
        self.login("hjalp")
        resp = self.client.post(f"/api/v2/inkorg/{item.id}/dokument/{document.id}/tolka-igen")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertIsNone(self.doc(document).interpretation)
        self.sale = {**SALE, "kopare_namn": "Andra Testsson"}
        interpreter.interpret_next()
        self.assertEqual((len(self.calls), len(self.sale_calls)), (2, 2))
        self.assertEqual(self.doc(document).interpretation["forsaljning"]["kopare_namn"], "Andra Testsson")


class TestSaleReadingGoes(InterpretationTest):
    """
    The seller and buyer read off the photo are kept only while the queue may still save a sale from the document,
    and only the queue's workers, who see the photo itself, are served them.
    """

    def read(self, files=2):
        """An upload of `files` certificates, each read with its seller and buyer."""
        item, documents = self.uploaded(files=files)
        self.sale = SALE
        for _ in documents:
            interpreter.interpret_next()
        self.assertTrue(all("sale" in self.doc(d).proposal for d in documents))
        return item, documents

    def assertGone(self, document):  # pylint: disable=invalid-name
        """The sale part is gone from the reading and the proposal; the rabbit's stays."""
        gone = self.doc(document)
        self.assertEqual(gone.interpretation, READING)
        self.assertEqual(set(gone.proposal), {"fields", "checks"})

    def test_a_sale_saved_from_the_document(self):
        item, (sold, other) = self.read()
        inbox.take(item, self.manager, over=False)
        self.login("man")
        body = {"individual": "G1-2111", "herd": "G2", "date": date.today().isoformat()}
        resp = self.client.post(f"/api/v2/inkorg/{item.id}/dokument/{sold.id}/overlat", json=body)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertNotIn("sale", resp.get_json()["document"]["proposal"])
        self.assertGone(sold)
        self.assertIn("sale", self.doc(other).proposal)  # another document of the item may still show a sale

    def test_a_document_dismissed(self):
        item, (dismissed, other) = self.read()
        inbox.take(item, self.helper, over=False)
        self.login("hjalp")
        resp = self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{dismissed.id}", json={"dismissed": True})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertGone(dismissed)
        self.assertIn("sale", self.doc(other).proposal)

    def test_a_document_done_without_a_sale(self):
        item, (masked, other) = self.read()
        inbox.take(item, self.helper, over=False)
        self.login("hjalp")
        body = {
            "action": "pappersintyg",
            "individual": "G1-2112",
            "paper_certificate": "P-1",
            "paper_number": "G1-2112",
        }
        resp = self.client.post(f"/api/v2/inkorg/{item.id}/dokument/{masked.id}/spara", json=body)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertIn("sale", self.doc(masked).proposal)  # saved, not done: the sale may still be registered
        body = {"rotation": 0, "mask_rects": [], "no_personal_data": True}
        resp = self.client.post(f"/api/v2/inkorg/{item.id}/dokument/{masked.id}/maskning", json=body)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertGone(masked)
        self.assertIn("sale", self.doc(other).proposal)

    def test_the_item_closed(self):
        item, documents = self.read()
        inbox.take(item, self.helper, over=False)
        self.login("hjalp")
        resp = self.client.post(f"/api/v2/inkorg/{item.id}/lage", json={"state": "skrap"})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        for document in documents:
            self.assertGone(document)

    def test_the_item_closed_as_klar_by_its_last_document(self):
        item, (done, last) = self.read()
        # done before done removed the reading: the item's closing ("klar") takes it
        db.InboxDocument.update(done_at=inbox.now()).where(db.InboxDocument.id == done.id).execute()
        inbox.take(item, self.helper, over=False)
        self.login("hjalp")
        resp = self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{last.id}", json={"dismissed": True})
        self.assertEqual((resp.status_code, self.reload(item).state), (200, "klar"))
        self.assertGone(done)

    def test_a_document_retyped_off_intyg(self):
        item, documents = self.read(files=3)
        inbox.take(item, self.helper, over=False)
        self.login("hjalp")
        for document, doc_type in zip(documents, ("bevis", "arsblankett", "annat"), strict=True):
            with self.subTest(doc_type):
                resp = self.client.patch(
                    f"/api/v2/inkorg/{item.id}/dokument/{document.id}", json={"doc_type": doc_type}
                )
                self.assertEqual(resp.status_code, 200, resp.get_json())
                self.assertNotIn("sale", resp.get_json()["document"]["proposal"])
                self.assertGone(document)

    def test_only_the_queue_is_served_it(self):
        item, _ = self.read(files=1)
        self.login("hjalp")
        resp = self.client.get(f"/api/v2/inkorg/{item.id}")
        self.assertEqual(resp.get_json()["documents"][0]["proposal"]["sale"]["buyer"]["name"], "Köpa Testsson")
        self.login("owner")  # the sender: her own list, and never the item
        for path, status in ((f"/api/v2/inkorg/{item.id}", 403), ("/api/v2/inkorg/mina-inskick", 200)):
            with self.subTest(path):
                resp = self.client.get(path)
                self.assertEqual(resp.status_code, status)
                self.assertNotIn("Testsson", resp.get_data(as_text=True))
                self.assertNotIn("kopa@example.com", resp.get_data(as_text=True))


class TestTooSmall(InterpretationTest):
    """A photo too small for the handwriting is not read by itself (MIN_READ_SIDE); "Tolka igen" reads it anyway."""

    def test_a_small_photo_waits_for_the_handler(self):
        self.login("owner")
        small = encoded(photo(size=(800, 1600)))  # the longer side is enough, the shorter is not
        resp = self.upload(("intyg.jpg", small), ("stort.jpg", encoded(photo())), accept_warnings="1")
        self.assertEqual(resp.status_code, 201, resp.get_json())
        item = db.InboxItem.get_by_id(resp.get_json()["item"]["id"])
        document, large = item.documents.order_by(db.InboxDocument.id)
        self.assertEqual((document.interpretation_status, large.interpretation_status), ("for_litet", "vantar"))
        self.assertEqual(interpreter.interpret_next(), large.id)
        self.assertIsNone(interpreter.interpret_next())
        self.assertEqual((len(self.calls), len(self.sale_calls)), (1, 1))  # nor its seller and buyer
        inbox.take(item, self.helper, over=False)
        self.login("hjalp")
        # Turned into another type and back, it is still too small: the type does not decide it.
        for doc_type, status in (("bevis", "av"), ("intyg", "for_litet")):
            self.client.patch(f"/api/v2/inkorg/{item.id}/dokument/{document.id}", json={"doc_type": doc_type})
            self.assertEqual(self.doc(document).interpretation_status, status)
        resp = self.client.post(f"/api/v2/inkorg/{item.id}/dokument/{document.id}/tolka-igen")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(interpreter.interpret_next(), document.id)
        self.assertEqual(self.doc(document).interpretation_status, "klar")

    def test_the_limit_is_the_shorter_side(self):
        sides = (interpreter.MIN_READ_SIDE - 1, interpreter.MIN_READ_SIDE)
        self.assertEqual(interpreter.initial_status({"short_side": sides[0]}), "for_litet")
        self.assertEqual(interpreter.initial_status({"short_side": sides[1]}), "vantar")
        self.assertEqual(interpreter.initial_status(None), "vantar")  # not measured: read as before
        with mock.patch.object(settings.interpretation, "interpreter", "av"):
            self.assertEqual(interpreter.initial_status({"short_side": 10}), "av")


class TestStatus(InterpretationTest):
    def test_waiting_last_done_and_the_alarm(self):
        _, documents = self.uploaded(files=4)
        self.login("hjalp")
        status = self.client.get("/api/v2/inkorg").get_json()["interpretation"]
        self.assertEqual(status, {"interpreter": "gemma", "waiting": 4, "last_done_at": None, "alarm": False})
        interpreter.interpret_next()
        self.answer = interpreter.InterpretationError("slut på minne")
        for _ in range(6):  # three documents, two attempts each
            interpreter.interpret_next()
        status = self.client.get("/api/v2/inkorg").get_json()["interpretation"]
        self.assertEqual((status["waiting"], status["alarm"]), (0, True))
        self.assertEqual(status["last_done_at"], self.doc(documents[0]).interpreted_at.isoformat())
        with mock.patch.object(settings.interpretation, "interpreter", "av"):  # turned off: no alarm to act on
            status = self.client.get("/api/v2/inkorg").get_json()["interpretation"]
        self.assertEqual((status["interpreter"], status["alarm"]), ("av", False))
