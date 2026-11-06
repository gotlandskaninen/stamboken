"""The paper certificate's individual number against Stamboken's: dry run, conflict, choice, block.

Registration (promote, Lägg till) answers a paper whose number differs
with a 409 number_conflict and writes nothing until the breeder chooses.

isort:skip_file
"""

import os
import threading
import uuid
from datetime import date, timedelta

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.database as db  # noqa: E402
from blueprints.bunny_v2 import RosterActionError, promote_bunny  # noqa: E402
from herdbook import APP, limiter  # noqa: E402
from utils.database import DATABASE  # noqa: E402

from tests.database_test import _USE_POSTGRES, DatabaseTest  # noqa: E402

limiter.enabled = False

CHECK = "/api/v2/individual/number-check"
CREATE = "/api/v2/individual"
IMPORT = "/api/v2/individual/import"


class NumberCheckMixin:
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="owner", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        self.client = APP.test_client(use_cookies=True)  # a logged-in session ignores another login
        return self.client.post("/api/login", json={"username": username, "password": password})

    def _litter(self, birth_date, litter_number, *, mother=None, father=None, litter_size6w=5, herd=None):
        """A G1 litter of 2025 (past the six weeks), with the fixture doe and buck unless told otherwise."""
        return db.Breeding.create(
            breeding_herd_id=herd or self.herds[0],
            breed_date=birth_date - timedelta(days=31),
            birth_date=birth_date,
            litter_number=litter_number,
            litter_size=5,
            litter_size6w=litter_size6w,
            mother=mother,
            father=father,
        )

    def _parents(self):
        return {"mother": self.parents[0], "father": self.parents[1]}

    def _rabbit(self, number, litter, **fields):
        return db.Individual.create(number=number, origin_herd=litter.breeding_herd_id, breeding=litter, **fields)

    def _check(self, **body):
        return self.client.post(CHECK, json=body)

    def _kinds(self, data):
        return [c["kind"] for c in data["conflicts"]]

    def _written(self):
        return db.Breeding.select().count(), db.Individual.select().count(), db.IndividualCommand.select().count()


