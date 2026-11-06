"""
Flask CLI commands for seeding the database with minimal realistic test data.

Usage:
    docker exec <api-container> flask seed create
    docker exec <api-container> flask seed create --verbose

Creates data mirroring production patterns:
- 2 genebanks (Gotlandskanin: 35 colors, Mellerudskanin: 2 colors)
- ~10 herds including GX1/MX1 external herds and inactive herds
- ~30 individuals across 3 generations with correct numbering formats
- Corner cases: no sex, no color, no mother/father, transfers, deaths,
  pending pregnancies, litter_size > 12, old/new number formats
- litter_number on every seeded litter that has been born (seeded rows bypass
  both real assignment paths — see _assign_litter_numbers)

Idempotent — safe to run multiple times (skips existing data).
"""

import logging
import os
import re
import uuid
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import NamedTuple

import click
from flask.cli import AppGroup
from utils import data_access as da
from utils.database import (
    DATABASE,
    Bodyfat,
    Breeding,
    Color,
    Genebank,
    Herd,
    HerdTracking,
    Individual,
    User,
    Weight,
    ht_not_voided,
)

logger = logging.getLogger("herdbook.seed")

seed_cli = AppGroup("seed", help="Seed database with test data.")


def _get_or_create(model, defaults=None, **kwargs):
    """Get existing record or create new one. Returns (instance, created)."""
    defaults = defaults or {}
    try:
        return model.get(**kwargs), False
    except model.DoesNotExist:
        params = {**kwargs, **defaults}
        return model.create(**params), True


