"""Every path that changes Individual.number takes the v1 certificate (S3) and the photo along.

Paths: renumber and litter-number (v2), a legacy rename, a v2 litter move across years (inside the route's
own transaction), and breeding edits that change the kits' herd or birth year. Each runs once with an
injected failure right after the commit's first asset operation: the new numbers stay, and every asset
is still at its staging name ``~<new>``. A failure while staging rolls the whole change back.

isort:skip_file
"""

import logging
import os
import shutil
import tempfile
import threading
from contextlib import contextmanager
from datetime import date
from unittest import mock

os.environ.setdefault("AUTHCONFIGFILE", os.path.join(os.path.dirname(__file__), "auth.ini.test"))

import utils.data_access as da  # noqa: E402
import utils.database as db  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402
from herdbook import APP, limiter  # noqa: E402

from tests.database_test import DatabaseTest  # noqa: E402
from tests.ht_helpers import ht_row  # noqa: E402

PHOTO_SUFFIXES = (".jpg", "_thumb.jpg")


class FakeS3:
    """In-memory stand-in for utils.s3.S3Handler; the `fail_at`:th write (copy or delete) raises."""

    def __init__(self, objects, fail_at=None):
        self.objects, self.fail_at, self.writes = objects, fail_at, 0

    def _write(self):
        self.writes += 1
        if self.writes == self.fail_at:
            raise ConnectionError("injected S3 failure")

    def copy_object(self, old_object_name, object_name):
        self._write()
        if old_object_name not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "CopyObject")
        self.objects[object_name] = self.objects[old_object_name]
        return True

    def delete_object(self, bucket_object_name):
        self._write()
        self.objects.pop(bucket_object_name, None)
        return True


@contextmanager
def _logged_errors():
    records = []
    handler = logging.Handler(logging.ERROR)
    handler.emit = records.append
    logging.getLogger().addHandler(handler)
    try:
        yield records
    finally:
        logging.getLogger().removeHandler(handler)


