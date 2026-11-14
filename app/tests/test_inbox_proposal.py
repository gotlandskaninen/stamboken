"""The checks behind the image reading's proposal (utils/inbox_proposal.py): each rule with a case it accepts and a
case it must not turn into a confident field.

A synthetic registry of three generations in made-up herds (G9001–G9004, and M9005 in the other genebank). The
interpreter's answers are canned dicts in the shape of inbox_interpreter.SCHEMA. No real certificate or number.
"""

from datetime import date

import utils.database as db
from utils.inbox_proposal import build_proposal

from tests.database_test import DatabaseTest
from tests.ht_helpers import ht_row, make_individual


def ancestor(herd="", individual="", name=""):
    return {"genbanksnr": herd, "ar_kull_individ": individual, "namn": name}


def reading(**changes):
    """The certificate of a new rabbit, G9001-2511, read right: mother G9001-2211, father G9003-2311."""
    base = {
        "genbanksnr": "G9001",
        "ar_kull_individ": "2511",
        "intygsnummer": "SYN-501",
        "fodelsedatum": "250510",
        "kon": "Hona",
        "namn": "Testa",
        "farg": "bleighe",
        "fodda_i_kullen": "5 st",
        "levande_efter_6_veckor": "4",
        "mor": ancestor("G9001", "2211", "Mira"),
        "far": ancestor("G9003", "2311", "Max"),
        "morfar": ancestor("G9004", "2011"),
        "mormor": ancestor("G9004", "2112"),
        "farfar": ancestor("G9003", "2011"),
        "farmor": ancestor("G9003", "2112"),
        "overstruket": [],
    }
    return {**base, **changes}


class ProposalTest(DatabaseTest):
    def setUp(self):
        super().setUp()
        gotland, mellerud = self.genebanks
        self.h = {code: db.Herd.create(genebank=gotland, herd=code) for code in ("G9001", "G9002", "G9003", "G9004")}
        self.h["M9005"] = db.Herd.create(genebank=mellerud, herd="M9005")
        # Founders: the grandparents, and the parents of a buck that is not the father.
        founders = [
            ("G9003", "G9003-2011", "male"),
            ("G9003", "G9003-2112", "female"),
            ("G9004", "G9004-2011", "male"),
            ("G9004", "G9004-2112", "female"),
            ("G9002", "G9002-2011", "male"),
            ("G9002", "G9002-2112", "female"),
        ]
        self.r = {n: make_individual(self.h[h], n, date(2020, 5, 1), sex=s) for h, n, s in founders}
        sisters = [("G9001-2211", "female", "Mira"), ("G9001-2212", "female", "Sara")]
        self.mother = self.litter("G9001", "G9004-2112", "G9004-2011", date(2022, 3, 10), sisters)[0]
        ht_row("BIRTH", herd=self.h["G9001"], individual=self.mother, herd_tracking_date=date(2022, 3, 10))
        siblings = [("G9003-2311", "male", "Max"), ("G9003-2312", "male", "Mats"), ("G9003-2313", "female", "Maja")]
        self.father = self.litter("G9003", "G9003-2112", "G9003-2011", date(2023, 4, 1), siblings)[0]
        # Another buck with the father's individual digits, one herd digit away, and other parents.
        self.litter("G9002", "G9002-2112", "G9002-2011", date(2023, 4, 2), [("G9002-2311", "male", "Max")])
        # The other genebank: the only buck whose number ends in 2399.
        mellerud_buck = make_individual(self.h["M9005"], "M9005-2399", date(2023, 4, 1), sex="male")
        self.r[mellerud_buck.number] = mellerud_buck

    def litter(self, herd, mother, father, born, rabbits, size=None, **extra):
        breeding = db.Breeding.create(
            breeding_herd_id=self.h[herd],
            mother=self.r[mother],
            father=self.r[father],
            birth_date=born,
            breed_date=date.fromordinal(born.toordinal() - 31),
            litter_size=size or max(len(rabbits), 1),
            litter_size6w=size or max(len(rabbits), 1),
            litter_number=1,
        )
        made = []
        for number, sex, name, *rest in rabbits:
            extra = {"certificate": f"C-{number}", **(rest[0] if rest else {})}
            rabbit = db.Individual.create(
                origin_herd=self.h[herd], breeding=breeding, number=number, sex=sex, name=name, **extra
            )
            self.r[number] = rabbit
            made.append(rabbit)
        return made or [breeding]

    def propose(self, raw, genebank=0, herd="G9001"):
        proposal = build_proposal(raw, self.genebanks[genebank].id, self.h[herd].id if herd else None)
        for key, field in proposal["fields"].items():  # the guarantee: nothing unsure carries a value
            if field["source"] in ("avviker", "osäker"):
                self.assertIsNone(field["value"], key)
            else:
                self.assertIn(field["source"], ("läst", "härlett"), key)
                self.assertIsNotNone(field["value"], key)
        return proposal

    def source(self, proposal, key):
        field = proposal["fields"].get(key)
        return field and (field["source"], field["value"])

    def texts(self, proposal, ok=None):
        return [c["text"] for c in proposal["checks"] if ok is None or c["ok"] is ok]


