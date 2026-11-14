"""
The proposal from an interpreted certificate (docs/inkorg.md, "Tolkning"): what the model read, checked against
the registry and the pedigree, as fields for the registration form and a list of checks in words.

The model would rather guess than leave a field empty, so how sure a field is comes from the checks, never from
the model. Every field has a source:

- läst: read and confirmed by the registry (a parent by its own parents, the rabbit's number by its litter), or,
  where the registry has nothing to say, read and valid (a name, a colour from the genebank's list);
- härlett: taken from the registry (a number one character off, a grandparent of a confirmed parent, a litter);
- avviker: the certificate as read and the registry disagree; both are shown and nothing here chooses;
- osäker: anything else, and always a value struck through or corrected on the paper.

Only läst and härlett fields carry a value into the form. avviker and osäker show what was read (and the registry's
value) beside an empty field, for the handler to read off the photo. Everything is searched within the item's
genebank, since rabbits never change genebank.
"""

import difflib
import re
import unicodedata
from datetime import date, timedelta
from types import SimpleNamespace

from utils.database import Breeding, Color, Herd, Individual, not_voided
from utils.individual_number_v2 import number_check

READ, DERIVED, DEVIATES, UNSURE = "läst", "härlett", "avviker", "osäker"
# Each parent: its key on the certificate, its father's and its mother's, the sexes it may have, its label.
_PARENTS = {
    "mother": ("mor", "morfar", "mormor", ("female",), "Mor"),
    "father": ("far", "farfar", "farmor", ("male", "eunuch"), "Far"),
}
# The kinds of number_check conflict that say the paper's number is not the one its litter gives.
_NUMBER_CONFLICTS = {"prefix", "year", "litter", "litter_missing", "litter_order", "position", "number_taken"}
SAME_LITTER_DAYS = 35  # a litter of the same parents this close is the certificate's, registered on another date
MAX_LISTED = 5  # litters listed for the handler when nothing read picks one
_DIGIT_FOR = str.maketrans({"S": "5", "s": "5", "O": "0", "o": "0", "l": "1", "I": "1", "|": "1"})
_SEVERAL, _NONE = "liknar flera kaniner i Stamboken", "finns inte i Stamboken"  # why a number read was not found
_SEXES = {"HONA": "female", "HANE": "male"}


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _entry(raw, key):
    value = raw.get(key)
    return value if isinstance(value, dict) else {}


def _field(source, value=None, read=None, registry=None):
    """A proposed field. Only läst and härlett carry a value into the form."""
    field = {"value": value if source in (READ, DERIVED) else None, "source": source}
    if read:
        field["read"] = read
    if registry is not None:
        field["registry"] = registry
    return field


def _check(ok, text):
    """A line under the form: ok True passed, False failed, None for information."""
    return {"ok": ok, "text": text}


def _one_off(a, b):
    """a and b differ in at most one character: one changed, added or left out."""
    if a == b:
        return True
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1
    short, long = sorted((a, b), key=len)
    return len(long) - len(short) == 1 and any(long[:i] + long[i + 1 :] == short for i in range(len(long)))


def _digits(text):
    """(digits, swapped) without spaces, dots and dashes; letters read as digits (S, O, l) only as swapped."""
    clean = re.sub(r"[\s.,\-–]", "", text)
    if re.fullmatch(r"[0-9]+", clean):
        return clean, False
    swapped = clean.translate(_DIGIT_FOR)
    return (swapped, True) if re.fullmatch(r"[0-9]+", swapped) else (None, False)


def _number_text(entry):
    return " ".join(part for part in (_text(entry.get("genbanksnr")), _text(entry.get("ar_kull_individ"))) if part)


def _parse_number(entry, letter):
    """
    (herd digits, individual digits, swapped) of a number on the certificate, or None when it has no such shape.
    Written in one field ("G1274-2512") it is split. Letters read as digits, or a letter that is not the
    genebank's, make it swapped: such a number is never läst.
    """
    herd, ind = _text(entry.get("genbanksnr")), _text(entry.get("ar_kull_individ"))
    if not ind and (both := re.fullmatch(r"(.+?)[\s\-–]+(\S{4,5})", herd)):
        herd, ind = both[1], both[2]
    prefix = re.fullmatch(r"([A-Za-z]?)\s*(.+)", herd)
    if prefix is None or not ind:
        return None
    herd_digits, herd_swapped = _digits(prefix[2])
    ind_digits, ind_swapped = _digits(ind)
    if not herd_digits or len(herd_digits) > 5 or not ind_digits or len(ind_digits) not in (4, 5):
        return None
    return herd_digits, ind_digits, herd_swapped or ind_swapped or prefix[1].upper() not in ("", letter)


