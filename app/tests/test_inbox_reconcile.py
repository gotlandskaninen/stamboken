"""The reconciliation table (POST …/avstamning, utils/inbox_reconcile.py): what the handler typed off the paper,
beside the registry row by row, and the checks in words.

The synthetic registry of test_inbox_proposal: made-up herds G9001–G9004 in Gotland and M9005 in Mellerud. No real
certificate or number.
"""

from datetime import date
from unittest import mock

import utils.database as db
import utils.inbox as inbox
import utils.inbox_proposal as inbox_proposal
from utils.inbox_reconcile import HIDDEN, NOT_SEARCHED

from tests.ht_helpers import ht_row, make_individual
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

    def test_a_zero_padded_litter_number_is_shown_as_registration_writes_it(self):
        # G9001-25011 is the year's first litter, written with a zero: registration gives it as G9001-2511.
        self.assertEqual(self.row(self.answer(paper_number="G9001-25011"), "paper_number"), ("stammer", "G9001-2511"))

    def test_a_certificate_number_too_long_to_save_differs(self):
        answer = self.answer(paper_certificate="X" * 21)
        self.assertEqual(self.row(answer, "paper_certificate"), ("skiljer", None))
        self.assertIn("Intygsnumret är för långt: högst 20 tecken.", self.texts(answer, False))
        self.assertNotIn("Intygsnumret är ledigt.", self.texts(answer))

    def test_a_certificate_number_in_use_differs(self):
        answer = self.answer(paper_certificate="C-G9003-2312")
        self.assertEqual(self.row(answer, "paper_certificate"), ("skiljer", "G9003-2312"))
        self.assertIn("Intygsnumret C-G9003-2312 finns redan på G9003-2312.", self.texts(answer, False))

    def test_a_colour_only_as_the_genebank_spells_it(self):
        # Registration looks a colour up as typed: another case is not the listed one.
        self.assertEqual(self.row(self.answer(color="bleighe"), "color"), ("stammer", "bleighe"))
        self.assertEqual(self.row(self.answer(color="Bleighe"), "color"), ("skiljer", "bleighe"))
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
        db.Individual.update(sex="eunuch").where(db.Individual.number == "G9003-2311").execute()
        self.assertEqual(self.answer(father="G9013-2311")["rows"]["father"]["near"][0]["sex"], "male")
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
        self.login("mhjalp")
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
        answer = self.answer(paper_number="9001-2511")  # no letter: no genebank to search
        self.assertEqual(self.row(answer, "mother"), ("ingen", None))
        self.assertEqual(self.texts(answer), [NOT_SEARCHED])


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
            color="bleighe",
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
        self.assertEqual(self.row(self.existing(color="Bleighe"), "color"), ("skiljer", "bleighe"))
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
        self.login("mhjalp")  # in the queue, but a worker of the other genebank
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

    def test_an_item_without_a_genebank_takes_a_manager(self):
        db.InboxItem.update(genebank=None).where(db.InboxItem.id == self.queue_item.id).execute()
        self.login("hjalp")
        self.assertEqual(self.reconcile(**TYPED).status_code, 403)
        self.login("man")
        self.assertEqual(self.reconcile(**TYPED).status_code, 200)


class TestNumberCheckNames(ReconcileTest):
    """The number check names the rabbits and litters the user would see in the 409 from …/spara."""

    def sibling_line(self, answer):
        return next(text for text in self.texts(answer) if "i kullen saknar intyg" in text)

    def test_a_helpers_line_names_what_her_409_would(self):
        self.litter(
            "G9001",
            "G9001-2211",
            "G9003-2311",
            date(2025, 5, 10),
            [("G9001-2512", "female", "Syster", {"certificate": None})],
        )
        self.login("hjalp")
        with mock.patch.object(inbox_proposal, "number_check", wraps=inbox_proposal.number_check) as check:
            answer = self.answer()
        self.assertEqual(check.call_args.args[0].id, self.helper.id)  # the helper herself, as …/spara asks
        self.assertEqual(self.sibling_line(answer), "G9001-2512 i kullen saknar intyg. Är det samma kanin?")
        # Kept in a herd of the other genebank, the sibling is no longer hers to see: the line without its number.
        ht_row(
            "TRANSFER",
            from_herd=self.h["G9001"],
            herd=self.h["M9005"],
            individual=self.r["G9001-2512"],
            herd_tracking_date=date(2025, 8, 1),
        )
        self.assertEqual(self.sibling_line(self.answer()), "En kanin i kullen saknar intyg. Är det samma kanin?")


def rows_of(order, **changes):
    """Every row of an answer: nothing to compare with, unless `changes` says otherwise."""
    rows = {key: {"registry": None, "status": "ingen"} for key in order}
    for key, (status, registry) in changes.items():
        rows[key] = {"registry": registry, "status": status}
    return rows


NEW_ROWS = (
    "paper_number",
    "paper_certificate",
    "name",
    "sex",
    "birth_date",
    "color",
    "litter_size",
    "litter_size6w",
    "mother",
    "morfar",
    "mormor",
    "father",
    "farfar",
    "farmor",
)