class TestNormalise(ProposalTest):
    """Rule 1: numbers with or without spaces and letter, dates in both handwritten forms, "st" in counts."""

    def test_spaces_and_both_date_forms(self):
        for written in ("250510", "10/5-25", "10/5 2025", "2025-05-10"):
            with self.subTest(written):
                proposal = self.propose(
                    reading(
                        fodelsedatum=written, genbanksnr="G 9001", ar_kull_individ="25 11", mor=ancestor("9001", "2211")
                    )
                )
                self.assertEqual(self.source(proposal, "birth_date"), ("läst", "2025-05-10"))
                self.assertEqual(self.source(proposal, "paper_number"), ("läst", "G9001-2511"))
                self.assertEqual(self.source(proposal, "mother"), ("läst", "G9001-2211"))
                self.assertEqual(self.source(proposal, "litter_size"), ("läst", 5))

    def test_what_does_not_parse_is_unsure(self):
        for written in ("10/5", "99/99-25", "251340", "10 maj", "1/1-35"):
            with self.subTest(written):
                proposal = self.propose(reading(fodelsedatum=written))
                self.assertEqual(self.source(proposal, "birth_date"), ("osäker", None))
                self.assertEqual(proposal["fields"]["birth_date"]["read"], written)
        proposal = self.propose(reading(fodda_i_kullen="fem"))
        self.assertEqual(self.source(proposal, "litter_size"), ("osäker", None))


class TestGenebank(ProposalTest):
    """Rule 2: only the item's genebank is searched."""

    def test_the_items_genebank_is_searched(self):
        self.assertEqual(self.source(self.propose(reading()), "father"), ("läst", "G9003-2311"))

    def test_the_other_genebanks_numbers_are_never_matched(self):
        # M9005-2399 is in Mellerud; on a Gotland certificate "G9005 2399" (or "M9005") must not find it.
        for herd in ("G9005", "M9005", "9005"):
            with self.subTest(herd):
                proposal = self.propose(reading(far=ancestor(herd, "2399")))
                self.assertEqual(self.source(proposal, "father"), ("osäker", None))
                self.assertIn(f"Far: {herd} 2399 finns inte i Stamboken.", self.texts(proposal, False))
        # And a Gotland reading on a Mellerud item finds nothing at all.
        proposal = self.propose(reading(), genebank=1, herd="M9005")
        for key in ("mother", "father", "paper_number"):
            self.assertEqual(self.source(proposal, key), ("osäker", None), key)


