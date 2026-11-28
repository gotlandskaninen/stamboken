"""flask certificates reissue-v1: v1 certificates get a v2 certificate attested by the original issuer (#142)."""

import io
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import cli.certificates as reissue_cli
import utils.cert_service_v2 as cert_service
import utils.database as db
import utils.s3 as s3
from botocore.exceptions import EndpointConnectionError
from herdbook import APP
from pdfrw import PdfArray, PdfDict, PdfName, PdfString, PdfWriter
from utils.cert_acess import download_certificate_s3, get_certificate_data, upload_certificate
from utils.certificates import FORM_KEYS

from tests.database_test import _USE_POSTGRES
from tests.test_certificates_v2_api import CertV2Mixin
from tests.test_endpoints import FlaskTest

V2 = b"%PDF-1.4 v2"


def pdf_with(fields):
    """A PDF with these form fields, encoded as the v1 generator (utils/certificates.py) fills them."""
    annotations = [
        PdfDict(
            Type=PdfName.Annot,
            Subtype=PdfName.Widget,
            FT=PdfName.Tx,
            T=PdfString.encode(name),
            V=PdfString.encode(str(value) if value else ""),  # as CertificateGenerator._encode_pdf_string
            Rect=PdfArray([0, 0, 100, 20]),
        )
        for name, value in fields.items()
    ]
    # The signature field endesive adds to every v1 certificate: its value is a dictionary, not a string.
    annotations.append(
        PdfDict(
            Type=PdfName.Annot,
            Subtype=PdfName.Widget,
            FT=PdfName.Sig,
            T=PdfString.encode("Signature1"),
            V=PdfDict(Type=PdfName.Sig),
        )
    )
    writer = PdfWriter()
    writer.addpage(PdfDict(Type=PdfName.Page, MediaBox=PdfArray([0, 0, 595, 842]), Annots=PdfArray(annotations)))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@unittest.skipUnless(_USE_POSTGRES, "needs Postgres")
