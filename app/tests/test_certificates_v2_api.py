"""
Tests for v2 certificate API endpoints (Blueprint).

Note: All tests that issue certificates use mock_aws() from moto for S3,
and require app/certs/key.pem + app/certs/ca.pem in the test container.
"""

import os
import unittest
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import patch

import blueprints.certificates as certificates
import utils.database as db
import utils.settings as settings
from moto import mock_aws
from utils.cert_service_v2 import ATTESTER_NAME_MISSING

from tests.database_test import _USE_POSTGRES
from tests.ht_helpers import ht_row
from tests.test_endpoints import FlaskTest


class CertV2Mixin:
    """Mixin that patches S3 endpoint for moto compatibility and starts mock_aws.

    Certificate tests run da.update_individual through the full Flask request
    pipeline. If a request handler raises an unhandled exception, psycopg2
    may leave the connection in 'aborted transaction' state. All subsequent
    SQL on that connection then fails with "current transaction is aborted".
    We guard against this by issuing ROLLBACK in tearDown.
    """

    def setUp(self):
        # Guard: ensure DB connection is not in aborted-transaction state
        # before parent setUp tries to truncate tables.
        import utils.database as db

        if db.DATABASE and not db.DATABASE.is_closed():
            try:
                db.DATABASE.connection().rollback()
            except Exception:
                pass
        super().setUp()
        # The issuing user attests in her own name, so she needs one .
        db.User.update(fullname="Test Namn").where(db.User.id == self.owner.id).execute()
        # Patch S3 endpoint to None so moto intercepts boto3 calls
        self._s3_endpoint_patcher = patch.object(settings.s3, "endpoint", None)
        self._s3_endpoint_patcher.start()

    def tearDown(self):
        self._s3_endpoint_patcher.stop()
        # Ensure clean DB connection state after certificate operations
        import utils.database as db

        if db.DATABASE and not db.DATABASE.is_closed():
            try:
                db.DATABASE.connection().rollback()
            except Exception:
                pass
        super().tearDown()

    def _request(self, user, method, url, body=None):
        with self.app as context:
            context.get("/api/logout")  # a login while logged in keeps the previous user's session
            login = context.post("/api/login", json={"username": user.email, "password": "pass"})
            self.assertEqual(login.status_code, 200, user.email)
            return getattr(context, method)(url, json=body or {})

    def _start_mock_aws(self):
        """Start mock_aws and register cleanup."""
        mock = mock_aws()
        mock.start()
        self.addCleanup(mock.stop)