class TestDryRun(NumberCheckMixin, DatabaseTest):
    def test_match(self):
        litter = self._litter(date(2025, 4, 3), 1, **self._parents())
        self._login()
        before = self._written()
        response = self._check(breeding_id=litter.id, paper_number="G1-2511", paper_certificate="P-1")
        self.assertEqual(response.status_code, 200, response.get_json())
        data = response.get_json()
        self.assertEqual(
            (data["status"], data["stamboken_number"], data["paper_number"], data["conflicts"], data["choices"]),
            ("match", "G1-2511", "G1-2511", [], []),
        )
        self.assertEqual(self._written(), before)

    def test_litter_names_the_litter_that_holds_the_papers_digit(self):
        first = self._litter(date(2025, 4, 3), 1)
        self._rabbit("G1-2511", first, certificate="P-0")
        second = self._litter(date(2025, 5, 10), 2, **self._parents())
        self._login()
        data = self._check(breeding_id=second.id, paper_number="G1-2512").get_json()
        self.assertEqual((data["status"], data["stamboken_number"]), ("conflict", "G1-2522"))
        conflict = data["conflicts"][0]
        self.assertEqual(
            (conflict["kind"], conflict["paper"], conflict["stamboken"], conflict["holder"]["number"]),
            ("litter", "1", "2", "G1-2511"),
        )
        self.assertEqual(conflict["holder"]["litter"], "parning 2025-03-03, född 2025-04-03")
        self.assertEqual(data["choices"], ["use_stamboken_number", "paper_is_right"])
        action = data["actions"][0]
        self.assertEqual(action["self_service"], "/stamboken/min-besattning?herd=G1&tab=breeding")
        self.assertIn("Kull 1 år 2025 är kullen parning 2025-03-03, född 2025-04-03 (G1-2511…)", action["text"])
        self.assertIn("Pappersintyget säger G1-2512, Stamboken ger G1-2522", action["manager_message"])
        self.assertIn("mor G1-1911, far G2-1711", action["manager_message"])

    def test_position_held_by_a_sibling(self):
        litter = self._litter(date(2025, 4, 3), 1)
        self._rabbit("G1-2512", litter, certificate="P-0")
        self._login()
        data = self._check(breeding_id=litter.id, paper_number="G1-2512").get_json()
        self.assertEqual(data["stamboken_number"], "G1-2511")
        self.assertEqual(self._kinds(data), ["position", "number_taken"])
        self.assertEqual([c["holder"]["number"] for c in data["conflicts"]], ["G1-2512", "G1-2512"])
        self.assertEqual(data["choices"], ["use_stamboken_number", "paper_is_right"])  # G1-2511 is free

    def test_a_free_paper_position_is_taken(self):
        litter = self._litter(date(2025, 4, 3), 1)
        self._login()
        data = self._check(breeding_id=litter.id, paper_number="G1-2513").get_json()
        self.assertEqual((data["status"], data["stamboken_number"]), ("match", "G1-2513"))

    def test_a_retired_paper_position_is_not_taken(self):
        litter = self._litter(date(2025, 4, 3), 1)
        self._rabbit("G1-2513", litter, voided=True)
        self._login()
        data = self._check(breeding_id=litter.id, paper_number="G1-2513").get_json()
        self.assertEqual((data["stamboken_number"], self._kinds(data)), ("G1-2511", ["position", "number_taken"]))

    def test_year_and_prefix_leave_only_paper_is_right(self):
        litter = self._litter(date(2024, 12, 28), 1)
        self._login()
        for paper, kind in (("G1-2511", "year"), ("G2-2411", "prefix")):
            with self.subTest(kind=kind):
                data = self._check(breeding_id=litter.id, paper_number=paper).get_json()
                self.assertEqual((self._kinds(data), data["choices"]), ([kind], ["paper_is_right"]))
                self.assertIsNotNone(data["actions"][0]["text"])

    def test_number_taken_by_a_voided_rabbit_in_another_litter(self):
        other = self._litter(date(2024, 6, 1), 1)
        self._rabbit("G1-2511", other, voided=True)  # a verbatim number, voided since
        litter = self._litter(date(2025, 4, 3), 1)
        self._login()
        data = self._check(breeding_id=litter.id, paper_number="G1-2511").get_json()
        self.assertEqual((data["stamboken_number"], self._kinds(data)), ("G1-2511", ["number_taken"]))
        self.assertEqual(data["choices"], ["paper_is_right"])  # Stamboken's number is the taken one

    def test_a_zero_padded_paper_number_finds_the_row_stored_as_typed(self):
        self._rabbit("G1-25012", self._litter(date(2024, 6, 1), 1))  # legacy, typed zero-padded
        litter = self._litter(date(2025, 4, 3), 1)
        self._login()
        data = self._check(breeding_id=litter.id, paper_number="g1-25012").get_json()
        self.assertEqual((data["paper_number"], data["stamboken_number"]), ("G1-2512", "G1-2512"))
        self.assertEqual(self._kinds(data), ["number_taken"])
        self.assertEqual(data["conflicts"][0]["holder"]["number"], "G1-25012")

    def test_certificate_taken_and_duplicate_rabbit(self):
        litter = self._litter(date(2025, 4, 3), 1, **self._parents())
        self._rabbit("G1-2511", litter, certificate="P-SAME")
        self._login()
        same = self._check(breeding_id=litter.id, paper_number="G1-2512", paper_certificate="P-SAME").get_json()
        other = self._check(breeding_id=litter.id, paper_number="G1-2512", paper_certificate="12").get_json()
        self.assertEqual(self._kinds(same), ["duplicate_rabbit"])
        self.assertEqual(
            (same["conflicts"][0]["paper"], same["conflicts"][0]["holder"]["number"]), ("P-SAME", "G1-2511")
        )
        self.assertEqual(self._kinds(other), ["certificate_taken"])
        self.assertEqual(other["conflicts"][0]["holder"]["number"], "G1-2111")
        # The certificate number is unique: Stamboken's number with it would not save either.
        self.assertEqual((same["choices"], other["choices"]), (["paper_is_right"], ["paper_is_right"]))

    def test_duplicate_rabbit_an_uncertified_sibling(self):
        litter = self._litter(date(2025, 4, 3), 1, **self._parents())
        self._rabbit("G1-2511", litter)  # registered (legacy) without a certificate, not a roster kit
        roster_kit = self._rabbit("G1-2513", litter)
        db.Bunny.create(breeding=litter, slot_order=1, fate="registered", individual=roster_kit)
        self._login()
        data = self._check(breeding_id=litter.id, paper_number="G1-2512").get_json()
        self.assertEqual((data["stamboken_number"], data["status"]), ("G1-2512", "conflict"))
        self.assertEqual(self._kinds(data), ["duplicate_rabbit"])
        self.assertEqual(data["conflicts"][0]["holder"]["number"], "G1-2511")
        self.assertEqual(data["choices"], ["use_stamboken_number", "paper_is_right"])

    def test_duplicate_litter_of_the_same_doe_with_another_father(self):
        litter = self._litter(date(2025, 4, 3), 1, **self._parents())
        near = self._litter(date(2025, 4, 20), 2, mother=self.parents[0], father=self.individuals[1])
        self._litter(date(2025, 6, 1), 3, **self._parents())  # 59 days on: another litter
        self._login()
        data = self._check(breeding_id=near.id, paper_number="G1-2521").get_json()
        self.assertEqual(self._kinds(data), ["duplicate_litter"])
        self.assertEqual(
            (data["conflicts"][0]["stamboken"], data["conflicts"][0]["holder"]["breeding_id"]),
            ("2025-04-03", litter.id),
        )
        self.assertEqual(data["choices"], ["use_stamboken_number", "paper_is_right"])

    def test_missing_litter_is_numbered_by_new_litter_number_not_the_paper(self):
        # Litters 1 and 3 (2 deleted): the litter is created as 4 (max+1), whatever the paper says.
        self._litter(date(2025, 1, 5), 1)
        self._litter(date(2025, 2, 1), 3)
        self._login()
        body = {"mother": "G1-1911", "father": "G2-1711", "birth_date": "2025-05-10"}
        wrong = self._check(**body, paper_number="G1-2522").get_json()
        self.assertEqual((wrong["stamboken_number"], self._kinds(wrong)), ("G1-2542", ["litter_missing"]))
        self.assertEqual((wrong["conflicts"][0]["paper"], wrong["conflicts"][0]["stamboken"]), ("2", "4"))
        self.assertIsNone(wrong["actions"][0]["manager_message"])  # the breeder fixes this alone
        # shortcut: a paper agreeing with the litter to be created is a match (no dialog), not litter_missing.
        right = self._check(**body, paper_number="G1-2542").get_json()
        self.assertEqual((right["status"], right["stamboken_number"]), ("match", "G1-2542"))

    def test_missing_litter_born_before_a_numbered_one_is_litter_order(self):
        self._litter(date(2025, 8, 1), 1)
        self._login()
        data = self._check(mother="G1-1911", father="G2-1711", birth_date="2025-05-10", paper_number="G1-2511")
        data = data.get_json()
        self.assertEqual(
            (data["status"], data["stamboken_number"], self._kinds(data), data["choices"]),
            ("conflict", None, ["litter_order"], ["paper_is_right"]),
        )
        self.assertEqual(data["conflicts"][0]["holder"]["litter_number"], 1)
        self.assertIn("född före kull 1", data["actions"][0]["text"])

    def test_missing_litter_born_before_an_unborn_numbered_one_is_litter_order(self):
        # Kull 1 is mated but not born yet: it counts from its mating date + 30 days, as new_litter_number does.
        db.Breeding.create(breeding_herd_id=self.herds[0], breed_date=date(2025, 7, 1), litter_number=1)
        self._login()
        data = self._check(mother="G1-1911", father="G2-1711", birth_date="2025-05-10", paper_number="G1-2511")
        data = data.get_json()
        self.assertEqual((data["status"], self._kinds(data)), ("conflict", ["litter_order"]))
        self.assertEqual(data["conflicts"][0]["holder"]["litter_number"], 1)

    def test_a_mother_without_a_herd_is_refused(self):
        # Her latest herd-tracking row has no herd: the litter's herd cannot be determined (was a 500).
        db.HerdTracking.create(
            individual=self.parents[0],
            herd=None,
            herd_tracking_date=date.today(),
            kind="TRANSFER",
            operation_id=uuid.uuid4(),
        )
        self.assertIsNone(db.Individual.get_by_id(self.parents[0].id).current_herd)
        self._login()
        litter = {"mother": "G1-1911", "father": "G2-1711", "birth_date": "2025-05-10"}
        self.assertEqual(self._check(**litter, paper_number="G1-2511").status_code, 403)
        body = {**litter, "sex": "female", "color": "bleighe", "litter_size": 5, "litter_size6w": 4}
        self.assertEqual(self.client.post(CREATE, json={**body, "certificate_type": "digital"}).status_code, 403)

    def test_a_litter_without_birth_date_leaves_it_out_of_the_message(self):
        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0], breed_date=date(2025, 3, 3), litter_number=1, **self._parents()
        )
        self._rabbit("G1-2511", self._litter(date(2024, 6, 1), 1))
        self._login()
        data = self._check(breeding_id=litter.id, paper_number="G1-2511").get_json()
        self.assertEqual((data["status"], self._kinds(data)), ("uncomputable", ["number_taken"]))
        message = data["actions"][0]["manager_message"]
        self.assertIn("Kullen: besättning G1, mor G1-1911, far G2-1711. Jag menar", message)
        self.assertNotIn("None", message)

    def test_uncomputable_without_a_litter_number(self):
        litter = self._litter(date(2025, 4, 3), None)
        self._login()
        data = self._check(breeding_id=litter.id, paper_number="G1-2511").get_json()
        self.assertEqual(
            (data["status"], data["stamboken_number"], data["choices"]), ("uncomputable", None, ["paper_is_right"])
        )

    def test_holder_only_in_accessible_genebanks_and_contactable_for_managers(self):
        mellerud = self._litter(date(2024, 6, 1), 1, herd=self.herds[2])
        self._rabbit("G1-2511", mellerud)  # a G1 number on a Mellerud rabbit: the owner may not see it
        membership = db.Membership.create()
        db.Herd.update(membership=membership).where(db.Herd.id == self.herds[0].id).execute()
        mine = self._litter(date(2025, 4, 3), 1)
        self._rabbit("G1-2512", mine, certificate="P-0")
        self._login()
        hidden = self._check(breeding_id=mine.id, paper_number="G1-2511").get_json()
        self.assertEqual([c["holder"] for c in hidden["conflicts"] if c["kind"] == "number_taken"], [None])
        seen = self._check(breeding_id=mine.id, paper_number="G1-2512").get_json()
        self.assertNotIn("contactable", seen["conflicts"][0]["holder"])
        self._login("man")
        managed = self._check(breeding_id=mine.id, paper_number="G1-2512").get_json()
        self.assertTrue(managed["conflicts"][0]["holder"]["contactable"])

    def test_refusals(self):
        litter = self._litter(date(2025, 4, 3), 1)
        mellerud = self._litter(date(2025, 4, 3), 1, herd=self.herds[2])
        self._login()
        self.assertEqual(self._check(breeding_id=litter.id, paper_number="2511").status_code, 400)
        self.assertEqual(self._check(breeding_id=litter.id).status_code, 400)
        self.assertEqual(self._check(breeding_id=mellerud.id, paper_number="M3-2511").status_code, 403)
        self.assertEqual(self._check(breeding_id=999999, paper_number="G1-2511").status_code, 404)


