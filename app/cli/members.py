"""
Flask CLI for member registry operations.

Usage:
    flask members import <csv_path> [--dry-run | --counts-only]
    flask members link-by-herd [--apply --actor-user-id <id> --plan <value>]

`import` expects the MATR2026 paper-matrikel layout (headers matched
case-insensitively after normalization):

    G, M, Nr, Namn Efternamn, Adress, <adresskolumner>, Telefonnr, e-postadress, Bet senast, Noteringar

The address columns come in exactly two accepted layouts, decided once per
file from its header row:

- legacy: a single `Postadress` ("623 55 Visby"), split on import;
- split: `Postnummer` + `Postort` — what our own matrikel export writes.

A mixed or partial set (both layouts at once, or only one of
Postnummer/Postort) and duplicate columns are file-level errors: nothing is
written and the member-number counter is left untouched.

The raw spreadsheet export is accepted as-is: title/legend/count rows
before the header line and year-statistics footer rows (only the Nr cell
filled) are skipped.

Rules (Member Model v2 design spec):
- Rows sharing an Nr > 0 form ONE membership: first row = huvudmedlem,
  subsequent rows = familjemedlem.
- Nr = 0 rows become friexemplar memberships, one per distinct name;
  identical duplicate rows collapse into one membership with a note.
- G/M flags link herd G<Nr>/M<Nr> to the membership; a missing herd only
  logs a warning (the membership is still created).
- Merge policy: (1) member_number match means already imported, skip;
  (2) main-person name + contact email against active number-less
  memberships means the CSV row adopts that membership and sets its number.
- Both merge paths re-read the membership FOR UPDATE inside the group's
  transaction and UPDATE only the importer-owned fields they changed:
  membership_status and publication_consent are never written, so a
  re-import can never undo a deactivation or a withdrawn consent.
- A membership that has an ended person (soft-deleted, GDPR-anonymized or
  ended by a retirement), or that is inactive, is never written to: the
  whole Nr group is listed for manual review instead. Erasure works by
  setting end_date and replacing the name, so the importer cannot tell an
  erased person from a missing one and would bring back the spreadsheet's
  PII. The same check runs on an adoption candidate, and before a
  friexemplar row is created (see _erased_friexemplar_exists).
- The member-number counter is raised to the highest imported number.
- gdpr_consented_at is NEVER fabricated: MATR2026 has no consent column,
  so imported persons always have NULL.
- Import never sets Member.user and never calls the auto-link helper.
- A main member's address becomes a login address (reserve_login_address): when
  another person holds it, the whole group fails and is listed as an error.

`link-by-herd` links existing accounts to member rows through herd
ownership: the only account with role `owner` on herd G<Nr>/M<Nr> whose name
equals the name of membership Nr's main member is linked (mode "cli"). Other
cases are listed for the register manager. Plan only unless --apply.
"""

import csv
import hashlib
import logging
import re
import unicodedata
from collections import Counter

import click
from flask.cli import AppGroup
from peewee import IntegrityError, fn
from utils.database import DB_PROXY, Genebank, Herd, Member, Membership, User
from utils.herd_contact import link_herd
from utils.login_code import reserve_login_address
from utils.matrikel import (
    ANONYMIZED_FIRST_NAME,
    ANONYMIZED_LAST_NAME,
    ConfirmRequired,
    LinkError,
    link_access_delta,
    link_member_user,
    new_membership,
    normalize_postal_code,
    raise_counter_to,
    split_postal_address,
)
from utils.membership_lifecycle import Status

logger = logging.getLogger(__name__)

members_cli = AppGroup("members", help="Member registry operations.")


@members_cli.command("import")
@click.argument("csv_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--dry-run", is_flag=True, help="Print the full import plan without writing.")
@click.option(
    "--counts-only",
    is_flag=True,
    help="Run the real import in a transaction that is rolled back; print only counts, no names (#117).",
)
def import_cmd(csv_path: str, dry_run: bool, counts_only: bool) -> None:
    """Import memberships from a MATR2026 CSV file."""
    if dry_run and counts_only:
        raise click.UsageError("--dry-run och --counts-only går inte att kombinera")
    rows, errors, file_errors = _read_rows(csv_path)
    if file_errors:
        # The whole file is unusable (no header row, duplicate columns, an
        # address layout we cannot read). Abort here — before _group_rows and
        # before the counter is raised — so a rejected file leaves nothing
        # behind, not even a moved member-number high-water mark.
        for line in [f"{len(file_errors)} file error(s)"] if counts_only else file_errors:
            click.echo(f"Error: {line}", err=True)
        raise click.ClickException("filen avvisades — inga rader importerade")
    if counts_only:
        # nested atomic() blocks become savepoints: persons, links and the counter all roll back
        with DB_PROXY.atomic() as outer:
            report = _import(rows, errors, dry_run=False)
            outer.rollback()
        for line in _count_lines(report):
            click.echo(line)
        click.echo("(counts-only — rolled back, nothing written)")
    else:
        report = _import(rows, errors, dry_run)
        _print_report(report, dry_run)

    # Non-zero exit code when any rows errored — lets CI detect bad imports.
    if report["errors"]:
        if counts_only:
            raise click.ClickException(f"{len(report['errors'])} row(s) failed to import")
        for line in report["errors"]:
            click.echo(f"Error: {line}", err=True)
        raise click.ClickException(f"{len(report['errors'])} row(s) failed to import — see stderr for details")


