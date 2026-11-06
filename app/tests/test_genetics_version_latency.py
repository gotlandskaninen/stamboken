"""Write latency of the genetics version triggers. Run with RUN_SLOW=1."""

import os
import statistics
import threading
import time

import psycopg2
import pytest
import utils.database as db

from tests.database_test import DatabaseTest

THREADS = 20
UPDATES = 50
BULK_ROWS = 1000
RUNS = 3
P95_BUDGET_MS = 10.0
ASSERTED_WRITERS = 2
WRITER_COUNTS = (1, 2, 4, 8, 20)
BULK_COMMIT_BUDGET_MS = 50.0


def _connect():
    return psycopg2.connect(database=db.DATABASE.database, **db.DATABASE.connect_params)


def _p95(samples):
    return statistics.quantiles(samples, n=100)[94]


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("RUN_SLOW") != "1", reason="set RUN_SLOW=1 to run measurements")
class TestGeneticsVersionLatency(DatabaseTest):
    def _make_rows(self, count):
        herd = self.herds[0]
        db.Individual.insert_many([{"origin_herd": herd, "number": f"LAT-{i:05d}"} for i in range(count)]).execute()
        return [
            r[0]
            for r in db.DATABASE.execute_sql(
                "SELECT individual_id FROM individual WHERE number LIKE %s ORDER BY 1", ("LAT-%",)
            )
        ]

    def _run_writers(self, ids, threads_n):
        """threads_n writers, UPDATES autocommit single-row updates each; returns ms per statement."""
        samples = []
        lock = threading.Lock()
        barrier = threading.Barrier(threads_n)

        def worker(individual_id):
            conn = _connect()
            conn.autocommit = True
            cur = conn.cursor()
            mine = []
            barrier.wait()
            for i in range(UPDATES):
                day = "2026-03-01" if i % 2 == 0 else "2026-03-02"
                t0 = time.perf_counter()
                cur.execute("UPDATE individual SET death_date = %s WHERE individual_id = %s", (day, individual_id))
                mine.append((time.perf_counter() - t0) * 1000)
            conn.close()
            with lock:
                samples.extend(mine)

        threads = [threading.Thread(target=worker, args=(i,)) for i in ids[:threads_n]]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return samples

    def test_update_p95_with_and_without_trigger(self):
        """Prints the p95 delta per writer count; asserts the median over runs for ASSERTED_WRITERS only."""
        asserted = None
        ids = self._make_rows(THREADS)
        self._run_writers(ids, THREADS)  # warm-up (plan cache, connections)
        for n in WRITER_COUNTS:
            deltas = []
            for run in range(1, RUNS + 1):
                with_trigger = self._run_writers(ids, n)
                conn = _connect()
                conn.autocommit = True
                conn.cursor().execute("ALTER TABLE individual DISABLE TRIGGER genetics_change_individual_upd")
                try:
                    without_trigger = self._run_writers(ids, n)
                finally:
                    conn.cursor().execute("ALTER TABLE individual ENABLE TRIGGER genetics_change_individual_upd")
                    conn.close()
                p_with, p_without = _p95(with_trigger), _p95(without_trigger)
                deltas.append(p_with - p_without)
                print(
                    f"\nLATENCY writers={n} run={run} p95 with={p_with:.2f} ms "
                    f"without={p_without:.2f} ms delta={p_with - p_without:.2f} ms"
                )
            if n == ASSERTED_WRITERS:
                asserted = statistics.median(deltas)
        self.assertLessEqual(asserted, P95_BUDGET_MS)

    def test_bulk_commit_holds_version_lock_briefly(self):
        ids = self._make_rows(BULK_ROWS)
        conn = _connect()
        cur = conn.cursor()
        cur.execute("UPDATE individual SET death_date = '2026-04-01' WHERE individual_id = ANY(%s)", (ids,))
        t0 = time.perf_counter()
        conn.commit()
        commit_ms = (time.perf_counter() - t0) * 1000
        conn.close()
        print(f"\nLATENCY bulk commit ({BULK_ROWS} rows) = {commit_ms:.2f} ms")
        self.assertLessEqual(commit_ms, BULK_COMMIT_BUDGET_MS)
