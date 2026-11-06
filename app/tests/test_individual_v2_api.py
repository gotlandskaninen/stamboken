"""Tests for v2 individual creation endpoint.

isort:skip_file
"""

import os
from datetime import date, timedelta
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.database as db  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402

limiter.enabled = False

IMPORT_URL = "/api/v2/individual/import"


class TestCreateIndividualV2(DatabaseTest):
    """Tests for POST /api/v2/individual."""

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()
        # Create a breeding with litter_number for registration tests.
        # Historical date: the litter must be past the 42-day minimum age
        # on any calendar date (mirrors _old_litter in test_bunny_v2_api).
        self.test_breeding = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2025, 3, 25),
            litter_number=1,
            litter_size=5,
            mother=self.parents[0],
            father=self.parents[1],
        )

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post(
            "/api/login",
            json={"username": username, "password": password},
        )

    def test_creates_individual_with_auto_number(self):
        """POST /api/v2/individual creates rabbit with auto-generated number."""
        self._login()
        response = self.client.post(
            "/api/v2/individual",
            json={
                "breeding_id": self.test_breeding.id,
                "sex": "female",
                "color": "bleighe",
                "name": "TestKanin",
                "certificate_type": "paper",
                "paper_number": "G1-2511",
                "paper_certificate": "GK-TEST-001",
                "litter_size6w": 5,
            },
        )
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertIn("individual", data)
        self.assertIsNotNone(data["individual"]["number"])
        self.assertEqual(data["individual"]["name"], "TestKanin")

    def test_creates_with_paper_certificate(self):
        """Creating with paper certificate stores the number."""
        self._login()
        response = self.client.post(
            "/api/v2/individual",
            json={
                "breeding_id": self.test_breeding.id,
                "sex": "male",
                "color": "bleighe",
                "certificate_type": "paper",
                "paper_number": "G1-2511",
                "paper_certificate": "GK-TEST-001",
                "litter_size6w": 5,
            },
        )
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertEqual(data["individual"]["certificate"], "GK-TEST-001")

    def test_unknown_sex_sends_null(self):
        """Sex=null creates individual with no sex set."""
        self._login()
        response = self.client.post(
            "/api/v2/individual",
            json={
                "breeding_id": self.test_breeding.id,
                "sex": None,
                "color": "bleighe",
                "certificate_type": "paper",
                "paper_number": "G1-2511",
                "paper_certificate": "GK-TEST-001",
                "litter_size6w": 5,
            },
        )
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertIsNone(data["individual"]["sex"])

    def test_requires_breeding_id(self):
        """Missing breeding_id returns 400."""
        self._login()
        response = self.client.post(
            "/api/v2/individual",
            json={"sex": "female", "color": "bleighe", "certificate_type": "paper", "paper_certificate": "GK-TEST-001"},
        )
        self.assertEqual(response.status_code, 400)

    def test_requires_authentication(self):
        """Unauthenticated request returns 401."""
        response = self.client.post(
            "/api/v2/individual",
            json={
                "breeding_id": self.test_breeding.id,
                "sex": "female",
                "color": "bleighe",
                "certificate_type": "paper",
                "paper_certificate": "GK-TEST-001",
            },
        )
        self.assertEqual(response.status_code, 401)

    def test_updates_litter_size6w(self):
        """Providing litter_size6w updates the breeding record."""
        self._login()
        response = self.client.post(
            "/api/v2/individual",
            json={
                "breeding_id": self.test_breeding.id,
                "sex": "female",
                "color": "bleighe",
                "certificate_type": "paper",
                "paper_number": "G1-2511",
                "paper_certificate": "GK-TEST-001",
                "litter_size6w": 4,
            },
        )
        self.assertEqual(response.status_code, 201)
        b = db.Breeding.get_by_id(self.test_breeding.id)
        self.assertEqual(b.litter_size6w, 4)

    def test_breeding_without_litter_number_returns_400(self):
        """Breeding without litter_number returns 400."""
        b = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2030, 4, 1),
            litter_size=3,
        )
        self._login()
        response = self.client.post(
            "/api/v2/individual",
            json={
                "breeding_id": b.id,
                "sex": "female",
                "color": "bleighe",
                "certificate_type": "paper",
                "paper_certificate": "GK-TEST-001",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_viewer_denied(self):
        """Viewer cannot register individuals."""
        self._login(username="spec", password="pass")
        response = self.client.post(
            "/api/v2/individual",
            json={
                "breeding_id": self.test_breeding.id,
                "sex": "female",
                "color": "bleighe",
                "certificate_type": "paper",
                "paper_certificate": "GK-TEST-001",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_owner_can_register(self):
        """Owner of the breeding herd can register."""
        self._login(username="owner", password="pass")
        response = self.client.post(
            "/api/v2/individual",
            json={
                "breeding_id": self.test_breeding.id,
                "sex": "female",
                "color": "bleighe",
                "certificate_type": "paper",
                "paper_number": "G1-2511",
                "paper_certificate": "GK-TEST-001",
                "litter_size6w": 5,
            },
        )
        self.assertEqual(response.status_code, 201)

    def test_duplicate_paper_certificate_returns_409(self):
        """Reusing an existing paper certificate number returns 409, not 500."""
        self._login()
        first = self.client.post(
            "/api/v2/individual",
            json={
                "breeding_id": self.test_breeding.id,
                "certificate_type": "paper",
                "paper_certificate": "GK-DUP-001",
                "paper_number": "G1-2511",
                "litter_size6w": 5,
            },
        )
        self.assertEqual(first.status_code, 201)
        dup = self.client.post(
            "/api/v2/individual",
            json={
                "breeding_id": self.test_breeding.id,
                "certificate_type": "paper",
                "paper_certificate": "GK-DUP-001",
                "paper_number": "G1-2512",
            },
        )
        # The certificate is on a rabbit of the same litter: the same rabbit registered twice.
        self.assertEqual(dup.status_code, 409)
        self.assertEqual(dup.get_json()["title"], "number_conflict")
        self.assertEqual([c["kind"] for c in dup.get_json()["conflicts"]], ["duplicate_rabbit"])

    def test_register_too_young_returns_422(self):
        """Direct registration is blocked before the 42-day minimum age."""
        young = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date.today() - timedelta(days=10),
            litter_number=2,
            litter_size=3,
            mother=self.parents[0],
            father=self.parents[1],
        )
        self._login()
        response = self.client.post(
            "/api/v2/individual",
            json={
                "breeding_id": young.id,
                "color": "bleighe",
                "certificate_type": "paper",
                "paper_certificate": "GK-TEST-001",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["title"], "too_young")

    def test_non_integer_breeding_id_returns_400(self):
        """A non-numeric breeding_id returns 400."""
        self._login()
        response = self.client.post(
            "/api/v2/individual",
            json={"breeding_id": "abc", "certificate_type": "paper", "paper_certificate": "GK-TEST-001"},
        )
        self.assertEqual(response.status_code, 400)

    def test_oversized_name_returns_400(self):
        """A name longer than 50 characters returns 400."""
        self._login()
        response = self.client.post(
            "/api/v2/individual",
            json={
                "breeding_id": self.test_breeding.id,
                "name": "x" * 51,
                "certificate_type": "paper",
                "paper_certificate": "GK-TEST-001",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_oversized_paper_certificate_returns_400(self):
        """A paper_certificate longer than 20 characters returns 400."""
        self._login()
        response = self.client.post(
            "/api/v2/individual",
            json={
                "breeding_id": self.test_breeding.id,
                "certificate_type": "paper",
                "paper_certificate": "x" * 21,
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_certificate_needs_the_roster_in_sync(self):
        """A certificate is refused while more roster kits are alive than litter_size6w, as on promote."""
        db.Breeding.update(litter_size6w=2).where(db.Breeding.id == self.test_breeding.id).execute()
        for slot in range(1, 5):
            db.Bunny.create(breeding=self.test_breeding, slot_order=slot)
        self._login()
        response = self.client.post(
            "/api/v2/individual",
            json={
                "breeding_id": self.test_breeding.id,
                "sex": "female",
                "color": "bleighe",
                "certificate_type": "paper",
                "paper_number": "G1-2511",
                "paper_certificate": "GK-SYNC-001",
            },
        )
        problem = response.get_json()
        self.assertEqual(
            (response.status_code, problem.get("detail"), problem.get("must_mark_dead")),
            (400, "roster_alive_exceeds_6w", 2),
            "4 kits alive in the roster but litter_size6w=2, and the certificate was not refused",
        )
        self.assertFalse(db.Individual.select().where(db.Individual.breeding == self.test_breeding).exists())

    def test_certificate_quota_applies_from_the_first_registration_day(self):
        """Registration opens at age 42 days, and the quota must apply that day too. A litter
        without roster rows (2 positions, litter_size6w=1) took two paper certificates on day 42."""
        self._login()
        outcomes = {}
        for litter_number, days in ((2, 41), (3, 42), (4, 43)):
            litter = db.Breeding.create(
                breeding_herd_id=self.herds[0],
                birth_date=date.today() - timedelta(days=days),
                litter_number=litter_number,
                litter_size=2,
                litter_size6w=1,
            )  # no mother: three litters of one doe a day apart would be duplicate_litter conflicts
            outcomes[days] = []
            for n in (1, 2):
                response = self.client.post(
                    "/api/v2/individual",
                    json={
                        "breeding_id": litter.id,
                        "sex": "female",
                        "color": "bleighe",
                        "certificate_type": "paper",
                        "paper_certificate": f"GK-6W-{days}-{n}",
                        "paper_number": f"G1-{litter.birth_date:%y}{litter_number}{n}",
                    },
                )
                outcomes[days].append((response.status_code, response.get_json().get("detail")))
        too_young = (422, "Individual must be at least 42 days old to register")
        self.assertEqual(
            outcomes,
            {
                41: [too_young, too_young],
                42: [(201, None), (400, "certificate_quota_exceeded")],
                43: [(201, None), (400, "certificate_quota_exceeded")],
            },
        )

    def test_registration_is_decided_on_the_locked_litter(self):
        """Final review (24a65b0): the herd was authorized before the litter lock. An admin moving the litter
        to M3 meanwhile let a G1 owner set M3's litter_size6w and add a G1-born rabbit to M3's litter."""
        import blueprints.individual_v2_create as create

        real, moved = create._can_register_in_herd, []

        def authorized_then_moved(user, herd):
            allowed = real(user, herd)
            if not moved:  # an admin's move commits after the request's authorization, before its lock
                moved.append(True)
                db.Breeding.update(breeding_herd_id=self.herds[2]).where(
                    db.Breeding.id == self.test_breeding.id
                ).execute()
            return allowed

        self._login("owner")  # owner of G1, the litter's herd when the request starts
        with mock.patch.object(create, "_can_register_in_herd", side_effect=authorized_then_moved):
            response = self.client.post(
                "/api/v2/individual",
                json={
                    "breeding_id": self.test_breeding.id,
                    "sex": "female",
                    "color": "bleighe",
                    "certificate_type": "paper",
                    "paper_number": "G1-2511",
                    "paper_certificate": "GK-TEST-001",
                    "litter_size6w": 4,
                },
            )
        litter = db.Breeding.get_by_id(self.test_breeding.id)
        kits = db.Individual.select().where(db.Individual.breeding == litter).count()
        self.assertEqual(
            (response.status_code, litter.breeding_herd_id.herd, litter.litter_size6w, kits), (403, "M3", None, 0)
        )

    def test_registration_requires_a_certificate(self):
        """Decision 2026-10-30: no registration without a certificate; nothing is written."""
        self._login()
        body = {"breeding_id": self.test_breeding.id, "sex": "female", "color": "bleighe", "litter_size6w": 5}
        required = "Intyg krävs: välj pappersintyg eller digitalt intyg."
        for extra, detail in (
            ({}, required),
            ({"certificate_type": "none"}, required),
            ({"certificate_type": "paper"}, "Intygsnummer krävs för pappersintyg."),
        ):
            with self.subTest(extra=extra):
                response = self.client.post("/api/v2/individual", json={**body, **extra})
                self.assertEqual((response.status_code, response.get_json()["detail"]), (400, detail))
        self.assertFalse(db.Individual.select().where(db.Individual.breeding == self.test_breeding).exists())
        self.assertIsNone(db.Breeding.get_by_id(self.test_breeding.id).litter_size6w)

    def test_digital_certificate_is_issued_after_the_registration(self):
        """Digital is issued after the commit, as promote does; its outcome is in the response."""
        self._login()
        failed = {"type": "about:blank", "title": "certificate_issuance_failed", "status": 503, "detail": "nere"}
        for outcome, certificate, error in ((("100500", None), "100500", None), ((None, failed), None, failed)):
            with self.subTest(certificate=certificate):
                with mock.patch(
                    "blueprints.individual_v2_create._apply_certificate", return_value=outcome
                ) as apply_certificate:
                    response = self.client.post(
                        "/api/v2/individual",
                        json={
                            "breeding_id": self.test_breeding.id,
                            "sex": "female",
                            "color": "bleighe",
                            "certificate_type": "digital",
                            "litter_size6w": 5,
                        },
                    )
                self.assertEqual(response.status_code, 201)
                data = response.get_json()
                self.assertEqual((data["certificate"], data["certificate_error"]), (certificate, error))
                registered, certificate_type, _user_id = apply_certificate.call_args.args
                self.assertEqual((registered.number, certificate_type), (data["individual"]["number"], "digital"))


class TestImportIndividualV2(DatabaseTest):
    """Tests for POST /api/v2/individual/import (utan-kull / no-litter-context path).

    An Individual created without a litter must still have a non-null Breeding
    so that Individual.as_dict() (which dereferences self.breeding.birth_date at
    database.py ~L771) and cert issuance do not crash.
    """

    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        self.client = APP.test_client(use_cookies=True)
        super().setUp()

    def _login(self, username="admin", password="pass"):  # nosemgrep: hardcoded-password-default-argument
        return self.client.post(
            "/api/login",
            json={"username": username, "password": password},
        )

    def test_import_creates_individual_with_minimal_breeding(self):
        """POST /api/v2/individual/import → 201; Individual has non-null breeding;
        Individual.as_dict() does not raise."""
        self._login()
        response = self.client.post(
            IMPORT_URL,
            json={
                "herd": "G1",
                "birth_date": "2030-01-15",
                "sex": "female",
                "color": "bleighe",
                "name": "ImportKanin",
            },
        )
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertIn("individual", data)
        ind = data["individual"]
        # Number was minted from the minimal breeding
        self.assertIsNotNone(ind.get("number"))
        # birth_date in response comes from Individual.as_dict() → self.breeding.birth_date
        # If breeding were null this would have crashed on the server side
        self.assertEqual(ind.get("birth_date"), "2030-01-15")
        # Verify in DB: the Individual's breeding_id must be non-null
        db_ind = db.Individual.get(db.Individual.number == ind["number"])
        self.assertIsNotNone(db_ind.breeding_id)
        # Call as_dict() directly — must not raise
        as_d = db_ind.as_dict()
        self.assertEqual(as_d["birth_date"], "2030-01-15")

    def test_import_requires_herd(self):
        """Missing herd returns 400."""
        self._login()
        response = self.client.post(IMPORT_URL, json={"birth_date": "2030-01-15"})
        self.assertEqual(response.status_code, 400)

    def test_import_requires_birth_date(self):
        """Missing birth_date returns 400."""
        self._login()
        response = self.client.post(IMPORT_URL, json={"herd": "G1"})
        self.assertEqual(response.status_code, 400)

    def test_import_unknown_herd_returns_404(self):
        """Non-existent herd returns 404."""
        self._login()
        response = self.client.post(IMPORT_URL, json={"herd": "ZZZZ", "birth_date": "2030-01-15"})
        self.assertEqual(response.status_code, 404)

    def test_import_requires_authentication(self):
        """Unauthenticated request returns 401."""
        response = self.client.post(IMPORT_URL, json={"herd": "G1", "birth_date": "2030-01-15"})
        self.assertEqual(response.status_code, 401)

    def test_import_viewer_denied(self):
        """Viewer cannot import individuals."""
        self._login(username="spec", password="pass")
        response = self.client.post(IMPORT_URL, json={"herd": "G1", "birth_date": "2030-01-15"})
        self.assertEqual(response.status_code, 403)

    def test_import_owner_can_register(self):
        """Owner of the herd can import."""
        self._login(username="owner", password="pass")
        response = self.client.post(
            IMPORT_URL,
            json={
                "herd": "G1",
                "birth_date": "2030-02-01",
                "sex": "male",
            },
        )
        self.assertEqual(response.status_code, 201)

    def test_import_with_provided_number(self):
        """Supplying an explicit number stores it verbatim on the Individual."""
        self._login()
        response = self.client.post(
            IMPORT_URL,
            json={
                "herd": "G1",
                "birth_date": "2025-05-10",
                "number": "G1-2531",
                "sex": "male",
            },
        )
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertEqual(data["individual"]["number"], "G1-2531")
        # Breeding must still be non-null, and is the litter the number names
        db_ind = db.Individual.get(db.Individual.number == "G1-2531")
        self.assertEqual(db_ind.breeding.litter_number, 3)

    def test_import_duplicate_provided_number_returns_409(self):
        """A provided number that already exists → 409 (not an uncaught 500)."""
        self._login()
        first = self.client.post(
            IMPORT_URL,
            json={"herd": "G1", "birth_date": "2025-05-10", "number": "G1-2532"},
        )
        self.assertEqual(first.status_code, 201)
        dup = self.client.post(
            IMPORT_URL,
            json={"herd": "G1", "birth_date": "2025-06-11", "number": "G1-2532"},
        )
        self.assertEqual(dup.status_code, 409)

    def test_import_foreign_namespace_number_returns_422(self):
        """A provided number must lie in the authorized herd's namespace."""
        self._login()
        response = self.client.post(
            IMPORT_URL,
            json={"herd": "G1", "birth_date": "2025-05-10", "number": "G2-2911"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["title"], "Unprocessable Entity")

    def test_import_malformed_number_returns_422(self):
        """A number that is not {herd}-<digits> returns 422."""
        self._login()
        response = self.client.post(
            IMPORT_URL,
            json={"herd": "G1", "birth_date": "2025-05-10", "number": "G1-HIST-001"},
        )
        self.assertEqual(response.status_code, 422)

    def test_import_non_string_herd_returns_400(self):
        """A non-string herd returns 400."""
        self._login()
        response = self.client.post(IMPORT_URL, json={"herd": 123, "birth_date": "2025-05-10"})
        self.assertEqual(response.status_code, 400)

    def test_import_non_string_number_returns_400(self):
        """A non-string number returns 400."""
        self._login()
        response = self.client.post(
            IMPORT_URL,
            json={"herd": "G1", "birth_date": "2025-05-10", "number": 12345},
        )
        self.assertEqual(response.status_code, 400)