def _import(rows: list[dict], errors: list[str], dry_run: bool) -> dict:
    """Write the groups (unless dry_run) and return the report."""
    groups, friexemplar_groups = _group_rows(rows)

    report = {
        "memberships_created": 0,
        "persons_created": 0,
        "friexemplar_created": 0,
        "matched_existing": 0,
        "merges": [],  # (nr, membership_id, main name)
        "collapses": [],  # (name, row count) — identical duplicate rows
        "conflicts": [],  # (name, row count) — same name, differing fields
        "review": [],  # (label, membership_id, reason) — ended/erased/inactive, nothing written
        "herd_warnings": [],
        "name_splits": [],  # (raw, first, last)
        "postal_review": [],  # (label, raw Postadress) — legacy value that did not parse
        "herd_links": 0,
        "contact_cases": Counter(),  # (row, case) -> herds linked, from link_herd
        "errors": errors,
    }
    for row in rows:
        report["name_splits"].append((row["name"], row["first_name"], row["last_name"]))
        if row["postal_needs_review"]:
            label = f"Nr {row['nr']}" if row["nr"] else row["name"]
            report["postal_review"].append((label, row["postal_raw"]))

    # Raise the counter to the highest imported number BEFORE writing any
    # group, in its own committed transaction. If the
    # import then crashes mid-way, the counter already sits at the high-water
    # mark, so application approval never allocates a number that collides
    # with an imported one — a crash only leaves unused gap numbers, which
    # high-water semantics tolerate. Raising the counter AFTER the groups
    # (the old order) left a window where the counter trailed existing
    # numbers and approval repeatedly allocated colliding numbers.
    if groups and not dry_run:
        with DB_PROXY.atomic():
            raise_counter_to(max(groups))

    for nr, group in groups.items():
        try:
            _import_membership_group(nr, group, dry_run, report)
        except Exception as e:  # pylint: disable=broad-exception-caught
            report["errors"].append(f"Nr {nr}: {e}")

    for name_key, group in friexemplar_groups.items():
        try:
            _import_friexemplar_group(name_key, group, dry_run, report)
        except Exception as e:  # pylint: disable=broad-exception-caught
            report["errors"].append(f"friexemplar {name_key!r}: {e}")
    return report


LEGACY_LAYOUT = "legacy"  # single "Postadress" column (paper matrikel)
SPLIT_LAYOUT = "split"  # "Postnummer" + "Postort"
ADDRESS_HEADERS = ("postadress", "postnummer", "postort")


def _header_identity(raw: str) -> str:
    """Canonical identity for duplicate detection: normalised header with every
    non-alphanumeric stripped — 'Post-ort', 'post_ort' and 'Postort' collide."""
    return re.sub(r"[^0-9a-zåäö]", "", _normalize_header(raw))


def _duplicate_headers(cells: list[str]) -> list[str]:
    seen: dict[str, tuple[int, str]] = {}
    errors = []
    for position, raw in enumerate(cells, start=1):
        identity = _header_identity(raw)
        if not identity:
            continue
        if identity in seen:
            first_position, first_raw = seen[identity]
            errors.append(f"dubblettkolumn: {first_raw!r} (kolumn {first_position}) och {raw!r} (kolumn {position})")
        else:
            seen[identity] = (position, raw)
    return errors


def _detect_layout(normalized: list[str]) -> str:
    keys = set(normalized)
    has_legacy, has_code, has_city = ("postadress" in keys), ("postnummer" in keys), ("postort" in keys)
    if has_legacy and not has_code and not has_city:
        return LEGACY_LAYOUT
    if has_code and has_city and not has_legacy:
        return SPLIT_LAYOUT
    present = ", ".join(k for k in ADDRESS_HEADERS if k in keys) or "ingen adresskolumn"
    raise ValueError(
        f"ogiltig adresslayout i rubrikraden ({present}): använd antingen 'Postadress' "
        "eller både 'Postnummer' och 'Postort'"
    )


def _read_rows(csv_path: str) -> tuple[list[dict], list[str], list[str]]:
    """Parse the CSV into normalized row dicts.

    Returns (rows, row_errors, file_errors). file_errors (no header row,
    duplicate columns, an address layout that is neither the legacy
    'Postadress' nor the split 'Postnummer'+'Postort') mean NOTHING may be
    written — the caller aborts before touching the counter.

    Lines before the header row (title/legend/count preamble in the raw
    export) and filler rows with at most the Nr cell filled (the
    year-statistics footer) are skipped. A row carrying any other data
    without a name still errors — that is corruption, not filler.
    """
    rows, errors, file_errors = [], [], []
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        fieldnames = None
        layout = None
        for cells in reader:
            if fieldnames is None:
                normalized = [_normalize_header(c) for c in cells]
                if {"nr", "namn_efternamn"} <= set(normalized):
                    file_errors.extend(_duplicate_headers(cells))
                    try:
                        layout = _detect_layout(normalized)
                    except ValueError as e:
                        file_errors.append(str(e))
                    if file_errors:
                        return [], [], file_errors
                    fieldnames = normalized
                continue
            # strict=False: ragged rows are expected — extra cells drop, short rows leave fields empty
            raw = dict(zip(fieldnames, cells, strict=False))
            values = {k: (v or "").strip() for k, v in raw.items()}
            if not values.get("namn_efternamn") and not any(v for k, v in values.items() if k != "nr"):
                continue
            try:
                rows.append(_parse_row(raw, layout))
            except ValueError as e:
                errors.append(f"row {reader.line_num}: {e}")
    if fieldnames is None:
        file_errors.append("hittade ingen rubrikrad (med kolumnerna 'Nr' och 'Namn Efternamn') i filen")
    return rows, errors, file_errors


