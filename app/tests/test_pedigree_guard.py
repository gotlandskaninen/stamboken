"""No parent change may make an animal its own ancestor."""

import io
import re
import threading
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import utils.data_access as da
import utils.database as db
from utils.certificates_v2 import SigningUnavailableError
from utils.pedigree_guard import CYCLE_MESSAGE, pedigree_cycle_error

from tests.database_test import _USE_POSTGRES, DatabaseTest
from tests.ht_helpers import make_individual
from tests.test_endpoints import FlaskTest


class PedigreeFixture:
    """m0 x f0 -> A; A x f1 -> B; B x f2 -> C (each founder alone in a parentless litter)."""

    def setUp(self):
        super().setUp()
        h = self.herds[0]
        self.m0 = make_individual(h, "G1-M0", date(2020, 1, 1), sex="male")
        self.f0 = make_individual(h, "G1-F0", date(2020, 1, 1), sex="female")
        self.f1 = make_individual(h, "G1-F1", date(2020, 1, 1), sex="female")
        self.f2 = make_individual(h, "G1-F2", date(2020, 1, 1), sex="female")
        self.a = self._kid("G1-A", self.m0, self.f0, date(2022, 1, 1))
        self.b = self._kid("G1-B", self.a, self.f1, date(2023, 1, 1))
        self.c = self._kid("G1-C", self.b, self.f2, date(2024, 1, 1))

    def _litter(self, father, mother, birth):
        return db.Breeding.create(
            breeding_herd_id=self.herds[0], father=father, mother=mother, birth_date=birth, litter_size=1
        )

    def _kid(self, number, father, mother, birth):
        return db.Individual.create(
            origin_herd=self.herds[0],
            number=number,
            sex="male",
            breeding=self._litter(father, mother, birth),
            certificate=f"C-{number}",
        )

    def _father_of(self, individual):
        return db.Breeding.get_by_id(db.Individual.get_by_id(individual.id).breeding_id).father_id


