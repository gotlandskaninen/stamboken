"""The reconciliation table (POST …/avstamning, utils/inbox_reconcile.py): what the handler typed off the paper,
beside the registry row by row, and the checks in words.

The synthetic registry of test_inbox_proposal: made-up herds G9001–G9004 in Gotland and M9005 in Mellerud. No real
certificate or number.
"""

from datetime import date

import utils.database as db

from tests.inbox_fixtures import InboxTest
from tests.test_inbox_proposal import ProposalTest

# The new rabbit G9001-2511, typed right: mother G9001-2211 (Mira), father G9003-2311 (Max).
TYPED = {
    "mode": "ny_kanin",
    "paper_number": "G9001-2511",
    "paper_certificate": "SYN-501",
    "name": "Testa",
    "sex": "female",
    "birth_date": "2025-05-10",
    "color": "bleighe",
    "litter_size": 5,
    "litter_size6w": "4",
    "mother": "G9001-2211",
    "father": "G9003-2311",
    "morfar": "G9004-2011",
    "mormor": "G9004-2112",
    "farfar": "G9003-2011",
    "farmor": "G9003-2112",
}


class ReconcileTest(InboxTest, ProposalTest):
    def setUp(self):
        super().setUp()
        self.queue_item = self.item()  # sent in for G1: Gotland's
        self.document = self.queue_item.documents.get()
        self.login("man")

    def reconcile(self, item=None, document=None, body=None, **typed):
        item, document = item or self.queue_item, document or self.document
        path = f"/api/v2/inkorg/{item.id}/dokument/{document.id}/avstamning"
        return self.client.post(path, json=typed if body is None else body)

    def answer(self, item=None, **changes):
        resp = self.reconcile(item, item and item.documents.get(), **{**TYPED, **changes})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        return resp.get_json()

    def row(self, answer, key):
        found = answer["rows"][key]
        return found["status"], found["registry"]

    def near(self, answer, key):
        return [rabbit["number"] for rabbit in answer["rows"][key].get("near", [])]

    def read(self, **fields):
        """The stored proposal: what the model read, field by field."""
        proposal = {"fields": {k: {"value": None, "source": "osäker", "read": v} for k, v in fields.items()}}
        db.InboxDocument.update(interpretation_status="klar", proposal={**proposal, "checks": []}).where(
            db.InboxDocument.id == self.document.id
        ).execute()


