"""The colour atlas API: colours from the database, texts and photos from a package under PRIVATE_UPLOAD_FOLDER."""

import json
import os
import shutil
import tempfile
from unittest import mock

import utils.database as db
import utils.settings as settings
from herdbook import APP, limiter
from utils.fargatlas import ATLAS_FARGER, seed_colors

from tests.database_test import DatabaseTest

# Made up for the tests: no atlas text, photo or photographer from the real package.
MANIFEST = {
    "version": "test",
    "grupper": {"testgrupp-a": {"beskrivning": "Testtext om en grupp."}},
    "farger": {
        "22": {
            "beskrivning": "Testbeskrivning av viltgrå.",
            "skiljs_fran": "Testskillnad mot viltgul.",
            "foton": [
                {"id": "22-a", "fotograf": "Test Fotograf", "bildtext": "Testbild", "far_anvandas": "ja"},
                {"id": "../22-b", "fotograf": None, "bildtext": None},
            ],
        },
        "11": None,
    },
    "nyckel": {
        "version": "test",
        "start": "q1",
        "fragor": {"q1": {"text": "Testfråga?", "svar": [{"id": "q1-ja", "text": "Ja", "till": 22}]}},
        "efter_numret": [],
        "grupper": [{"id": "testgrupp", "namn": "Testgrupp", "nummer": [22]}],
    },
}
JPEG = {"22-a.jpg": b"\xff\xd8 stor", "22-a-480.jpg": b"\xff\xd8 liten", "23-a.jpg": b"\xff\xd8 utan post"}


