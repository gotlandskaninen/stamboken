"""The image reading's interpreter interface: the Ollama request, the setting that turns it off, bad answers.

No model runs here: the HTTP call is faked.
"""

import base64
import json
import unittest
from unittest import mock

import requests
import utils.inbox_interpreter as interpreter
import utils.settings as settings


def _answer(content, status=200):
    response = mock.Mock(status_code=status, text="")
    response.json.return_value = {"message": {"content": content}}
    response.raise_for_status.side_effect = requests.HTTPError(str(status)) if status >= 400 else None
    return response


class TestInterpreter(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(settings.interpretation, "interpreter", "gemma")
        patcher.start()
        self.addCleanup(patcher.stop)

    @mock.patch.object(settings.interpretation, "ollama_url", "http://ollama.invalid:11434")
    @mock.patch.object(settings.interpretation, "model", "testmodell")
    def test_gemma_asks_ollama_for_structured_output_against_the_schema(self):
        reading = {"genbanksnr": "G9001", "ar_kull_individ": "2512"}
        with mock.patch.object(requests, "post", return_value=_answer(json.dumps(reading))) as post:
            self.assertEqual(interpreter.interpret(b"jpeg-bytes"), reading)
        (url,), kwargs = post.call_args
        body = kwargs["json"]
        self.assertEqual(url, "http://ollama.invalid:11434/api/chat")
        self.assertEqual((body["model"], body["stream"], body["format"]), ("testmodell", False, interpreter.SCHEMA))
        self.assertEqual(body["options"]["temperature"], 0)
        self.assertEqual(body["messages"][0]["images"], [base64.b64encode(b"jpeg-bytes").decode()])
        self.assertGreaterEqual(kwargs["timeout"], 600)

    def test_the_schema_asks_for_the_certificate_number_and_what_was_struck_through(self):
        self.assertIn("intygsnummer", interpreter.SCHEMA["required"])
        self.assertIn("overstruket", interpreter.SCHEMA["required"])
        self.assertEqual(
            interpreter.SCHEMA["properties"]["mormor"]["required"], ["genbanksnr", "ar_kull_individ", "namn"]
        )

    def test_off_reads_nothing(self):
        for value in ("av", "okänd"):
            with self.subTest(value), mock.patch.object(settings.interpretation, "interpreter", value):
                self.assertFalse(interpreter.enabled())
                with mock.patch.object(requests, "post") as post, self.assertRaises(interpreter.InterpretationError):
                    interpreter.interpret(b"jpeg-bytes")
                post.assert_not_called()

    def test_an_unusable_answer_is_an_error(self):
        for name, response in [
            ("not json", _answer("inte json")),
            ("not an object", _answer("[1, 2]")),
            ("server error", _answer("{}", status=500)),
        ]:
            with self.subTest(name), mock.patch.object(requests, "post", return_value=response):
                with self.assertRaises(interpreter.InterpretationError):
                    interpreter.interpret(b"jpeg-bytes")
        with mock.patch.object(requests, "post", side_effect=requests.Timeout("slut på tid")):
            with self.assertRaises(interpreter.InterpretationError):
                interpreter.interpret(b"jpeg-bytes")

    def test_a_second_interpreter_is_one_more_entry(self):
        with mock.patch.dict(interpreter.INTERPRETERS, {"annan": lambda image, schema: {"namn": "Testa"}}):
            with mock.patch.object(settings.interpretation, "interpreter", "annan"):
                self.assertEqual(interpreter.interpret(b"x"), {"namn": "Testa"})
