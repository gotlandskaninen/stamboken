"""
The yearly report's register statistics per herd and breeding year.

Counted from the register: the litters born in the year, and the rabbits each
herd held on 31 December with proof that they were alive then. The rules are
the yearly report spec's export and support conditions (8) and its list rule
(5.2).
"""

from dataclasses import dataclass
from datetime import date

from peewee import JOIN, Tuple, fn

from utils.database import (
    LIFE_SIGN_KINDS,
    OUTSIDE_GENEBANK_HERDS,
    Breeding,
    Herd,
    HerdTracking,
    Individual,
    ht_not_voided,
    latest_ht_per_individual,
    not_voided,
)
from utils.reference_population import _alive_by_note

# The legacy sex 'eunuch' is a castrated male; any other value is an unknown sex.
SEXES = {"female": "female", "male": "male", "eunuch": "male"}


@dataclass(frozen=True)
class Kanin:
    """A rabbit a herd held on 31 December, one per rabbit in ``innehav``."""

    individual_id: int
    sex: str | None  # 'female', 'male' or None (unknown)
    kastrerad: bool  # castrated on or before 31 December, or the legacy sex 'eunuch'


@dataclass(frozen=True)
class Statistik:
    kullar: int
    kullar_med_ungar: int  # litters with at least one kit born (support condition, spec 8)
    ungar: int | None  # None when a litter's size is unknown: unknown, not zero
    levande_6v: int | None  # None when a litter's 6-week count is unknown
    kullar_okant_6v: int  # litters without a 6-week count
    avelshonor: int
    avelshanar: int
    honor: int  # castrated too
    hanar: int  # castrated too
    okant_kon: int  # held rabbits of unknown sex, in neither honor nor hanar
    preliminart: bool = False  # a litter's 6-week count is still the count born (levande_6v is a guess)


def innehav(genebank_id: int, year: int) -> dict[int, list[Kanin]]:
    """The rabbits each herd in the genebank held on 31 December ``year``, keyed by herd id.

    Spec 8: a rabbit counts for herd H when H is its holder on 31 December (the
    latest active row dated on or before that day, in ``ht_order_desc()`` order,
    as ``current_holder_row``) and it has an active ATTESTATION dated 31
    December in H or an active life sign (``LIFE_SIGN_KINDS``) dated later, such
    as a sale in January, which then counts with the seller. What the register
    expects (the 5.2 list) is not a holding: a rabbit nobody reported is left
    out. As in 5.2 it also needs a certificate (an empty paper number is none),
    must not be voided, and must not be dead on 31 December: no ``death_date``
    on or before it, and a death note without a date is read by
    ``_alive_by_note``. GX1/MX1 are not herds.

    Castrated rabbits are included and flagged, so the support conditions
    filter them out themselves (``sex == "male" and not kastrerad``).
    """
    # shortcut: the support conditions also leave out rabbits whose pending sale proposal is
    # dated on or before 31 December, but sale_proposal is not in the schema; flag it here when it is.
    last = date(year, 12, 31)
    OriginHerd = Herd.alias()
    # Limited to the genebank before the window function runs, as in reference_population.
    holder = (
        latest_ht_per_individual(as_of=last)
        .join(Individual, on=(HerdTracking.individual == Individual.id))
        .join(OriginHerd, on=(Individual.origin_herd == OriginHerd.id))
        .where(OriginHerd.genebank == genebank_id)
        .alias("holder")
    )
    attested = HerdTracking.select(HerdTracking.individual, HerdTracking.herd).where(
        ht_not_voided(), HerdTracking.kind == "ATTESTATION", HerdTracking.herd_tracking_date == last
    )
    later_life_sign = HerdTracking.select(HerdTracking.individual).where(
        ht_not_voided(), HerdTracking.kind.in_(LIFE_SIGN_KINDS), HerdTracking.herd_tracking_date > last
    )
    rows = (
        Individual.select(
            Individual.id,
            holder.c.herd.alias("herd_id"),
            Individual.sex,
            Individual.castration_date,
            Individual.death_date,
            Individual.death_note,
            Breeding.birth_date,
        )
        .join(holder, on=((holder.c.i_id == Individual.id) & (holder.c.rank == 1)))
        .join(Herd, on=(Herd.id == holder.c.herd))
        .switch(Individual)
        .join(Breeding, JOIN.LEFT_OUTER, on=(Individual.breeding == Breeding.id))
        .where(
            Herd.genebank == genebank_id,
            Herd.herd.not_in(OUTSIDE_GENEBANK_HERDS),
            not_voided(),
            (Individual.certificate.is_null(False) & (Individual.certificate != ""))
            | Individual.digital_certificate.is_null(False),
            Individual.death_date.is_null() | (Individual.death_date > last),
            Tuple(Individual.id, holder.c.herd).in_(attested) | Individual.id.in_(later_life_sign),
        )
    )
    held = {}
    for row in rows.dicts():
        if not _alive_by_note(row, last):
            continue
        castrated = row["sex"] == "eunuch" or (row["castration_date"] is not None and row["castration_date"] <= last)
        held.setdefault(row["herd_id"], []).append(Kanin(row["id"], SEXES.get(row["sex"]), castrated))
    return held