def _date(text):
    """A date written ÅÅÅÅ-MM-DD (dashes optional), ÅÅMMDD or D/M-ÅÅ (or -ÅÅÅÅ); None otherwise or in the future."""
    text = re.sub(r"\s+", " ", text.strip().rstrip("."))
    for pattern, order in (
        (r"(\d{4})-?(\d{2})-?(\d{2})", "ymd"),
        (r"(\d{2})(\d{2})(\d{2})", "ymd"),
        (r"(\d{1,2})/(\d{1,2})[-/ ]?(\d{4}|\d{2})", "dmy"),
    ):
        if match := re.fullmatch(pattern, text):
            parts = {key: int(value) for key, value in zip(order, match.groups(), strict=True)}
            try:
                found = date(parts["y"] + (2000 if parts["y"] < 100 else 0), parts["m"], parts["d"])
            except ValueError:
                return None
            return found if found <= date.today() else None
    return None


def _count(text):
    match = re.fullmatch(r"(\d{1,2})\s*(st\.?)?", text, re.IGNORECASE)
    return int(match[1]) if match else None


def _same_name(a, b):
    a, b = (
        re.sub(r"[^A-Z]", "", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper())
        for s in (a, b)
    )
    return bool(a and b) and (a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8)


def _has_certificate(rabbit):
    return bool(rabbit.certificate) or rabbit.digital_certificate is not None


def _sex(value):
    return {"eunuch": "male"}.get(value, value)


def _littermate_doubt(rabbit, name):
    """
    Littermates share their parents and their birth date, so nothing in the pedigree tells them apart, and a
    misread individual digit lands exactly on one. A rabbit with a littermate of its sex (or of an unknown sex)
    is therefore only told apart by its name: the doubt, unless the name read is its own and no such littermate's.
    """
    if rabbit.breeding_id is None:
        return None
    mates = Individual.select().where(
        (Individual.breeding == rabbit.breeding_id) & (Individual.id != rabbit.id) & not_voided()
    )
    alike = [m for m in mates if not (rabbit.sex and m.sex) or _sex(m.sex) == _sex(rabbit.sex)]
    if not alike:
        return None
    if (
        name
        and rabbit.name
        and _same_name(name, rabbit.name)
        and not any(_same_name(name, m.name or "") for m in alike)
    ):
        return None
    return f"{rabbit.number} har ett kullsyskon av samma kön, och namnet på intyget skiljer dem inte åt"


class _Registry:
    """The genebank's registry, as the checks ask it."""

    def __init__(self, genebank_id):
        self.genebank_id = genebank_id
        self.herds = {code for (code,) in Herd.select(Herd.herd).where(Herd.genebank == genebank_id).tuples()}
        self.letter = min(self.herds)[0] if self.herds else ""
        self.colors = [name for (name,) in Color.select(Color.name).where(Color.genebank == genebank_id).tuples()]

    def _rabbits(self, where):
        query = Individual.select().join(Herd, on=Individual.origin_herd == Herd.id)
        return query.where(where & (Herd.genebank == self.genebank_id) & not_voided())

    def rabbit(self, number):
        """The live rabbit with the number in this genebank, or None."""
        return self._rabbits(Individual.number == number).first()

    def find(self, parsed):
        """
        (rabbit, how) for a number read: READ when it is in the registry as read; DERIVED when letters were read
        as digits, or its herd is one character off and only one rabbit fits (rule 4); else (None, a reason).
        """
        herd, ind, swapped = parsed
        rabbit = self.rabbit(f"{self.letter}{herd}-{ind}")
        if rabbit is not None:
            return rabbit, DERIVED if swapped else READ
        near = [r for r in self._rabbits(Individual.number.endswith(f"-{ind}")) if self._near(r.number, herd, ind)]
        if len(near) == 1:
            return near[0], DERIVED
        return None, _SEVERAL if near else _NONE

    @staticmethod
    def _near(number, herd, ind):
        match = re.fullmatch(r"[A-Z](\d+)-(\d+)", number)
        return match is not None and match[2] == ind and _one_off(match[1], herd)

    def compare(self, parsed, expected):
        """
        How a number read fits the registry's rabbit `expected`: READ or DERIVED when it finds that rabbit (as
        find does: one character off only when no other rabbit fits), "differs" when it finds another or none,
        None (unknown) when it cannot be read or fits several.
        """
        if parsed is None or expected is None:
            return None
        rabbit, how = self.find(parsed)
        if rabbit is not None:
            return how if rabbit.id == expected.id else "differs"
        return None if how == _SEVERAL else "differs"


