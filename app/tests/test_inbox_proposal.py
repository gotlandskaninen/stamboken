"""The checks behind the image reading's proposal (utils/inbox_proposal.py): each rule with a case it accepts and a
case it must not turn into a confident field.

A synthetic registry of three generations in made-up herds (G9001–G9004, and M9005 in the other genebank). The
interpreter's answers are canned dicts in the shape of inbox_interpreter.SCHEMA. No real certificate or number.
"""

from datetime import date
from unittest import mock

import utils.database as db
import utils.inbox_proposal as inbox_proposal
from utils.herd_tracking import buyer_contact_fields
from utils.inbox_proposal import build_proposal, sale_part

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
                        fodelsedatum=written,
                        genbanksnr="G 9001",
                        ar_kull_individ="25 11",
                        mor=ancestor("9001", "2211", "Mira"),
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

    def test_a_letter_that_is_not_the_genebanks_is_named(self):
        # Which is wrong, the reading or the item's genebank, the handler sees on the photo.
        proposal = self.propose(reading(), genebank=1, herd="M9005")
        named = "Individnumret börjar med G på intyget, men genbankens nummer börjar med M."
        self.assertEqual(proposal["checks"][0], {"ok": False, "text": named})
        proposal = self.propose(reading(genbanksnr="M9001"))
        self.assertIn(
            "Individnumret börjar med M på intyget, men genbankens nummer börjar med G.", self.texts(proposal)
        )
        self.assertEqual(self.source(proposal, "paper_number")[0], "härlett")  # a letter not the genebank's
        for herd in ("G9001", "9001", "g9001", "Nr 9001"):
            with self.subTest(herd):
                self.assertNotIn("börjar med", " ".join(self.texts(self.propose(reading(genbanksnr=herd)))))
        unreadable = self.propose(reading(genbanksnr="M9001", ar_kull_individ="??"))  # the letter still speaks
        self.assertIn(
            "Individnumret börjar med M på intyget, men genbankens nummer börjar med G.", self.texts(unreadable)
        )
        struck = self.propose(reading(genbanksnr="M9001", overstruket=["genbanksnr"]))
        self.assertNotIn("börjar med", " ".join(self.texts(struck)))

    def test_an_item_without_a_genebank_searches_the_one_its_letter_names(self):
        # A mail from an address not in the member register has no genebank: the letter read points to one.
        self.assertEqual(self.source(build_proposal(reading(), None), "father"), ("läst", "G9003-2311"))
        proposal = build_proposal(reading(genbanksnr="9001"), None)  # no letter read: no genebank to search
        self.assertEqual(self.source(proposal, "father"), ("osäker", None))


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

    def test_a_grandparent_read_as_its_own_parent_is_a_misread(self):
        # The model read the parents' boxes again for the mother's parents: no rabbit is its own parent, so the
        # registry is not against the certificate. Morfar as the father is a real mating, and named nowhere.
        proposal = self.propose(reading(morfar=ancestor("G9003", "2311"), mormor=ancestor("G9001", "2211")))
        for key in ("mother", "morfar", "mormor"):
            self.assertEqual(self.source(proposal, key), ("osäker", None), key)
            self.assertNotIn("registry", proposal["fields"][key], key)
        self.assertIn(
            "Mor: mormor är inläst med mors eget nummer, så tolkningen har troligen tagit fel ruta.",
            self.texts(proposal, False),
        )
        self.assertNotIn("far- och morföräldrarna på intyget", " ".join(self.texts(proposal)))
        self.assertEqual(self.source(proposal, "father"), ("läst", "G9003-2311"))  # the other branch stands
        # Her litter with the confirmed father, born the date read, is listed; she is not taken from it.
        self.litter("G9001", "G9001-2211", "G9003-2311", date(2025, 5, 10), [], size=5)
        proposal = self.propose(reading(mormor=ancestor("G9001", "2211")))
        self.assertEqual(self.source(proposal, "mother"), ("osäker", None))
        self.assertIn(
            "Kull i Stamboken: född 2025-05-10, mor G9001-2211, far G9003-2311, 5 födda.", self.texts(proposal)
        )

    def test_a_misread_box_near_the_parent_is_caught_and_the_other_box_still_counts(self):
        # Mormor one character from the mother finds her too, and so do both boxes copying her.
        for morfar, named in (
            (ancestor("G9004", "2011"), "mormor är inläst"),
            (ancestor("G9001", "2211"), "morfar och mormor är inlästa"),
        ):
            proposal = self.propose(reading(morfar=morfar, mormor=ancestor("G9011", "2211")))
            self.assertIn(f"Mor: {named} med mors eget nummer", " ".join(self.texts(proposal, False)))
        proposal = self.propose(reading(mormor=ancestor("G9011", "2211")))
        self.assertEqual(self.source(proposal, "mother"), ("osäker", None))
        self.assertIn("Mor: mormor är inläst med mors eget nummer", " ".join(self.texts(proposal, False)))
        # Mormor repeats the mother and morfar the father, one herd digit off: the parents' row read again.
        proposal = self.propose(reading(morfar=ancestor("G9013", "2311"), mormor=ancestor("G9001", "2211")))
        self.assertEqual(self.source(proposal, "mother"), ("osäker", None))
        self.assertNotIn("far- och morföräldrarna på intyget", " ".join(self.texts(proposal)))
        # Farmor copies the father, but farfar, read on its own, is not G9002-2311's father: still a disagreement.
        proposal = self.propose(reading(far=ancestor("G9002", "2311", "Max"), farmor=ancestor("G9002", "2311")))
        self.assertEqual(self.source(proposal, "father"), ("avviker", None))
        self.assertEqual(proposal["fields"]["farfar"]["registry"], "G9002-2011")
        self.assertIn(
            "Far: far- och morföräldrarna på intyget är inte registrets för G9002-2311.", self.texts(proposal, False)
        )

    def test_a_misread_box_does_not_lead_to_another_rabbits_litter(self):
        # The mother misread as Maja, whose mormor box repeats her, and morfar left empty: nothing else speaks
        # against Maja, but her one litter born that day must not fill in the parents.
        self.litter("G9003", "G9003-2313", "G9002-2311", date(2025, 5, 10), [], size=5)
        proposal = self.propose(
            reading(mor=ancestor("G9003", "2313"), morfar=ancestor(), mormor=ancestor("G9003", "2313"), far=ancestor())
        )
        self.assertEqual(self.source(proposal, "mother"), ("osäker", None))
        self.assertIsNone(self.source(proposal, "father"))
        self.assertNotIn("Mor och far är hämtade ur Stamboken, ur kullen född 2025-05-10.", self.texts(proposal))

    def test_a_parent_only_found_does_not_overrule_a_confirmed_one(self):
        # Maja's (or G9002-2311's) litter born that day is not the confirmed parent's: it may not make that one avviker.
        self.litter("G9003", "G9003-2313", "G9002-2311", date(2025, 5, 10), [], size=5)
        for role, changes in (
            ("father", {"mor": ancestor("G9003", "2313"), "morfar": ancestor(), "mormor": ancestor()}),
            ("mother", {"far": ancestor("G9002", "2311"), "farfar": ancestor(), "farmor": ancestor()}),
        ):
            with self.subTest(confirmed=role):
                proposal = self.propose(reading(**changes))
                confirmed = {"father": "G9003-2311", "mother": "G9001-2211"}[role]
                self.assertEqual(self.source(proposal, role), ("läst", confirmed))
                self.assertNotIn("avviker", [f["source"] for f in proposal["fields"].values()])

    def test_grandparents_are_never_proposed_without_their_parent(self):
        proposal = self.propose(reading(far=ancestor()))
        for key in ("farfar", "farmor"):
            self.assertNotIn(proposal["fields"].get(key, {}).get("source"), ("läst", "härlett"), key)

    def test_a_parent_with_a_littermate_of_its_sex_needs_its_name(self):
        # Max and Mats are brothers: the same parents, the same birth date, one digit apart.
        for name, source in (("", "osäker"), ("Mats", "osäker"), ("Max", "läst")):
            with self.subTest(name=name):
                proposal = self.propose(reading(far=ancestor("G9003", "2311", name)))
                self.assertEqual(self.source(proposal, "father")[0], source)
                if source == "osäker":
                    self.assertNotIn(self.source(proposal, "farfar"), [("läst", "G9003-2011")])
        proposal = self.propose(reading(far=ancestor("G9003", "2311")))
        self.assertIn("Far: G9003-2311 har ett kullsyskon av samma kön", " ".join(self.texts(proposal, False)))

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
                proposal = self.propose(reading(far=ancestor(herd, individual, "Max")))
                self.assertEqual(self.source(proposal, "father"), ("härlett", "G9003-2311"))
                self.assertEqual(proposal["fields"]["father"]["read"], f"{herd} {individual}")

    def test_several_or_no_near_numbers_are_unsure(self):
        # G9000 is one digit from both G9002 and G9003; G7777 is a herd nobody has.
        for herd, why in (
            ("G9000", "finns inte i Stamboken, men flera kaniner har nästan samma nummer"),
            ("G7777", "finns inte i Stamboken"),
        ):
            with self.subTest(herd):
                proposal = self.propose(reading(far=ancestor(herd, "2311")))
                self.assertEqual(self.source(proposal, "father"), ("osäker", None))
                self.assertIn(f"Far: {herd} 2311 {why}.", self.texts(proposal, False))
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
        self.assertNotIn("registry", proposal["fields"]["paper_certificate"])
        self.assertIn("Intygsnumret C-G9003-2312 finns redan på G9003-2312.", self.texts(proposal, False))


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


