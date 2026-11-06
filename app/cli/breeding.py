"""
Flask CLI for breeding data-quality checks.

Usage:
    flask breeding check-collisions [--since-year 2015] [--fail]

`check-collisions` is the prevention half of the 2026-09 litter-number
collision fix (the repair script for the historical rows lives in the private
operations repo, stamboken-drift: scripts/data-fixes/fix_litter_collisions.py). It reports the three collision shapes found in the
production data:

1. Same mother with litters closer together than MIN_DAYS_BETWEEN_LITTERS —
   validate_breeding rejects this today, so a hit means the row predates the
   check or came in through the legacy UI.
2. Same herd/year/litter number on more than one breeding. Two variants: the
   stored Breeding.litter_number (v2 schema only — kept unique by
   idx_breeding_herd_year_litter, so a hit there means the index is missing)
   and the litter digit parsed out of the offspring numbers, which is what
   migration 22's backfill reads.
3. The subset of (2) where the mothers differ — those are two real litters
   that were issued the same litter digit, so one of them has to be
   renumbered; they cannot be merged.

The v2 variant also reports, for information only, modern breedings that have
registered offspring but no litter_number: mint/BunnyPromote raise "Breeding
record has no litter_number set" on those. They are the leftovers migration
22's backfill cleared, not collisions, so they do not affect the exit code.

With --fail the command exits 1 when any collision is reported, so it can be
wired into a nightly job or CI.
"""

import click
from flask.cli import AppGroup
from utils.data_access import MIN_DAYS_BETWEEN_LITTERS
from utils.database import DB_PROXY

breeding_cli = AppGroup("breeding", help="Breeding data quality checks.")

_YEAR_EXPR = "EXTRACT(YEAR FROM COALESCE(b.birth_date, b.breed_date + INTERVAL '30 days'))::int"

_SAME_MOTHER_SQL = """
SELECT h.herd, mor.number, b1.breeding_id, b1.birth_date, b2.breeding_id, b2.birth_date,
       abs(b2.birth_date - b1.birth_date) AS days
  FROM breeding b1
  JOIN breeding b2 ON b2.mother_id = b1.mother_id AND b2.breeding_id > b1.breeding_id
  JOIN herd h ON h.herd_id = b1.breeding_herd_id
  JOIN individual mor ON mor.individual_id = b1.mother_id
 WHERE b1.birth_date IS NOT NULL
   AND b2.birth_date IS NOT NULL
   AND abs(b2.birth_date - b1.birth_date) < %s
   AND GREATEST(b1.birth_date, b2.birth_date) >= make_date(%s, 1, 1)
 ORDER BY h.herd, b1.birth_date
"""

# Litter digit read out of the offspring numbers ({herd}-{YY}{litter}{slot}),
# the same source migration 22's backfill uses; MODE() picks the most common
# parse within the litter so a single mistyped number cannot flip the group.
_PARSED_LITTER_SQL = r"""
WITH parsed AS (
    SELECT b.breeding_id,
           b.mother_id,
           h.herd,
           {year_expr} AS year,
           MODE() WITHIN GROUP (ORDER BY (regexp_match(i.number, '-\d\d(\d+)\d$'))[1]::int) AS litter
      FROM breeding b
      JOIN herd h ON h.herd_id = b.breeding_herd_id
      JOIN individual i ON i.breeding_id = b.breeding_id
     WHERE COALESCE(b.birth_date, b.breed_date) >= make_date(%s, 1, 1)
       AND i.number ~ '-\d\d\d+\d$'
     GROUP BY b.breeding_id, b.mother_id, h.herd, 4
)
SELECT herd, year, litter, count(*) AS breedings, count(DISTINCT mother_id) AS mothers,
       string_agg(breeding_id::text, ' ' ORDER BY breeding_id) AS breeding_ids
  FROM parsed
 WHERE litter IS NOT NULL
 GROUP BY herd, year, litter
HAVING count(*) > 1
 ORDER BY herd, year, litter
""".replace("{year_expr}", _YEAR_EXPR)

