"""
The reference population for mean kinship: the only place that decides membership.

Live membership (today's MK) and the membership of each history year both go
through ``members()``. The rule is versioned: a board decision such as
"15 months rolling" becomes a new ``ReferenceDefinition``, not new code.
The rule is PRELIMINARY, pending a board decision.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from peewee import JOIN, fn

from utils.database import (
    LIFE_SIGN_KINDS,
    OUTSIDE_GENEBANK_HERDS,
    Breeding,
    Herd,
    HerdTracking,
    YearlyReportRound,
    ht_not_voided,
    ht_order_desc,
    not_voided,
)
from utils.database import Individual as DBIndividual
from utils.genetics import MAX_RABBIT_AGE_DAYS, extract_death_year


@dataclass(frozen=True)
class ReferenceDefinition:
    version: int
    window: Literal["round_start", "rolling_days"]
    rolling_days: int | None = None
    preliminary: bool = True


# Version 1 is reserved for the old 13-month rule and is not implemented.
DEFINITIONS = {2: ReferenceDefinition(2, "round_start")}
CURRENT_DEFINITION = DEFINITIONS[2]

# A history year is shown from the first year with at least this many members.
MIN_HISTORY_MEMBERS = 30


def reference_population_start(today: date | None = None) -> date:
    """First day of the most recently closed yearly report round.

    That is 1 January of the highest ``YearlyReportRound.report_year`` whose
    ``end_date`` has passed. Falls back to 1 January of the previous calendar
    year when no round has closed.
    """
    if today is None:
        today = date.today()

    closed = (
        YearlyReportRound.select(YearlyReportRound.report_year)
        .where(YearlyReportRound.end_date.is_null(False))
        .where(YearlyReportRound.end_date < today)
        .order_by(YearlyReportRound.report_year.desc())
        .first()
    )
    if closed is not None:
        return date(closed.report_year, 1, 1)
    return date(today.year - 1, 1, 1)


def members(genebank_id: int, *, start: date, as_of: date, live: bool) -> set[str]:
    """Individual numbers in the genebank's reference population.

    Both modes: a non-voided life sign (BIRTH/TRANSFER/ATTESTATION; a CORRECTION
    is not one) dated in ``[start, as_of]``; the current herd (latest non-voided
    row dated ≤ ``as_of``, of any kind) is not GX1/MX1; a certificate; not voided.

    ``live``: the current herd is active, and no death date, death note or
    castration date at all. History: the herd's ``is_active`` is ignored (it
    cannot be reconstructed); born ≤ ``as_of`` or unknown; dead or castrated
    only after ``as_of``; a death note without a date counts from 1 January of
    its year, else from birth + ``MAX_RABBIT_AGE_DAYS``, else always.
    """
    OriginHerd = Herd.alias()
    CurrentHerd = Herd.alias()

    latest = (
        HerdTracking.select(
            HerdTracking.individual.alias("individual_id"),
            HerdTracking.herd.alias("herd_id"),
            fn.MAX(HerdTracking.herd_tracking_date)
            .filter(HerdTracking.kind.in_(LIFE_SIGN_KINDS))
            .over(partition_by=[HerdTracking.individual])
            .alias("life_sign_date"),
            fn.ROW_NUMBER()
            .over(
                partition_by=[HerdTracking.individual],
                order_by=ht_order_desc(),
            )
            .alias("rn"),
        )
        .join(DBIndividual, on=(HerdTracking.individual == DBIndividual.id))
        .join(OriginHerd, on=(DBIndividual.origin_herd == OriginHerd.id))
        .where(OriginHerd.genebank == genebank_id)
        .where(ht_not_voided())
        # A row dated after as_of is neither a life sign nor the current herd.
        .where(HerdTracking.herd_tracking_date <= as_of)
        .cte("latest_tracking")
    )

    query = (
        DBIndividual.select(
            DBIndividual.number,
            DBIndividual.death_date,
            DBIndividual.death_note,
            Breeding.birth_date,
        )
        .join(latest, on=(latest.c.individual_id == DBIndividual.id))
        .join(CurrentHerd, on=(CurrentHerd.id == latest.c.herd_id))
        .switch(DBIndividual)
        .join(Breeding, JOIN.LEFT_OUTER, on=(DBIndividual.breeding == Breeding.id))
        .where(latest.c.rn == 1)
        .where(latest.c.life_sign_date >= start)
        # Explicit: GX1/MX1 never count, whatever their is_active says (spec 999.5).
        .where(CurrentHerd.herd.not_in(OUTSIDE_GENEBANK_HERDS))
        .where(DBIndividual.certificate.is_null(False) | DBIndividual.digital_certificate.is_null(False))
        .where(not_voided(DBIndividual))
        .with_cte(latest)
    )

    if live:
        query = query.where(
            CurrentHerd.is_active == True,  # noqa: E712 — peewee needs == not `is`
            DBIndividual.death_date.is_null(),
            DBIndividual.death_note.is_null() | (DBIndividual.death_note == ""),
            DBIndividual.castration_date.is_null(),
        )
        return {row["number"] for row in query.dicts()}

    query = query.where(
        Breeding.birth_date.is_null() | (Breeding.birth_date <= as_of),
        DBIndividual.castration_date.is_null() | (DBIndividual.castration_date > as_of),
        DBIndividual.death_date.is_null() | (DBIndividual.death_date > as_of),
    )
    return {row["number"] for row in query.dicts() if _alive_by_note(row, as_of)}


def _alive_by_note(row: dict, as_of: date) -> bool:
    """A death note without a death date: dead from its year, else from birth + max age, else always."""
    note = (row["death_note"] or "").strip()
    if row["death_date"] is not None or not note:
        return True
    year = extract_death_year(note)
    if year is not None:
        return as_of < date(year, 1, 1)
    birth = row["birth_date"]
    if birth is None:
        return False
    return as_of < birth + timedelta(days=MAX_RABBIT_AGE_DAYS)


def live_members(genebank_id: int, today: date, definition: ReferenceDefinition = CURRENT_DEFINITION) -> set[str]:
    """Today's reference population under ``definition``."""
    if definition.window == "round_start":
        start = reference_population_start(today)
    else:
        start = today - timedelta(days=definition.rolling_days)
    return members(genebank_id, start=start, as_of=today, live=True)


def history_as_of(report_year: int) -> date | None:
    """The day after the year's round ended (rows dated on end_date count).

    No round for the year: 1 April the year after. A round without an end
    date: ``None`` (the year is not closed).
    """
    report_round = YearlyReportRound.get_or_none(YearlyReportRound.report_year == report_year)
    if report_round is None:
        return date(report_year + 1, 4, 1)
    if report_round.end_date is None:
        return None
    return report_round.end_date + timedelta(days=1)


def is_closed(report_year: int, today: date) -> bool:
    """A year is closed once its ``history_as_of`` has come; a reopened round is open again."""
    as_of = history_as_of(report_year)
    return as_of is not None and as_of <= today


def history_window(report_year: int, definition: ReferenceDefinition = CURRENT_DEFINITION) -> tuple[date, date] | None:
    """``(start, as_of)`` for a history year, or ``None`` while its round has no end date."""
    as_of = history_as_of(report_year)
    if as_of is None:
        return None
    if definition.window == "round_start":
        return date(report_year, 1, 1), as_of
    return as_of - timedelta(days=definition.rolling_days), as_of