class TestWhatTheUserMayRead(ReconcileTest):
    """A rabbit is named only to someone who may read it (GET /v2/individual): its herd in one of their genebanks."""

    def test_an_item_without_a_genebank_searches_none_the_user_does_not_work(self):
        # Mellerud's numbers on an item without a genebank, asked by Gotland's manager: nothing is searched.
        db.InboxItem.update(genebank=None).where(db.InboxItem.id == self.queue_item.id).execute()
        self.r["M9005-2112"] = make_individual(self.h["M9005"], "M9005-2112", date(2021, 4, 1), sex="female")
        self.litter("M9005", "M9005-2112", "M9005-2399", date(2025, 5, 10), [("M9005-2512", "female", "Syster")])
        typed = {"paper_number": "M9005-2511", "mother": "M9005-2112", "father": "M9005-2399", "farfar": "M9005-2511"}
        answer = self.answer(**typed)
        self.assertEqual(answer, {"rows": rows_of(NEW_ROWS), "checks": [{"ok": None, "text": NOT_SEARCHED}]})
        self.login("admin")  # an admin works every genebank
        self.assertEqual(self.row(self.answer(**typed), "mother"), ("stammer", "M9005-2112"))

    def test_read_access_to_the_genebank_is_not_enough(self):
        # Gotland's manager may read Mellerud, but does not work it: an item without a genebank searches nothing there.
        self.manager.add_role("viewer", self.genebanks[1].id)
        db.InboxItem.update(genebank=None).where(db.InboxItem.id == self.queue_item.id).execute()
        typed = {"paper_number": "M9005-2511", "father": "M9005-2399", "farfar": "", "farmor": ""}
        answer = self.answer(**typed)
        self.assertEqual(answer, {"rows": rows_of(NEW_ROWS), "checks": [{"ok": None, "text": NOT_SEARCHED}]})

    def test_a_rabbit_moved_to_another_genebank_is_never_named(self):
        # Max, the father, now lives in a Mellerud herd: Gotland's helper may no longer read him.
        ht_row(
            "TRANSFER",
            from_herd=self.h["G9003"],
            herd=self.h["M9005"],
            individual=self.father,
            herd_tracking_date=date(2025, 1, 10),
        )
        self.login("hjalp")
        seen = {
            "paper_certificate": ("stammer", "ledigt"),
            "color": ("stammer", "bleighe"),
            "mother": ("stammer", "G9001-2211 Mira"),
            "morfar": ("stammer", "G9004-2011"),
            "mormor": ("stammer", "G9004-2112"),
            "farfar": ("ingen", "G9003-2011"),  # not compared: his son is not hers to see
            "farmor": ("ingen", "G9003-2112"),
        }
        answer = self.answer()
        expected_rows = rows_of(NEW_ROWS, **seen, father=("ingen", HIDDEN))
        self.assertEqual(answer["rows"], expected_rows)
        self.assertEqual(
            answer["checks"],
            [
                {"ok": False, "text": f"Far G9003-2311 är {HIDDEN}."},
                {"ok": None, "text": "Individnumret går inte att pröva mot kullen utan mor, far och födelsedatum."},
                {"ok": True, "text": "Intygsnumret är ledigt."},
            ],
        )
        # One character off, his certificate, his number: never his number or name.
        answer = self.answer(father="G9013-2311", paper_certificate="C-G9003-2311", paper_number="G9003-2311")
        changed = {
            "father": ("skiljer", "finns inte"),  # no "near": he is the only one one character off
            "paper_number": ("skiljer", f"finns redan: {HIDDEN}"),
            "paper_certificate": ("skiljer", "används redan"),
        }
        expected_rows = rows_of(NEW_ROWS, **(seen | changed))
        self.assertEqual(answer["rows"], expected_rows)
        self.assertEqual(
            answer["checks"],
            [
                {"ok": False, "text": "Årssiffrorna i individnumret stämmer inte med födelsedatumet."},
                {"ok": False, "text": "Far G9013-2311 finns inte i Stamboken."},
                {"ok": False, "text": "G9003-2311 finns redan i Stamboken. Välj Pappersintyg på en kanin som finns."},
                {"ok": False, "text": "Intygsnumret C-G9003-2311 används redan."},
            ],
        )
        # Chosen as the rabbit in Stamboken: nothing of his is shown or compared.
        answer = self.reconcile(mode="pappersintyg", individual="G9003-2311", name="Max").get_json()
        self.assertEqual(
            answer,
            {
                "rows": rows_of(("individual", *NEW_ROWS), individual=("ingen", HIDDEN)),
                "checks": [{"ok": False, "text": f"G9003-2311 är {HIDDEN}."}],
            },
        )


