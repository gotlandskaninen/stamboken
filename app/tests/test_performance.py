"""
Performance benchmarks for GET /api/individuals.

Measures response times across multiple query patterns to verify
the < 500ms target from Story 3.4 AC2.

Run:
  docker exec herdbook-pytest-api-1 pytest /app/tests/test_performance.py -v -s
"""

import statistics
import time
from datetime import datetime, timedelta

import utils.database as db

from tests.ht_helpers import ht_row
from tests.test_endpoints import FlaskTest


class TestPerformanceBenchmarks(FlaskTest):
    """Benchmarks for the paginated individuals endpoint."""

    SEED_COUNT = 500  # Rows to seed for realistic benchmarks
    ITERATIONS = 5  # Repeat each query for stable median

    def setUp(self):
        super().setUp()
        # Give individuals names for search/sort testing
        self.individuals[0].name = "Bruno"
        self.individuals[0].save()
        self.individuals[1].name = "Bella"
        self.individuals[1].save()

        # Seed extra individuals for realistic JOINs
        for i in range(self.SEED_COUNT):
            b = db.Breeding.create(
                breed_date=datetime(2023, 1, 1),
                birth_date=datetime(2020, 1, 1) + timedelta(days=i),
                litter_size=3,
                litter_size6w=2,
                breeding_herd_id=self.herds[i % len(self.herds)],
            )
            ind = db.Individual.create(
                origin_herd=self.herds[i % len(self.herds)],
                breeding=b,
                number=f"G1-BM{i:04d}",
                name=f"Benchmark-{i:04d}",
                sex="male" if i % 2 == 0 else "female",
            )
            ht_row(
                "BIRTH",
                herd=self.herds[i % len(self.herds)],
                individual=ind,
                herd_tracking_date=datetime.now() - timedelta(days=10),
            )

    def _login_admin(self, ctx):
        ctx.post("/api/login", json={"username": self.admin.email, "password": "pass"})

    def _benchmark(self, ctx, url, label):
        """Run a query ITERATIONS times, return median ms."""
        times = []
        for _ in range(self.ITERATIONS):
            start = time.monotonic()
            resp = ctx.get(url)
            elapsed = (time.monotonic() - start) * 1000
            self.assertEqual(resp.status_code, 200)
            times.append(elapsed)
        median = statistics.median(times)
        print(f"  {label}: median={median:.1f}ms  min={min(times):.1f}ms  max={max(times):.1f}ms")
        return median

    def test_benchmark_default_page(self):
        """Benchmark: GET /api/individuals?per_page=50 (default sort by name)."""
        with self.app as ctx:
            self._login_admin(ctx)
            median = self._benchmark(ctx, "/api/individuals?per_page=50", "default_page")
            self.assertLess(median, 500, f"Default page median {median:.0f}ms exceeds 500ms")

    def test_benchmark_sort_by_name(self):
        """Benchmark: GET /api/individuals?per_page=50&sort=name (explicit Swedish sort)."""
        with self.app as ctx:
            self._login_admin(ctx)
            median = self._benchmark(ctx, "/api/individuals?per_page=50&sort=name&order=asc", "sort_name")
            self.assertLess(median, 500, f"Sort-by-name median {median:.0f}ms exceeds 500ms")

    def test_benchmark_search(self):
        """Benchmark: GET /api/individuals?search=Benchmark (substring search)."""
        with self.app as ctx:
            self._login_admin(ctx)
            median = self._benchmark(ctx, "/api/individuals?per_page=50&search=Benchmark", "search")
            self.assertLess(median, 500, f"Search median {median:.0f}ms exceeds 500ms")

    def test_benchmark_sort_by_number(self):
        """Benchmark: GET /api/individuals?per_page=50&sort=number."""
        with self.app as ctx:
            self._login_admin(ctx)
            median = self._benchmark(ctx, "/api/individuals?per_page=50&sort=number&order=asc", "sort_number")
            self.assertLess(median, 500, f"Sort-by-number median {median:.0f}ms exceeds 500ms")

    def test_benchmark_status_filter(self):
        """Benchmark: GET /api/individuals?status=active."""
        with self.app as ctx:
            self._login_admin(ctx)
            median = self._benchmark(ctx, "/api/individuals?per_page=50&status=active", "status_active")
            self.assertLess(median, 500, f"Status filter median {median:.0f}ms exceeds 500ms")