class TestPreliminaryCount(ProposalTest):
    def test_a_preliminary_count_alive_is_never_proposed(self):
        # The litter's count alive is only a copy of its count born until someone confirms it: never härlett, and
        # what was read is not set against it.
        self.litter("G9001", "G9001-2211", "G9003-2311", date(2025, 5, 10), [], size=5)
        db.Breeding.update(litter_size6w_preliminary=True).where(db.Breeding.birth_date == date(2025, 5, 10)).execute()
        proposal = self.propose(reading(levande_efter_6_veckor=""))
        self.assertEqual(self.source(proposal, "litter_size"), ("läst", 5))
        self.assertNotIn("litter_size6w", proposal["fields"])
        proposal = self.propose(reading())  # 4 read
        self.assertEqual(self.source(proposal, "litter_size6w"), ("läst", 4))
        self.assertNotIn("Kullen har 5 i Stamboken där intyget säger 4.", self.texts(proposal))


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
        return reading(**{"ar_kull_individ": number, "fodelsedatum": "240420", "intygsnummer": "SYN-777", **changes})

    def test_a_photo_of_the_certificate_the_rabbit_has_reads_it_as_its_own(self):
        db.Individual.update(certificate="SYN-777").where(db.Individual.number == "G9001-2411").execute()
        proposal = self.propose(self.existing("2411", namn="Elsa"))
        self.assertEqual(self.source(proposal, "individual"), ("läst", "G9001-2411"))
        self.assertEqual(self.source(proposal, "paper_certificate"), ("läst", "SYN-777"))
        self.assertIn("Intygsnumret är kaninens.", self.texts(proposal, True))
        self.assertEqual(self.texts(proposal, False), [])  # what "Förslag: stämmer" in the queue needs

    def test_a_digital_certificate_needs_nothing_more(self):
        proposal = self.propose(self.existing("2412", kon="Hane", namn="Ebbe"))
        self.assertEqual(
            proposal["fields"], {"individual": {"value": "G9001-2412", "source": "läst", "read": "G9001 2412"}}
        )
        self.assertEqual(self.texts(proposal), ["G9001-2412 finns redan med digitalt intyg."])

    def test_another_birth_date_deviates_and_proposes_no_rabbit(self):
        proposal = self.propose(self.existing("2411", namn="Elsa", fodelsedatum="240421"))
        for key in ("individual", "paper_number"):
            self.assertEqual(self.source(proposal, key), ("avviker", None), key)
            self.assertEqual(proposal["fields"][key]["registry"], "G9001-2411")
        self.assertIn("Intyget säger född 2024-04-21, Stamboken 2024-04-20.", self.texts(proposal, False))
        proposal = self.propose(self.existing("2412", kon="Hane", namn="Ebbe", fodelsedatum="240421"))
        self.assertEqual(self.source(proposal, "individual"), ("avviker", None))  # a digital one too

    def test_a_rabbit_with_a_sister_is_read_only_by_its_name(self):
        sisters = [
            ("G9003-2421", "female", "Lova", {"certificate": None}),
            ("G9003-2422", "female", "Lisa", {"certificate": None}),
            ("G9003-2423", "female", "Vera", {"certificate": None, "digital_certificate": 9002}),
            ("G9003-2424", "female", "Vega", {"certificate": None, "digital_certificate": 9003}),
        ]
        self.litter("G9003", "G9001-2211", "G9003-2311", date(2024, 6, 1), sisters)  # G9003's first litter of 2024
        for number, name, source in (
            ("2422", "", "osäker"),  # the name not read: Lova as likely
            ("2422", "Lisa", "läst"),
            ("2424", "", "osäker"),  # a digital certificate is no exception
            ("2424", "Vega", "läst"),
        ):
            with self.subTest(number=number, name=name):
                reading_ = self.existing(number, genbanksnr="G9003", kon="Hona", namn=name, fodelsedatum="240601")
                proposal = self.propose(reading_)
                self.assertEqual(self.source(proposal, "individual")[0], source)
        proposal = self.propose(self.existing("2424", genbanksnr="G9003", kon="Hona", namn="", fodelsedatum="240601"))
        self.assertNotIn("G9003-2424 finns redan med digitalt intyg.", self.texts(proposal))

    def test_a_paper_certificate_for_a_rabbit_in_stamboken(self):
        proposal = self.propose(self.existing("2411", namn="Elsa"))
        self.assertEqual(self.source(proposal, "individual"), ("läst", "G9001-2411"))
        self.assertEqual(self.source(proposal, "paper_certificate"), ("läst", "SYN-777"))
        self.assertIn("Föräldrarna på intyget stämmer med registret.", self.texts(proposal, True))

    def test_every_row_read_is_set_beside_the_rabbit(self):
        # What the handler compares in "Pappersintyg på en kanin som finns": each row read, against the rabbit.
        db.Individual.update(color=self.colors[1]).where(db.Individual.number == "G9001-2411").execute()
        reading_ = self.existing(
            "2411",
            namn="Elsa",
            levande_efter_6_veckor="3",
            farfar=ancestor("G9002", "2011"),
            farmor=ancestor("G", "??"),
        )
        proposal = self.propose(reading_)
        expected = {
            "individual": ("läst", "G9001-2411"),  # as before
            "paper_number": ("läst", "G9001-2411"),
            "paper_certificate": ("läst", "SYN-777"),
            "mother": ("läst", "G9001-2211"),
            "father": ("läst", "G9003-2311"),
            "birth_date": ("läst", "2024-04-20"),
            "litter_size": ("avviker", None),  # 5 read, 2 registered
            "litter_size6w": ("avviker", None),
            "name": ("läst", "Elsa"),
            "sex": ("läst", "female"),
            "color": ("avviker", None),  # bleighe read, stgröhn registered
            "morfar": ("läst", "G9004-2011"),
            "mormor": ("läst", "G9004-2112"),
            "farfar": ("avviker", None),  # G9002-2011 is not the father's father
            "farmor": ("osäker", None),
        }
        self.assertEqual({key: self.source(proposal, key) for key in proposal["fields"]}, expected)
        registry = {key: proposal["fields"][key].get("registry") for key in ("litter_size", "color", "farfar")}
        self.assertEqual(registry, {"litter_size": 2, "color": "stgröhn", "farfar": "G9003-2011"})
        self.assertEqual(proposal["fields"]["farmor"]["read"], "G ??")
        self.assertEqual(self.texts(proposal, False), [])  # the checks are as they were
        struck = self.propose({**reading_, "overstruket": ["namn", "mormor"]})
        self.assertEqual(self.source(struck, "name"), ("osäker", None))
        self.assertEqual(self.source(struck, "mormor"), ("osäker", None))

    def test_a_report_photo_sets_its_fields_once(self):
        # _registered sets every field itself: the checks it takes from _existing compare nothing more.
        with mock.patch.object(inbox_proposal, "_beside", wraps=inbox_proposal._beside) as beside:
            reading_ = self.existing("2411", namn="Elsa")
            build_proposal(reading_, self.genebanks[0].id, registered=self.r["G9001-2411"])
        self.assertEqual(beside.call_count, 1)

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
        for raw in (None, [], {"far": "G9003-2311", "overstruket": "far", "fodelsedatum": 250510}, {"overstruket": 3}):
            with self.subTest(raw):
                self.assertIsInstance(self.propose(raw)["fields"], dict)