def _parse_row(raw: dict[str, str], layout: str) -> dict:
    """Map one MATR2026 row onto membership/person fields.

    Raises ValueError on malformed rows — the caller counts those as errors.
    """
    # csv.DictReader emits None as the key for cells past the declared
    # header — those have no semantics, drop them.
    row = {_normalize_header(k): (v or "").strip() for k, v in raw.items() if k is not None}

    name = " ".join(row.get("namn_efternamn", "").split())
    if not name:
        raise ValueError("kolumnen 'Namn Efternamn' saknas eller är tom")

    nr_raw = row.get("nr", "")
    if nr_raw == "":
        raise ValueError("kolumnen 'Nr' saknas eller är tom")
    try:
        nr = int(nr_raw)
    except ValueError as exc:
        raise ValueError(f"ogiltigt Nr: {nr_raw!r}") from exc
    if nr < 0:
        raise ValueError(f"ogiltigt Nr: {nr_raw!r}")

    if layout == SPLIT_LAYOUT:
        try:
            postal_code = normalize_postal_code(row.get("postnummer") or None)
        except ValueError as exc:
            raise ValueError(f"ogiltigt postnummer: {row.get('postnummer')!r}") from exc
        city = row.get("postort") or None
        postal_raw, needs_review = None, False
    else:
        postal_raw = row.get("postadress") or None
        postal_code, city = split_postal_address(postal_raw)
        needs_review = city is not None and postal_code is None
    if city is not None and len(city) > 100:
        # After BOTH branches — a non-parsing legacy Postadress lands whole in city.
        raise ValueError("Postort får vara högst 100 tecken")

    first_name, last_name = _split_name(name, treat_as_org=(nr == 0))
    return {
        "nr": nr,
        "name": name,
        "first_name": first_name,
        "last_name": last_name,
        "g": bool(row.get("g")),
        "m": bool(row.get("m")),
        "address": row.get("adress") or None,
        "postal_code": postal_code,
        "city": city,
        "postal_raw": postal_raw,
        "postal_needs_review": needs_review,
        "phone": row.get("telefonnr") or None,
        "email": (row.get("e_postadress") or "").lower() or None,
        "payment_note": row.get("bet_senast") or None,
        "notes": row.get("noteringar") or None,
    }


def _normalize_header(raw: str) -> str:
    """Lowercase + strip + convert spaces/dashes to underscores."""
    return raw.lower().strip().replace(" ", "_").replace("-", "_")


def _split_name(name: str, treat_as_org: bool) -> tuple[str, str]:
    """Last token = last name. Org rows (Nr=0) and space-less names go whole into last_name."""
    if treat_as_org or " " not in name:
        return "", name
    first, _, last = name.rpartition(" ")
    return first, last


def _group_rows(rows: list[dict]) -> tuple[dict[int, list[dict]], dict[str, list[dict]]]:
    """Nr>0 rows group by Nr (one membership); Nr=0 rows group by distinct name."""
    groups: dict[int, list[dict]] = {}
    friexemplar: dict[str, list[dict]] = {}
    for row in rows:
        if row["nr"] > 0:
            groups.setdefault(row["nr"], []).append(row)
        else:
            friexemplar.setdefault(row["name"].lower(), []).append(row)
    return groups, friexemplar


def _first_value(group: list[dict], key: str):
    """First non-empty value for a membership field across the group's rows."""
    for row in group:
        if row[key]:
            return row[key]
    return None


def _find_adoptable_membership(main: dict):
    """Merge rule 2: main-person name + contact email against active number-less memberships."""
    if not main["email"]:
        return None
    candidates = (
        Member.select(Member, Membership)
        .join(Membership)
        .where(
            Member.role == "huvudmedlem",
            Member.end_date.is_null(True),
            Membership.member_number.is_null(True),
            Membership.membership_status == Status.ACTIVE,
            fn.LOWER(Member.email) == main["email"],
        )
    )
    for person in candidates:
        if _main_person_matches(person, main):
            return person.membership
    return None


def _main_person_matches(person, main: dict) -> bool:
    existing_name = " ".join(f"{person.first_name} {person.last_name}".split()).lower()
    return existing_name == main["name"].lower()


def _still_adoptable(row: Membership, main: dict) -> bool:
    """Re-check the adoption predicate on the LOCKED candidate.

    Between the lookup and the lock an admin may have numbered the row or
    swapped its huvudmedlem. Writing the CSV number over an administrative one,
    or onto somebody else's membership, would be silent data loss — so the row
    must still be numberless and still fronted by the huvudmedlem whose name +
    e-mail matched. A deactivation or an erasure in between is not decided
    here: _manual_review_reason parks such a candidate, because discarding it
    would let the creation branch bring the erased person back.
    """
    if row.member_number is not None:
        return False
    mains = Member.select().where(
        Member.membership == row,
        Member.role == "huvudmedlem",
        Member.end_date.is_null(True),
        fn.LOWER(Member.email) == main["email"],
    )
    return any(_main_person_matches(person, main) for person in mains)