class TestCertificateV2Issue(CertV2Mixin, FlaskTest):
    """Tests for POST /api/v2/certificates/issue/<number>."""

    def test_issue_without_auth_returns_401(self):
        """Unauthenticated request returns 401."""
        individual = self.individuals[3].number
        response = self.app.post(f"/api/v2/certificates/issue/{individual}")
        self.assertEqual(response.status_code, 401)

    def test_issue_returns_201(self):
        """Authenticated breeder can issue a certificate."""
        self._start_mock_aws()
        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            response = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={
                    "color_id": 1,
                    "litter_size": 5,
                    "litter_size6w": 4,
                },
            )
            self.assertEqual(response.status_code, 201)
            data = response.get_json()
            self.assertIn("verification_token", data)
            self.assertIn("digital_certificate", data)
            self.assertEqual(data["certificate_type"], "pedigree")

    def test_issue_duplicate_returns_400(self):
        """Cannot issue certificate twice for same individual."""
        self._start_mock_aws()
        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            # First issue
            context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
            )
            # Second issue — should fail
            response = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
            )
            self.assertEqual(response.status_code, 400)

    def test_issue_cert_data_includes_pedigree(self):
        """Rendered certificate data keeps parents and color after update_individual.

        update_individual mutates the form dict in place (parents become Peewee
        objects) — the blueprint must refetch before rendering, or the PDF
        silently loses its pedigree.
        """
        self._start_mock_aws()
        individual = self.individuals[3]
        import utils.cert_service_v2 as cert_service

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            with patch.object(
                cert_service._generator,
                "generate_pedigree",
                wraps=cert_service._generator.generate_pedigree,
            ) as spy:
                response = context.post(
                    f"/api/v2/certificates/issue/{individual.number}",
                    json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
                )
            self.assertEqual(response.status_code, 201)
            cert_data = spy.call_args.args[0]
            # breeding[0]: father=G2-1711, mother=G1-1911
            self.assertEqual(cert_data.get("F_number"), "G2-1711")
            self.assertEqual(cert_data.get("M_number"), "G1-1911")
            self.assertIsInstance(cert_data.get("color"), str)

    def test_demo_instance_stamps_watermark_into_cert_data(self):
        """On a demo instance the rendered cert data carries demo_watermark=True.

        The template renders the red "DEMO – EJ GILTIGT INTYG" overlay from this
        flag; default (production) instances leave it False.
        """
        self._start_mock_aws()
        individual = self.individuals[3]
        import utils.cert_service_v2 as cert_service

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            with (
                patch.object(cert_service.cert_settings, "demo_watermark", True),
                patch.object(
                    cert_service._generator,
                    "generate_pedigree",
                    wraps=cert_service._generator.generate_pedigree,
                ) as spy,
            ):
                response = context.post(
                    f"/api/v2/certificates/issue/{individual.number}",
                    json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
                )
            self.assertEqual(response.status_code, 201)
            self.assertTrue(spy.call_args.args[0]["demo_watermark"])

    def test_production_instance_leaves_watermark_off(self):
        """Default (non-demo) instance renders cert data with demo_watermark=False."""
        self._start_mock_aws()
        individual = self.individuals[3]
        import utils.cert_service_v2 as cert_service

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            with patch.object(
                cert_service._generator,
                "generate_pedigree",
                wraps=cert_service._generator.generate_pedigree,
            ) as spy:
                response = context.post(
                    f"/api/v2/certificates/issue/{individual.number}",
                    json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
                )
            self.assertEqual(response.status_code, 201)
            self.assertFalse(spy.call_args.args[0]["demo_watermark"])

    def test_a_failed_disk_write_leaves_no_certificate(self):
        """Issuing writes the PDF to the data volume only (stamboken-drift #69, step A): if that fails, the
        transaction rolls back and nothing can be downloaded."""
        self._start_mock_aws()
        import utils.database as db

        individual = self.individuals[3]
        with self.app as context:
            context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
            with patch("utils.cert_service_v2.open", side_effect=OSError("disk full"), create=True):
                try:
                    response = context.post(
                        f"/api/v2/certificates/issue/{individual.number}",
                        json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
                    )
                    self.assertGreaterEqual(response.status_code, 500)
                except OSError:
                    pass  # TESTING=True propagates unhandled exceptions to the client
            count = db.DigitalCertificateV2.select().where(db.DigitalCertificateV2.individual == individual).count()
            self.assertEqual(count, 0)
            self.assertIsNone(db.Individual.get(db.Individual.id == individual.id).digital_certificate)
            response = context.get(f"/api/v2/certificates/{individual.number}")
            self.assertEqual(response.status_code, 404)

    def test_issue_paper_cert_returns_400(self):
        """Cannot issue when a paper certificate exists — convert via PATCH."""
        individual = self.individuals[0]  # certificate="12"

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            response = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={},
            )
            self.assertEqual(response.status_code, 400)

    def test_only_one_current_certificate_per_individual(self):
        """Partial unique index rejects a second is_current row."""
        import peewee
        import utils.database as db

        individual = self.individuals[3]
        db.DigitalCertificateV2.create(
            individual=individual,
            issued_by=self.admin,
            file_path="certifikat/v2/test-a.pdf",
            checksum="0" * 64,
            is_current=True,
        )
        with self.assertRaises(peewee.IntegrityError):
            db.DigitalCertificateV2.create(
                individual=individual,
                issued_by=self.admin,
                file_path="certifikat/v2/test-b.pdf",
                checksum="1" * 64,
                is_current=True,
            )

    def test_admin_and_manager_cannot_issue_or_update(self):
        """Only people with access to the origin herd attest; admin and the genebank manager get 403."""
        self._start_mock_aws()
        individual = self.individuals[3]
        db.User.update(fullname="Test Namn").where(db.User.id == self.manager.id).execute()

        for user in (self.admin, self.manager):
            with self.subTest(user=user.email):
                response = self._request(user, "post", f"/api/v2/certificates/issue/{individual.number}")
                self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
                response = self._request(user, "patch", f"/api/v2/certificates/update/{individual.number}")
                self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
        self.assertIsNone(db.Individual.get_by_id(individual.id).digital_certificate)

    def test_issue_without_a_name_returns_400(self):
        """The issuer stands on the certificate in her own name: no fullname, no issue or update."""
        self._start_mock_aws()
        individual = self.individuals[3]
        db.User.update(fullname=None).where(db.User.id == self.owner.id).execute()

        for method, route in (("post", "issue"), ("patch", "update")):
            with self.subTest(route=route):
                response = self._request(self.owner, method, f"/api/v2/certificates/{route}/{individual.number}")
                self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
                self.assertEqual(response.get_json()["detail"], ATTESTER_NAME_MISSING)
        self.assertIsNone(db.Individual.get_by_id(individual.id).digital_certificate)

    def test_signing_guard_returns_503(self):
        """Signing failure returns 503 Service Unavailable."""
        self._start_mock_aws()
        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            from utils.certificates_v2 import SigningUnavailableError

            with patch("utils.cert_service_v2.sign_pdf", side_effect=SigningUnavailableError("no creds")):
                response = context.post(
                    f"/api/v2/certificates/issue/{individual.number}",
                    json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
                )
                self.assertEqual(response.status_code, 503)

            # The whole issue flow is one transaction — the individual must
            # not be left marked as certified without a certificate row.
            import utils.database as db

            refreshed = db.Individual.get(db.Individual.id == individual.id)
            self.assertIsNone(refreshed.digital_certificate)

    def test_refused_litter_update_signs_nothing(self):
        """update_breeding's refusal aborts the issue before anything is signed or stored."""
        import utils.database as db
        from utils.certificates_v2 import SigningUnavailableError

        individual = self.individuals[3]
        # Raising keeps the base behaviour observable: reaching generate_and_store would answer 503.
        with patch("blueprints.certificates.generate_and_store", side_effect=SigningUnavailableError) as generate:
            with self.app as context:
                context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
                response = context.post(
                    f"/api/v2/certificates/issue/{individual.number}",
                    json={"color_id": 1, "litter_size": 0, "litter_size6w": 0},
                )
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(response.get_json()["detail"], "Litter size must be larger than zero.")
        generate.assert_not_called()
        self.assertIsNone(db.Individual.get_by_id(individual.id).digital_certificate)
        self.assertEqual(db.Breeding.get_by_id(individual.breeding_id).litter_size, 2)

    def test_issue_ignores_fields_outside_the_certificate_form(self):
        """A new origin herd in the body is not a certificate field (litter moves:
        test_pedigree_guard; a sale takes the transfer rules: test_caretaker_cannot_sell_via_certificate_issue)."""
        import utils.database as db

        self._start_mock_aws()
        individual = self.individuals[3]  # G1-2112, born and held in G1
        body = {"color_id": 1, "origin_herd": {"herd": "G2"}}
        with self.app as context:
            context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
            response = context.post(f"/api/v2/certificates/issue/{individual.number}", json=body)
        stored = db.Individual.get_by_id(individual.id)
        self.assertEqual((stored.origin_herd.herd, stored.current_herd.herd), ("G1", "G1"), "the issue moved it")
        self.assertEqual(response.status_code, 201, response.get_json())

    def _full_roster_litter(self):
        """A roster litter past 6 weeks with litter_size6w=1, already used by a certified kit."""
        from datetime import date

        import utils.database as db

        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2025, 1, 10),
            litter_number=1,
            litter_size=3,
            litter_size6w=1,
            mother=self.parents[0],
            father=self.parents[1],
        )
        certified = db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2511", certificate="P1")
        rabbit = db.Individual.create(
            origin_herd=self.herds[0], breeding=litter, number="G1-2512", color=self.colors[0]
        )
        return certified, rabbit

    def test_issue_respects_the_litter_quota(self):
        """The first certificate of a kit in a full litter is refused like POST /v2/individual."""
        import utils.database as db

        self._start_mock_aws()
        _, rabbit = self._full_roster_litter()
        with self.app as context:
            context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
            response = context.post(f"/api/v2/certificates/issue/{rabbit.number}", json={"color_id": 1})
        self.assertIsNone(
            db.Individual.get_by_id(rabbit.id).digital_certificate,
            f"issue returned {response.status_code}: litter_size6w=1 but a second kit got a certificate",
        )
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(response.get_json()["detail"], "certificate_quota_exceeded")

    def test_issue_requires_litter_size6w_and_a_roster_in_sync(self):
        """A first certificate needs litter_size6w, and no more kits alive in the roster than it says."""
        from datetime import date, datetime

        import utils.database as db

        self._start_mock_aws()
        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2025, 1, 10),
            litter_number=1,
            litter_size=3,
            mother=self.parents[0],
            father=self.parents[1],
        )
        rabbit = db.Individual.create(
            origin_herd=self.herds[0], breeding=litter, number="G1-2511", color=self.colors[0]
        )
        with self.app as context:
            context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
            missing = context.post(f"/api/v2/certificates/issue/{rabbit.number}", json={"color_id": 1})
        self.assertIsNone(
            db.Individual.get_by_id(rabbit.id).digital_certificate,
            f"issue returned {missing.status_code}: a certificate in a litter without litter_size6w",
        )
        self.assertEqual((missing.status_code, missing.get_json().get("detail")), (400, "litter_size6w_required"))

        # 3 kits alive in the roster (the rabbit itself is registered), 2 alive at 6 weeks.
        db.Breeding.update(litter_size6w=2).where(db.Breeding.id == litter.id).execute()
        db.Bunny.create(breeding=litter, slot_order=1, fate="registered", individual=rabbit)
        db.Bunny.create(breeding=litter, slot_order=2)
        db.Bunny.create(breeding=litter, slot_order=3)
        # The owner with edit rights (rabbit still in G1) first, then as the breeder after a sale (no edit rights).
        responses = {}
        with self.app as context:
            context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
            responses["editor"] = context.post(f"/api/v2/certificates/issue/{rabbit.number}", json={"color_id": 1})
        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[1],
            signature=self.manager,
            individual=rabbit,
            herd_tracking_date=datetime.now(),
        )
        with self.app as context:
            context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
            responses["breeder"] = context.post(f"/api/v2/certificates/issue/{rabbit.number}", json={})
        self.assertIsNone(
            db.Individual.get_by_id(rabbit.id).digital_certificate,
            "3 kits alive in the roster but litter_size6w=2, and a certificate was issued",
        )
        for path, response in responses.items():
            with self.subTest(path):
                problem = response.get_json()
                self.assertEqual(
                    (response.status_code, problem.get("detail"), problem.get("must_mark_dead")),
                    (400, "roster_alive_exceeds_6w", 1),
                )

    def test_reissue_and_conversion_in_a_full_litter_take_no_new_slot(self):
        """The quota counts first certificates only; an updated certificate is already counted."""
        self._start_mock_aws()
        paper, _ = self._full_roster_litter()  # G1-2511: paper certificate, the litter's only slot
        with self.app as context:
            context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
            converted = context.patch(f"/api/v2/certificates/update/{paper.number}", json={})
            reissued = context.patch(f"/api/v2/certificates/update/{paper.number}", json={"name": "Ny"})
        self.assertEqual((converted.status_code, reissued.status_code), (200, 200), converted.get_json())


