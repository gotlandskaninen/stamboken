"""Shared helpers for the 999.5 herd-tracking tests (test code only — never imported by app/)."""

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest import mock

import utils.database as db
from peewee import JOIN, fn
from utils import herd_tracking


def ht_row(kind, **fields):
    """Insert a HerdTracking row with an explicit kind (there is no model default) and a fresh operation id."""
    fields.setdefault("operation_id", uuid.uuid4())
    return db.HerdTracking.create(kind=kind, **fields)


def make_individual(herd, number, birth, *, sex="female", certificate=True):
    """A registered individual alone in its own litter, born in `herd` (no herd-tracking row)."""
    breeding = db.Breeding.create(
        breed_date=birth - timedelta(days=31),
        birth_date=birth,
        litter_size=1,
        litter_size6w=1,
        breeding_herd_id=herd,
    )
    return db.Individual.create(
        origin_herd=herd,
        breeding=breeding,
        number=number,
        sex=sex,
        certificate=f"C-{number}" if certificate else None,
    )


def age_row(row, days):
    """Backdate created_at by `days` (tests only — production never rewrites created_at)."""
    db.HerdTracking.update(created_at=datetime.now(timezone.utc) - timedelta(days=days)).where(
        db.HerdTracking.id == row.id
    ).execute()


def _void(row, user, reason="test"):
    """Void one row via the whitelisted writer (tests only)."""
    herd_tracking._void_rows([row], user, reason, uuid.uuid4())


def _active(ind):
    """The individual's active rows, newest first (tests only)."""
    return list(
        db.HerdTracking.select()
        .where(db.HerdTracking.individual == ind, db.ht_not_voided())
        .order_by(*db.ht_order_desc())
    )


@contextmanager
def count_queries():
    """Count SQL statements executed on the database inside the block."""
    counter = {"n": 0}
    original = db.DATABASE.execute_sql

    def counting(*args, **kwargs):
        counter["n"] += 1
        return original(*args, **kwargs)

    with mock.patch.object(db.DATABASE, "execute_sql", side_effect=counting):
        yield counter


def herd_members(herd):
    """Individuals whose current herd (latest active tracking row, else the origin herd) is `herd`."""
    latest = db.latest_ht_per_individual().alias("latest_ht")
    return list(
        db.Individual.select()
        .join(latest, JOIN.LEFT_OUTER, on=((db.Individual.id == latest.c.i_id) & (latest.c.rank == 1)))
        .where(fn.COALESCE(latest.c.herd, db.Individual.origin_herd_id) == herd.id)
    )