class TestRegistration(NumberCheckMixin, DatabaseTest):
    """POST /api/v2/individual (Lägg till) and promote with a paper certificate."""

    def setUp(self):
        super().setUp()
        self.first = self._litter(date(2025, 4, 3), 1)
        self._rabbit("G1-2511", self.first, certificate="P-0")
        # The rabbit's litter: number 2, alive at 6 weeks not declared yet.
        self.litter = self._litter(date(2025, 5, 10), 2, litter_size6w=None, **self._parents())

    def _body(self, **overrides):
        body = {
            "breeding_id": self.litter.id,
            "sex": "female",
            "color": "bleighe",
            "litter_size6w": 4,
            "certificate_type": "paper",
            "paper_certificate": "P-NEW",
            "paper_number": "G1-2512",  # kull 1 on the paper, kull 2 in Stamboken
        }
        return {**body, **overrides}

    def _assert_nothing_written(self, before):
        self.assertEqual(self._written(), before)
        self.assertIsNone(db.Breeding.get_by_id(self.litter.id).litter_size6w)

    def test_409_without_a_resolution_writes_nothing(self):
        self._login()
        before = self._written()
        response = self.client.post(CREATE, json=self._body())
        problem = response.get_json()
        self.assertEqual((response.status_code, problem["title"]), (409, "number_conflict"), problem)
        self.assertEqual(
            (problem["check_status"], problem["stamboken_number"], problem["paper_number"], self._kinds(problem)),
            ("conflict", "G1-2522", "G1-2512", ["litter"]),
        )
        self.assertEqual(problem["choices"], ["use_stamboken_number", "paper_is_right"])
        self.assertEqual(problem["status"], 409)  # the HTTP status; the check's own is check_status
        self._assert_nothing_written(before)

    def test_use_stamboken_number_registers_and_logs_the_choice(self):
        self._login()
        resolution = {"expected_number": "G1-2522", "choice": "use_stamboken_number"}
        response = self.client.post(CREATE, json=self._body(resolution=resolution))
        self.assertEqual(response.status_code, 201, response.get_json())
        rabbit = db.Individual.get(db.Individual.number == "G1-2522")
        self.assertEqual((rabbit.certificate, db.Breeding.get_by_id(self.litter.id).litter_size6w), ("P-NEW", 4))
        # The paper's number is stored nowhere on the rabbit, only in its change history.
        self.assertNotIn("G1-2512", [str(v) for v in rabbit.__data__.values()])
        entry = db.IndividualCommand.get(db.IndividualCommand.individual == rabbit)
        self.assertEqual(
            (entry.command, entry.actor_id, entry.before, entry.after),
            (
                "UseStambokenNumber",
                self.owner.id,
                {"paper_number": "G1-2512"},
                {"number": "G1-2522", "conflicts": ["litter"]},
            ),
        )

    def test_an_expected_number_that_changed_gives_a_new_409(self):
        self._login()
        before = self._written()
        resolution = {"expected_number": "G1-2521", "choice": "use_stamboken_number"}
        response = self.client.post(CREATE, json=self._body(resolution=resolution))
        self.assertEqual((response.status_code, response.get_json()["stamboken_number"]), (409, "G1-2522"))
        self._assert_nothing_written(before)

    def test_paper_is_right_writes_nothing_and_returns_the_actions(self):
        self._login()
        before = self._written()
        resolution = {"expected_number": "G1-2522", "choice": "paper_is_right"}
        response = self.client.post(CREATE, json=self._body(resolution=resolution))
        self.assertEqual(response.status_code, 409)
        self.assertEqual([a["kind"] for a in response.get_json()["actions"]], ["litter"])
        self._assert_nothing_written(before)

    def test_a_choice_not_offered_is_refused(self):
        self._login()
        before = self._written()
        resolution = {"expected_number": "G1-2522", "choice": "use_stamboken_number"}
        response = self.client.post(CREATE, json=self._body(paper_number="G1-2422", resolution=resolution))
        self.assertEqual((response.status_code, response.get_json()["choices"]), (409, ["paper_is_right"]))
        self._assert_nothing_written(before)

    def test_a_taken_certificate_is_a_number_conflict_not_a_failed_write(self):
        self._login()
        before = self._written()
        resolution = {"expected_number": "G1-2522", "choice": "use_stamboken_number"}
        response = self.client.post(CREATE, json=self._body(paper_certificate="P-0", resolution=resolution))
        problem = response.get_json()
        self.assertEqual(
            (response.status_code, problem["title"], problem["choices"]), (409, "number_conflict", ["paper_is_right"])
        )
        self._assert_nothing_written(before)

    def test_paper_needs_its_individual_number(self):
        self._login()
        for value in (None, "", "kull 2"):
            with self.subTest(paper_number=value):
                response = self.client.post(CREATE, json=self._body(paper_number=value))
                self.assertEqual(response.status_code, 400)
        response = self.client.post(CREATE, json=self._body(resolution={"choice": "renumber_stamboken"}))
        self.assertEqual(response.status_code, 400)

    def test_lagg_till_takes_the_papers_free_position(self):
        self._login()
        response = self.client.post(CREATE, json=self._body(paper_number="G1-2524", position=1))
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["individual"]["number"], "G1-2524")
        self.assertFalse(db.IndividualCommand.select().exists())  # a match is not a choice

    def test_missing_litter_with_a_wrong_digit(self):
        self._login()
        body = {**self._body(), "breeding_id": None, "birth_date": "2025-06-20", "litter_size": 5}
        body.update(mother="G1-1911", father="G2-1711", paper_number="G1-2512")
        before = self._written()
        response = self.client.post(CREATE, json=body)
        problem = response.get_json()
        self.assertEqual(
            (response.status_code, problem["stamboken_number"], self._kinds(problem)),
            (409, "G1-2532", ["litter_missing"]),
        )
        self.assertEqual(self._written(), before)
        body["resolution"] = {"expected_number": "G1-2532", "choice": "use_stamboken_number"}
        response = self.client.post(CREATE, json=body)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(
            (response.get_json()["individual"]["number"], response.get_json()["breeding"]["litter_number"]),
            ("G1-2532", 3),
        )

    def test_missing_litter_born_before_a_numbered_one(self):
        self._login()
        body = {**self._body(), "breeding_id": None, "birth_date": "2025-03-20", "litter_size": 5}
        body.update(mother="G1-1911", father="G2-1711", paper_number="G1-2522")
        before = self._written()
        response = self.client.post(CREATE, json=body)
        problem = response.get_json()
        self.assertEqual(
            (response.status_code, problem["title"], self._kinds(problem)), (409, "number_conflict", ["litter_order"])
        )
        self.assertIsNone(problem["stamboken_number"])
        self.assertEqual(self._written(), before)

    def _roster(self, slots=2):
        db.Breeding.update(litter_size6w=4).where(db.Breeding.id == self.litter.id).execute()
        return [
            db.Bunny.create(breeding=self.litter, slot_order=i, observed_sex="female", observed_color="bleighe")
            for i in range(1, slots + 1)
        ]

    def _promote(self, bunny, **body):
        body = {"certificate_type": "paper", "paper_certificate": "P-NEW", **body}
        return self.client.post(f"/api/v2/bunny/{bunny.id}/promote", json=body)

    def test_promote_saves_alive_at_6_weeks_only_with_the_registration(self):
        bunny = db.Bunny.create(breeding=self.litter, slot_order=1, observed_sex="female", observed_color="bleighe")
        self._login()
        before = self._written()
        response = self._promote(bunny, paper_number="G1-2512", litter_size6w=4)
        self.assertEqual((response.status_code, response.get_json()["title"]), (409, "number_conflict"))
        self._assert_nothing_written(before)  # litter_size6w still unset
        resolution = {"expected_number": "G1-2522", "choice": "use_stamboken_number"}
        response = self._promote(bunny, paper_number="G1-2512", litter_size6w=4, resolution=resolution)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(db.Breeding.get_by_id(self.litter.id).litter_size6w, 4)

    def test_promote_takes_the_papers_free_position(self):
        first, _second = self._roster()
        self._login()
        response = self._promote(first, paper_number="G1-2523")
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["individual"]["number"], "G1-2523")

    def test_promote_conflict_writes_nothing_then_the_choice_registers(self):
        first, _second = self._roster()
        self._login()
        before = self._written()
        response = self._promote(first, paper_number="G1-2512")
        self.assertEqual((response.status_code, self._kinds(response.get_json())), (409, ["litter"]))
        self.assertEqual(self._written(), before)
        self.assertEqual(db.Bunny.get_by_id(first.id).fate, "undecided")
        resolution = {"expected_number": "G1-2522", "choice": "use_stamboken_number"}
        response = self._promote(first, paper_number="G1-2512", resolution=resolution)
        self.assertEqual((response.status_code, response.get_json()["individual"]["number"]), (201, "G1-2522"))
        self.assertEqual(db.IndividualCommand.get().before, {"paper_number": "G1-2512"})

    def test_promote_a_taken_paper_position_is_position(self):
        first, second = self._roster()
        self._login()
        self.assertEqual(self._promote(first, paper_number="G1-2521").status_code, 201)
        response = self._promote(second, paper_number="G1-2521", paper_certificate="P-2")
        problem = response.get_json()
        self.assertEqual((response.status_code, problem["stamboken_number"]), (409, "G1-2522"))
        self.assertEqual(self._kinds(problem), ["position", "number_taken"])

    def test_promote_in_a_litter_without_litter_number_is_uncomputable(self):
        db.Breeding.update(litter_number=None, litter_size6w=4).where(db.Breeding.id == self.litter.id).execute()
        bunny = db.Bunny.create(breeding=self.litter, slot_order=1, observed_sex="female", observed_color="bleighe")
        self._login()
        response = self._promote(bunny, paper_number="G1-2521")
        self.assertEqual((response.status_code, response.get_json()["check_status"]), (409, "uncomputable"))