@seed_cli.command("create")
@click.option("--verbose", "-v", is_flag=True, help="Print detailed output")
def create_seed_data(verbose):
    """Create minimal realistic test data mirroring production patterns."""
    # Same production check as cli.create_test_users: the seed users have public passwords.
    if os.environ.get("FLASK_ENV") == "production":
        raise click.ClickException("refusing to seed test data with public passwords in production.")
    stats = {"created": 0, "existing": 0}

    def log(msg, created=True):
        stats["created" if created else "existing"] += 1
        if verbose:
            click.echo(f"  {'✓' if created else '='} {msg}")

    click.echo("Seeding database with production-like data...")

    with DATABASE.atomic():
        # ══════════════════════════════════════════════
        # GENEBANKS
        # ══════════════════════════════════════════════
        gk, c = _get_or_create(Genebank, name="Gotlandskanin")
        log("Genebank: Gotlandskanin", c)

        mk, c = _get_or_create(Genebank, name="Mellerudskanin")
        log("Genebank: Mellerudskanin", c)

        # ══════════════════════════════════════════════
        # COLORS (all 35 GK + 2 MK from production)
        # ══════════════════════════════════════════════
        gk_color_names = [
            "Albino",
            "Allt annat",
            "Annan japanteckning",
            "Blå",
            "Blåbrokig",
            "Brokad på annat sätt",
            "Brun",
            "Brunbrokig",
            "Chinchilla",
            "Chinchillabrokig",
            "Gul-blå japantecknad",
            "Gulbrokig",
            "Gul-svart japantecknad",
            "Isabella",
            "Järnblå",
            "Järngrå",
            "Madagaskar",
            "Madagaskarbrokig",
            "Rödgul",
            "Sallander",
            "Snöhare",
            "Svart",
            "Svartbrokig",
            "Svart med vita stickelhår",
            "Trefärgad",
            "Viltblå",
            "Viltgrå",
            "Viltgråbrokig",
            "Viltgul",
            "Vit-blå japantecknad",
            "Vit ej albino",
            "Vit-svart japantecknad",
            "White blå och Otter blå",
            "White svart och Otter svart",
            "Wienertecknad",
        ]
        gk_colors = {}
        for name in gk_color_names:
            color, c = _get_or_create(Color, name=name, genebank=gk)
            gk_colors[name] = color
        log(f"Colors: {len(gk_color_names)} Gotlandskanin", True)

        mk_color_names = ["Albino", "Holländarteckning"]
        mk_colors = {}
        for name in mk_color_names:
            color, c = _get_or_create(Color, name=name, genebank=mk)
            mk_colors[name] = color
        log(f"Colors: {len(mk_color_names)} Mellerudskanin", True)

        # ══════════════════════════════════════════════
        # HERDS (mixed active/inactive + GX1/MX1 external)
        # ══════════════════════════════════════════════
        gk1 = _herd(gk, "G1274", "Visby Kaninuppfödning", True, "Anna Andersson", "anna@example.com", log)
        gk2 = _herd(gk, "G1398", "Fårö Gotlandskaniner", True, "Erik Eriksson", "erik@example.com", log)
        # Active empty herd for test-empty user
        _herd(gk, "G1500", "Tom Besättning", True, "Test Testsson", "test@example.com", log)
        gk3 = _herd(
            gk, "G95", "Gammal Besättning", False, "Karl Karlsson", None, log
        )  # Old format, short number, inactive
        gkx = _herd(gk, "GX1", "Externa djur (Gotland)", False, None, None, log)  # Special external herd

        mk1 = _herd(mk, "M1220", "Dalslands Mellerudskaniner", True, "Maria Johansson", "maria@example.com", log)
        mk2 = _herd(mk, "M940", "Bengtsfors Kaninfarm", True, "Bengt Bengtsson", "bengt@example.com", log)
        _herd(
            mk,
            "M1603",
            "Historisk Besättning",
            False,
            "Lisa Svensson",
            None,
            log,
        )  # Inactive
        mkx = _herd(mk, "MX1", "Externa djur (Mellerud)", False, None, None, log)  # Special external herd

        # ══════════════════════════════════════════════
        # USERS
        # ══════════════════════════════════════════════
        _user(
            "seed-admin@test.local",
            "seed-admin-pass",
            "seed-admin",
            "Seed Admin",
            [("admin", None)],
            log,
        )
        gk_mgr = _user(
            "seed-gk-mgr@test.local",
            "seed-gk-pass",
            "seed-gk-manager",
            "GK Genbanksansvarig",
            [("manager", gk.id)],
            log,
        )
        mk_mgr = _user(
            "seed-mk-mgr@test.local",
            "seed-mk-pass",
            "seed-mk-manager",
            "MK Genbanksansvarig",
            [("manager", mk.id)],
            log,
        )
        _user(
            "seed-gk-owner@test.local",
            "seed-gk-owner-pass",
            "seed-gk-owner",
            "Anna Andersson",
            [("owner", gk1.id)],
            log,
        )
        _user(
            "seed-mk-owner@test.local",
            "seed-mk-owner-pass",
            "seed-mk-owner",
            "Maria Johansson",
            [("owner", mk1.id)],
            log,
        )

        # ══════════════════════════════════════════════
        # GOTLANDSKANIN — 3 generations + corner cases
        # ══════════════════════════════════════════════

        # --- Founders (generation 0, no parents) ---
        # Old number format (short herd number, from the 90s)
        _individual(
            "G95-9811",
            "Gamle Stamfar",
            "male",
            gk3,
            date(1998, 4, 1),
            None,
            None,
            gk_colors["Viltgrå"],
            "12345",
            gk_mgr,
            log,
        )
        _individual(
            "G95-9821",
            "Gamla Stammor",
            "female",
            gk3,
            date(1998, 5, 10),
            None,
            None,
            gk_colors["Svart"],
            "12346",
            gk_mgr,
            log,
            death_date=date(2005, 3, 1),
            death_note="Ålder",
        )

        # Modern founders (G1274)
        gk_f0 = _individual(
            "G1274-1911",
            "Visby Stamfar",
            "male",
            gk1,
            date(2019, 3, 15),
            None,
            None,
            gk_colors["Viltgrå"],
            "100042",
            gk_mgr,
            log,
        )
        gk_m0 = _individual(
            "G1274-1921",
            "Visby Stammor",
            "female",
            gk1,
            date(2019, 4, 10),
            None,
            None,
            gk_colors["Chinchilla"],
            "100043",
            gk_mgr,
            log,
        )

        # External founder (GX1 herd — imported rabbit)
        _individual(
            "GX1-1811",
            "Extern Hane",
            "male",
            gkx,
            date(2018, 6, 1),
            None,
            None,
            None,
            None,
            gk_mgr,
            log,
        )  # No color, no certificate

        # Founder from G1398
        gk_f0b = _individual(
            "G1398-2011",
            "Fårö Grundare",
            "male",
            gk2,
            date(2020, 3, 20),
            None,
            None,
            gk_colors["Blå"],
            "100050",
            gk_mgr,
            log,
        )

        # --- Generation 1 (offspring of founders, 2021) ---
        gk_g1 = _breeding(gk1, date(2021, 4, 1), date(2021, 3, 1), gk_f0, gk_m0, 5, 4, log)
        gk_g1_f = _individual(
            "G1274-2111",
            "Visby Viking",
            "male",
            gk1,
            date(2021, 4, 1),
            gk_f0,
            gk_m0,
            gk_colors["Viltgrå"],
            "100060",
            gk_mgr,
            log,
            breeding=gk_g1,
        )
        gk_g1_m = _individual(
            "G1274-2112",
            "Visby Vilda",
            "female",
            gk1,
            date(2021, 4, 1),
            gk_f0,
            gk_m0,
            gk_colors["Svart"],
            "100061",
            gk_mgr,
            log,
            breeding=gk_g1,
        )
        gk_g1_m2 = _individual(
            "G1274-2113",
            "Visby Vera",
            "female",
            gk1,
            date(2021, 4, 1),
            gk_f0,
            gk_m0,
            gk_colors["Viltgrå"],
            None,
            gk_mgr,
            log,
            breeding=gk_g1,
        )  # No certificate

        # Corner case: individual without sex (prod has 286 of these)
        _individual(
            "G1274-2114",
            None,
            None,
            gk1,
            date(2021, 4, 1),
            gk_f0,
            gk_m0,
            None,
            None,
            gk_mgr,
            log,
            breeding=gk_g1,
        )  # No sex, no color, no name

        # --- Generation 2 (cross-herd mating, 2023) ---
        gk_g2 = _breeding(gk1, date(2023, 5, 15), date(2023, 4, 14), gk_f0b, gk_g1_m, 4, 3, log)
        gk_g2_1 = _individual(
            "G1274-2311",
            "Visby Junior",
            "male",
            gk1,
            date(2023, 5, 15),
            gk_f0b,
            gk_g1_m,
            gk_colors["Blå"],
            "100070",
            gk_mgr,
            log,
            breeding=gk_g2,
        )
        gk_g2_2 = _individual(
            "G1274-2312",
            "Visby Junia",
            "female",
            gk1,
            date(2023, 5, 15),
            gk_f0b,
            gk_g1_m,
            gk_colors["Viltgrå"],
            "100071",
            gk_mgr,
            log,
            breeding=gk_g2,
        )

        # Corner case: large litter (>12, prod has 17 of these)
        gk_big = _breeding(gk2, date(2022, 6, 1), date(2022, 5, 1), gk_f0b, gk_g1_m2, 14, 10, log)
        _individual(
            "G1398-2211",
            "Storkull",
            "female",
            gk2,
            date(2022, 6, 1),
            gk_f0b,
            gk_g1_m2,
            gk_colors["Viltgrå"],
            "100080",
            gk_mgr,
            log,
            breeding=gk_big,
        )

        # Transfer: sell G1274-2312 to G1398
        _transfer(gk_g2_2, gk2, gk1, gk_mgr, date(2024, 1, 15), log)

        # Dead individual
        _individual(
            "G1274-2011",
            "Visby Gamlingen",
            "male",
            gk1,
            date(2020, 6, 1),
            None,
            None,
            gk_colors["Brun"],
            "100044",
            gk_mgr,
            log,
            death_date=date(2024, 8, 1),
            death_note="Ålder",
        )

        # --- Unrelated pairs for e2e form tests ---
        # TWO separate lineages to avoid inbreeding warnings between test pairs.

        # Lineage A: Fårö line — for mating-registration test
        ind_faro_f1 = _individual(
            "G1398-2012",
            "Fårö Freja",
            "female",
            gk2,
            date(2020, 5, 10),
            None,
            None,
            gk_colors["Svart"],
            None,
            gk_mgr,
            log,
        )
        ind_faro_m1 = _individual(
            "G1398-2013",
            "Fårö Fenris",
            "male",
            gk2,
            date(2020, 6, 15),
            None,
            None,
            gk_colors["Viltgrå"],
            None,
            gk_mgr,
            log,
        )
        breeding_faro = _breeding(
            gk2,
            date(2021, 4, 20),
            date(2021, 3, 18),
            ind_faro_m1,
            ind_faro_f1,
            4,
            3,
            log,
        )
        # Mating test pair: mother from lineage A, father is an unrelated founder
        ind_form_mother = _individual(
            "G1274-2115",
            "Visby Saga",
            "female",
            gk1,
            date(2021, 4, 20),
            ind_faro_m1,
            ind_faro_f1,
            gk_colors["Svart"],
            "CERT-2115",
            gk_mgr,
            log,
            breeding=breeding_faro,
        )
        # Father is a standalone founder — no relation to Fårö line
        ind_form_father = _individual(
            "G1274-2116",
            "Visby Storm",
            "male",
            gk1,
            date(2019, 8, 5),
            None,
            None,
            gk_colors["Viltgrå"],
            "CERT-2116",
            gk_mgr,
            log,
        )

        # Lineage B: Gammelstad line — for litter-registration test
        ind_gammel_f1 = _individual(
            "G1398-2014",
            "Fårö Greta",
            "female",
            gk2,
            date(2019, 3, 12),
            None,
            None,
            gk_colors["Blå"],
            None,
            gk_mgr,
            log,
        )
        ind_gammel_m1 = _individual(
            "G1398-2015",
            "Fårö Gustav",
            "male",
            gk2,
            date(2019, 7, 22),
            None,
            None,
            gk_colors["Chinchilla"],
            None,
            gk_mgr,
            log,
        )
        breeding_gammel = _breeding(
            gk2,
            date(2020, 5, 15),
            date(2020, 4, 10),
            ind_gammel_m1,
            ind_gammel_f1,
            5,
            4,
            log,
        )
        # Litter test pair: mother from lineage B, father is another unrelated founder
        ind_form_mother2 = _individual(
            "G1274-2117",
            "Visby Dimma",
            "female",
            gk1,
            date(2020, 5, 15),
            ind_gammel_m1,
            ind_gammel_f1,
            gk_colors["Blå"],
            "CERT-2117",
            gk_mgr,
            log,
            breeding=breeding_gammel,
        )
        ind_form_father2 = _individual(
            "G1274-2118",
            "Visby Blixt",
            "male",
            gk1,
            date(2018, 11, 3),
            None,
            None,
            gk_colors["Svart"],
            "CERT-2118",
            gk_mgr,
            log,
        )

        # Add HerdTracking for form-test individuals so they appear as "active".
        # Use a recent date (relative to today) so status doesn't expire after 13 months.
        recent_tracking = date.today() - timedelta(days=30)
        for ind in [ind_form_mother, ind_form_father, ind_form_mother2, ind_form_father2]:
            _track(ind, gk1, None, gk_mgr, recent_tracking, "ATTESTATION", log)

        # --- Bulk individuals for pagination testing ---
        # "Active" in this app requires: cert + recent HerdTracking + no death.
        # Create a mix: ~15 active (with cert + tracking), ~5 inactive (no cert), ~5 dead.
        bulk_colors = [
            gk_colors["Svart"],
            gk_colors["Viltgrå"],
            gk_colors["Blå"],
            gk_colors["Chinchilla"],
            gk_colors["Rödgul"],
        ]
        for i in range(25):
            year = 2020 + (i % 5)
            month = 1 + (i % 12)
            sex = "female" if i % 2 == 0 else "male"
            color = bulk_colors[i % len(bulk_colors)]
            # 4-digit suffix to match existing format (e.g., G1274-2350)
            num = f"G1274-{year % 100}{i + 50:02d}"
            name = f"Visby Test-{i + 1:02d}"

            # Determine status: first 15 active, next 5 inactive, last 5 dead
            if i < 15:
                cert = f"CERT-BULK-{i + 1:02d}"
                death_date, death_note = None, None
            elif i < 20:
                cert = None  # no cert → inactive
                death_date, death_note = None, None
            else:
                cert = f"CERT-BULK-{i + 1:02d}"
                death_date = date(2024, 6, 15)
                death_note = "Ålder"

            ind = _individual(
                num,
                name,
                sex,
                gk1,
                date(year, month, 15),
                None,
                None,  # no parents (founders)
                color,
                cert,
                gk_mgr,
                log,
                death_date=death_date,
                death_note=death_note,
            )

            # Add HerdTracking for active individuals (cert + tracking = active)
            if i < 15:
                _track(ind, gk1, None, gk_mgr, recent_tracking, "ATTESTATION", log)

        # ══════════════════════════════════════════════
        # MELLERUDSKANIN — 2 generations + corner cases
        # ══════════════════════════════════════════════

        mk_f0 = _individual(
            "M1220-2011",
            "Dansen",
            "male",
            mk1,
            date(2020, 3, 20),
            None,
            None,
            mk_colors["Albino"],
            "200010",
            mk_mgr,
            log,
        )
        mk_m0 = _individual(
            "M1220-2021",
            "Dansen Mor",
            "female",
            mk1,
            date(2020, 4, 5),
            None,
            None,
            mk_colors["Holländarteckning"],
            "200011",
            mk_mgr,
            log,
        )

        # Old format MK
        mk_old = _individual(
            "M940-1612",
            "Gammal Mellerud",
            "female",
            mk2,
            date(2016, 5, 1),
            None,
            None,
            mk_colors["Albino"],
            "200001",
            mk_mgr,
            log,
        )

        # External MK
        _individual(
            "MX1-1911",
            "Extern Mellerud",
            "male",
            mkx,
            date(2019, 3, 1),
            None,
            None,
            None,
            None,
            mk_mgr,
            log,
        )  # No color, no cert

        # Gen 1
        mk_g1 = _breeding(mk1, date(2022, 5, 10), date(2022, 4, 9), mk_f0, mk_m0, 6, 5, log)
        mk_g1_f = _individual(
            "M1220-2211",
            "Lansen",
            "male",
            mk1,
            date(2022, 5, 10),
            mk_f0,
            mk_m0,
            mk_colors["Holländarteckning"],
            "200020",
            mk_mgr,
            log,
            breeding=mk_g1,
        )
        mk_g1_m = _individual(
            "M1220-2212",
            "Lansen Syster",
            "female",
            mk1,
            date(2022, 5, 10),
            mk_f0,
            mk_m0,
            mk_colors["Albino"],
            "200021",
            mk_mgr,
            log,
            breeding=mk_g1,
        )

        # Corner case: breeding with breed_date but no birth_date (pending pregnancy)
        # Prod has 19 of these
        recent = date.today() - timedelta(days=20)
        _breeding(mk1, None, recent, mk_g1_f, mk_g1_m, None, None, log)

        # Corner case: breeding with litter_size = 0
        _breeding(mk1, date(2023, 8, 1), date(2023, 7, 1), mk_f0, mk_m0, 0, 0, log)

        # Transfer: MK rabbit between herds
        _transfer(mk_old, mk1, mk2, mk_mgr, date(2021, 3, 1), log)

        # ══════════════════════════════════════════════
        # WEIGHTS & BODYFAT
        # ══════════════════════════════════════════════
        for ind, w, bf in [
            (gk_g1_f, 3.2, "normal"),
            (gk_g1_m, 2.8, "low"),
            (gk_g2_1, 3.0, "normal"),
            (mk_g1_f, 2.5, "high"),
            (mk_g1_m, 2.3, "normal"),
        ]:
            _get_or_create(Weight, individual=ind, defaults={"weight": w, "weight_date": date(2024, 6, 1)})
            _get_or_create(Bodyfat, individual=ind, defaults={"bodyfat": bf, "bodyfat_date": date(2024, 6, 1)})
        log("Weights + bodyfat: 5 individuals", True)

        # ══════════════════════════════════════════════
        # LITTER NUMBERS (last — ranks each litter against its siblings)
        # ══════════════════════════════════════════════
        numbered = _assign_litter_numbers()
        log(f"Litter numbers: {numbered} litter(s) numbered", numbered > 0)

    # ══════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════
    click.echo(f"\nSeed complete: {stats['created']} created, {stats['existing']} existing.")
    click.echo("\nData summary:")
    click.echo("  Genebanks: 2 (Gotlandskanin, Mellerudskanin)")
    click.echo("  Colors: 35 GK + 2 MK (all production colors)")
    click.echo("  Herds: 8 (4 active, 2 inactive, GX1+MX1 external)")
    click.echo("  Individuals: ~22 across 3 generations")
    click.echo("  Corner cases: no sex, no color, no cert, external, old format,")
    click.echo("    large litter (14), litter_size=0, pending pregnancy, transfers, deaths")
    click.echo("\nTest users:")
    click.echo("  seed-admin@test.local / seed-admin-pass (admin)")
    click.echo("  seed-gk-mgr@test.local / seed-gk-pass (GK manager)")
    click.echo("  seed-mk-mgr@test.local / seed-mk-pass (MK manager)")
    click.echo("  seed-gk-owner@test.local / seed-gk-owner-pass (G1274 owner)")
    click.echo("  seed-mk-owner@test.local / seed-mk-owner-pass (M1220 owner)")


