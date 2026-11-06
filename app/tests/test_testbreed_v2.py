"""Tests for POST /api/v2/testbreed (Provparning v2).

isort:skip_file
"""

import json
import os
from datetime import date
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from blueprints.testbreed_v2 import MAX_ANCESTOR_GENERATIONS, THRESHOLDS, _verdict  # noqa: E402
from herdbook import APP, limiter  # noqa: E402
from utils import genetics_service  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402
from tests.ht_helpers import ht_row  # noqa: E402

limiter.enabled = False

URL = "/api/v2/testbreed"


class TestVerdict(DatabaseTest):
    """Threshold boundaries (4 % / 6 %)."""

    def test_boundaries(self):
        self.assertEqual(THRESHOLDS, {"good_max": 4.0, "check_max": 6.0})
        self.assertEqual(_verdict(0.0), "good")
        self.assertEqual(_verdict(4.0), "good")
        self.assertEqual(_verdict(4.01), "check")
        self.assertEqual(_verdict(6.0), "check")
        self.assertEqual(_verdict(6.01), "high")


class TestTestbreedV2(DatabaseTest):
    """Endpoint behaviour on a small hand-built pedigree.

    F1 (m) x F2 (f) -> S1F (f), S2M (m)           full siblings
    F1b (m) x F2 (f) -> H1M (m)                    S1F/H1M half siblings (mother)
    F1 (m) x S1F (f) -> D1F (f)                    F1/S1F parent-child
    S2M (m) x U2 (f) -> K1M (m)                    K1M/S1F: common F1 + F2 (2,1)
    S1F (f) x S2M (m) -> INB (f)                   F(INB) = 25 %
    U1 (m), U2 (f) unrelated founders.
    """

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        self.nobody = da.register_user("nobody", "pass")
        self._build_pedigree()

    def _login(self, username="spec", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post("/api/login", json={"username": username, "password": password})

    def _ind(self, number, sex, breeding=None, herd=None, name=None):
        return db.Individual.create(
            origin_herd=herd or self.herds[0], number=number, sex=sex, breeding=breeding, name=name
        )

    def _breed(self, mother, father, herd=None):
        return db.Breeding.create(
            breeding_herd_id=herd or self.herds[0],
            mother=mother,
            father=father,
            birth_date=date(2022, 3, 1 + db.Breeding.select().count() % 27),
        )

    def _build_pedigree(self):
        f1 = self._ind("G1-F1", "male", name="Farfar")
        f1b = self._ind("G1-F1B", "male")
        f2 = self._ind("G1-F2", "female", name="Farmor")
        u1 = self._ind("G1-U1", "male")
        u2 = self._ind("G1-U2", "female")
        b1 = self._breed(f2, f1)
        s1f = self._ind("G1-S1F", "female", b1, name="Syster")
        s2m = self._ind("G1-S2M", "male", b1, name="Bror")
        h1m = self._ind("G1-H1M", "male", self._breed(f2, f1b))
        self._ind("G1-D1F", "female", self._breed(s1f, f1))
        self._ind("G1-K1M", "male", self._breed(u2, s2m))
        self._ind("G1-INB", "female", self._breed(s1f, s2m))
        self.mellerud = self._ind("M3-X1M", "male", herd=self.herds[2])
        self.ids = {"f1": f1, "f2": f2, "s1f": s1f, "s2m": s2m, "h1m": h1m, "u1": u1, "u2": u2}

    def _post(self, body):
        return self.client.post(URL, json=body)

    def _single(self, female, male, genebank=None):
        body = {
            "genebank_id": (genebank or self.genebanks[0]).id,
            "female": female,
            "males": [{"number": male}],
        }
        resp = self._post(body)
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        return resp.get_json()

    # --- access ---------------------------------------------------------

    def test_unauthenticated_401(self):
        resp = self._post({"genebank_id": self.genebanks[0].id, "female": "G1-S1F", "males": [{"number": "G1-U1"}]})
        self.assertEqual(resp.status_code, 401)

    def test_user_without_genebank_access_403(self):
        self._login("nobody")
        resp = self._post({"genebank_id": self.genebanks[0].id, "female": "G1-S1F", "males": [{"number": "G1-U1"}]})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.mimetype, "application/problem+json")

    def test_viewer_of_other_genebank_403(self):
        self._login("spec")  # viewer of genebank 0 only
        resp = self._post({"genebank_id": self.genebanks[1].id, "female": "M3-X1M", "males": [{"number": "M3-X1M"}]})
        self.assertEqual(resp.status_code, 403)

    def test_viewer_allowed(self):
        self._login("spec")
        data = self._single("G1-S1F", "G1-U1")
        self.assertEqual(data["results"][0]["verdict"], "good")

    def test_owner_without_manager_role_allowed(self):
        self._login("owner")  # owner(G1) is NOT a genebank manager
        self._single("G1-S1F", "G1-U1")

    # --- validation -----------------------------------------------------

    def test_unknown_number_400_names_number(self):
        self._login()
        resp = self._post({"genebank_id": self.genebanks[0].id, "female": "G1-NOPE", "males": [{"number": "G1-U1"}]})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("G1-NOPE", resp.get_json()["detail"])

    def test_individual_in_other_genebank_400(self):
        self._login("admin")
        resp = self._post({"genebank_id": self.genebanks[0].id, "female": "G1-S1F", "males": [{"number": "M3-X1M"}]})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("M3-X1M", resp.get_json()["detail"])

    GENERIC = "finns inte eller är inte tillgänglig i den valda genbanken."

    def test_unknown_and_inaccessible_give_identical_generic_400(self):
        """Origin in the chosen bank but CURRENT herd in a bank the user can't see."""
        moved = self._ind("G1-MOVED", "male")
        ht_row("BIRTH", herd=self.herds[0], individual=moved, herd_tracking_date=date(2022, 4, 1))
        ht_row("TRANSFER", herd=self.herds[2], individual=moved, herd_tracking_date=date(2023, 4, 1))
        self._login()  # viewer of genebank 0 only
        details = []
        for number in ("G1-MOVED", "G1-NOPE"):
            resp = self._post({"genebank_id": self.genebanks[0].id, "female": "G1-S1F", "males": [{"number": number}]})
            self.assertEqual(resp.status_code, 400, number)
            detail = resp.get_json()["detail"]
            self.assertEqual(detail, f"Individen {number} {self.GENERIC}")
            details.append(detail.replace(number, "X"))
        self.assertEqual(details[0], details[1])

    def test_moved_animal_visible_to_user_with_access_to_current_bank(self):
        moved = self._ind("G1-MOVED", "male")
        ht_row("TRANSFER", herd=self.herds[1], individual=moved, herd_tracking_date=date(2023, 4, 1))
        self._login()
        self._single("G1-S1F", "G1-MOVED")  # now in G2 (same bank): fine
        ht_row("TRANSFER", herd=self.herds[2], individual=moved, herd_tracking_date=date(2024, 4, 1))
        self.client = APP.test_client(use_cookies=True)
        self._login("admin")  # admin sees every bank
        self._single("G1-S1F", "G1-MOVED")

    def test_voided_individual_400_generic(self):
        db.Individual.create(origin_herd=self.herds[0], number="G1-VOID", sex="male", voided=True)
        self._login()
        resp = self._post({"genebank_id": self.genebanks[0].id, "female": "G1-S1F", "males": [{"number": "G1-VOID"}]})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(self.GENERIC, resp.get_json()["detail"])

    def test_voided_and_foreign_ancestors_never_listed(self):
        voided = db.Individual.create(origin_herd=self.herds[0], number="G1-VOID", sex="male", voided=True)
        foreign = self.mellerud  # male, origin Mellerud bank
        # Shared voided father and shared foreign mother-side ancestor would otherwise show up.
        kid_f = self._ind("G1-KF", "female", self._breed(self.ids["f2"], voided))
        kid_m = self._ind("G1-KM", "male", self._breed(self.ids["f2"], voided))
        foreign_mother = self._ind("M3-FM", "female", herd=self.herds[2])
        kid_f2 = self._ind("G1-KF2", "female", self._breed(foreign_mother, foreign))
        kid_m2 = self._ind("G1-KM2", "male", self._breed(foreign_mother, foreign))
        self.assertTrue(kid_f and kid_m and kid_f2 and kid_m2)
        self._login()
        res = self._single("G1-KF", "G1-KM")["results"][0]
        self.assertEqual([a["number"] for a in res["common_ancestors"]], ["G1-F2"])  # shared mother only
        # Relation uses the RECORDED parents: same mother AND same (voided) father = full siblings.
        self.assertEqual(res["relation"], "full_siblings")
        res = self._single("G1-KF2", "G1-KM2")["results"][0]
        self.assertEqual(res["common_ancestors"], [])  # nobody visible to name ...
        self.assertEqual(res["relation"], "full_siblings")  # ... but the warning must not be hidden

    def test_relation_uses_recorded_parents_when_only_shared_parent_is_filtered(self):
        voided = db.Individual.create(origin_herd=self.herds[0], number="G1-VOID", sex="male", voided=True)
        self._ind("G1-HF", "female", self._breed(self.ids["f2"], voided))
        self._ind("G1-HM", "male", self._breed(self.ids["u2"], voided))  # only the voided father is shared
        self._login()
        data = self._single("G1-HF", "G1-HM")
        res = data["results"][0]
        self.assertEqual(res["relation"], "half_siblings")
        self.assertNotIn("G1-VOID", json.dumps(data))

    def test_voided_and_foreign_ancestors_absent_from_whole_response_and_trees(self):
        voided = db.Individual.create(origin_herd=self.herds[0], number="G1-VOID", sex="male", voided=True)
        foreign_mother = self._ind("M3-FM", "female", herd=self.herds[2], name="Främmande")
        # Grandparents on the female side: voided grandfather + foreign grandmother.
        mother = self._ind("G1-GM", "female", self._breed(foreign_mother, voided))
        father = self._ind("G1-GF", "male", self._breed(self.ids["f2"], self.ids["f1"]))
        kid_f = self._ind("G1-TF", "female", self._breed(mother, father))
        kid_m = self._ind("G1-TM", "male", self._breed(mother, father))
        self.assertTrue(kid_f and kid_m)
        self._login()
        resp = self._post(
            {
                "genebank_id": self.genebanks[0].id,
                "female": "G1-TF",
                "males": [
                    {"number": "G1-TM"},
                    {"number": None, "parents": {"mother": "G1-GM", "father": "G1-GF"}},
                ],
            }
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_data(as_text=True)
        for hidden in ("G1-VOID", "M3-FM", "Främmande"):
            self.assertNotIn(hidden, body)
        data = resp.get_json()
        pedigree = data["female"]["pedigree"]
        self.assertEqual(pedigree["number"], "G1-TF")
        self.assertEqual(pedigree["sex"], "female")
        gm = pedigree["mother"]
        self.assertEqual(gm["number"], "G1-GM")
        self.assertIsNone(gm["mother"])  # foreign grandmother -> unknown
        self.assertIsNone(gm["father"])  # voided grandfather -> unknown
        self.assertEqual(pedigree["father"]["mother"]["number"], "G1-F2")
        # The same filtered ancestry for the sibling and, under an "Ej registrerad" node, the virtual male.
        sibling = data["results"][0]["male"]["pedigree"]
        self.assertEqual(sibling["mother"]["mother"], None)
        virtual = data["results"][1]["male"]["pedigree"]
        self.assertTrue(virtual["unregistered"])
        self.assertEqual((virtual["number"], virtual["sex"]), (None, "male"))
        self.assertEqual(virtual["mother"]["number"], "G1-GM")
        self.assertIsNone(virtual["mother"]["mother"])
        self.assertIsNone(virtual["mother"]["father"])

    @staticmethod
    def _depth(node):
        if node is None:
            return 0
        return 1 + max(TestTestbreedV2._depth(node["mother"]), TestTestbreedV2._depth(node["father"]))

    def test_pedigree_has_three_levels_and_nested_shape(self):
        chain = self.ids["f2"]
        for i in range(1, 6):  # 5 generations of mothers on top of G1-F2
            chain = self._ind(f"G1-L{i}", "female", self._breed(chain, self.ids["f1"]))
        self._login()
        data = self._single("G1-L5", "G1-K1M")
        female = data["female"]["pedigree"]
        self.assertEqual(self._depth(female), 3)  # partner + two ancestor generations
        self.assertEqual(set(female), {"id", "number", "name", "sex", "mother", "father"})
        self.assertEqual(female["mother"]["mother"]["number"], "G1-L3")
        self.assertIsNone(female["mother"]["mother"]["mother"])  # cut at depth
        male = data["results"][0]["male"]["pedigree"]
        self.assertEqual(male["number"], "G1-K1M")
        self.assertEqual(male["father"]["number"], "G1-S2M")
        self.assertEqual(male["father"]["father"]["number"], "G1-F1")
        self.assertEqual(self._depth(male), 3)

    def test_virtual_female_pedigree_is_unregistered_node_over_given_parents(self):
        self._login()
        resp = self._post(
            {
                "genebank_id": self.genebanks[0].id,
                "female": None,
                "female_parents": {"mother": "G1-F2", "father": None},
                "males": [{"number": "G1-S2M"}],
            }
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        node = resp.get_json()["female"]["pedigree"]
        self.assertEqual(
            (node["id"], node["number"], node["name"], node["sex"], node["unregistered"]),
            (None, None, None, "female", True),
        )
        self.assertEqual(node["mother"]["number"], "G1-F2")
        self.assertIsNone(node["father"])
        self.assertEqual(self._depth(node), 2)  # unregistered node + mother; her own parents are not recorded

    # --- visibility consistency with GET /api/v2/individual/<n> ---------------

    def test_same_date_tracking_ties_agree_with_individual_endpoint(self):
        """Two herd-tracking rows on one date: the newest row (highest id) decides, in both endpoints."""
        tie = date(2023, 4, 1)
        for number, first, second, visible in (
            ("G1-TIE-A", self.herds[0], self.herds[2], False),  # newest row = other genebank
            ("G1-TIE-B", self.herds[2], self.herds[0], True),  # newest row = accessible
        ):
            animal = self._ind(number, "male", self._breed(self.ids["f2"], self.ids["f1"]))  # as_dict needs a breeding
            ht_row(
                "BIRTH" if first == self.herds[0] else "TRANSFER", herd=first, individual=animal, herd_tracking_date=tie
            )
            ht_row("TRANSFER", herd=second, individual=animal, herd_tracking_date=tie)
            self.client = APP.test_client(use_cookies=True)
            self._login()  # viewer of genebank 0 only
            detail = self.client.get(f"/api/v2/individual/{number}")
            resp = self._post({"genebank_id": self.genebanks[0].id, "female": "G1-S1F", "males": [{"number": number}]})
            self.assertEqual(detail.status_code, 200 if visible else 404, number)
            self.assertEqual(resp.status_code, 200 if visible else 400, number)

    def test_query_count_stays_small_for_one_female_ten_males(self):
        """Ancestor walk = one query per generation for ALL animals, not per animal per generation."""
        u2 = self.ids["f2"]
        chain = [self._ind("G1-C0", "male")]
        for i in range(1, 8):  # 7 generations of male-line ancestry
            chain.append(self._ind(f"G1-C{i}", "male", self._breed(u2, chain[-1])))
        mother_line = [self.ids["f2"]]
        for i in range(1, 8):
            mother_line.append(self._ind(f"G1-D{i}", "female", self._breed(mother_line[-1], self.ids["f1"])))
        real = db.DB_PROXY.obj
        calls = []
        original = real.execute_sql

        def counting(sql, *args, **kwargs):
            calls.append(sql)
            return original(sql, *args, **kwargs)

        self._login()
        males = [f"G1-C{i}" for i in range(2, 8)] + ["G1-U1", "G1-F1", "G1-S2M", "G1-K1M"]
        with mock.patch.object(real, "execute_sql", counting):
            resp = self._post(
                {"genebank_id": self.genebanks[0].id, "female": "G1-D7", "males": [{"number": m} for m in males]}
            )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        # Queries owned by this endpoint: the ancestor walk (alias mother_id) and the
        # individual/current-herd lookups. (calculate_testbreed's own cache checks are excluded.)
        owned = [q for q in calls if 'AS "mother_id"' in q or 'AS "genebank_id" FROM' in q]
        self.assertLessEqual(len(owned), 2 + MAX_ANCESTOR_GENERATIONS + 1, len(owned))

    def test_wrong_sex_400(self):
        self._login()
        resp = self._post({"genebank_id": self.genebanks[0].id, "female": "G1-U1", "males": [{"number": "G1-F1"}]})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("G1-U1", resp.get_json()["detail"])
        resp = self._post({"genebank_id": self.genebanks[0].id, "female": "G1-S1F", "males": [{"number": "G1-F2"}]})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("G1-F2", resp.get_json()["detail"])

    def test_wrong_sex_virtual_parent_400(self):
        self._login()
        resp = self._post(
            {
                "genebank_id": self.genebanks[0].id,
                "female": None,
                "female_parents": {"mother": "G1-F1", "father": "G1-F2"},  # swapped
                "males": [{"number": "G1-U1"}],
            }
        )
        self.assertEqual(resp.status_code, 400)

    def test_more_than_ten_males_400(self):
        self._login()
        resp = self._post(
            {"genebank_id": self.genebanks[0].id, "female": "G1-S1F", "males": [{"number": "G1-U1"}] * 11}
        )
        self.assertEqual(resp.status_code, 400)

    def test_ten_males_ok(self):
        self._login()
        resp = self._post(
            {"genebank_id": self.genebanks[0].id, "female": "G1-S1F", "males": [{"number": "G1-U1"}] * 10}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.get_json()["results"]), 10)

    def test_no_males_or_bad_body_400(self):
        self._login()
        for body in (
            {"genebank_id": self.genebanks[0].id, "female": "G1-S1F", "males": []},
            {"genebank_id": self.genebanks[0].id, "female": "G1-S1F"},
            {"genebank_id": "1", "female": "G1-S1F", "males": [{"number": "G1-U1"}]},
            {"genebank_id": self.genebanks[0].id, "males": [{"number": "G1-U1"}]},  # no female, no parents
            {
                "genebank_id": self.genebanks[0].id,
                "female": "G1-S1F",
                "males": [{"number": None, "parents": {"mother": None, "father": None}}],
            },
            [1, 2],
        ):
            resp = self._post(body)
            self.assertEqual(resp.status_code, 400, body)

    # --- calculation ----------------------------------------------------

    def test_unrelated_is_zero_and_good(self):
        self._login()
        data = self._single("G1-U2", "G1-U1")
        res = data["results"][0]
        self.assertEqual(res["offspring_f"], 0.0)
        self.assertEqual(res["verdict"], "good")
        self.assertIsNone(res["relation"])
        self.assertEqual(res["common_ancestors"], [])
        self.assertEqual(data["thresholds"], {"good_max": 4.0, "check_max": 6.0})

    def test_full_siblings(self):
        self._login()
        res = self._single("G1-S1F", "G1-S2M")["results"][0]
        self.assertEqual(res["offspring_f"], 25.0)
        self.assertEqual(res["verdict"], "high")
        self.assertEqual(res["relation"], "full_siblings")

    def test_half_siblings(self):
        self._login()
        res = self._single("G1-S1F", "G1-H1M")["results"][0]
        self.assertEqual(res["offspring_f"], 12.5)
        self.assertEqual(res["relation"], "half_siblings")
        self.assertEqual(
            [(a["number"], a["generations"]) for a in res["common_ancestors"]],
            [("G1-F2", [1, 1])],
        )

    def test_parent_child_both_directions(self):
        self._login()
        res = self._single("G1-S1F", "G1-F1")["results"][0]  # father x daughter
        self.assertEqual(res["relation"], "parent_child")
        self.assertEqual(res["offspring_f"], 25.0)
        # the father himself is the common ancestor (0 from his side, 1 from hers)
        self.assertEqual(res["common_ancestors"][0]["number"], "G1-F1")
        self.assertEqual(res["common_ancestors"][0]["generations"], [0, 1])
        res = self._single("G1-F2", "G1-S2M")["results"][0]  # son x mother
        self.assertEqual(res["relation"], "parent_child")

    def test_common_ancestors_listed_nearest_first_with_names(self):
        self._login()
        res = self._single("G1-S1F", "G1-K1M")["results"][0]
        self.assertIsNone(res["relation"])
        cas = {a["number"]: a for a in res["common_ancestors"]}
        # K1M -> S2M -> (F1, F2): 2 generations; S1F -> (F1, F2): 1 generation
        self.assertEqual(cas["G1-F1"]["generations"], [2, 1])
        self.assertEqual(cas["G1-F2"]["generations"], [2, 1])
        self.assertEqual(cas["G1-F1"]["name"], "Farfar")
        self.assertEqual(cas["G1-F2"]["name"], "Farmor")
        self.assertEqual(res["offspring_f"], 12.5)

    def test_parent_f_and_mk_in_response(self):
        self._login()
        data = self._single("G1-INB", "G1-U1")
        self.assertEqual(data["female"]["number"], "G1-INB")
        self.assertEqual(data["female"]["f"], 25.0)
        self.assertIn("mk", data["female"])
        self.assertEqual(data["results"][0]["male"]["number"], "G1-U1")
        self.assertEqual(data["results"][0]["male"]["f"], 0.0)

    def test_results_follow_request_order(self):
        self._login()
        resp = self._post(
            {
                "genebank_id": self.genebanks[0].id,
                "female": "G1-S1F",
                "males": [{"number": "G1-S2M"}, {"number": "G1-U1"}],
            }
        )
        res = resp.get_json()["results"]
        self.assertEqual([r["male"]["number"] for r in res], ["G1-S2M", "G1-U1"])
        self.assertEqual([r["verdict"] for r in res], ["high", "good"])

    def test_virtual_female_all_null_summary_and_relation(self):
        self._login()
        resp = self._post(
            {
                "genebank_id": self.genebanks[0].id,
                "female": None,
                "female_parents": {"mother": "G1-F2", "father": "G1-F1"},
                "males": [{"number": "G1-S2M"}],
            }
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        data = resp.get_json()
        self.assertEqual(
            {k: v for k, v in data["female"].items() if k != "pedigree"},
            {"number": None, "name": None, "f": None, "mk": None},
        )
        res = data["results"][0]
        self.assertEqual(res["offspring_f"], 25.0)
        self.assertEqual(res["relation"], "full_siblings")

    def test_virtual_male_one_parent_known(self):
        self._login()
        resp = self._post(
            {
                "genebank_id": self.genebanks[0].id,
                "female": "G1-S1F",
                "males": [{"number": None, "parents": {"mother": "G1-F2", "father": None}}],
            }
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        res = resp.get_json()["results"][0]
        self.assertEqual(res["relation"], "half_siblings")
        self.assertEqual(res["male"]["number"], None)

    # --- parity with the legacy endpoint ---------------------------------

    def _legacy(self, **payload):
        payload["genebankId"] = self.genebanks[0].id
        resp = self.client.post("/api/testbreed", json=payload)
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        return resp.get_json()["offspringCOI"]

    def test_same_f_as_legacy_registered_pair(self):
        self._login()
        # (legacy 500s on founders without a breeding record; v2 handles them, so use bred animals here)
        for female, male in (("G1-S1F", "G1-K1M"), ("G1-S1F", "G1-S2M"), ("G1-INB", "G1-H1M"), ("G1-D1F", "G1-K1M")):
            v2 = self._single(female, male)["results"][0]["offspring_f"]
            legacy = self._legacy(female=female, male=male)
            self.assertAlmostEqual(v2, legacy, places=2, msg=f"{female} x {male}")

    def test_same_f_as_legacy_virtual_parent(self):
        self._login()
        # legacy: maleGF = father, maleGM = mother of the unregistered male
        legacy = self._legacy(female="G1-S1F", male="", maleGF="G1-F1B", maleGM="G1-F2")
        resp = self._post(
            {
                "genebank_id": self.genebanks[0].id,
                "female": "G1-S1F",
                "males": [{"number": None, "parents": {"mother": "G1-F2", "father": "G1-F1B"}}],
            }
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        self.assertAlmostEqual(resp.get_json()["results"][0]["offspring_f"], legacy, places=2)
        self.assertGreater(legacy, 0)

        legacy = self._legacy(female="", male="G1-S2M", femaleGF="G1-F1", femaleGM="G1-F2")
        resp = self._post(
            {
                "genebank_id": self.genebanks[0].id,
                "female": None,
                "female_parents": {"mother": "G1-F2", "father": "G1-F1"},
                "males": [{"number": "G1-S2M"}],
            }
        )
        self.assertAlmostEqual(resp.get_json()["results"][0]["offspring_f"], legacy, places=2)

    # --- one request, one snapshot -------------------------------

    def test_one_request_reads_one_snapshot(self):
        """A snapshot published between two comparisons must not leak into the same response."""
        self._login()
        body = {"genebank_id": self.genebanks[0].id, "female": "G1-S1F", "males": [{"number": "G1-S2M"}] * 2}
        expected = self._post(body).get_json()
        self.assertEqual([r["offspring_f"] for r in expected["results"]], [25.0, 25.0])

        real = genetics_service.calculate_testbreed
        calls = []

        def publish_after_first(genebank_id, *args, **kwargs):
            result = real(genebank_id, *args, **kwargs)
            if not calls:
                # S2M becomes unrelated to S1F, and the new snapshot is published.
                s2m = self.ids["s2m"]
                s2m.breeding = self._breed(self.ids["u2"], self.ids["u1"])
                s2m.save()
                genetics_service.ps.mark_stale(genebank_id)
                genetics_service.ps.wait_for_builds(genebank_id, timeout=10)
            calls.append(result)
            return result

        with mock.patch.object(genetics_service, "calculate_testbreed", publish_after_first):
            resp = self._post(body)
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        self.assertEqual(len(calls), 2)
        self.assertEqual(resp.get_json(), expected)
        # The publication did happen: a new request sees the unrelated pair.
        self.assertEqual(genetics_service.calculate_testbreed(self.genebanks[0].id, "G1-S2M", "G1-S1F"), 0.0)
