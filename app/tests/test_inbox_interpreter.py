"""The image reading's interpreter interface: the Ollama request, the setting that turns it off, bad answers.

No model runs here: the HTTP call is faked.
"""

import base64
import io
import json
import unittest
from unittest import mock

import requests
import utils.inbox_interpreter as interpreter
import utils.mail as mail
import utils.settings as settings
from PIL import Image, ImageDraw, ImageStat


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

    def test_the_seller_and_buyer_have_a_schema_and_a_prompt_of_their_own(self):
        with mock.patch.object(requests, "post", return_value=_answer(json.dumps({"datum": "240601"}))) as post:
            self.assertEqual(interpreter.interpret(b"jpeg-bytes", interpreter.SALE_SCHEMA), {"datum": "240601"})
            interpreter.interpret(b"jpeg-bytes")
        sale, main = [call.kwargs["json"] for call in post.call_args_list]
        self.assertEqual(
            (sale["format"], sale["messages"][0]["content"]), (interpreter.SALE_SCHEMA, interpreter.SALE_PROMPT)
        )
        self.assertEqual((main["format"], main["messages"][0]["content"]), (interpreter.SCHEMA, interpreter.PROMPT))
        self.assertIn("Säljarens och köparens uppgifter ska inte skrivas av.", interpreter.PROMPT)
        self.assertIn("Skriv inte av telefonnumret.", interpreter.SALE_PROMPT)
        self.assertNotIn("kopare", json.dumps(interpreter.SCHEMA))
        # Flat strings, and never a phone number.
        self.assertEqual({p["type"] for p in interpreter.SALE_SCHEMA["properties"].values()}, {"string"})
        self.assertNotIn("telefon", json.dumps(interpreter.SALE_SCHEMA))
        # The seller's name is of no use to the sale: never read.
        self.assertNotIn("saljare_namn", interpreter.SALE_SCHEMA["properties"])
        self.assertIn("Säljaren: besättningsnummer", interpreter.SALE_PROMPT)

    def test_the_sale_answer_is_held_to_its_schema(self):
        answer = {
            "kopare_namn": "Köpa Testsson\x00",
            "kopare_postnummer": 62355,  # a number where a string belongs: missing
            "kopare_telefon": "0701234567",  # not asked for: dropped
            "saljare_namn": {"namn": "x"},
            "datum": "1/6-24",
        }
        self.assertEqual(
            interpreter.conform(answer, interpreter.SALE_SCHEMA), {"kopare_namn": "Köpa Testsson", "datum": "1/6-24"}
        )

    def test_the_schema_asks_for_the_certificate_number_and_for_no_list(self):
        self.assertIn("intygsnummer", interpreter.SCHEMA["required"])
        # A list has no end in the model's grammar: Gemma filled one until the answer was cut (trial 2026-11-15).
        self.assertNotIn("array", json.dumps(interpreter.SCHEMA))
        self.assertEqual(
            interpreter.SCHEMA["properties"]["mormor"]["required"], ["genbanksnr", "ar_kull_individ", "namn"]
        )

    def test_the_answer_is_held_to_the_schema(self):
        answer = {
            "genbanksnr": "G9001\x00",  # NUL: jsonb refuses it
            "ar_kull_individ": 2512,  # a number where a string belongs: missing
            "namn": "x" * 5000,
            "farg": "vit\ud800",  # a lone surrogate: not UTF-8
            "fodda_i_kullen": float("nan"),
            "kon": None,
            "mor": {"genbanksnr": "G9001", "ar_kull_individ": ["2211"], "namn": "Mira", "extra": "x"},
            "far": "G9003-2311",  # a string where an object belongs
            "overstruket": ["far", "mor"],  # no longer asked for: dropped like any unknown key
            "okand_nyckel": {"x": 1},
        }
        with mock.patch.object(requests, "post", return_value=_answer(json.dumps(answer))):
            conformed = interpreter.interpret(b"jpeg-bytes")
        self.assertEqual(
            conformed,
            {
                "genbanksnr": "G9001",
                "namn": "x" * interpreter.MAX_STRING,
                "farg": "vit",
                "mor": {"genbanksnr": "G9001", "namn": "Mira"},
            },
        )
        self.assertIsNone(interpreter.conform([], interpreter.SCHEMA))

    def test_conform_masks_a_token_after_normalizing_and_cutting(self):  # FA3
        with mock.patch.object(settings.mail, "link_secret", "test-link-secret"):
            token = mail.link_token("rapport", 12)
        row, secret = token.split(".")
        pad = "x" * (interpreter.MAX_STRING - len(token) - 1) + " "
        schema = {"type": "object", "properties": {"namn": {"type": "string"}}}
        for text in (token, f"{row}.{secret[:10]}\x00{secret[10:]}", f"{pad}{token}X"):
            with self.subTest(text=text[-30:]):
                kept = interpreter.conform({"namn": text}, schema)
                self.assertNotIn(secret, kept["namn"])

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

    def test_the_photo_is_turned_bounded_and_enhanced(self):
        # Pale green paper with pencil strokes in the top left corner; turned 90 degrees clockwise they are top right.
        photo = Image.new("RGB", (3000, 4000), (200, 230, 190))
        draw = ImageDraw.Draw(photo)
        for y in range(100, 500, 12):
            draw.line([(100, y), (500, y)], fill=(90, 90, 100), width=4)
        source = io.BytesIO()
        photo.save(source, "JPEG")
        for rotation, size in [(0, (1500, 2000)), (90, (2000, 1500)), (270, (2000, 1500))]:
            with self.subTest(rotation):
                source.seek(0)
                with Image.open(io.BytesIO(interpreter.prepare_image(source, rotation))) as prepared:
                    self.assertEqual((prepared.format, prepared.mode, prepared.size), ("JPEG", "L", size))
                    w, h = size

                    def mean(box):
                        return ImageStat.Stat(prepared.crop(box)).mean[0]

                    corners = {
                        "top left": mean((50, 50, 250, 250)),
                        "top right": mean((w - 250, 50, w - 50, 250)),
                        "bottom left": mean((50, h - 250, 250, h - 50)),
                    }
                written = {0: "top left", 90: "top right", 270: "bottom left"}[rotation]
                blank = [v for k, v in corners.items() if k != written]
                self.assertTrue(all(v > 240 for v in blank), corners)  # the paper turns white
                self.assertLess(corners[written], min(blank) - 50, corners)

    def test_a_small_photo_is_not_enlarged(self):
        source = io.BytesIO()
        Image.new("RGB", (800, 600), (220, 220, 220)).save(source, "PNG")
        source.seek(0)
        with Image.open(io.BytesIO(interpreter.prepare_image(source, 180))) as prepared:
            self.assertEqual(prepared.size, (800, 600))

    def test_a_second_interpreter_is_one_more_entry(self):
        with mock.patch.dict(interpreter.INTERPRETERS, {"annan": lambda image, schema: {"namn": "Testa"}}):
            with mock.patch.object(settings.interpretation, "interpreter", "annan"):
                self.assertEqual(interpreter.interpret(b"x"), {"namn": "Testa"})