# ══════════════════════════════════════════════════
# Litter numbers
# ══════════════════════════════════════════════════

# Minted individual numbers are {herd}-{YY}{litter}{slot} (individual_number_v2).
# The litter component is [1-9]\d* rather than \d+: generate_individual_number
# serialises the litter integer unpadded (f"{herd}-{YY}{litter_number}{slot}"),
# so a number with a leading zero there was never mintable.
_NUMBER_RE = re.compile(r"^(?P<herd>.+)-(?P<year>\d\d)(?P<litter>[1-9]\d*)(?P<slot>\d)$")


class _Litter(NamedTuple):
    """A Breeding row reduced to the fields the numbering decides from."""

    breeding_id: int
    herd: str
    birth_date: date | None
    breed_date: date | None
    litter_number: int | None
    offspring_numbers: tuple[str, ...] = ()


def _parse_litter_number(number, herd_identifier, year):
    """Litter number encoded in a minted individual number, or None.

    Same source as migrate_21_to_22's backfill (the number that was actually
    issued), but the grammar is checked against the litter the number belongs
    to. The seed also holds numbers that only look minted — bulk pagination
    fixtures ending in slot 0, zero-padded litter components, kits carrying
    another herd's prefix or another year's suffix — and those must fall through
    to the chronological rank instead of claiming a litter.
    """
    match = _NUMBER_RE.match(number or "")
    if not match or match["herd"] != herd_identifier or int(match["year"]) != year % 100:
        return None
    litter, slot = int(match["litter"]), int(match["slot"])
    return litter if slot >= 1 and litter <= 32767 else None


