#!/usr/bin/env python3
"""
One-off migration replay run before gunicorn starts (see .docker/api).

An unreachable database is tolerated — herdbook.py's boot loop waits for it
and the advisory lock in check_migrations() keeps the worker replays safe —
but a replay that fails against a reachable database must stop the container
instead of letting gunicorn treat the schema as ready.
"""

import sys

from peewee import OperationalError
from utils import database


def main():
    try:
        database.DATABASE.connect(reuse_if_open=True)
    except OperationalError as exception:
        print(f"prestart: database unavailable, deferring migrations to app boot: {exception}")
        return 0

    database.check_migrations()
    print("prestart: migrations up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
