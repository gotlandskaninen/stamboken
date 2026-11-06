#!/usr/bin/env python3
"""
Unit tests for the herdbook endpoints.

isort:skip_file
"""
# Fairly lax pylint settings as we want to test a lot of things

# pylint: disable=too-many-public-methods
# pylint: disable=too-many-statements

import logging
import os
import unittest
from datetime import datetime, timedelta

import psycopg2
import utils.data_access as da

# pylint: disable=import-error
import utils.database as db
from psycopg2 import sql
from utils import pedigree_snapshot as ps

from tests.ht_helpers import ht_row  # noqa: E402

# Use PostgreSQL when env vars are set (pytest container has its own database)
# Falls back to SQLite if POSTGRES_HOST/POSTGRES_DB are not configured
_USE_POSTGRES = bool(os.getenv("POSTGRES_HOST")) and bool(os.getenv("POSTGRES_DB"))

# Safety: refuse to truncate a non-test database
_POSTGRES_DB = os.getenv("POSTGRES_DB", "")
_FLASK_ENV = os.getenv("FLASK_ENV", "")
if _USE_POSTGRES:
    _is_test_db = "test" in _POSTGRES_DB.lower()
    _is_test_env = _FLASK_ENV.lower() == "testing"
    if not (_is_test_db and _is_test_env):
        raise RuntimeError(
            f"SAFETY: Refusing to run tests against POSTGRES_DB='{_POSTGRES_DB}' "
            f"with FLASK_ENV='{_FLASK_ENV}'. "
            f"Tests require POSTGRES_DB containing 'test' AND FLASK_ENV='testing'. "
            f"Use: docker compose -f docker-compose.yml -f docker-compose.pytest.yml "
            f"-p herdbook-pytest up -d database api"
        )


_TABLES_TO_TRUNCATE = [
    "audit_log",
    "individual_command",  # before individual + hbuser (FKs individual, actor)
    "matrikel_audit",  # before membership + hbuser (FKs actor, membership)
    "herd_access_grant",  # before member + herd (FKs member, herd, granted_by)
    "member_application",  # before member (FK created_member)
    "member",  # before membership (FK membership)
    "member_number_counter",  # single-row counter — re-seeded to 0 below
    "herd_tracking",
    "authenticators",
    "yearlyherdreport",
    "yearlyreportround",
    "usermessage",
    "bodyfat",
    "weight",
    "individualdisease",
    "disease",
    "individualfile",
    "bunny",
    "digitalcertificatev2",
    "individual",
    "breeding",
    "color",
    "herd",  # before membership (FK membership)
    "membership",
    "hbuser",
    "genebank",
]


