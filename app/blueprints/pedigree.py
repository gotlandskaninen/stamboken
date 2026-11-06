"""
Pedigree tree API endpoint.

Returns a nested ancestor tree for an individual, used by the Next.js
pedigree visualization.  See ADR-0007 for blueprint conventions.
"""

from flask import Blueprint, jsonify, request
from flask_login import current_user
from utils.database import Individual

from blueprints.common import json_login_required, problem

pedigree_bp = Blueprint("pedigree", __name__, url_prefix="/api")


def _build_pedigree_node(individual, generations_remaining):
    """Recursively build a pedigree tree node.

    Returns a dict with {id, name, number, sex, mother, father} where
    mother/father are either nested nodes or None.
    """
    if individual is None or generations_remaining <= 0:
        return None

    node = {
        "id": individual.id,
        "name": individual.name,
        "number": individual.number,
        "sex": individual.sex,
        "mother": None,
        "father": None,
    }

    if generations_remaining > 1 and individual.breeding:
        node["mother"] = _build_pedigree_node(individual.breeding.mother, generations_remaining - 1)
        node["father"] = _build_pedigree_node(individual.breeding.father, generations_remaining - 1)

    return node


# [Next.js]
@pedigree_bp.route("/individual/<i_number>/pedigree")
@json_login_required
def individual_pedigree(i_number):
    """Return a nested pedigree tree for the given individual.

    Query params:
        generations (int): Number of generations to include (default 4,
            i.e. subject + 3 ancestor generations).  Max 6.
    """
    generations = request.args.get("generations", 4, type=int)
    generations = max(1, min(generations, 6))

    try:
        individual = Individual.get(Individual.number == i_number)
    except Individual.DoesNotExist:
        return problem(404, "Not Found", f"Individual {i_number} not found")

    current_herd = individual.current_herd
    if not current_herd or current_herd.genebank.id not in current_user.accessible_genebanks:
        return problem(404, "Not Found", f"Individual {i_number} not found")

    tree = _build_pedigree_node(individual, generations)
    return jsonify(tree)
