"""
Provparning (test mating) v2 endpoint.

Thin route handler; the inbreeding maths lives in utils/genetics_service.py
(Henderson cache, virtual parents) and is shared with the legacy
``POST /api/testbreed``. See ADR-0007 for blueprint conventions.
"""

import contextlib

from extensions import limiter
from flask import Blueprint, jsonify, request
from flask_login import current_user
from peewee import JOIN
from utils import genetics_service
from utils.database import Breeding, Herd, HerdTracking, Individual, ht_not_voided, ht_order_desc, not_voided

from .common import json_login_required, problem

testbreed_v2_bp = Blueprint("testbreed_v2", __name__, url_prefix="/api")

# Offspring inbreeding (percent) at or below which a mating is "good" / "check".
# Returned in every response so the frontend never hard-codes them (and so they
# can become a per-genebank setting later).
THRESHOLDS = {"good_max": 4.0, "check_max": 6.0}

MAX_MALES = 10
# Ancestors are listed up to this many generations back on each side
# (a partner's own parents are generation 1).
MAX_ANCESTOR_GENERATIONS = 6
# Levels in the returned pedigree of each partner: the partner itself plus two
# ancestor generations (what the frontend's PedigreeTree renders under the
# offspring, same as ``GET /api/individual/<n>/pedigree?generations=3``).
PEDIGREE_LEVELS = 3


class _Invalid(Exception):
    """User error → 400 problem+json with a Swedish ``detail``."""


def _verdict(offspring_f):
    if offspring_f <= THRESHOLDS["good_max"]:
        return "good"
    if offspring_f <= THRESHOLDS["check_max"]:
        return "check"
    return "high"


def _parents_of(form, label):
    """Validate a ``{"mother": ..., "father": ...}`` object; return (mother, father) numbers."""
    if not isinstance(form, dict):
        raise _Invalid(f"{label}: ange föräldrar som ett objekt med mother och father.")
    mother = form.get("mother") or None
    father = form.get("father") or None
    for value in (mother, father):
        if value is not None and not isinstance(value, str):
            raise _Invalid(f"{label}: föräldrarnas nummer måste vara text.")
    if not mother and not father:
        raise _Invalid(f"{label}: ange minst en förälder för ett oregistrerat djur.")
    return mother, father


def _parse_animal(number, parents, label):
    """Normalise one side of the mating to {"number", "parents": (mother, father) | None}."""
    if number:
        if not isinstance(number, str):
            raise _Invalid(f"{label}: numret måste vara text.")
        return {"number": number, "parents": None, "label": label}
    return {"number": None, "parents": _parents_of(parents, label), "label": label}


def _current_genebanks(individual_ids):
    """{individual id: genebank id of its CURRENT herd} (latest herd tracking row; falls back to origin)."""
    current = {}
    rows = (
        HerdTracking.select(HerdTracking.individual.alias("individual_id"), Herd.genebank.alias("genebank_id"))
        .join(Herd, on=(HerdTracking.herd == Herd.id))
        .where(HerdTracking.individual.in_(sorted(individual_ids)), ht_not_voided())
        .order_by(HerdTracking.individual, *ht_order_desc())
        .dicts()
    )
    for row in rows:
        current.setdefault(row["individual_id"], row["genebank_id"])
    return current


def _load_individuals(numbers, genebank_id):
    """Return {number: row-dict} for the numbers the user may use in ``genebank_id``.

    An animal qualifies when it is in the chosen genebank's pedigree (origin
    herd) AND is visible to the user by the same rule as
    ``data_access.get_individual``: the genebank of its CURRENT herd must be
    accessible. Unknown and inaccessible numbers give one identical 400 so the
    response never reveals whether a number exists elsewhere.
    """
    rows = (
        Individual.select(
            Individual.id,
            Individual.number,
            Individual.name,
            Individual.sex,
            Herd.genebank.alias("genebank_id"),
        )
        .join(Herd, on=(Individual.origin_herd == Herd.id))
        .where(Individual.number.in_(sorted(numbers)))
        .where(not_voided(Individual))
        .dicts()
    )
    candidates = {row["number"]: row for row in rows if row["genebank_id"] == genebank_id}
    current = _current_genebanks([row["id"] for row in candidates.values()])
    accessible = set(current_user.accessible_genebanks)
    found = {
        number: row for number, row in candidates.items() if current.get(row["id"], row["genebank_id"]) in accessible
    }
    for number in sorted(numbers):
        if number not in found:
            raise _Invalid(f"Individen {number} finns inte eller är inte tillgänglig i den valda genbanken.")
    return found


