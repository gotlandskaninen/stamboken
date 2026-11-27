"""
The reconciliation table (docs/inkorg.md, "Avstämning"): what the handler has typed off a paper certificate, beside
the registry row by row, with the checks in words. It is recomputed as she types and writes nothing.

The proposal (utils/inbox_proposal.py) judges what the model read; this judges only what was typed. A value read but
not typed looks nothing up, since an unconfirmed reading must never pick a parent or a litter: such a row is osäker.
A typed number is looked up as typed, its letter too, and only within the item's genebank. Each row has the
registry's value and a status:

- stammer: what was typed is the registry's value;
- skiljer: it is not, or a number typed is not in the registry ("finns inte", with the numbers one character off);
- osaker: nothing typed, but the image reading saw something there;
- ingen: the registry has nothing to compare with, or nothing was typed or read.
"""

import re

from utils.database import Breeding, Individual
from utils.inbox_proposal import (
    _PARENTS,
    _SEXES,
    DEVIATES,
    READ,
    _check,
    _count,
    _date,
    _genebank_of_letter,
    _number_against_litter,
    _Registry,
    _sex,
)
from utils.individual_number_v2 import PAPER_NUMBER_REQUIRED, parse_number

MATCH, DIFFERS, UNSURE, NOTHING = "stammer", "skiljer", "osaker", "ingen"
NOT_FOUND = "finns inte"
MAX_TYPED = 100  # characters of a typed value looked at; every field of the form is shorter
# The rows in the table's order; a paper certificate on a rabbit in Stamboken also has "individual", first.
ROWS = (
    "paper_number",
    "paper_certificate",
    "name",
    "sex",
    "birth_date",
    "color",
    "litter_size",
    "litter_size6w",
    "mother",
    "morfar",
    "mormor",
    "father",
    "farfar",
    "farmor",
)
_RABBITS = ("individual", "mother", "father", "morfar", "mormor", "farfar", "farmor")
# Each grandparent: the parent it is a parent of, and which of that parent's parents it is.
_GRANDPARENTS = {
    "morfar": ("mother", "father"),
    "mormor": ("mother", "mother"),
    "farfar": ("father", "father"),
    "farmor": ("father", "mother"),
}
_LABELS = {
    "mother": "Mor",
    "father": "Far",
    "morfar": "Morfar",
    "mormor": "Mormor",
    "farfar": "Farfar",
    "farmor": "Farmor",
}


def _typed(body, key):
    """A typed value as a string: "" when it is missing, or neither a string nor a whole number."""
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ""
    return str(value).strip()[:MAX_TYPED]


def _number(text):
    """A typed individual number as the registry writes it (G1-2311), its letter as typed; None for another shape."""
    match = re.fullmatch(r"([A-Z]+)\s*(\d{1,5})\s*[-–\s]\s*(\d{4,5})", text.upper())
    return f"{match[1]}{match[2]}-{match[3]}" if match else None


def _typed_sex(text):
    """female or male, typed as the form's value or as the word."""
    return text if text in ("female", "male") else _SEXES.get(text.upper())


def _named(rabbit):
    return f"{rabbit.number} {rabbit.name}" if rabbit.name else rabbit.number


def _fits(role, rabbit):
    """The rabbit may be the mother (or the father): its sex is that or not known."""
    return not rabbit.sex or rabbit.sex in _PARENTS[role][3]


def _litter_of(rabbit):
    return Breeding.get_or_none(Breeding.id == rabbit.breeding_id) if rabbit is not None else None


def _parents(litter):
    return {role: getattr(litter, role) if litter is not None else None for role in ("mother", "father")}


