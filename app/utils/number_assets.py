"""
Certificates and photos are keyed by Individual.number; they follow the number when it changes.

The v1 certificate lives in S3 at ``{number}/certificate.pdf``, the photo on disk at
``<UPLOAD_FOLDER>/kaniner/{number}.jpg`` (+ ``_thumb.jpg``). A number change moves them in two steps:

1. ``record()``, inside the renaming transaction: lock the old and the new number, then copy every
   asset to the staging name ``~{new}``. Copies only, so a rollback leaves the originals as they
   were; a copy error raises ``AssetMoveError`` and the rename rolls back with it.
2. ``finish()``, after the outermost commit (entry points are wrapped in ``@finishing``;
   ``teardown_request`` covers routes that hold the transaction themselves): for each move the
   database confirms, put ``~{new}`` at ``{new}`` for ALL moves before removing any old name, so a
   swap never overwrites; then release the number locks. A failure is logged with the steps that are
   left and never raised: the staging copies still hold every asset.

The number locks are PostgreSQL session advisory locks, so they outlive the commit: another rename or
a photo upload touching the same number waits until the files are in place. Lock order: row locks
first, then number locks; ``finish()`` takes no row locks.
"""

import functools
import logging
import os
import shutil
import threading
from functools import partial

from peewee import SqliteDatabase

import utils.database as dbm
import utils.s3 as s3

from utils.database import DB_PROXY as DATABASE  # isort:skip
from utils.database import Individual  # isort:skip

logger = logging.getLogger(__name__)

PHOTO_SUFFIXES = (".jpg", "_thumb.jpg")
_LOCK_NS = 0x48424E52  # "HBNR": classid of the advisory locks on rabbit numbers
_pending = threading.local()  # gunicorn runs threads: one pending set per thread (= per connection)


class AssetMoveError(Exception):
    """An asset could not be staged under its new number; the rename must roll back."""


def kaniner_path():
    """Return the upload directory for rabbit photos."""
    return os.path.join(os.getenv("UPLOAD_FOLDER", "/app/uppladdningar"), "kaniner")


def cert_key(number):
    """S3 key of the v1 certificate for `number`."""
    return f"{number}/certificate.pdf"


def lock_number(number, xact=False):
    """Wait until no other operation moves assets to or from `number`; a session lock unless `xact`."""
    if isinstance(dbm.DATABASE, SqliteDatabase):
        return
    func = "pg_advisory_xact_lock" if xact else "pg_advisory_lock"
    DATABASE.execute_sql(f"SELECT {func}(%s, hashtext(%s))", (_LOCK_NS, number))


def _state():
    if not hasattr(_pending, "moves"):
        _pending.moves, _pending.locked = {}, set()
    return _pending


def _missing(exc):
    return exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404") if hasattr(exc, "response") else False


def _remove(path):
    if os.path.exists(path):
        os.remove(path)


def record(individual_id, old_number, new_number, has_certificate):
    """Stage the assets of one number change. Call inside the transaction that changes the number."""
    state = _state()
    prev = state.moves.get(individual_id)
    # A change that continues one recorded earlier in this transaction (A -> B, then B -> C): the
    # assets are still at A. update_individual records its rename (A -> C) after the birth-year
    # fix it triggered (B -> C), so A is the old number there as given.
    move = {
        "old": prev["old"] if prev and prev["new"] == old_number else old_number,
        "new": new_number,
        # ("cert" | "photo<suffix>", number) for every ~<number> this move created
        "staged": prev["staged"] if prev else set(),
    }
    state.moves[individual_id] = move
    try:
        for number in sorted({move["old"], new_number} - state.locked):
            lock_number(number)
            state.locked.add(number)
        if move["old"] == new_number:
            return
        if has_certificate:
            try:
                s3.get_s3_client().copy_object(
                    old_object_name=cert_key(move["old"]), object_name=cert_key("~" + new_number)
                )
                move["staged"].add(("cert", new_number))
            except Exception as exc:  # pylint: disable=broad-except
                if not _missing(exc):
                    raise
                logger.warning(f"No certificate object for {move['old']}; nothing to move to {new_number}")
        folder = kaniner_path()
        for suffix in PHOTO_SUFFIXES:
            src = os.path.join(folder, move["old"] + suffix)
            if os.path.exists(src):
                move["staged"].add(("photo" + suffix, new_number))  # before the copy: a partial file is ours
                shutil.copyfile(src, os.path.join(folder, "~" + new_number + suffix))
    except Exception as exc:
        raise AssetMoveError(f"{move['old']} -> {new_number}: {exc}") from exc