class TestCertificateV2Update(CertV2Mixin, FlaskTest):
    """Tests for PATCH /api/v2/certificates/update/<number>."""

    def test_update_v1_to_v2(self):
        """Update existing v1 cert creates v2 row, overwrites S3."""
        self._start_mock_aws()
        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            # First issue to get a v1 cert
            context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
            )
            # Update (v1→v2 upgrade)
            response = context.patch(
                f"/api/v2/certificates/update/{individual.number}",
                json={"color_id": 1, "litter_size": 6, "litter_size6w": 5},
            )
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("verification_token", data)

    def test_update_converts_paper_to_digital(self):
        """PATCH on a paper-certificate individual assigns a digital number."""
        self._start_mock_aws()
        import utils.database as db

        individual = self.individuals[0]  # certificate="12", no digital

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            response = context.patch(
                f"/api/v2/certificates/update/{individual.number}",
                json={},
            )
            self.assertEqual(response.status_code, 200)
            refreshed = db.Individual.get(db.Individual.id == individual.id)
            self.assertIsNotNone(refreshed.digital_certificate)
            self.assertIsNone(refreshed.certificate)

    def test_owner_converts_paper_to_digital(self):
        """The breeder (no manager rights) still gets a number: issue_digital is the route's own argument."""
        self._start_mock_aws()
        import utils.database as db

        individual = self.individuals[0]  # certificate="12", owner's herd G1
        with self.app as context:
            context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
            response = context.patch(f"/api/v2/certificates/update/{individual.number}", json={"litter_size": 2})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        refreshed = db.Individual.get_by_id(individual.id)
        self.assertEqual((refreshed.certificate, refreshed.digital_certificate), (None, 100000))
        self.assertEqual(response.get_json()["digital_certificate"], 100000)

    def test_body_cannot_point_issuance_at_another_rabbit(self):
        """Issuance is pinned to the URL rabbit; a body id/number cannot hand a number to another one.

        B (bred in G2, now in G1) is editable by the owner, who may not issue for it.
        """
        self._start_mock_aws()
        from datetime import datetime

        import utils.database as db

        other = db.Individual.create(origin_herd=self.herds[1], breeding=self.breeding[2], number="G2-2012")
        ht_row("BIRTH", herd=self.herds[1], individual=other, herd_tracking_date=datetime(2020, 2, 1))
        ht_row(
            "TRANSFER",
            from_herd=self.herds[1],
            herd=self.herds[0],
            individual=other,
            herd_tracking_date=datetime(2020, 6, 1),
        )
        body = {
            "id": other.id,
            "number": other.number,
            "breeding": self.breeding[2].id,
            "origin_herd": {"herd": "G2"},
            "herd": "G1",
        }
        with self.app as context:
            context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
            # issue: uncertified G1-2112; update: paper→digital conversion of G1-2111
            context.post(f"/api/v2/certificates/issue/{self.individuals[3].number}", json=body)
            self.assertIsNone(db.Individual.get_by_id(other.id).digital_certificate)
            context.patch(f"/api/v2/certificates/update/{self.individuals[0].number}", json=body)
            self.assertIsNone(db.Individual.get_by_id(other.id).digital_certificate)

    def test_update_sets_old_not_current(self):
        """Reissue sets old v2 row is_current=False."""
        self._start_mock_aws()
        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            # Issue
            issue_resp = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
            )
            old_token = issue_resp.get_json()["verification_token"]

            # Update
            context.patch(
                f"/api/v2/certificates/update/{individual.number}",
                json={"color_id": 1, "litter_size": 6, "litter_size6w": 5},
            )

            # Old cert should no longer be current
            from utils.database import DigitalCertificateV2

            old_cert = (
                DigitalCertificateV2.select().where(DigitalCertificateV2.verification_token == old_token).dicts().get()
            )
            self.assertFalse(old_cert["is_current"])

    def test_verify_superseded_reports_replacement(self):
        """Public verify of an old token flags is_current=False + newest date."""
        self._start_mock_aws()
        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            issue_resp = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
            )
            old_token = issue_resp.get_json()["verification_token"]

            update_resp = context.patch(
                f"/api/v2/certificates/update/{individual.number}",
                json={"color_id": 1, "litter_size": 6, "litter_size6w": 5},
            )
            new_issued_at = update_resp.get_json()["issued_at"]

            new_token = update_resp.get_json()["verification_token"]

        # The issuing person shows her name and the rabbit is sold (stamboken #6)
        db.User.update(fullname="Ada Uppfödare", name_on_check_page=True).where(db.User.id == self.owner.id).execute()
        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[1],
            signature=self.manager,
            individual=individual,
            herd_tracking_date=date(2026, 3, 15),
        )
        current = self.app.get(f"/api/v2/certificates/verify/{new_token}").get_json()
        self.assertEqual((current["attested_by"], current["transferred"]), ("Ada Uppfödare", ["2026-03"]))

        # Public endpoint — no auth
        response = self.app.get(f"/api/v2/certificates/verify/{old_token}")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["verified"])
        self.assertFalse(data["is_current"])
        self.assertEqual(data["replaced_by_date"], new_issued_at)
        # An old QR code tells neither the name nor later sales
        self.assertEqual(data["attested_by"], "Uppfödaren")  # the role, not the name; the breeder issued it (#141)
        self.assertEqual(data["transferred"], [])


class TestCertificateV2Download(CertV2Mixin, FlaskTest):
    """Tests for GET /api/v2/certificates/<number>."""

    def test_download_returns_pdf(self):
        """Download returns PDF content-type."""
        self._start_mock_aws()
        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            # Issue first
            context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
            )
            # Download
            response = context.get(f"/api/v2/certificates/{individual.number}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content_type, "application/pdf")

    def test_download_falls_back_to_s3_when_disk_file_missing(self):
        """Download serves the token-named S3 copy when the disk file is gone: a certificate issued before step A of
        stamboken-drift #69, when v2 still uploaded one. The S3 reads go in step C."""
        self._start_mock_aws()
        import os

        import utils.database as db

        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
            )
            cert = (
                db.DigitalCertificateV2.select()
                .where(
                    (db.DigitalCertificateV2.individual == individual) & (db.DigitalCertificateV2.is_current == True)  # noqa: E712
                )
                .get()
            )
            from utils.cert_acess import upload_certificate_v2

            with open(os.path.join("uppladdningar", cert.file_path), "rb") as stored:
                upload_certificate_v2(pdf_bytes=stored.read(), token=cert.verification_token)
            os.remove(os.path.join("uppladdningar", cert.file_path))

            response = context.get(f"/api/v2/certificates/{individual.number}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content_type, "application/pdf")
            self.assertTrue(response.data.startswith(b"%PDF"))

    def test_download_404_when_disk_and_s3_missing(self):
        """404 when both the disk file and the token-named S3 object are gone."""
        self._start_mock_aws()
        import os

        import utils.database as db
        import utils.s3 as s3

        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
            )
            cert = (
                db.DigitalCertificateV2.select()
                .where(
                    (db.DigitalCertificateV2.individual == individual) & (db.DigitalCertificateV2.is_current == True)  # noqa: E712
                )
                .get()
            )
            os.remove(os.path.join("uppladdningar", cert.file_path))
            s3.get_s3_client().delete_object(f"certifikat/v2/{cert.verification_token}.pdf")

            response = context.get(f"/api/v2/certificates/{individual.number}")
            self.assertEqual(response.status_code, 404)

    def test_download_fallback_to_s3(self):
        """Download falls back to legacy S3 for a v1-certified individual."""
        self._start_mock_aws()
        import utils.database as db

        individual = self.individuals[3]
        # v1-certified: the digital_certificate number is the marker
        db.Individual.update(digital_certificate=4711).where(db.Individual.id == individual.id).execute()

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            # Upload a fake cert to S3 without creating a v2 row
            from utils.cert_acess import upload_certificate

            upload_certificate(pdf_bytes=b"%PDF-fake-cert", ind_number=individual.number)

            response = context.get(f"/api/v2/certificates/{individual.number}")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.data.startswith(b"%PDF-fake-cert"))

    def test_download_404_for_uncertified_even_with_orphaned_s3_object(self):
        """No v2 row AND no v1 number → 404 even if a legacy S3 object exists.

        Regression for the rolled-back-issuance hazard: generate_and_store
        uploads to S3 before the DB commit, so a failed issuance can orphan
        the legacy-key PDF. The download endpoint must not serve it.
        """
        self._start_mock_aws()
        individual = self.individuals[3]  # digital_certificate is None

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            from utils.cert_acess import upload_certificate

            upload_certificate(pdf_bytes=b"%PDF-orphan", ind_number=individual.number)

            response = context.get(f"/api/v2/certificates/{individual.number}")
            self.assertEqual(response.status_code, 404)