class TestImport(NumberCheckMixin, DatabaseTest):
    def _import(self, number, birth_date="2025-05-10"):
        return self.client.post(IMPORT, json={"herd": "G1", "birth_date": birth_date, "number": number})

    def test_the_phantom_litter_is_the_litter_the_number_names(self):
        self._login("admin")
        response = self._import("G1-2532")
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(db.Individual.get(db.Individual.number == "G1-2532").breeding.litter_number, 3)

    def test_siblings_share_the_phantom_litter(self):
        self._login("admin")
        first, second = self._import("G1-2531"), self._import("G1-2532")
        self.assertEqual((first.status_code, second.status_code), (201, 201), second.get_json())
        litters = {db.Individual.get(db.Individual.number == n).breeding_id for n in ("G1-2531", "G1-2532")}
        self.assertEqual(len(litters), 1)

    def test_a_taken_litter_digit_is_refused(self):
        self._litter(date(2025, 5, 10), 3, **self._parents())  # a real litter: register in it instead
        self._login("admin")
        before = self._written()
        response = self._import("G1-2532")
        self.assertEqual(response.status_code, 409)
        self.assertIn("Kull 3 år 2025 finns redan", response.get_json()["detail"])
        self.assertEqual(self._written(), before)

    def test_the_number_check_applies(self):
        other = self._litter(date(2024, 6, 1), 1)
        self._rabbit("G1-2531", other, voided=True)
        self._login("admin")
        before = self._written()
        for number, kind in (("G1-2531", "number_taken"), ("G1-2432", "year")):
            with self.subTest(number=number):
                response = self._import(number)
                self.assertEqual((response.status_code, self._kinds(response.get_json())), (409, [kind]))
        self.assertEqual(self._written(), before)