class TestNewRabbit(ReconcileTest):
    def test_typed_right_agrees_with_the_registry(self):
        answer = self.answer()
        self.assertNotIn("individual", answer["rows"])
        self.assertEqual(self.row(answer, "mother"), ("stammer", "G9001-2211 Mira"))
        self.assertEqual(self.row(answer, "father"), ("stammer", "G9003-2311 Max"))
        for key, number in (("morfar", "G9004-2011"), ("mormor", "G9004-2112"), ("farfar", "G9003-2011")):
            self.assertEqual(self.row(answer, key), ("stammer", number), key)
        self.assertEqual(self.row(answer, "paper_number"), ("stammer", "G9001-2511"))  # as its new litter gives it
        self.assertEqual(self.row(answer, "paper_certificate"), ("stammer", "ledigt"))
        self.assertEqual(self.row(answer, "color"), ("stammer", "bleighe"))
        for key in ("name", "sex", "birth_date", "litter_size", "litter_size6w"):  # no litter in Stamboken yet
            self.assertEqual(self.row(answer, key), ("ingen", None), key)
        for text in ("Mor och far finns i Stamboken.", "Numret stämmer med kullen.", "Intygsnumret är ledigt."):
            self.assertIn(text, self.texts(answer, True))
        self.assertEqual(self.texts(answer, False), [])

    def test_numbers_are_normalised_as_the_registry_writes_them(self):
        answer = self.answer(mother="g9001 2211", father=" G9003 - 2311", paper_number="g9001 2511")
        self.assertEqual(self.row(answer, "mother"), ("stammer", "G9001-2211 Mira"))
        self.assertEqual(self.row(answer, "father"), ("stammer", "G9003-2311 Max"))
        self.assertEqual(self.row(answer, "paper_number"), ("stammer", "G9001-2511"))

    def test_the_litter_in_stamboken_gives_the_date_and_counts(self):
        self.litter("G9001", "G9001-2211", "G9003-2311", date(2025, 5, 10), [], size=3)
        answer = self.answer(litter_size="3")
        self.assertEqual(self.row(answer, "birth_date"), ("stammer", "2025-05-10"))
        self.assertEqual(self.row(answer, "litter_size"), ("stammer", 3))
        self.assertEqual(self.row(answer, "litter_size6w"), ("skiljer", 3))  # 4 typed

    def test_a_number_its_litter_does_not_give_differs(self):
        answer = self.answer(paper_number="G9001-2521")  # the year's first litter, not its second
        self.assertEqual(self.row(answer, "paper_number"), ("skiljer", "G9001-2511"))
        self.assertIn("Individnumret stämmer inte med kullen. Stamboken ger G9001-2511.", self.texts(answer, False))

    def test_a_number_already_in_stamboken_differs(self):
        answer = self.answer(paper_number="G9003-2312")
        self.assertEqual(self.row(answer, "paper_number"), ("skiljer", "finns redan: G9003-2312 Mats"))

    def test_the_number_waits_for_mother_father_and_a_whole_date(self):
        for changes in ({"father": ""}, {"birth_date": "2025-05"}):
            with self.subTest(changes):
                answer = self.answer(**changes)
                self.assertEqual(self.row(answer, "paper_number"), ("ingen", None))
                self.assertIn(
                    "Individnumret går inte att pröva mot kullen utan mor, far och födelsedatum.", self.texts(answer)
                )

    def test_a_grandparent_that_is_not_the_parents_parent_differs(self):
        answer = self.answer(farfar="G9002-2011")
        self.assertEqual(self.row(answer, "farfar"), ("skiljer", "G9003-2011"))

    def test_a_grandparent_typed_as_its_own_parent(self):
        answer = self.answer(mormor="G9001-2211")
        self.assertIn("Mormor har samma nummer som mor.", self.texts(answer, False))

    def test_a_parent_of_the_wrong_sex_differs(self):
        answer = self.answer(mother="G9003-2311", morfar="", mormor="")
        self.assertEqual(self.row(answer, "mother"), ("skiljer", "G9003-2311 Max (hane)"))
        self.assertIn("Mor G9003-2311 är en hane i Stamboken.", self.texts(answer, False))

    def test_a_certificate_number_in_use_differs(self):
        answer = self.answer(paper_certificate="C-G9003-2312")
        self.assertEqual(self.row(answer, "paper_certificate"), ("skiljer", "G9003-2312"))
        self.assertIn("Intygsnumret C-G9003-2312 finns redan på G9003-2312.", self.texts(answer, False))

    def test_a_colour_not_in_the_list_differs(self):
        self.assertEqual(self.row(self.answer(color="Bleighe"), "color"), ("stammer", "bleighe"))
        self.assertEqual(self.row(self.answer(color="lila"), "color"), ("skiljer", "finns inte"))

    def test_a_letter_that_is_not_the_genebanks_is_named(self):
        answer = self.answer(paper_number="M9001-2511")
        self.assertIn(
            "Individnumret börjar med M på pappret, men genbankens nummer börjar med G.", self.texts(answer, False)
        )


class TestNearMatches(ReconcileTest):
    def test_a_number_not_found_lists_those_one_character_off(self):
        answer = self.answer(father="G9000-2311", farfar="", farmor="")  # one digit from G9002 and from G9003
        self.assertEqual(self.row(answer, "father"), ("skiljer", "finns inte"))
        self.assertEqual(sorted(self.near(answer, "father")), ["G9002-2311", "G9003-2311"])
        self.assertEqual(answer["rows"]["father"]["near"][0], {"number": "G9002-2311", "name": "Max", "sex": "male"})
        self.assertIn("Far G9000-2311 finns inte i Stamboken.", self.texts(answer, False))
        answer = self.answer(father="G9013-2311")  # a single one is listed too, never taken
        self.assertEqual(self.row(answer, "father"), ("skiljer", "finns inte"))
        self.assertEqual(self.near(answer, "father"), ["G9003-2311"])
        self.assertEqual(self.row(answer, "farfar"), ("ingen", "G9003-2011"))  # no father, nothing to compare
        answer = self.answer(father="G7777-2311")
        self.assertEqual(self.row(answer, "father"), ("skiljer", "finns inte"))
        self.assertNotIn("near", answer["rows"]["father"])