def _branch(registry, raw, struck, role, fields, checks):
    """
    A parent and its parents (rule 3). The parent is confirmed when its number is in the registry and the
    registry's parents of it agree with the certificate's: one of them at least, and neither against; a parent
    with a littermate of its sex, whom its parents cannot tell apart, also by its name. Its parents
    are then proposed from the registry (rule 3: only under a confirmed parent). A disagreement marks the whole
    branch, since the parent may as well be the one misread. Returns (the confirmed parent, the rabbit found if
    nothing ruled it out but a lack of grandparents to compare), each None otherwise.
    """
    key, father_key, mother_key, sexes, label = _PARENTS[role]
    entry = _entry(raw, key)
    text = _number_text(entry)
    if not text:
        return None, None
    if key in struck:
        fields[role] = _field(UNSURE, read=text)
        checks.append(_check(False, f"{label}: numret är överstruket eller rättat på intyget."))
        return None, None
    parsed = _parse_number(entry, registry.letter)
    rabbit, how = registry.find(parsed) if parsed else (None, "numret går inte att läsa")
    if rabbit is None:
        fields[role] = _field(UNSURE, read=text)
        checks.append(_check(False, f"{label}: {text} {how}." if parsed else f"{label}: {how}."))
        return None, None
    litter = Breeding.get_or_none(Breeding.id == rabbit.breeding_id)
    grandparents = []
    for gp_key, theirs in ((father_key, litter and litter.father), (mother_key, litter and litter.mother)):
        gp_entry = _entry(raw, gp_key)
        parsed_gp = None if gp_key in struck else _parse_number(gp_entry, registry.letter)
        grandparents.append((gp_key, _number_text(gp_entry), theirs, registry.compare(parsed_gp, theirs)))

    if any(result == "differs" for *_, result in grandparents):
        # A number read as it stands is a known disagreement; one this code derived is merely unsure.
        source = DEVIATES if how == READ else UNSURE
        fields[role] = _field(source, read=text)
        for gp_key, gp_text, theirs, _ in grandparents:
            fields[gp_key] = _field(source, read=gp_text or None, registry=theirs.number if theirs else None)
        checks.append(
            _check(False, f"{label}: far- och morföräldrarna på intyget är inte registrets för {rabbit.number}.")
        )
        return None, None

    doubts = []  # its sex and its name rule the rabbit out, also as the anchor of the registry's litters
    if rabbit.sex and rabbit.sex not in sexes:
        doubts.append(f"{rabbit.number} är {'en hona' if rabbit.sex == 'female' else 'en hane'} i Stamboken")
    name = _text(entry.get("namn"))
    if name and rabbit.name and not _same_name(name, rabbit.name):
        doubts.append(f"namnet på intyget är inte registrets ({rabbit.name})")
    elif sibling := _littermate_doubt(rabbit, name):
        doubts.append(sibling)
    compared = any(result in (READ, DERIVED) for *_, result in grandparents)
    if not compared:
        doubts.append(f"far- och morföräldrarna går inte att jämföra med registrets för {rabbit.number}")
    if doubts:
        fields[role] = _field(UNSURE, read=text)
        for gp_key, gp_text, _, _ in grandparents:
            if gp_text:
                fields[gp_key] = _field(UNSURE, read=gp_text)
        checks.append(_check(False, f"{label}: {'; '.join(doubts)}."))
        return None, rabbit if len(doubts) == 1 and not compared else None

    fields[role] = _field(how, rabbit.number, read=text)
    for gp_key, gp_text, theirs, result in grandparents:
        if gp_key in struck or (theirs is None and gp_text):
            fields[gp_key] = _field(UNSURE, read=gp_text)
        elif theirs is not None:
            fields[gp_key] = _field(result or DERIVED, theirs.number, read=gp_text or None)
    return rabbit, rabbit


