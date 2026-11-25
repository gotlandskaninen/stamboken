"""The genetics work list (Avelsprioritet): the priorities with each rabbit's details, and its CSV file."""

import csv
import io
import logging
import re
from decimal import ROUND_HALF_UP, Decimal

import utils.data_access as da
from utils.csv_safe import csv_safe

logger = logging.getLogger(__name__)

LEVELS = ("critical", "important", "normal")
LEVEL_LABEL = {"critical": "Högsta", "important": "Hög", "normal": "Övriga"}
SEX_LABEL = {"female": "Hona", "male": "Hane", "eunuch": "Hane (kastrerad)"}  # eunuch: a legacy value
HEADER = [
    "Individnummer",
    "Namn",
    "Besättning",
    "Kön",
    "Född",
    "Avelsprioritet",
    "Ovanliga gener (0–100)",
    "Unika gener (%)",
    "Skäl",
]


def with_details(priorities):
    """New rows with each rabbit's name, sex, birth date and current herd; without them when reading fails."""
    try:
        details = da.work_list_details([p["individual_id"] for p in priorities])
    except Exception:  # pylint: disable=broad-except  # the priorities are worth showing without the details
        logger.exception("Could not read the work list details")
        details = {}
    return [{**p, **details.get(p["individual_id"], {})} for p in priorities]


def _herd_key(herd):
    """G9 before G10, as the page's per-herd order."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", herd or "")]


def select(rows, levels, per_herd):
    """The rows of the chosen levels, in the list's order or per herd within each level."""
    rows = [r for r in rows if r["priority"] in levels]
    if per_herd:
        rows.sort(key=lambda r: (LEVELS.index(r["priority"]), _herd_key(r.get("herd"))))
    return rows


def _fixed(x, digits):
    """x with `digits` decimals and a decimal comma, rounded as the page's toLocaleString: a tie goes up."""
    return str(Decimal(x).quantize(Decimal(10) ** -digits, rounding=ROUND_HALF_UP)).replace(".", ",")


def _pct(value, digits):
    return _fixed(float(value) * 100, digits) + "\u00a0%"


# The page's Swedish for the priority reasons (next-app/src/utils/translateReasons.ts); keep the two in step.
_REASONS = [
    (
        re.compile(r"^Sole active carrier of founder (.+)$"),
        lambda own, founder: (
            "Är själv founderdjur och har inga ättlingar i beräkningen"
            if founder == own
            else f"Enda kaninen i beräkningen med gener från founderdjuret {founder}"
        ),
    ),
    (
        re.compile(r"^Mean kinship ([\d.]+) is below 5th percentile \(([\d.]+)\)$"),
        lambda own, mk, limit: (
            f"Medelsläktskap {_pct(mk, 2)}, på eller under gränsen för de 5\u00a0% minst släkta ({_pct(limit, 2)})"
        ),
    ),
    (
        re.compile(r"^Mean kinship ([\d.]+) is below 25th percentile \(([\d.]+)\)$"),
        lambda own, mk, limit: (
            f"Medelsläktskap {_pct(mk, 2)}, på eller under gränsen för de 25\u00a0% minst släkta ({_pct(limit, 2)})"
        ),
    ),
    (
        re.compile(r"^Genome uniqueness ([\d.]+) is above 75th percentile \(([\d.]+)\)$"),
        lambda own, gu, limit: (
            f"Unika gener {_pct(gu, 1)}, över gränsen för de 25\u00a0% med flest unika gener ({_pct(limit, 1)})"
        ),
    ),
    (
        re.compile(r"^Carries underrepresented founder (.+)$"),
        lambda own, founder: (
            "Är själv founderdjur, med liten andel av generna i beräkningen"
            if founder == own
            else f"Bär gener från founderdjuret {founder}, som har liten andel av generna i beräkningen"
        ),
    ),
    (re.compile(r"^Genetic representation within normal range$"), lambda own: "–"),
]


def swedish_reason(reason, own_number):
    for pattern, text in _REASONS:
        match = pattern.match(reason)
        if match:
            return text(own_number, *match.groups())
    return reason


def priorities_csv(rows):
    """The rows for Excel: BOM, semicolons, every cell quoted, text cells formula-safe."""
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(HEADER)
    for r in rows:
        number = r["individual_id"]
        writer.writerow(
            [
                csv_safe(number),
                csv_safe(r.get("name")),
                csv_safe(r.get("herd")),
                # No details (the number is gone from the database): empty, like the other details.
                SEX_LABEL.get(r["sex"], "Okänt") if "sex" in r else "",
                csv_safe(r.get("birth_date")),
                LEVEL_LABEL[r["priority"]],
                _fixed(r["genetic_value_score"], 0),
                _fixed(r["genome_uniqueness"] * 100, 1),
                csv_safe("; ".join(swedish_reason(reason, number) for reason in r["reasons"])),
            ]
        )
    return buf.getvalue()