class TestGenebankScope(ReconcileTest):
    def test_only_the_items_genebank_is_searched(self):
        # M9003-2311 is not G9003-2311: a typed letter is never swapped for the genebank's.
        for number in ("M9003-2311", "M9005-2399", "G9005-2399"):
            with self.subTest(number):
                answer = self.answer(father=number)
                self.assertEqual(self.row(answer, "father"), ("skiljer", "finns inte"))
                self.assertNotIn("M9005-2399", self.near(answer, "father"))
        # On a Mellerud item nothing of Gotland is found, nor offered.
        mellerud = self.item(herd=2)
        answer = self.answer(item=mellerud)
        self.assertEqual(self.row(answer, "father"), ("skiljer", "finns inte"))
        self.assertEqual(self.near(answer, "father"), [])

    def test_a_certificate_in_another_genebank_is_not_named(self):
        db.Individual.update(certificate="SYN-999").where(db.Individual.number == "M9005-2399").execute()
        answer = self.answer(paper_certificate="SYN-999")
        self.assertEqual(self.row(answer, "paper_certificate"), ("skiljer", "används redan"))
        self.assertNotIn("M9005", " ".join(self.texts(answer)))

    def test_an_item_without_a_genebank_searches_the_one_its_letter_names(self):
        db.InboxItem.update(genebank=None).where(db.InboxItem.id == self.queue_item.id).execute()
        self.assertEqual(self.row(self.answer(), "mother"), ("stammer", "G9001-2211 Mira"))
        self.assertEqual(self.row(self.answer(paper_number="9001-2511"), "mother"), ("skiljer", "finns inte"))


class TestExistingRabbit(ReconcileTest):
    def setUp(self):
        super().setUp()
        rabbits = [
            ("G9001-2411", "female", "Elsa", {"certificate": "SYN-777"}),
            ("G9001-2412", "male", "Ebbe", {"certificate": None}),
        ]
        self.litter("G9001", "G9001-2211", "G9003-2311", date(2024, 4, 20), rabbits)
        db.Individual.update(color=self.colors[0]).where(db.Individual.number == "G9001-2411").execute()

    def existing(self, **changes):
        typed = {key: "" for key in TYPED} | {"mode": "pappersintyg", "individual": "g9001 2411"}
        resp = self.reconcile(**{**typed, **changes})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        return resp.get_json()

    def test_every_row_comes_from_the_rabbit(self):
        answer = self.existing()
        self.assertEqual(self.row(answer, "individual"), ("stammer", "G9001-2411 Elsa"))
        expected = {
            "paper_number": "G9001-2411",
            "paper_certificate": "SYN-777",
            "name": "Elsa",
            "sex": "female",
            "birth_date": "2024-04-20",
            "color": "bleighe",
            "litter_size": 2,
            "litter_size6w": 2,
            "mother": "G9001-2211 Mira",
            "father": "G9003-2311 Max",
            "morfar": "G9004-2011",
            "mormor": "G9004-2112",
            "farfar": "G9003-2011",
            "farmor": "G9003-2112",
        }
        for key, theirs in expected.items():
            self.assertEqual(self.row(answer, key), ("ingen", theirs), key)  # nothing typed, nothing read
        self.assertIn("G9001-2411 finns i Stamboken.", self.texts(answer))

    def test_the_paper_typed_against_the_rabbit(self):
        answer = self.existing(
            paper_number="G9001-2411",
            paper_certificate="SYN-777",
            name="elsa",
            sex="female",
            birth_date="2024-04-21",
            color="Bleighe",
            litter_size=2,
            mother="G9001-2212",
            father="G9003-2311",
            farmor="G9003-2112",
        )
        for key in ("paper_number", "paper_certificate", "name", "sex", "color", "litter_size", "father", "farmor"):
            self.assertEqual(self.row(answer, key)[0], "stammer", key)
        self.assertEqual(self.row(answer, "birth_date"), ("skiljer", "2024-04-20"))
        self.assertEqual(self.row(answer, "mother"), ("skiljer", "G9001-2211 Mira"))  # Sara, her sister
        self.assertIn("Intygsnumret är kaninens.", self.texts(answer, True))
        answer = self.existing(paper_certificate="SYN-778")
        self.assertEqual(self.row(answer, "paper_certificate"), ("skiljer", "SYN-777"))
        self.assertIn("G9001-2411 har redan intyg SYN-777 i Stamboken.", self.texts(answer, False))

    def test_a_rabbit_without_a_certificate_takes_a_free_one(self):
        answer = self.existing(individual="G9001-2412", paper_certificate="SYN-801")
        self.assertEqual(self.row(answer, "paper_certificate"), ("stammer", "ledigt"))

    def test_a_number_not_in_stamboken(self):
        answer = self.existing(individual="G9001-2419", name="Elsa")
        self.assertEqual(self.row(answer, "individual"), ("skiljer", "finns inte"))
        self.assertEqual(self.row(answer, "name"), ("ingen", None))
        self.assertIn("G9001-2419 finns inte i Stamboken.", self.texts(answer, False))
        answer = self.existing(individual="")
        self.assertEqual(self.row(answer, "individual"), ("ingen", None))