class FargatlasTest(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        db.Individual.update(color=None).execute()
        db.Color.delete().execute()
        seed_colors(*self.genebanks)
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        for patcher in (
            mock.patch.object(settings.service, "private_upload_folder", self.folder),
            mock.patch.object(limiter, "enabled", False),  # a login per test
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.paket = os.path.join(self.folder, "fargatlas")

    def package(self, manifest=MANIFEST):
        os.makedirs(self.paket, exist_ok=True)
        with open(os.path.join(self.paket, "fargatlas.json"), "w", encoding="utf-8") as out:
            out.write(manifest if isinstance(manifest, str) else json.dumps(manifest))
        for name, content in JPEG.items():
            with open(os.path.join(self.paket, name), "wb") as out:
                out.write(content)

    def login(self):
        response = self.client.post("/api/login", json={"username": "spec", "password": "pass"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

    def atlas(self):
        response = self.client.get("/api/v2/fargatlas")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def test_anonym_401(self):
        self.package()
        for url in ("/api/v2/fargatlas", "/api/v2/fargatlas/foto/22-a?storlek=480"):
            with self.subTest(url):
                self.assertEqual(self.client.get(url).status_code, 401)

    def test_lista_37(self):
        self.package()
        self.login()
        atlas = self.atlas()
        self.assertEqual((atlas["version"], atlas["grupper"]), ("test", MANIFEST["grupper"]))
        self.assertEqual(atlas["nyckel"], MANIFEST["nyckel"])  # the key is passed on as ops built it
        self.assertEqual([c["id"] for c in atlas["farger"]], sorted(id_ for id_, *_ in ATLAS_FARGER))
        farger = {c["id"]: c for c in atlas["farger"]}
        self.assertEqual(
            farger[22],
            {
                "id": 22,
                "name": "Viltgrå",
                "comment": "Varierar, kan vara ljus till mörk, kallas även hargrå",
                "genebank": self.genebanks[0].name,
                "beskrivning": "Testbeskrivning av viltgrå.",
                "skiljs_fran": "Testskillnad mot viltgul.",
                # only the fields the page shows, and only ids the photo endpoint serves
                "foton": [{"id": "22-a", "fotograf": "Test Fotograf", "bildtext": "Testbild"}],
            },
        )
        self.assertEqual((farger[11]["beskrivning"], farger[11]["foton"]), (None, []))  # null in the manifest

    def test_utan_paket_200(self):
        self.login()
        atlas = self.atlas()
        self.assertEqual(
            (atlas["version"], atlas["grupper"], atlas["nyckel"], len(atlas["farger"])), (None, {}, None, len(ATLAS_FARGER))
        )
        self.assertTrue(all(c["beskrivning"] is None and c["foton"] == [] for c in atlas["farger"]))

    def test_ogiltigt_manifest_loggas(self):
        for manifest in ("{inte json", "[]", '{"farger": []}'):
            with self.subTest(manifest):
                self.package(manifest)
                self.login()
                with self.assertLogs("utils.fargatlas", "ERROR"):
                    atlas = self.atlas()
                self.assertEqual(len(atlas["farger"]), len(ATLAS_FARGER))
                self.assertEqual(self.client.get("/api/v2/fargatlas/foto/22-a").status_code, 404)

    def test_feltypade_poster_loggas_och_utesluts(self):
        manifest = {
            "version": 3,
            "grupper": {"testgrupp-a": "text", "testgrupp-b": {"beskrivning": ["lista"]}},
            "farger": {
                **MANIFEST["farger"],
                "23": "se 25",
                "24": {"beskrivning": {"text": "fel"}, "skiljs_fran": 7, "foton": "23-a"},
                "25": {"foton": [{"id": 25}, "25-a", {"id": "25-a", "fotograf": ["fel"]}]},
            },
        }
        self.package(manifest)
        for name in ("25-a.jpg", "25-a-480.jpg"):
            with open(os.path.join(self.paket, name), "wb") as out:
                out.write(b"\xff\xd8 25")
        self.login()
        with self.assertLogs("utils.fargatlas", "ERROR") as logs:
            atlas = self.atlas()
        self.assertIn("23", logs.output[0])
        farger = {c["id"]: c for c in atlas["farger"]}
        self.assertEqual(farger[22]["beskrivning"], "Testbeskrivning av viltgrå.")  # the good entries stay
        self.assertEqual((farger[23]["beskrivning"], farger[23]["foton"]), (None, []))
        self.assertEqual((farger[24]["beskrivning"], farger[24]["skiljs_fran"], farger[24]["foton"]), (None, None, []))
        self.assertEqual(farger[25]["foton"], [{"id": "25-a", "fotograf": None, "bildtext": None}])
        self.assertEqual((atlas["version"], atlas["grupper"]), (None, {"testgrupp-b": {"beskrivning": None}}))
        with self.assertNoLogs("utils.fargatlas", "ERROR"):  # logged once by the page, not once per photo
            self.assertEqual(self.client.get("/api/v2/fargatlas/foto/22-a").status_code, 200)

    def test_nyckel_av_fel_form_loggas(self):
        hel = MANIFEST["nyckel"]
        fragor = hel["fragor"]
        for nyckel in (
            "text",
            {**hel, "start": 1},
            {**hel, "fragor": []},
            {**hel, "grupper": [{"id": "testgrupp", "namn": "Testgrupp"}]},  # no nummer
            {**hel, "grupper": [None]},
            {**hel, "fragor": {"q1": {**fragor["q1"], "svar": [{"id": "q1-ja", "text": "Ja", "till": None}]}}},
            {**hel, "fragor": {"q1": {**fragor["q1"], "svar": [None]}}},
            {**hel, "efter_numret": {}},
            {**hel, "fragor": {"q1": {**fragor["q1"], "hjalp": {"text": "fel"}}}},
            {  # two answers with one id
                **hel,
                "fragor": {
                    "q1": {
                        **fragor["q1"],
                        "svar": [{"id": "q1-a", "text": "A", "till": 22}, {"id": "q1-a", "text": "B", "till": 11}],
                    }
                },
            },
        ):
            with self.subTest(nyckel=nyckel):
                self.package({**MANIFEST, "nyckel": nyckel})
                self.login()
                with self.assertLogs("utils.fargatlas", "ERROR"):
                    atlas = self.atlas()
                self.assertIsNone(atlas["nyckel"])
                self.assertEqual(len(atlas["farger"]), len(ATLAS_FARGER))  # the colours stay

    def test_for_djupt_manifest_loggas(self):
        self.package()
        self.login()
        with mock.patch("utils.fargatlas.json.load", side_effect=RecursionError):
            with self.assertLogs("utils.fargatlas", "ERROR"):
                atlas = self.atlas()
        self.assertEqual(len(atlas["farger"]), len(ATLAS_FARGER))  # the database's colours still come

    def test_foto_ok(self):
        self.package()
        self.login()
        for storlek, content in (("480", JPEG["22-a-480.jpg"]), ("1600", JPEG["22-a.jpg"]), (None, JPEG["22-a.jpg"])):
            with self.subTest(storlek):
                query = f"?storlek={storlek}" if storlek else ""
                response = self.client.get(f"/api/v2/fargatlas/foto/22-a{query}")
                self.assertEqual((response.status_code, response.mimetype), (200, "image/jpeg"))
                self.assertEqual(response.get_data(), content)
                self.assertEqual(response.headers["Cache-Control"], "private, max-age=86400")
                response.close()

    def test_foto_okant_404(self):
        self.package()
        self.login()
        for url in ("/api/v2/fargatlas/foto/99-z", "/api/v2/fargatlas/foto/22-a?storlek=800"):
            with self.subTest(url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_foto_saknad_fil_404(self):
        self.package()
        os.remove(os.path.join(self.paket, "22-a-480.jpg"))
        self.login()
        self.assertEqual(self.client.get("/api/v2/fargatlas/foto/22-a?storlek=480").status_code, 404)
        # the size still on disk is not served either: the page does not show the photo
        self.assertEqual(self.client.get("/api/v2/fargatlas/foto/22-a?storlek=1600").status_code, 404)
        # and the card says "Foto saknas" instead of showing a broken image
        self.assertEqual({c["id"]: c for c in self.atlas()["farger"]}[22]["foton"], [])

    def test_foto_traversal_404(self):
        self.package()
        with open(os.path.join(self.folder, "hemlig.jpg"), "wb") as out:
            out.write(b"\xff\xd8 hemlig")
        self.login()
        for foto_id in ("..", "../hemlig", "..%2Fhemlig", "%2E%2E%2Fhemlig", "22-a%2F", "..%2F22-b"):
            with self.subTest(foto_id):
                response = self.client.get(f"/api/v2/fargatlas/foto/{foto_id}")
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(b"hemlig", response.get_data())

    def test_foto_utan_manifestpost_404(self):
        self.package()
        self.login()
        self.assertEqual(self.client.get("/api/v2/fargatlas/foto/23-a").status_code, 404)  # the file is on disk

    def test_seedens_testpaket(self):
        from cli.seed import _fargatlas_paket  # pylint: disable=import-outside-toplevel

        self.assertTrue(_fargatlas_paket())
        self.login()
        atlas = self.atlas()
        self.assertEqual(atlas["version"], "test")
        self.assertTrue(all(c["beskrivning"].startswith("Påhittad") for c in atlas["farger"]))
        self.assertEqual(atlas["nyckel"]["start"], "q1")  # a made-up key, so e2e can walk the guide
        foton = [f["id"] for c in atlas["farger"] for f in c["foton"]]
        self.assertEqual(foton, ["11-a", "22-a", "31-a", "42-a", "100-a"])
        for storlek in ("480", "1600"):
            self.assertEqual(self.client.get(f"/api/v2/fargatlas/foto/42-a?storlek={storlek}").status_code, 200)

        with open(os.path.join(self.paket, "fargatlas.json"), "w", encoding="utf-8") as out:
            out.write('{"version": "riktigt", "farger": {}}')
        self.assertFalse(_fargatlas_paket())  # a package already there is left alone
        self.assertEqual(self.atlas()["version"], "riktigt")

        # A folder without a manifest (a copy that stopped halfway) is left alone too: its photos are not replaced.
        os.remove(os.path.join(self.paket, "fargatlas.json"))
        with open(os.path.join(self.paket, "22-a.jpg"), "wb") as out:
            out.write(b"\xff\xd8 riktig")
        self.assertFalse(_fargatlas_paket())
        with open(os.path.join(self.paket, "22-a.jpg"), "rb") as photo:
            self.assertEqual(photo.read(), b"\xff\xd8 riktig")
        self.assertEqual([n for n in os.listdir(self.folder) if n.startswith(".fargatlas-")], [])

    def test_seed_create_overlever_en_skrivskyddad_mapp(self):
        from cli.seed import create_seed_data  # pylint: disable=import-outside-toplevel

        db.Color.delete().execute()  # the seed's genebanks get the atlas numbers
        with mock.patch("cli.seed._fargatlas_paket", side_effect=PermissionError("skyddat")):
            result = APP.test_cli_runner().invoke(create_seed_data)
        self.assertEqual(result.exit_code, 0, f"{result.output} {result.exception!r}")
        self.assertIn("Colour atlas test package not written", result.output)
        self.assertTrue(db.Herd.select().where(db.Herd.herd == "G1274").exists())  # the seed itself stayed

    def test_foto_har_ingen_adressgrans(self):  # a page is some 35 photos, and members may share an address
        self.package()
        self.login()
        limiter.reset()
        limiter.enabled = True
        self.addCleanup(limiter.reset)
        photos = []
        for _ in range(110):
            response = self.client.get("/api/v2/fargatlas/foto/22-a?storlek=480")
            photos.append(response.status_code)
            response.close()
        self.assertEqual(set(photos), {200})
        pages = [self.client.get("/api/v2/fargatlas").status_code for _ in range(101)]
        self.assertEqual(pages[-1], 429)  # the rest of the API keeps the default limit