def _litter_line(litter):
    parts = [f"född {litter.birth_date}", f"mor {litter.mother.number if litter.mother else 'okänd'}"]
    parts.append(f"far {litter.father.number if litter.father else 'okänd'}")
    if litter.litter_size is not None:
        parts.append(f"{litter.litter_size} födda")
    return _check(None, f"Kull i Stamboken: {', '.join(parts)}.")


def _registry_litter(registry, raw, struck, found, birth, herd_id, year, fields, checks):
    """
    The registry's help when the parents are not both confirmed: a parent found (one the checks did not rule
    out) gives its litters, or with no parent read at all, the uploader's herd gives its litters of the year.
    Only a single litter born on the date read fills the form (härlett), and only where every parent on the
    certificate fits it: one read otherwise is a disagreement, and one struck through or ruled out by the checks
    is not taken back here. Otherwise the litters are listed for the handler. Returns the litter that filled it.
    """
    anchor = next(((role, found[role]) for role in ("mother", "father") if found[role] is not None), None)
    if anchor is not None:
        query = Breeding.select().where(getattr(Breeding, anchor[0]) == anchor[1].id)
    elif not any(role in fields for role in found) and herd_id is not None:
        query = Breeding.select().where(
            (Breeding.breeding_herd_id == herd_id) & Breeding.birth_date.between(date(year, 1, 1), date(year, 12, 31))
        )
    else:
        return None
    query = query.where(Breeding.mother.is_null(False) & Breeding.father.is_null(False))
    picked = list(query.where(Breeding.birth_date == birth)) if birth else []
    if len(picked) != 1:
        checks.extend(_litter_line(litter) for litter in query.order_by(Breeding.birth_date.desc()).limit(MAX_LISTED))
        return None
    litter = picked[0]
    verdict = {}
    for role in ("mother", "father"):
        theirs, key = getattr(litter, role), _PARENTS[role][0]
        if found[role] is not None:
            verdict[role] = "fits" if found[role].id == theirs.id else "clash"
        elif key in struck:
            verdict[role] = "hold"
        else:
            parsed = _parse_number(_entry(raw, key), registry.letter)
            rabbit, how = registry.find(parsed) if parsed else (None, None)
            if rabbit is not None:
                verdict[role] = "hold" if rabbit.id == theirs.id else "clash"
            else:
                verdict[role] = "clash" if how == _NONE else "fits"
    if "clash" in verdict.values():
        for role in (role for role, v in verdict.items() if v == "clash"):
            fields[role] = _field(DEVIATES, read=fields[role].get("read"), registry=getattr(litter, role).number)
        checks.append(_check(False, f"Kullen född {birth} i Stamboken har en annan mor eller far än intyget."))
        return None
    if "hold" in verdict.values():
        checks.append(_litter_line(litter))
        return None
    for role in ("mother", "father"):
        current = fields.get(role)
        if current is None or current["source"] == UNSURE:
            fields[role] = _field(DERIVED, getattr(litter, role).number, read=current and current.get("read"))
    checks.append(_check(None, f"Mor och far är hämtade ur Stamboken, ur kullen född {birth}."))
    return litter


def _viewer(genebank_id):
    """number_check names the rabbits and litters it finds to someone who may see them: here, the genebank's."""
    return SimpleNamespace(accessible_genebanks=[genebank_id], is_manager=None, is_admin=False)