class TestCertificateV2Preview(CertV2Mixin, FlaskTest):
    """Tests for GET /api/v2/certificates/preview/<number>."""

    def test_preview_returns_unsigned_pdf(self):
        """Preview returns PDF content-type (unsigned)."""
        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            response = context.get(f"/api/v2/certificates/preview/{individual.number}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content_type, "application/pdf")

    def _preview_status(self, client, url):
        try:
            return client.get(url).status_code
        except Exception as exc:  # TESTING=True propagates an unhandled error (a 500 in production)
            return f"unhandled {type(exc).__name__}: {exc}"

    def test_preview_renders_with_voided_or_unknown_parent(self):
        """A voided parent (unpromoted doe) or an unknown one (founder/import) prints as unknown, not a 500."""
        mother = self.parents[0]  # G1-1911, mother of G1-2112
        mother.voided = True
        mother.save()
        founder = self.parents[1]  # G2-1711: its litter has no mother or father
        with self.app as context:
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            observed = {
                "v2_kit_of_voided_mother": self._preview_status(
                    context, f"/api/v2/certificates/preview/{self.individuals[3].number}"
                ),
                "v2_founder": self._preview_status(context, f"/api/v2/certificates/preview/{founder.number}"),
                "legacy_founder": self._preview_status(context, f"/api/certificates/preview/{founder.number}"),
            }
        self.assertEqual(observed, {"v2_kit_of_voided_mother": 200, "v2_founder": 200, "legacy_founder": 200})

    def test_founder_can_be_issued_a_certificate(self):
        """Issuance for a rabbit with unknown parents works too in v2 (no 500, no "Invalid parents")."""
        self._start_mock_aws()

        def status(request):
            try:
                return request().status_code
            except Exception as exc:  # TESTING=True propagates an unhandled error (a 500 in production)
                return f"unhandled {type(exc).__name__}: {exc}"

        v2 = self.parents[1]  # G2-1711: a founder, litter without parents
        # add_role saves the stale in-memory user, so the name goes in after it.
        self.owner.add_role("owner", self.herds[1].id)  # origin herd of the founder
        db.User.update(fullname="Test Namn").where(db.User.id == self.owner.id).execute()
        with self.app as context:
            context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
            observed = {
                "v2_issue": status(lambda: context.post(f"/api/v2/certificates/issue/{v2.number}", json={})),
            }
        self.assertEqual(observed, {"v2_issue": 201})


class TestCertificateV2Verify(CertV2Mixin, FlaskTest):
    """Tests for GET/POST /api/v2/certificates/verify/<uuid>."""

    def test_verify_invalid_token_returns_404(self):
        """Invalid UUID returns 404 problem."""
        response = self.app.get("/api/v2/certificates/verify/00000000-0000-0000-0000-000000000000")
        self.assertEqual(response.status_code, 404)

    def test_verify_valid_token(self):
        """Valid token returns certificate metadata."""
        self._start_mock_aws()
        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            issue_resp = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
            )
            token = issue_resp.get_json()["verification_token"]

            verify_resp = context.get(f"/api/v2/certificates/verify/{token}")
            self.assertEqual(verify_resp.status_code, 200)
            data = verify_resp.get_json()
            self.assertTrue(data["verified"])
            self.assertEqual(data["individual_number"], individual.number)
            # No person on the public page: neither the issuing user's name nor an email
            self.assertNotIn("issued_by", data)
            self.assertNotIn("@", str(data))

    def test_verify_attester_and_transfers(self):
        """Stamboken #6: the issuer's name only by her own choice, each change of holder as month and year only."""
        self._start_mock_aws()
        individual = self.individuals[3]  # born in herds[0]
        with self.app as context:
            context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
            token = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
            ).get_json()["verification_token"]

        db.User.update(fullname="Olle Ägare").where(db.User.id == self.owner.id).execute()
        data = self.app.get(f"/api/v2/certificates/verify/{token}").get_json()
        self.assertEqual(data["attested_by"], "Uppfödaren")
        self.assertEqual(data["transferred"], [])

        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[1],
            signature=self.manager,
            individual=individual,
            herd_tracking_date=date(2026, 3, 15),
        )
        ht_row(
            "CORRECTION",
            from_herd=self.herds[1],
            herd=self.herds[0],
            signature=self.manager,
            individual=individual,
            herd_tracking_date=date(2026, 6, 9),
        )
        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[1],
            signature=self.manager,
            individual=individual,
            herd_tracking_date=date(2026, 8, 20),
            voided_at=datetime.now(),
            voided_by_user=self.manager,
            voided_reason="fel kanin",
            voided_operation_id=uuid.uuid4(),
        )
        ht_row(
            "ATTESTATION",
            herd=self.herds[0],
            signature=self.manager,
            individual=individual,
            herd_tracking_date=date(2026, 9, 1),
        )
        ht_row(  # migrated history without a receiving herd, no sale
            "TRANSFER",
            from_herd=self.herds[0],
            herd=None,
            signature=self.admin,
            individual=individual,
            herd_tracking_date=date(2026, 9, 15),
        )
        ht_row(  # an admin's register fix into the other genebank, no sale
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[2],
            signature=self.admin,
            individual=individual,
            herd_tracking_date=date(2026, 10, 1),
        )
        owner = self.app.application.test_client(use_cookies=True)
        login = owner.post("/api/login", json={"username": self.owner.email, "password": "pass"})
        self.assertEqual(login.status_code, 200)
        url = "/api/v2/certificates/check-page-name"
        self.assertEqual(owner.get(url).get_json(), {"show": None})  # a new account has not chosen yet
        self.assertEqual(owner.put(url, json={"show": "true"}).status_code, 400)
        account_audits = db.AuditLog.select().where(db.AuditLog.table_name == "hbuser").count()
        self.assertEqual(owner.put(url, json={"show": True}).get_json(), {"show": True})
        # her choice writes no audit row (it would copy her name and e-mail)
        self.assertEqual(db.AuditLog.select().where(db.AuditLog.table_name == "hbuser").count(), account_audits)

        data = self.app.get(f"/api/v2/certificates/verify/{token}").get_json()
        self.assertEqual(data["attested_by"], "Olle Ägare")
        # the corrected history's changes of holder; no voided row, no move between genebanks
        self.assertEqual(data["transferred"], ["2026-03", "2026-06"])
        self.assertNotIn("Gotlandsherd1", str(data))  # never the herd name
        self.assertNotIn("2026-03-15", str(data))
        with patch.object(settings.service, "demo_instance", True):  # a day-old copy: no name, no sales
            demo = self.app.get(f"/api/v2/certificates/verify/{token}").get_json()
        self.assertEqual((demo["attested_by"], demo["transferred"]), ("Uppfödaren", []))

        self.assertEqual(owner.put(url, json={"show": False}).get_json(), {"show": False})
        self.assertEqual(self.app.get(f"/api/v2/certificates/verify/{token}").get_json()["attested_by"], "Uppfödaren")

    def test_attester_role_without_a_name(self):
        """Without her choice: the role she issued in, stored on the certificate, not her roles at the scan."""
        from utils.cert_service_v2 import issuer_role

        individual = self.individuals[3]  # born in herds[0]
        for user, role in ((self.owner, "breeder"), (self.admin, "admin"), (self.manager, "manager")):
            with self.subTest(user=user.email):
                self.assertEqual(issuer_role(user, individual), role)
        cert = db.DigitalCertificateV2.create(
            individual=individual, issued_by=self.manager, issued_as="manager", file_path="x", checksum="0" * 64
        )
        self.assertEqual(
            certificates._attested_by(cert, may_name=True), "Föreningen Gotlandskaninen (genbanksansvarig)"
        )
        self.manager.remove_role("manager", self.genebanks[0].id)  # she steps down; the certificate keeps its role
        cert = db.DigitalCertificateV2.get_by_id(cert.id)
        self.assertEqual(
            certificates._attested_by(cert, may_name=True), "Föreningen Gotlandskaninen (genbanksansvarig)"
        )
        db.DigitalCertificateV2.update(issued_as=None).where(db.DigitalCertificateV2.id == cert.id).execute()
        cert = db.DigitalCertificateV2.get_by_id(cert.id)
        self.assertEqual(certificates._attested_by(cert, may_name=True), "Uppfödaren")  # an older row, fixed text
        db.User.get_by_id(self.manager.id).add_role("admin", None)  # the issuer becomes admin
        cert = db.DigitalCertificateV2.get_by_id(cert.id)
        self.assertEqual(certificates._attested_by(cert, may_name=True), "Uppfödaren")  # roles today do not matter
        db.User.update(fullname="Maja Ansvarig", name_on_check_page=True, is_active=False).where(
            db.User.id == self.manager.id
        ).execute()
        cert = db.DigitalCertificateV2.get_by_id(cert.id)
        self.assertEqual(certificates._attested_by(cert, may_name=True), "Uppfödaren")  # a deactivated account
        db.User.update(fullname="  ", is_active=True).where(db.User.id == self.manager.id).execute()
        cert = db.DigitalCertificateV2.get_by_id(cert.id)
        self.assertEqual(certificates._attested_by(cert, may_name=True), "Uppfödaren")  # no blank name

    def test_check_page_name_reaches_production_without_production_access(self):
        """She can always read and withdraw her choice, also once her production access is gone."""
        rules = patch.object(settings.service, "access_rules", "enforce")  # as in production
        rules.start()
        self.addCleanup(rules.stop)
        db.User.update(name_on_check_page=True, v2_prod_access=False).where(db.User.id == self.owner.id).execute()
        client = self.app.application.test_client(use_cookies=True)
        self.assertEqual(
            client.post("/api/login", json={"username": self.owner.email, "password": "pass"}).status_code, 200
        )
        self.assertEqual(client.get("/api/v2/certificates/check-page-name").get_json(), {"show": True})
        self.assertEqual(
            client.put("/api/v2/certificates/check-page-name", json={"show": False}).get_json(), {"show": False}
        )
        self.assertFalse(db.User.get_by_id(self.owner.id).name_on_check_page)
        self.assertEqual(client.get("/api/v2/individual/G1-2112").status_code, 403)  # the gate is really on

    def test_sale_months_on_migrated_history(self):
        """Migrated rows lack from_herd: a row without a herd, and a return to the same herd, are no sale."""
        from utils.herd_tracking import sale_months

        individual = self.individuals[3]  # born in herds[0]
        for day, herd in (
            (date(2026, 2, 1), None),
            (date(2026, 3, 1), self.herds[0]),
            (date(2026, 4, 1), self.herds[1]),
        ):
            ht_row("TRANSFER", herd=herd, signature=self.manager, individual=individual, herd_tracking_date=day)
        self.assertEqual(sale_months(individual), ["2026-04"])

    def test_sale_months_counts_a_resale_within_gx1(self):
        """ADR-0016: a resale to a new buyer within GX1 is a sale, also once the buyer is erased (stamboken #6)."""
        from utils.herd_tracking import sale_months

        gx1 = db.Herd.create(genebank=self.genebanks[0], herd="GX1")
        individual = self.individuals[3]  # born in herds[0]
        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=gx1,
            signature=self.manager,
            individual=individual,
            herd_tracking_date=date(2026, 3, 1),
        )
        ht_row(  # the resale; its buyer is erased (buyer_removed)
            "TRANSFER",
            from_herd=gx1,
            herd=gx1,
            signature=self.manager,
            individual=individual,
            herd_tracking_date=date(2026, 4, 1),
            buyer_removed=True,
        )
        ht_row(  # a later row repeating GX1 without any buyer (migrated): no sale
            "TRANSFER",
            herd=gx1,
            signature=self.manager,
            individual=individual,
            herd_tracking_date=date(2026, 5, 1),
        )
        self.assertEqual(sale_months(individual), ["2026-03", "2026-04"])

    def test_sale_months_resale_after_an_earlier_sale_entered_later(self):
        """An earlier sale into GX1 entered afterwards: the later row's stored sender is stale, its buyer is not."""
        from utils.herd_tracking import sale_months

        gx1 = db.Herd.create(genebank=self.genebanks[0], herd="GX1")
        individual = self.individuals[3]  # born in herds[0]
        for day in (date(2026, 4, 1), date(2026, 3, 1)):  # April first, then March by a correction
            ht_row(
                "TRANSFER" if day.month == 4 else "CORRECTION",
                from_herd=self.herds[0],
                herd=gx1,
                signature=self.manager,
                individual=individual,
                herd_tracking_date=day,
                buyer_removed=True,
            )
        self.assertEqual(sale_months(individual), ["2026-03", "2026-04"])

    def test_sale_months_walks_the_holder_past_a_voided_row(self):
        """A later row's stored from_herd can name a voided row's herd: the active history decides."""
        from utils.herd_tracking import sale_months

        m4 = db.Herd.create(genebank=self.genebanks[1], herd="M4")
        individual = self.individuals[3]  # born in herds[0] (G1)
        ht_row(  # G1 -> M3, struck out later
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[2],
            signature=self.admin,
            individual=individual,
            herd_tracking_date=date(2026, 2, 1),
            voided_at=datetime.now(),
            voided_by_user=self.admin,
            voided_reason="fel genbank",
            voided_operation_id=uuid.uuid4(),
        )
        ht_row(  # stored sender M3, but the active history goes G1 -> G2: a change within the genebank
            "CORRECTION",
            from_herd=self.herds[2],
            herd=self.herds[1],
            signature=self.admin,
            individual=individual,
            herd_tracking_date=date(2026, 3, 1),
        )
        ht_row(  # stored sender M3 again, but G2 -> M4 crosses genebanks: no sale
            "TRANSFER",
            from_herd=self.herds[2],
            herd=m4,
            signature=self.admin,
            individual=individual,
            herd_tracking_date=date(2026, 4, 1),
        )
        self.assertEqual(sale_months(individual), ["2026-03"])

    def test_sale_months_follows_the_corrected_history(self):
        """Date fixes, a fix of a fix and a joint fix: the months the corrected history changes holder, once each."""
        from utils.herd_tracking import correct_herd_tracking, record_herd_tracking, sale_months

        gx1 = db.Herd.create(genebank=self.genebanks[0], herd="GX1")
        individual = self.individuals[3]  # born in herds[0]
        sale = record_herd_tracking(individual, self.herds[1], date(2026, 2, 1), "TRANSFER", self.manager)
        second = record_herd_tracking(individual, gx1, date(2026, 3, 1), "TRANSFER", self.manager)
        self.assertEqual(sale_months(individual), ["2026-02", "2026-03"])

        def fix(row, day):
            (written,) = correct_herd_tracking(
                individual,
                self.manager,
                None,
                [row.id],
                [{"kind": "CORRECTION", "date": day, "herd": row.herd.herd}],
                "Fel datum",
            )
            return written

        fixed = fix(second, date(2026, 5, 1))
        fix(fixed, date(2026, 4, 1))  # a fix of the fix
        fix(sale, date(2026, 1, 15))
        self.assertEqual(sale_months(individual), ["2026-01", "2026-04"])

    def test_verify_post_with_pdf(self):
        """POST verify with actual PDF bytes checks checksum + signature."""
        self._start_mock_aws()
        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            issue_resp = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
            )
            token = issue_resp.get_json()["verification_token"]

            # POST with fake PDF bytes (won't match checksum)
            verify_resp = context.post(
                f"/api/v2/certificates/verify/{token}",
                data=b"%PDF-fake-data",
                content_type="application/pdf",
            )
            self.assertEqual(verify_resp.status_code, 200)
            data = verify_resp.get_json()
            # Fake PDF won't match stored checksum
            self.assertFalse(data["checksum_match"])

    def test_verify_post_real_pdf(self):
        """Uploading the actual stored PDF passes checksum + pinned-CA signature."""
        self._start_mock_aws()
        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            issue_resp = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
            )
            token = issue_resp.get_json()["verification_token"]

            download_resp = context.get(f"/api/v2/certificates/{individual.number}")
            self.assertEqual(download_resp.status_code, 200)

            verify_resp = context.post(
                f"/api/v2/certificates/verify/{token}",
                data=download_resp.data,
                content_type="application/pdf",
            )
            self.assertEqual(verify_resp.status_code, 200)
            data = verify_resp.get_json()
            self.assertTrue(data["checksum_match"])
            self.assertTrue(data["signature_valid"])
            self.assertTrue(data["verified"])