def reconcile(item, document, body, user):
    """
    The rows and checks for what was typed (`body`, untrusted: the form's fields as strings or numbers, `mode` and,
    for a paper certificate on a rabbit in Stamboken, `individual`): {"rows": {key: {registry, status, near?}},
    "checks": [{ok, text}]}. The document's stored proposal says only which rows were read. The number check names
    what `user` would see in the 409 from …/spara.
    """
    body = body if isinstance(body, dict) else {}
    existing = body.get("mode") == "pappersintyg"
    typed = {key: _typed(body, key) for key in ("individual", *ROWS)}
    if not existing:
        typed["individual"] = ""
    numbers = {key: _number(typed[key]) for key in ("paper_number", *_RABBITS)}
    own = typed["individual"] or typed["paper_number"]
    genebank = item.genebank_id if item.genebank_id is not None else _genebank_of_letter({"genbanksnr": own})
    registry = _Registry(genebank)
    found = {key: registry.rabbit(numbers[key]) if numbers[key] else None for key in _RABBITS}
    proposal = document.proposal if isinstance(document.proposal, dict) else {}
    fields = proposal.get("fields") if isinstance(proposal.get("fields"), dict) else {}
    read = {key for key, field in fields.items() if isinstance(field, dict) and field.get("read")}
    birth = _date(typed["birth_date"]) if typed["birth_date"] else None
    rows, checks = {}, []

    # The registry's side: the rabbit and its litter, or for a new rabbit the parents typed and their litter.
    rabbit = found["individual"]
    fit = {role: found[role] if found[role] and _fits(role, found[role]) else None for role in ("mother", "father")}
    if existing:
        litter = _litter_of(rabbit)
        parents = _parents(litter)
    else:
        parents = {role: found[role] for role in ("mother", "father")}
        both = fit["mother"] and fit["father"] and birth
        litter = (
            Breeding.select()
            .where(
                (Breeding.mother == fit["mother"].id)
                & (Breeding.father == fit["father"].id)
                & (Breeding.birth_date == birth)
            )
            .first()
            if both
            else None
        )
    theirs_of = {role: _parents(_litter_of(parents[role])) for role in ("mother", "father")}
    grand = {gp: theirs_of[role][which] for gp, (role, which) in _GRANDPARENTS.items()}

    def empty(key, theirs):
        return {"registry": theirs, "status": UNSURE if key in read else NOTHING}

    def compare(key, theirs, same):
        """A row the registry has `theirs` for (None: nothing to compare with)."""
        if not typed[key]:
            return empty(key, theirs)
        if theirs is None:
            return {"registry": None, "status": NOTHING}
        return {"registry": theirs, "status": MATCH if same(typed[key], theirs) else DIFFERS}

    def rabbit_row(key, theirs):
        """A number row whose rabbit in the registry is `theirs` (None: nothing to compare with)."""
        if not typed[key]:
            return empty(key, theirs and _named(theirs))
        typed_rabbit = found[key]
        row = {"registry": _named(theirs or typed_rabbit) if theirs or typed_rabbit else NOT_FOUND}
        if typed_rabbit is None or (theirs is not None and typed_rabbit.id != theirs.id):
            row["status"] = DIFFERS
        else:
            row["status"] = MATCH if theirs is not None else NOTHING
        parts = re.fullmatch(r"[A-Z]+(\d+)-(\d+)", numbers[key] or "")
        if typed_rabbit is None and parts and (near := registry.near(parts[1], parts[2])):
            row["near"] = [{"number": r.number, "name": r.name, "sex": _sex(r.sex)} for r in near]
        return row

    paper = numbers["paper_number"]
    if paper and registry.letter and paper[0] != registry.letter:
        # Which is wrong, the paper or the item's genebank, the handler sees on the photo.
        checks.append(
            _check(
                False,
                f"Individnumret börjar med {paper[0]} på pappret, men genbankens nummer börjar med {registry.letter}.",
            )
        )

    if existing:
        if rabbit is not None:
            checks.append(_check(None, f"{rabbit.number} finns i Stamboken."))
        elif typed["individual"]:
            checks.append(_check(False, f"{numbers['individual'] or typed['individual']} finns inte i Stamboken."))
        else:
            checks.append(_check(None, "Skriv kaninens nummer i Stamboken för att jämföra."))
        rows["individual"] = rabbit_row("individual", rabbit)
        rows["paper_number"] = compare("paper_number", rabbit and rabbit.number, lambda _, theirs: paper == theirs)
        for role in ("mother", "father"):
            rows[role] = rabbit_row(role, parents[role])
    else:
        problems = []
        for role in ("mother", "father"):
            label, typed_rabbit = _LABELS[role], found[role]
            rows[role] = rabbit_row(role, typed_rabbit)
            if not typed[role]:
                problems.append(f"{label} saknas.")
            elif typed_rabbit is None:
                problems.append(f"{label} {numbers[role] or typed[role]} finns inte i Stamboken.")
            elif not fit[role]:
                sex = "en hona" if typed_rabbit.sex == "female" else "en hane"
                problems.append(f"{label} {typed_rabbit.number} är {sex} i Stamboken.")
                word = "hona" if typed_rabbit.sex == "female" else "hane"
                rows[role] = {"registry": f"{_named(typed_rabbit)} ({word})", "status": DIFFERS}
        checks.extend(_check(False, text) for text in problems)
        if not problems:
            checks.append(_check(True, "Mor och far finns i Stamboken."))
    for gp, (role, _) in _GRANDPARENTS.items():
        rows[gp] = rabbit_row(gp, grand[gp])
        if numbers[gp] and numbers[gp] == numbers[role]:
            checks.append(_check(False, f"{_LABELS[gp]} har samma nummer som {_LABELS[role].lower()}."))

    if not existing:
        rows["paper_number"] = _new_number(registry, typed, paper, fit, litter, birth, empty, checks, user)
    rows["paper_certificate"] = _certificate(registry, typed, rabbit, empty, checks)

    def casefold(a, b):
        return a.casefold() == b.casefold()

    rows["name"] = compare("name", rabbit.name if existing and rabbit else None, casefold)
    sex = _sex(rabbit.sex) if existing and rabbit else None
    rows["sex"] = compare("sex", sex, lambda text, theirs: _typed_sex(text) == theirs)
    born = litter.birth_date.isoformat() if litter and litter.birth_date else None
    rows["birth_date"] = compare(
        "birth_date", born, lambda text, theirs: (d := _date(text)) and d.isoformat() == theirs
    )
    if existing:
        color = rabbit.color.name if rabbit and rabbit.color_id else None
        rows["color"] = compare("color", color, casefold)
    elif typed["color"]:
        listed = next((c for c in registry.colors if casefold(c, typed["color"])), None)
        rows["color"] = {"registry": listed or NOT_FOUND, "status": MATCH if listed else DIFFERS}
    else:
        rows["color"] = empty("color", None)
    for key in ("litter_size", "litter_size6w"):
        rows[key] = compare(key, getattr(litter, key) if litter else None, lambda text, theirs: _count(text) == theirs)

    order = ("individual", *ROWS) if existing else ROWS
    return {"rows": {key: rows[key] for key in order}, "checks": checks}