def statistik(genebank_id: int, year: int) -> dict[int, Statistik]:
    """Register statistics per herd in the genebank for breeding year ``year``, keyed by herd id.

    Only herds with a litter born in the year or a rabbit held on 31 December
    are included, active or not; the caller decides whether a herd that has
    ended goes into the export. GX1/MX1 are not herds. Two queries.

    Litters: ``Breeding`` rows with the herd as ``breeding_herd_id`` and
    ``birth_date`` in ``year``. ``ungar`` and ``levande_6v`` are their sums,
    or None when any litter's count is unknown; ``kullar_okant_6v`` counts the
    litters without a 6-week count. ``preliminart`` is set when a litter's count is still preliminary.
    ``avelshonor``/``avelshanar`` count distinct
    mothers and fathers of those litters, castrated or not.

    ``honor``/``hanar``/``okant_kon`` count ``innehav``, castrated included.
    """
    litters = (
        Breeding.select(
            Breeding.breeding_herd_id.alias("herd_id"),
            fn.COUNT(Breeding.id).alias("kullar"),
            fn.COUNT(Breeding.id).filter(Breeding.litter_size > 0).alias("kullar_med_ungar"),
            fn.SUM(Breeding.litter_size).alias("ungar"),
            fn.COUNT(Breeding.id).filter(Breeding.litter_size.is_null()).alias("okand_storlek"),
            fn.SUM(Breeding.litter_size6w).alias("levande_6v"),
            fn.COUNT(Breeding.id).filter(Breeding.litter_size6w.is_null()).alias("kullar_okant_6v"),
            fn.COUNT(Breeding.id).filter(Breeding.litter_size6w_preliminary).alias("preliminara"),
            fn.COUNT(Breeding.mother.distinct()).alias("avelshonor"),
            fn.COUNT(Breeding.father.distinct()).alias("avelshanar"),
        )
        .join(Herd, on=(Breeding.breeding_herd_id == Herd.id))
        .where(
            Herd.genebank == genebank_id,
            Herd.herd.not_in(OUTSIDE_GENEBANK_HERDS),
            Breeding.birth_date.between(date(year, 1, 1), date(year, 12, 31)),
        )
        .group_by(Breeding.breeding_herd_id)
    )
    by_herd = {}
    for row in litters.dicts():
        if row.pop("okand_storlek"):
            row["ungar"] = None
        if row["kullar_okant_6v"]:
            row["levande_6v"] = None
        row["preliminart"] = bool(row.pop("preliminara"))
        by_herd[row.pop("herd_id")] = row

    no_litters = dict(
        kullar=0, kullar_med_ungar=0, ungar=0, levande_6v=0, kullar_okant_6v=0, avelshonor=0, avelshanar=0
    )
    held = innehav(genebank_id, year)
    result = {}
    for herd_id in by_herd.keys() | held.keys():
        sexes = [rabbit.sex for rabbit in held.get(herd_id, [])]
        result[herd_id] = Statistik(
            **by_herd.get(herd_id, no_litters),
            honor=sexes.count("female"),
            hanar=sexes.count("male"),
            okant_kon=sexes.count(None),
        )
    return result