def _manual_review_reason(membership) -> str | None:
    """Why a re-import must not write to this membership, or None.

    anonymize_person, soft_delete_person and retire_membership all end a person
    by setting end_date, and anonymization also replaces the name, so the
    importer cannot tell an erased or removed person from one the spreadsheet
    merely lists: it would create them again with the original name, e-mail and
    phone, and refill an address that the erasure cleared. Any ended person
    parks the whole group, checked before the first write. So does an inactive
    membership: add_person refuses to add people to one, so the importer must not.
    """
    if Member.select().where(Member.membership == membership, Member.end_date.is_null(False)).exists():
        return "avslutade eller borttagna personer"
    if membership.membership_status == "inactive":
        return "inaktivt medlemskap"
    return None


def _erased_friexemplar_exists() -> bool:
    """True when a numberless or friexemplar membership has an anonymized contact.

    Erasure replaces the name, and a friexemplar has no member number to find it
    by, so a Nr=0 row that matches nothing cannot be told apart from the erased
    contact. Such rows are parked until someone looks at them. The scan
    deliberately ignores status and number separately: an admin may have
    activated the friexemplar or numbered it before the erasure.
    """
    return (
        Member.select()
        .join(Membership)
        .where(
            Membership.member_number.is_null(True) | (Membership.membership_status == "friexemplar"),
            Member.first_name == ANONYMIZED_FIRST_NAME,
            Member.last_name == ANONYMIZED_LAST_NAME,
        )
        .exists()
    )


def _import_membership_group(nr: int, group: list[dict], dry_run: bool, report: dict) -> None:
    main = group[0]
    fields = {
        "address": _first_value(group, "address"),
        "postal_code": _first_value(group, "postal_code"),
        "city": _first_value(group, "city"),
        "payment_note": _first_value(group, "payment_note"),
        "notes": _first_value(group, "notes"),
    }

    existing = Membership.get_or_none(Membership.member_number == nr)
    with DB_PROXY.atomic():
        if existing is not None and not dry_run:
            # `existing` was read BEFORE this transaction. Re-resolve it BY
            # NUMBER under the row lock: the reconcile below
            # writes onto the locked row, so an admin deactivation or a consent
            # withdrawal that committed in between stands — and a renumber that
            # took `nr` away from this row drops the group into the adoption /
            # creation branches instead of reconciling it, herd links included,
            # onto the wrong membership.
            existing = _locked_membership_by_number(nr)
        adopted = None
        if existing is None:
            adopted = _find_adoptable_membership(main)
        if adopted is not None and not dry_run:
            # member_number writer: counter row FIRST, then the membership —
            # the order every other writer uses (approve_application,
            # PATCH /v2/memberships). Saving first and locking after would
            # invert it and can deadlock against a concurrent approval.
            raise_counter_to(nr)
            adopted = _locked_membership(adopted.id)
            if _manual_review_reason(adopted) is None and not _still_adoptable(adopted, main):
                # Numbered or re-fronted since the lookup: the
                # group is a new membership now — created below, still under
                # the counter lock. A candidate whose main person was erased or
                # retired in between is NOT discarded: it is parked below.
                adopted = None
        membership = existing if existing is not None else adopted
        if membership is not None:
            reason = _manual_review_reason(membership)
            if reason is not None:
                report["review"].append((f"Nr {nr}", membership.id, reason))
                return
        if existing is not None:
            # Merge rule 1: a membership with this number already exists.
            # Re-import is idempotent but NOT a no-op skip: it reconciles — fills only still-empty membership
            # fields, ensures the main person, then falls through to add
            # family rows an interrupted earlier run missed and retry herd
            # links whose herd has since been created. Never overwrites a
            # non-empty stored field.
            report["matched_existing"] += 1
            membership = existing
            if not dry_run:
                _fill_empty_fields(membership, fields)
                _ensure_main_person(membership, main)
        elif adopted is not None:
            report["merges"].append((nr, adopted.id, main["name"]))
            membership = adopted
            if not dry_run:
                changed = {} if membership.member_number == nr else {"member_number": nr}
                # Adoption keeps its merge semantics: a CSV value wins over the
                # stored one. Only the values that actually differ are written.
                for key, value in fields.items():
                    if value is not None and getattr(membership, key) != value:
                        changed[key] = value
                _save_importer_fields(membership, changed)
        else:
            report["memberships_created"] += 1
            report["persons_created"] += 1
            membership = None
            if not dry_run:
                membership = new_membership(Status.ACTIVE, member_number=nr, **fields)
                _create_main(membership, main)
        _add_family_members(membership, group[1:], dry_run, report)
        _link_flag_herds(nr, group, membership, dry_run, report)


def _locked_membership(membership_id: int) -> Membership:
    """Re-read a membership FOR UPDATE inside the caller's open transaction."""
    return Membership.select().where(Membership.id == membership_id).for_update().get()


def _locked_membership_by_number(nr: int) -> Membership | None:
    """The membership that owns `nr` right now, FOR UPDATE, or None.

    Locking on the number rather than on a remembered id is what makes a
    concurrent renumber safe: PostgreSQL re-checks the predicate once the
    other transaction commits, so a row that lost `nr` is simply not found.
    """
    return Membership.select().where(Membership.member_number == nr).for_update().get_or_none()


def _save_importer_fields(membership, changed: dict) -> None:
    """UPDATE only the columns the importer owns AND actually changed.

    The row lock serialises the write, but a full-row save would still push
    every attribute the instance carries — including membership_status and
    publication_consent, which the importer never writes. A re-import racing an
    admin deactivation or a member's consent withdrawal would silently undo it:
    the membership flips back to active (its linked huvudmedlem regains herd
    access) or the withdrawn consent reappears in the Koharen export.
    Nothing changed → no UPDATE at all.
    """
    if not changed:
        return
    for key, value in changed.items():
        setattr(membership, key, value)
    membership.save(only=[getattr(Membership, key) for key in changed] + [Membership.updated_at])