class TestCheckedAsSavingTakesIt(ReconcileTest):
    def test_a_digital_certificate_is_said_and_never_free(self):
        rabbits = [("G9001-2411", "male", "Digge", {"certificate": None, "digital_certificate": 9001})]
        self.litter("G9001", "G9001-2211", "G9003-2311", date(2024, 4, 20), rabbits)
        digital = "G9001-2411 har digitalt intyg. Sparar du pappersintyget ersätts det digitala."
        for certificate, row in (("", ("ingen", "digitalt intyg")), ("SYN-801", ("skiljer", "digitalt intyg"))):
            with self.subTest(certificate=certificate):
                answer = self.reconcile(mode="pappersintyg", individual="G9001-2411", paper_certificate=certificate)
                answer = answer.get_json()
                self.assertEqual(self.row(answer, "paper_certificate"), row)
                self.assertIn(digital, self.texts(answer, False))
                self.assertNotIn("Intygsnumret är ledigt.", self.texts(answer))

    def test_a_certificate_number_only_as_saving_takes_it(self):
        # Saving trims the number and keeps the spaces inside: "AB 12" is not the stored "AB12".
        rabbits = [("G9001-2411", "female", "Elsa", {"certificate": "AB12"})]
        self.litter("G9001", "G9001-2211", "G9003-2311", date(2024, 4, 20), rabbits)
        typed = {"mode": "pappersintyg", "individual": "G9001-2411", "paper_number": "G9001-2411"}
        self.assertEqual(
            self.row(self.reconcile(**typed, paper_certificate="AB 12").get_json(), "paper_certificate"),
            ("skiljer", "AB12"),
        )
        answer = self.reconcile(**typed, paper_certificate=" AB12 ").get_json()
        self.assertEqual(self.row(answer, "paper_certificate"), ("stammer", "AB12"))
        # What stämmer saves as a link: the stored number is untouched.
        inbox.take(self.queue_item, self.manager, over=False)
        body = {
            "action": "pappersintyg",
            "individual": "G9001-2411",
            "paper_certificate": "AB12",
            "paper_number": "G9001-2411",
        }
        saved = self.post(f"/{self.queue_item.id}/dokument/{self.document.id}/spara", **body)
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertEqual(db.Individual.get(db.Individual.number == "G9001-2411").certificate, "AB12")
        self.assertEqual(db.InboxDocument.get_by_id(self.document.id).individual.number, "G9001-2411")


class TestTheReadingsChecksFromWhatIsTyped(ReconcileTest):
    def test_a_herd_not_in_stamboken(self):
        answer = self.answer(paper_number="G9009-2511")
        self.assertIn("Besättningen G9009 finns inte i Stamboken.", self.texts(answer, False))
        self.assertNotIn("Besättningen", " ".join(self.texts(self.answer())))

    def test_the_year_digits_against_the_birth_date(self):
        text = "Årssiffrorna i individnumret stämmer inte med födelsedatumet."
        self.assertIn(text, self.texts(self.answer(paper_number="G9001-2411"), False))
        self.assertNotIn(text, self.texts(self.answer()))
        self.assertNotIn(text, self.texts(self.answer(paper_number="G9001-2411", birth_date="")))

    def test_the_parents_litters_when_none_was_born_that_day(self):
        self.litter("G9001", "G9001-2211", "G9003-2311", date(2025, 5, 12), [], size=3)
        line = "Kull i Stamboken: född 2025-05-12, mor G9001-2211, far G9003-2311, 3 födda."
        self.assertIn(line, self.texts(self.answer()))  # typed born the 10th
        self.assertIn(line, self.texts(self.answer(father="", birth_date="")))  # the mother's litters
        self.assertNotIn(line, self.texts(self.answer(birth_date="2025-05-12")))  # that one is the litter


class TestTheStoredProposalShown(ReconcileTest):
    """Everyone in the queue may open the item; the registry's side of its reading only those who work it."""

    def test_only_what_the_photo_shows_to_someone_who_does_not_work_the_genebank(self):
        proposal = {
            "fields": {
                "mother": {"value": "G9001-2211", "source": "läst", "read": "G9001 2211"},
                "farfar": {"value": None, "source": "avviker", "read": "G9002 2011", "registry": "G9003-2011"},
                "farmor": {"value": "G9003-2112", "source": "härlett"},
            },
            "checks": [
                {"ok": False, "text": "Far: far- och morföräldrarna på intyget är inte registrets för G9003-2311."}
            ],
        }
        db.InboxDocument.update(interpretation_status="klar", proposal=proposal).where(
            db.InboxDocument.id == self.document.id
        ).execute()

        def shown(username):
            self.login(username)
            resp = self.client.get(f"/api/v2/inkorg/{self.queue_item.id}")
            self.assertEqual(resp.status_code, 200, resp.get_json())
            return resp.get_json()["documents"][0]["proposal"]

        self.assertEqual(shown("hjalp"), proposal)  # a worker of Gotland: as stored
        self.assertEqual(
            shown("mhjalp"),
            {
                "fields": {
                    "mother": {"source": "läst", "read": "G9001 2211"},
                    "farfar": {"source": "avviker", "read": "G9002 2011"},
                    "farmor": {"source": "härlett"},
                },
                "checks": [],
            },
        )