class TestCertificateV2Authorization(CertV2Mixin, FlaskTest):
    """Tests for certificate authorization — origin_herd based."""

    def test_origin_herd_owner_can_issue(self):
        """Owner of the rabbit's origin_herd can issue certificate."""
        # The 'owner' user owns herds[0] (herd="G1")
        # individuals[3] has origin_herd=herds[0] (herd="G1")
        self._start_mock_aws()
        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            response = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
            )
            # Owner should succeed (origin_herd check)
            self.assertEqual(response.status_code, 201)

    def test_non_origin_owner_cannot_issue(self):
        """Herd owner who is not the rabbit's breeder (origin_herd) gets 403."""
        # The 'owner' user owns herds[0] (herd="G1")
        # individuals[1] has origin_herd=herds[1] (herd="G2")
        individual = self.individuals[1]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            response = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
            )
            self.assertEqual(response.status_code, 403)

    def test_breeder_can_issue_after_transfer(self):
        """Breeder (origin herd owner) can issue after the rabbit moved herds,
        but cannot edit the individual's data in the same request."""
        self._start_mock_aws()
        from datetime import datetime

        import utils.database as db

        individual = self.individuals[3]  # origin_herd=herds[0], owned by self.owner
        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[1],
            signature=self.manager,
            individual=individual,
            herd_tracking_date=datetime.now(),
        )

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.owner.email, "password": "pass"},
            )
            # Form edits require edit rights on the current herd — rejected.
            response = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 1},
            )
            self.assertEqual(response.status_code, 403)
            # Plain issuance (no edits) is the breeder's right.
            response = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={},
            )
            self.assertEqual(response.status_code, 201)
            refreshed = db.Individual.get(db.Individual.id == individual.id)
            self.assertIsNotNone(refreshed.digital_certificate)

    def test_caretaker_genebank_change_via_certificate_issue_is_refused(self):
        """A herd change in the issue body is a transfer under the sale's rules. A herd-access grant sells as the
        owner (#326), and a move into another genebank is an admin correction, so this caretaker is refused."""
        self._start_mock_aws()
        import utils.data_access as da
        import utils.database as db

        membership = db.Membership.create(member_number=6, membership_status="active")
        db.Herd.update(membership=membership).where(db.Herd.id == self.herds[0].id).execute()
        user = da.register_user("sune@ex.se", "pass", username="sune")
        db.User.update(fullname="Sune S").where(db.User.id == user.id).execute()
        caretaker = db.Member.create(
            membership=membership, first_name="Sune", last_name="S", email="sune@ex.se", role="skotare", user=user
        )
        db.HerdAccessGrant.create(member=caretaker, herd=self.herds[0], granted_by=self.admin)
        number = self.individuals[3].number  # G1-2112: born in G1, uncertified
        body = {"herd": "M3", "selling_date": "2021-06-01", "litter_size": 2, "litter_size6w": 2, "reason": "Fel"}
        with self.app as context:
            context.post("/api/login", json={"username": "sune", "password": "pass"})
            response = context.post(f"/api/v2/certificates/issue/{number}", json=dict(body))
            # the update route (paper→digital conversion of G1-2111) merges the body the same way
            updated = context.patch(f"/api/v2/certificates/update/{self.individuals[0].number}", json=dict(body))
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
        self.assertEqual(updated.status_code, 403, updated.get_data(as_text=True))
        for individual in (self.individuals[3], self.individuals[0]):
            stored = db.Individual.get_by_id(individual.id)
            self.assertEqual((stored.current_herd.herd, stored.digital_certificate), ("G1", None))
        self.assertEqual(db.DigitalCertificateV2.select().count(), 0)

    def test_genebank_change_via_certificate_issue_is_refused_to_everyone(self):
        """A herd change into another genebank is an admin correction, and admin cannot issue: nobody gets it here."""
        self._start_mock_aws()
        import utils.database as db

        individual = self.individuals[3]  # G1-2112: born in G1, uncertified
        body = {"herd": "M3", "selling_date": "2021-06-01", "litter_size": 2, "litter_size6w": 2, "reason": "Fel"}
        for user in (self.owner, self.manager, self.admin):
            with self.subTest(user=user.email):
                response = self._request(user, "post", f"/api/v2/certificates/issue/{individual.number}", dict(body))
                self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
        self.assertEqual(db.DigitalCertificateV2.select().count(), 0)
        self.assertEqual(db.Individual.get_by_id(individual.id).current_herd.herd, "G1")

    def test_a_sale_outside_via_certificate_issue_needs_a_buyer_the_route_cannot_take(self):
        """The certificate form has no buyer fields, so a sale to GX1 through it is refused (ADR-0016)."""
        self._start_mock_aws()
        import utils.database as db

        db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför genbanken")
        individual = self.individuals[3]  # G1-2112: born in G1, uncertified
        body = {"herd": "GX1", "selling_date": "2021-06-01", "litter_size": 2, "litter_size6w": 2}
        with self.app as context:
            context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
            response = context.post(f"/api/v2/certificates/issue/{individual.number}", json=dict(body))
        self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        self.assertIn("köparens namn och ort", response.get_json()["detail"])
        self.assertEqual(db.Individual.get_by_id(individual.id).current_herd.herd, "G1")
        self.assertEqual(db.DigitalCertificateV2.select().count(), 0)

    def test_viewer_cannot_issue(self):
        """User who is not admin/manager/origin-owner gets 403."""
        individual = self.individuals[3]

        with self.app as context:
            # Login as viewer (no owner/manager role)
            context.post(
                "/api/login",
                json={"username": self.viewer.email, "password": "pass"},
            )
            response = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
            )
            self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()


