"""Refuse parent changes that would make an animal its own ancestor.

Runs in the data-access layer (update_breeding, update_individual, audit
revert/restore) after the herd-tracking locks and before any side effect outside the
database, so the certificate routes refuse before PDF signing or S3 (and they
never move a rabbit to another litter: `breeding` is not a certificate form
field). Raw SQL and two concurrent edits that are only cyclic together are not covered;
the snapshot's cycle-breaking sort is the backstop.
"""

from utils.database import DB_PROXY as DATABASE

CYCLE_MESSAGE = "Föräldern är en ättling till kaninen"
CYCLE_PROBLEM = {"status": "error", "message": CYCLE_MESSAGE, "problem_status": 409, "title": "Konflikt", "rows": []}

# The new parents and all their ancestors; UNION deduplicates ids, so the recursion
# ends even when the stored pedigree already loops.
_ANCESTORS_HIT = """
WITH RECURSIVE anc(id) AS (
    SELECT unnest(%s::int[])
  UNION
    SELECT p.parent
    FROM anc
    JOIN individual i ON i.individual_id = anc.id
    JOIN breeding b ON b.breeding_id = i.breeding_id
    CROSS JOIN LATERAL (VALUES (b.father_id), (b.mother_id)) AS p(parent)
    WHERE p.parent IS NOT NULL
)
SELECT 1 FROM anc WHERE id = ANY(%s::int[]) LIMIT 1
"""


def pedigree_cycle_error(child_ids, sire_id, dam_id):
    """CYCLE_MESSAGE if giving `child_ids` these parents closes a loop, else None."""
    parents = [int(p) for p in (sire_id, dam_id) if p is not None]
    children = [int(c) for c in child_ids]
    if not parents or not children:
        return None
    hit = DATABASE.execute_sql(_ANCESTORS_HIT, (parents, children)).fetchone()
    return CYCLE_MESSAGE if hit else None