class TestPedigreeGuard(PedigreeFixture, DatabaseTest):
    def test_descendant_as_parent_is_refused(self):
        self.assertEqual(pedigree_cycle_error([self.a.id], self.c.id, None), CYCLE_MESSAGE)
        self.assertEqual(pedigree_cycle_error([self.a.id], None, self.c.id), CYCLE_MESSAGE)
        self.assertEqual(pedigree_cycle_error([self.a.id], self.a.id, None), CYCLE_MESSAGE)
        self.assertIsNone(pedigree_cycle_error([self.c.id], self.m0.id, self.f0.id))
        self.assertIsNone(pedigree_cycle_error([self.a.id], None, None))
        self.assertIsNone(pedigree_cycle_error([], self.c.id, None))

    def test_terminates_on_an_existing_cycle(self):
        # Raw write: A's litter gets C as father, so the stored pedigree already loops.
        db.Breeding.update(father=self.c).where(db.Breeding.id == self.a.breeding_id).execute()
        self.assertEqual(pedigree_cycle_error([self.b.id], self.a.id, None), CYCLE_MESSAGE)
        self.assertIsNone(pedigree_cycle_error([self.m0.id], self.f1.id, None))

    def test_update_breeding_refuses_with_409(self):
        """B's litter gets C (B's son) as father."""
        result = da.update_breeding({"id": self.b.breeding_id, "father": self.c.number}, self.admin.uuid)
        self.assertEqual((result["status"], result.get("problem_status")), ("error", 409), result)
        self.assertEqual(result["message"], CYCLE_MESSAGE)
        self.assertEqual(self._father_of(self.b), self.a.id)

    def test_valid_parent_change_passes(self):
        """Precondition for the refusal above: the same kind of edit goes through when acyclic."""
        result = da.update_breeding({"id": self.c.breeding_id, "father": self.m0.number}, self.admin.uuid)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(self._father_of(self.c), self.m0.id)

    def test_moving_an_animal_into_a_descendants_litter_is_refused(self):
        c_litter = self._litter(self.c, self.f2, date(2022, 1, 1))
        form = da.get_individual(self.a.number, self.admin.uuid)
        form["breeding"] = c_litter.id
        result = da.update_individual(form, self.admin.uuid)
        self.assertEqual((result["status"], result.get("problem_status")), ("error", 409), result)
        self.assertEqual(result["message"], CYCLE_MESSAGE)
        self.assertEqual(db.Individual.get_by_id(self.a.id).breeding_id, self.a.breeding_id)

    def test_valid_litter_move_passes(self):
        """Precondition: moving into an unrelated litter with the same birth date succeeds."""
        other = self._litter(self.m0, self.f1, date(2022, 1, 1))
        form = da.get_individual(self.a.number, self.admin.uuid)
        form["breeding"] = other.id
        result = da.update_individual(form, self.admin.uuid)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(db.Individual.get_by_id(self.a.id).breeding_id, other.id)

    def test_every_parentage_writer_calls_the_guard(self):
        """Inventory: functions that change existing parentage call the guard.

        A write is an attribute assignment of father/mother/breeding(_id), form_to_individual's
        generic setattr, a Breeding/Individual bulk update touching the litter, or a raw UPDATE.
        Creations (Breeding/Individual create) are not listed: a new litter has no kits and a new
        animal no descendants, so neither can close a cycle.
        """
        src = Path(da.__file__).read_text()
        guarded = {"update_breeding", "revert_audit_entry", "restore_record"}
        for fn in guarded:
            body = src.split(f"def {fn}(", 1)[1].split("\ndef ", 1)[0]
            self.assertTrue("pedigree_cycle_error" in body, fn)
        writes = re.compile(
            r"\.(father|mother|breeding)(_id)?\s*=(?!=)"
            r"|setattr\(individual,"
            r"|\bBreeding\.update\("
            r"|\bIndividual(Model)?\.update\(.*breeding"
            r'|UPDATE "?(\{table_name\}|breeding\b|individual\b)'
        )
        # form_to_individual builds add_individual's new animal; update_individual's litter move is
        # MoveToLitter's, checked with the commands below.
        creators = {"form_to_individual"}
        for chunk in src.split("\ndef ")[1:]:
            name = chunk.split("(", 1)[0]
            if writes.search(chunk):
                self.assertIn(name, guarded | creators, f"{name} writes parentage without the guard")
        # The write commands: one that writes parentage asks the guard itself (MoveToLitter, in CYCLE).
        commands = Path(da.__file__).with_name("individual_commands.py").read_text()
        for chunk in re.split(r"\n(?=class |def )", commands):
            if writes.search(chunk):
                self.assertIn("pedigree_cycle_error", chunk, chunk.split("(", 1)[0])
        # Other files whose hits are not parentage changes: database.py (migration backfills of
        # updated_at/litter_number), individual_number_v2.py (Breeding.update of litter_number),
        # pedigree_guard.py (a read-only join in the ancestor query), cli/breeding.py (a read-only
        # join in check-collisions).
        allowed = {
            "data_access.py",
            "individual_commands.py",
            "database.py",
            "individual_number_v2.py",
            "pedigree_guard.py",
            "cli/breeding.py",
        }
        app_dir = Path(da.__file__).parents[1]
        offenders = sorted(
            str(p.relative_to(app_dir))
            for p in app_dir.rglob("*.py")
            if "tests" not in p.parts
            and not {p.name, str(p.relative_to(app_dir))} & allowed
            and writes.search(p.read_text())
        )
        self.assertEqual(offenders, [])