class TestPedigree(ProposalTest):
    """Rule 3: a parent is confirmed by its own parents in the registry; grandparents only under a confirmed one."""

    def test_confirmed_parents_and_their_parents(self):
        proposal = self.propose(reading(farmor=ancestor()))  # an empty grandparent comes from the registry
        self.assertEqual(self.source(proposal, "mother"), ("läst", "G9001-2211"))
        self.assertEqual(self.source(proposal, "father"), ("läst", "G9003-2311"))
        self.assertEqual(self.source(proposal, "farfar"), ("läst", "G9003-2011"))
        self.assertEqual(self.source(proposal, "farmor"), ("härlett", "G9003-2112"))
        self.assertIn("Mor och far finns i Stamboken med intyg.", self.texts(proposal, True))

    def test_a_misread_parent_whose_grandparents_disagree_flags_its_branch(self):
        # G9002-2311 exists, but its parents are not the farfar and farmor the certificate shows.
        proposal = self.propose(reading(far=ancestor("G9002", "2311", "Max")))
        for key in ("father", "farfar", "farmor"):
            self.assertEqual(self.source(proposal, key), ("avviker", None), key)
        self.assertEqual(proposal["fields"]["farfar"]["registry"], "G9002-2011")
        self.assertEqual(self.source(proposal, "mother"), ("läst", "G9001-2211"))  # the other branch stands
        self.assertNotIn("Mor och far finns i Stamboken med intyg.", self.texts(proposal))

    def test_no_grandparent_to_compare_leaves_the_parent_unsure(self):
        proposal = self.propose(reading(farfar=ancestor(), farmor=ancestor("G", "oläsligt")))
        self.assertEqual(self.source(proposal, "father"), ("osäker", None))
        self.assertNotIn("farfar", proposal["fields"])
        # A founder: the registry has no parents to compare with.
        proposal = self.propose(reading(far=ancestor("G9003", "2011"), farfar=ancestor(), farmor=ancestor()))
        self.assertEqual(self.source(proposal, "father"), ("osäker", None))

    def test_grandparents_are_never_proposed_without_their_parent(self):
        proposal = self.propose(reading(far=ancestor()))
        for key in ("farfar", "farmor"):
            self.assertNotIn(proposal["fields"].get(key, {}).get("source"), ("läst", "härlett"), key)

    def test_a_littermate_of_the_other_sex_or_name_is_caught(self):
        for number, name in (("2312", "Max"), ("2313", "Max")):  # Mats is a brother, Maja a sister of Max
            with self.subTest(number):
                proposal = self.propose(reading(far=ancestor("G9003", number, name)))
                self.assertEqual(self.source(proposal, "father"), ("osäker", None))
                self.assertNotIn(self.source(proposal, "farfar"), [("läst", "G9003-2011")])

    def test_a_grandparent_near_several_numbers_confirms_nothing(self):
        # G9000 is one digit from G9002, G9003 and G9004, which all have a 2011.
        proposal = self.propose(reading(farfar=ancestor("G9000", "2011"), farmor=ancestor()))
        self.assertEqual(self.source(proposal, "father"), ("osäker", None))


class TestNearestMatch(ProposalTest):
    """Rule 4: a number one character off gives the registry's number as härlett, never läst."""

    def test_one_character_off_is_derived(self):
        for herd, individual in (("G9013", "2311"), ("69003", "2311"), ("G9OO3", "23l1")):
            with self.subTest(f"{herd} {individual}"):
                proposal = self.propose(reading(far=ancestor(herd, individual)))
                self.assertEqual(self.source(proposal, "father"), ("härlett", "G9003-2311"))
                self.assertEqual(proposal["fields"]["father"]["read"], f"{herd} {individual}")

    def test_several_or_no_near_numbers_are_unsure(self):
        # G9000 is one digit from both G9002 and G9003; G7777 is a herd nobody has.
        for herd, why in (("G9000", "liknar flera"), ("G7777", "finns inte")):
            with self.subTest(herd):
                proposal = self.propose(reading(far=ancestor(herd, "2311")))
                self.assertEqual(self.source(proposal, "father"), ("osäker", None))
                self.assertTrue(any(why in text for text in self.texts(proposal, False)), proposal["checks"])
        proposal = self.propose(reading(genbanksnr="G7777"))  # the rabbit's own herd
        self.assertEqual(self.source(proposal, "paper_number"), ("osäker", None))


