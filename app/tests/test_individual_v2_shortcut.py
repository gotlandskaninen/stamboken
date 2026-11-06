"""POST /api/v2/individual without breeding_id: "Lägg till kanin", the litter created on the way.

isort:skip_file
"""

import os
from datetime import date, timedelta

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.database as db  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402
from tests.test_certificates_v2_api import CertV2Mixin  # noqa: E402

limiter.enabled = False

URL = "/api/v2/individual"
BIRTH = "2025-05-10"


class ShortcutMixin:
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="owner", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post("/api/login", json={"username": username, "password": password})

    def _body(self, **overrides):
        # owner owns G1; G1-1911 is a G1 doe, G2-1711 a buck of the same genebank.
        body = {
            "mother": "G1-1911",
            "father": "G2-1711",
            "birth_date": BIRTH,
            "litter_size": 5,
            "litter_size6w": 4,
            "sex": "female",
            "color": "bleighe",
            "certificate_type": "paper",
            "paper_certificate": "SC-1",
            "paper_number": "G1-2511",  # the paper agrees: the year's first litter, position 1
        }
        return {**body, **overrides}

    def _litter(self, birth_date, litter_number, **fields):
        return db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=birth_date,
            litter_number=litter_number,
            litter_size=5,
            litter_size6w=5,
            **fields,
        )

    def _written(self):
        """Litters and rabbits in the database: unchanged after a refusal."""
        return db.Breeding.select().count(), db.Individual.select().count()


class TestShortcutCreate(ShortcutMixin, DatabaseTest):
    def test_creates_the_litter_with_a_default_mating_date(self):
        self._login()
        response = self.client.post(URL, json=self._body())
        self.assertEqual(response.status_code, 201, response.get_json())
        data = response.get_json()
        litter = db.Breeding.get_by_id(data["breeding"]["id"])
        self.assertEqual(data["breeding"], {"id": litter.id, "litter_number": 1, "created": True})
        self.assertEqual(
            (
                litter.breeding_herd_id.herd,
                litter.mother.number,
                litter.father.number,
                litter.birth_date,
                litter.breed_date,
                litter.litter_size,
                litter.litter_size6w,
            ),
            ("G1", "G1-1911", "G2-1711", date(2025, 5, 10), date(2025, 4, 9), 5, 4),
        )
        self.assertEqual((data["individual"]["number"], data["individual"]["certificate"]), ("G1-2511", "SC-1"))

    def test_an_explicit_mating_date_is_kept(self):
        self._login()
        response = self.client.post(URL, json=self._body(breed_date="2025-04-12"))
        self.assertEqual(response.status_code, 201, response.get_json())
        litter = db.Breeding.get_by_id(response.get_json()["breeding"]["id"])
        self.assertEqual(litter.breed_date, date(2025, 4, 12))

    def test_reuses_the_litter_of_the_same_parents_and_birth_date(self):
        litter = self._litter(date(2025, 5, 10), 1, mother=self.parents[0], father=self.parents[1])
        db.Individual.create(number="G1-2511", origin_herd=self.herds[0], breeding=litter, certificate="SC-0")
        before = db.Breeding.select().count()
        self._login()
        response = self.client.post(URL, json=self._body(paper_number="G1-2512"))
        self.assertEqual(response.status_code, 201, response.get_json())
        data = response.get_json()
        self.assertEqual(data["breeding"], {"id": litter.id, "litter_number": 1, "created": False})
        self.assertEqual(data["individual"]["number"], "G1-2512")
        self.assertEqual(db.Breeding.select().count(), before)

    def test_the_litter_number_follows_the_years_litters(self):
        # Litters 1 and 3 earlier in the year (2 was deleted): the new one is 4, not the colliding 3.
        self._litter(date(2025, 1, 5), 1)
        self._litter(date(2025, 2, 1), 3)
        self._login()
        response = self.client.post(URL, json=self._body(paper_number="G1-2541"))
        self.assertEqual(response.status_code, 201, response.get_json())
        data = response.get_json()
        self.assertEqual((data["breeding"]["litter_number"], data["individual"]["number"]), (4, "G1-2541"))

    def test_a_litter_born_before_a_numbered_litter_is_refused(self):
        # Digital: a paper certificate gets the number conflict litter_order instead (test_number_check).
        self._litter(date(2025, 8, 1), 1)
        before = self._written()
        self._login()
        response = self.client.post(URL, json=self._body(certificate_type="digital", paper_certificate=None))
        self.assertEqual((response.status_code, response.get_json()["title"]), (409, "litter_order_conflict"))
        self.assertEqual(self._written(), before)

    def test_a_doe_outside_the_users_herds_is_refused(self):
        before = self._written()
        self._login()
        response = self.client.post(URL, json=self._body(mother="M3-1911", father="M3-1811"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._written(), before)

    def test_a_buck_of_another_genebank_is_refused(self):
        before = self._written()
        self._login()
        response = self.client.post(URL, json=self._body(father="M3-1811"))
        self.assertEqual(
            (response.status_code, response.get_json()["detail"]),
            (400, "Fadern måste vara registrerad i samma genbank som modern."),
        )
        self.assertEqual(self._written(), before)

    def test_unknown_parents_are_refused(self):
        self._login()
        for parents in ({"mother": "G1-9999"}, {"father": None}):
            with self.subTest(parents=parents):
                response = self.client.post(URL, json=self._body(**parents))
                self.assertEqual(
                    (response.status_code, response.get_json()["detail"]),
                    (400, "Välj mor och far bland registrerade kaniner."),
                )

    def test_litter_sizes_are_validated(self):
        before = self._written()
        self._login()
        for sizes, detail in (
            ({"litter_size": 5, "litter_size6w": 6}, "Antal levande vid 6 veckor kan inte vara fler än antal födda."),
            ({"litter_size": 0}, "Ange antal födda (minst 1)."),
            ({"litter_size6w": None}, "Ange antal levande vid 6 veckor (minst 1)."),
        ):
            with self.subTest(sizes=sizes):
                response = self.client.post(URL, json=self._body(**sizes))
                self.assertEqual((response.status_code, response.get_json()["detail"]), (400, detail))
        self.assertEqual(self._written(), before)

    def test_a_doe_with_another_litter_that_day_is_refused(self):
        # The same doe and day with another buck: two litters 0 days apart (the 35-day rule).
        self._litter(date(2025, 5, 10), 1, mother=self.parents[0], father=self.individuals[1])
        before = self._written()
        self._login()
        response = self.client.post(URL, json=self._body())
        self.assertEqual(
            (response.status_code, response.get_json()["detail"]),
            (400, "Honan har redan en kull registrerad inom 35 dagar"),
        )
        self.assertEqual(self._written(), before)

    def test_a_litter_younger_than_six_weeks_is_refused(self):
        before = self._written()
        self._login()
        response = self.client.post(URL, json=self._body(birth_date=str(date.today() - timedelta(days=20))))
        self.assertEqual((response.status_code, response.get_json()["title"]), (422, "too_young"))
        self.assertEqual(self._written(), before)

    def test_paper_requires_its_number(self):
        before = self._written()
        self._login()
        response = self.client.post(URL, json=self._body(paper_certificate=None))
        self.assertEqual(
            (response.status_code, response.get_json()["detail"]), (400, "Intygsnummer krävs för pappersintyg.")
        )
        self.assertEqual(self._written(), before)

    def test_a_failure_after_the_litter_was_created_rolls_it_back(self):
        # Paper certificate "12" belongs to G1-2111: refused (number_conflict) with the litter not written.
        before = self._written()
        self._login()
        response = self.client.post(URL, json=self._body(paper_certificate="12"))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._written(), before)
        self.assertFalse(db.Breeding.select().where(db.Breeding.birth_date == date(2025, 5, 10)).exists())


