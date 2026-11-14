"""
The yearly report's register statistics per herd and breeding year.

Counted from the register, not from submitted reports: what the register
expects on 31 December. The rules are the yearly report spec's list rule (5.2)
and its export and support conditions (8).
"""

from dataclasses import dataclass
from datetime import date, timedelta

from peewee import JOIN, fn

from utils.database import (
    ACTIVE_WINDOW_DAYS,
    OUTSIDE_GENEBANK_HERDS,
    Breeding,
    Herd,
    Individual,
    latest_ht_per_individual,
    not_voided,
)


@dataclass(frozen=True)
class Statistik:
    kullar: int
    ungar: int
    levande_6v: int  # sum of the known values only
    kullar_okant_6v: int  # litters without a 6-week count; never read as 0 alive
    avelshonor: int
    avelshanar: int
    honor: int
    hanar: int


def statistik(genebank_id: int, year: int) -> dict[int, Statistik]:
    """Register statistics for every herd in the genebank, keyed by herd id.

    GX1/MX1 (sold outside the genebank) are not herds here. Two queries.

    Litters: ``Breeding`` rows with the herd as ``breeding_herd_id`` and
    ``birth_date`` in ``year``. ``ungar`` sums ``litter_size``,
    ``levande_6v`` sums the known ``litter_size6w`` and
    ``kullar_okant_6v`` counts the litters where it is NULL.
    ``avelshonor``/``avelshanar`` count distinct mothers and fathers of those
    litters, castrated or not.

    ``honor``/``hanar`` on 31 December (list rule 5.2): rabbits with a
    certificate (paper or digital, required), whose latest active
    herd-tracking row dated on or before 31 December, in ``ht_order_desc()``
    order, is in the herd, with no ``death_date`` on or before 31 December,
    and with a life sign (``LIFE_SIGN_KINDS``) on or before 31 December within
    ``ACTIVE_WINDOW_DAYS``, so an old rabbit nobody reported is left out.
    Castrated rabbits count. Rows after 31 December are ignored: a rabbit
    sold in January counts with the seller.
    """
    first, last = date(year, 1, 1), date(year, 12, 31)

    litters = (
        Herd.select(
            Herd.id,
            fn.COUNT(Breeding.id).alias("kullar"),
            fn.COALESCE(fn.SUM(Breeding.litter_size), 0).alias("ungar"),
            fn.COALESCE(fn.SUM(Breeding.litter_size6w), 0).alias("levande_6v"),
            fn.COUNT(Breeding.id).filter(Breeding.litter_size6w.is_null()).alias("kullar_okant_6v"),
            fn.COUNT(Breeding.mother.distinct()).alias("avelshonor"),
            fn.COUNT(Breeding.father.distinct()).alias("avelshanar"),
        )
        .join(
            Breeding,
            JOIN.LEFT_OUTER,
            on=((Breeding.breeding_herd_id == Herd.id) & Breeding.birth_date.between(first, last)),
        )
        .where(Herd.genebank == genebank_id, Herd.herd.not_in(OUTSIDE_GENEBANK_HERDS))
        .group_by(Herd.id)
    )

    latest = latest_ht_per_individual(as_of=last).alias("latest_ht")
    held = (
        Individual.select(
            latest.c.herd.alias("herd_id"),
            fn.COUNT(Individual.id).filter(Individual.sex == "female").alias("honor"),
            fn.COUNT(Individual.id).filter(Individual.sex == "male").alias("hanar"),
        )
        .join(latest, on=((Individual.id == latest.c.i_id) & (latest.c.rank == 1)))
        .join(Herd, on=(Herd.id == latest.c.herd))
        .where(
            Herd.genebank == genebank_id,
            not_voided(),
            Individual.certificate.is_null(False) | Individual.digital_certificate.is_null(False),
            Individual.death_date.is_null() | (Individual.death_date > last),
            latest.c.life_sign_date > last - timedelta(days=ACTIVE_WINDOW_DAYS),
        )
        .group_by(latest.c.herd)
    )
    held_by_herd = {row.pop("herd_id"): row for row in held.dicts()}

    result = {}
    for row in litters.dicts():
        herd_id = row.pop("id")
        result[herd_id] = Statistik(**row, **held_by_herd.get(herd_id, {"honor": 0, "hanar": 0}))
    return result