class TestCertificateV2ViewAuthorization(CertV2Mixin, FlaskTest):
    """Download and preview: current owner, breeder, genebank manager, admin."""

    def _status(self, user, url):
        with self.app as context:
            context.get("/api/logout")  # the client keeps the previous role's session
            login = context.post("/api/login", json={"username": user.email, "password": "pass"})
            self.assertEqual(login.status_code, 200, user.email)
            return context.get(url).status_code

    def _issue_as_breeder(self, individual):
        self._start_mock_aws()
        with self.app as context:
            context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
            response = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
            )
            self.assertEqual(response.status_code, 201)

    def test_viewer_cannot_download_or_preview(self):
        """A viewer role on the genebank reads the register but not the certificate."""
        individual = self.individuals[3]
        self._issue_as_breeder(individual)
        self.assertEqual(self._status(self.viewer, f"/api/v2/certificates/{individual.number}"), 403)
        self.assertEqual(self._status(self.viewer, f"/api/v2/certificates/preview/{individual.number}"), 403)

    def test_owner_of_another_herd_gets_403(self):
        """individuals[1] was bred in and lives in herds[1]; self.owner owns herds[0]."""
        individual = self.individuals[1]
        self.assertEqual(self._status(self.owner, f"/api/v2/certificates/preview/{individual.number}"), 403)

    def test_breeder_manager_admin_can_preview(self):
        individual = self.individuals[3]  # origin herds[0] = self.owner's herd, genebank[0]
        for user in (self.owner, self.manager, self.admin):
            self.assertEqual(self._status(user, f"/api/v2/certificates/preview/{individual.number}"), 200, user.email)

    def test_current_owner_keeps_access_after_transfer(self):
        """The buyer (current herd) may download; the breeder keeps access too."""
        import utils.data_access as da

        individual = self.individuals[3]
        self._issue_as_breeder(individual)
        buyer = da.register_user("buyer", "pass")
        buyer.add_role("owner", self.herds[1].id)
        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[1],
            signature=self.manager,
            individual=individual,
            herd_tracking_date=datetime.now(),
        )
        self.assertEqual(db.Individual.get(db.Individual.id == individual.id).current_herd.id, self.herds[1].id)
        self.assertEqual(self._status(buyer, f"/api/v2/certificates/{individual.number}"), 200)
        self.assertEqual(self._status(self.owner, f"/api/v2/certificates/{individual.number}"), 200)

    def _rabbit_page(self, user, number):
        """GET /api/v2/individual/<number> as `user`: what the rabbit page is told."""
        with self.app as context:
            context.get("/api/logout")
            context.post("/api/login", json={"username": user.email, "password": "pass"})
            response = context.get(f"/api/v2/individual/{number}")
            self.assertEqual(response.status_code, 200, user.email)
            return response.get_json()

    def _as_breeder(self, method, url, **kwargs):
        """Issue or re-issue as the origin herd's owner: the breeder may, whoever else may too (#141)."""
        self._start_mock_aws()
        with self.app as context:
            context.get("/api/logout")
            context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
            response = getattr(context, method)(url, **kwargs)
            self.assertIn(response.status_code, (200, 201), response.get_json())

    def test_rabbit_page_flag_matches_the_download(self):
        """The page shows the button exactly when the download answers: before and after a sale, for every role."""
        import utils.data_access as da

        individual = self.individuals[3]  # bred in herds[0] (self.owner), genebank[0]
        self._as_breeder(
            "post",
            f"/api/v2/certificates/issue/{individual.number}",
            json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
        )
        buyer = da.register_user("buyer", "pass")
        buyer.add_role("owner", self.herds[1].id)
        users = (self.owner, buyer, self.manager, self.admin, self.viewer)

        def check(expected):
            for user in users:
                with self.subTest(user=user.email, expected=expected[user.email]):
                    flag = self._rabbit_page(user, individual.number)["can_view_certificate"]
                    status = self._status(user, f"/api/v2/certificates/{individual.number}")
                    self.assertIs(flag, expected[user.email])
                    self.assertEqual(status, 200 if flag else 403)

        check({"owner": True, "buyer": False, "man": True, "admin": True, "spec": False})
        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[1],
            signature=self.manager,
            individual=individual,
            herd_tracking_date=datetime.now(),
        )
        check({"owner": True, "buyer": True, "man": True, "admin": True, "spec": False})

    def test_rabbit_page_links_the_current_certificate_for_everyone(self):
        """The verification link goes to all who may see the rabbit, and follows a re-issue."""
        individual = self.individuals[3]
        self._as_breeder(
            "post",
            f"/api/v2/certificates/issue/{individual.number}",
            json={"color_id": 1, "litter_size": 5, "litter_size6w": 4},
        )
        self._as_breeder("patch", f"/api/v2/certificates/update/{individual.number}", json={"name": "Ny"})
        current = db.DigitalCertificateV2.get(
            (db.DigitalCertificateV2.individual == individual) & (db.DigitalCertificateV2.is_current == True)  # noqa: E712
        )
        for user in (self.viewer, self.owner):
            with self.subTest(user=user.email):
                self.assertEqual(
                    self._rabbit_page(user, individual.number)["current_certificate"],
                    {"verification_token": str(current.verification_token), "issued_at": current.issued_at.isoformat()},
                )

    def test_rabbit_page_has_no_verification_link_without_a_v2_certificate(self):
        """A v1 certificate has no verification page; the owner still gets the button (the v1 PDF)."""
        individual = self.individuals[3]
        db.Individual.update(digital_certificate=4711).where(db.Individual.id == individual.id).execute()
        data = self._rabbit_page(self.owner, individual.number)
        self.assertIsNone(data["current_certificate"])
        self.assertTrue(data["can_view_certificate"])

    def test_a_role_on_gx1_does_not_open_certificates_sold_outside(self):
        """GX1 holds every rabbit sold outside the genebank: an owner role there reads none of their certificates."""
        import utils.data_access as da

        individual = self.individuals[3]
        self._issue_as_breeder(individual)
        gx1 = db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför genbanken")
        gx_owner = da.register_user("gxowner", "pass")
        gx_owner.add_role("owner", gx1.id)
        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=gx1,
            signature=self.manager,
            individual=individual,
            herd_tracking_date=datetime.now(),
        )
        self.assertEqual(db.Individual.get(db.Individual.id == individual.id).current_herd.id, gx1.id)
        for url in (f"/api/v2/certificates/{individual.number}", f"/api/v2/certificates/preview/{individual.number}"):
            self.assertEqual(self._status(gx_owner, url), 403, url)
        self.assertEqual(self._status(self.owner, f"/api/v2/certificates/{individual.number}"), 200)

    def test_gx1_as_origin_gives_no_right(self):
        """A rabbit imported into GX1/MX1 is no rabbit of a GX1 role holder: no issue, no view."""
        from types import SimpleNamespace
        from unittest import mock

        gx1 = db.Herd.create(genebank=self.genebanks[0], herd="GX1", herd_name="Utanför genbanken")
        imported = SimpleNamespace(origin_herd=gx1, current_herd=gx1)
        user = db.User.get_by_id(self.owner.id)
        with mock.patch.object(db.User, "effective_herd_ids", return_value={gx1.id, self.herds[0].id}):
            self.assertFalse(user.can_issue_certificate(imported))
            self.assertFalse(user.can_view_certificate(imported))
            self.assertTrue(user.owns_herd_of(self.herds[0]))

    def test_nameless_breeder_gets_no_preview_without_a_name(self):
        """With no signed PDF to fall back on, a nameless herd member is told to get a name, not shown a blank."""
        individual = self.individuals[3]  # uncertified, born in self.owner's herd
        db.User.update(fullname=None).where(db.User.id == self.owner.id).execute()
        with self.app as context:
            context.get("/api/logout")
            context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
            response = context.get(f"/api/v2/certificates/preview/{individual.number}")
        self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["detail"], ATTESTER_NAME_MISSING)

    def test_buyer_preview_is_the_signed_certificate(self):
        """Only someone who may issue the next version gets a rendered preview naming her; the buyer gets the PDF."""
        from unittest import mock

        import utils.data_access as da
        from utils.cert_service_v2 import _generator

        individual = self.individuals[3]
        db.User.update(fullname="Utfärdande Person").where(db.User.id == self.admin.id).execute()
        self._issue_as_breeder(individual)
        buyer = da.register_user("buyer", "pass")
        buyer.add_role("owner", self.herds[1].id)
        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[1],
            signature=self.manager,
            individual=individual,
            herd_tracking_date=datetime.now(),
        )
        # The buyer, the manager and admin get the signed certificate as issued, so nothing changed since appears
        # under the issuer's name; also when older code cleared the rabbit's number but the v2 row is current
        db.Individual.update(digital_certificate=None).where(db.Individual.id == individual.id).execute()
        nameless = da.register_user("skotare", "pass")
        nameless.add_role("owner", self.herds[0].id)  # herd access, but no name: may not issue, so no rendered preview
        for viewer in (buyer, self.manager, self.admin, nameless):
            with mock.patch.object(_generator, "generate_pedigree") as render:
                self.assertEqual(self._status(viewer, f"/api/v2/certificates/preview/{individual.number}"), 200)
            render.assert_not_called()


