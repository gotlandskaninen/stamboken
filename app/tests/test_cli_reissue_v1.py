"""flask certificates reissue-v1: v1 certificates get a v2 certificate attested by the original issuer (#142)."""

import io
import unittest
from unittest.mock import MagicMock, mock_open, patch

import cli.certificates as reissue_cli
import utils.cert_service_v2 as cert_service
import utils.data_access as da
import utils.database as db
from herdbook import APP
from pdfrw import PdfArray, PdfDict, PdfName, PdfString, PdfWriter

from tests.database_test import _USE_POSTGRES
from tests.test_certificates_v2_api import CertV2Mixin
from tests.test_endpoints import FlaskTest


def v1_pdf(attester):
    """A PDF with the v1 form's IntygasAv field, encoded as utils/certificates.py fills it."""
    field = PdfDict(
        Type=PdfName.Annot,
        Subtype=PdfName.Widget,
        FT=PdfName.Tx,
        T=PdfString.encode("IntygasAv"),
        V=PdfString.encode(attester),
        Rect=PdfArray([0, 0, 100, 20]),
    )
    writer = PdfWriter()
    writer.addpage(PdfDict(Type=PdfName.Page, MediaBox=PdfArray([0, 0, 595, 842]), Annots=PdfArray([field])))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@unittest.skipUnless(_USE_POSTGRES, "needs Postgres")
class ReissueV1Test(CertV2Mixin, FlaskTest):
    def setUp(self):
        super().setUp()
        self.rabbit = self.individuals[3]  # origin herd G1, which the owner owns
        db.Individual.update(digital_certificate=4711).where(db.Individual.id == self.rabbit.id).execute()
        db.User.update(fullname="Åsa  Öberg").where(db.User.id == self.owner.id).execute()
        self.pedigree = MagicMock(return_value=b"%PDF-1.4 v2")
        self.s3 = MagicMock()
        stubs = (
            patch.object(cert_service._generator, "generate_pedigree", self.pedigree),
            patch.object(cert_service, "sign_pdf", side_effect=lambda pdf, **kw: pdf),
            patch.object(cert_service, "upload_certificate_v2"),
            patch.object(cert_service, "upload_certificate"),
            patch.object(cert_service, "open", mock_open(), create=True),
            patch.object(reissue_cli.s3, "get_s3_client", return_value=self.s3),
        )
        for stub in stubs:
            stub.start()
            self.addCleanup(stub.stop)

    def invoke(self, *args, pdf=None):
        source = {"side_effect": KeyError("NoSuchKey")} if pdf is None else {"return_value": pdf}
        with patch.object(reissue_cli, "download_certificate_s3", **source):
            return APP.test_cli_runner().invoke(args=["certificates", "reissue-v1", *args])

    def current_rows(self):
        return list(
            db.DigitalCertificateV2.select().where(
                (db.DigitalCertificateV2.individual == self.rabbit.id) & db.DigitalCertificateV2.is_current
            )
        )

    def test_dry_run_writes_nothing(self):
        result = self.invoke(pdf=v1_pdf("Åsa Öberg"))
        self.assertIn("Skulle återutfärdas: 1", result.output)
        self.assertEqual(self.current_rows(), [])
        self.pedigree.assert_not_called()
        self.s3.put_object.assert_not_called()

    def test_run_attests_with_the_original_issuer_and_keeps_the_v1_pdf(self):
        original = v1_pdf("Åsa Öberg")
        result = self.invoke("--run", pdf=original)
        self.assertIn("Återutfärdade: 1", result.output, result.output)
        (row,) = self.current_rows()
        self.assertEqual((row.issued_by_id, row.issued_as), (self.owner.id, "breeder"))
        data = self.pedigree.call_args.args[0]
        self.assertTrue(data["replaces_v1"])
        self.assertEqual(" ".join(data["fullname"].split()), "Åsa Öberg")
        copy = f"certifikat/v1/{self.rabbit.number}.pdf"
        self.s3.put_object.assert_called_once_with(file_name=copy, file_data=original)
        # Again: the rabbit has a current v2 row now and is not selected.
        self.assertIn("Återutfärdade: 0", self.invoke("--run", pdf=original).output)

    def test_an_unknown_attester_stops_the_rabbit(self):
        result = self.invoke("--run", pdf=v1_pdf("Någon Annan"))
        self.assertIn(f"{self.rabbit.number} (besättning G1): {reissue_cli.NO_ACCOUNT}", result.output)
        self.assertEqual(self.current_rows(), [])

    def test_an_attester_without_access_to_the_origin_herd_stops_the_rabbit(self):
        # The old app let a buyer press "Uppdatera": a name that matches an account outside the origin herd.
        db.User.update(fullname="Bo Köpare").where(db.User.id == self.manager.id).execute()
        result = self.invoke("--run", pdf=v1_pdf("Bo Köpare"))
        self.assertIn(reissue_cli.NO_ACCOUNT, result.output)
        self.assertEqual(self.current_rows(), [])

    def test_two_accounts_with_the_name_stop_the_rabbit(self):
        twin = da.register_user("tvilling", "pass")
        twin.add_role("owner", self.herds[0].id)
        db.User.update(fullname="Åsa Öberg").where(db.User.id == twin.id).execute()
        result = self.invoke("--run", pdf=v1_pdf("Åsa Öberg"))
        self.assertIn(reissue_cli.SEVERAL, result.output)
        self.assertEqual(self.current_rows(), [])

    def test_no_v1_pdf_stops_the_rabbit(self):
        result = self.invoke("--run")
        self.assertIn(reissue_cli.NO_PDF, result.output)
        self.assertEqual(self.current_rows(), [])

    def test_the_update_endpoint_says_it_replaces_a_v1_certificate(self):
        db.User.update(fullname="Test Namn").where(db.User.id == self.owner.id).execute()
        response = self._request(self.owner, "patch", f"/api/v2/certificates/update/{self.rabbit.number}")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(self.pedigree.call_args.args[0]["replaces_v1"])
