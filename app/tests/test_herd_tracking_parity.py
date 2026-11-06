"""999.5 parity: every herd_tracking write goes through utils.herd_tracking (or a whitelisted seed)."""

import ast
import re
import unittest
from pathlib import Path

import utils.database as db

APP_DIR = Path(__file__).resolve().parents[1]
ORM_WRITE = re.compile(
    r"HerdTracking\s*(?:\.\s*(?:create|insert|insert_many|insert_from|replace|update|delete|bulk_create|bulk_update)\b|\()"
)
RAW_WRITE = re.compile(r"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+\"?herd_tracking\b", re.IGNORECASE)
ORM_WHITELIST = {"utils/herd_tracking.py", "cli/seed.py"}
RAW_WHITELIST = {"utils/database.py"}  # the migration backfill


def _app_sources():
    for path in sorted(APP_DIR.rglob("*.py")):
        rel = path.relative_to(APP_DIR).as_posix()
        if not rel.startswith("tests/"):
            yield rel, path.read_text(encoding="utf-8")


class TestWriterParity(unittest.TestCase):
    def test_orm_writes_only_in_the_service_or_seed(self):
        offenders = []
        for rel, text in _app_sources():
            if rel in ORM_WHITELIST:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith(("#", "class ")):
                    continue
                if ORM_WRITE.search(line):
                    offenders.append(f"{rel}:{number}: {stripped}")
        self.assertEqual(offenders, [])

    def test_raw_sql_writes_only_in_the_migration(self):
        offenders = [
            f"{rel}: {match.group(0)}"
            for rel, text in _app_sources()
            if rel not in RAW_WHITELIST
            for match in RAW_WRITE.finditer(text)
        ]
        self.assertEqual(offenders, [])

    def test_in_place_updates_are_only_void_and_unvoid(self):
        tree = ast.parse((APP_DIR / "utils" / "herd_tracking.py").read_text(encoding="utf-8"))

        def is_update(node):
            return (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "update"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "HerdTracking"
            )

        total = sum(1 for node in ast.walk(tree) if is_update(node))
        allowed = sum(
            1
            for fn in ast.walk(tree)
            if isinstance(fn, ast.FunctionDef) and fn.name in {"_void_rows", "_unvoid_rows"}
            for node in ast.walk(fn)
            if is_update(node)
        )
        self.assertGreaterEqual(allowed, 1)
        self.assertEqual(total, allowed)

    def test_model_has_no_kind_default(self):
        self.assertIsNone(db.HerdTracking.kind.default)
        self.assertFalse(db.HerdTracking.kind.null)