class TestOnlyTypedValuesLookUp(ReconcileTest):
    def test_an_empty_row_that_was_read_is_unsure(self):
        self.read(father="G9003 2311", birth_date="10/5")
        answer = self.answer(father="", farfar="", farmor="", birth_date="")
        self.assertEqual(self.row(answer, "father"), ("osaker", None))
        self.assertEqual(self.row(answer, "birth_date"), ("osaker", None))
        self.assertEqual(self.row(answer, "farfar"), ("ingen", None))  # not G9003-2011: the reading looks up nothing
        self.assertEqual(self.row(answer, "morfar"), ("stammer", "G9004-2011"))
        answer = self.answer(mother="", morfar="")
        self.assertEqual(self.row(answer, "morfar"), ("ingen", None))  # no mother typed: no registry either

    def test_a_parent_only_read_never_picks_the_litter(self):
        self.litter("G9001", "G9001-2211", "G9003-2311", date(2025, 5, 10), [], size=3)
        self.read(father="G9003 2311")
        answer = self.answer(father="")
        self.assertEqual(self.row(answer, "birth_date"), ("ingen", None))
        self.assertEqual(self.row(answer, "litter_size"), ("ingen", None))
        self.assertEqual(self.row(answer, "paper_number"), ("ingen", None))

    def test_an_empty_row_with_a_registry_value_shows_it(self):
        self.read(morfar="G9004 2011")
        answer = self.answer(morfar="")
        self.assertEqual(self.row(answer, "morfar"), ("osaker", "G9004-2011"))


class TestRequests(ReconcileTest):
    def test_only_the_queue_and_only_its_documents(self):
        self.login("owner")
        self.assertEqual(self.reconcile(**TYPED).status_code, 403)
        self.login("hjalp")
        self.assertEqual(self.reconcile(**TYPED).status_code, 200)
        other = self.item()
        self.assertEqual(self.reconcile(document=other.documents.get(), **TYPED).status_code, 404)
        missing = db.InboxItem(id=self.queue_item.id + 1000)
        self.assertEqual(self.reconcile(item=missing, **TYPED).status_code, 404)

    def test_nothing_is_written(self):
        self.read(father="G9003 2311")
        tables = (
            db.Individual,
            db.Breeding,
            db.HerdTracking,
            db.InboxItem,
            db.InboxDocument,
            db.InboxEvent,
            db.AuditLog,
        )

        def everything():
            return [list(table.select().order_by(table.id).dicts()) for table in tables]

        before = everything()
        for typed in (TYPED, {**TYPED, "paper_number": "G9001-2521"}, {**TYPED, "mode": "pappersintyg"}):
            self.assertEqual(self.reconcile(**typed).status_code, 200)
        self.assertEqual(everything(), before)

    def test_half_typed_and_garbage_values_are_answered(self):
        for body in (
            [],
            {},
            {"mode": 3, "paper_number": ["G9001"], "mother": {"x": 1}, "litter_size": True},
            {**TYPED, "paper_number": "G9001-25", "birth_date": "2025-0", "litter_size": "fem"},
            {**TYPED, "paper_number": "G", "mother": "G9001-", "father": "9003", "birth_date": "2025-13-40"},
            {**TYPED, "paper_number": "G9001-2511" * 20, "paper_certificate": "x" * 300},
        ):
            with self.subTest(body=str(body)[:60]):
                resp = self.reconcile(body=body)
                self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
                self.assertIn("paper_number", resp.get_json()["rows"])