def _fill_empty_fields(membership, fields: dict) -> None:
    """Reconciliation: set only membership fields that are currently NULL/empty
    from the CSV — never overwrite a non-empty stored value."""
    changed = {key: value for key, value in fields.items() if value is not None and not getattr(membership, key)}
    _save_importer_fields(membership, changed)


def _ensure_main_person(membership, main: dict) -> None:
    """Reconciliation: create the huvudmedlem if a prior interrupted run left
    the membership without one; a matching active huvudmedlem is left as is."""
    has_main = (
        Member.select()
        .where(
            Member.membership == membership,
            Member.role == "huvudmedlem",
            Member.end_date.is_null(True),
        )
        .exists()
    )
    if not has_main:
        _create_main(membership, main)


def _create_main(membership, row: dict) -> None:
    """The main member from a CSV row. Her address becomes a login address: AddressTaken (the group's error, nothing
    of the group written) when another person holds it."""
    person = Member.create(
        membership=membership,
        role="huvudmedlem",
        first_name=row["first_name"],
        last_name=row["last_name"],
        email=row["email"],
        phone=row["phone"],
    )
    reserve_login_address(person.email, person.id)


def _add_family_members(membership, rows: list[dict], dry_run: bool, report: dict) -> None:
    """Subsequent rows in an Nr group become familjemedlem person rows.

    membership is None on the dry-run new-membership path — nothing to
    dedupe against, every row counts as a would-be person.
    """
    for row in rows:
        if membership is not None:
            exists = (
                Member.select()
                .where(
                    Member.membership == membership,
                    Member.end_date.is_null(True),
                    fn.LOWER(Member.first_name) == row["first_name"].lower(),
                    fn.LOWER(Member.last_name) == row["last_name"].lower(),
                )
                .exists()
            )
            if exists:
                continue
        report["persons_created"] += 1
        if not dry_run and membership is not None:
            Member.create(
                membership=membership,
                role="familjemedlem",
                first_name=row["first_name"],
                last_name=row["last_name"],
                email=row["email"],
                phone=row["phone"],
            )


def _link_flag_herds(nr: int, group: list[dict], membership, dry_run: bool, report: dict) -> None:
    """G/M flags link herd G<Nr>/M<Nr> with link_herd, which compares the herd's contact with the register (#117).
    A missing herd is a warning, never a row skip."""
    for key, prefix in (("g", "G"), ("m", "M")):
        if not any(row[key] for row in group):
            continue
        code = f"{prefix}{nr}"
        herd = Herd.get_or_none(Herd.herd == code)
        if herd is None:
            report["herd_warnings"].append(f"herd {code} not found — flag ignored")
            continue
        if herd.membership_id is not None:
            if membership is not None and herd.membership_id == membership.id:
                continue  # already linked (re-import)
            report["herd_warnings"].append(f"herd {code} already linked to membership {herd.membership_id}")
            continue
        if dry_run or membership is None:
            report["herd_links"] += 1
            continue
        cases = link_herd(herd.id, membership.id, herd_code=code)
        if cases is None:  # linked or renumbered by someone else since the read above
            report["herd_warnings"].append(f"herd {code} changed or linked meanwhile — not linked")
            continue
        report["herd_links"] += 1
        report["contact_cases"].update(cases.items())


_FRIEXEMPLAR_COMPARE_KEYS = (
    "g",
    "m",
    "first_name",
    "last_name",
    "address",
    # The normalised halves, never postal_raw/postal_needs_review (report
    # metadata): "62355 Visby" and "623 55 Visby" are the same address.
    "postal_code",
    "city",
    "phone",
    "email",
    "payment_note",
    "notes",
)


def _rows_identical(rows: list[dict]) -> bool:
    """True iff every row matches the first across all import fields."""
    first = tuple(rows[0][k] for k in _FRIEXEMPLAR_COMPARE_KEYS)
    return all(tuple(r[k] for k in _FRIEXEMPLAR_COMPARE_KEYS) == first for r in rows[1:])