def _check_sex(row, expected, label):
    if row["sex"] != expected:
        role = "en hona" if expected == "female" else "en hane"
        raise _Invalid(f"{label}: {row['number']} är inte {role}.")


def _load_pedigree(seeds, genebank_id):
    """Load the ancestry of every seed with one query per generation.

    ``seeds`` maps individual id -> start distance (generations from the mating
    partner). Walks upwards level by level, batching the ids of all seeds at
    once; only individuals that are not voided and belong to ``genebank_id``
    are loaded, so foreign or voided parents are never returned (and are
    treated as unknown). Returns
    ``{id: {"number", "name", "sex", "parents": (mother_id, father_id)}}``;
    ``parents`` are the RECORDED parent ids, which may name individuals that are
    not in the graph themselves (voided / other genebank).
    """
    graph = {}
    requested = set()
    by_level = {}
    for ind_id, start in seeds.items():
        by_level.setdefault(start, set()).add(ind_id)
    frontier = set()
    for d in range(MAX_ANCESTOR_GENERATIONS + 1):
        frontier = (frontier | by_level.get(d, set())) - requested
        if not frontier:
            continue
        requested |= frontier
        rows = (
            Individual.select(
                Individual.id,
                Individual.number,
                Individual.name,
                Individual.sex,
                Breeding.mother.alias("mother_id"),
                Breeding.father.alias("father_id"),
            )
            .join(Breeding, JOIN.LEFT_OUTER, on=(Individual.breeding == Breeding.id))
            .join(Herd, on=(Individual.origin_herd == Herd.id))
            .where(Individual.id.in_(sorted(frontier)))
            .where(not_voided(Individual))
            .where(Herd.genebank == genebank_id)
            .dicts()
        )
        frontier = set()
        for row in rows:
            graph[row["id"]] = {
                "number": row["number"],
                "name": row["name"],
                "sex": row["sex"],
                "parents": (row["mother_id"], row["father_id"]),
            }
            if d < MAX_ANCESTOR_GENERATIONS:
                frontier.update(p for p in graph[row["id"]]["parents"] if p is not None)
    return graph


def _distances(graph, seed_ids, start_distance):
    """{id: min generations} for the ancestors of ``seed_ids`` that exist in ``graph``."""
    distance = {}
    frontier = {i for i in seed_ids if i in graph}
    d = start_distance
    while frontier and d <= MAX_ANCESTOR_GENERATIONS:
        for ind_id in frontier:
            distance[ind_id] = d
        nxt = set()
        if d < MAX_ANCESTOR_GENERATIONS:
            for ind_id in frontier:
                nxt.update(p for p in graph[ind_id]["parents"] if p in graph and p not in distance)
        frontier = nxt
        d += 1
    return distance


def _plan(animal, found, own_sex):
    """Work out where the pedigree walk of one side of the mating starts.

    A registered animal is walked from itself (distance 0); an unregistered
    ("virtual") one from its stated parents (distance 1). ``own_sex`` is the
    sex of the side ("female" / "male"), needed for the virtual node.
    """
    if animal["number"]:
        row = found[animal["number"]]
        return {"row": row, "seeds": [row["id"]], "start": 0, "parent_ids": None, "sex": own_sex}

    mother_no, father_no = animal["parents"]
    label = animal["label"]
    parent_ids = []
    for number, sex in ((mother_no, "female"), (father_no, "male")):
        if number is None:
            parent_ids.append(None)
            continue
        parent = found[number]
        _check_sex(parent, sex, label)
        parent_ids.append(parent["id"])
    return {
        "row": None,
        "seeds": [p for p in parent_ids if p is not None],
        "start": 1,
        "parent_ids": tuple(parent_ids),
        "sex": own_sex,
    }