def _number_against_litter(registry, paper, swapped, own_text, litter, parents, birth, fields, checks):
    """The rabbit's number against its litter: the paper-number conflict rule of registration (rule 5)."""
    mother, father = parents["mother"], parents["father"]
    if litter is not None:
        check = number_check(_viewer(registry.genebank_id), paper, breeding=litter)
    elif (herd := mother.current_herd) is not None:
        litter_facts = {"herd": herd, "birth_date": birth, "mother": mother, "father": father}
        check = number_check(_viewer(registry.genebank_id), paper, **litter_facts)
    else:
        check = {"status": "uncomputable", "conflicts": []}
    kinds = {conflict["kind"] for conflict in check["conflicts"]}
    if kinds & _NUMBER_CONFLICTS:
        theirs = check.get("stamboken_number")
        fields["paper_number"] = _field(DEVIATES, read=own_text, registry=theirs)
        given = f" Stamboken ger {theirs}." if theirs else ""
        checks.append(_check(False, f"Individnumret stämmer inte med kullen.{given}"))
    elif check["status"] == "uncomputable":
        fields["paper_number"] = _field(UNSURE, read=own_text)
        checks.append(_check(None, "Individnumret gick inte att pröva mot kullen."))
    else:
        fields["paper_number"] = _field(DERIVED if swapped else READ, paper, read=own_text)
        checks.append(_check(True, "Numret stämmer med kullen."))
    for conflict in check["conflicts"]:
        held = (conflict.get("holder") or {}).get("number")
        if conflict["kind"] == "duplicate_rabbit" and conflict["paper"] is None:
            checks.append(_check(None, f"{held or 'En kanin'} i kullen saknar intyg. Är det samma kanin?"))
        elif conflict["kind"] == "duplicate_litter":
            checks.append(_check(None, f"Modern har en annan kull, född {conflict['stamboken']}."))


def _litter_counts(raw, struck, litter, fields, checks):
    """Born and alive at six weeks: read, against the registry's litter when there is one."""
    counts = {}
    for key, raw_key in (("litter_size", "fodda_i_kullen"), ("litter_size6w", "levande_efter_6_veckor")):
        text = _text(raw.get(raw_key))
        count = None if raw_key in struck else _count(text)
        counts[key] = (text, count if count else None)  # a litter has at least one, as registration requires
        theirs = getattr(litter, key) if litter is not None else None
        if theirs is not None and not text:
            fields[key] = _field(DERIVED, theirs)
        elif theirs is not None and counts[key][1] is not None:
            if counts[key][1] == theirs:
                fields[key] = _field(READ, theirs, read=text)
            else:
                fields[key] = _field(DEVIATES, read=text, registry=theirs)
                checks.append(_check(False, f"Kullen har {theirs} i Stamboken där intyget säger {text}."))
        elif text:
            fields[key] = _field(READ, counts[key][1], read=text) if counts[key][1] else _field(UNSURE, read=text)
    born, alive = counts["litter_size"][1], counts["litter_size6w"][1]
    if born is not None and alive is not None and alive > born and litter is None:
        fields["litter_size"] = _field(UNSURE, read=counts["litter_size"][0])
        fields["litter_size6w"] = _field(UNSURE, read=counts["litter_size6w"][0])
        checks.append(_check(False, "Fler levande efter 6 veckor än födda i kullen."))


def _certificate(raw, struck, rabbit, fields, checks):
    """The certificate number: free, or already the rabbit's (rule 5)."""
    text = _text(raw.get("intygsnummer"))
    number = re.sub(r"\s", "", text)
    if not number:
        return
    if "intygsnummer" in struck or len(number) > Individual.certificate.max_length:
        fields["paper_certificate"] = _field(UNSURE, read=text)
        return
    holder = Individual.get_or_none(Individual.certificate == number)
    if holder is None or (rabbit is not None and holder.id == rabbit.id):
        fields["paper_certificate"] = _field(READ, number, read=text)
        checks.append(_check(True, "Intygsnumret är ledigt." if holder is None else "Intygsnumret är kaninens."))
    else:
        fields["paper_certificate"] = _field(DEVIATES, read=text, registry=holder.number)
        checks.append(_check(False, f"Intygsnumret {number} finns redan på {holder.number}."))


def _plain_fields(registry, raw, struck, fields):
    """Name, sex and colour: nothing in the registry confirms them for a new rabbit, so read and valid is läst."""
    name = _text(raw.get("namn"))
    if name:
        fields["name"] = _field(UNSURE if "namn" in struck or len(name) > 50 else READ, name, read=name)
    sex_text = _text(raw.get("kon"))
    if sex_text:
        word = re.sub(r"[^A-ZÅÄÖ]", "", sex_text.upper())
        near = [sex for spelled, sex in _SEXES.items() if _one_off(spelled, word)]
        if "kon" in struck or len(near) != 1:
            fields["sex"] = _field(UNSURE, read=sex_text)
        else:
            fields["sex"] = _field(READ if word in _SEXES else DERIVED, near[0], read=sex_text)
    color_text = _text(raw.get("farg"))
    if color_text:
        listed = next((c for c in registry.colors if c.casefold() == color_text.casefold()), None)
        ok = listed and "farg" not in struck
        fields["color"] = _field(READ, listed, read=color_text) if ok else _field(UNSURE, read=color_text)