class DatabaseTest(unittest.TestCase):
    """
    Database test wrapper that sets up the database connection.

    Optimizations over naive approach:
    - db.init() once per class (not per test) — skips repeated table_exists checks
    - Single batch TRUNCATE instead of 17 individual statements
    """

    # pylint: disable=too-many-instance-attributes

    TEST_DATABASE = "test_database.sqlite3"
    # Uncomment this line to get get full diff
    # maxDiff = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if _USE_POSTGRES:
            db.init()

    @classmethod
    def _batch_truncate_tables(cls):
        """Truncate all test tables in a single statement."""
        table_list = ", ".join(f'"{t}"' for t in _TABLES_TO_TRUNCATE)
        try:
            db.DB_PROXY.execute_sql(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE")
        except Exception:
            logging.warning("Batch TRUNCATE failed, falling back to individual statements", exc_info=True)
            for table in _TABLES_TO_TRUNCATE:
                try:
                    db.DB_PROXY.execute_sql(f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE')
                except Exception:
                    logging.debug("Could not truncate table %s (may not exist yet)", table)

        # member_number_counter is a single-row high-water mark — truncation
        # alone would leave allocation with no row to lock. Re-seed 0.
        try:
            db.DB_PROXY.execute_sql('INSERT INTO "member_number_counter" ("value") VALUES (0)')
        except Exception:
            logging.debug("Could not re-seed member_number_counter (may not exist yet)")

    def setUp(self):
        ps.reset_for_tests()  # genebank ids repeat after RESTART IDENTITY
        if _USE_POSTGRES:
            self._batch_truncate_tables()
        else:
            db.set_test_database(self.TEST_DATABASE)
            db.init()

        self.insert_default()

    def tearDown(self):
        if not _USE_POSTGRES:
            try:
                os.stat(self.TEST_DATABASE)
                os.remove(self.TEST_DATABASE)
            except FileNotFoundError:
                pass

    def insert_default(self):
        """
        This function saves all variables to be easily accessible later.
        """
        self.genebanks = [
            db.Genebank.create(name="Gotland"),
            db.Genebank.create(name="Mellerud"),
        ]

        self.colors = [
            db.Color.create(name="bleighe", genebank=self.genebanks[0]),
            db.Color.create(name="stgröhn", genebank=self.genebanks[0]),
            db.Color.create(name="bläåh", genebank=self.genebanks[1]),
        ]

        self.herds = [
            db.Herd.create(
                genebank=self.genebanks[0],
                herd="G1",
                herd_name="Gotlandsherd1",
                name="owner1",
                name_privacy="private",
                email="o@h1",
                email_privacy="authenticated",
                www="www1",
                www_privacy="public",
            ),
            db.Herd.create(
                genebank=self.genebanks[0],
                herd="G2",
                herd_name="Gotlandsherd2",
                name="owner2",
                name_privacy="authenticated",
                email="o@h2",
                email_privacy="public",
                www="www2",
                www_privacy="private",
            ),
            db.Herd.create(
                genebank=self.genebanks[1],
                herd="M3",
                herd_name="Mellerudherd3",
                name="Owner3",
                name_privacy="public",
                email="o@h3",
                email_privacy="private",
                www="www3",
                www_privacy="authenticated",
            ),
        ]

        parent_breeding = db.Breeding.create(
            breed_date=datetime(2019, 1, 1),
            birth_date=datetime(2019, 2, 1),
            litter_size=2,
            litter_size6w=2,
            breeding_herd_id=self.herds[0],
        )

        parent_breeding2 = db.Breeding.create(
            breed_date=datetime(2017, 1, 1),
            birth_date=datetime(2017, 2, 1),
            litter_size=2,
            litter_size6w=2,
            breeding_herd_id=self.herds[1],
        )

        parent_breeding3 = db.Breeding.create(
            breed_date=datetime(2019, 1, 1),
            birth_date=datetime(2019, 2, 1),
            litter_size=2,
            litter_size6w=2,
            breeding_herd_id=self.herds[2],
        )

        parent_breeding4 = db.Breeding.create(
            breed_date=datetime(2018, 1, 1),
            birth_date=datetime(2018, 2, 1),
            litter_size=2,
            litter_size6w=2,
            breeding_herd_id=self.herds[2],
        )

        self.parents = [
            db.Individual.create(origin_herd=self.herds[0], breeding=parent_breeding, number="G1-1911"),
            db.Individual.create(origin_herd=self.herds[1], breeding=parent_breeding2, number="G2-1711"),
            db.Individual.create(origin_herd=self.herds[2], breeding=parent_breeding3, number="M3-1911"),
            db.Individual.create(origin_herd=self.herds[2], breeding=parent_breeding4, number="M3-1811"),
        ]

        ht_row(
            "BIRTH",
            herd=self.herds[0],
            individual=self.parents[0],
            herd_tracking_date=datetime(2019, 2, 1),
        )

        self.breeding = [
            db.Breeding.create(
                breed_date=datetime(2021, 1, 1),
                birth_date=datetime(2021, 2, 1),
                mother=self.parents[0],
                father=self.parents[1],
                litter_size=2,
                litter_size6w=2,
                breeding_herd_id=self.herds[0],
            ),
            db.Breeding.create(
                breed_date=datetime(2021, 1, 1),
                birth_date=datetime(2021, 2, 1),
                mother=self.parents[2],
                father=self.parents[3],
                litter_size=2,
                litter_size6w=2,
                breeding_herd_id=self.herds[2],
            ),
            db.Breeding.create(
                breed_date=datetime(2020, 1, 1),
                birth_date=datetime(2020, 2, 1),
                mother=self.parents[0],
                father=self.parents[1],
                litter_size=2,
                litter_size6w=2,
                breeding_herd_id=self.herds[1],
            ),
            db.Breeding.create(
                breed_date=datetime(2022, 1, 1),
                #       birth_date=datetime(2021, 2, 1),
                mother=self.parents[2],
                father=self.parents[3],
                breeding_herd_id=self.herds[2],
            ),
        ]

        self.individuals = [
            db.Individual.create(
                origin_herd=self.herds[0],
                breeding=self.breeding[0],
                color=self.colors[0],
                certificate="12",
                number="G1-2111",
            ),
            db.Individual.create(
                origin_herd=self.herds[1],
                breeding=self.breeding[2],
                color=self.colors[0],
                certificate="13",
                number="G2-2011",
            ),
            db.Individual.create(origin_herd=self.herds[2], breeding=self.breeding[1], number="M3-2122"),
            db.Individual.create(
                origin_herd=self.herds[0],
                breeding=self.breeding[0],
                color=self.colors[0],
                number="G1-2112",
            ),
            db.Individual.create(
                origin_herd=self.herds[2],
                breeding=self.breeding[1],
                color=self.colors[0],
                number="M3-2111",
            ),
        ]

        # additional breeding between regular individuals
        self.breeding += [
            db.Breeding.create(
                breed_date=datetime(2020, 6, 1),
                mother=self.individuals[0],
                father=self.individuals[1],
                litter_size=3,
                litter_size6w=2,
                breeding_herd_id=self.herds[0],
            ),
        ]

        self.weights = [
            db.Weight.create(
                individual=self.individuals[0],
                weight=2.1,
                weight_date=datetime(2020, 2, 2),
            ),
        ]

        self.bodyfat = [
            db.Bodyfat.create(
                individual=self.individuals[0],
                bodyfat="low",
                bodyfat_date=datetime(2020, 2, 2),
            ),
        ]

        self.admin = da.register_user("admin", "pass")
        self.viewer = da.register_user("spec", "pass")
        self.manager = da.register_user("man", "pass")
        self.owner = da.register_user("owner", "pass")
        self.admin.add_role("admin", None)
        self.viewer.add_role("viewer", self.genebanks[0].id)
        self.manager.add_role("manager", self.genebanks[0].id)
        self.owner.add_role("owner", self.herds[0].id)

        self.herd_tracking = [
            ht_row(
                "BIRTH",
                herd=self.herds[0],
                signature=self.manager,
                individual=self.individuals[0],
                herd_tracking_date=datetime(2021, 2, 1),
            ),
            ht_row(
                "BIRTH",
                herd=self.herds[1],
                signature=self.manager,
                individual=self.individuals[1],
                herd_tracking_date=datetime(2021, 2, 1),
            ),
            ht_row(
                "TRANSFER",
                herd=self.herds[0],
                signature=self.manager,
                individual=self.individuals[2],
                herd_tracking_date=datetime(2021, 2, 1),
            ),
            ht_row(
                "BIRTH",
                herd=self.herds[0],
                signature=self.manager,
                individual=self.individuals[3],
                herd_tracking_date=datetime(2021, 2, 1),
            ),
            ht_row(
                "BIRTH",
                herd=self.herds[2],
                signature=self.manager,
                individual=self.individuals[4],
                herd_tracking_date=datetime(2021, 2, 1),
            ),
            ht_row(
                "TRANSFER",
                from_herd=self.herds[0],
                herd=self.herds[2],
                signature=self.manager,
                individual=self.individuals[2],
                herd_tracking_date=datetime.now() - timedelta(days=30),
            ),
        ]


def _reset_scratch_database(shared, name, create):
    """Drop database `name` (if present) and optionally create it empty."""
    conn = psycopg2.connect(dbname=shared.database, **shared.connect_params)
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
            (name,),
        )
        # nosemgrep: sqlalchemy-execute-raw-query (psycopg2.sql.Identifier is safe)
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        if create:
            # nosemgrep: sqlalchemy-execute-raw-query (psycopg2.sql.Identifier is safe)
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    finally:
        conn.close()


class IsolatedSchemaTest(DatabaseTest):
    """
    DatabaseTest on a throwaway database, for tests that reshape the schema.

    db.init() only creates MISSING tables, so columns a test drops or re-adds
    in the shared test database stay that way for every later test in the
    worker and for later runs on a reused volume. Classes that do that run in
    their own database, `<shared>_mig` (per xdist worker), bootstrapped by
    db.init() and dropped when the class is done.
    """

    @classmethod
    def setUpClass(cls):
        shared, migrator = db.DATABASE, db.DATABASE_MIGRATOR
        scratch = f"{shared.database}_mig"
        # Registered first so a failed bootstrap still restores the binding.
        cls.addClassCleanup(cls._restore_shared, shared, migrator, scratch)
        _reset_scratch_database(shared, scratch, create=True)
        params = shared.connect_params
        db.set_database(scratch, params["host"], params["port"], params["user"], params["password"])
        super().setUpClass()

    @staticmethod
    def _restore_shared(shared, migrator, scratch):
        if db.DATABASE is not shared:
            db.DATABASE.close()
        db.DATABASE, db.DATABASE_MIGRATOR = shared, migrator
        db.DB_PROXY.initialize(shared)
        _reset_scratch_database(shared, scratch, create=False)
