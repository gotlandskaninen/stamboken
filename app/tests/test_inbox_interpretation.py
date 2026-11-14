"""The image reading as a job: one document a run, two attempts, no transaction while the model reads, "Tolka igen".

The interpreter is a fake that returns canned dicts; no model runs.

isort:skip_file
"""

from unittest import mock

import utils.database as db  # noqa: E402
import utils.inbox as inbox  # noqa: E402
import utils.inbox_interpreter as interpreter  # noqa: E402
import utils.settings as settings  # noqa: E402

from tests.inbox_fixtures import InboxTest, encoded, photo  # noqa: E402

READING = {"genbanksnr": "G1", "ar_kull_individ": "2111", "namn": "Testa", "overstruket": []}


class InterpretationTest(InboxTest):
    def setUp(self):
        super().setUp()
        self.calls = []
        self.answer = READING
        for patcher in (
            mock.patch.object(settings.interpretation, "interpreter", "gemma"),
            mock.patch.dict(interpreter.INTERPRETERS, {"gemma": self.fake}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake(self, image, schema):
        """The model: records the call, checks that nothing of the database is held, and answers."""
        self.assertTrue(db.DB_PROXY.is_closed(), "a connection is open while the model reads")
        self.calls.append((image, schema))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

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
        self.assertEqual(self.reinterpret(item, document).status_code, 409)
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
