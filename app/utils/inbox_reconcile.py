"""
The reconciliation table (docs/inkorg.md, "Avstämning"): what the handler has typed off a paper certificate, beside
the registry row by row, with the checks in words. It is recomputed as she types and writes nothing.

The proposal (utils/inbox_proposal.py) judges what the model read; this judges only what was typed. A value read but
not typed looks nothing up, since an unconfirmed reading must never pick a parent or a litter: such a row is osäker.
A typed number is looked up as typed, its letter too, and only within the item's genebank. Each row has the
registry's value and a status:

- stammer: what was typed is the registry's value, as saving takes it;
- skiljer: it is not, or a number typed is not in the registry ("finns inte", with the numbers one character off);
- osaker: nothing typed, but the image reading saw something there;
- ingen: the registry has nothing to compare with, or nothing was typed or read.

A rabbit or litter is named only to someone who may read it (GET /v2/individual/<number>: its herd's genebank is one
of theirs); any other is "en kanin i en annan genbank", and nothing is compared with it.
"""

import operator
import re

from utils.database import Breeding, Individual
from utils.inbox_proposal import (
    _PARENTS,
    _SEXES,
    DEVIATES,
    MAX_LISTED,
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
HIDDEN = "en kanin i en annan genbank"
DIGITAL = "digitalt intyg"
NOT_SEARCHED = (
    "Posten har ingen genbank, och individnumret pekar inte ut en genbank du arbetar i. Inget jämförs med registret."
)
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


class _View:
    """What `user` may read: a rabbit in a herd of one of their genebanks, a litter born in one (as the 409 names)."""

    def __init__(self, user):
        self.genebanks = set(user.accessible_genebanks)
        self._seen = {}

    def sees(self, rabbit):
        if rabbit.id not in self._seen:
            self._seen[rabbit.id] = rabbit.current_herd.genebank_id in self.genebanks
        return self._seen[rabbit.id]

    def rabbit(self, rabbit):
        """The rabbit if they may read it, else None."""
        return rabbit if rabbit is not None and self.sees(rabbit) else None

    def litter(self, litter):
        herd = litter.breeding_herd_id if litter is not None else None
        return litter if herd is not None and herd.genebank_id in self.genebanks else None

    def named(self, rabbit):
        return _named(rabbit) if self.sees(rabbit) else HIDDEN


def reconcile(item, document, body, user):
    """
    The rows and checks for what was typed (`body`, untrusted: the form's fields as strings or numbers, `mode` and,
    for a paper certificate on a rabbit in Stamboken, `individual`): {"rows": {key: {registry, status, near?}},
    "checks": [{ok, text}]}. The document's stored proposal says only which rows were read. Only what `user` may read
    is named; the number check names what they would see in the 409 from …/spara.
    """
    body = body if isinstance(body, dict) else {}
    existing = body.get("mode") == "pappersintyg"
    order = ("individual", *ROWS) if existing else ROWS
    typed = {key: _typed(body, key) for key in ("individual", *ROWS)}
    if not existing:
        typed["individual"] = ""
    numbers = {key: _number(typed[key]) for key in ("paper_number", *_RABBITS)}
    proposal = document.proposal if isinstance(document.proposal, dict) else {}
    fields = proposal.get("fields") if isinstance(proposal.get("fields"), dict) else {}
    read = {key for key, field in fields.items() if isinstance(field, dict) and field.get("read")}
    view = _View(user)

    def empty(key, theirs):
        return {"registry": theirs, "status": UNSURE if key in read else NOTHING}

    genebank = item.genebank_id
    if genebank is None:  # the letter typed names one; searched only when it is the user's
        genebank = _genebank_of_letter({"genbanksnr": typed["individual"] or typed["paper_number"]})
        if genebank not in view.genebanks:
            rows = {key: empty(key, None) if not typed[key] else {"registry": None, "status": NOTHING} for key in order}
            return {"rows": rows, "checks": [_check(None, NOT_SEARCHED)]}
    registry = _Registry(genebank)
    found = {key: registry.rabbit(numbers[key]) if numbers[key] else None for key in _RABBITS}
    birth = _date(typed["birth_date"]) if typed["birth_date"] else None
    rows, checks = {}, []

    # The registry's side: the rabbit and its litter, or for a new rabbit the parents typed and their litter. Only
    # what the user may read is compared with, so that no status tells them more than a name would.
    rabbit = view.rabbit(found["individual"])
    fit = {role: r if (r := view.rabbit(found[role])) and _fits(role, r) else None for role in ("mother", "father")}
    if existing:
        litter = view.litter(_litter_of(rabbit))
        parents = _parents(litter)
    else:
        parents = {role: found[role] for role in ("mother", "father")}
        litter = None
        if fit["mother"] and fit["father"] and birth:
            same = (Breeding.mother == fit["mother"].id) & (Breeding.father == fit["father"].id)
            litter = view.litter(Breeding.select().where(same & (Breeding.birth_date == birth)).first())
    theirs_of = {role: _parents(view.litter(_litter_of(view.rabbit(parents[role])))) for role in ("mother", "father")}
    grand = {gp: theirs_of[role][which] for gp, (role, which) in _GRANDPARENTS.items()}

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
            return empty(key, theirs and view.named(theirs))
        if theirs is not None and not view.sees(theirs):
            return {"registry": HIDDEN, "status": NOTHING}
        typed_rabbit = found[key]
        if typed_rabbit is not None and not view.sees(typed_rabbit):
            return {"registry": _named(theirs) if theirs else HIDDEN, "status": DIFFERS if theirs else NOTHING}
        row = {"registry": _named(theirs or typed_rabbit) if theirs or typed_rabbit else NOT_FOUND}
        if typed_rabbit is None or (theirs is not None and typed_rabbit.id != theirs.id):
            row["status"] = DIFFERS
        else:
            row["status"] = MATCH if theirs is not None else NOTHING
        parts = re.fullmatch(r"[A-Z]+(\d+)-(\d+)", numbers[key] or "")
        near = [r for r in registry.near(parts[1], parts[2]) if view.sees(r)] if typed_rabbit is None and parts else []
        if near:
            row["near"] = [{"number": r.number, "name": r.name, "sex": _sex(r.sex)} for r in near]
        return row

    paper = numbers["paper_number"] if parse_number(numbers["paper_number"]) else None
    if paper and registry.letter and paper[0] != registry.letter:
        # Which is wrong, the paper or the item's genebank, the handler sees on the photo.
        checks.append(
            _check(
                False,
                f"Individnumret börjar med {paper[0]} på pappret, men genbankens nummer börjar med {registry.letter}.",
            )
        )
    elif paper and paper.split("-")[0] not in registry.herds:
        checks.append(_check(False, f"Besättningen {paper.split('-')[0]} finns inte i Stamboken."))
    if paper and birth and paper.split("-")[1][:2] != f"{birth:%y}":
        checks.append(_check(False, "Årssiffrorna i individnumret stämmer inte med födelsedatumet."))

    if existing:
        if found["individual"] is not None and rabbit is None:
            checks.append(_check(False, f"{numbers['individual']} är {HIDDEN}."))
        elif rabbit is not None:
            checks.append(_check(None, f"{rabbit.number} finns i Stamboken."))
            if rabbit.digital_certificate is not None:  # AssignPaperCertificate: a paper number replaces it (IR-20)
                checks.append(
                    _check(False, f"{rabbit.number} har digitalt intyg. Sparar du pappersintyget ersätts det digitala.")
                )
        elif typed["individual"]:
            checks.append(_check(False, f"{numbers['individual'] or typed['individual']} finns inte i Stamboken."))
        else:
            checks.append(_check(None, "Skriv kaninens nummer i Stamboken för att jämföra."))
        rows["individual"] = rabbit_row("individual", found["individual"])
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
            elif not view.sees(typed_rabbit):
                problems.append(f"{label} {numbers[role]} är {HIDDEN}.")
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
        rows["paper_number"] = _new_number(registry, view, typed, paper, fit, litter, birth, empty, checks, user)
        if litter is None:
            checks.extend(_litters(view, fit))
    rows["paper_certificate"] = _certificate(view, typed, rabbit, empty, checks)

    rows["name"] = compare("name", rabbit.name if rabbit else None, lambda a, b: a.casefold() == b.casefold())
    rows["sex"] = compare("sex", _sex(rabbit.sex) if rabbit else None, lambda text, theirs: _typed_sex(text) == theirs)
    born = litter.birth_date.isoformat() if litter and litter.birth_date else None
    rows["birth_date"] = compare(
        "birth_date", born, lambda text, theirs: (d := _date(text)) and d.isoformat() == theirs
    )
    # A colour only as it is spelled in the genebank's list: registration looks it up as typed.
    if existing:
        rows["color"] = compare("color", rabbit.color.name if rabbit and rabbit.color_id else None, operator.eq)
    elif typed["color"]:
        listed = next((c for c in registry.colors if c.casefold() == typed["color"].casefold()), None)
        rows["color"] = {"registry": listed or NOT_FOUND, "status": MATCH if listed == typed["color"] else DIFFERS}
    else:
        rows["color"] = empty("color", None)
    for key in ("litter_size", "litter_size6w"):
        rows[key] = compare(key, getattr(litter, key) if litter else None, lambda text, theirs: _count(text) == theirs)

    return {"rows": {key: rows[key] for key in order}, "checks": checks}


def _new_number(registry, view, typed, paper, fit, litter, birth, empty, checks, user):
    """A new rabbit's number: the one Stamboken would give it in its litter (number_check, as for a reading)."""
    if not typed["paper_number"]:
        return empty("paper_number", None)
    if paper is None:
        checks.append(_check(False, PAPER_NUMBER_REQUIRED))
        return {"registry": None, "status": NOTHING}
    taken = registry.rabbit(paper)
    if taken is not None:
        checks.append(_check(False, f"{paper} finns redan i Stamboken. Välj Pappersintyg på en kanin som finns."))
        return {"registry": f"finns redan: {view.named(taken)}", "status": DIFFERS}
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


def _litters(view, fit):
    """With no litter of the parents born that day: a parent's litters in Stamboken, to read the right one off."""
    anchor = next(((role, fit[role]) for role in ("mother", "father") if fit[role]), None)
    if anchor is None:
        return []
    both = Breeding.mother.is_null(False) & Breeding.father.is_null(False)
    query = Breeding.select().where((getattr(Breeding, anchor[0]) == anchor[1].id) & both)
    lines = []
    for other in query.order_by(Breeding.birth_date.desc()).limit(MAX_LISTED):
        if view.litter(other) is None:
            continue
        parts = [f"född {other.birth_date}"]
        for role, word in (("mother", "mor"), ("father", "far")):
            parent = getattr(other, role)
            parts.append(f"{word} {parent.number if view.sees(parent) else HIDDEN}")
        if other.litter_size is not None:
            parts.append(f"{other.litter_size} födda")
        lines.append(_check(None, f"Kull i Stamboken: {', '.join(parts)}."))
    return lines


def _certificate(view, typed, rabbit, empty, checks):
    """
    The certificate number as saving takes it (trimmed, spaces inside kept): the rabbit's own, or a free one. A
    rabbit with a digital certificate has none to compare with, and a free number replaces its digital one.
    """
    value = typed["paper_certificate"]
    own = rabbit.certificate if rabbit is not None else None
    digital = rabbit is not None and rabbit.digital_certificate is not None
    if not value:
        return empty("paper_certificate", own or (DIGITAL if digital else None))
    if own:
        if value == own:
            checks.append(_check(True, "Intygsnumret är kaninens."))
            return {"registry": own, "status": MATCH}
        checks.append(_check(False, f"{rabbit.number} har redan intyg {own} i Stamboken."))
        return {"registry": own, "status": DIFFERS}
    holder = Individual.get_or_none(Individual.certificate == value)
    if holder is None and digital:
        return {"registry": DIGITAL, "status": DIFFERS}  # its check says what saving does
    if holder is None:
        checks.append(_check(True, "Intygsnumret är ledigt."))
        return {"registry": "ledigt", "status": MATCH}
    if not view.sees(holder):
        checks.append(_check(False, f"Intygsnumret {value} används redan."))
        return {"registry": "används redan", "status": DIFFERS}
    checks.append(_check(False, f"Intygsnumret {value} finns redan på {holder.number}."))
    return {"registry": holder.number, "status": DIFFERS}