def _existing(registry, raw, struck, rabbit, own_text, swapped):
    """
    A certificate of a rabbit already in Stamboken: the paper certificate to put on it, or for a digital one
    nothing more. Either way its parents and birth date must agree with the registry, and its sex and name must
    not disagree. That does not tell a rabbit from a littermate of its sex, which has the same parents and birth
    date and is one misread digit away: such a rabbit is läst only when the name read is its own.
    """
    doubts = []
    sex = _SEXES.get(re.sub(r"[^A-ZÅÄÖ]", "", _text(raw.get("kon")).upper()))
    if sex and rabbit.sex and sex != _sex(rabbit.sex):
        doubts.append(f"Könet på intyget är inte registrets för {rabbit.number}.")
    name = _text(raw.get("namn"))
    if name and rabbit.name and not _same_name(name, rabbit.name):
        doubts.append(f"Namnet på intyget är inte registrets för {rabbit.number} ({rabbit.name}).")
    elif sibling := _littermate_doubt(rabbit, name):
        doubts.append(f"{sibling}.")

    fields, checks = {}, [_check(None, f"{rabbit.number} finns redan i Stamboken.")]
    checks.extend(_check(False, doubt) for doubt in doubts)
    litter = Breeding.get_or_none(Breeding.id == rabbit.breeding_id)
    results = []
    for role in ("mother", "father"):
        key = _PARENTS[role][0]
        parsed = None if key in struck else _parse_number(_entry(raw, key), registry.letter)
        results.append(registry.compare(parsed, litter and getattr(litter, role)))
    birth = None if "fodelsedatum" in struck else _date(_text(raw.get("fodelsedatum")))
    born_else = birth and litter is not None and litter.birth_date and birth != litter.birth_date
    if "differs" in results or born_else:  # another rabbit's certificate as likely as a misread one
        source = DEVIATES
        if "differs" in results:
            checks.append(_check(False, f"Mor eller far på intyget är inte registrets för {rabbit.number}."))
        if born_else:
            checks.append(_check(False, f"Intyget säger född {birth}, Stamboken {litter.birth_date}."))
    elif doubts or not any(result in (READ, DERIVED) for result in results):
        source = UNSURE
        if not doubts:
            checks.append(_check(False, "Föräldrarna på intyget går inte att jämföra med registrets."))
    else:
        source = DERIVED if swapped else READ
        checks.append(_check(True, "Föräldrarna på intyget stämmer med registret."))
    if rabbit.digital_certificate is not None and source == READ:
        fields = {"individual": _field(READ, rabbit.number, read=own_text)}
        return {"fields": fields, "checks": [_check(True, f"{rabbit.number} finns redan med digitalt intyg.")]}
    registry_number = rabbit.number if source == DEVIATES else None
    fields["individual"] = _field(source, rabbit.number, read=own_text, registry=registry_number)
    fields["paper_number"] = _field(source, rabbit.number, read=own_text, registry=registry_number)
    if rabbit.certificate and rabbit.certificate != re.sub(r"\s", "", _text(raw.get("intygsnummer"))):
        checks.append(_check(False, f"{rabbit.number} har redan intyg {rabbit.certificate} i Stamboken."))
    _certificate(raw, struck, rabbit, fields, checks)
    return {"fields": fields, "checks": checks}


