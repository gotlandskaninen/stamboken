"""
Tests for v2 certificate API endpoints (Blueprint).

Note: All tests that issue certificates use mock_aws() from moto for S3,
and require app/certs/key.pem + app/certs/ca.pem in the test container.
"""

import unittest
from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import patch

import blueprints.certificates as certificates
import utils.database as db
import utils.settings as settings
from moto import mock_aws

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
                json={"username": self.admin.email, "password": "pass"},
            )
            response = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={
                    "color_id": 3,
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
                json={"username": self.admin.email, "password": "pass"},
            )
            # First issue
            context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
            )
            # Second issue — should fail
            response = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
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
                json={"username": self.admin.email, "password": "pass"},
            )
            with patch.object(
                cert_service._generator,
                "generate_pedigree",
                wraps=cert_service._generator.generate_pedigree,
            ) as spy:
                response = context.post(
                    f"/api/v2/certificates/issue/{individual.number}",
                    json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
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
                json={"username": self.admin.email, "password": "pass"},
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
                    json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
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
                json={"username": self.admin.email, "password": "pass"},
            )
            with patch.object(
                cert_service._generator,
                "generate_pedigree",
                wraps=cert_service._generator.generate_pedigree,
            ) as spy:
                response = context.post(
                    f"/api/v2/certificates/issue/{individual.number}",
                    json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
                )
            self.assertEqual(response.status_code, 201)
            self.assertFalse(spy.call_args.args[0]["demo_watermark"])

    def test_issue_uploads_token_named_s3_object(self):
        """Issue uploads the signed PDF to S3 under certifikat/v2/<token>.pdf."""
        self._start_mock_aws()
        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.admin.email, "password": "pass"},
            )
            response = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
            )
            self.assertEqual(response.status_code, 201)
            token = response.get_json()["verification_token"]

            from utils.cert_acess import download_certificate_v2

            pdf_bytes = download_certificate_v2(token)
            self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_failed_v2_upload_leaves_no_downloadable_certificate(self):
        """A failed token-named S3 upload must not leave a downloadable cert.

        The v2 upload runs before the legacy v1-key upload — if it fails, the
        transaction rolls back and the legacy key must be untouched, so the
        no-v2-row download fallback cannot serve an uncommitted PDF.
        """
        self._start_mock_aws()
        import utils.database as db

        class _S3Down(Exception):
            pass

        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.admin.email, "password": "pass"},
            )
            with patch("utils.cert_service_v2.upload_certificate_v2", side_effect=_S3Down("S3 down")):
                try:
                    response = context.post(
                        f"/api/v2/certificates/issue/{individual.number}",
                        json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
                    )
                    self.assertGreaterEqual(response.status_code, 500)
                except _S3Down:
                    # TESTING=True propagates unhandled exceptions to the client
                    pass

            # Transaction rolled back — no cert row, individual not certified
            count = db.DigitalCertificateV2.select().where(db.DigitalCertificateV2.individual == individual).count()
            self.assertEqual(count, 0)
            refreshed = db.Individual.get(db.Individual.id == individual.id)
            self.assertIsNone(refreshed.digital_certificate)

            # Legacy S3 key was never written — nothing to download
            response = context.get(f"/api/v2/certificates/{individual.number}")
            self.assertEqual(response.status_code, 404)

    def test_issue_paper_cert_returns_400(self):
        """Cannot issue when a paper certificate exists — convert via PATCH."""
        individual = self.individuals[0]  # certificate="12"

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.admin.email, "password": "pass"},
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

    def test_manager_can_issue(self):
        """Genebank manager can issue certificates for individuals in their genebank."""
        self._start_mock_aws()
        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.manager.email, "password": "pass"},
            )
            response = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
            )
            # Manager should succeed if individual is in their genebank
            self.assertIn(response.status_code, [201, 403])

    def test_signing_guard_returns_503(self):
        """Signing failure returns 503 Service Unavailable."""
        self._start_mock_aws()
        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.admin.email, "password": "pass"},
            )
            from utils.certificates_v2 import SigningUnavailableError

            with patch("utils.cert_service_v2.sign_pdf", side_effect=SigningUnavailableError("no creds")):
                response = context.post(
                    f"/api/v2/certificates/issue/{individual.number}",
                    json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
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
                context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
                response = context.post(
                    f"/api/v2/certificates/issue/{individual.number}",
                    json={"color_id": 3, "litter_size": 0, "litter_size6w": 0},
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
        body = {"color_id": 3, "origin_herd": {"herd": "G2"}}
        with self.app as context:
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
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
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            response = context.post(f"/api/v2/certificates/issue/{rabbit.number}", json={"color_id": 3})
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
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            missing = context.post(f"/api/v2/certificates/issue/{rabbit.number}", json={"color_id": 3})
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
        # The breeder after a sale issues without edit rights: the other (non-editor) path.
        ht_row(
            "TRANSFER",
            from_herd=self.herds[0],
            herd=self.herds[1],
            signature=self.manager,
            individual=rabbit,
            herd_tracking_date=datetime.now(),
        )
        responses = {}
        for path, user, body in (("editor", self.admin, {"color_id": 3}), ("breeder", self.owner, {})):
            with self.app as context:
                context.post("/api/login", json={"username": user.email, "password": "pass"})
                responses[path] = context.post(f"/api/v2/certificates/issue/{rabbit.number}", json=body)
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
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
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
                json={"username": self.admin.email, "password": "pass"},
            )
            # First issue to get a v1 cert
            context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
            )
            # Update (v1→v2 upgrade)
            response = context.patch(
                f"/api/v2/certificates/update/{individual.number}",
                json={"color_id": 3, "litter_size": 6, "litter_size6w": 5},
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
                json={"username": self.admin.email, "password": "pass"},
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
                json={"username": self.admin.email, "password": "pass"},
            )
            # Issue
            issue_resp = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
            )
            old_token = issue_resp.get_json()["verification_token"]

            # Update
            context.patch(
                f"/api/v2/certificates/update/{individual.number}",
                json={"color_id": 3, "litter_size": 6, "litter_size6w": 5},
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
                json={"username": self.admin.email, "password": "pass"},
            )
            issue_resp = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
            )
            old_token = issue_resp.get_json()["verification_token"]

            update_resp = context.patch(
                f"/api/v2/certificates/update/{individual.number}",
                json={"color_id": 3, "litter_size": 6, "litter_size6w": 5},
            )
            new_issued_at = update_resp.get_json()["issued_at"]

        # Public endpoint — no auth
        response = self.app.get(f"/api/v2/certificates/verify/{old_token}")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["verified"])
        self.assertFalse(data["is_current"])
        self.assertEqual(data["replaced_by_date"], new_issued_at)