def _litter_number_from_offspring(offspring_numbers, herd_identifier, year):
    """Most common litter number among the litter's minted individuals (MODE).

    Ties break the way the migration's MODE() WITHIN GROUP (ORDER BY ... ::int)
    does: among the most frequent parses, the smallest number wins.
    """
    counts = Counter(
        litter
        for litter in (_parse_litter_number(number, herd_identifier, year) for number in offspring_numbers)
        if litter is not None
    )
    if not counts:
        return None
    return max(counts.items(), key=lambda entry: (entry[1], -entry[0]))[0]


def _litter_bucket(litter):
    """(herd, year) bucket of the unique index, or None when the row has no date."""
    birth = litter.birth_date or (litter.breed_date + timedelta(days=30) if litter.breed_date else None)
    return (litter.herd, birth.year) if birth is not None else None


def _plan_litter_numbers(litters):
    """Litter numbers to write, as {breeding_id: litter_number}.

    Pure decision logic — `litters` are _Litter records, not database rows.
    Mirrors the migration's backfill: a litter whose individuals were minted
    under the real grammar keeps the litter number that was issued, the rest are
    ranked chronologically per herd/year. Buckets match the unique index
    (breeding_herd_id, year of COALESCE(birth_date, breed_date + 30 days),
    litter_number).

    Three deliberate differences from the migration, all because the seed writes
    into a live dev database instead of backfilling a legacy dump:
      * only rows with litter_number IS NULL are planned — a litter numbered by
        birth registration is never renumbered, and its number stays reserved;
      * a number already taken in the herd/year falls through to the next free
        one instead of being cleared to NULL (the migration's dedupe pass).
        Several fixtures are founders that share a litter prefix without sharing
        a breeding, and NULL there is exactly the gap this function closes;
      * a mating still awaiting birth is left out — register_birth assigns (and
        overwrites) the number when the birth is registered, and the roster
        helpers need a birth_date anyway, so a number there would only occupy a
        slot in the herd/year space.
    """
    taken = defaultdict(set)
    pending = defaultdict(list)
    for litter in litters:
        bucket = _litter_bucket(litter)
        if bucket is None:
            continue  # no date at all — outside every index bucket
        if litter.litter_number is not None:
            taken[bucket].add(litter.litter_number)
        elif litter.birth_date is not None:
            pending[bucket].append(litter)

    plan = {}
    for bucket, bucket_litters in pending.items():
        herd_identifier, year = bucket
        used = taken[bucket]
        unnumbered = []
        for litter in sorted(bucket_litters, key=lambda entry: (entry.birth_date, entry.breeding_id)):
            minted = _litter_number_from_offspring(litter.offspring_numbers, herd_identifier, year)
            if minted is None or minted in used:
                unnumbered.append(litter)
                continue
            used.add(minted)
            plan[litter.breeding_id] = minted
        candidate = 1
        for litter in unnumbered:
            while candidate in used:
                candidate += 1
            used.add(candidate)
            plan[litter.breeding_id] = candidate
    return plan