class TestOwnNumber(ProposalTest):
    """Rule 5: the rabbit's number against its birth year and litter; the certificate number free."""

    def test_number_litter_and_certificate_agree(self):
        proposal = self.propose(reading())
        self.assertEqual(self.source(proposal, "paper_number"), ("läst", "G9001-2511"))
        self.assertEqual(self.source(proposal, "paper_certificate"), ("läst", "SYN-501"))
        passed = self.texts(proposal, True)
        for text in (
            "Mor och far finns i Stamboken med intyg.",
            "Numret stämmer med kullen.",
            "Intygsnumret är ledigt.",
        ):
            self.assertIn(text, passed)

    def test_a_number_its_litter_does_not_give_deviates(self):
        proposal = self.propose(reading(ar_kull_individ="2521"))  # the year's first litter, not its second
        self.assertEqual(self.source(proposal, "paper_number"), ("avviker", None))
        self.assertEqual(proposal["fields"]["paper_number"]["registry"], "G9001-2511")

    def test_year_digits_against_the_birth_date(self):
        proposal = self.propose(reading(ar_kull_individ="2411"))
        self.assertEqual(self.source(proposal, "paper_number"), ("osäker", None))
        self.assertEqual(self.source(proposal, "birth_date"), ("osäker", None))
        self.assertIn("Årssiffrorna i individnumret stämmer inte med födelsedatumet.", self.texts(proposal, False))

    def test_a_certificate_number_in_use_deviates(self):
        proposal = self.propose(reading(intygsnummer="C-G9003-2312"))
        self.assertEqual(self.source(proposal, "paper_certificate"), ("avviker", None))
        self.assertEqual(proposal["fields"]["paper_certificate"]["registry"], "G9003-2312")


class TestDeviations(ProposalTest):
    """Rule 6: where the certificate and the registry disagree, both are shown and nothing chooses."""

    def test_a_litter_registered_two_days_off(self):
        self.litter("G9001", "G9001-2211", "G9003-2311", date(2025, 5, 12), [], size=3)
        proposal = self.propose(reading())
        field = proposal["fields"]["birth_date"]
        self.assertEqual((field["source"], field["value"], field["read"]), ("avviker", None, "250510"))
        self.assertEqual(field["registry"], "2025-05-12")
        self.assertEqual(self.source(proposal, "paper_number"), ("osäker", None))  # no litter to try it on

    def test_a_litter_size_that_differs(self):
        self.litter("G9001", "G9001-2211", "G9003-2311", date(2025, 5, 10), [], size=3)
        proposal = self.propose(reading())
        self.assertEqual(self.source(proposal, "litter_size"), ("avviker", None))
        self.assertEqual(proposal["fields"]["litter_size"]["registry"], 3)
        self.assertEqual(self.source(proposal, "paper_number"), ("läst", "G9001-2511"))
        proposal = self.propose(reading(fodda_i_kullen="", levande_efter_6_veckor="3"))
        self.assertEqual(self.source(proposal, "litter_size"), ("härlett", 3))
        self.assertEqual(self.source(proposal, "litter_size6w"), ("läst", 3))


class TestStruckThrough(ProposalTest):
    def test_a_struck_through_value_is_always_unsure(self):
        for struck, key in (("ar_kull_individ", "paper_number"), ("far", "father"), ("fodelsedatum", "birth_date")):
            with self.subTest(struck):
                proposal = self.propose(reading(overstruket=[struck]))
                self.assertEqual(self.source(proposal, key), ("osäker", None))
        self.assertEqual(self.source(self.propose(reading(overstruket=["far"])), "farfar"), None)


class TestExistingRabbit(ProposalTest):
    def setUp(self):
        super().setUp()
        rabbits = [
            ("G9001-2411", "female", "Elsa", {"certificate": None}),
            ("G9001-2412", "male", "Ebbe", {"certificate": None, "digital_certificate": 9001}),
        ]
        self.litter("G9001", "G9001-2211", "G9003-2311", date(2024, 4, 20), rabbits)

    def existing(self, number, **changes):
        return reading(ar_kull_individ=number, fodelsedatum="240420", intygsnummer="SYN-777", **changes)

    def test_a_digital_certificate_needs_nothing_more(self):
        proposal = self.propose(self.existing("2412", kon="Hane", namn="Ebbe"))
        self.assertEqual(
            proposal["fields"], {"individual": {"value": "G9001-2412", "source": "läst", "read": "G9001 2412"}}
        )
        self.assertEqual(self.texts(proposal), ["G9001-2412 finns redan med digitalt intyg."])

    def test_a_paper_certificate_for_a_rabbit_in_stamboken(self):
        proposal = self.propose(self.existing("2411", namn="Elsa"))
        self.assertEqual(self.source(proposal, "individual"), ("läst", "G9001-2411"))
        self.assertEqual(self.source(proposal, "paper_certificate"), ("läst", "SYN-777"))
        self.assertIn("Föräldrarna på intyget stämmer med registret.", self.texts(proposal, True))

    def test_a_digital_rabbit_that_does_not_fit_gets_the_checks(self):
        proposal = self.propose(self.existing("2412", kon="Hona"))
        self.assertEqual(self.source(proposal, "individual"), ("osäker", None))
        proposal = self.propose(self.existing("2411", far=ancestor("G9002", "2311")))
        self.assertEqual(self.source(proposal, "individual"), ("avviker", None))

    def test_a_number_with_letters_read_as_digits_is_at_most_derived(self):
        proposal = self.propose(self.existing("24l1", namn="Elsa"))
        self.assertEqual(self.source(proposal, "individual"), ("härlett", "G9001-2411"))
        proposal = self.propose(self.existing("24l2", kon="Hane", namn="Ebbe"))
        self.assertNotIn("G9001-2412 finns redan med digitalt intyg.", self.texts(proposal))