class ReissueV1Test(CertV2Mixin, FlaskTest):
    def setUp(self):
        super().setUp()
        self._start_mock_aws()  # real S3 calls, in moto
        db.User.update(fullname="Åsa  Öberg").where(db.User.id == self.owner.id).execute()
        self.owner = db.User.get_by_id(self.owner.id)
        self.rabbit = self.v1_rabbit(self.individuals[3], 4711)  # origin herd G1, which the owner owns
        self.pedigree = MagicMock(return_value=V2)
        stubs = (
            patch.object(cert_service._generator, "generate_pedigree", self.pedigree),
            patch.object(cert_service, "sign_pdf", side_effect=lambda pdf, **kw: pdf),
            patch.object(cert_service, "write_durably"),
        )
        for stub in stubs:
            stub.start()
            self.addCleanup(stub.stop)
        self.archive = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.archive)
        archive = patch.object(reissue_cli, "ARCHIVE", self.archive)
        archive.start()
        self.addCleanup(archive.stop)
        self.keys = self.s3_keys()

    def s3_keys(self):
        client = s3.get_s3_client()
        return {o["Key"] for o in client.s3_client.list_objects_v2(Bucket=client.bucket).get("Contents", [])}

    def archived(self, rabbit=None):
        path = os.path.join(self.archive, f"{(rabbit or self.rabbit).digital_certificate}.pdf")
        with open(path, "rb") as kept:
            return kept.read()

    def v1_rabbit(self, rabbit, number, **fields):
        """Give `rabbit` digital number `number` and a v1 PDF as the old app made it, with `fields` changed."""
        update = db.Individual.update(certificate=None, digital_certificate=number)
        update.where(db.Individual.id == rabbit.id).execute()
        rabbit = db.Individual.get_by_id(rabbit.id)
        today = get_certificate_data(rabbit.as_dict(), self.owner.uuid)
        made = {field: today.get(key, "") for field, key in FORM_KEYS.items() if key}
        made.update(fields)
        upload_certificate(pdf_bytes=pdf_with(made), ind_number=rabbit.number)
        return rabbit

    def invoke(self, *args):
        return APP.test_cli_runner().invoke(args=["certificates", "reissue-v1", *args])

    def current_row(self, rabbit=None):
        return db.DigitalCertificateV2.get_or_none(
            (db.DigitalCertificateV2.individual == (rabbit or self.rabbit).id) & db.DigitalCertificateV2.is_current
        )

    def assert_stopped(self, reason, *args):
        original = download_certificate_s3(self.rabbit.number)
        result = self.invoke("--run", *args)
        self.assertIn(f"{self.rabbit.number} (besättning G1): {reason}", result.output, result.output)
        self.assertIsNone(self.current_row())
        self.assertEqual(download_certificate_s3(self.rabbit.number), original)  # the v1 file is untouched
        return result

    def test_dry_run_writes_nothing(self):
        original = download_certificate_s3(self.rabbit.number)
        result = self.invoke()
        self.assertIn("Skulle återutfärdas: 1", result.output, result.output)
        self.assertIsNone(self.current_row())
        self.pedigree.assert_not_called()
        self.assertEqual(download_certificate_s3(self.rabbit.number), original)

    def test_run_attests_with_the_original_issuer_after_the_commit(self):
        result = self.invoke("--run")
        self.assertIn("Återutfärdade: 1", result.output, result.output)
        row = self.current_row()
        self.assertEqual((row.issued_by_id, row.issued_as), (self.owner.id, "breeder"))
        data = self.pedigree.call_args.args[0]
        self.assertTrue(data["replaces_v1"])
        self.assertEqual(" ".join(data["fullname"].split()), "Åsa Öberg")
        original = download_certificate_s3(self.rabbit.number)
        self.assertEqual(self.archived(), original)  # kept on the data volume
        self.assertEqual(self.s3_keys(), self.keys)  # nothing written to S3: the v1 file stays where it was
        self.assertIn("Återutfärdade: 0", self.invoke("--run").output)  # it has a current v2 row now

    def test_a_namesake_buyer_stops_the_rabbit(self):
        # The buyer shares the breeder's name: the v1 file cannot say which of them pressed "Uppdatera".
        db.User.update(fullname="Åsa Öberg").where(db.User.id == self.manager.id).execute()
        self.assert_stopped(reissue_cli.SEVERAL)

    def test_an_unknown_attester_stops_the_rabbit(self):
        self.rabbit = self.v1_rabbit(self.rabbit, 4711, IntygasAv="Någon Annan")
        self.assert_stopped(reissue_cli.NO_ACCOUNT)

    def test_an_inactive_attester_stops_the_rabbit(self):
        db.User.update(is_active=False).where(db.User.id == self.owner.id).execute()
        self.assert_stopped(reissue_cli.INACTIVE)

    def test_an_attester_without_the_right_stops_the_rabbit(self):
        db.User.update(fullname="Bo Köpare").where(db.User.id == self.manager.id).execute()
        self.rabbit = self.v1_rabbit(self.rabbit, 4711, IntygasAv="Bo Köpare")
        self.assert_stopped(reissue_cli.NO_RIGHT)

    def test_a_v1_certificate_made_in_another_herd_stops_the_rabbit(self):
        self.rabbit = self.v1_rabbit(self.rabbit, 4711, IntygasNummer="G2")
        self.assert_stopped(reissue_cli.OTHER_HERD)

    def test_an_empty_herd_in_the_v1_certificate_stops_the_rabbit(self):
        self.rabbit = self.v1_rabbit(self.rabbit, 4711, IntygasNummer="")
        self.assert_stopped(reissue_cli.OTHER_HERD)

    def test_a_pdf_of_another_certificate_stops_the_rabbit(self):
        self.rabbit = self.v1_rabbit(self.rabbit, 4711, Nummer="4712")
        self.assert_stopped(reissue_cli.OTHER_CERTIFICATE)

    def test_data_changed_since_v1_stops_the_rabbit(self):
        self.rabbit = self.v1_rabbit(self.rabbit, 4711, IdNamn="Ett annat namn")
        result = self.assert_stopped(reissue_cli.CHANGED)
        self.assertIn("ändrat fält IdNamn: 1", result.output)

    def test_a_number_changed_since_v1_is_reported_apart_and_can_be_allowed(self):
        self.rabbit = self.v1_rabbit(self.rabbit, 4711, IdÅrKullIndivid="2111")
        result = self.assert_stopped(reissue_cli.NUMBER_CHANGED)
        self.assertNotIn(reissue_cli.CHANGED + "\n", result.output)
        self.assertIn("ändrat fält IdÅrKullIndivid: 1", result.output)
        result = self.invoke("--run", "--tillat-nytt-nummer")
        self.assertIn("Återutfärdade: 1", result.output, result.output)
        self.assertEqual(self.pedigree.call_args.args[0]["genebank_aki"], self.rabbit.number.split("-")[1])  # today's

    def test_a_renumbered_father_counts_as_a_number_change_only_with_the_audit_log(self):
        father = self.rabbit.breeding.father
        herd, aki = father.number.split("-")
        self.rabbit = self.v1_rabbit(self.rabbit, 4711, FarÅrKullIndivid="1999")
        self.assert_stopped(reissue_cli.CHANGED, "--tillat-nytt-nummer")  # a littermate put in as father looks alike
        db.AuditLog.create(
            table_name="individual",
            record_id=str(father.id),
            operation="UPDATE",
            old_data={"number": f"{herd}-1999"},
            new_data={"number": f"{herd}-{aki}"},
        )
        self.assert_stopped(reissue_cli.NUMBER_CHANGED)
        self.assertIn("Återutfärdade: 1", self.invoke("--run", "--tillat-nytt-nummer").output)

    def test_fields_the_v1_certificate_never_had_are_left_empty_unless_asked(self):
        update = db.Individual.update(foot_ring="FGK 218", microchip="752098100012345", rex=True)
        update.where(db.Individual.id == self.rabbit.id).execute()
        self.assertIn("Återutfärdade: 1", self.invoke("--run").output)
        data = self.pedigree.call_args.args[0]
        self.assertEqual((data["foot_ring"], data["microchip"], data["rex"]), (None, None, None))
        rabbit = self.v1_rabbit(self.individuals[0], 4712)
        db.Individual.update(foot_ring="FGK 219").where(db.Individual.id == rabbit.id).execute()
        self.assertIn("Återutfärdade: 1", self.invoke("--run", "--ta-med-nya-falt").output)
        self.assertEqual(self.pedigree.call_args.args[0]["foot_ring"], "FGK 219")

    def test_a_number_and_another_field_changed_is_a_change(self):
        self.rabbit = self.v1_rabbit(self.rabbit, 4711, IdÅrKullIndivid="2111", IdNamn="Ett annat namn")
        self.assert_stopped(reissue_cli.CHANGED, "--tillat-nytt-nummer")

    def test_no_v1_pdf_stops_the_rabbit(self):
        rabbit = self.individuals[0]
        db.Individual.update(certificate=None, digital_certificate=4712).where(db.Individual.id == rabbit.id).execute()
        result = self.invoke("--run", "--number", rabbit.number)
        self.assertIn(f"{rabbit.number} (besättning G1): {reissue_cli.NO_PDF}", result.output, result.output)

    def test_a_paper_and_a_digital_number_stop_the_rabbit(self):
        db.Individual.update(certificate="99").where(db.Individual.id == self.rabbit.id).execute()
        self.assert_stopped(reissue_cli.STATE)

    def test_an_unreadable_pdf_does_not_stop_the_next_rabbit(self):
        upload_certificate(pdf_bytes=b"%PDF-1.4 trasig", ind_number=self.rabbit.number)
        other = self.v1_rabbit(self.individuals[0], 4712)
        result = self.invoke("--run")
        self.assertIn(f"{self.rabbit.number} (besättning G1): {reissue_cli.UNREADABLE}", result.output, result.output)
        self.assertIn("Återutfärdade: 1", result.output)
        self.assertIsNotNone(self.current_row(other))

    def test_a_failed_insert_keeps_the_v1_file_and_can_be_run_again(self):
        original = download_certificate_s3(self.rabbit.number)
        with patch.object(db.DigitalCertificateV2, "issue_current", side_effect=RuntimeError("insert")):
            result = self.invoke("--run")
        self.assertIn(f"{reissue_cli.FAILED}: RuntimeError", result.output, result.output)
        self.assertIsNone(self.current_row())
        self.assertEqual(download_certificate_s3(self.rabbit.number), original)
        self.assertIn("Återutfärdade: 1", self.invoke("--run").output)
        self.assertEqual(self.archived(), original)

    def test_a_failed_archive_write_leaves_nothing_and_can_be_run_again(self):
        with patch.object(reissue_cli.os, "fsync", side_effect=OSError("disk full")):
            result = self.invoke("--run")
        self.assertIn(f"{reissue_cli.FAILED}: OSError", result.output, result.output)
        self.assertEqual(os.listdir(self.archive), [])  # no half-written file under the final name
        self.assertIn("Återutfärdade: 1", self.invoke("--run").output)
        self.assertEqual(self.archived(), download_certificate_s3(self.rabbit.number))

    def test_another_archived_v1_file_stops_the_rabbit(self):
        with open(os.path.join(self.archive, "4711.pdf"), "wb") as other:
            other.write(b"%PDF-1.4 annan")
        self.assert_stopped(reissue_cli.ARCHIVED_OTHER)
        self.assertEqual(self.archived(), b"%PDF-1.4 annan")

    def test_an_unreachable_s3_stops_the_run(self):
        unreachable = EndpointConnectionError(endpoint_url="https://s3.example.invalid")
        with patch.object(reissue_cli, "download_certificate_s3", side_effect=unreachable):
            for args in ((), ("--run",)):
                result = self.invoke(*args)
                self.assertNotEqual(result.exit_code, 0, result.output)
                self.assertIn("S3 svarar inte som väntat", result.output)
        self.assertIsNone(self.current_row())

    def test_limit_counts_reissued_rabbits(self):
        upload_certificate(pdf_bytes=b"%PDF-1.4 trasig", ind_number=self.rabbit.number)  # stops, oldest first
        self.v1_rabbit(self.individuals[0], 4712)
        self.assertIn("Återutfärdade: 1", self.invoke("--run", "--limit", "1").output)
        self.assertEqual(self.invoke("--run", "--limit", "0").exit_code, 2)