def _pedigree_node(graph, ind_id, levels):
    """Nested ``{id, number, name, sex, mother, father}`` for ``levels`` generations.

    Built only from ``graph``, so voided and other-genebank ancestors (absent
    from it) become ``None`` ("okänd") exactly as they are excluded from the
    common ancestors.
    """
    node = graph.get(ind_id)
    if node is None or levels <= 0:
        return None
    mother_id, father_id = node["parents"]
    return {
        "id": ind_id,
        "number": node["number"],
        "name": node["name"],
        "sex": node["sex"],
        "mother": _pedigree_node(graph, mother_id, levels - 1),
        "father": _pedigree_node(graph, father_id, levels - 1),
    }


def _side_pedigree(plan, parent_ids, graph):
    """Pedigree of one partner; an unregistered one is an "Ej registrerad" node over its stated parents."""
    if plan["row"] is not None:
        return _pedigree_node(graph, plan["row"]["id"], PEDIGREE_LEVELS)
    mother_id, father_id = parent_ids
    return {
        "id": None,
        "number": None,
        "name": None,
        "sex": plan["sex"],
        "unregistered": True,
        "mother": _pedigree_node(graph, mother_id, PEDIGREE_LEVELS - 1),
        "father": _pedigree_node(graph, father_id, PEDIGREE_LEVELS - 1),
    }


def _resolve(plan, graph):
    """Attach distances, the recorded parent ids and the filtered pedigree to a planned side.

    ``parent_ids`` are the parents as RECORDED (a biological fact used only for
    the relation check); they may be voided or in another genebank, so they are
    never turned into a number or name. Everything shown comes from ``graph``.
    """
    parent_ids = plan["parent_ids"]
    if parent_ids is None:
        parent_ids = graph[plan["row"]["id"]]["parents"]
    return {
        "row": plan["row"],
        "parent_ids": parent_ids,
        "distance": _distances(graph, plan["seeds"], plan["start"]),
        "pedigree": _side_pedigree(plan, parent_ids, graph),
    }


def _relation(female, male):
    f_row, m_row = female["row"], male["row"]
    f_mother, f_father = female["parent_ids"]
    m_mother, m_father = male["parent_ids"]
    if (f_row and f_row["id"] in (m_mother, m_father)) or (m_row and m_row["id"] in (f_mother, f_father)):
        return "parent_child"
    same_mother = f_mother is not None and f_mother == m_mother
    same_father = f_father is not None and f_father == m_father
    if same_mother and same_father:
        return "full_siblings"
    if same_mother or same_father:
        return "half_siblings"
    return None


def _common_ancestors(female, male, graph):
    """Ancestors (incl. the partners themselves, distance 0) reachable from both sides."""
    shared = set(female["distance"]) & set(male["distance"])
    rows = [
        {
            "number": graph[i]["number"],
            "name": graph[i]["name"],
            "generations": [male["distance"][i], female["distance"][i]],
        }
        for i in shared
    ]
    rows.sort(key=lambda r: (sum(r["generations"]), max(r["generations"]), r["number"]))
    return rows


def _animal_summary(side, inbreeding, mean_kinship):
    """{number, name, f, mk, pedigree}; f/mk in percent, all null for an unregistered animal."""
    row = side["row"]
    pedigree = side["pedigree"]
    if row is None:
        return {"number": None, "name": None, "f": None, "mk": None, "pedigree": pedigree}
    number = row["number"]
    f = inbreeding.get(number, 0.0) * 100
    # Mean kinship is only defined for the active reference population.
    mk = mean_kinship[number] * 100 if number in mean_kinship else None
    return {
        "number": number,
        "name": row["name"],
        "f": round(f, 2),
        "mk": None if mk is None else round(mk, 2),
        "pedigree": pedigree,
    }


def _parse_request(payload):
    if not isinstance(payload, dict):
        raise _Invalid("Begäran måste vara ett JSON-objekt.")
    genebank_id = payload.get("genebank_id")
    if isinstance(genebank_id, bool) or not isinstance(genebank_id, int):
        raise _Invalid("genebank_id måste vara ett heltal.")

    female = _parse_animal(payload.get("female"), payload.get("female_parents"), "Honan")

    males_in = payload.get("males")
    if not isinstance(males_in, list) or not males_in:
        raise _Invalid("Ange minst en hane.")
    if len(males_in) > MAX_MALES:
        raise _Invalid(f"Högst {MAX_MALES} hanar åt gången.")
    males = []
    for idx, entry in enumerate(males_in, start=1):
        if not isinstance(entry, dict):
            raise _Invalid(f"Hane {idx}: ogiltigt format.")
        males.append(_parse_animal(entry.get("number"), entry.get("parents"), f"Hane {idx}"))
    return genebank_id, female, males


