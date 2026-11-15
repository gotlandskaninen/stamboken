"""The colour number (its id, the atlas number) reaches the individual response and the certificate."""

from utils import database as db
from utils.cert_service_v2 import build_cert_data

from tests.database_test import DatabaseTest


class TestColorNumberInResponseAndCertificate(DatabaseTest):
    def _cert_code(self, individual):
        individual.sex = "female"  # the fixture rabbits have none, which the certificate data needs
        individual.save()
        return build_cert_data(individual, individual.as_dict(), self.admin.uuid)["color_code"]

    def test_individ_har_color_id(self):
        ind = self.individuals[3]
        ind.color = self.colors[1]
        ind.save()
        self.assertEqual(ind.as_dict()["color_id"], self.colors[1].id)
        self.assertEqual(ind.as_dict()["color"], "stgröhn")

    def test_color_id_ar_null_utan_farg(self):
        ind = self.individuals[3]
        ind.color = None
        ind.save()
        self.assertIsNone(ind.as_dict()["color_id"])

    def test_color_code_ar_farg_id(self):
        color = db.Color.create(id=22, name="Viltgrå", genebank=self.genebanks[0])
        ind = self.individuals[3]
        ind.color = color
        ind.save()
        self.assertEqual(self._cert_code(ind), "22")

    def test_color_code_mellerud_albino(self):
        color = db.Color.create(id=101, name="Albino", genebank=self.genebanks[1])
        ind = self.individuals[2]  # in M3
        ind.color = color
        ind.save()
        self.assertEqual(self._cert_code(ind), "101")

    def test_color_code_tom_utan_farg(self):
        ind = self.individuals[3]
        ind.color = None
        ind.save()
        self.assertEqual(self._cert_code(ind), "")

    def test_color_code_tom_for_annan_genbanks_farg(self):
        ind = self.individuals[2]  # in M3, Mellerud
        ind.color = self.colors[0]  # Gotland's
        ind.save()
        self.assertEqual(self._cert_code(ind), "")