def _new_number(registry, typed, paper, fit, litter, birth, empty, checks, user):
    """A new rabbit's number: the one Stamboken would give it in its litter (number_check, as for a reading)."""
    if not typed["paper_number"]:
        return empty("paper_number", None)
    if paper is None or parse_number(paper) is None:
        checks.append(_check(False, PAPER_NUMBER_REQUIRED))
        return {"registry": None, "status": NOTHING}
    taken = registry.rabbit(paper)
    if taken is not None:
        checks.append(_check(False, f"{paper} finns redan i Stamboken. Välj Pappersintyg på en kanin som finns."))
        return {"registry": f"finns redan: {_named(taken)}", "status": DIFFERS}
    if not (fit["mother"] and fit["father"] and birth):
        checks.append(_check(None, "Individnumret går inte att pröva mot kullen utan mor, far och födelsedatum."))
        return {"registry": None, "status": NOTHING}
    scratch = {}
    _number_against_litter(registry, paper, False, typed["paper_number"], litter, fit, birth, scratch, checks, user)
    field = scratch["paper_number"]
    if field["source"] == DEVIATES:
        return {"registry": field.get("registry"), "status": DIFFERS}
    if field["source"] == READ:
        return {"registry": paper, "status": MATCH}
    return {"registry": None, "status": NOTHING}  # the litter gives no number to compare with


def _certificate(registry, typed, rabbit, empty, checks):
    """The certificate number: the rabbit's own, or a free one. A holder in another genebank is not named."""
    value = re.sub(r"\s", "", typed["paper_certificate"])
    own = rabbit.certificate if rabbit is not None else None
    if not value:
        return empty("paper_certificate", own)
    if own:
        if value == own:
            checks.append(_check(True, "Intygsnumret är kaninens."))
            return {"registry": own, "status": MATCH}
        checks.append(_check(False, f"{rabbit.number} har redan intyg {own} i Stamboken."))
        return {"registry": own, "status": DIFFERS}
    holder = registry._rabbits(Individual.certificate == value).first()
    if holder is None and not Individual.select().where(Individual.certificate == value).exists():
        checks.append(_check(True, "Intygsnumret är ledigt."))
        return {"registry": "ledigt", "status": MATCH}
    if holder is None:
        checks.append(_check(False, f"Intygsnumret {value} används redan."))
        return {"registry": "används redan", "status": DIFFERS}
    checks.append(_check(False, f"Intygsnumret {value} finns redan på {holder.number}."))
    return {"registry": holder.number, "status": DIFFERS}