def build_proposal(raw, genebank_id, herd_id=None):
    """
    The proposal for a certificate in an item of `genebank_id` (sent in for the herd `herd_id`), from the
    interpreter's answer `raw` (inbox_interpreter.SCHEMA, untrusted): {"fields": {key: {value, source, read?,
    registry?}}, "checks": [{ok, text}]}. The keys are the registration form's (docs/inkorg.md, "Spara det intyget
    visar") and the grandparents': farfar, farmor, morfar, mormor.
    """
    raw = raw if isinstance(raw, dict) else {}
    struck = {key for key in raw.get("overstruket") or [] if isinstance(key, str)}
    registry = _Registry(genebank_id)
    fields, checks = {}, []
    own_text = _number_text(raw)
    own = None if {"genbanksnr", "ar_kull_individ"} & struck else _parse_number(raw, registry.letter)
    if own is not None:
        rabbit = registry.rabbit(f"{registry.letter}{own[0]}-{own[1]}")
        if rabbit is not None:
            return _existing(registry, raw, struck, rabbit, own_text, own[2])

    # The rabbit's own number: its herd must exist (one character off is härlett); its litter is tried below.
    paper = None
    if own is not None:
        herd = f"{registry.letter}{own[0]}"
        near = [h for h in registry.herds if (m := re.fullmatch(r"[A-Z](\d+)", h)) and _one_off(m[1], own[0])]
        if herd in registry.herds or len(near) == 1:
            paper = f"{herd if herd in registry.herds else near[0]}-{own[1]}"
            swapped = own[2] or herd not in registry.herds
        else:
            checks.append(_check(False, f"Besättningen {herd} finns inte i Stamboken."))
    elif own_text:
        reason = (
            "är överstruket eller rättat på intyget"
            if {"genbanksnr", "ar_kull_individ"} & struck
            else "går inte att läsa"
        )
        checks.append(_check(False, f"Individnumret {reason}."))
    if own_text and paper is None:
        fields["paper_number"] = _field(UNSURE, read=own_text)

    birth_text = _text(raw.get("fodelsedatum"))
    birth = None if "fodelsedatum" in struck else _date(birth_text)
    if birth_text and birth is None:
        fields["birth_date"] = _field(UNSURE, read=birth_text)
    if paper and birth and paper.split("-")[1][:2] != f"{birth:%y}":
        checks.append(_check(False, "Årssiffrorna i individnumret stämmer inte med födelsedatumet."))
        fields["paper_number"] = _field(UNSURE, read=own_text)
        fields["birth_date"] = _field(UNSURE, read=birth_text)
        paper = birth = None
    elif birth:
        fields["birth_date"] = _field(READ, birth.isoformat(), read=birth_text)

    parents, found = {}, {}
    for role in ("mother", "father"):
        parents[role], found[role] = _branch(registry, raw, struck, role, fields, checks)
    litter = None
    if parents["mother"] and parents["father"]:
        certified = all(_has_certificate(parent) for parent in parents.values())
        checks.insert(
            0,
            _check(True, "Mor och far finns i Stamboken med intyg." if certified else "Mor och far finns i Stamboken."),
        )
    elif not any(fields.get(role, {}).get("source") == DEVIATES for role in ("mother", "father")):
        year = birth.year if birth else (2000 + int(own[1][:2]) if own else date.today().year)
        found = {role: parents[role] or found[role] for role in parents}
        litter = _registry_litter(registry, raw, struck, found, birth, herd_id, year, fields, checks)
        if litter is not None:
            parents = {"mother": litter.mother, "father": litter.father}

    if parents["mother"] and parents["father"] and birth:
        if litter is None:
            same = Breeding.select().where(
                (Breeding.mother == parents["mother"].id) & (Breeding.father == parents["father"].id)
            )
            litter = same.where(Breeding.birth_date == birth).first()
            window = timedelta(days=SAME_LITTER_DAYS)
            near = None if litter else same.where(Breeding.birth_date.between(birth - window, birth + window)).first()
            if near is not None:
                fields["birth_date"] = _field(DEVIATES, read=birth_text, registry=near.birth_date.isoformat())
                checks.append(_check(False, f"Kullen med samma mor och far är född {near.birth_date} i Stamboken."))
                if paper:
                    fields["paper_number"] = _field(UNSURE, read=own_text)
                paper = None
        if paper:
            _number_against_litter(registry, paper, swapped, own_text, litter, parents, birth, fields, checks)
    if paper and "paper_number" not in fields:
        fields["paper_number"] = _field(UNSURE, read=own_text)
        checks.append(_check(None, "Individnumret går inte att pröva mot kullen utan mor, far och födelsedatum."))

    _litter_counts(raw, struck, litter, fields, checks)
    _certificate(raw, struck, None, fields, checks)
    _plain_fields(registry, raw, struck, fields)
    return {"fields": fields, "checks": checks}