def _import_friexemplar_group(name_key: str, group: list[dict], dry_run: bool, report: dict) -> None:
    """Nr=0: one friexemplar membership per distinct name, one contact person.

    Duplicate rows that are IDENTICAL across every import field (extra
    magazine copies in the paper file) collapse into one membership with a
    note. Same-name rows that DIFFER (e.g. an organisation with several
    distinct contact persons) are NOT synthesized into a combined row that
    existed in no source row: the FIRST row is
    imported verbatim and the divergent rows are reported as conflicts for
    manual resolution."""
    # Idempotent re-import: a friexemplar contact with this name exists. A retired
    # friexemplar (status inactive, no number) or an ended contact counts as
    # present too, but is reported for review instead of being created again.
    existing = (
        Member.select(Member, Membership)
        .join(Membership)
        .where(
            (Membership.membership_status == "friexemplar")
            | ((Membership.membership_status == "inactive") & Membership.member_number.is_null(True))
        )
    )
    matches = [
        person for person in existing if " ".join(f"{person.first_name} {person.last_name}".split()).lower() == name_key
    ]
    if matches:
        if any(p.end_date is None and p.membership.membership_status == "friexemplar" for p in matches):
            report["matched_existing"] += 1
        else:
            report["review"].append((f"friexemplar {group[0]['name']}", matches[0].membership_id, "avslutad kontakt"))
        return
    if _erased_friexemplar_exists():
        report["review"].append((f"friexemplar {group[0]['name']}", None, "en raderad kontakt kan inte uteslutas"))
        return

    # First row verbatim — no cross-row field mixing.
    row = group[0]
    notes = row["notes"]
    if len(group) > 1:
        if _rows_identical(group):
            collapse_note = f"Import: {len(group)} identiska rader ihopslagna till ett medlemskap"
            notes = f"{notes} — {collapse_note}" if notes else collapse_note
            report["collapses"].append((row["name"], len(group)))
        else:
            conflict_note = (
                f"Import: {len(group)} rader med samma namn men olika uppgifter — "
                "första raden importerad, övriga kräver manuell granskning"
            )
            notes = f"{notes} — {conflict_note}" if notes else conflict_note
            report["conflicts"].append((row["name"], len(group)))

    report["friexemplar_created"] += 1
    if dry_run:
        return

    with DB_PROXY.atomic():
        membership = new_membership(
            Status.FRIEXEMPLAR,
            member_number=None,
            address=row["address"],
            postal_code=row["postal_code"],
            city=row["city"],
            payment_note=row["payment_note"],
            notes=notes,
        )
        _create_main(membership, row)


def _leftover_numberless(adopted_ids: set[int]) -> list[tuple[int, str]]:
    """Active number-less memberships left after import — manual reconciliation list."""
    leftovers = []
    query = (
        Membership.select()
        .where(
            Membership.member_number.is_null(True),
            Membership.membership_status == Status.ACTIVE,
        )
        .order_by(Membership.id)
    )
    for membership in query:
        if membership.id in adopted_ids:
            continue  # dry-run: adoption would have set a number
        main = (
            Member.select()
            .where(
                Member.membership == membership,
                Member.role == "huvudmedlem",
                Member.end_date.is_null(True),
            )
            .first()
        )
        name = f"{main.first_name} {main.last_name}".strip() if main else "(no main person)"
        leftovers.append((membership.id, name))
    return leftovers


def _print_report(report: dict, dry_run: bool) -> None:
    if dry_run:
        click.echo("Name splits:")
        for raw, first, last in report["name_splits"]:
            marker = " (whole name kept as last_name)" if not first else ""
            click.echo(f"  {raw!r} -> first={first!r}, last={last!r}{marker}")

    if report["merges"]:
        click.echo("Merges (adopted memberships):")
        for nr, membership_id, name in report["merges"]:
            click.echo(f"  Nr {nr} -> existing membership {membership_id} ({name})")

    if report["collapses"]:
        click.echo("Collapsed friexemplar duplicates:")
        for name, count in report["collapses"]:
            click.echo(f"  {name}: {count} rows -> 1 membership")

    if report["conflicts"]:
        click.echo("Conflicting same-name friexemplar rows (first imported, rest need review):")
        for name, count in report["conflicts"]:
            click.echo(f"  {name}: {count} rows differ — {count - 1} row(s) skipped", err=True)

    if report["review"]:
        click.echo("Manual review (ended, erased or inactive — nothing was written for these):")
        for label, membership_id, reason in report["review"]:
            click.echo(f"  {label} -> membership {membership_id or '-'}: {reason}")

    if report["postal_review"]:
        click.echo("Postadress kräver granskning (hela värdet lagt i Postort, postnummer tomt):")
        for label, raw in report["postal_review"]:
            click.echo(f"  {label}: {raw!r}")

    for warning in report["herd_warnings"]:
        click.echo(f"  warning: {warning}", err=True)

    adopted_ids = {membership_id for _, membership_id, _ in report["merges"]}
    leftovers = _leftover_numberless(adopted_ids)
    if leftovers:
        click.echo("Active memberships without member number (manual reconciliation):")
        for membership_id, name in leftovers:
            click.echo(f"  membership {membership_id}: {name}")

    for line in _count_lines(report):
        click.echo(line)
    if dry_run:
        click.echo("(dry-run — no writes performed)")


def _count_lines(report: dict) -> list[str]:
    """The report's counts, without names, addresses or herd codes: all that --counts-only prints."""
    return [
        f"Memberships created: {report['memberships_created']}, "
        f"Persons created: {report['persons_created']}, "
        f"Friexemplar created: {report['friexemplar_created']}, "
        f"Merges: {len(report['merges'])}, "
        f"Matched existing (skipped): {report['matched_existing']}, "
        f"Manual review: {len(report['review'])}, "
        f"Herd links: {report['herd_links']}, "
        f"Errors: {len(report['errors'])}",
        f"Herd warnings: {len(report['herd_warnings'])}",
        *(f"Contact {field} {case}: {n}" for (field, case), n in sorted(report["contact_cases"].items())),
    ]