class TestSale(ProposalTest):
    """Rule 5 b: the seller and buyer read at the bottom of the certificate, for the sale panel; nothing confident."""

    def sale(self, own=None, **read):
        """The sale part of a reading of the seller and buyer `read`, on the certificate `own` (default: reading())."""
        raw = {**(own or reading()), "forsaljning": read}
        return sale_part(raw, self.genebanks[0].id, self.propose(raw)["fields"])

    def test_the_buyers_herd_is_filled_only_when_it_is_the_genebanks_as_read(self):
        db.Herd.create(genebank=self.genebanks[0], herd="GX1")
        for written, found in (
            ("G9002", "G9002"),
            ("9002", "G9002"),
            ("g 9002", "G9002"),
            ("M9005", None),  # the other genebank's
            ("G9999", None),  # no such herd
            ("GX1", None),  # outside the association is no herd to fill in
            ("G9OO2", None),  # letters read as digits
        ):
            with self.subTest(written):
                sale = self.sale(kopare_besattning=written, kopare_namn="Köpa Testsson")
                if found:
                    self.assertEqual((sale["buyer_herd"], sale["checks"]), ({"herd": found, "found": True}, []))
                else:  # kept as read, and said
                    self.assertEqual(sale["buyer_herd"], {"herd": written, "found": False})
                    text = f"Köparens besättning {written} finns inte i genbanken."
                    self.assertEqual(sale["checks"], [{"ok": False, "text": text}])

    def test_a_buyer_outside_the_association_in_the_form_the_sale_takes(self):
        sale = self.sale(
            kopare_namn=" Köpa Testsson ",
            kopare_utdelningsadress="Väg 1",
            kopare_postnummer="623 55",
            kopare_ort="Visby",
            kopare_epost="kopa@example.com",
            datum="1/6-25",
        )
        buyer = {
            "name": "Köpa Testsson",
            "postal_address": "Väg 1, 623 55",
            "town": "Visby",
            "email": "kopa@example.com",
        }
        self.assertEqual((sale["buyer"], sale["buyer_herd"], sale["date"]), (buyer, None, "2025-06-01"))
        # 5 b: a sale until 2027 takes it as it is, with the e-mail for the notice only.
        fields = buyer_contact_fields({**buyer, "notice_only": True}, date(2025, 6, 1), address_required=True)
        self.assertEqual((fields["postal_address"], fields["email_notice_only"]), ("Väg 1, 623 55", True))

    def test_a_date_that_does_not_parse_is_none(self):
        for written in ("juni", "31/2-25", "2099-01-01", ""):
            with self.subTest(written):
                self.assertIsNone(self.sale(datum=written, kopare_namn="Köpa Testsson")["date"])

    def test_the_seller_against_the_rabbits_herd_of_origin(self):
        self.litter("G9001", "G9001-2211", "G9003-2311", date(2025, 5, 10), [], size=5)  # the number is läst
        sale = self.sale(saljare_besattning="G9002")
        self.assertEqual(sale["seller_herd"], "G9002")
        text = "Säljarens besättning G9002 avviker från kaninens ursprungsbesättning G9001."
        self.assertEqual(sale["checks"], [{"ok": False, "text": text}])
        self.assertEqual(self.sale(saljare_besattning="9001")["checks"], [])

    def test_the_seller_against_the_number_as_read_when_the_registry_does_not_confirm_it(self):
        unread = reading(ar_kull_individ="")  # the rabbit's number cannot be looked up
        text = "Säljarens besättning G9002 avviker från kaninens ursprungsbesättning G9001."
        self.assertEqual(self.sale(unread, saljare_besattning="G9002")["checks"], [{"ok": False, "text": text}])
        text = "Säljarens besättning G9001 kan inte bekräftas mot registret."
        self.assertEqual(self.sale(unread, saljare_besattning="G9001")["checks"], [{"ok": None, "text": text}])

    def test_no_sale_part_without_a_reading_of_it(self):
        for read in (None, {}, {"kopare_namn": " "}, "Köpa Testsson"):
            with self.subTest(read):
                raw = reading() if read is None else reading(forsaljning=read)
                self.assertIsNone(sale_part(raw, self.genebanks[0].id, {}))
        self.assertNotIn("sale", self.propose(reading(forsaljning={"kopare_namn": "Köpa Testsson"})))