def _assign_litter_numbers():
    """Give every seeded litter a litter_number. Returns how many were numbered.

    Seeded Breeding rows are inserted straight into an already-migrated
    database, so they miss both real assignment paths (register_birth and
    migrate_21_to_22) and provisional_number() then returns None for every kit
    added to them. The decision logic lives in _plan_litter_numbers; this reads
    the rows, hands it plain data and saves the plan.
    """
    breedings = {breeding.id: breeding for breeding in Breeding.select(Breeding, Herd).join(Herd)}
    offspring = defaultdict(list)
    for individual in Individual.select(Individual.number, Individual.breeding).where(
        Individual.breeding.is_null(False)
    ):
        offspring[individual.breeding_id].append(individual.number)

    plan = _plan_litter_numbers(
        _Litter(
            breeding_id=breeding.id,
            herd=breeding.breeding_herd_id.herd,
            birth_date=breeding.birth_date,
            breed_date=breeding.breed_date,
            litter_number=breeding.litter_number,
            offspring_numbers=tuple(offspring[breeding.id]),
        )
        for breeding in breedings.values()
    )
    for breeding_id, litter_number in plan.items():
        breeding = breedings[breeding_id]
        breeding.litter_number = litter_number
        breeding.save()
    return len(plan)


# ══════════════════════════════════════════════════
# Helper functions
# ══════════════════════════════════════════════════