def finish():
    """Finalize staged moves once no transaction is open; clean up moves that rolled back. Never raises."""
    if DATABASE.transaction_depth() > 0 or not getattr(_pending, "moves", None):
        return
    moves, locked = _pending.moves, _pending.locked
    _pending.moves, _pending.locked = {}, set()
    plan, pos, planned = [], 0, False
    try:
        numbers = dict(
            Individual.select(Individual.id, Individual.number).where(Individual.id.in_(list(moves))).tuples()
        )
        done = {i for i, m in moves.items() if numbers.get(i) == m["new"] and m["old"] != m["new"]}
        # What a committed move writes, per asset kind and name. Any other old name goes, so a rabbit
        # without a PDF or photo of its own never inherits its swap partner's.
        final = {(kind, n) for i in done for kind, n in moves[i]["staged"] if n == moves[i]["new"]}
        client = s3.get_s3_client() if any(kind == "cert" for m in moves.values() for kind, _ in m["staged"]) else None
        folder = kaniner_path()

        def path(kind, number):
            return os.path.join(folder, number + kind[len("photo") :])

        for i in done:  # pass 1: every staged copy to its final name before any old name goes
            new = moves[i]["new"]
            for kind, _ in sorted(k for k in final if k[1] == new):
                if kind == "cert":
                    step = partial(client.copy_object, old_object_name=cert_key("~" + new), object_name=cert_key(new))
                    plan.append((f"S3 copy {cert_key('~' + new)} -> {cert_key(new)}", step))
                else:
                    step = partial(os.replace, path(kind, "~" + new), path(kind, new))
                    plan.append((f"mv {path(kind, '~' + new)} {path(kind, new)}", step))
        for i in done:  # pass 2: old names no committed move writes to
            old = moves[i]["old"]
            for kind, _ in sorted(k for k in final if k[1] == moves[i]["new"]):
                if (kind, old) in final:
                    continue
                if kind == "cert":
                    plan.append((f"S3 delete {cert_key(old)}", partial(client.delete_object, cert_key(old))))
                else:
                    plan.append((f"rm {path(kind, old)}", partial(_remove, path(kind, old))))
        for m in moves.values():  # pass 3: staging copies, incl. those of moves that rolled back
            for kind, number in sorted(m["staged"]):
                if kind == "cert":
                    step = partial(client.delete_object, cert_key("~" + number))
                    plan.append((f"S3 delete {cert_key('~' + number)}", step))
                elif (kind, number) not in final:  # pass 1 moved the final ones into place
                    plan.append((f"rm {path(kind, '~' + number)}", partial(_remove, path(kind, "~" + number))))
        planned = True
        while pos < len(plan):
            plan[pos][1]()
            pos += 1
    except Exception:  # pylint: disable=broad-except
        logger.exception(
            "Certificate/photo move after a number change stopped. Each asset is at its old name or at "
            "~<new>. Moves: %s. Left to do, in order:\n  %s",
            ", ".join(f"{m['old']} -> {m['new']}" for m in moves.values()),
            "\n  ".join(label for label, _ in plan[pos:]) if planned else "(could not plan the steps)",
        )
    finally:
        _unlock(locked)


def _unlock(numbers):
    if not numbers or isinstance(dbm.DATABASE, SqliteDatabase):
        return
    try:
        for number in numbers:
            DATABASE.execute_sql("SELECT pg_advisory_unlock(%s, hashtext(%s))", (_LOCK_NS, number))
    except Exception:  # pylint: disable=broad-except
        # Session locks survive a rollback and the connection is reused: close it, which drops them.
        logger.exception("Could not release number locks %s; closing the connection", sorted(numbers))
        try:
            DATABASE.close()
        except Exception:  # pylint: disable=broad-except
            logger.exception("Could not close the connection holding number locks %s", sorted(numbers))


def finishing(func):
    """Run finish() when `func` returns or raises; a no-op while a caller's transaction is open."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            finish()

    return wrapper