@members_cli.command("link-by-herd")
@click.option("--apply", "apply_links", is_flag=True, help="Write the links (default prints the plan only).")
@click.option(
    "--actor-user-id",
    type=int,
    default=None,
    help="Admin/matrikel_admin user recorded as audit actor (required with --apply).",
)
@click.option("--plan", "plan_value", default=None, help="Kontrollvärde från planen du läst (required with --apply).")
def link_by_herd_cmd(apply_links: bool, actor_user_id: int | None, plan_value: str | None) -> None:
    """Link accounts to the main member of the membership whose herd they own.

    The only account with role `owner` on herd G<Nr>/M<Nr> (tied to membership Nr) whose name equals the
    name of membership Nr's main member is proposed as that member's account.
    NEITHER THE NAME NOR THE ACCOUNT'S E-MAIL IS PROOF: the account holder can
    edit both, and so can a genebank manager, who can also hand out `owner`.
    The Google address was verified at the Google sign-in that stored it; a
    later sign-in or a new Google link may not have replaced it. Read every
    printed pair first.
    Without --apply nothing is written; the plan ends with a "Kontrollvärde"
    (a hash of the printed pairs). --apply needs that value in --plan: the plan
    is recomputed and, if it no longer gives the same value, the run stops
    before the first write and prints the new plan. Everything else is listed
    for the register manager. Each link commits on its own (mode "cli").
    """
    actor = None
    if apply_links:
        if actor_user_id is None:
            raise click.UsageError("--apply kräver --actor-user-id <id> (auditloggens aktör)")
        if plan_value is None:
            raise click.UsageError("--apply kräver --plan <kontrollvärde> från planen du har läst")
        actor = User.get_or_none(User.id == actor_user_id)
        if actor is None or not actor.is_active or not (actor.is_admin or actor.is_matrikel_admin):
            raise click.UsageError(
                f"--actor-user-id {actor_user_id}: måste vara ett aktivt konto med rollen admin eller matrikel_admin"
            )

    to_link, listed, already = _plan_herd_links()
    lines = {id(pair): _pair_line(*pair) for pair in to_link}
    value = hashlib.sha256("\n".join(sorted(lines.values())).encode()).hexdigest()[:16]
    if apply_links and plan_value != value:
        _echo_plan("Att koppla", [lines[id(p)] for p in to_link], listed, already)
        click.echo(f"Kontrollvärde: {value}")
        raise click.ClickException(
            "planen har ändrats sedan du läste den — läs den nya planen ovan och kör om med dess värde"
        )

    linked = []
    for pair in to_link:
        try:
            if apply_links:
                link_member_user(pair[0].id, pair[1].id, actor=actor, mode="cli")
        except (ConfirmRequired, LinkError, IntegrityError) as exc:
            listed.append((pair[2], f"länkningen avvisades ({type(exc).__name__}: {_q(exc)})"))
        else:
            linked.append(lines[id(pair)])

    _echo_plan("Kopplade" if apply_links else "Att koppla", linked, listed, already)
    if not apply_links:
        click.echo(f"Kontrollvärde: {value}")
        click.echo("(endast plan — läs paren ovan, inget skrevs; kör om med --apply --plan <kontrollvärde>)")


def _pair_line(main, user, codes) -> str:
    return f"{'/'.join(codes)}: {_pair_detail(main, user)}"


def _echo_plan(heading: str, pair_lines: list[str], listed: list, already: int) -> None:
    click.echo(f"{heading}: {len(pair_lines)}, Redan kopplade: {already}, Till granskning: {len(listed)}")
    for line in pair_lines:
        click.echo(f"  {line}")
    if listed:
        click.echo("Till granskning:")
        for codes, reason in listed:
            click.echo(f"  {'/'.join(codes)}: {reason}")


def _norm_name(name: str | None) -> str:
    # NFC: "Å" typed as one character and as A with a combining ring are the same name.
    return " ".join(unicodedata.normalize("NFC", name or "").split()).casefold()


def _q(text) -> str:
    """Free text in quotes; backslash, quote, non-printable and combining characters as visible escapes (NFC first)."""
    if text is None:
        return "-"
    out = []
    for char in unicodedata.normalize("NFC", str(text)):
        if char in '\\"':
            out.append("\\" + char)
        elif not char.isprintable() or unicodedata.category(char) in ("Mn", "Me"):
            out.append(char.encode("unicode_escape").decode())
        else:
            out.append(char)
    return '"' + "".join(out) + '"'


def _pair_detail(main, user) -> str:
    """Ids first, then the free text in quotes. The account's e-mail is unverified; the Google address was verified
    when it was stored, at a Google sign-in."""
    return (
        f"medlem {main.id} -> konto {user.id} | "
        f"medlem: {_q(f'{main.first_name} {main.last_name}'.strip())} {_q(main.email)} | "
        f"konto: namn {_q(user.fullname)}, användarnamn {_q(user.username)}, "
        f"e-post (overifierad) {_q(user.email)}, senast sparade Google-adress {_q(user.google_email)}"
    )


def _owner_index() -> tuple[dict[int, dict[int, User]], set[int]]:
    """Herd id -> {user id: user} with role owner, and the users with an incomplete owner role."""
    owners: dict[int, dict[int, User]] = {}
    incomplete: set[int] = set()
    for user in User.select().order_by(User.id):
        for role in user.privileges:
            if not isinstance(role, dict) or "level" not in role:
                incomplete.add(user.id)  # link_access_delta reads role["level"]
                continue
            if role["level"] != "owner":
                continue
            herd_id = role.get("herd")
            if isinstance(herd_id, str) and re.fullmatch(r"[0-9]+", herd_id):
                herd_id = int(herd_id)  # older rows may store the id as a string
            if isinstance(herd_id, bool) or not isinstance(herd_id, int):
                incomplete.add(user.id)
                continue
            owners.setdefault(herd_id, {})[user.id] = user
    return owners, incomplete


