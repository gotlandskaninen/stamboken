"""`flask seed arsrapport`: the demo round for the trial run. Idempotent, synthetic, refuses production."""

import json
import os
import shutil
import tempfile
from collections import Counter
from datetime import date
from unittest import mock

import utils.arsrapport as arsrapport
import utils.database as db
import utils.report_code as report_code
import utils.settings as settings
from herdbook import APP

from tests.database_test import DatabaseTest
from tests.ht_helpers import ht_row

MODELS = (
    db.Herd,
    db.Individual,
    db.Breeding,
    db.HerdTracking,
    db.Member,
    db.Membership,
    db.User,
    db.YearlyReportRound,
    db.InboxItem,
    db.InboxDocument,
)


class SeedArsrapportTest(DatabaseTest):
    def setUp(self):
        super().setUp()
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        patcher = mock.patch.object(settings.service, "private_upload_folder", folder)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.folder = folder
        link_secret = mock.patch.object(settings.mail, "link_secret", "test-link-secret")
        link_secret.start()
        self.addCleanup(link_secret.stop)
        self.runner = APP.test_cli_runner()

    def seed(self, command="arsrapport"):
        result = self.runner.invoke(args=["seed", command])
        self.assertEqual(result.exit_code, 0, f"{result.output} {result.exception!r}")

    def counts(self):
        return {model.__name__: model.select().count() for model in MODELS}

    def test_idempotent_and_the_lists_of_the_round(self):
        self.seed("create")
        self.seed()
        first = self.counts()
        self.seed()
        self.assertEqual(self.counts(), first)

        herd = lambda code: db.Herd.get(db.Herd.herd == code)  # noqa: E731
        states = Counter(row["state"] for row in arsrapport.report_list(herd("G9001"), 2025))
        self.assertEqual(states, {"att_valja": 12, "via_flytt": 1})
        self.assertEqual(Counter(r["state"] for r in arsrapport.report_list(herd("G9004"), 2025)), {"att_valja": 183})
        paper = arsrapport.report_list(herd("G9002"), 2025)
        self.assertEqual((len(paper), sum(r["sex"] == "male" for r in paper)), (12, 1))
        self.assertEqual(arsrapport.account_end(herd("G9002")), "12")
        self.assertTrue(arsrapport.get_round(2025).deadline <= arsrapport.get_round(2025).end_date)
        self.assertFalse(db.YearlyReportRoundGenebank.select().exists())  # the manager activates it
        self.assertTrue(os.path.isfile(os.path.join(self.folder, arsrapport.BLANK_FORM)))
        item = db.InboxItem.get(db.InboxItem.herd == herd("G9002"))
        self.assertEqual(item.state, "ny")
        self.assertEqual([d.doc_type for d in item.documents], ["arsblankett"])
        for document in item.documents:
            self.assertTrue(os.path.isfile(os.path.join(self.folder, document.original_path)))

        # The Mellerud herds of the user-type tests: median and 90th-percentile sizes, three paper forms.
        sizes = {code: len(arsrapport.report_list(herd(code), 2025)) for code in ("M9001", "M9003", "M9004", "M9102")}
        self.assertEqual(sizes, {"M9001": 6, "M9003": 30, "M9004": 3, "M9102": 6})
        litter = db.Breeding.get(db.Breeding.breeding_herd_id == herd("M9001"), db.Breeding.birth_date == date(2025, 5, 2))
        self.assertEqual((litter.mother.sex, litter.father.sex, litter.litter_size), ("female", "male", 1))
        on_paper = sorted(i.herd.herd for i in db.InboxItem.select() if i.herd.herd.startswith("M"))
        self.assertEqual(on_paper, ["M9005", "M9006", "M9006", "M9102"])
        uppfodare = db.User.get(db.User.email == "seed-mk-uppfodare@test.local")
        codes = ("M9001", "M9002", "M9003", "M9004", "M9005", "M9006", "M9007", "M9101", "M9102")
        owned = [code for code in codes if arsrapport.report_access(uppfodare, herd(code))]
        self.assertEqual(owned, ["M9001", "M9002", "M9003", "M9004", "M9006", "M9007", "M9101"])

    def test_needs_seed_create_first(self):
        result = self.runner.invoke(args=["seed", "arsrapport"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("seed create", result.output)

    def test_refuses_in_production(self):
        self.seed("create")
        with mock.patch.dict(os.environ, {"FLASK_ENV": "production"}):
            result = self.runner.invoke(args=["seed", "arsrapport"])
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("production", result.output)
        self.assertFalse(db.Herd.select().where(db.Herd.herd == "G9001").exists())

    def test_refuses_in_the_demo(self):
        self.seed("create")
        with mock.patch.object(settings.service, "demo_instance", True):
            result = self.runner.invoke(args=["seed", "arsrapport"])
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("demo", result.output)
        self.assertFalse(db.Herd.select().where(db.Herd.herd == "G9001").exists())

    def test_seed_lankar_prints_a_working_link_per_herd(self):
        self.seed("create")
        self.seed()
        result = self.runner.invoke(args=["seed", "arsrapport-lankar"])
        self.assertEqual(result.exit_code, 0, f"{result.output} {result.exception!r}")
        links = json.loads(result.output)
        self.assertEqual(sorted(links), ["M9201", "M9202", "M9203"])
        for herd, link in links.items():
            self.assertRegex(link, r"^/rapport#\d+\.[A-Za-z0-9_-]{22}$")
            code = report_code.resolve(link.split("#")[1])
            self.assertEqual(code.herd.herd, herd)
            self.assertEqual(len(arsrapport.report_list(code.herd, 2025)), 6)
            self.assertIsNone(report_code.refusal(code, code.herd, today=arsrapport.today()))
        again = self.runner.invoke(args=["seed", "arsrapport-lankar"])
        self.assertEqual(json.loads(again.output), links)  # the active code is reused

    def test_seed_lankar_refused_in_production(self):
        self.seed("create")
        self.seed()
        with mock.patch.dict(os.environ, {"FLASK_ENV": "production"}):
            result = self.runner.invoke(args=["seed", "arsrapport-lankar"])
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("production", result.output)
        self.assertFalse(db.ReportAccessCode.select().exists())

    def test_seed_lankar_refused_in_the_demo(self):
        self.seed("create")
        self.seed()
        with mock.patch.object(settings.service, "demo_instance", True):
            result = self.runner.invoke(args=["seed", "arsrapport-lankar"])
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertFalse(db.ReportAccessCode.select().exists())

    def test_leaves_an_existing_herd_untouched(self):
        self.seed("create")
        gk = db.Genebank.get(db.Genebank.name == "Gotlandskanin")
        real = db.Herd.create(genebank=gk, herd="G9001", herd_name="Riktig", is_active=True)
        rabbit = db.Individual.create(origin_herd=real, number="G9001-2111", sex="female", name="Riktig kanin")
        ht_row("BIRTH", herd=real, individual=rabbit, herd_tracking_date=date(2021, 5, 1))
        owned = db.Individual.select().where(db.Individual.origin_herd == real.id).count()
        self.seed()
        self.assertEqual(db.Herd.get_by_id(real.id).herd_name, "Riktig")
        self.assertIsNone(db.Herd.get_by_id(real.id).membership_id)
        self.assertEqual(db.Individual.select().where(db.Individual.origin_herd == real.id).count(), owned)
        self.assertEqual(db.HerdTracking.select().where(db.HerdTracking.herd == real.id).count(), 1)
        self.assertFalse(db.User.get(db.User.email == "seed-gk-arsrapport@test.local").has_role("owner", real.id))
        self.assertTrue(db.Herd.select().where(db.Herd.herd == "G9004").exists())  # the missing herds are made

    def test_a_cleared_date_stays_cleared(self):
        self.seed("create")
        self.seed()
        dead = db.Individual.get(db.Individual.death_date.is_null(False), db.Individual.number.startswith("G9001-"))
        castrated = db.Individual.get(db.Individual.castration_date.is_null(False))
        db.Individual.update(death_date=None, death_note=None, castration_date=None).where(
            db.Individual.id.in_([dead.id, castrated.id])
        ).execute()
        self.seed()
        self.assertIsNone(db.Individual.get_by_id(dead.id).death_date)
        self.assertIsNone(db.Individual.get_by_id(castrated.id).castration_date)