@unittest.skipUnless(_USE_POSTGRES, "needs Postgres")
class UpdateReplacesV1Test(CertV2Mixin, FlaskTest):
    """PATCH /api/v2/certificates/update says it replaces a certificate only when that certificate was a v1."""

    def setUp(self):
        super().setUp()
        self.pedigree = MagicMock(return_value=V2)
        stubs = (
            patch.object(cert_service._generator, "generate_pedigree", self.pedigree),
            patch.object(cert_service, "sign_pdf", side_effect=lambda pdf, **kw: pdf),
            patch.object(cert_service, "write_durably"),
        )
        for stub in stubs:
            stub.start()
            self.addCleanup(stub.stop)

    def update(self, rabbit):
        response = self._request(self.owner, "patch", f"/api/v2/certificates/update/{rabbit.number}")
        self.assertEqual(response.status_code, 200, response.get_json())
        return self.pedigree.call_args.args[0]["replaces_v1"]

    def test_a_v1_certificate(self):
        rabbit = self.individuals[3]
        db.Individual.update(digital_certificate=4711).where(db.Individual.id == rabbit.id).execute()
        self.assertTrue(self.update(rabbit))

    def test_a_v2_reissue(self):
        rabbit = self.individuals[3]
        db.Individual.update(digital_certificate=4711).where(db.Individual.id == rabbit.id).execute()
        self.update(rabbit)
        self.assertFalse(self.update(rabbit))

    def test_paper_to_digital(self):
        self.assertFalse(self.update(self.individuals[0]))  # certificate="12", no digital number