def _plan_herd_links() -> tuple[list, list, int]:
    """Decide every link first: returns (to_link [(main, user, codes)], listed [(codes, reason)], already)."""
    owners, incomplete = _owner_index()
    memberships = {m.member_number: m for m in Membership.select().where(Membership.member_number.is_null(False))}
    herds_by_code: dict[str, list] = {}
    for herd in Herd.select(Herd, Genebank).join(Genebank):
        found = re.fullmatch(r"([GM])([1-9][0-9]*)", herd.herd or "")
        # The prefix names the genebank by its initial, as in data_access._genebank_letters.
        if found and herd.genebank.name[:1].upper() == found.group(1):
            herds_by_code.setdefault(herd.herd, []).append(herd)

    listed: list = []
    already: set[tuple[int, int]] = set()
    pairs: dict[tuple[int, int], list] = {}  # (main id, user id) -> [main, user, codes]
    possible: set[tuple[int, int]] = set()  # every name-matching owner: a counterpart, linked only through pairs
    # Counterparts are counted in one place and before anything is filtered or sorted out: for every herd row
    # that has an owner, whatever its code, genebank or state, every person left in the membership the row is
    # stored on, and in the one its code's number names, who has an owner's name.
    for herd in Herd.select():
        herd_owners = owners.get(herd.id)
        if not herd_owners:
            continue
        # One number, whatever stands around it ("M901 " too); a leading zero names no membership.
        number = re.fullmatch(r"[^0-9]*([1-9][0-9]*)[^0-9]*", herd.herd or "")
        named = memberships.get(int(number.group(1))) if number else None
        behind = {herd.membership_id, getattr(named, "id", None)} - {None}
        for person in Member.select().where(Member.membership.in_(behind), Member.end_date.is_null(True)):
            wanted = _norm_name(f"{person.first_name} {person.last_name}")
            possible |= {
                (person.id, uid) for uid, u in herd_owners.items() if wanted and _norm_name(u.fullname) == wanted
            }
    for code in sorted(herds_by_code, key=lambda c: (int(c[1:]), c[0])):
        herds = herds_by_code[code]
        owner_users = {uid: u for h in herds for uid, u in owners.get(h.id, {}).items()}
        not_inactive = any(h.is_active is not False for h in herds)
        membership = memberships.get(int(code[1:]))
        active = membership is not None and membership.membership_status == Status.ACTIVE
        main = None
        if active:
            main = (
                Member.select()
                .where(Member.membership == membership, Member.role == "huvudmedlem", Member.end_date.is_null(True))
                .first()
            )

        if len(herds) > 1:
            listed.append(([code], "flera besättningar har samma kod"))
        elif herds[0].membership_id not in (None, getattr(membership, "id", None)):
            listed.append(([code], "besättningen tillhör ett annat medlemskap"))
        elif not active:
            if owner_users and not_inactive:
                listed.append(([code], "inget aktivt medlemskap har det numret"))
        elif main is None:
            if owner_users and not_inactive:
                listed.append(([code], "medlemskapet har ingen kvarvarande huvudmedlem"))
        elif not owner_users:
            listed.append(([code], "inget konto har rollen ägare på besättningen"))
        elif len(owner_users) > 1:
            listed.append(([code], "flera konton har rollen ägare på besättningen"))
        elif herds[0].membership_id is None:  # the import ties the herd when the matrikel row is marked G/M
            listed.append(([code], "besättningen är inte knuten till medlemskapet (matrikelraden saknar markeringen)"))
        else:
            _check_owner(code, main, next(iter(owner_users.values())), incomplete, listed, already, pairs)

    # Several possible links for one member or one account: none of them is made.
    by_main, by_user = {}, {}
    for key in pairs.keys() | possible:
        by_main.setdefault(key[0], []).append(key)
        by_user.setdefault(key[1], []).append(key)
    to_link = []
    for key, (main, user, codes) in pairs.items():
        if len(by_main[key[0]]) > 1 or len(by_user[key[1]]) > 1:
            listed.append((codes, f"flera möjliga kopplingar ({_pair_detail(main, user)})"))
        elif link_access_delta(main, user):
            listed.append((codes, "länken skulle ge kontot åtkomst till fler besättningar"))
        else:
            to_link.append((main, user, codes))
    return to_link, listed, len(already)


def _check_owner(code, main, user, incomplete, listed, already, pairs) -> None:
    """One herd with one owner account and one active main member: already done, listed or a candidate pair."""
    if main.user_id == user.id:
        already.add((main.id, user.id))
    elif user.id in incomplete:
        listed.append(([code], "kontots ägarroll är ofullständig"))
    elif not user.is_active:
        listed.append(([code], "kontot är inaktivt"))
    elif not _norm_name(user.fullname) or _norm_name(user.fullname) != _norm_name(
        f"{main.first_name} {main.last_name}"
    ):
        listed.append(([code], "namnet skiljer sig mellan kontot och huvudmedlemmen"))
    elif (
        sum(
            _norm_name(f"{m.first_name} {m.last_name}") == _norm_name(user.fullname)
            for m in Member.select().where(Member.membership == main.membership_id, Member.end_date.is_null(True))
        )
        > 1
    ):
        listed.append(([code], "flera personer i medlemskapet har kontots namn"))
    elif main.user_id is not None:
        listed.append(([code], "huvudmedlemmen är redan kopplad till ett annat konto"))
    elif Member.select().where(Member.user == user).exists():
        listed.append(([code], "kontot är redan kopplat till en annan medlem"))
    else:
        pairs.setdefault((main.id, user.id), [main, user, []])[2].append(code)