class TestCertificateLockOrder(CertV2Mixin, FlaskTest):
    """issue/update lock Breeding, then ONE ascending call over the rabbit + its parents."""

    def _capture(self, method, url, payload):
        from unittest import mock

        import utils.database as db

        statements = []
        original = db.DATABASE.execute_sql

        def capture(sql, params=None, *args, **kwargs):
            statements.append((sql, list(params or [])))
            return original(sql, params, *args, **kwargs)

        with self.app as context:
            context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
            with mock.patch.object(db.DATABASE, "execute_sql", side_effect=capture):
                response = getattr(context, method)(url, json=payload)
        return response, statements

    def _assert_order(self, statements, individual):
        def is_lock(sql):
            return "FOR UPDATE" in sql or "FOR NO KEY UPDATE" in sql

        locks = [(i, sql, params) for i, (sql, params) in enumerate(statements) if is_lock(sql)]
        self.assertIn('FROM "breeding"', locks[0][1], "the Breeding row is locked first")
        ind_locks = [(i, params) for i, sql, params in locks if 'FROM "individual"' in sql]
        breeding = individual.breeding
        wanted = sorted({individual.id, breeding.mother_id, breeding.father_id})
        self.assertEqual(ind_locks[0][1], wanted, "rabbit + parents in one ascending call")
        first_write = next(i for i, (sql, _) in enumerate(statements) if sql.startswith('UPDATE "individual"'))
        self.assertLess(ind_locks[0][0], first_write)
        held = set(wanted)
        self.assertTrue(
            all(set(params) <= held for _, params in ind_locks), "no individual lock beyond the first call's set"
        )

    @unittest.skipUnless(_USE_POSTGRES, "row locks need PostgreSQL")
    def test_issue_with_litter_change(self):
        self._start_mock_aws()
        individual = self.individuals[3]
        response, statements = self._capture(
            "post",
            f"/api/v2/certificates/issue/{individual.number}",
            {"color_id": 1, "litter_size": 5, "litter_size6w": 1},
        )
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        self._assert_order(statements, individual)

    @unittest.skipUnless(_USE_POSTGRES, "row locks need PostgreSQL")
    def test_update_with_litter_change(self):
        self._start_mock_aws()
        individual = self.individuals[0]  # paper certificate
        response, statements = self._capture(
            "patch",
            f"/api/v2/certificates/update/{individual.number}",
            {"litter_size": 5, "litter_size6w": 1},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self._assert_order(statements, individual)


class TestCertificateIssueOnTheLockedRow(CertV2Mixin, FlaskTest):
    """Final review: issuance acts on the rabbit as committed when it takes the lock. A change committing
    between the route's read and its lock is simulated deterministically inside normalize_color, which
    both routes call in that window (same pattern as in test_uploads)."""

    MOVED = {"death_date": date(2026, 10, 1), "death_note": "död", "number": "G1-2119"}

    def setUp(self):
        super().setUp()
        self._start_mock_aws()

    def _sold(self, individual):
        """Sold to G2: the breeder (owner of G1) may still issue, but not edit (the scoped branch)."""
        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[1],
            signature=self.manager,
            individual=individual,
            herd_tracking_date=datetime.now(),
        )

    @contextmanager
    def _committed_before_the_lock(self, individual_id, **values):
        real, ran = certificates.normalize_color, []

        def concurrent(*args, **kwargs):
            ran.append(True)
            db.Individual.update(**values).where(db.Individual.id == individual_id).execute()
            return real(*args, **kwargs)

        with patch.object(certificates, "normalize_color", side_effect=concurrent):
            yield
        self.assertTrue(ran, "normalize_color was never reached")

    def _result(self, response, individual_id):
        stored = db.Individual.get_by_id(individual_id)
        body = response.get_json()
        return (response.status_code, body.get("individual_number"), stored.number, stored.death_date)

    def test_breeder_issuance_keeps_a_death_and_renumber(self):
        individual = self.individuals[3]  # G1-2112: born in G1, uncertified
        self._sold(individual)
        with self._committed_before_the_lock(individual.id, **self.MOVED):
            response = self._request(self.owner, "post", f"/api/v2/certificates/issue/{individual.number}")
        self.assertEqual(self._result(response, individual.id), (201, "G1-2119", "G1-2119", date(2026, 10, 1)))
        self.assertIsNotNone(db.Individual.get_by_id(individual.id).digital_certificate)

    def test_breeder_conversion_keeps_a_death_and_renumber(self):
        individual = self.individuals[0]  # G1-2111: paper certificate "12"
        self._sold(individual)
        with self._committed_before_the_lock(individual.id, **self.MOVED):
            response = self._request(self.owner, "patch", f"/api/v2/certificates/update/{individual.number}")
        self.assertEqual(self._result(response, individual.id), (200, "G1-2119", "G1-2119", date(2026, 10, 1)))
        stored = db.Individual.get_by_id(individual.id)
        self.assertEqual((stored.certificate, stored.digital_certificate), (None, 100000))

    def test_editor_issuance_keeps_a_renumber(self):
        """With edit rights the route writes through update_individual: its form must be the locked row,
        or the number read before the lock becomes a rename back."""
        individual = self.individuals[3]
        with self._committed_before_the_lock(individual.id, number="G1-2119"):
            response = self._request(self.owner, "post", f"/api/v2/certificates/issue/{individual.number}")
        self.assertEqual(self._result(response, individual.id), (201, "G1-2119", "G1-2119", None))

    def test_breeder_authority_is_decided_on_the_locked_row(self):
        """An origin correction to G2 commits before the lock: the G1 owner is no longer the breeder,
        for a first issuance or a paper conversion (which took no lock before)."""
        for method, route, individual in (
            ("post", "issue", self.individuals[3]),
            ("patch", "update", self.individuals[0]),
        ):
            with self.subTest(route=route):
                self._sold(individual)
                with self._committed_before_the_lock(individual.id, origin_herd=self.herds[1].id):
                    response = self._request(self.owner, method, f"/api/v2/certificates/{route}/{individual.number}")
                stored = db.Individual.get_by_id(individual.id)
                self.assertEqual(
                    (response.status_code, stored.origin_herd.herd, stored.digital_certificate), (403, "G2", None)
                )
        self.assertEqual(db.DigitalCertificateV2.select().count(), 0)

    def test_concurrent_issuance_keeps_the_first_number(self):
        individual = self.individuals[3]
        self._sold(individual)
        with self._committed_before_the_lock(individual.id, digital_certificate=100500):
            response = self._request(self.owner, "post", f"/api/v2/certificates/issue/{individual.number}")
        stored = db.Individual.get_by_id(individual.id)
        self.assertEqual((response.status_code, stored.digital_certificate), (400, 100500))
        self.assertEqual(db.DigitalCertificateV2.select().count(), 0)

    def test_blank_paper_number_is_no_certificate(self):
        """Legacy create stores certificate="". The quota counts it as none,
        but the conversion route took it for a paper certificate and gave the breeder a first digital number
        without the litter rules (here: litter_size6w missing). It is issued, under those rules."""
        litter = db.Breeding.create(
            breeding_herd_id=self.herds[0],
            birth_date=date(2025, 3, 25),
            litter_number=1,
            litter_size=2,
            mother=self.parents[0],
            father=self.parents[1],
        )
        rabbit = db.Individual.create(origin_herd=self.herds[0], breeding=litter, number="G1-2511", certificate="")
        self._sold(rabbit)
        converted = self._request(self.owner, "patch", f"/api/v2/certificates/update/{rabbit.number}")
        issued = self._request(self.owner, "post", f"/api/v2/certificates/issue/{rabbit.number}")
        self.assertEqual(
            (converted.status_code, issued.status_code, issued.get_json()["detail"]),
            (400, 400, "litter_size6w_required"),
        )
        self.assertIsNone(db.Individual.get_by_id(rabbit.id).digital_certificate)

    def test_issuing_writes_nothing_to_s3(self):
        """Step A of stamboken-drift #69: the v2 PDF lives on the data volume only, and the legacy routes read it
        from there."""
        import utils.s3 as s3

        self._start_mock_aws()
        client = s3.get_s3_client()
        individual = self.individuals[3]
        response = self._request(self.owner, "post", f"/api/v2/certificates/issue/{individual.number}")
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertNotIn("Contents", client.s3_client.list_objects_v2(Bucket=client.bucket))
        row = db.DigitalCertificateV2.get(db.DigitalCertificateV2.individual == individual.id)
        with open(os.path.join("uppladdningar", row.file_path), "rb") as stored:
            pdf = stored.read()
        legacy = self._request(self.owner, "get", f"/api/certificates/issue/{individual.number}")
        self.assertEqual((legacy.status_code, legacy.get_data()), (200, pdf))
        with self.app as context:
            context.post("/api/login", json={"username": self.owner.email, "password": "pass"})
            verified = context.post(f"/api/certificates/verify/{individual.number}", data=pdf)
        self.assertEqual(verified.status_code, 200, verified.get_json())

    def test_the_demo_never_hands_out_a_stored_certificate(self):
        """stamboken-drift #117 p3: the demo renders an unsigned, watermarked certificate without an attester."""
        import utils.cert_service_v2 as cert_service_v2

        self._start_mock_aws()
        individual = self.individuals[3]
        self.assertEqual(
            self._request(self.owner, "post", f"/api/v2/certificates/issue/{individual.number}").status_code, 201
        )
        with (
            patch.object(settings.service, "demo_instance", True),
            patch.object(cert_service_v2._generator, "generate_pedigree", return_value=b"%PDF-demo") as render,
        ):
            v2 = self._request(self.owner, "get", f"/api/v2/certificates/{individual.number}")
            legacy = self._request(self.owner, "get", f"/api/certificates/issue/{individual.number}")
        self.assertEqual((v2.get_data(), legacy.get_data()), (b"%PDF-demo", b"%PDF-demo"))
        data = render.call_args.args[0]
        self.assertEqual((data["fullname"], data["demo_watermark"]), ("", True))

    def test_the_demo_renders_also_the_preview_the_mail_and_a_row_without_its_number(self):
        import utils.buyer_mail as buyer_mail
        import utils.cert_service_v2 as cert_service_v2

        self._start_mock_aws()
        individual = self.individuals[3]
        self.assertEqual(
            self._request(self.owner, "post", f"/api/v2/certificates/issue/{individual.number}").status_code, 201
        )
        # migrate_37_to_38 keeps a current row whose digital number was lost: production still serves it.
        db.Individual.update(digital_certificate=None).where(db.Individual.id == individual.id).execute()
        with (
            patch.object(settings.service, "demo_instance", True),
            patch.object(cert_service_v2._generator, "generate_pedigree", return_value=b"%PDF-demo"),
        ):
            v2 = self._request(self.owner, "get", f"/api/v2/certificates/{individual.number}")
            preview = self._request(self.owner, "get", f"/api/certificates/preview/{individual.number}")
            mailed = buyer_mail._certificate_pdf(db.Individual.get_by_id(individual.id))
        self.assertEqual((v2.get_data(), preview.get_data(), mailed), (b"%PDF-demo", b"%PDF-demo", None))

    def test_a_v1_file_verifies_only_while_it_is_the_certificate(self):
        import hashlib

        from utils.cert_acess import upload_certificate, verify_certificate_checksum

        self._start_mock_aws()
        individual = self.individuals[3]
        upload_certificate(pdf_bytes=b"%PDF-v1", ind_number=individual.number)
        checksum = hashlib.sha256(b"%PDF-v1").hexdigest()
        db.Individual.update(digital_certificate=4711).where(db.Individual.id == individual.id).execute()
        self.assertTrue(verify_certificate_checksum(individual.number, checksum))
        # A paper certificate replaced it (or a reissue): the file stays in S3 but is no longer the certificate.
        db.Individual.update(digital_certificate=None).where(db.Individual.id == individual.id).execute()
        with self.assertRaises(LookupError):  # no certificate: the legacy route answers 400, as before
            verify_certificate_checksum(individual.number, checksum)