class TestConcurrentRegistrations(NumberCheckMixin, DatabaseTest):
    def test_two_registrations_in_one_herd_year_do_not_deadlock(self):
        """Both lock the herd/year's litters first, then their own."""
        if not _USE_POSTGRES:
            self.skipTest("row locks need PostgreSQL")
        litters = [self._litter(date(2025, 4, 3), 1), self._litter(date(2025, 5, 10), 2)]
        bunnies = [
            db.Bunny.create(breeding=litter, slot_order=1, observed_sex="female", observed_color="bleighe")
            for litter in litters
        ]
        barrier, results = threading.Barrier(2), {}

        def worker(bunny, paper):
            try:
                DATABASE.connect(reuse_if_open=True)
                barrier.wait()
                ind, _cert, _err = promote_bunny(
                    bunny.id,
                    user=self.owner,
                    user_id=self.owner.uuid,
                    certificate_type="paper",
                    paper_certificate=f"P-{paper}",
                    paper_number=paper,
                )
                results[paper] = ind.number
            except RosterActionError as exc:
                results[paper] = exc.status
            except Exception as exc:  # noqa: BLE001 — a deadlock surfaces here
                results[paper] = repr(exc)
            finally:
                DATABASE.close()

        threads = [
            threading.Thread(target=worker, args=pair) for pair in zip(bunnies, ("G1-2511", "G1-2521"), strict=True)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertEqual(results, {"G1-2511": "G1-2511", "G1-2521": "G1-2521"})


class TestFirstPaperCertificateOnAnExistingRabbit(NumberCheckMixin, DatabaseTest):
    """PATCH /api/individual/<number> (v2) and legacy PATCH /api/individual: the command layer checks."""

    def setUp(self):
        super().setUp()
        self.litter = self._litter(date(2025, 5, 10), 2, **self._parents())
        self.right = self._rabbit("G1-2521", self.litter)  # uncertified, its number agrees with kull 2
        self.wrong = self._rabbit("G1-2512", self.litter)  # uncertified, legacy-typed: kull 1 on kull 2
        self._login()

    def _legacy(self, rabbit, **fields):
        return self.client.patch(
            "/api/individual", json={"id": rabbit.id, "number": rabbit.number, "herd": "G1", **fields}
        )

    def _stored(self, rabbit):
        row = db.Individual.get_by_id(rabbit.id)
        return row.number, row.certificate

    def test_v2_needs_the_papers_number(self):
        response = self.client.patch(f"/api/individual/{self.right.number}", json={"certificate": "P-1"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._stored(self.right), ("G1-2521", None))

    def test_v2_paper_that_differs_is_409(self):
        body = {"certificate": "P-1", "paper_number": "G1-2511"}
        response = self.client.patch(f"/api/individual/{self.right.number}", json=body)
        problem = response.get_json()
        self.assertEqual((response.status_code, problem["title"]), (409, "number_conflict"), problem)
        self.assertEqual((problem["stamboken_number"], self._kinds(problem)), ("G1-2521", ["litter"]))
        self.assertEqual(self._stored(self.right), ("G1-2521", None))

    def test_v2_paper_that_agrees_with_the_litter_but_not_the_stored_number_is_409(self):
        # Stored G1-2512 in kull 2: the paper's G1-2522 is what the litter gives, not the rabbit's number.
        body = {"certificate": "P-1", "paper_number": "G1-2522"}
        response = self.client.patch(f"/api/individual/{self.wrong.number}", json=body)
        problem = response.get_json()
        self.assertEqual((response.status_code, problem["title"]), (409, "number_conflict"), problem)
        self.assertIn("Numret G1-2512 stämmer inte med kullen (kull 2 år 2025)", problem["detail"])
        self.assertEqual(self._stored(self.wrong), ("G1-2512", None))

    def test_v2_paper_that_agrees_is_stored(self):
        body = {"certificate": "P-1", "paper_number": "g1-2521"}
        response = self.client.patch(f"/api/individual/{self.right.number}", json=body)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self._stored(self.right), ("G1-2521", "P-1"))

    def test_legacy_on_a_rabbit_whose_number_differs(self):
        response = self._legacy(self.wrong, certificate="P-1")
        self.assertEqual(response.status_code, 200)
        envelope = response.get_json()
        self.assertEqual(
            (envelope["status"], envelope["message"]),
            (
                "error",
                "Numret G1-2512 stämmer inte med kullen (kull 2 år 2025). "
                "Använd G1-2522 eller kontakta genbanksansvarig.",
            ),
        )
        self.assertEqual(self._stored(self.wrong), ("G1-2512", None))

    def test_legacy_on_a_rabbit_whose_number_agrees(self):
        response = self._legacy(self.right, certificate="P-1")
        self.assertEqual(response.get_json()["status"], "success", response.get_json())
        self.assertEqual(self._stored(self.right), ("G1-2521", "P-1"))

    def test_legacy_number_and_certificate_in_one_call(self):
        response = self.client.patch(
            "/api/individual", json={"id": self.right.id, "number": "G1-2513", "herd": "G1", "certificate": "P-1"}
        )
        self.assertEqual(response.get_json()["status"], "error", response.get_json())
        self.assertEqual(self._stored(self.right), ("G1-2521", None))

    def test_a_rename_and_a_paper_that_disagrees_in_one_call(self):
        # The rename is one the litter gives, the paper says the old number: the paper must still be compared.
        body = {"id": self.right.id, "number": "G1-2523", "herd": "G1", "certificate": "P-1", "paper_number": "G1-2521"}
        response = self.client.patch("/api/individual", json=body)
        self.assertEqual(response.get_json()["status"], "error", response.get_json())
        self.assertEqual(self._stored(self.right), ("G1-2521", None))

    def test_legacy_number_and_certificate_in_two_calls(self):
        renamed = self.client.patch("/api/individual", json={"id": self.right.id, "number": "G1-2513", "herd": "G1"})
        self.assertIn("stämmer inte med kullen", renamed.get_json()["message"])
        self.assertEqual(self._stored(self.right), ("G1-2521", None))
        # A rename the litter agrees with passes, and the certificate after it.
        moved = self.client.patch("/api/individual", json={"id": self.right.id, "number": "G1-2523", "herd": "G1"})
        self.assertEqual(moved.get_json()["status"], "success", moved.get_json())
        self.right = db.Individual.get_by_id(self.right.id)
        self.assertEqual(self._legacy(self.right, certificate="P-1").get_json()["status"], "success")
        self.assertEqual(self._stored(self.right), ("G1-2523", "P-1"))

    def test_correcting_a_stored_certificate_number_is_unchanged(self):
        db.Individual.update(certificate="P-OLD").where(db.Individual.id == self.wrong.id).execute()
        self._login("man")
        response = self.client.patch(
            "/api/individual", json={"id": self.wrong.id, "number": "G1-2512", "herd": "G1", "certificate": "P-NEW"}
        )
        self.assertEqual(response.get_json()["status"], "success", response.get_json())
        self.assertEqual(self._stored(self.wrong), ("G1-2512", "P-NEW"))


class TestLegacyCreate(NumberCheckMixin, DatabaseTest):
    """Legacy POST /api/individual: the number's year and litter digit must be the litter's."""

    def _post(self, number):
        litter = self.litter
        body = {"herd": "G1", "origin_herd": {"herd": "G1"}, "birth_date": "2025-05-10", "breeding": litter.id}
        return self.client.post("/api/individual", json={**body, "number": number, "certificate": f"P-{number}"})

    def setUp(self):
        super().setUp()
        self.litter = self._litter(date(2025, 5, 10), 2, **self._parents())
        self._login()

    def test_wrong_litter_digit_or_year(self):
        for number, right in (("G1-2512", "G1-2522"), ("G1-2422", "G1-2522")):
            with self.subTest(number=number):
                response = self._post(number)
                self.assertEqual(
                    (response.status_code, response.get_json()),
                    (
                        200,
                        {
                            "status": "error",
                            "message": f"Numret {number} stämmer inte med kullen (kull 2 år 2025). "
                            f"Använd {right} eller kontakta genbanksansvarig.",
                        },
                    ),
                )
                self.assertFalse(db.Individual.select().where(db.Individual.number == number).exists())

    def test_the_right_number_is_created_as_today(self):
        response = self._post("G1-2523")
        self.assertEqual(response.get_json()["status"], "success", response.get_json())
        self.assertTrue(db.Individual.select().where(db.Individual.number == "G1-2523").exists())