def _herd(genebank, herd_num, name, active, contact, email, log):
    herd, created = _get_or_create(
        Herd,
        herd=herd_num,
        genebank=genebank,
        defaults={
            "herd_name": name,
            "is_active": active,
            "name": contact or "",
            "name_privacy": "authenticated",
            "email": email or "",
            "email_privacy": "authenticated" if email else "private",
        },
    )
    log(f"Herd: {herd_num} ({name})", created)
    return herd


def _user(email, password, username, fullname, roles, log):
    existing = User.select().where(User.email == email).first()
    if existing:
        log(f"User: {username}", created=False)
        return existing
    user = da.register_user(email, password, username=username, fullname=fullname, validated=True)
    for level, target in roles:
        if level == "admin":
            user.add_role(level)
        elif target is not None:
            user.add_role(level, target)
    user.save()
    log(f"User: {username} ({', '.join(level for level, _ in roles)})")
    return user


def _breeding(herd, birth_date, breed_date, father, mother, litter_size, litter_size6w, log):
    if birth_date:
        existing = (
            Breeding.select()
            .where(
                Breeding.breeding_herd_id == herd,
                Breeding.birth_date == birth_date,
                Breeding.mother == mother,
                Breeding.father == father,
            )
            .first()
        )
        if existing:
            log(f"Breeding: {herd.herd} birth={birth_date}", created=False)
            return existing
    breeding = Breeding.create(
        breeding_herd_id=herd,
        birth_date=birth_date,
        breed_date=breed_date,
        father=father,
        mother=mother,
        litter_size=litter_size,
        litter_size6w=litter_size6w,
    )
    log(f"Breeding: {herd.herd} birth={birth_date or 'pending'}")
    return breeding