class TestRegistryOnly(ProposalTest):
    """When the reading gives no confirmed parents, the registry's litters help, clearly as härlett."""

    def test_a_parent_found_gives_its_litter_born_on_the_date_read(self):
        self.litter("G9001", "G9001-2211", "G9003-2311", date(2025, 5, 10), [], size=5)
        proposal = self.propose(reading(far=ancestor("G", "???"), morfar=ancestor(), mormor=ancestor()))
        self.assertEqual(self.source(proposal, "mother"), ("härlett", "G9001-2211"))
        self.assertEqual(self.source(proposal, "father"), ("härlett", "G9003-2311"))
        self.assertIn("Mor och far är hämtade ur Stamboken, ur kullen född 2025-05-10.", self.texts(proposal))
        self.assertEqual(self.source(proposal, "paper_number"), ("läst", "G9001-2511"))

    def test_a_parent_read_against_the_litter_is_not_overridden(self):
        self.litter("G9001", "G9001-2211", "G9003-2311", date(2025, 5, 10), [], size=5)
        proposal = self.propose(reading(far=ancestor("G9002", "2011"), farfar=ancestor(), farmor=ancestor()))
        self.assertEqual(self.source(proposal, "father"), ("avviker", None))

    def test_nothing_usable_lists_the_herds_litters_of_the_year(self):
        this_year = date(date.today().year, 1, 1)
        self.litter("G9001", "G9001-2211", "G9003-2311", this_year, [], size=2)
        empty = {key: "" for key in reading() if isinstance(reading()[key], str)}
        proposal = self.propose(empty)
        self.assertEqual(proposal["fields"], {})
        self.assertEqual([c["ok"] for c in proposal["checks"]], [None])
        self.assertIn("mor G9001-2211", proposal["checks"][0]["text"])
        # With a birth date read, the herd's single litter that day fills the parents.
        proposal = self.propose({**empty, "fodelsedatum": this_year.isoformat()})
        self.assertEqual(self.source(proposal, "mother"), ("härlett", "G9001-2211"))
        self.assertEqual(self.source(proposal, "father"), ("härlett", "G9003-2311"))

    def test_a_parent_the_checks_ruled_out_is_not_taken_back(self):
        # The mother misread as her sister, whose litter with the father was born that day: still osäker.
        self.litter("G9001", "G9001-2212", "G9003-2311", date(2025, 5, 10), [], size=5)
        proposal = self.propose(reading(mor=ancestor("G9001", "2212", "Mira")))
        self.assertEqual(self.source(proposal, "mother"), ("osäker", None))
        self.assertEqual(self.source(proposal, "paper_number"), ("osäker", None))
        self.assertNotIn("Mor och far är hämtade ur Stamboken, ur kullen född 2025-05-10.", self.texts(proposal))

    def test_a_parent_struck_through_is_not_taken_from_the_litter(self):
        self.litter("G9001", "G9001-2211", "G9003-2311", date(2025, 5, 10), [], size=5)
        proposal = self.propose(reading(overstruket=["far"]))
        self.assertEqual(self.source(proposal, "father"), ("osäker", None))
        self.assertEqual(self.source(proposal, "paper_number"), ("osäker", None))

    def test_garbage_from_the_model_is_survived(self):
        for raw in (None, [], {"far": "G9003-2311", "overstruket": "far", "fodelsedatum": 250510}):
            with self.subTest(raw):
                self.assertIsInstance(self.propose(raw)["fields"], dict)