class TestShortcutSuggestion(ShortcutMixin, DatabaseTest):
    def _suggest(self, **params):
        query = {"mother": "G1-1911", "father": "G2-1711", "birth_date": BIRTH, **params}
        return self.client.get(f"{URL}/suggest-number", query_string=query)

    def test_suggests_the_first_number_of_the_new_litter(self):
        self._litter(date(2025, 2, 1), 1)
        self._login()
        response = self._suggest()
        self.assertEqual(response.status_code, 200, response.get_json())
        data = response.get_json()
        self.assertEqual(
            (data["suggested"], data["litter_number"], data["breeding_id"], data["certificate_blocked_reason"]),
            ("G1-2521", 2, None, "litter_size6w_required"),
        )
        self.assertEqual(db.Breeding.select().where(db.Breeding.birth_date == date(2025, 5, 10)).count(), 0)

    def test_suggests_the_next_number_of_an_existing_litter(self):
        litter = self._litter(date(2025, 5, 10), 1, mother=self.parents[0], father=self.parents[1])
        self._login()
        data = self._suggest().get_json()
        self.assertEqual((data["suggested"], data["breeding_id"], data["litter_number"]), ("G1-2511", litter.id, 1))

    def test_refusals_match_the_registration(self):
        self._litter(date(2025, 8, 1), 1)
        self._login()
        self.assertEqual(self._suggest().status_code, 409)
        self.assertEqual(self._suggest(mother="M3-1911", father="M3-1811").status_code, 403)
        self.assertEqual(self._suggest(birth_date="maj").status_code, 400)


class TestShortcutDigital(ShortcutMixin, CertV2Mixin, DatabaseTest):
    def test_digital_is_issued_at_once(self):
        self._start_mock_aws()
        self._login()
        # Parents with a pedigree of their own, so the real certificate data can be built.
        response = self.client.post(
            URL,
            json=self._body(mother="G1-2111", father="G2-2011", certificate_type="digital", paper_certificate=None),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        data = response.get_json()
        created = db.Individual.get(db.Individual.number == data["individual"]["number"])
        self.assertIsNone(data["certificate_error"])
        self.assertIsNotNone(created.digital_certificate)
        self.assertEqual(data["certificate"], str(created.digital_certificate))
        self.assertEqual(data["individual"]["digital_certificate"], created.digital_certificate)
        self.assertTrue(db.DigitalCertificateV2.get(db.DigitalCertificateV2.individual == created).is_current)