class TestAuditRevertGuard(PedigreeFixture, DatabaseTest):
    def _audit_update(self, table, record_id, **old):
        """An UPDATE audit entry whose old_data is the stored row with `old` swapped in."""
        pk = db.AUDITED_TABLES[table][0]
        row = db.DATABASE.execute_sql(
            f'SELECT row_to_json(t) FROM "{table}" t WHERE "{pk}" = %s', (record_id,)
        ).fetchone()[0]
        return db.AuditLog.create(
            table_name=table,
            record_id=str(record_id),
            operation="UPDATE",
            old_data={**row, **old},
            new_data=row,
            changed_fields=list(old),
        )

    def test_audit_revert_and_restore_cannot_create_a_cycle(self):
        entry = self._audit_update("breeding", self.b.breeding_id, father_id=self.c.id)
        self.assertEqual(
            da.revert_audit_entry(entry.id, fields=["father_id"]),
            ({"status": "error", "message": CYCLE_MESSAGE}, 409),
        )
        self.assertEqual(
            da.restore_record("breeding", self.b.breeding_id, entry.id),
            ({"status": "error", "message": CYCLE_MESSAGE}, 409),
        )
        self.assertEqual(self._father_of(self.b), self.a.id)

    def test_audit_revert_cannot_move_an_animal_into_a_descendants_litter(self):
        """breeding_id is not an audit-undo column: update_individual moves an animal between
        litters, with the cycle check and the BIRTH rows. Revert refuses it, restore skips it."""
        c_litter = self._litter(self.c, self.f2, date(2025, 1, 1))
        entry = self._audit_update("individual", self.a.id, breeding_id=c_litter.id)
        for result, status in (
            (da.revert_audit_entry(entry.id, fields=["breeding_id"]), 409),
            (da.restore_record("individual", self.a.id, entry.id), 200),
        ):
            self.assertEqual(result[1], status)
            self.assertIn("breeding_id", result[0]["message"])
        self.assertEqual(db.Individual.get_by_id(self.a.id).breeding_id, self.a.breeding_id)

    def test_acyclic_audit_revert_still_works(self):
        entry = self._audit_update("breeding", self.c.breeding_id, father_id=self.m0.id)
        self.assertEqual(da.revert_audit_entry(entry.id, fields=["father_id"])[1], 200)
        self.assertEqual(self._father_of(self.c), self.m0.id)

    def test_audit_revert_and_restore_cannot_restore_a_voided_parent(self):
        """C's litter once had F9 as mother; F9 was unpromoted (voided) since. Undo must not bring her back."""
        f9 = make_individual(self.herds[0], "G1-F9", date(2020, 1, 1), sex="female")
        db.Individual.update(voided=True).where(db.Individual.id == f9.id).execute()
        entry = self._audit_update("breeding", self.c.breeding_id, mother_id=f9.id)
        results = [
            da.revert_audit_entry(entry.id, fields=["mother_id"]),
            da.restore_record("breeding", self.c.breeding_id, entry.id),
        ]
        mother = db.Breeding.get_by_id(self.c.breeding_id).mother_id
        self.assertEqual(mother, self.f2.id, f"{results}: the litter names the voided F9 again")
        self.assertEqual([status for _, status in results], [409, 409])

    @unittest.skipUnless(_USE_POSTGRES, "row locks need PostgreSQL")
    def test_revert_and_update_breeding_on_the_same_litter_serialise(self):
        """Both lock the litter first: both finish, no deadlock, and the result is acyclic."""
        entry = self._audit_update("breeding", self.b.breeding_id, father_id=self.c.id)
        litter_id, admin_uuid, m0_number = self.b.breeding_id, self.admin.uuid, self.m0.number
        barrier = threading.Barrier(2)
        results, failures = [None, None], []

        def run(index, fn):
            try:
                barrier.wait(timeout=10)
                results[index] = fn()
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(exc)
            finally:
                try:
                    db.DB_PROXY.close()
                except Exception:  # pylint: disable=broad-except
                    pass

        workers = [
            lambda: da.revert_audit_entry(entry.id, fields=["father_id"]),
            lambda: da.update_breeding({"id": litter_id, "father": m0_number}, admin_uuid),
        ]
        threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        for thread in threads:
            self.assertFalse(thread.is_alive(), "a worker is still blocked — lock never released")
        self.assertEqual(failures, [])
        self.assertEqual(results[0], ({"status": "error", "message": CYCLE_MESSAGE}, 409))
        self.assertEqual(results[1]["status"], "success", results[1])
        father = self._father_of(self.b)
        self.assertEqual(father, self.m0.id)
        self.assertIsNone(pedigree_cycle_error([self.b.id], father, self.f1.id))