class TestCertificateV2Download(CertV2Mixin, FlaskTest):
    """Tests for GET /api/v2/certificates/<number>."""

    def test_download_returns_pdf(self):
        """Download returns PDF content-type."""
        self._start_mock_aws()
        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.admin.email, "password": "pass"},
            )
            # Issue first
            context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
            )
            # Download
            response = context.get(f"/api/v2/certificates/{individual.number}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content_type, "application/pdf")

    def test_download_falls_back_to_s3_when_disk_file_missing(self):
        """Download serves the token-named S3 copy when the disk file is gone."""
        self._start_mock_aws()
        import os

        import utils.database as db

        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.admin.email, "password": "pass"},
            )
            context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
            )
            cert = (
                db.DigitalCertificateV2.select()
                .where(
                    (db.DigitalCertificateV2.individual == individual) & (db.DigitalCertificateV2.is_current == True)  # noqa: E712
                )
                .get()
            )
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
                json={"username": self.admin.email, "password": "pass"},
            )
            context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
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
                json={"username": self.admin.email, "password": "pass"},
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
                json={"username": self.admin.email, "password": "pass"},
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
                json={"username": self.admin.email, "password": "pass"},
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
        """Issuance for a rabbit with unknown parents works too, legacy and v2 (no 500, no "Invalid parents")."""
        self._start_mock_aws()

        def status(request):
            try:
                return request().status_code
            except Exception as exc:  # TESTING=True propagates an unhandled error (a 500 in production)
                return f"unhandled {type(exc).__name__}: {exc}"

        legacy, v2 = self.parents[0], self.parents[1]  # G1-1911, G2-1711: founders, litters without parents
        with self.app as context:
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            observed = {
                "legacy_issue": status(
                    lambda: context.post(
                        f"/api/certificates/issue/{legacy.number}", json={"litter_size": 2, "litter_size6w": 2}
                    )
                ),
                "v2_issue": status(lambda: context.post(f"/api/v2/certificates/issue/{v2.number}", json={})),
            }
        self.assertEqual(observed, {"legacy_issue": 200, "v2_issue": 201})


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
                json={"username": self.admin.email, "password": "pass"},
            )
            issue_resp = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
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

    def test_verify_post_with_pdf(self):
        """POST verify with actual PDF bytes checks checksum + signature."""
        self._start_mock_aws()
        individual = self.individuals[3]

        with self.app as context:
            context.post(
                "/api/login",
                json={"username": self.admin.email, "password": "pass"},
            )
            issue_resp = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
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
                json={"username": self.admin.email, "password": "pass"},
            )
            issue_resp = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
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
                json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
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
                json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
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
                json={"color_id": 3},
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

    def test_caretaker_cannot_sell_via_certificate_issue(self):
        """A herd-access grant may edit and issue, but a herd change in the issue body is a transfer."""
        self._start_mock_aws()
        import utils.data_access as da
        import utils.database as db

        membership = db.Membership.create(member_number=6, membership_status="active")
        db.Herd.update(membership=membership).where(db.Herd.id == self.herds[0].id).execute()
        user = da.register_user("sune@ex.se", "pass", username="sune")
        caretaker = db.Member.create(
            membership=membership, first_name="Sune", last_name="S", email="sune@ex.se", role="skotare", user=user
        )
        db.HerdAccessGrant.create(member=caretaker, herd=self.herds[0], granted_by=self.admin)
        number = self.individuals[3].number  # G1-2112: born in G1, uncertified
        body = {"herd": "G2", "selling_date": "2021-06-01", "litter_size": 2, "litter_size6w": 2}
        with self.app as context:
            context.post("/api/login", json={"username": "sune", "password": "pass"})
            # sanity: the individual route refuses this caretaker the same move
            denied = context.patch(f"/api/individual/{number}", json=dict(body))
            self.assertEqual(denied.status_code, 403, denied.get_data(as_text=True))
            response = context.post(f"/api/v2/certificates/issue/{number}", json=dict(body))
            # the update route (paper→digital conversion of G1-2111) merges the body the same way
            updated = context.patch(f"/api/v2/certificates/update/{self.individuals[0].number}", json=dict(body))
        self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
        self.assertEqual(updated.status_code, 403, updated.get_data(as_text=True))
        for individual in (self.individuals[3], self.individuals[0]):
            stored = db.Individual.get_by_id(individual.id)
            self.assertEqual((stored.current_herd.herd, stored.digital_certificate), ("G1", None))
        self.assertEqual(db.DigitalCertificateV2.select().count(), 0)

    def test_genebank_change_via_certificate_issue_is_an_admin_correction(self):
        """The issue route merges a herd change like PATCH: into another genebank only by an admin, with a reason."""
        self._start_mock_aws()
        import utils.database as db

        individual = self.individuals[3]  # G1-2112: born in G1, uncertified
        body = {"herd": "M3", "selling_date": "2021-06-01", "litter_size": 2, "litter_size6w": 2}
        with self.app as context:
            context.post("/api/login", json={"username": self.manager.email, "password": "pass"})
            denied = context.post(f"/api/v2/certificates/issue/{individual.number}", json={**body, "reason": "Fel"})
            context.get("/api/logout")
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            no_reason = context.post(f"/api/v2/certificates/issue/{individual.number}", json=dict(body))
            self.assertEqual(denied.status_code, 403, denied.get_data(as_text=True))
            self.assertEqual(no_reason.status_code, 400, no_reason.get_data(as_text=True))
            self.assertEqual(db.DigitalCertificateV2.select().count(), 0)
            self.assertEqual(db.Individual.get_by_id(individual.id).current_herd.herd, "G1")
            response = context.post(f"/api/v2/certificates/issue/{individual.number}", json={**body, "reason": "Fel"})
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        stored = db.Individual.get_by_id(individual.id)
        self.assertEqual((stored.current_herd.herd, stored.digital_certificate), ("M3", 100000))
        transfer = db.HerdTracking.get(db.HerdTracking.individual == individual, db.HerdTracking.kind == "TRANSFER")
        self.assertEqual(transfer.notes, "Fel")

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
                json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
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

    def _issue_as_admin(self, individual):
        self._start_mock_aws()
        with self.app as context:
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            response = context.post(
                f"/api/v2/certificates/issue/{individual.number}",
                json={"color_id": 3, "litter_size": 5, "litter_size6w": 4},
            )
            self.assertEqual(response.status_code, 201)

    def test_viewer_cannot_download_or_preview(self):
        """A viewer role on the genebank reads the register but not the certificate."""
        individual = self.individuals[3]
        self._issue_as_admin(individual)
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
        self._issue_as_admin(individual)
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
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
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
            {"color_id": 3, "litter_size": 5, "litter_size6w": 1},
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

    def _request(self, user, method, url):
        with self.app as context:
            context.post("/api/login", json={"username": user.email, "password": "pass"})
            return getattr(context, method)(url, json={})

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
            response = self._request(self.manager, "post", f"/api/v2/certificates/issue/{individual.number}")
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

    def test_legacy_key_upload_holds_the_number_lock(self):
        """Final review (24a65b0): a renumber copies its staged assets to the new number after its commit, under
        the number lock (number_assets.finish). The certificate upload to that key did not take the lock, so
        the older PDF could land over the new one. It uploads under the lock now, as a photo upload does."""
        import utils.cert_service_v2 as cert_service_v2
        from utils import number_assets

        events = []
        real_lock, real_upload = number_assets.lock_number, cert_service_v2.upload_certificate

        def lock(number, xact=False):
            events.append(("lock", number, xact))
            return real_lock(number, xact=xact)

        def upload(pdf_bytes, ind_number):
            events.append(("upload", ind_number))
            return real_upload(pdf_bytes=pdf_bytes, ind_number=ind_number)

        individual = self.individuals[3]
        with (
            patch.object(number_assets, "lock_number", side_effect=lock),
            patch.object(cert_service_v2, "upload_certificate", side_effect=upload),
        ):
            response = self._request(self.manager, "post", f"/api/v2/certificates/issue/{individual.number}")
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(events[-2:], [("lock", individual.number, True), ("upload", individual.number)])