class TestNumberChangeMovesAssets(DatabaseTest):
    def setUp(self):
        # nosemgrep: python.flask.security.audit.hardcoded-config.avoid_hardcoded_config_TESTING
        APP.config["TESTING"] = True
        limiter.enabled = False
        self.client = APP.test_client(use_cookies=True)
        self._upload_dir = tempfile.mkdtemp()
        self._old_upload = os.environ.get("UPLOAD_FOLDER")
        os.environ["UPLOAD_FOLDER"] = self._upload_dir
        super().setUp()
        self.kaniner = os.path.join(self._upload_dir, "kaniner")
        os.makedirs(self.kaniner)
        for herd in self.herds:
            herd.is_active = True
            herd.save()
        self.g1 = self.herds[0]
        # Litter 1 is born AFTER litter 2, so a renumber swaps them.
        self.litter = self._litter(date(2026, 3, 1), 1)
        self.other = self._litter(date(2026, 2, 1), 2)
        self.objects = {}
        kits = (("G1-2611", self.litter), ("G1-2612", self.litter), ("G1-2621", self.other))
        for i, (number, litter) in enumerate(kits):
            kit = db.Individual.create(
                number=number,
                origin_herd=self.g1,
                breeding=litter,
                sex="female",
                digital_certificate=100001 + i,
                has_photo=True,
            )
            ht_row("BIRTH", individual=kit, herd=self.g1, herd_tracking_date=litter.birth_date)
            self.objects[f"{number}/certificate.pdf"] = f"cert-of-{number}".encode()
            for suffix in PHOTO_SUFFIXES:
                with open(os.path.join(self.kaniner, number + suffix), "wb") as f:
                    f.write(f"photo{suffix}-of-{number}".encode())
        self.client.post("/api/login", json={"username": "admin", "password": "pass"})

    def tearDown(self):
        shutil.rmtree(self._upload_dir, ignore_errors=True)
        if self._old_upload is None:
            os.environ.pop("UPLOAD_FOLDER", None)
        else:
            os.environ["UPLOAD_FOLDER"] = self._old_upload
        super().tearDown()

    def _litter(self, birth, litter_number=None):
        return db.Breeding.create(
            breeding_herd_id=self.g1,
            mother=self.parents[0],
            father=self.parents[1],
            birth_date=birth,
            litter_number=litter_number,
            litter_size=2,
        )

    # --- the number-changing paths: each returns (response, {old number: new number}) ---

    def _renumber(self):
        response = self.client.post("/api/v2/breeding/renumber", json={"herd_id": "G1", "year": 2026, "confirm": True})
        return response, {"G1-2611": "G1-2621", "G1-2612": "G1-2622", "G1-2621": "G1-2611"}

    def _litter_number(self):
        response = self.client.patch(f"/api/v2/breeding/{self.litter.id}/litter-number", json={"litter_number": 5})
        return response, {"G1-2611": "G1-2651", "G1-2612": "G1-2652"}

    def _legacy_rename(self):
        kit = db.Individual.get(db.Individual.number == "G1-2621")
        response = self.client.patch("/api/individual", json={"id": kit.id, "number": "G1-2629", "herd": "G1"})
        return response, {"G1-2621": "G1-2629"}

    def _legacy_rename_and_litter_move(self):
        # Two number changes in one transaction: the rename to G1-2629, then the birth-year fix to G1-2529.
        older = self._litter(date(2025, 6, 1))
        kit = db.Individual.get(db.Individual.number == "G1-2621")
        response = self.client.patch(
            "/api/individual", json={"id": kit.id, "number": "G1-2629", "herd": "G1", "breeding": older.id}
        )
        return response, {"G1-2621": "G1-2529"}

    def _v2_litter_move(self):
        older = self._litter(date(2025, 6, 1))
        response = self.client.patch("/api/individual/G1-2621", json={"breeding": older.id})
        return response, {"G1-2621": "G1-2521"}

    def _breeding_herd(self):
        response = self.client.patch(f"/api/v2/breeding/{self.litter.id}", json={"breeding_herd": "G2"})
        return response, {"G1-2611": "G2-2611", "G1-2612": "G2-2612"}

    def _legacy_birth_year(self):
        response = self.client.patch("/api/breeding", json={"id": self.litter.id, "birth_date": "2025-03-01"})
        return response, {"G1-2611": "G1-2511", "G1-2612": "G1-2512"}

    # --- checks ---

    def _cert(self, number):
        return self.objects.get(f"{number}/certificate.pdf")

    def _photo(self, name):
        path = os.path.join(self.kaniner, name)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return f.read()

    def _run(self, path, fail_at=None):
        with mock.patch("utils.s3.get_s3_client", return_value=FakeS3(self.objects, fail_at)):
            response, moves = path()
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertNotEqual((response.get_json() or {}).get("status"), "error", response.get_json())
        numbers = {n for (n,) in db.Individual.select(db.Individual.number).tuples()}
        self.assertTrue(set(moves.values()) <= numbers, f"new numbers committed: {sorted(numbers)}")
        return moves

    def _assert_moved(self, moves):
        for old, new in moves.items():
            self.assertEqual(self._cert(new), f"cert-of-{old}".encode(), f"certificate of {old} at {new}")
            for suffix in PHOTO_SUFFIXES:
                self.assertEqual(self._photo(new + suffix), f"photo{suffix}-of-{old}".encode(), f"{new}{suffix}")
        for old in set(moves) - set(moves.values()):
            self.assertIsNone(self._cert(old), f"old certificate key {old} removed")
            self.assertIsNone(self._photo(old + ".jpg"), f"old photo {old}.jpg removed")
        self._assert_no_staging()

    def _assert_no_staging(self):
        self.assertEqual([k for k in self.objects if k.startswith("~")], [], "no staging keys left")
        self.assertEqual([f for f in os.listdir(self.kaniner) if f.startswith("~")], [], "no staging files left")

    def _assert_recoverable(self, moves, errors):
        for old, new in moves.items():
            self.assertEqual(self._cert("~" + new), f"cert-of-{old}".encode(), f"staged certificate of {old}")
            for suffix in PHOTO_SUFFIXES:
                self.assertEqual(self._photo("~" + new + suffix), f"photo{suffix}-of-{old}".encode())
        self.assertTrue(errors, "the unfinished move is logged as an ERROR")
        self.assertIn("Left to do", errors[0].getMessage())

    def _assert_failure_after_commit_is_recoverable(self, path, staged):
        # `staged` S3 copies run inside the transaction (one per certified kit); the next write is the
        # first asset operation after the commit.
        with _logged_errors() as errors:
            moves = self._run(path, fail_at=staged + 1)
        self._assert_recoverable(moves, errors)

    def _assert_staging_failure_rolls_back(self, path, status):
        before = {n for (n,) in db.Individual.select(db.Individual.number).tuples()}
        snapshot = dict(self.objects)
        with mock.patch("utils.s3.get_s3_client", return_value=FakeS3(self.objects, fail_at=2)):
            response, _ = path()
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        if status == 200:
            self.assertEqual(response.get_json()["status"], "error", response.get_json())
        self.assertEqual({n for (n,) in db.Individual.select(db.Individual.number).tuples()}, before)
        self.assertEqual(self.objects, snapshot, "originals untouched, staging removed")
        self._assert_no_staging()

    # --- paths not covered by the renumber repros in test_breeding_v2_api ---

    def test_legacy_rename_moves_certificate_and_photo(self):
        self._assert_moved(self._run(self._legacy_rename))

    def test_legacy_rename_with_birth_year_fix_moves_assets_from_the_original_number(self):
        self._assert_moved(self._run(self._legacy_rename_and_litter_move))

    def test_v2_litter_move_across_years_moves_assets_after_the_routes_commit(self):
        self._assert_moved(self._run(self._v2_litter_move))

    def test_breeding_herd_change_moves_every_kits_assets(self):
        self._assert_moved(self._run(self._breeding_herd))

    def test_legacy_birth_year_change_moves_every_kits_assets(self):
        self._assert_moved(self._run(self._legacy_birth_year))

    # --- injected failure after the first asset operation of the commit ---

    def test_renumber_swap_failure_after_commit_is_recoverable(self):
        self._assert_failure_after_commit_is_recoverable(self._renumber, staged=3)

    def test_litter_number_failure_after_commit_is_recoverable(self):
        self._assert_failure_after_commit_is_recoverable(self._litter_number, staged=2)

    def test_legacy_rename_failure_after_commit_is_recoverable(self):
        self._assert_failure_after_commit_is_recoverable(self._legacy_rename, staged=1)

    def test_v2_litter_move_failure_after_commit_is_recoverable(self):
        self._assert_failure_after_commit_is_recoverable(self._v2_litter_move, staged=1)

    def test_breeding_herd_failure_after_commit_is_recoverable(self):
        self._assert_failure_after_commit_is_recoverable(self._breeding_herd, staged=2)

    def test_legacy_birth_year_failure_after_commit_is_recoverable(self):
        self._assert_failure_after_commit_is_recoverable(self._legacy_birth_year, staged=2)

    def test_photo_move_failure_after_commit_is_recoverable(self):
        db.Individual.update(digital_certificate=None).execute()
        real_replace = os.replace

        def replace(src, dst):
            if os.path.dirname(src) == self.kaniner:
                raise OSError("injected disk failure")
            return real_replace(src, dst)

        with _logged_errors() as errors, mock.patch("os.replace", side_effect=replace):
            moves = self._run(self._renumber)
        for old, new in moves.items():
            for suffix in PHOTO_SUFFIXES:
                self.assertEqual(self._photo("~" + new + suffix), f"photo{suffix}-of-{old}".encode())
        self.assertTrue(errors, "the unfinished move is logged as an ERROR")

    def test_renumber_swap_failure_midway_is_recoverable(self):
        # The first S3 copy after the commit succeeds (with that kit's photos), the second fails.
        with _logged_errors() as errors:
            moves = self._run(self._renumber, fail_at=5)
        for old, new in moves.items():
            self.assertIn(f"cert-of-{old}".encode(), (self._cert("~" + new), self._cert(new)), f"certificate of {old}")
            for suffix in PHOTO_SUFFIXES:
                self.assertIn(
                    f"photo{suffix}-of-{old}".encode(), (self._photo("~" + new + suffix), self._photo(new + suffix))
                )
        self.assertTrue(errors, "the unfinished move is logged as an ERROR")

    # --- injected failure right after the first staging copy: nothing changes ---

    def test_renumber_staging_failure_rolls_back_with_503(self):
        self._assert_staging_failure_rolls_back(self._renumber, 503)

    def test_litter_number_staging_failure_rolls_back_with_503(self):
        self._assert_staging_failure_rolls_back(self._litter_number, 503)

    def test_breeding_herd_staging_failure_rolls_back(self):
        self._assert_staging_failure_rolls_back(self._breeding_herd, 400)

    def test_legacy_birth_year_staging_failure_keeps_the_200_error_envelope(self):
        self._assert_staging_failure_rolls_back(self._legacy_birth_year, 200)

    def test_rollback_of_the_routes_transaction_after_staging_leaves_nothing_behind(self):
        """Guard (passes on develop too, which never stages): the route's own transaction rolls back after
        update_individual staged the photo; teardown_request removes the staging copies."""
        db.Individual.update(digital_certificate=None).where(db.Individual.number == "G1-2621").execute()
        del self.objects["G1-2621/certificate.pdf"]
        older = self._litter(date(2025, 6, 1))
        with (
            mock.patch("utils.s3.get_s3_client", return_value=FakeS3(self.objects)),
            mock.patch("blueprints.certificates.update_breeding_if_changed", side_effect=RuntimeError("late failure")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post("/api/v2/certificates/issue/G1-2621", json={"breeding": older.id})
        self.assertTrue(db.Individual.select().where(db.Individual.number == "G1-2621").exists())
        self.assertEqual(self._photo("G1-2621.jpg"), b"photo.jpg-of-G1-2621")
        self._assert_no_staging()

    def test_photo_kinds_are_owned_separately_in_a_swap(self):
        """A kit with only a full image and one with only a thumbnail swap numbers."""
        db.Individual.update(digital_certificate=None).execute()
        os.remove(os.path.join(self.kaniner, "G1-2611_thumb.jpg"))
        os.remove(os.path.join(self.kaniner, "G1-2621.jpg"))
        self._run(self._renumber)
        self.assertEqual(self._photo("G1-2621.jpg"), b"photo.jpg-of-G1-2611")
        self.assertIsNone(self._photo("G1-2621_thumb.jpg"), "G1-2611 had no thumbnail; G1-2621's must not stay")
        self.assertEqual(self._photo("G1-2611_thumb.jpg"), b"photo_thumb.jpg-of-G1-2621")
        self.assertIsNone(self._photo("G1-2611.jpg"), "G1-2621 had no full image; G1-2611's must not stay")
        self._assert_no_staging()

    def test_second_rename_waits_until_the_first_ones_files_are_in_place(self):
        """Renaming the same rabbit again right after a rename must not copy the still-empty
        intermediate number while the first rename is moving its files."""
        kit = db.Individual.get(db.Individual.number == "G1-2621")
        fake = FakeS3(self.objects)
        entered, release = threading.Event(), threading.Event()
        real_copy = fake.copy_object

        def copy_object(old_object_name, object_name):
            if object_name == "G1-2629/certificate.pdf" and not entered.is_set():  # the first rename's publication
                entered.set()
                release.wait(10)
            return real_copy(old_object_name=old_object_name, object_name=object_name)

        fake.copy_object = copy_object
        errors = []

        def rename(number):
            try:
                db.DATABASE.connect(reuse_if_open=True)
                result = da.update_individual({"id": kit.id, "number": number, "herd": "G1"}, self.admin.uuid)
                if result["status"] != "success":
                    errors.append(result)
            except Exception as exc:  # noqa: BLE001 — surfaced below
                errors.append(repr(exc))
            finally:
                db.DATABASE.close()

        with mock.patch("utils.s3.get_s3_client", return_value=fake):
            first = threading.Thread(target=rename, args=("G1-2629",), daemon=True)
            first.start()
            self.assertTrue(entered.wait(10), "the first rename reached its publication")
            second = threading.Thread(target=rename, args=("G1-2639",), daemon=True)
            second.start()
            second.join(1)  # without the number lock it is done by now, having found nothing at G1-2629
            release.set()
            first.join(10)
            second.join(10)
        self.assertEqual(errors, [])
        self.assertEqual(db.Individual.get_by_id(kit.id).number, "G1-2639")
        self._assert_moved({"G1-2621": "G1-2639"})
        self.assertIsNone(self._cert("G1-2629"))
        self.assertIsNone(self._photo("G1-2629.jpg"))

    def test_a_failed_unlock_closes_the_connection_so_no_number_stays_locked(self):
        """Guard for the number locks (develop has none, so it passes there too)."""
        real = db.DATABASE.execute_sql

        def execute_sql(sql, *args, **kwargs):
            if "pg_advisory_unlock" in sql:
                raise RuntimeError("injected unlock failure")
            return real(sql, *args, **kwargs)

        with (
            mock.patch("utils.s3.get_s3_client", return_value=FakeS3(self.objects)),
            mock.patch.object(db.DATABASE, "execute_sql", side_effect=execute_sql),
        ):
            response, _ = self._legacy_rename()
        self.assertEqual(response.get_json()["status"], "success", response.get_json())
        # pg_locks is cluster-wide; other xdist workers' databases hold their own number locks.
        held = db.DATABASE.execute_sql(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = %s"
            " AND database = (SELECT oid FROM pg_database WHERE datname = current_database())",
            (0x48424E52,),
        ).fetchone()[0]
        self.assertEqual(held, 0, "number locks still held after a failed unlock")

    def test_missing_certificate_object_does_not_block_a_renumber(self):
        del self.objects["G1-2621/certificate.pdf"]
        moves = self._run(self._renumber)
        # G1-2611 -> G1-2621 brings its PDF; G1-2621 -> G1-2611 has none, so G1-2611's old PDF must not stay
        # behind for it.
        self.assertEqual(self._cert("G1-2621"), b"cert-of-G1-2611")
        self.assertIsNone(self._cert("G1-2611"), "the kit without a PDF does not inherit the other kit's")
        self.assertEqual(self._photo(moves["G1-2621"] + ".jpg"), b"photo.jpg-of-G1-2621")
        self._assert_no_staging()
