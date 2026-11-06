"""
pytest-xdist support: per-worker database isolation.

When running with `pytest -n auto`, each worker gets its own PostgreSQL
database (e.g. herdbook_test_gw0, herdbook_test_gw1). The controller
process creates them before tests start; workers connect via the
POSTGRES_DB env var which is set before database.py is imported.

Sequential runs (no -n flag) use the default herdbook_test database.
"""

import os

import psycopg2
from psycopg2 import sql


def pytest_configure(config):
    """Create per-worker test database when running under xdist."""
    config.addinivalue_line("markers", "slow: long-running measurements, run with RUN_SLOW=1")

    worker_id = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker_id:
        return  # sequential run or controller — nothing to do

    base_db = os.environ.get("POSTGRES_DB", "herdbook_test")
    worker_db = f"{base_db}_{worker_id}"

    # Create the worker database (connect to default 'postgres' db)
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "herdbook")
    password = os.environ.get("POSTGRES_PASSWORD", "")

    conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=base_db)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (worker_db,))
    if not cur.fetchone():
        # nosemgrep: sqlalchemy-execute-raw-query (psycopg2.sql.Identifier is safe)
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(worker_db)))
    cur.close()
    conn.close()

    # Point this worker at its own database — database.py reads this at import time
    os.environ["POSTGRES_DB"] = worker_db

    # Give each worker its own exclusive Redis DB to avoid flushdb() races.
    # Workers are gw0..gwN; offset from DB 2 (DB 0 = dev, DB 1 = default test).
    #
    # Co-locate this worker's sessions in the SAME db as its data cache — one db
    # per worker, not two. Within a single xdist worker there is no concurrency
    # (a worker runs its assigned tests sequentially and owns its db exclusively),
    # so an inter-test flushdb only ever wipes this worker's own state, never
    # another worker's. One db per worker fits Redis's default 16-db range (0-15)
    # for up to 14 workers; a two-dbs-per-worker scheme (e.g. 3 + 2*worker_num)
    # would overflow to db 25 under `-n auto` on a 12-core host.
    worker_num = int(worker_id.replace("gw", ""))
    redis_db = worker_num + 2
    # Explicit raise instead of assert: asserts are stripped under `python -O`,
    # and this guard must never be optimized away (silent db collisions).
    if redis_db > 15:
        raise ValueError(
            f"pytest-xdist worker maps to Redis db {redis_db}, exceeding Redis's "
            "default 16-db range (0-15); run pytest with -n <=14 on hosts with more cores"
        )
    base_redis = os.environ.get("REDIS_URL", "redis://redis:6379/1")
    base_session = os.environ.get("SESSION_REDIS_URL", "redis://redis:6379/2")
    # Replace the DB number at the end of each URL, co-locating both in redis_db
    os.environ["REDIS_URL"] = base_redis.rsplit("/", 1)[0] + f"/{redis_db}"
    os.environ["SESSION_REDIS_URL"] = base_session.rsplit("/", 1)[0] + f"/{redis_db}"