_STORED_LITTER_SQL = """
SELECT h.herd, {year_expr} AS year, b.litter_number, count(*) AS breedings,
       string_agg(b.breeding_id::text, ' ' ORDER BY b.breeding_id) AS breeding_ids
  FROM breeding b
  JOIN herd h ON h.herd_id = b.breeding_herd_id
 WHERE b.litter_number IS NOT NULL
   AND COALESCE(b.birth_date, b.breed_date) >= make_date(%s, 1, 1)
 GROUP BY h.herd, 2, b.litter_number
HAVING count(*) > 1
 ORDER BY h.herd, 2, b.litter_number
""".replace("{year_expr}", _YEAR_EXPR)

_MISSING_LITTER_SQL = """
SELECT h.herd, {year_expr} AS year, b.breeding_id, count(i.individual_id) AS offspring
  FROM breeding b
  JOIN herd h ON h.herd_id = b.breeding_herd_id
  JOIN individual i ON i.breeding_id = b.breeding_id
 WHERE b.litter_number IS NULL
   AND COALESCE(b.birth_date, b.breed_date) >= make_date(%s, 1, 1)
 GROUP BY h.herd, 2, b.breeding_id
 ORDER BY h.herd, 2, b.breeding_id
""".replace("{year_expr}", _YEAR_EXPR)


def _query(sql, params):
    return DB_PROXY.execute_sql(sql, params).fetchall()


def _has_litter_number():
    return bool(
        _query(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name = 'breeding' AND column_name = 'litter_number'",
            (),
        )
    )


def _print_table(title, headers, rows):
    """Print one category; returns the number of rows found."""
    click.echo(f"\n{title}")
    if not rows:
        click.echo("  inga träffar")
        return 0
    table = [[("" if cell is None else str(cell)) for cell in row] for row in rows]
    widths = [max(len(headers[i]), *(len(r[i]) for r in table)) for i in range(len(headers))]
    click.echo("  " + "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    click.echo("  " + "  ".join("-" * w for w in widths))
    for row in table:
        click.echo("  " + "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
    click.echo(f"  {len(rows)} träff(ar)")
    return len(rows)


@breeding_cli.command("check-collisions")
@click.option("--since-year", type=int, default=2015, help="Earliest year to check (default: 2015).")
@click.option("--fail", "fail_on_findings", is_flag=True, help="Exit 1 if anything is found (nightly/CI use).")
def check_collisions(since_year, fail_on_findings):
    """Report litter-number collisions in the breeding data."""
    found = 0

    found += _print_table(
        f"Kategori 1 — samma mor, kullar närmare än {MIN_DAYS_BETWEEN_LITTERS} dagar (från {since_year}):",
        ["Besättning", "Mor", "Parning 1", "Född 1", "Parning 2", "Född 2", "Dagar"],
        _query(_SAME_MOTHER_SQL, (MIN_DAYS_BETWEEN_LITTERS, since_year)),
    )

    parsed = _query(_PARSED_LITTER_SQL, (since_year,))
    found += _print_table(
        f"Kategori 2 — samma besättning/år/kullsiffra läst ur individnumren (från {since_year}):",
        ["Besättning", "År", "Kull", "Parningar", "Mödrar", "Parnings-id"],
        parsed,
    )
    found += _print_table(
        "Kategori 3 — som kategori 2 men med OLIKA mödrar (kräver omnumrering, inte sammanslagning):",
        ["Besättning", "År", "Kull", "Parningar", "Mödrar", "Parnings-id"],
        [row for row in parsed if row[4] > 1],
    )

    if _has_litter_number():
        found += _print_table(
            f"Kategori 2b — samma besättning/år/kullnummer i breeding.litter_number (från {since_year}):",
            ["Besättning", "År", "Kullnummer", "Parningar", "Parnings-id"],
            _query(_STORED_LITTER_SQL, (since_year,)),
        )
        # Informativt, inte en kollision: dessa rader är kvarvarande NULL efter
        # migration 22:s backfill (mint/BunnyPromote kastar på dem). De räknas
        # inte in i --fail, som gäller kollisionerna 1, 2, 2b och 3.
        _print_table(
            f"Kategori 2c — parningar med registrerade ungar men utan kullnummer, informativt (från {since_year}):",
            ["Besättning", "År", "Parning", "Ungar"],
            _query(_MISSING_LITTER_SQL, (since_year,)),
        )
    else:
        click.echo("\nbreeding.litter_number finns inte i det här schemat — hoppar över kategori 2b och 2c")

    click.echo(f"\nTotalt {found} kollisionsträff(ar) från {since_year}.")
    if fail_on_findings and found:
        raise SystemExit(1)
