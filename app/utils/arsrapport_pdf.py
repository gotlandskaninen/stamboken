"""
The register extract (before the report) and the receipt (after it) as PDFs, from one template (spec 9, fråga 36).
Neither carries the account or a buyer's name, town or contact details.
"""

from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from peewee import JOIN
from weasyprint import HTML

import utils.arsrapport as arsrapport
from utils.database import Breeding, HerdTracking, Individual, Weight, ht_not_voided

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "arsrapport"
# nosemgrep: python.flask.security.xss.audit.direct-use-of-jinja2.direct-use-of-jinja2
_ENV = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)
_SEX = {"female": "hona", "male": "hane", "eunuch": "kastrat"}
_HEALTH = {None: "Ej besvarad", "inga": "Inga sjukdomsfall eller defekter"}
_HULL = {"low": "mager", "normal": "normal", "high": "fet"}


def _render(**context) -> bytes:
    return HTML(string=_ENV.get_template("registerutdrag.html").render(**context)).write_pdf()


def _numbers(ids):
    return dict(Individual.select(Individual.id, Individual.number).where(Individual.id.in_(list(ids))).tuples())


def _latest_weights(ids):
    """The newest weight of each rabbit: the rows run oldest first, so the last one read wins."""
    rows = Weight.select().where(Weight.individual.in_(list(ids))).order_by(Weight.weight_date, Weight.id)
    return {row.individual_id: row.weight for row in rows}


def _sold_and_dead(herd, year):
    """The rabbits the herd sold (a TRANSFER out of it) or lost (a death date, held by it then) during the year."""
    first, last = date(year, 1, 1), date(year, 12, 31)
    sold = (
        HerdTracking.select(HerdTracking.individual, HerdTracking.herd_tracking_date)
        .where(
            HerdTracking.kind == "TRANSFER",
            HerdTracking.from_herd == herd.id,
            HerdTracking.herd_tracking_date.between(first, last),
            ht_not_voided(),
        )
        .order_by(HerdTracking.herd_tracking_date, HerdTracking.id)
    )
    sold = [(row.individual_id, row.herd_tracking_date) for row in sold]
    deaths = Individual.select(Individual.id, Individual.death_date).where(Individual.death_date.between(first, last))
    dead = [
        (row.id, row.death_date)
        for row in deaths.order_by(Individual.death_date, Individual.id)
        if arsrapport._holder_on(row.id, row.death_date, set()) == herd.id  # pylint: disable=protected-access
    ]
    numbers = _numbers([i for i, _ in sold + dead])
    return (
        [{"number": numbers[i], "date": day.isoformat()} for i, day in sold],
        [{"number": numbers[i], "date": day.isoformat()} for i, day in dead],
    )


def _litters(herd, year):
    mother, father = Individual.alias(), Individual.alias()
    rows = (
        Breeding.select(Breeding, mother.number.alias("mother_number"), father.number.alias("father_number"))
        .join(mother, on=(Breeding.mother == mother.id), join_type=JOIN.LEFT_OUTER)
        .join(father, on=(Breeding.father == father.id), join_type=JOIN.LEFT_OUTER)
        .where(Breeding.breeding_herd_id == herd.id, Breeding.birth_date.between(date(year, 1, 1), date(year, 12, 31)))
        .order_by(Breeding.birth_date, Breeding.id)
        .objects()
    )
    return [
        {
            "date": row.birth_date.isoformat(),
            "number": row.litter_number,
            "mother": row.mother_number,
            "father": row.father_number,
            "born": row.litter_size,
            "alive": row.litter_size6w,
        }
        for row in rows
    ]


def register_extract_pdf(herd, round_) -> bytes:
    """The rabbits the register holds in `herd` on 31 December, and its sold, dead and litters that year."""
    year = round_.report_year
    rows = arsrapport.report_list(herd, year)
    weights = _latest_weights(row["id"] for row in rows)
    sold, dead = _sold_and_dead(herd, year)
    rabbits = [
        {
            "number": row["number"],
            "name": row["name"],
            "sex": _SEX.get(row["sex"], row["sex"]),
            "born": row["birth_date"],
            "last_reported": row["last_reported"],
            "weight": weights.get(row["id"]),
        }
        for row in rows
    ]
    return _render(
        mode="utdrag", herd=herd.herd, year=year, rabbits=rabbits, sold=sold, dead=dead, litters=_litters(herd, year)
    )


def _choice(entry):
    if entry.val == "kvar":
        return "Finns kvar"
    if entry.val == "dod":
        return "Död"
    if entry.val == "sald":
        return "Såld " + ("utanför genbanken" if entry.sald["till"] == "utanfor" else f"till {entry.sald['till']}")
    return "Ej angiven"


def receipt_pdf(report, submission) -> bytes:
    """What the submission reported: each rabbit's choice, weight and hull, and the health answer."""
    data = submission.data
    entries = arsrapport._entries(data.get("rabbits") or {})  # pylint: disable=protected-access
    numbers = _numbers(entries)
    rabbits = [
        {
            "number": numbers[rabbit],
            "choice": _choice(entry),
            "when": _when(entry.dod or entry.sald),
            "weight": entry.vikt,
            "hull": _HULL.get(entry.hull),
        }
        for rabbit, entry in sorted(entries.items(), key=lambda item: numbers[item[0]])
    ]
    health = data.get("health")
    diseases = [_disease(name, value) for name, value in (data.get("diseases") or {}).items()]
    named = _numbers(d["individual_id"] for d in data.get("defects") or [])
    defects = [{"number": named.get(d["individual_id"]), "text": d["beskrivning"]} for d in data.get("defects") or []]
    return _render(
        mode="kvittens",
        herd=report.herd.herd,
        year=report.round.report_year,
        received=submission.created_at.astimezone(arsrapport.STOCKHOLM).strftime("%Y-%m-%d %H:%M"),
        rabbits=rabbits,
        health=_HEALTH.get(health, "Sjukdomsfall eller defekter"),
        diseases=diseases,
        defects=defects,
    )


def _disease(name, value):
    label = (value.get("namn") or name) if name == "annat" else name
    return f"{label}: {value['antal']} st" + (f", {value['alder']}" if value.get("alder") else "")


def _when(month):
    return (
        f"{month['ar']}-{month['manad']:02d}" + (f"-{month['dag']:02d}" if month.get("dag") else "") if month else None
    )