class TestPedigreeGuardV2Routes(PedigreeFixture, FlaskTest):
    def _login(self, context):
        context.post("/api/login", json={"username": self.admin.email, "password": "pass"})

    def test_patch_breeding_with_a_descendant_as_father_is_409(self):
        with self.app as context:
            self._login(context)
            response = context.patch(f"/api/v2/breeding/{self.b.breeding_id}", json={"father": self.c.number})
        self.assertEqual(response.status_code, 409, response.get_json())
        self.assertEqual(response.headers["Content-Type"], "application/problem+json")
        self.assertEqual(response.get_json()["detail"], CYCLE_MESSAGE)
        self.assertEqual(self._father_of(self.b), self.a.id)

    def test_certificate_update_ignores_a_body_litter(self):
        """A body `breeding` reaches neither the write nor the PDF: certificate routes never move a rabbit."""
        c_litter = self._litter(self.c, self.f2, date(2025, 1, 1))
        # Signing unavailable: the route stops in generate_and_store and rolls back, so no S3 is needed.
        with patch("blueprints.certificates.generate_and_store", side_effect=SigningUnavailableError) as generate:
            with self.app as context:
                self._login(context)
                response = context.patch(f"/api/v2/certificates/update/{self.a.number}", json={"breeding": c_litter.id})
        self.assertEqual(response.status_code, 503, response.get_json())
        self.assertEqual(generate.call_args.args[2]["breeding"], self.a.breeding_id, "rendered from the stored litter")
        individual = db.Individual.get_by_id(self.a.id)
        self.assertEqual(individual.breeding_id, self.a.breeding_id)
        self.assertIsNone(individual.digital_certificate)


# The stored litter sizes: the legacy routes call update_breeding whenever the form's differ.
SIZES = {"litter_size": 1, "litter_size6w": None}


class TestPedigreeGuardLegacyCertificateRoutes(PedigreeFixture, FlaskTest):
    """A body litter is ignored: the legacy certificate routes never move a rabbit."""

    def setUp(self):
        super().setUp()
        self.c_litter = self._litter(self.c, self.f2, date(2025, 1, 1))
        patches = {
            "present": patch("herdbook.check_certificate_s3", return_value=True),
            "sign": patch("herdbook.sign_data", side_effect=lambda pdf: io.BytesIO(b"%PDF-fake")),
            "upload": patch("herdbook.upload_certificate", return_value=True),
        }
        self.mocks = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    def _request(self, method, url, body):
        with self.app as context:
            context.post("/api/login", json={"username": self.admin.email, "password": "pass"})
            return context.open(url, method=method, json=body)

    def _assert_signed_in_place(self, response):
        self.assertEqual(response.status_code, 200, response.data[:200])
        self.mocks["sign"].assert_called_once()
        self.mocks["upload"].assert_called_once()
        self.assertEqual(db.Individual.get_by_id(self.a.id).breeding_id, self.a.breeding_id)

    def _digital(self):
        db.Individual.update(certificate=None, digital_certificate=100500).where(
            db.Individual.id == self.a.id
        ).execute()

    def test_update_certificate_ignores_a_body_litter(self):
        self._digital()
        body = {"breeding": self.c_litter.id, **SIZES}
        self._assert_signed_in_place(self._request("PATCH", f"/api/certificates/update/{self.a.number}", body))

    def test_update_certificate_without_a_litter_change_still_signs(self):
        self._digital()
        response = self._request("PATCH", f"/api/certificates/update/{self.a.number}", {"name": "Ny", **SIZES})
        self.assertEqual(response.status_code, 200, response.data[:200])
        self.mocks["sign"].assert_called_once()
        self.mocks["upload"].assert_called_once()

    def test_issue_certificate_ignores_a_body_litter(self):
        db.Individual.update(certificate=None).where(db.Individual.id == self.a.id).execute()
        body = {"breeding": self.c_litter.id, **SIZES}
        self._assert_signed_in_place(self._request("POST", f"/api/certificates/issue/{self.a.number}", body))

    def test_issue_certificate_without_a_litter_change_still_signs(self):
        db.Individual.update(certificate=None).where(db.Individual.id == self.a.id).execute()
        body = dict(SIZES)
        response = self._request("POST", f"/api/certificates/issue/{self.a.number}", body)
        self.assertEqual(response.status_code, 200, response.data[:200])
        self.mocks["sign"].assert_called_once()
        self.mocks["upload"].assert_called_once()