def _individual(
    number,
    name,
    sex,
    herd,
    birth_date,
    father,
    mother,
    color,
    cert,
    manager,
    log,
    breeding=None,
    death_date=None,
    death_note=None,
):
    existing = Individual.select().where(Individual.number == number).first()
    if existing:
        log(f"Individual: {number}", created=False)
        return existing

    if breeding is None:
        breeding = _breeding(herd, birth_date, None, father, mother, None, None, log)

    ind = Individual.create(
        origin_herd=herd,
        number=number,
        name=name,
        sex=sex,
        breeding=breeding,
        color=color,
        certificate=cert,
        death_date=death_date,
        death_note=death_note,
    )

    if birth_date:
        _track(ind, herd, None, manager, birth_date, "BIRTH", log)

    log(f"Individual: {number} {name or '(unnamed)'} ({sex or 'unknown'})")
    return ind


def _transfer(individual, to_herd, from_herd, manager, tracking_date, log):
    _track(individual, to_herd, from_herd, manager, tracking_date, "TRANSFER", log)
    log(f"Transfer: {individual.number} {from_herd.herd} → {to_herd.herd}")


def _track(individual, herd, from_herd, manager, tracking_date, kind, log):
    existing = (
        HerdTracking.select()
        .where(
            HerdTracking.individual == individual,
            HerdTracking.herd == herd,
            HerdTracking.herd_tracking_date == tracking_date,
            HerdTracking.kind == kind,
            ht_not_voided(),
        )
        .first()
    )
    if existing:
        return existing
    return HerdTracking.create(
        individual=individual,
        herd=herd,
        from_herd=from_herd,
        signature=manager,
        herd_tracking_date=tracking_date,
        kind=kind,
        operation_id=uuid.uuid4(),
    )