def _referenced_numbers(animals):
    numbers = set()
    for animal in animals:
        if animal["number"]:
            numbers.add(animal["number"])
        else:
            numbers.update(n for n in animal["parents"] if n)
    return numbers


# [Next.js]
@testbreed_v2_bp.route("/v2/testbreed", methods=["POST"])
@limiter.limit("60 per minute")
@json_login_required
def testbreed():
    """Offspring inbreeding for one female against 1-10 males.

    Body: {genebank_id, female | female_parents, males: [{number | parents}]}.
    Response: TestbreedResponse in next-app/src/lib/provparning.ts.
    Any user with access to the genebank may call this (viewer level is enough).
    """
    try:
        genebank_id, female, males = _parse_request(request.get_json(silent=True))
    except _Invalid as exc:
        return problem(400, "Ogiltig begäran", str(exc))

    if genebank_id not in current_user.accessible_genebanks:
        return problem(403, "Åtkomst nekad", "Du saknar åtkomst till den valda genbanken.")

    try:
        found = _load_individuals(_referenced_numbers([female, *males]), genebank_id)
        if female["number"]:
            _check_sex(found[female["number"]], "female", female["label"])
        for male in males:
            if male["number"]:
                _check_sex(found[male["number"]], "male", male["label"])
        plans = [_plan(animal, found, sex) for animal, sex in ((female, "female"), *((male, "male") for male in males))]
    except _Invalid as exc:
        return problem(400, "Ogiltig begäran", str(exc))

    # One shared, batched traversal for every animal (<= MAX_ANCESTOR_GENERATIONS + 1 queries).
    seeds = {}
    for plan in plans:
        for seed in plan["seeds"]:
            seeds[seed] = min(plan["start"], seeds.get(seed, plan["start"]))
    graph = _load_pedigree(seeds, genebank_id)
    female_side, *male_sides = [_resolve(plan, graph) for plan in plans]
    # Loaded once for all animals instead of per summary.
    registered = any(plan["row"] for plan in plans)
    # One snapshot for the whole response: a rebuild published mid-request must not mix pedigrees.
    # It must know every supplied animal (a renumbered or new one waits for its rebuild).
    try:
        snap = genetics_service.snapshot_with(genebank_id, _referenced_numbers([female, *males]))
    except genetics_service.SnapshotNotReady:
        body, status, headers = problem(503, "Service Unavailable", "Genetiken uppdateras, försök igen om en stund")
        return body, status, {**headers, "Retry-After": "5"}
    with genetics_service.ps.pinned(snap) if snap is not None else contextlib.nullcontext():
        inbreeding = genetics_service.get_inbreeding(genebank_id) if registered else {}
        mean_kinship = genetics_service.get_mean_kinship(genebank_id) if registered else {}

        female_virtual_parents = None if female["number"] else (female["parents"][1], female["parents"][0])
        results = []
        for male, side in zip(males, male_sides, strict=True):
            male_virtual_parents = None if male["number"] else (male["parents"][1], male["parents"][0])
            # calculate_testbreed takes (father, mother) tuples for unregistered animals.
            offspring = genetics_service.calculate_testbreed(
                genebank_id,
                male["number"] or "",
                female["number"] or "",
                male_parents=male_virtual_parents,
                female_parents=female_virtual_parents,
            )
            offspring_f = round(offspring * 100, 2)
            results.append(
                {
                    "male": _animal_summary(side, inbreeding, mean_kinship),
                    "offspring_f": offspring_f,
                    "verdict": _verdict(offspring_f),
                    "relation": _relation(female_side, side),
                    "common_ancestors": _common_ancestors(female_side, side, graph),
                }
            )

    return jsonify(
        {
            "genebank_id": genebank_id,
            "thresholds": THRESHOLDS,
            "female": _animal_summary(female_side, inbreeding, mean_kinship),
            "results": results,
        }
    )
